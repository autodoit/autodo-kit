"""Zotero RDF 转 A020 增量导入输入包工具。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import pandas as pd

from autodokit.tools.bibliodb_sqlite import build_stable_attachment_uid, load_literatures_df
from autodokit.tools.old.bibliodb_csv_compat import build_cite_key, clean_title_text, extract_first_author, generate_uid, parse_year_int


RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
Z_NS = "http://www.zotero.org/namespaces/export#"
DC_NS = "http://purl.org/dc/elements/1.1/"
FOAF_NS = "http://xmlns.com/foaf/0.1/"
BIB_NS = "http://purl.org/net/biblio#"
LINK_NS = "http://purl.org/rss/1.0/modules/link/"
DCTERMS_NS = "http://purl.org/dc/terms/"
PRISM_NS = "http://prismstandard.org/namespaces/1.2/basic/"
NSMAP = {
    "rdf": RDF_NS,
    "z": Z_NS,
    "dc": DC_NS,
    "foaf": FOAF_NS,
    "bib": BIB_NS,
    "link": LINK_NS,
    "dcterms": DCTERMS_NS,
    "prism": PRISM_NS,
}


@dataclass(frozen=True)
class ParsedAttachment:
    """Zotero RDF 附件节点。"""

    source_key: str
    attachment_name: str
    mime_type: str


@dataclass(frozen=True)
class ParsedItem:
    """Zotero RDF 文献节点。"""

    source_key: str
    entry_type: str
    title: str
    authors: str
    year: str
    abstract: str
    keywords: str
    cite_key: str
    language: str
    doi: str
    attachment_refs: tuple[str, ...]
    origin_path: str


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _resolve_relative_path(base_dir: Path, raw_path: str | Path) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (base_dir / path)


def _iter_rdf_files(rdf_path: Path) -> list[Path]:
    if rdf_path.is_dir():
        return [path for path in sorted(rdf_path.rglob("*.rdf")) if path.is_file()]
    if rdf_path.is_file():
        return [rdf_path]
    return []


def _normalize_key(value: Any) -> str:
    text = _stringify(value)
    if text.startswith("#"):
        text = text[1:]
    return text


def _find_text(node: ET.Element, xpath: str) -> str:
    value = node.findtext(xpath, default="", namespaces=NSMAP)
    if _stringify(value):
        return _stringify(value)
    return _stringify("".join(node.itertext()))


def _is_attachment_node(node: ET.Element) -> bool:
    item_type = _find_text(node, "z:itemType").lower()
    return node.tag.endswith("Attachment") or item_type == "attachment"


def _is_item_node(node: ET.Element) -> bool:
    if _is_attachment_node(node):
        return False
    local_name = node.tag.rsplit("}", 1)[-1]
    if local_name in {"Journal", "Publisher", "Library", "Collection"}:
        return False
    if _find_text(node, "z:citationKey"):
        return True
    if node.find(".//bib:authors", NSMAP) is not None:
        return True
    if _find_text(node, "dc:title") and _find_text(node, "dc:date"):
        return True
    if _find_text(node, "dcterms:abstract") or _find_text(node, "dc:description"):
        return True
    if node.find("link:link", NSMAP) is not None:
        return True
    return False


def _parse_authors(node: ET.Element) -> str:
    authors: list[str] = []
    for person in node.findall(".//bib:authors/rdf:Seq/rdf:li/foaf:Person", NSMAP):
        surname = _find_text(person, "foaf:surname")
        given_name = _find_text(person, "foaf:givenName")
        if surname and given_name:
            authors.append(f"{surname}, {given_name}")
        elif surname:
            authors.append(surname)
        elif given_name:
            authors.append(given_name)
    return " and ".join(authors)


def _parse_keywords(node: ET.Element) -> str:
    keywords: list[str] = []
    for subject in node.findall("dc:subject", NSMAP):
        text = _find_text(subject, ".")
        if not text:
            continue
        keywords.append(text)
    return "; ".join(dict.fromkeys(keywords))


def _parse_doi(node: ET.Element) -> str:
    for identifier in node.findall("dc:identifier", NSMAP):
        text = _find_text(identifier, ".")
        if not text:
            continue
        lowered = text.lower()
        if lowered.startswith("doi"):
            return text.split(" ", 1)[-1].strip()
        if "10." in text and "/" in text:
            return text
    return ""


def _normalize_entry_type(raw_type: str) -> str:
    value = _stringify(raw_type).lower()
    mapping = {
        "journalarticle": "article",
        "preprint": "article",
        "conferencepaper": "inproceedings",
        "book": "book",
        "thesis": "phdthesis",
        "report": "techreport",
        "webpage": "misc",
        "document": "misc",
    }
    return mapping.get(value, value or "misc")


def _parse_rdf_file(rdf_file: Path) -> tuple[list[ParsedItem], dict[str, ParsedAttachment]]:
    tree = ET.parse(rdf_file)
    root = tree.getroot()

    items: list[ParsedItem] = []
    attachments: dict[str, ParsedAttachment] = {}

    for node in root.iter():
        source_key = _normalize_key(node.attrib.get(f"{{{RDF_NS}}}about"))
        if not source_key:
            continue

        if _is_attachment_node(node):
            attachment_name = _find_text(node, "dc:title")
            mime_type = _find_text(node, "link:type") or ""
            attachments[source_key] = ParsedAttachment(
                source_key=source_key,
                attachment_name=attachment_name,
                mime_type=mime_type,
            )
            continue

        if not _is_item_node(node):
            continue

        title = _find_text(node, "dc:title")
        authors = _parse_authors(node)
        year = _find_text(node, "dc:date")
        abstract = _find_text(node, "dcterms:abstract") or _find_text(node, "dc:description")
        keywords = _parse_keywords(node)
        cite_key = _find_text(node, "z:citationKey")
        language = _find_text(node, "z:language")
        doi = _parse_doi(node)
        attachment_refs = tuple(
            _normalize_key(link.attrib.get(f"{{{RDF_NS}}}resource"))
            for link in node.findall("link:link", NSMAP)
            if _normalize_key(link.attrib.get(f"{{{RDF_NS}}}resource"))
        )

        if not title and not authors and not attachment_refs:
            continue

        first_author = extract_first_author(authors)
        year_int = parse_year_int(year)
        title_norm = clean_title_text(title)
        items.append(
            ParsedItem(
                source_key=source_key,
                entry_type=_normalize_entry_type(_find_text(node, "z:itemType") or node.tag.rsplit("}", 1)[-1]),
                title=title,
                authors=authors,
                year=year if year_int is not None else "",
                abstract=abstract,
                keywords=keywords,
                cite_key=cite_key or build_cite_key(first_author, "" if year_int is None else str(year_int), title_norm),
                language=language,
                doi=doi,
                attachment_refs=attachment_refs,
                origin_path=str(rdf_file.resolve()),
            )
        )

    return items, attachments


def _compute_checksum(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_attachment_search_index(attachments_root: Path | None) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    if attachments_root is None or not attachments_root.exists():
        return index
    for file_path in attachments_root.rglob("*"):
        if not file_path.is_file():
            continue
        index.setdefault(file_path.name.lower(), []).append(file_path.resolve())
    return index


def _resolve_attachment_path(attachment_name: str, attachment_index: dict[str, list[Path]]) -> tuple[str, str]:
    if not attachment_name:
        return "", "missing_name"
    candidates = attachment_index.get(Path(attachment_name).name.lower(), [])
    if len(candidates) == 1:
        return str(candidates[0]), "exact_name"
    if len(candidates) > 1:
        return "", "ambiguous_name"
    return "", "missing_file"


def _load_existing_literature_index(content_db_path: Path | None) -> dict[str, list[str]]:
    if content_db_path is None or not content_db_path.exists():
        return {}

    try:
        existing_df = load_literatures_df(content_db_path)
    except Exception:
        return {}

    index: dict[str, list[str]] = {}
    for _, row in existing_df.iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        if not uid_literature:
            continue
        cite_key = _stringify(row.get("cite_key")).lower()
        title = _stringify(row.get("title"))
        first_author = _stringify(row.get("first_author"))
        year = _stringify(row.get("year"))
        title_signature = f"{clean_title_text(title)}|{extract_first_author(first_author)}|{parse_year_int(year) or ''}".lower()
        doi = _stringify(row.get("doi") or row.get("identifier")).lower()
        for key in {f"cite:{cite_key}" if cite_key else "", f"sig:{title_signature}" if title_signature else "", f"doi:{doi}" if doi else ""}:
            if not key:
                continue
            index.setdefault(key, []).append(uid_literature)
    return index


def _resolve_existing_uid(item: ParsedItem, existing_index: dict[str, list[str]]) -> tuple[str, str]:
    cite_key = _stringify(item.cite_key).lower()
    if cite_key:
        candidates = existing_index.get(f"cite:{cite_key}", [])
        if len(candidates) == 1:
            return str(candidates[0]), "cite_key"

    if item.doi:
        candidates = existing_index.get(f"doi:{item.doi.lower()}", [])
        if len(candidates) == 1:
            return str(candidates[0]), "doi"

    title_signature = f"{clean_title_text(item.title)}|{extract_first_author(item.authors)}|{parse_year_int(item.year) or ''}".lower()
    if title_signature:
        candidates = existing_index.get(f"sig:{title_signature}", [])
        if len(candidates) == 1:
            return str(candidates[0]), "title_year_author"

    title_norm = clean_title_text(item.title)
    first_author = extract_first_author(item.authors)
    year_int = parse_year_int(item.year)
    return generate_uid(first_author, year_int, title_norm), "generated"


def _merge_text(existing: str, candidate: str) -> str:
    if not _stringify(existing):
        return _stringify(candidate)
    if not _stringify(candidate):
        return _stringify(existing)
    return _stringify(candidate) if len(_stringify(candidate)) > len(_stringify(existing)) else _stringify(existing)


def _build_item_row(item: ParsedItem, uid_literature: str, match_reason: str, primary_attachment_name: str, has_fulltext: int, source_path: str) -> dict[str, Any]:
    first_author = extract_first_author(item.authors)
    year_int = parse_year_int(item.year)
    title_norm = clean_title_text(item.title)
    return {
        "uid_literature": uid_literature,
        "cite_key": item.cite_key or build_cite_key(first_author, item.year, title_norm),
        "title": item.title,
        "clean_title": clean_title_text(item.title),
        "title_norm": title_norm,
        "authors": item.authors,
        "first_author": first_author,
        "year": "" if year_int is None else str(year_int),
        "entry_type": item.entry_type or "article",
        "abstract": item.abstract,
        "keywords": item.keywords,
        "is_placeholder": 0,
        "has_fulltext": int(has_fulltext),
        "primary_attachment_name": primary_attachment_name,
        "standard_note_uid": "",
        "source_type": "zotero_rdf",
        "origin_path": source_path,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "match_reason": match_reason,
    }


def _build_attachment_row(item_row: dict[str, Any], item: ParsedItem, attachment: ParsedAttachment, source_path: str, storage_path: str, checksum: str, is_primary: int, relation_reason: str) -> dict[str, Any]:
    file_ext = Path(attachment.attachment_name).suffix.lower().lstrip(".")
    attachment_type = "fulltext" if file_ext == "pdf" else "asset"
    uid_attachment = build_stable_attachment_uid(
        str(item_row["uid_literature"]),
        checksum=checksum,
        source_path=source_path or attachment.attachment_name,
        attachment_name=attachment.attachment_name,
        storage_path=storage_path,
        fallback_uid=attachment.source_key,
    )
    return {
        "uid_attachment": uid_attachment,
        "uid_literature": str(item_row["uid_literature"]),
        "attachment_name": attachment.attachment_name,
        "attachment_type": attachment_type,
        "file_ext": file_ext,
        "storage_path": storage_path,
        "source_path": source_path,
        "checksum": checksum,
        "is_primary": int(is_primary),
        "status": "available" if storage_path else "missing",
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "relation_reason": relation_reason,
        "source_key": attachment.source_key,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    frame = pd.DataFrame(rows, columns=columns)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def convert_zotero_rdf_to_a020_incremental_package(payload: dict[str, Any]) -> dict[str, Any]:
    """将 Zotero RDF 规范化为 A020 可直接消费的增量输入包。

    Args:
        payload: 输入参数字典。
            - rdf_path: Zotero RDF 文件或目录（必填）。
            - workspace_root: 工作区根目录（必填，用于解析相对路径）。
            - content_db_path: 现有 content.db 路径（可选，用于复用已存在的 uid_literature）。
            - attachments_root: Zotero 导出附件根目录（可选，用于把附件名映射成实际文件）。
            - output_dir: 输出目录（可选，默认写入 workspace/tasks 下的独立目录）。
            - dry_run: 是否仅预演（可选；工具仍会输出中间文件）。

    Returns:
        dict[str, Any]: 包含输出路径、统计信息与匹配摘要的结果字典。

    Raises:
        ValueError: 当 rdf_path 或 workspace_root 缺失，或 RDF 解析失败时抛出。

    Examples:
        >>> result = convert_zotero_rdf_to_a020_incremental_package({
        ...     "rdf_path": "data/zotero.rdf",
        ...     "workspace_root": "workspace",
        ... })
        >>> isinstance(result, dict)
        True
    """

    workspace_root_raw = _stringify(payload.get("workspace_root"))
    if not workspace_root_raw:
        raise ValueError("workspace_root 不能为空")
    workspace_root = Path(workspace_root_raw).expanduser().resolve()

    rdf_path_raw = _stringify(payload.get("rdf_path"))
    if not rdf_path_raw:
        raise ValueError("rdf_path 不能为空")

    rdf_path = _resolve_relative_path(workspace_root, rdf_path_raw).resolve()
    if not rdf_path.exists():
        raise ValueError(f"未找到 RDF 路径: {rdf_path}")

    content_db_raw = _stringify(payload.get("content_db_path")) or _stringify(payload.get("content_db"))
    content_db_path = _resolve_relative_path(workspace_root, content_db_raw).resolve() if content_db_raw else None
    if content_db_path is not None and not content_db_path.exists():
        content_db_path = None

    attachments_root_raw = _stringify(payload.get("attachments_root"))
    attachments_root = _resolve_relative_path(workspace_root, attachments_root_raw).resolve() if attachments_root_raw else None
    if attachments_root is not None and not attachments_root.exists():
        attachments_root = None

    output_dir_raw = _stringify(payload.get("output_dir"))
    if output_dir_raw:
        output_dir = _resolve_relative_path(workspace_root, output_dir_raw).resolve()
    else:
        output_dir = (workspace_root / "workspace" / "tasks" / f"zotero_rdf_to_a020_{datetime.now().strftime('%Y%m%d%H%M%S')}").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / "run_log.txt"
    summary_path = output_dir / "run_summary.md"
    manifest_path = output_dir / "literature-manifest.json"
    unmatched_path = output_dir / "unmatched_items.json"
    items_csv = output_dir / "literature_items.csv"
    files_csv = output_dir / "literature_files.csv"

    log_lines: list[str] = []

    def log(message: str) -> None:
        log_lines.append(f"[{_utc_now_iso()}] {message}")

    try:
        rdf_files = _iter_rdf_files(rdf_path)
        if not rdf_files:
            raise ValueError(f"未发现可解析的 RDF 文件: {rdf_path}")

        attachment_index = _build_attachment_search_index(attachments_root)
        existing_index = _load_existing_literature_index(content_db_path)

        parsed_items: list[ParsedItem] = []
        parsed_attachments: dict[str, ParsedAttachment] = {}
        for rdf_file in rdf_files:
            log(f"解析 RDF 文件: {rdf_file}")
            items, attachments = _parse_rdf_file(rdf_file)
            parsed_items.extend(items)
            parsed_attachments.update(attachments)

        item_rows_by_uid: dict[str, dict[str, Any]] = {}
        item_summary_rows: list[dict[str, Any]] = []
        attachment_rows: list[dict[str, Any]] = []
        unmatched_rows: list[dict[str, Any]] = []

        for item in parsed_items:
            resolved_uid, match_reason = _resolve_existing_uid(item, existing_index)
            item_row = _build_item_row(
                item,
                resolved_uid,
                match_reason,
                primary_attachment_name="",
                has_fulltext=0,
                source_path=item.origin_path,
            )

            related_attachments: list[dict[str, Any]] = []
            missing_attachment_names: list[str] = []
            for attachment_ref in item.attachment_refs:
                attachment = parsed_attachments.get(attachment_ref)
                if attachment is None:
                    missing_attachment_names.append(attachment_ref)
                    continue
                resolved_path, resolve_reason = _resolve_attachment_path(attachment.attachment_name, attachment_index)
                if not resolved_path:
                    missing_attachment_names.append(attachment.attachment_name or attachment.source_key)
                    continue

                source_path = resolved_path
                checksum = _compute_checksum(Path(resolved_path)) if Path(resolved_path).exists() else ""
                attachment_row = _build_attachment_row(
                    item_row,
                    item,
                    attachment,
                    source_path=source_path,
                    storage_path=resolved_path,
                    checksum=checksum,
                    is_primary=0,
                    relation_reason=resolve_reason,
                )
                related_attachments.append(attachment_row)

            if related_attachments:
                pdf_candidates = [row for row in related_attachments if str(row.get("file_ext") or "").lower() == "pdf"]
                primary_candidate = pdf_candidates[0] if pdf_candidates else related_attachments[0]
                for row in related_attachments:
                    row["is_primary"] = 1 if row is primary_candidate else 0
                    row["status"] = "available" if row.get("storage_path") else "missing"
                    attachment_rows.append(row)

                item_row["has_fulltext"] = 1 if pdf_candidates else 0
                item_row["primary_attachment_name"] = str(primary_candidate.get("attachment_name") or "")
            else:
                item_row["has_fulltext"] = 0
                item_row["primary_attachment_name"] = ""

            existing_item_row = item_rows_by_uid.get(str(item_row["uid_literature"]))
            if existing_item_row is None:
                item_rows_by_uid[str(item_row["uid_literature"])] = item_row
            else:
                merged_row = dict(existing_item_row)
                merged_row["title"] = _merge_text(str(existing_item_row.get("title") or ""), str(item_row.get("title") or ""))
                merged_row["authors"] = _merge_text(str(existing_item_row.get("authors") or ""), str(item_row.get("authors") or ""))
                merged_row["abstract"] = _merge_text(str(existing_item_row.get("abstract") or ""), str(item_row.get("abstract") or ""))
                merged_row["keywords"] = _merge_text(str(existing_item_row.get("keywords") or ""), str(item_row.get("keywords") or ""))
                merged_row["primary_attachment_name"] = str(existing_item_row.get("primary_attachment_name") or item_row.get("primary_attachment_name") or "")
                merged_row["has_fulltext"] = int(bool(existing_item_row.get("has_fulltext")) or bool(item_row.get("has_fulltext")))
                merged_row["updated_at"] = _utc_now_iso()
                merged_row["match_reason"] = str(existing_item_row.get("match_reason") or item_row.get("match_reason") or "")
                item_rows_by_uid[str(item_row["uid_literature"])] = merged_row

            item_summary_rows.append(
                {
                    "source_key": item.source_key,
                    "uid_literature": str(item_row["uid_literature"]),
                    "cite_key": str(item_row["cite_key"]),
                    "match_reason": match_reason,
                    "attachment_count": len(related_attachments),
                    "primary_attachment_name": str(item_row["primary_attachment_name"]),
                    "has_fulltext": int(item_row["has_fulltext"]),
                    "origin_path": item.origin_path,
                }
            )

            if missing_attachment_names:
                unmatched_rows.append(
                    {
                        "source_key": item.source_key,
                        "uid_literature": str(item_row["uid_literature"]),
                        "cite_key": str(item_row["cite_key"]),
                        "title": str(item_row["title"]),
                        "missing_attachments": missing_attachment_names,
                        "origin_path": item.origin_path,
                    }
                )

        item_rows = sorted(item_rows_by_uid.values(), key=lambda row: (str(row.get("cite_key") or ""), str(row.get("title") or "")))
        for index, row in enumerate(item_rows, start=1):
            row["id"] = index

        attachment_dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in attachment_rows:
            relation_key = (str(row.get("uid_literature") or ""), str(row.get("uid_attachment") or ""), str(row.get("attachment_name") or ""))
            if relation_key not in attachment_dedup:
                attachment_dedup[relation_key] = row

        final_attachment_rows = list(attachment_dedup.values())
        for index, row in enumerate(final_attachment_rows, start=1):
            row["id"] = index

        item_columns = [
            "id",
            "uid_literature",
            "cite_key",
            "title",
            "clean_title",
            "title_norm",
            "authors",
            "first_author",
            "year",
            "entry_type",
            "abstract",
            "keywords",
            "is_placeholder",
            "has_fulltext",
            "primary_attachment_name",
            "standard_note_uid",
            "source_type",
            "origin_path",
            "created_at",
            "updated_at",
        ]
        file_columns = [
            "id",
            "uid_attachment",
            "uid_literature",
            "attachment_name",
            "attachment_type",
            "file_ext",
            "storage_path",
            "source_path",
            "checksum",
            "is_primary",
            "status",
            "created_at",
            "updated_at",
        ]

        _write_csv(items_csv, item_rows, item_columns)
        _write_csv(files_csv, final_attachment_rows, file_columns)

        output_payload = {
            "schema_version": "zotero-rdf-to-a020-incremental-v1",
            "status": "WARN" if unmatched_rows else "PASS",
            "source": {
                "rdf_path": str(rdf_path),
                "workspace_root": str(workspace_root),
                "content_db_path": str(content_db_path) if content_db_path is not None else "",
                "attachments_root": str(attachments_root) if attachments_root is not None else "",
            },
            "outputs": {
                "output_dir": str(output_dir),
                "literature_items_csv": str(items_csv),
                "literature_files_csv": str(files_csv),
                "literature_manifest_json": str(manifest_path),
                "run_log_path": str(log_path),
                "run_summary_path": str(summary_path),
                "unmatched_items_path": str(unmatched_path),
            },
            "counts": {
                "rdf_files": len(rdf_files),
                "items_total": len(item_rows),
                "attachments_total": len(final_attachment_rows),
                "items_matched_existing": sum(1 for row in item_rows if str(row.get("match_reason") or "") in {"cite_key", "doi", "title_year_author"}),
                "items_generated": sum(1 for row in item_rows if str(row.get("match_reason") or "") == "generated"),
                "items_with_fulltext": sum(1 for row in item_rows if int(row.get("has_fulltext") or 0) == 1),
                "unmatched_items": len(unmatched_rows),
            },
            "items": item_summary_rows,
            "unmatched_items": unmatched_rows,
            "dry_run": bool(payload.get("dry_run", True)),
        }

        log(f"输出主表行数: {len(item_rows)}")
        log(f"输出附件行数: {len(final_attachment_rows)}")
        log(f"复用已有文献数: {output_payload['counts']['items_matched_existing']}")
        log(f"未匹配条目数: {len(unmatched_rows)}")

        _write_json(manifest_path, output_payload)
        _write_json(unmatched_path, {"items": unmatched_rows, "count": len(unmatched_rows)})
        _write_text(
            summary_path,
            "\n".join(
                [
                    "# Zotero RDF 转 A020 增量导入结果",
                    "",
                    f"- 状态: {output_payload['status']}",
                    f"- RDF 文件数: {len(rdf_files)}",
                    f"- 文献条目数: {len(item_rows)}",
                    f"- 附件关系数: {len(final_attachment_rows)}",
                    f"- 复用已有文献数: {output_payload['counts']['items_matched_existing']}",
                    f"- 新生成文献数: {output_payload['counts']['items_generated']}",
                    f"- 未匹配条目数: {len(unmatched_rows)}",
                    "",
                    "## 输出文件",
                    f"- {items_csv.name}",
                    f"- {files_csv.name}",
                    f"- {manifest_path.name}",
                    f"- {unmatched_path.name}",
                    f"- {log_path.name}",
                ]
            ),
        )
        _write_text(log_path, "\n".join(log_lines))

        return {
            "status": output_payload["status"],
            "output_dir": str(output_dir),
            "literature_items_csv": str(items_csv),
            "literature_files_csv": str(files_csv),
            "literature_manifest_json": str(manifest_path),
            "run_log_path": str(log_path),
            "run_summary_path": str(summary_path),
            "unmatched_items_path": str(unmatched_path),
            "counts": output_payload["counts"],
        }
    except Exception as exc:
        log(f"失败: {exc}")
        _write_text(log_path, "\n".join(log_lines))
        _write_text(
            summary_path,
            "\n".join(
                [
                    "# Zotero RDF 转 A020 增量导入结果",
                    "",
                    "- 状态: FAIL",
                    f"- 错误: {exc}",
                    f"- RDF 路径: {rdf_path if 'rdf_path' in locals() else ''}",
                ]
            ),
        )
        _write_json(
            manifest_path,
            {
                "schema_version": "zotero-rdf-to-a020-incremental-v1",
                "status": "FAIL",
                "error": str(exc),
                "source": {
                    "rdf_path": str(rdf_path) if 'rdf_path' in locals() else rdf_path_raw,
                    "workspace_root": str(workspace_root) if 'workspace_root' in locals() else _stringify(payload.get("workspace_root")),
                },
                "outputs": {
                    "output_dir": str(output_dir),
                    "literature_items_csv": str(items_csv),
                    "literature_files_csv": str(files_csv),
                    "literature_manifest_json": str(manifest_path),
                    "run_log_path": str(log_path),
                    "run_summary_path": str(summary_path),
                    "unmatched_items_path": str(unmatched_path),
                },
            },
        )
        _write_json(unmatched_path, {"items": [], "count": 0, "error": str(exc)})
        raise


__all__ = ["convert_zotero_rdf_to_a020_incremental_package"]