"""文献数据库兼容工具。

本模块当前定位为 SQLite 主库时代的 DataFrame 兼容层：

1. 提供文献记录规范化、匹配、占位引文与绑定等纯内存 DataFrame 处理能力；
2. 供需要中间表运算的事务在内存态复用；
3. 不再承担“CSV 主库”职责，运行时主库存取应优先使用 `bibliodb_sqlite.py`
    或 `storage_backend.py`。

说明：
- 核心字段契约仍与文献主库一致；
- 模块保留旧接口包装函数，用于平滑迁移既有事务；
- CSV 语义仅保留为历史兼容，不再是主路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd
import re
import unicodedata


DEFAULT_LITERATURE_COLUMNS: List[str] = [
    "uid_literature",
    "cite_key",
    "title",
    "reference_text",
    "title_norm",
    "first_author",
    "year",
    "entry_type",
    "is_placeholder",
    "placeholder_reason",
    "placeholder_status",
    "placeholder_run_uid",
    "has_fulltext",
    "primary_attachment_name",
    "standard_note_uid",
    "created_at",
    "updated_at",
    "authors",
    "abstract",
    "keywords",
    "source_type",
    "origin_path",
    "source",
    "clean_title",
    "llm_invoked",
    "parse_method",
    "parse_failed",
    "parse_failure_reason",
    "online_lookup_status",
    "online_lookup_source",
    "online_lookup_note",
]

DEFAULT_ATTACHMENT_COLUMNS: List[str] = [
    "uid_literature",
    "attachment_name",
    "attachment_type",
    "is_primary",
    "note",
]


@dataclass
class MatchCandidate:
    """文献匹配候选项。

    Args:
        uid_literature: 文献唯一标识。
        score: 匹配得分（0~1）。
        title: 文献标题。
        first_author: 第一作者。
        year: 年份文本。
        row: 原始行字典。
    """

    uid_literature: str
    score: float
    title: str
    first_author: str
    year: str
    row: Dict[str, Any]


@dataclass
class ReferenceParseResult:
    """参考文献行文本解析结果。

    Args:
        reference_text: 原始参考文献文本。
        first_author: 解析出的第一作者。
        year_int: 解析出的年份整数。
        title: 解析出的标题。
        clean_title: 标题清洗结果。
    """

    reference_text: str
    first_author: str
    year_int: int | None
    title: str
    clean_title: str


UTC = getattr(datetime, "UTC", timezone.utc)


def _utc_now_iso() -> str:
    """返回 UTC ISO 时间字符串。

    Returns:
        当前 UTC 时间字符串。
    """

    return datetime.now(tz=UTC).isoformat()


def _stringify(value: Any) -> str:
    """把任意值安全转换为字符串。

    Args:
        value: 任意输入值。

    Returns:
        去除首尾空白后的字符串。
    """

    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_text_for_match(text: str) -> str:
    """将文本规范化为匹配友好的形式。

    Args:
        text: 原始文本。

    Returns:
        小写、去噪并压缩空白后的文本。
    """

    raw = unicodedata.normalize("NFKD", str(text or ""))
    raw = "".join(ch for ch in raw if not unicodedata.category(ch).startswith("M"))
    raw = raw.lower()
    chars: List[str] = []
    for ch in raw:
        if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"):
            chars.append(ch)
        else:
            chars.append(" ")
    return " ".join("".join(chars).split())


def clean_title_text(title: str) -> str:
    """将标题转换为便于引用与匹配的清洗标题。

    Args:
        title: 原始标题。

    Returns:
        使用下划线连接的清洗标题。
    """

    text = unicodedata.normalize("NFKD", str(title or ""))
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("M"))
    text = text.lower()
    text = re.sub(r"[\s\-–—]+", "_", text)
    text = re.sub(r"[^0-9a-z_\u4e00-\u9fff]", "", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def parse_year_int(year_raw: Any) -> int | None:
    """从原始年份值中提取年份整数。

    Args:
        year_raw: 原始年份值。

    Returns:
        年份整数；若无法提取则返回 None。
    """

    if year_raw is None:
        return None
    match = re.search(r"(19|20)\d{2}", str(year_raw))
    if not match:
        return None
    return int(match.group(0))


def extract_first_author(author_raw: Any) -> str:
    """从作者字段中提取第一作者。

    Args:
        author_raw: 原始作者字段。

    Returns:
        第一作者文本。
    """

    text = str(author_raw or "").strip()
    if not text:
        return ""
    parts = re.split(r"\s*(?:;|,|，|、|＆|/|\\|\||\sand\s)\s*", text)
    for part in parts:
        if part and part.strip():
            return part.strip()
    return ""


def parse_reference_text(reference_text: str) -> ReferenceParseResult:
    """从参考文献单行文本中解析作者、年份与标题。

    Args:
        reference_text: 参考文献原始文本。

    Returns:
        解析结果对象。
    """

    text = str(reference_text or "").strip()
    text = re.sub(r"^\s*(?:\[\d+\]|\(\d+\)|\d+[\).、])\s*", "", text)
    text = " ".join(text.split())

    year_match = re.search(r"(19|20)\d{2}", text)
    year_int = int(year_match.group(0)) if year_match else None

    if year_match:
        author_part = text[: year_match.start()].strip(" .,;:()[]")
        after_year = text[year_match.end() :].strip()
    else:
        author_part = re.split(r"\.", text, maxsplit=1)[0].strip(" .,;:()[]")
        after_year = text

    first_author = extract_first_author(author_part)

    title_candidate = ""
    quoted_match = re.search(r"[\"“](.+?)[\"”]", after_year)
    if quoted_match:
        title_candidate = quoted_match.group(1).strip()
    else:
        after_year = re.sub(r"^[\s\)\]\.,;:]+", "", after_year)
        pieces = re.split(r"\.\s+", after_year, maxsplit=1)
        title_candidate = pieces[0].strip() if pieces else ""

    if not title_candidate:
        fallback = text
        if year_match:
            fallback = text[year_match.end() :].strip(" .,;:()[]") or text
        title_candidate = fallback

    title_candidate = " ".join(title_candidate.split())
    clean_title = clean_title_text(title_candidate)
    return ReferenceParseResult(
        reference_text=text,
        first_author=first_author,
        year_int=year_int,
        title=title_candidate,
        clean_title=clean_title,
    )


def generate_uid(first_author: str | None, year_int: int | None, title_norm: str, prefix: str | None = None) -> str:
    """生成稳定文献 UID。

    Args:
        first_author: 第一作者。
        year_int: 年份整数。
        title_norm: 规范化标题。
        prefix: 可选前缀；未提供时默认使用 `lit`。

    Returns:
        稳定文献 UID。
    """

    author = normalize_text_for_match(first_author or "")
    year = "" if year_int is None else str(year_int)
    base = f"{author}|{year}|{normalize_text_for_match(title_norm)}"
    digest = sha1(base.encode("utf-8")).hexdigest()[:16]
    prefix_text = prefix or "lit"
    return f"{prefix_text}-{digest}"


def build_cite_key(first_author: str, year: str, title_norm: str) -> str:
    """构建可读引用键。

    Args:
        first_author: 第一作者。
        year: 年份文本。
        title_norm: 规范化标题。

    Returns:
        cite_key 字符串。
    """

    author_key = clean_title_text(first_author or "unknown") or "unknown"
    year_key = _stringify(year) or "nd"
    title_key = clean_title_text(title_norm or "untitled") or "untitled"
    return f"{author_key}-{year_key}-{title_key}"


def init_empty_literatures_table() -> pd.DataFrame:
    """初始化空文献主表。

    Returns:
        空文献主表 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_LITERATURE_COLUMNS))


