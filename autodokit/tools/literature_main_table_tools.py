"""文献主表构建工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Tuple

import pandas as pd

from autodokit.tools.bibliodb import (
    build_cite_key,
    clean_title_text,
    ensure_id_column,
    extract_first_author,
    generate_uid,
    parse_year_int,
)
from autodokit.tools.obsidian_note_timezone_tools import get_current_time_iso


def _pick_better_text(current: str, candidate: str) -> str:
    """返回更优的文本值：优先非空，再优先更长内容。"""

    current_text = str(current or "").strip()
    candidate_text = str(candidate or "").strip()
    if not current_text:
        return candidate_text
    if not candidate_text:
        return current_text
    return candidate_text if len(candidate_text) > len(current_text) else current_text


def _merge_duplicate_row(existing: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """合并同一题录键的两条记录。"""

    merged = dict(existing)
    has_fulltext_existing = int(bool(merged.get("has_fulltext")))
    has_fulltext_candidate = int(bool(candidate.get("has_fulltext")))
    merged["has_fulltext"] = max(has_fulltext_existing, has_fulltext_candidate)

    if (not has_fulltext_existing) and has_fulltext_candidate:
        merged["pdf_path"] = str(candidate.get("pdf_path") or "")
        merged["primary_attachment_name"] = str(candidate.get("primary_attachment_name") or "")
        merged["primary_attachment_source_path"] = str(candidate.get("primary_attachment_source_path") or "")
    else:
        if not str(merged.get("pdf_path") or ""):
            merged["pdf_path"] = str(candidate.get("pdf_path") or "")
        if not str(merged.get("primary_attachment_name") or ""):
            merged["primary_attachment_name"] = str(candidate.get("primary_attachment_name") or "")
        if not str(merged.get("primary_attachment_source_path") or ""):
            merged["primary_attachment_source_path"] = str(candidate.get("primary_attachment_source_path") or "")

    for text_field in (
        "authors",
        "abstract",
        "keywords",
        "journal",
        "author",
        "note",
        "url",
        "doi",
        "publisher",
        "booktitle",
    ):
        if text_field in merged or text_field in candidate:
            merged[text_field] = _pick_better_text(str(merged.get(text_field) or ""), str(candidate.get(text_field) or ""))

    if not str(merged.get("entry_type") or ""):
        merged["entry_type"] = str(candidate.get("entry_type") or "")
    if not str(merged.get("year") or ""):
        merged["year"] = str(candidate.get("year") or "")
    return merged


def build_literature_main_table(
    records: List[Any],
    pdf_matches: List[Tuple[bool, str] | Mapping[str, Any]],
    *,
    normalize_text_fn: Callable[[str], str],
) -> pd.DataFrame:
    """根据解析记录与附件匹配结果构建文献主表。

    Args:
        records: 记录对象列表。每个对象需包含 `entry_type` 与 `fields` 属性。
        pdf_matches: 与 records 对齐的附件匹配结果。
        normalize_text_fn: 文本归一化函数。

    Returns:
        文献主表 DataFrame，索引为 `id`。
    """
    dedup_rows: List[Dict[str, Any]] = []
    dedup_map: Dict[str, int] = {}
    used_uid: set[str] = set()
    now_iso = get_current_time_iso("Asia/Shanghai")

    for record, raw_pdf_match in zip(records, pdf_matches):
        if isinstance(raw_pdf_match, Mapping):
            has_pdf = bool(raw_pdf_match.get("matched") or raw_pdf_match.get("has_pdf"))
            pdf_path = str(raw_pdf_match.get("storage_path") or raw_pdf_match.get("pdf_path") or "")
            pdf_source_path = str(raw_pdf_match.get("source_path") or "")
        else:
            has_pdf, pdf_path = raw_pdf_match
            pdf_source_path = ""

        row: Dict[str, Any] = {}
        for key, value in getattr(record, "fields", {}).items():
            row[key] = value

        title_text = str(getattr(record, "fields", {}).get("title", ""))
        title_norm = normalize_text_fn(title_text)
        first_author = extract_first_author(getattr(record, "fields", {}).get("author", ""))
        year_int = parse_year_int(getattr(record, "fields", {}).get("year", ""))
        clean_title = clean_title_text(title_text)

        cite_key = build_cite_key(first_author, "" if year_int is None else str(year_int), clean_title)
        dedup_identity = cite_key.lower()
        if not dedup_identity:
            dedup_identity = "|".join(
                [
                    title_norm.lower(),
                    ("" if year_int is None else str(year_int)),
                    first_author.lower(),
                ]
            )

        row["cite_key"] = cite_key
        row["clean_title"] = clean_title
        row["title"] = title_text
        row["title_norm"] = title_norm
        row["first_author"] = first_author
        row["year"] = "" if year_int is None else str(year_int)
        row["entry_type"] = getattr(record, "entry_type", "")
        row["is_placeholder"] = 0
        row["has_fulltext"] = int(bool(has_pdf))
        row["primary_attachment_name"] = Path(pdf_path).name if pdf_path else ""
        row["primary_attachment_source_path"] = pdf_source_path
        row["standard_note_uid"] = ""
        row["created_at"] = now_iso
        row["updated_at"] = now_iso
        row["imported_at"] = now_iso
        row["authors"] = str(getattr(record, "fields", {}).get("author", ""))
        row["abstract"] = str(getattr(record, "fields", {}).get("abstract", ""))
        row["keywords"] = str(getattr(record, "fields", {}).get("keywords", ""))
        row["source_type"] = "imported_bibtex"
        row["origin_path"] = ""
        row["source"] = "imported"
        row["pdf_path"] = pdf_path
        existing_index = dedup_map.get(dedup_identity)
        if existing_index is None:
            dedup_map[dedup_identity] = len(dedup_rows)
            dedup_rows.append(row)
        else:
            dedup_rows[existing_index] = _merge_duplicate_row(dedup_rows[existing_index], row)

    rows: List[Dict[str, Any]] = []
    for row in dedup_rows:
        uid = generate_uid(
            first_author=str(row.get("first_author") or ""),
            year_int=parse_year_int(str(row.get("year") or "")),
            title_norm=str(row.get("title_norm") or ""),
        )
        if uid in used_uid:
            suffix = 2
            new_uid = f"{uid}-{suffix}"
            while new_uid in used_uid:
                suffix += 1
                new_uid = f"{uid}-{suffix}"
            uid = new_uid
        used_uid.add(uid)
        normalized = dict(row)
        normalized["uid_literature"] = uid
        rows.append(normalized)

    df = pd.DataFrame(rows)
    df = ensure_id_column(df)
    if "id" in df.columns:
        df.set_index("id", inplace=True, drop=True)
    return df
