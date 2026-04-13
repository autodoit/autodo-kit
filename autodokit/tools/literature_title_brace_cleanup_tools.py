"""文献标题花括号检测与清洗原子工具。"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _now_compact() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _resolve_workspace_root(content_db: Path) -> Path:
    """根据 content_db 路径推断 workspace 根目录。"""

    parts = [p.lower() for p in content_db.parts]
    marker = ["workspace", "database", "content"]
    for idx in range(0, len(parts) - len(marker) + 1):
        if parts[idx : idx + len(marker)] == marker:
            return Path(*content_db.parts[: idx + 1])
    if content_db.parent.parent.parent.exists():
        return content_db.parent.parent.parent
    return content_db.parent


def _normalize_title_text(title: str) -> str:
    """移除 BibTeX brace 并整理空白与标点间距。"""

    text = title.replace("{", "").replace("}", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    return text


def _contains_brace(text: str) -> bool:
    return "{" in text or "}" in text


def _ensure_output_dir(payload: dict[str, Any], workspace_root: Path) -> Path:
    raw_output_dir = str(payload.get("output_dir") or "").strip()
    if raw_output_dir:
        output_dir = Path(raw_output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    task_uid = f"{_now_compact()}-A040-TITLE-BRACE-CLEANUP"
    output_dir = workspace_root / "tasks" / task_uid
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def detect_and_clean_literature_title_braces(payload: dict[str, Any]) -> dict[str, Any]:
    """检测并清洗 `literatures.title` 中的花括号污染。

    Args:
        payload: 运行参数。
            - content_db: content.db 路径（必填）。
            - mode: `preview` 或 `apply`，默认 `preview`。
            - source_types: 来源类型列表，默认 `['imported_bibtex']`。
            - sample_limit: 样例上限，默认 30。
            - output_dir: 可选输出目录。
            - update_updated_at: 可选，默认 `true`。

    Returns:
        dict[str, Any]: 检测与清洗摘要，含审计文件路径与变更统计。

    Raises:
        ValueError: 当 content_db 缺失或 mode 非法时抛出。

    Examples:
        >>> payload = {
        ...     "content_db": "workspace/database/content/content.db",
        ...     "mode": "preview",
        ... }
        >>> result = detect_and_clean_literature_title_braces(payload)
        >>> result["status"] in {"PASS", "SKIPPED"}
        True
    """

    db_raw = str(payload.get("content_db") or "").strip()
    if not db_raw:
        raise ValueError("content_db 不能为空")

    mode = str(payload.get("mode") or "preview").strip().lower()
    if mode not in {"preview", "apply"}:
        raise ValueError("mode 仅支持 preview 或 apply")

    source_types_raw = payload.get("source_types")
    if isinstance(source_types_raw, list):
        source_types = [str(item).strip() for item in source_types_raw if str(item).strip()]
    elif isinstance(source_types_raw, str) and source_types_raw.strip():
        source_types = [source_types_raw.strip()]
    else:
        source_types = ["imported_bibtex"]

    sample_limit = max(1, int(payload.get("sample_limit") or 30))
    update_updated_at = bool(payload.get("update_updated_at", True))

    db_path = Path(db_raw).expanduser().resolve()
    workspace_root = _resolve_workspace_root(db_path)
    output_dir = _ensure_output_dir(payload, workspace_root)
    task_uid = output_dir.name
    started_at = _now_iso()

    select_sql = (
        "SELECT uid_literature, cite_key, title, source_type "
        "FROM literatures "
        "WHERE (instr(title, '{') > 0 OR instr(title, '}') > 0)"
    )
    params: list[Any] = []
    if source_types:
        placeholders = ",".join("?" for _ in source_types)
        select_sql += f" AND source_type IN ({placeholders})"
        params.extend(source_types)
    select_sql += " ORDER BY uid_literature"

    updated_count = 0
    unchanged_count = 0
    rows_for_csv: list[dict[str, Any]] = []

    with sqlite3.connect(str(db_path), timeout=60) as conn:
        conn.row_factory = sqlite3.Row
        matched_rows = list(conn.execute(select_sql, tuple(params)).fetchall())
        all_rows_count = int(
            conn.execute(
                "SELECT COUNT(1) FROM literatures WHERE instr(title, '{') > 0 OR instr(title, '}') > 0"
            ).fetchone()[0]
        )
        table_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(literatures)").fetchall()
        }

        update_sql = "UPDATE literatures SET title = ?"
        if update_updated_at and "updated_at" in table_columns:
            update_sql += ", updated_at = ?"
        update_sql += " WHERE uid_literature = ?"

        for row in matched_rows:
            uid_literature = str(row["uid_literature"] or "")
            cite_key = str(row["cite_key"] or "")
            source_type = str(row["source_type"] or "")
            title_old = str(row["title"] or "")
            title_new = _normalize_title_text(title_old)
            changed = title_new != title_old

            if changed:
                if mode == "apply":
                    update_params: list[Any] = [title_new]
                    if update_updated_at and "updated_at" in table_columns:
                        update_params.append(_now_iso())
                    update_params.append(uid_literature)
                    conn.execute(update_sql, tuple(update_params))
                updated_count += 1
            else:
                unchanged_count += 1

            rows_for_csv.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "source_type": source_type,
                    "changed": 1 if changed else 0,
                    "title_before": title_old,
                    "title_after": title_new,
                }
            )

        if mode == "apply":
            conn.commit()

    report_path = output_dir / "title_brace_cleanup_report.json"
    csv_path = output_dir / "title_brace_cleanup_changes.csv"
    gate_path = output_dir / "gate_review.json"

    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "uid_literature",
                "cite_key",
                "source_type",
                "changed",
                "title_before",
                "title_after",
            ],
        )
        writer.writeheader()
        for row in rows_for_csv:
            writer.writerow(row)

    sample_rows = rows_for_csv[:sample_limit]
    matched_count = len(rows_for_csv)
    skipped_count = max(0, matched_count - updated_count)
    gate_action = "pass_next"
    gate_summary = (
        f"title 花括号检测命中 {matched_count} 条，"
        f"{('已清洗' if mode == 'apply' else '可清洗')} {updated_count} 条。"
    )

    gate_payload = {
        "gate_code": "G040-TITLE-CLEANUP",
        "node_code": "A040",
        "mode": mode,
        "summary": gate_summary,
        "recommendation": gate_action,
        "checks": {
            "matched_rows": matched_count,
            "updated_rows": updated_count,
            "unchanged_rows": unchanged_count,
            "source_types": source_types,
        },
    }
    gate_path.write_text(json.dumps(gate_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    result = {
        "status": "PASS" if matched_count > 0 else "SKIPPED",
        "result_code": "PASS",
        "node_code": "A040",
        "task_uid": task_uid,
        "mode": mode,
        "content_db": str(db_path),
        "workspace_root": str(workspace_root),
        "source_types": source_types,
        "brace_rows_total": all_rows_count,
        "matched_rows": matched_count,
        "updated_rows": updated_count,
        "unchanged_rows": unchanged_count,
        "skipped_rows": skipped_count,
        "sample_rows": sample_rows,
        "decision_suggestion": gate_action,
        "gate_review_path": str(gate_path),
        "artifact_paths": [str(report_path), str(csv_path), str(gate_path)],
        "started_at": started_at,
        "ended_at": _now_iso(),
    }

    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
