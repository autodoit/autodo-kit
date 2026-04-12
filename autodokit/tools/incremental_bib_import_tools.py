"""增量 Bib 导入 content.db 工具。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pandas as pd
from bibtexparser import loads as bibtex_loads
import re

from autodokit.tools import bibliodb_sqlite
from autodokit.tools.literature_attachment_tools import build_literature_attachment_inverted_index
from autodokit.tools.literature_main_table_tools import build_literature_main_table
from autodokit.tools.literature_tag_tools import build_literature_tag_inverted_index
from autodokit.tools.metadata_dedup import normalize_text


@dataclass
class BibRecord:
    """BibTeX 条目对象。

    Args:
        entry_type: 条目类型。
        entry_key: 条目键。
        fields: 条目字段。

    Returns:
        BibRecord: 结构化 Bib 条目。

    Raises:
        无。

    Examples:
        >>> BibRecord(entry_type="article", entry_key="k1", fields={"title": "Demo"})
        BibRecord(entry_type='article', entry_key='k1', fields={'title': 'Demo'})
    """

    entry_type: str
    entry_key: str
    fields: Dict[str, Any]


def _iter_bib_source_files(bib_paths: str | Path | Sequence[str | Path]) -> List[Path]:
    """展开 Bib 输入路径为文件列表。"""

    if isinstance(bib_paths, (str, Path)):
        raw_paths: Sequence[str | Path] = [bib_paths]
    else:
        raw_paths = bib_paths

    source_files: List[Path] = []
    for raw in raw_paths:
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            source_files.extend(sorted(path.glob("*.bib")))
            continue
        if path.is_file():
            source_files.append(path)

    dedup: List[Path] = []
    seen: set[Path] = set()
    for item in source_files:
        if item in seen:
            continue
        seen.add(item)
        dedup.append(item)
    return dedup


def _preprocess_bibtex_text_for_parser(bibtex_text: str, *, file_prefix: str) -> str:
    """对 BibTeX 文本做与 A020 事务一致的预处理。"""

    text = bibtex_text or ""
    text = re.sub(r"@([^{]+)\{", lambda m: "@" + re.sub(r"\s+", "", m.group(1)) + "{", text)

    parts = re.split(r"(?=@)", text)
    out_parts: List[str] = []
    auto_idx = 1

    def map_type(orig: str) -> str:
        s = orig.lower().replace(" ", "")
        if "journal" in s or "article" in s:
            return "article"
        if "conference" in s or "inproceedings" in s or "proceedings" in s:
            return "inproceedings"
        if "thesis" in s or "dissertation" in s:
            return "phdthesis"
        if "book" in s:
            return "book"
        return "misc"

    for part in parts:
        if not part.strip():
            continue
        if not part.lstrip().startswith("@"):
            out_parts.append(part)
            continue

        brace_pos = part.find("{")
        if brace_pos == -1:
            out_parts.append(part)
            continue

        orig_type = part[1:brace_pos].strip()
        std_type = map_type(orig_type)
        first_comma = part.find(",", brace_pos + 1)
        if first_comma == -1:
            out_parts.append("@" + std_type + part[brace_pos:])
            continue

        key_candidate = part[brace_pos + 1:first_comma].strip()
        if not key_candidate or "=" in key_candidate:
            key = f"{file_prefix}auto_{auto_idx}"
            auto_idx += 1
            rest = part[brace_pos + 1:].lstrip()
            new_part = f"@{std_type}{{{key}, orig_entry_type = {{{orig_type}}}," + rest
        else:
            key = f"{file_prefix}{key_candidate}"
            rest = part[first_comma + 1:]
            new_part = f"@{std_type}{{{key}, orig_entry_type = {{{orig_type}}}," + rest

        out_parts.append(new_part)

    return "".join(out_parts)


def _load_bib_records(bib_paths: str | Path | Sequence[str | Path]) -> List[BibRecord]:
    """解析多个 Bib 文件并返回记录列表（与 A020 使用同一套解析逻辑）。"""

    records: List[BibRecord] = []
    source_files = _iter_bib_source_files(bib_paths)
    merged_parts: List[str] = []
    for idx, bib_file in enumerate(source_files, start=1):
        bib_text = bib_file.read_text(encoding="utf-8", errors="ignore")
        safe_stem = re.sub(r"[^0-9A-Za-z_\-]+", "_", bib_file.stem)
        prefix = f"f{idx:03d}_{safe_stem}_"
        merged_parts.append(_preprocess_bibtex_text_for_parser(bib_text, file_prefix=prefix))
        merged_parts.append("\n\n")

    bib_db = bibtex_loads("".join(merged_parts))
    for entry in bib_db.entries:
        entry_type = str(entry.get("ENTRYTYPE", ""))
        orig_type = entry.get("orig_entry_type") or entry.get("orig_entrytype")
        if orig_type:
            entry_type = str(orig_type)
        entry_key = str(entry.get("ID", ""))
        fields = {str(key).lower(): value for key, value in entry.items() if key not in {"ENTRYTYPE", "ID"}}
        records.append(BibRecord(entry_type=entry_type, entry_key=entry_key, fields=fields))
    return records


def _build_pdf_index(pdf_dir: Path) -> Dict[str, list[dict[str, str]]]:
    """按标题归一化结果建立 PDF 索引。"""

    index: Dict[str, list[dict[str, str]]] = {}
    if not pdf_dir.exists():
        return index
    for pdf_path in pdf_dir.rglob("*.pdf"):
        key = normalize_text(pdf_path.stem)
        if key:
            index.setdefault(key, []).append({"storage_path": str(pdf_path), "source_path": str(pdf_path)})
    return index


def _record_title_signature(record: BibRecord) -> str:
    title = normalize_text(str(record.fields.get("title", "")))
    author = normalize_text(str(record.fields.get("author", "")))
    year = normalize_text(str(record.fields.get("year", "")))
    return f"{title}|{author}|{year}"


def _match_pdf_paths(records: Iterable[BibRecord], pdf_index: Dict[str, list[dict[str, str]]]) -> List[dict[str, object]]:
    """按标题匹配 PDF 路径。"""

    record_list = list(records)
    title_to_signatures: Dict[str, set[str]] = {}
    for record in record_list:
        key = normalize_text(str(record.fields.get("title", "")))
        if key:
            title_to_signatures.setdefault(key, set()).add(_record_title_signature(record))

    results: List[dict[str, object]] = []
    for record in record_list:
        key = normalize_text(str(record.fields.get("title", "")))
        if not key:
            results.append({"matched": False, "storage_path": "", "source_path": "", "reason": "title_empty"})
            continue

        if len(title_to_signatures.get(key, set())) > 1:
            results.append({"matched": False, "storage_path": "", "source_path": "", "reason": "ambiguous_title_records"})
            continue

        exact_matches = list(pdf_index.get(key) or [])
        if len(exact_matches) == 1:
            match = exact_matches[0]
            results.append({"matched": True, "storage_path": str(match.get("storage_path") or ""), "source_path": str(match.get("source_path") or ""), "reason": "exact_title"})
            continue
        if len(exact_matches) > 1:
            results.append({"matched": False, "storage_path": "", "source_path": "", "reason": "ambiguous_title_files"})
            continue

        results.append({"matched": False, "storage_path": "", "source_path": "", "reason": "no_exact_match"})
    return results


def incremental_import_bib_into_content_db(
    *,
    db_path: str | Path,
    bib_paths: str | Path | Sequence[str | Path],
    tag_list: Sequence[str] | None = None,
    tag_match_fields: Sequence[str] | None = None,
    has_pdf_enable: bool = False,
    pdf_dir: str | Path | None = None,
) -> Dict[str, Any]:
    """把 Bib 条目增量导入到 content.db 文献域。

    Args:
        db_path: content.db 路径。
        bib_paths: 一个或多个 Bib 文件/目录路径。
        tag_list: 标签列表。
        tag_match_fields: 标签匹配字段列表。
        has_pdf_enable: 是否启用 PDF 匹配。
        pdf_dir: PDF 根目录，启用匹配时需要提供。

    Returns:
        Dict[str, Any]: 导入统计结果，包含新增、命中、总量等信息。

    Raises:
        ValueError: 未解析出任何 Bib 条目时抛出。

    Examples:
        >>> isinstance(
        ...     incremental_import_bib_into_content_db(
        ...         db_path="content.db",
        ...         bib_paths="refs.bib",
        ...     ),
        ...     dict,
        ... )
        True
    """

    target_db_path = Path(db_path).expanduser().resolve()
    records = _load_bib_records(bib_paths)
    if not records:
        raise ValueError("未解析到任何 Bib 条目，请检查 bib_paths。")

    if has_pdf_enable and pdf_dir is not None:
        pdf_index = _build_pdf_index(Path(pdf_dir).expanduser().resolve())
        pdf_matches = _match_pdf_paths(records, pdf_index)
    else:
        pdf_matches = [{"matched": False, "storage_path": "", "source_path": "", "reason": "disabled"} for _ in records]

    incoming_literatures_df = build_literature_main_table(records, pdf_matches, normalize_text_fn=normalize_text)
    incoming_attachment_index = build_literature_attachment_inverted_index(incoming_literatures_df)

    incoming_tags_df = pd.DataFrame()
    if tag_list:
        matched_fields = list(tag_match_fields or ["title", "abstract", "keywords"])
        incoming_tag_index = build_literature_tag_inverted_index(
            incoming_literatures_df,
            list(tag_list),
            matched_fields,
            normalize_text_fn=normalize_text,
        )
        incoming_tags_df = bibliodb_sqlite.build_tags_df_from_inverted_index(
            incoming_literatures_df,
            incoming_tag_index,
            normalize_text_fn=normalize_text,
        )

    incoming_attachments_df = bibliodb_sqlite.build_attachments_df_from_literatures(incoming_literatures_df)

    existing_literatures_df = bibliodb_sqlite.load_literatures_df(target_db_path)
    existing_attachments_df = bibliodb_sqlite.load_attachments_df(target_db_path)
    existing_tags_df = bibliodb_sqlite.load_tags_df(target_db_path)

    (
        merged_literatures_df,
        merged_attachments_df,
        merged_tags_df,
        merge_summary,
    ) = bibliodb_sqlite.merge_reference_records(
        existing_literatures_df=existing_literatures_df,
        existing_attachments_df=existing_attachments_df,
        existing_tags_df=existing_tags_df,
        incoming_literatures_df=incoming_literatures_df,
        incoming_attachments_df=incoming_attachments_df,
        incoming_tags_df=incoming_tags_df,
    )

    bibliodb_sqlite.replace_reference_tables_only(
        target_db_path,
        literatures_df=merged_literatures_df,
        attachments_df=merged_attachments_df,
        tags_df=merged_tags_df,
    )

    return {
        "db_path": str(target_db_path),
        "incoming_records": int(len(records)),
        "incoming_attachment_candidates": int(sum(1 for item in pdf_matches if bool(item.get("matched")))),
        "incoming_attachment_index_size": int(sum(len(v) for v in incoming_attachment_index.values())),
        **merge_summary,
    }
