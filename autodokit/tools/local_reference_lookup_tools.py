"""本地参考文献清单检索与占位补录工具。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from autodokit.path_compat import resolve_portable_path
from autodokit.tools.atomic.log_aok import append_aok_log_event, resolve_aok_log_db_path
from autodokit.tools.bibliodb import build_cite_key, clean_title_text, literature_insert_placeholder, literature_match, parse_reference_text
from autodokit.tools.bibliodb_sqlite import load_literatures_df
from autodokit.tools.contentdb_sqlite import connect_sqlite, infer_workspace_root_from_content_db, init_content_db, resolve_content_db_path
from autodokit.tools.reference_citation_tools import build_reference_quality_summary


REFERENCE_SPLIT_PATTERN = re.compile(r"^\s*(?:\[(\d+)\]|［(\d+)］|(\d+)\s*[.、．])\s*(.*)$")
REFERENCE_HEADING_PATTERN = re.compile(r"^\s*(?:参考文献|references?)\s*$", re.IGNORECASE)


def _stringify(value: Any) -> str:
    """把任意值转成去空白字符串。"""

    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _split_reference_list_text(reference_list_text: str) -> List[Dict[str, Any]]:
    """把参考文献清单文本拆为单条条目。

    Args:
        reference_list_text: 原始参考文献清单文本。

    Returns:
        单条参考文献字典列表。每项包含 ref_index 与 reference_text。

    Raises:
        ValueError: 输入为空时抛出。

    Examples:
        >>> rows = _split_reference_list_text("[1] 张三. 标题[J]. 2024.\n[2] 李四. 标题[J]. 2025.")
        >>> len(rows)
        2
    """

    raw_text = _stringify(reference_list_text)
    if not raw_text:
        raise ValueError("reference_list_text 不能为空")

    lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    entries: List[Dict[str, Any]] = []
    current_index = ""
    current_parts: List[str] = []

    def flush() -> None:
        text = " ".join(part for part in current_parts if _stringify(part)).strip()
        if text:
            entries.append({"ref_index": current_index, "reference_text": text})

    for raw_line in lines:
        line = _stringify(raw_line)
        if not line:
            continue
        if REFERENCE_HEADING_PATTERN.match(line):
            continue

        matched = REFERENCE_SPLIT_PATTERN.match(line)
        if matched:
            if current_parts:
                flush()
            current_index = _stringify(matched.group(1) or matched.group(2) or matched.group(3))
            current_parts = [_stringify(matched.group(4))]
            continue

        if current_parts:
            current_parts.append(line)

    if current_parts:
        flush()

    if entries:
        return entries

    fallback = [line.strip() for line in lines if _stringify(line) and not REFERENCE_HEADING_PATTERN.match(line)]
    return [
        {"ref_index": str(idx + 1), "reference_text": line}
        for idx, line in enumerate(fallback)
        if len(line) >= 12
    ]


def _iter_upsert_rows(rows: Iterable[Dict[str, Any]], allowed_columns: set[str]) -> Iterable[Dict[str, Any]]:
    """过滤并清洗待写回文献行。"""

    for row in rows:
        cleaned: Dict[str, Any] = {}
        for column, value in row.items():
            if column not in allowed_columns or column == "id":
                continue
            if isinstance(value, float) and pd.isna(value):
                cleaned[column] = None
            else:
                cleaned[column] = value
        if _stringify(cleaned.get("uid_literature")):
            yield cleaned


def _upsert_literatures_rows(content_db_path: Path, rows: List[Dict[str, Any]]) -> int:
    """按 uid_literature 把文献行写回 SQLite。"""

    if not rows:
        return 0

    init_content_db(content_db_path)
    updated_count = 0
    with connect_sqlite(content_db_path) as conn:
        table_columns = {
            str(item[1]).strip()
            for item in conn.execute("PRAGMA table_info(literatures)").fetchall()
            if len(item) >= 2
        }
        for row in _iter_upsert_rows(rows, table_columns):
            columns = list(row.keys())
            placeholders = ", ".join("?" for _ in columns)
            quoted_columns = ", ".join(f'"{column}"' for column in columns)
            update_columns = [column for column in columns if column != "uid_literature"]
            if update_columns:
                update_clause = ", ".join(f'"{column}"=excluded."{column}"' for column in update_columns)
                sql = (
                    f"INSERT INTO literatures ({quoted_columns}) VALUES ({placeholders}) "
                    f"ON CONFLICT(uid_literature) DO UPDATE SET {update_clause}"
                )
            else:
                sql = (
                    f"INSERT INTO literatures ({quoted_columns}) VALUES ({placeholders}) "
                    "ON CONFLICT(uid_literature) DO NOTHING"
                )
            conn.execute(sql, tuple(row[column] for column in columns))
            updated_count += 1
        conn.commit()
    return updated_count


def local_reference_lookup_and_materialize(
    *,
    content_db_path: str | Path,
    reference_list_text: str,
    workspace_root: str | Path | None = None,
    top_n: int = 5,
    placeholder_source: str = "placeholder_from_local_reference_lookup",
    print_to_stdout: bool = False,
) -> Dict[str, Any]:
    """对参考文献清单执行本地匹配并补录占位条目。

    Args:
        content_db_path: 统一内容库路径，支持历史别名路径。
        reference_list_text: 参考文献清单全文文本。
        workspace_root: 工作区根路径。为空时从 content.db 自动推断。
        top_n: 本地匹配候选上限。
        placeholder_source: 占位条目 source 字段值。
        print_to_stdout: 是否打印 JSON 摘要。

    Returns:
        结果字典，包含 matched_view、placeholder_view、all_rows 与 summary。

    Raises:
        ValueError: 输入文本为空或未解析出条目。

    Examples:
        >>> result = local_reference_lookup_and_materialize(
        ...     content_db_path="workspace/database/content/content.db",
        ...     reference_list_text="[1] 张三. 示例标题[J]. 2024."
        ... )
        >>> "summary" in result
        True
    """

    resolved_content_db_path = resolve_content_db_path(content_db_path)
    init_content_db(resolved_content_db_path)
    resolved_workspace_root = (
        resolve_portable_path(workspace_root, base=Path.cwd())
        if workspace_root
        else infer_workspace_root_from_content_db(resolved_content_db_path)
    )

    reference_rows = _split_reference_list_text(reference_list_text)
    if not reference_rows:
        raise ValueError("未从 reference_list_text 中解析出有效参考文献条目")

    literature_table = load_literatures_df(resolved_content_db_path)
    original_uid_set = {
        _stringify(row.get("uid_literature"))
        for _, row in literature_table.fillna("").iterrows()
        if _stringify(row.get("uid_literature"))
    }

    processed_rows: List[Dict[str, Any]] = []
    touched_rows: Dict[str, Dict[str, Any]] = {}

    for item in reference_rows:
        ref_index = _stringify(item.get("ref_index"))
        ref_text = _stringify(item.get("reference_text"))
        parsed = parse_reference_text(ref_text)
        first_author = _stringify(parsed.first_author)
        year_value = "" if parsed.year_int is None else str(parsed.year_int)
        title_value = _stringify(parsed.title)
        clean_title = _stringify(parsed.clean_title)

        matches = literature_match(
            table=literature_table,
            first_author=first_author or None,
            year=parsed.year_int,
            title=title_value,
            top_n=max(int(top_n or 0), 1),
        )

        action = "exists"
        match_score = 0.0
        matched_uid = ""
        matched_title = ""
        is_placeholder = 0

        if matches:
            top_match = matches[0]
            row = dict(top_match.get("row") or {})
            matched_uid = _stringify(row.get("uid_literature"))
            matched_title = _stringify(row.get("title"))
            match_score = float(top_match.get("score") or 0.0)
            is_placeholder = int(row.get("is_placeholder") or 0)
        else:
            literature_table, inserted_record, action = literature_insert_placeholder(
                table=literature_table,
                first_author=first_author,
                year=parsed.year_int,
                title=title_value,
                source=placeholder_source,
                extra={
                    "reference_text": ref_text,
                    "clean_title": clean_title,
                    "parse_method": "local_reference_text_parser",
                    "parse_failed": 0,
                    "llm_invoked": 0,
                    "online_lookup_status": "pending",
                    "online_lookup_source": "",
                    "online_lookup_note": "本地检索未命中，已插入占位条目。",
                },
                top_n=max(int(top_n or 0), 1),
            )
            if action == "exists":
                matched = dict(inserted_record.get("matched") or {})
                matched_uid = _stringify((matched.get("row") or {}).get("uid_literature") or matched.get("uid_literature"))
                matched_title = _stringify((matched.get("row") or {}).get("title") or matched.get("title"))
                match_score = float(matched.get("score") or 0.0)
                is_placeholder = int(((matched.get("row") or {}).get("is_placeholder") or 0))
            else:
                matched_uid = _stringify(inserted_record.get("uid_literature"))
                matched_title = _stringify(inserted_record.get("title"))
                is_placeholder = int(inserted_record.get("is_placeholder") or 0)
                touched_rows[matched_uid] = dict(inserted_record)

        cite_key = ""
        if matched_uid:
            row_df = literature_table[literature_table.get("uid_literature", pd.Series(dtype=str)).astype(str) == matched_uid]
            if not row_df.empty:
                row_obj = row_df.iloc[0].to_dict()
                cite_key = _stringify(row_obj.get("cite_key"))
                if not cite_key:
                    cite_key = build_cite_key(
                        _stringify(row_obj.get("first_author")) or first_author,
                        _stringify(row_obj.get("year")) or year_value,
                        _stringify(row_obj.get("clean_title")) or clean_title_text(_stringify(row_obj.get("title")) or title_value),
                    )
                    row_obj["cite_key"] = cite_key
                    touched_rows[matched_uid] = dict(row_obj)
                    literature_table.loc[row_df.index[0], "cite_key"] = cite_key

        processed_rows.append(
            {
                "ref_index": ref_index,
                "reference_text": ref_text,
                "recognized_fields": {
                    "first_author": first_author,
                    "year": year_value,
                    "title_raw": title_value,
                },
                "matched_uid_literature": matched_uid,
                "matched_title": matched_title,
                "matched_cite_key": cite_key,
                "match_score": round(match_score, 4),
                "action": action,
                "is_placeholder": int(is_placeholder),
                "parse_method": "local_reference_text_parser",
                "llm_invoked": 0,
                "parse_failed": 0,
                "parse_failure_reason": "",
                "is_reasonable": bool(title_value or (first_author and year_value)),
                "suspicious_mismatch": 0,
                "suspicious_merged": 0,
                "noise_trimmed": 0,
            }
        )

    updated_count = _upsert_literatures_rows(
        resolved_content_db_path,
        [row for row in touched_rows.values() if _stringify(row.get("uid_literature"))],
    )

    matched_view = [
        row
        for row in processed_rows
        if row["action"] == "exists"
    ]
    placeholder_view = [
        row
        for row in processed_rows
        if row["action"] != "exists"
    ]
    quality_summary = build_reference_quality_summary(processed_rows)
    quality_summary.update(
        {
            "total_input_count": len(reference_rows),
            "matched_existing_count": len(matched_view),
            "placeholder_inserted_or_updated_count": len(placeholder_view),
            "db_upsert_row_count": int(updated_count),
            "preexisting_uid_count": len(original_uid_set),
        }
    )

    result = {
        "content_db_path": str(resolved_content_db_path),
        "workspace_root": str(resolved_workspace_root),
        "matched_view": matched_view,
        "placeholder_view": placeholder_view,
        "all_rows": processed_rows,
        "summary": quality_summary,
    }

    append_aok_log_event(
        event_type="REFERENCE_LIST_LOCAL_LOOKUP",
        project_root=resolved_workspace_root,
            log_db_path=resolve_aok_log_db_path(workspace_root=resolved_workspace_root),
        enabled=True,
        handler_kind="local_script",
        handler_name="local_reference_lookup_and_materialize",
        model_name="",
        skill_names=["ar_插入引文_v1"],
        reasoning_summary="批量解析参考文献清单并执行本地匹配；未命中则插入占位文献。",
        payload={
            "content_db_path": str(resolved_content_db_path),
            "summary": quality_summary,
        },
    )

    if print_to_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result
