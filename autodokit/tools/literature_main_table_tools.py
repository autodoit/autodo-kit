"""文献主表构建工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

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


def build_literature_main_table(
    records: List[Any],
    pdf_matches: List[Tuple[bool, str]],
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
    rows: List[Dict[str, Any]] = []
    used_uid: set[str] = set()
    now_iso = get_current_time_iso("Asia/Shanghai")

    for record, (has_pdf, pdf_path) in zip(records, pdf_matches):
        row: Dict[str, Any] = {}
        for key, value in getattr(record, "fields", {}).items():
            row[key] = value

        title_text = str(getattr(record, "fields", {}).get("title", ""))
        title_norm = normalize_text_fn(title_text)
        first_author = extract_first_author(getattr(record, "fields", {}).get("author", ""))
        year_int = parse_year_int(getattr(record, "fields", {}).get("year", ""))
        clean_title = clean_title_text(title_text)

        uid = generate_uid(first_author=first_author, year_int=year_int, title_norm=title_norm)
        if uid in used_uid:
            suffix = 2
            new_uid = f"{uid}-{suffix}"
            while new_uid in used_uid:
                suffix += 1
                new_uid = f"{uid}-{suffix}"
            uid = new_uid
        used_uid.add(uid)

        row["uid_literature"] = uid
        row["cite_key"] = build_cite_key(first_author, "" if year_int is None else str(year_int), clean_title)
        row["clean_title"] = clean_title
        row["title"] = title_text
        row["title_norm"] = title_norm
        row["first_author"] = first_author
        row["year"] = "" if year_int is None else str(year_int)
        row["entry_type"] = getattr(record, "entry_type", "")
        row["is_placeholder"] = 0
        row["has_fulltext"] = int(bool(has_pdf))
        row["primary_attachment_name"] = Path(pdf_path).name if pdf_path else ""
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
        rows.append(row)

    df = pd.DataFrame(rows)
    df = ensure_id_column(df)
    if "id" in df.columns:
        df.set_index("id", inplace=True, drop=True)
    return df
