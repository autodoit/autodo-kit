"""增量 Bib 导入 content.db 工具。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pandas as pd
from bibtexparser import loads as bibtex_loads

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


def _load_bib_records(bib_paths: str | Path | Sequence[str | Path]) -> List[BibRecord]:
    """解析多个 Bib 文件并返回记录列表。"""

    records: List[BibRecord] = []
    source_files = _iter_bib_source_files(bib_paths)
    for bib_file in source_files:
        bib_text = bib_file.read_text(encoding="utf-8", errors="ignore")
        bib_db = bibtex_loads(bib_text)
        for entry in bib_db.entries:
            entry_type = str(entry.get("ENTRYTYPE", ""))
            entry_key = str(entry.get("ID", ""))
            fields = {str(key).lower(): value for key, value in entry.items() if key not in {"ENTRYTYPE", "ID"}}
            records.append(BibRecord(entry_type=entry_type, entry_key=entry_key, fields=fields))
    return records


def _build_pdf_index(pdf_dir: Path) -> Dict[str, str]:
    """按标题归一化结果建立 PDF 索引。"""

    index: Dict[str, str] = {}
    if not pdf_dir.exists():
        return index
    for pdf_path in pdf_dir.rglob("*.pdf"):
        key = normalize_text(pdf_path.stem)
        if key:
            index[key] = str(pdf_path)
    return index


def _match_pdf_paths(records: Iterable[BibRecord], pdf_index: Dict[str, str]) -> List[Tuple[bool, str]]:
    """按标题匹配 PDF 路径。"""

    results: List[Tuple[bool, str]] = []
    for record in records:
        key = normalize_text(str(record.fields.get("title", "")))
        if not key:
            results.append((False, ""))
            continue
        if key in pdf_index:
            results.append((True, pdf_index[key]))
            continue

        matched_path = ""
        for pdf_key, pdf_path in pdf_index.items():
            if key in pdf_key or pdf_key in key:
                matched_path = pdf_path
                break
        results.append((bool(matched_path), matched_path))
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
        pdf_matches = [(False, "") for _ in records]

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
        "incoming_attachment_candidates": int(sum(1 for hit, _ in pdf_matches if hit)),
        "incoming_attachment_index_size": int(sum(len(v) for v in incoming_attachment_index.values())),
        **merge_summary,
    }