def init_empty_attachments_table() -> pd.DataFrame:
    """初始化空文献附件关联表。

    Returns:
        空附件关联表 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_ATTACHMENT_COLUMNS))


def init_empty_table(columns: List[str] | None = None, table_kind: str = "literatures") -> pd.DataFrame:
    """初始化空表。

    Args:
        columns: 自定义列名。
        table_kind: 表类型，支持 `literatures` 或 `attachments`。

    Returns:
        空 DataFrame。
    """

    if columns is not None:
        return pd.DataFrame(columns=list(columns))
    if table_kind == "attachments":
        return init_empty_attachments_table()
    return init_empty_literatures_table()


def ensure_id_column(table: pd.DataFrame) -> pd.DataFrame:
    """为表生成连续 `id` 列。

    Args:
        table: 任意数据表。

    Returns:
        包含连续 `id` 列的新 DataFrame。
    """

    result = table.copy().reset_index(drop=True)
    result["id"] = list(range(1, len(result) + 1))
    return result


def _ensure_columns(table: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    """确保表包含指定列。

    Args:
        table: 原始表。
        columns: 目标列名列表。

    Returns:
        补齐列后的 DataFrame。
    """

    result = table.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = ""
    return result


def _normalize_literatures_table(table: pd.DataFrame) -> pd.DataFrame:
    """规范化文献主表字段。

    Args:
        table: 原始主表。

    Returns:
        使用 003 字段语义的主表。
    """

    result = table.copy()
    rename_map = {
        "uid": "uid_literature",
        "是否有原文": "has_fulltext",
    }
    for old_name, new_name in rename_map.items():
        if old_name in result.columns and new_name not in result.columns:
            result = result.rename(columns={old_name: new_name})

    result = _ensure_columns(result, list(DEFAULT_LITERATURE_COLUMNS))

    # 真实工作区中的历史表可能将这些字段存为严格整数类型，后续规范化会混合写入
    # 字符串与整数语义；先转为 object，避免 pandas 在 .at 回写时抛出 dtype 错误。
    for column in ["has_fulltext", "is_placeholder", "llm_invoked", "parse_failed"]:
        if column in result.columns:
            result[column] = result[column].astype(object)

    if "pdf_path" in result.columns:
        for idx, row in result.iterrows():
            primary = _stringify(row.get("primary_attachment_name"))
            pdf_path = _stringify(row.get("pdf_path"))
            if not primary and pdf_path:
                result.at[idx, "primary_attachment_name"] = Path(pdf_path).name

    for idx, row in result.iterrows():
        title = _stringify(row.get("title"))
        title_norm = _stringify(row.get("title_norm")) or normalize_text_for_match(title)
        first_author = _stringify(row.get("first_author")) or extract_first_author(row.get("authors") or row.get("author"))
        year = _stringify(row.get("year"))
        uid_literature = _stringify(row.get("uid_literature"))
        if not uid_literature and title:
            uid_literature = generate_uid(first_author, parse_year_int(year), title_norm)
            result.at[idx, "uid_literature"] = uid_literature
        result.at[idx, "title_norm"] = title_norm
        result.at[idx, "first_author"] = first_author
        if not _stringify(row.get("cite_key")) and title:
            result.at[idx, "cite_key"] = build_cite_key(first_author, year, clean_title_text(title_norm))

        has_fulltext_raw = row.get("has_fulltext")
        if _stringify(has_fulltext_raw):
            has_fulltext = 1 if str(has_fulltext_raw).strip().lower() in {"1", "true", "yes", "y"} else 0
        else:
            has_fulltext = 1 if _stringify(row.get("primary_attachment_name")) else 0
        result.at[idx, "has_fulltext"] = str(int(has_fulltext))

        if not _stringify(row.get("clean_title")) and title:
            result.at[idx, "clean_title"] = clean_title_text(title)

    return result


def _normalize_attachments_table(table: pd.DataFrame) -> pd.DataFrame:
    """规范化附件关联表字段。

    Args:
        table: 原始附件关联表。

    Returns:
        使用 003 字段语义的附件关联表。
    """

    result = table.copy()
    rename_map = {
        "item_uid": "uid_literature",
        "file_path": "attachment_name",
        "file_type": "attachment_type",
    }
    for old_name, new_name in rename_map.items():
        if old_name in result.columns and new_name not in result.columns:
            result = result.rename(columns={old_name: new_name})
    result = _ensure_columns(result, list(DEFAULT_ATTACHMENT_COLUMNS))

    for idx, row in result.iterrows():
        attachment_name = _stringify(row.get("attachment_name"))
        if attachment_name:
            result.at[idx, "attachment_name"] = Path(attachment_name).name
        is_primary_raw = row.get("is_primary")
        result.at[idx, "is_primary"] = 1 if str(is_primary_raw).strip().lower() in {"1", "true", "yes", "y"} else 0

    return result


def _normalize_literature_record(record: Dict[str, Any], *, existing: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """规范化单条文献记录。

    Args:
        record: 原始记录。
        existing: 已存在记录，用于保留创建时间等字段。

    Returns:
        规范化后的记录字典。
    """

    base: Dict[str, Any] = dict(existing or {})
    raw = dict(record)

    title = _stringify(raw.get("title") or base.get("title"))
    title_norm = _stringify(raw.get("title_norm") or base.get("title_norm")) or normalize_text_for_match(title)
    first_author = _stringify(raw.get("first_author") or base.get("first_author"))
    if not first_author:
        first_author = extract_first_author(raw.get("authors") or raw.get("author") or base.get("authors") or base.get("author"))
    year = _stringify(raw.get("year") or base.get("year"))
    year_int = parse_year_int(year)
    uid_literature = _stringify(raw.get("uid_literature") or raw.get("uid") or base.get("uid_literature"))
    if not uid_literature and title:
        uid_literature = generate_uid(first_author, year_int, title_norm)

    primary_attachment_name = _stringify(
        raw.get("primary_attachment_name")
        or base.get("primary_attachment_name")
        or (Path(_stringify(raw.get("pdf_path"))).name if _stringify(raw.get("pdf_path")) else "")
    )
    has_fulltext_raw = raw.get("has_fulltext", raw.get("has_pdf", base.get("has_fulltext", "")))
    if _stringify(has_fulltext_raw):
        has_fulltext = 1 if str(has_fulltext_raw).strip().lower() in {"1", "true", "yes", "y"} else 0
    else:
        has_fulltext = 1 if primary_attachment_name else 0

    created_at = _stringify(base.get("created_at")) or _stringify(raw.get("created_at")) or _utc_now_iso()
    updated_at = _stringify(raw.get("updated_at")) or _utc_now_iso()

    normalized: Dict[str, Any] = {
        "uid_literature": uid_literature,
        "cite_key": _stringify(raw.get("cite_key") or base.get("cite_key")) or build_cite_key(first_author, year, clean_title_text(title_norm)),
        "title": title,
        "reference_text": _stringify(raw.get("reference_text") or base.get("reference_text")),
        "title_norm": title_norm,
        "first_author": first_author,
        "year": year,
        "entry_type": _stringify(raw.get("entry_type") or base.get("entry_type")) or "article",
        "is_placeholder": int(raw.get("is_placeholder", base.get("is_placeholder", 0)) or 0),
        "placeholder_reason": _stringify(raw.get("placeholder_reason") or base.get("placeholder_reason")),
        "placeholder_status": _stringify(raw.get("placeholder_status") or base.get("placeholder_status")) or "",
        "placeholder_run_uid": _stringify(raw.get("placeholder_run_uid") or base.get("placeholder_run_uid")),
        "has_fulltext": int(has_fulltext),
        "primary_attachment_name": primary_attachment_name,
        "standard_note_uid": _stringify(raw.get("standard_note_uid") or base.get("standard_note_uid")),
        "created_at": created_at,
        "updated_at": updated_at,
        "authors": _stringify(raw.get("authors") or raw.get("author") or base.get("authors") or base.get("author")),
        "abstract": _stringify(raw.get("abstract") or base.get("abstract")),
        "keywords": _stringify(raw.get("keywords") or base.get("keywords")),
        "source_type": _stringify(raw.get("source_type") or base.get("source_type")),
        "origin_path": _stringify(raw.get("origin_path") or base.get("origin_path")),
        "source": _stringify(raw.get("source") or base.get("source")),
        "clean_title": _stringify(raw.get("clean_title") or base.get("clean_title")) or clean_title_text(title),
        "llm_invoked": int(raw.get("llm_invoked", base.get("llm_invoked", 0)) or 0),
        "parse_method": _stringify(raw.get("parse_method") or base.get("parse_method")),
        "parse_failed": int(raw.get("parse_failed", base.get("parse_failed", 0)) or 0),
        "parse_failure_reason": _stringify(raw.get("parse_failure_reason") or base.get("parse_failure_reason")),
        "online_lookup_status": _stringify(raw.get("online_lookup_status") or base.get("online_lookup_status")),
        "online_lookup_source": _stringify(raw.get("online_lookup_source") or base.get("online_lookup_source")),
        "online_lookup_note": _stringify(raw.get("online_lookup_note") or base.get("online_lookup_note")),
    }
    return normalized


def _with_legacy_aliases(record: Dict[str, Any]) -> Dict[str, Any]:
    """为旧接口返回值补充兼容别名字段。

    Args:
        record: 新字段语义记录。

    Returns:
        同时包含新旧别名字段的记录。
    """

    result = dict(record)
    result.setdefault("uid", result.get("uid_literature", ""))
    result.setdefault("has_pdf", result.get("has_fulltext", 0))
    result.setdefault("是否有原文", result.get("has_fulltext", 0))
    result.setdefault("pdf_path", result.get("pdf_path", ""))
    return result


def literature_match(table: pd.DataFrame, first_author: str | None, year: int | None, title: str, top_n: int = 5) -> List[Dict[str, Any]]:
    """在文献主表中查找候选匹配。

    Args:
        table: 文献主表。
        first_author: 待匹配第一作者。
        year: 待匹配年份。
        title: 待匹配标题。
        top_n: 返回候选上限。

    Returns:
        候选列表。
    """

    working = _normalize_literatures_table(table)
    if working.empty:
        return []

    title_norm = normalize_text_for_match(title)
    author_norm = normalize_text_for_match(first_author or "")
    candidates: List[MatchCandidate] = []

    for _, row in working.iterrows():
        row_title = normalize_text_for_match(_stringify(row.get("title_norm") or row.get("title") or row.get("clean_title")))
        row_author = normalize_text_for_match(_stringify(row.get("first_author")))
        row_year = parse_year_int(row.get("year"))

        score = 0.0
        if row_title and row_title == title_norm:
            score += 0.7
        elif row_title and (title_norm in row_title or row_title in title_norm):
            score += 0.4

        if author_norm and row_author and author_norm == row_author:
            score += 0.2

        if year is not None and row_year is not None and int(year) == int(row_year):
            score += 0.1

        if score <= 0:
            continue

        candidates.append(
            MatchCandidate(
                uid_literature=_stringify(row.get("uid_literature")),
                score=round(score, 4),
                title=_stringify(row.get("title")),
                first_author=_stringify(row.get("first_author")),
                year=_stringify(row.get("year")),
                row=dict(row),
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return [
        {
            "uid_literature": candidate.uid_literature,
            "uid": candidate.uid_literature,
            "score": candidate.score,
            "title": candidate.title,
            "first_author": candidate.first_author,
            "year": candidate.year,
            "year_int": parse_year_int(candidate.year),
            "row": _with_legacy_aliases(candidate.row),
        }
        for candidate in candidates[:top_n]
    ]


def find_match(table: pd.DataFrame, first_author: str | None, year: int | None, title: str, top_n: int = 5) -> List[Dict[str, Any]]:
    """旧接口包装：查找文献匹配候选。"""

    return literature_match(table=table, first_author=first_author, year=year, title=title, top_n=top_n)


def literature_upsert(table: pd.DataFrame, literature: Dict[str, Any], overwrite: bool = True) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """插入或更新文献主表记录。"""

    working = _normalize_literatures_table(table)
    incoming = _normalize_literature_record(literature)
    uid_literature = _stringify(incoming.get("uid_literature"))
    if not uid_literature:
        raise ValueError("literature_upsert 需要可生成的 uid_literature")

    matches = working.index[working["uid_literature"].astype(str) == uid_literature].tolist()
    if not matches and _stringify(incoming.get("cite_key")):
        matches = working.index[working["cite_key"].astype(str) == _stringify(incoming.get("cite_key"))].tolist()

    if not matches:
        row_to_add = {column: incoming.get(column, "") for column in DEFAULT_LITERATURE_COLUMNS}
        working = pd.concat([working, pd.DataFrame([row_to_add])], ignore_index=True)
        return working, dict(row_to_add), "inserted"

    idx = matches[0]
    current = dict(working.loc[idx])
    normalized = _normalize_literature_record(incoming, existing=current)
    merged: Dict[str, Any] = {}
    for column in DEFAULT_LITERATURE_COLUMNS:
        current_value = current.get(column, "")
        incoming_value = normalized.get(column, "")
        if overwrite:
            merged[column] = incoming_value if _stringify(incoming_value) or incoming_value in {0, 1} else current_value
        else:
            merged[column] = current_value if _stringify(current_value) else incoming_value
    for column, value in merged.items():
        working.at[idx, column] = value
    return working, merged, "updated"


def upsert_record(table: pd.DataFrame, bib_entry: Dict[str, Any], source: str = "imported", overwrite: bool = False) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """旧接口包装：插入或更新文献记录。"""

    payload = dict(bib_entry)
    payload.setdefault("source", source)
    new_table, record, action = literature_upsert(table=table, literature=payload, overwrite=overwrite)
    return new_table, _with_legacy_aliases(record), action


def literature_insert_placeholder(
    table: pd.DataFrame,
    *,
    reference_text: str = "",
    first_author: str = "",
    year: int | None = None,
    title: str = "",
    source: str = "placeholder",
    extra: Dict[str, Any] | None = None,
    top_n: int = 5,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """插入占位引文记录。"""

    working = _normalize_literatures_table(table)

    if reference_text:
        parsed = parse_reference_text(reference_text)
        first_author = parsed.first_author
        year = parsed.year_int
        title = parsed.title
        clean_title = parsed.clean_title
    else:
        clean_title = clean_title_text(title)

    if not title:
        raise ValueError("literature_insert_placeholder 需要 title 或 reference_text")

    matches = literature_match(table=working, first_author=first_author, year=year, title=title, top_n=top_n)
    if matches:
        return (
            working,
            {
                "action": "exists",
                "matched": matches[0],
                "parsed": {
                    "first_author": first_author,
                    "year_int": year,
                    "title": title,
                    "clean_title": clean_title,
                    "reference_text": reference_text,
                },
            },
            "exists",
        )

    payload: Dict[str, Any] = {
        "title": title,
        "title_norm": normalize_text_for_match(title),
        "first_author": first_author,
        "year": "" if year is None else str(year),
        "entry_type": "placeholder",
        "is_placeholder": 1,
        "has_fulltext": 0,
        "primary_attachment_name": "",
        "source": source,
        "clean_title": clean_title,
    }
    if reference_text:
        payload["reference_text"] = reference_text
    if extra:
        payload.update(extra)

    return literature_upsert(table=working, literature=payload, overwrite=False)


def create_placeholder(
    table: pd.DataFrame,
    first_author: str,
    year: int | None,
    title: str,
    clean_title: str,
    source: str = "placeholder",
    extra: Dict[str, Any] | None = None,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """旧接口包装：创建占位引文。"""

    new_table, record, action = literature_insert_placeholder(
        table=table,
        first_author=first_author,
        year=year,
        title=title,
        source=source,
        extra={"clean_title": clean_title, **(extra or {})},
    )
    return new_table, _with_legacy_aliases(record), action


def insert_placeholder_from_reference(
    table: pd.DataFrame,
    reference_text: str,
    source: str = "placeholder_from_reading",
    top_n: int = 5,
    extra: Dict[str, Any] | None = None,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """旧接口包装：从参考文献文本插入占位引文。"""

    new_table, record, action = literature_insert_placeholder(
        table=table,
        reference_text=reference_text,
        source=source,
        extra=extra,
        top_n=top_n,
    )
    if isinstance(record, dict) and action != "exists":
        return new_table, _with_legacy_aliases(record), action
    if isinstance(record, dict) and action == "exists":
        result = dict(record)
        matched = result.get("matched")
        if isinstance(matched, dict):
            result["matched"] = _with_legacy_aliases(matched)
        return new_table, result, action
    return new_table, record, action


def literature_attach_file(
    literatures_table: pd.DataFrame,
    attachments_table: pd.DataFrame,
    uid_literature: str,
    attachment_name: str,
    attachment_type: str = "other",
    is_primary: int | bool = 0,
    note: str = "",
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """为文献条目绑定附件关系。"""

    working_literatures = _normalize_literatures_table(literatures_table)
    working_attachments = _normalize_attachments_table(attachments_table)
    uid_text = _stringify(uid_literature)
    attachment_text = Path(_stringify(attachment_name)).name
    if not uid_text or not attachment_text:
        raise ValueError("literature_attach_file 需要 uid_literature 与 attachment_name")

    matches = working_literatures.index[working_literatures["uid_literature"].astype(str) == uid_text].tolist()
    if not matches:
        raise KeyError(f"未找到 uid_literature={uid_text} 的文献记录")

    primary_flag = 1 if bool(is_primary) else 0
    if primary_flag:
        primary_mask = working_attachments["uid_literature"].astype(str).eq(uid_text)
        if primary_mask.any():
            working_attachments.loc[primary_mask, "is_primary"] = 0

    relation_mask = (
        working_attachments["uid_literature"].astype(str).eq(uid_text)
        & working_attachments["attachment_name"].astype(str).eq(attachment_text)
    )
    relation_indices = working_attachments.index[relation_mask].tolist()
    relation_record = {
        "uid_literature": uid_text,
        "attachment_name": attachment_text,
        "attachment_type": _stringify(attachment_type) or "other",
        "is_primary": primary_flag,
        "note": _stringify(note),
    }

    if relation_indices:
        relation_idx = relation_indices[0]
        for key, value in relation_record.items():
            working_attachments.at[relation_idx, key] = value
    else:
        working_attachments = pd.concat([working_attachments, pd.DataFrame([relation_record])], ignore_index=True)

    literature_idx = matches[0]
    if primary_flag:
        working_literatures.at[literature_idx, "primary_attachment_name"] = attachment_text
        working_literatures.at[literature_idx, "has_fulltext"] = 1
        working_literatures.at[literature_idx, "updated_at"] = _utc_now_iso()

    return working_literatures, working_attachments, relation_record


def literature_bind_standard_note(
    literatures_table: pd.DataFrame,
    uid_literature: str,
    standard_note_uid: str,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """绑定文献条目与文献标准笔记 UID。"""

    working = _normalize_literatures_table(literatures_table)
    uid_text = _stringify(uid_literature)
    note_uid_text = _stringify(standard_note_uid)
    if not uid_text or not note_uid_text:
        raise ValueError("literature_bind_standard_note 需要 uid_literature 与 standard_note_uid")

    duplicate_mask = working["standard_note_uid"].astype(str).eq(note_uid_text) & ~working["uid_literature"].astype(str).eq(uid_text)
    if duplicate_mask.any():
        duplicate_uid = _stringify(working.loc[duplicate_mask].iloc[0].get("uid_literature"))
        raise ValueError(f"standard_note_uid 已绑定其他文献：{duplicate_uid}")

    matches = working.index[working["uid_literature"].astype(str) == uid_text].tolist()
    if not matches:
        raise KeyError(f"未找到 uid_literature={uid_text} 的文献记录")

    idx = matches[0]
    working.at[idx, "standard_note_uid"] = note_uid_text
    working.at[idx, "updated_at"] = _utc_now_iso()
    return working, dict(working.loc[idx])


def literature_get(
    literatures_table: pd.DataFrame,
    attachments_table: pd.DataFrame | None = None,
    *,
    uid_literature: str = "",
    cite_key: str = "",
) -> Dict[str, Any]:
    """按 UID 或 cite_key 获取文献记录。"""

    working_literatures = _normalize_literatures_table(literatures_table)
    if attachments_table is not None:
        working_attachments = _normalize_attachments_table(attachments_table)
    else:
        working_attachments = init_empty_attachments_table()

    if uid_literature:
        matches = working_literatures.index[working_literatures["uid_literature"].astype(str) == _stringify(uid_literature)].tolist()
    elif cite_key:
        matches = working_literatures.index[working_literatures["cite_key"].astype(str) == _stringify(cite_key)].tolist()
    else:
        raise ValueError("literature_get 需要 uid_literature 或 cite_key")

    if not matches:
        raise KeyError("未找到目标文献记录")

    row = dict(working_literatures.loc[matches[0]])
    uid_text = _stringify(row.get("uid_literature"))
    attachment_rows = working_attachments[working_attachments["uid_literature"].astype(str) == uid_text]
    row["attachments"] = [dict(item) for _, item in attachment_rows.iterrows()]
    return row


def update_pdf_status(table: pd.DataFrame, uid: str, has_pdf: int, pdf_path: str = "") -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """旧接口包装：更新原文状态。"""

    working = _normalize_literatures_table(table)
    uid_text = _stringify(uid)
    matches = working.index[working["uid_literature"].astype(str) == uid_text].tolist()
    if not matches and "uid" in working.columns:
        matches = working.index[working["uid"].astype(str) == uid_text].tolist()
    if not matches:
        raise KeyError(f"未找到 uid={uid_text} 的记录")

    idx = matches[0]
    working.at[idx, "has_fulltext"] = int(bool(has_pdf))
    if pdf_path:
        working.at[idx, "primary_attachment_name"] = Path(str(pdf_path)).name
        if "pdf_path" not in working.columns:
            working["pdf_path"] = ""
        working.at[idx, "pdf_path"] = str(pdf_path)
    working.at[idx, "updated_at"] = _utc_now_iso()
    return working, _with_legacy_aliases(dict(working.loc[idx]))
