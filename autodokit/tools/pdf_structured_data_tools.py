"""PDF 结构化结果与分块工具。"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from autodokit.tools.pdf_elements_extractors import extract_references_from_full_text


STRUCTURED_SCHEMA_VERSION = "aok.pdf_structured.v3"
DEFAULT_CHUNK_SET_STATUS = "ready"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def normalize_full_text(text: str) -> str:
    """规范化全文文本。

    Args:
        text: 原始全文文本。

    Returns:
        规整后的全文文本。
    """

    normalized = str(text or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"(?<=[A-Za-z])-\n(?=[A-Za-z])", "", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", normalized)
    normalized = re.sub(r"\u000c", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    return normalized.strip()


def split_text_to_sentences(text: str) -> List[Dict[str, Any]]:
    """把全文切分为句子对象列表。"""

    normalized = normalize_full_text(text)
    if not normalized:
        return []

    parts = re.split(r"(?<=[。！？；!?;])\s*", normalized)
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    cursor = 0
    for part in parts:
        sentence = re.sub(r"\s+", " ", part.strip(" \t\n-•"))
        if len(sentence) < 8:
            cursor += len(part)
            continue
        if sentence in seen:
            cursor += len(part)
            continue
        seen.add(sentence)
        start = normalized.find(sentence, cursor)
        if start < 0:
            start = cursor
        end = start + len(sentence)
        rows.append(
            {
                "sentence_id": f"sentence_{len(rows) + 1:04d}",
                "index": len(rows) + 1,
                "text": sentence,
                "sentence": sentence,
                "char_start": start,
                "char_end": end,
            }
        )
        cursor = end
    return rows


def split_text_to_paragraphs(text: str) -> List[Dict[str, Any]]:
    """把全文切分为段落对象列表。"""

    raw_text = normalize_full_text(text)
    if not raw_text:
        return []

    raw_lines = [line.strip() for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    blocks: List[str] = []
    buffer: List[str] = []
    for line in raw_lines:
        if not line:
            if buffer:
                blocks.append(" ".join(buffer).strip())
                buffer = []
            continue
        buffer.append(line)
    if buffer:
        blocks.append(" ".join(buffer).strip())

    if len(blocks) <= 1:
        sentence_rows = split_text_to_sentences(raw_text)
        blocks = []
        sentence_buffer: List[str] = []
        char_count = 0
        for row in sentence_rows:
            sentence = _stringify(row.get("text"))
            if not sentence:
                continue
            sentence_buffer.append(sentence)
            char_count += len(sentence)
            if len(sentence_buffer) >= 3 or char_count >= 280:
                blocks.append(" ".join(sentence_buffer).strip())
                sentence_buffer = []
                char_count = 0
        if sentence_buffer:
            blocks.append(" ".join(sentence_buffer).strip())

    rows: List[Dict[str, Any]] = []
    cursor = 0
    for block in blocks:
        paragraph = re.sub(r"\s+", " ", block).strip()
        if len(paragraph) < 20:
            continue
        start = raw_text.find(paragraph, cursor)
        if start < 0:
            start = cursor
        end = start + len(paragraph)
        rows.append(
            {
                "paragraph_id": f"paragraph_{len(rows) + 1:04d}",
                "index": len(rows) + 1,
                "text": paragraph,
                "char_start": start,
                "char_end": end,
            }
        )
        cursor = end
    return rows


def _pick_segment_rows(
    paragraphs: Sequence[Dict[str, Any]],
    *,
    keywords: Iterable[str],
    limit: int,
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for row in paragraphs:
        text = _stringify(row.get("text"))
        if not text:
            continue
        lowered = text.lower()
        if any(_stringify(keyword).lower() in lowered for keyword in keywords if _stringify(keyword)):
            output.append(
                {
                    "text": text,
                    "char_start": row.get("char_start"),
                    "char_end": row.get("char_end"),
                    "paragraph_id": row.get("paragraph_id"),
                }
            )
        if len(output) >= limit:
            break
    return output


def build_segments_map(full_text: str, references: Sequence[Dict[str, Any]] | None = None) -> Dict[str, List[Dict[str, Any]]]:
    """根据全文构建段落级 segments 结构。"""

    paragraphs = split_text_to_paragraphs(full_text)
    reference_rows: List[Dict[str, Any]] = []
    for item in references or []:
        reference_text = _stringify(item.get("raw_text") or item.get("raw") or item.get("text"))
        if not reference_text:
            continue
        reference_rows.append(
            {
                "text": reference_text,
                "raw_text": reference_text,
                "matched_uid_literature": _stringify(item.get("matched_uid_literature")),
                "matched_cite_key": _stringify(item.get("matched_cite_key")),
                "char_start": item.get("char_start"),
                "char_end": item.get("char_end"),
            }
        )

    return {
        "abstract": _pick_segment_rows(paragraphs, keywords=("摘要", "abstract"), limit=2),
        "conclusion": _pick_segment_rows(paragraphs, keywords=("结论", "conclusion", "总结"), limit=2),
        "references": reference_rows,
        "future_directions": _pick_segment_rows(paragraphs, keywords=("未来", "展望", "future", "建议"), limit=3),
        "method": _pick_segment_rows(paragraphs, keywords=("方法", "数据", "模型", "method"), limit=3),
    }


def build_units_map(full_text: str) -> Dict[str, List[Dict[str, Any]]]:
    """根据全文构建细粒度 units。"""

    paragraphs = split_text_to_paragraphs(full_text)
    sentences = split_text_to_sentences(full_text)
    return {
        "headings": [],
        "paragraphs": paragraphs,
        "sentences": sentences,
        "ordered_lists": [],
        "unordered_lists": [],
        "inline_formulas": [],
        "block_formulas": [],
        "inline_code": [],
        "block_code": [],
        "citations": [],
    }


def build_structured_data_payload(
    *,
    pdf_path: Path,
    backend: str,
    backend_family: str,
    task_type: str,
    full_text: str,
    extract_error: str | None,
    text_meta: Dict[str, Any] | None = None,
    uid_literature: str = "",
    cite_key: str = "",
    title: str = "",
    year: str = "",
    references: Sequence[Dict[str, Any]] | None = None,
    images: Sequence[Dict[str, Any]] | None = None,
    tables: Sequence[Dict[str, Any]] | None = None,
    formulas: Sequence[Dict[str, Any]] | None = None,
    layout: Dict[str, Any] | None = None,
    capabilities: Dict[str, Any] | None = None,
    artifacts: Dict[str, Any] | None = None,
    extra_fields: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """构建统一 `aok.pdf_structured.v3` 结果。"""

    normalized_text = normalize_full_text(full_text)
    if references is None:
        parsed_refs, _ = extract_references_from_full_text(normalized_text)
        references = parsed_refs

    segments = build_segments_map(normalized_text, references)
    units = build_units_map(normalized_text)
    source_payload: Dict[str, Any] = {
        "uid_literature": _stringify(uid_literature),
        "cite_key": _stringify(cite_key),
        "title": _stringify(title),
        "year": _stringify(year),
        "pdf_name": pdf_path.name,
        "pdf_abs_path": str(pdf_path),
        "backend": backend,
    }
    payload: Dict[str, Any] = {
        "schema": STRUCTURED_SCHEMA_VERSION,
        "source": source_payload,
        "parse_profile": {
            "task_type": _stringify(task_type) or "full_fine_grained",
            "backend_family": _stringify(backend_family) or backend,
            "backend_name": backend,
            "created_at": _utc_now_iso(),
        },
        "text": {
            "full_text": normalized_text,
            "extract_error": extract_error,
            "meta": dict(text_meta or {}),
        },
        "segments": segments,
        "units": units,
        "references": list(references or []),
        "images": list(images or []),
        "tables": list(tables or []),
        "formulas": list(formulas or []),
        "layout": dict(layout or {"coord_system": "unknown", "pages": [], "elements": [], "sources": [], "parse_error": None}),
        "artifacts": dict(artifacts or {}),
        "capabilities": dict(capabilities or {}),
    }
    if extra_fields:
        payload.update(dict(extra_fields))
    return payload


def load_structured_data(path: Path) -> Dict[str, Any]:
    """读取结构化 JSON 文件。"""

    if not path.is_absolute():
        raise ValueError(f"structured_json_path 必须是绝对路径：{path}")
    if not path.exists() or not path.is_file():
        raise ValueError(f"structured_json_path 必须是存在的文件：{path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def extract_reference_lines_from_structured_data(structured_data: Dict[str, Any]) -> Dict[str, Any]:
    """从结构化结果中提取 A05 兼容的引文扫描结果。"""

    references = structured_data.get("references") if isinstance(structured_data.get("references"), list) else []
    segments = structured_data.get("segments") if isinstance(structured_data.get("segments"), dict) else {}
    segment_refs = segments.get("references") if isinstance(segments.get("references"), list) else []

    lines: List[str] = []
    details: List[Dict[str, Any]] = []
    for item in references:
        reference_text = _stringify(item.get("raw_text") or item.get("raw") or item.get("text"))
        if not reference_text or reference_text in lines:
            continue
        lines.append(reference_text)
        detail = dict(item)
        detail.setdefault("reference_text", reference_text)
        detail.setdefault("suspicious_merged", 0)
        detail.setdefault("noise_trimmed", 0)
        details.append(detail)

    if not lines:
        for item in segment_refs:
            reference_text = _stringify(item.get("raw_text") or item.get("text"))
            if not reference_text or reference_text in lines:
                continue
            lines.append(reference_text)
            details.append(
                {
                    "reference_text": reference_text,
                    "suspicious_merged": 0,
                    "noise_trimmed": 0,
                }
            )

    text_payload = structured_data.get("text") if isinstance(structured_data.get("text"), dict) else {}
    source_payload = structured_data.get("source") if isinstance(structured_data.get("source"), dict) else {}
    return {
        "attachment_path": _stringify(source_payload.get("pdf_abs_path")),
        "attachment_type": "structured_json",
        "extract_status": "ok" if lines else "empty",
        "extract_method": _stringify(source_payload.get("backend")) or "structured_json",
        "reference_lines": lines,
        "reference_line_details": details,
        "full_text": _stringify(text_payload.get("full_text")),
        "pending_reason": "" if lines else "structured_no_references",
    }


def build_doc_record_from_structured_data(structured_data: Dict[str, Any], *, source_path: Path | None = None) -> Dict[str, Any]:
    """把结构化结果转换为旧消费者可用的文档记录。"""

    source = structured_data.get("source") if isinstance(structured_data.get("source"), dict) else {}
    text_payload = structured_data.get("text") if isinstance(structured_data.get("text"), dict) else {}
    segments = structured_data.get("segments") if isinstance(structured_data.get("segments"), dict) else {}
    abstract_segments = segments.get("abstract") if isinstance(segments.get("abstract"), list) else []
    abstract = "\n".join(_stringify(item.get("text")) for item in abstract_segments if _stringify(item.get("text")))
    cite_key = _stringify(source.get("cite_key"))
    uid_literature = _stringify(source.get("uid_literature"))
    doc_id = cite_key or uid_literature or (source_path.stem.replace(".structured", "") if source_path else "")
    return {
        "doc_id": doc_id,
        "uid": uid_literature or doc_id,
        "uid_literature": uid_literature,
        "cite_key": cite_key,
        "title": _stringify(source.get("title")) or doc_id or _stringify(source.get("pdf_name")),
        "year": _stringify(source.get("year")),
        "abstract": abstract,
        "keywords": _stringify(source.get("keywords")),
        "text": _stringify(text_payload.get("full_text")),
        "meta": {
            "source_path": str(source_path) if source_path else _stringify(source.get("pdf_abs_path")),
            "structured_abs_path": str(source_path) if source_path else "",
            "backend": _stringify(source.get("backend")),
            "schema": _stringify(structured_data.get("schema")),
            "title": _stringify(source.get("title")),
            "year": _stringify(source.get("year")),
            "abstract": abstract,
            "cite_key": cite_key,
            "uid_literature": uid_literature,
        },
    }


def load_single_document_record(
    *,
    uid: str = "",
    doc_id: str = "",
    structured_json_path: str = "",
    structured_dir: str = "",
    content_db: str = "",
    references_db: str = "",
) -> Dict[str, Any]:
    """优先从结构化结果读取单篇文献记录。"""

    resolved_uid = _stringify(uid)
    resolved_doc_id = _stringify(doc_id)
    if structured_json_path:
        path = Path(structured_json_path)
        payload = load_structured_data(path)
        return build_doc_record_from_structured_data(payload, source_path=path)

    db_path_text = _stringify(content_db) or _stringify(references_db)
    if db_path_text:
        from autodokit.tools.bibliodb_sqlite import load_literatures_df

        db_path = Path(db_path_text)
        table = load_literatures_df(db_path)
        if not table.empty:
            target = table
            if resolved_doc_id:
                mask = (
                    table.get("cite_key", []).astype(str) == resolved_doc_id
                    if "cite_key" in table.columns
                    else None
                )
                if mask is not None:
                    target = table.loc[mask]
            elif resolved_uid:
                mask = table.get("uid_literature", []).astype(str) == resolved_uid if "uid_literature" in table.columns else None
                if mask is not None:
                    target = table.loc[mask]
            if not target.empty:
                row = target.iloc[0].to_dict()
                structured_abs_path = _stringify(row.get("structured_abs_path"))
                if structured_abs_path:
                    path = Path(structured_abs_path)
                    if path.exists():
                        payload = load_structured_data(path)
                        return build_doc_record_from_structured_data(payload, source_path=path)

    if structured_dir:
        root = Path(structured_dir)
        if not root.is_absolute():
            raise ValueError(f"structured_dir 必须是绝对路径：{root}")
        candidates = [
            root / f"{resolved_doc_id}.structured.json",
            root / f"{resolved_uid}.structured.json",
            root / f"{resolved_doc_id}.json",
            root / f"{resolved_uid}.json",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                payload = load_structured_data(candidate)
                return build_doc_record_from_structured_data(payload, source_path=candidate)
        for candidate in sorted(root.glob("*.structured.json")):
            payload = load_structured_data(candidate)
            source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
            if resolved_uid and _stringify(source.get("uid_literature")) == resolved_uid:
                return build_doc_record_from_structured_data(payload, source_path=candidate)
            if resolved_doc_id and _stringify(source.get("cite_key")) == resolved_doc_id:
                return build_doc_record_from_structured_data(payload, source_path=candidate)

    raise ValueError("未找到匹配的 structured.json。请检查 uid/doc_id 或结构化输入路径。")


def load_document_records_from_structured_source(
    *,
    structured_dir: str = "",
    content_db: str = "",
    references_db: str = "",
    max_items: int | None = None,
) -> List[Dict[str, Any]]:
    """批量读取结构化文档记录。"""

    records: List[Dict[str, Any]] = []
    seen_paths: set[str] = set()

    db_path_text = _stringify(content_db) or _stringify(references_db)
    if db_path_text:
        from autodokit.tools.bibliodb_sqlite import load_literatures_df

        table = load_literatures_df(Path(db_path_text))
        if not table.empty and "structured_abs_path" in table.columns:
            for _, row in table.fillna("").iterrows():
                structured_abs_path = _stringify(row.get("structured_abs_path"))
                if not structured_abs_path or structured_abs_path in seen_paths:
                    continue
                path = Path(structured_abs_path)
                if not path.exists() or not path.is_file():
                    continue
                payload = load_structured_data(path)
                records.append(build_doc_record_from_structured_data(payload, source_path=path))
                seen_paths.add(structured_abs_path)
                if max_items and len(records) >= max_items:
                    return records

    if structured_dir:
        root = Path(structured_dir)
        for path in sorted(root.glob("*.structured.json")):
            key = str(path)
            if key in seen_paths:
                continue
            payload = load_structured_data(path)
            records.append(build_doc_record_from_structured_data(payload, source_path=path))
            seen_paths.add(key)
            if max_items and len(records) >= max_items:
                break

    return records


def build_chunk_entries_from_structured_data(
    structured_data: Dict[str, Any],
    *,
    chunk_size: int = 1500,
    min_chunk_size: int = 200,
) -> List[Dict[str, Any]]:
    """基于结构化结果生成 chunk 条目。"""

    source = structured_data.get("source") if isinstance(structured_data.get("source"), dict) else {}
    units = structured_data.get("units") if isinstance(structured_data.get("units"), dict) else {}
    paragraphs = units.get("paragraphs") if isinstance(units.get("paragraphs"), list) else []
    sentences = units.get("sentences") if isinstance(units.get("sentences"), list) else []
    cite_key = _stringify(source.get("cite_key"))
    uid_literature = _stringify(source.get("uid_literature"))
    doc_id = cite_key or uid_literature or _stringify(source.get("pdf_name"))
    chunk_rows: List[Dict[str, Any]] = []

    def append_row(
        *,
        chunk_text: str,
        chunk_type: str,
        chunk_index: int,
        char_start: int | None,
        char_end: int | None,
        unit_start: int | None,
        unit_end: int | None,
    ) -> None:
        text = _stringify(chunk_text)
        if len(text) < min_chunk_size:
            return
        chunk_id = f"{doc_id or 'doc'}::chunk::{chunk_index:04d}"
        chunk_rows.append(
            {
                "chunk_id": chunk_id,
                "uid": uid_literature or doc_id,
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "doc_id": doc_id,
                "chunk_index": chunk_index,
                "chunk_type": chunk_type,
                "text": text,
                "char_start": char_start,
                "char_end": char_end,
                "meta": {
                    "backend": _stringify(source.get("backend")),
                    "unit_start": unit_start,
                    "unit_end": unit_end,
                    "pdf_abs_path": _stringify(source.get("pdf_abs_path")),
                },
            }
        )

    if paragraphs:
        buffer: List[Dict[str, Any]] = []
        for row in paragraphs:
            text = _stringify(row.get("text"))
            if not text:
                continue
            candidate_text = "\n\n".join([_stringify(item.get("text")) for item in [*buffer, row] if _stringify(item.get("text"))]).strip()
            if buffer and len(candidate_text) > chunk_size:
                append_row(
                    chunk_text="\n\n".join(_stringify(item.get("text")) for item in buffer),
                    chunk_type="paragraph_bundle",
                    chunk_index=len(chunk_rows) + 1,
                    char_start=buffer[0].get("char_start"),
                    char_end=buffer[-1].get("char_end"),
                    unit_start=int(buffer[0].get("index") or 0),
                    unit_end=int(buffer[-1].get("index") or 0),
                )
                buffer = [row]
            else:
                buffer.append(row)
        if buffer:
            append_row(
                chunk_text="\n\n".join(_stringify(item.get("text")) for item in buffer),
                chunk_type="paragraph_bundle",
                chunk_index=len(chunk_rows) + 1,
                char_start=buffer[0].get("char_start"),
                char_end=buffer[-1].get("char_end"),
                unit_start=int(buffer[0].get("index") or 0),
                unit_end=int(buffer[-1].get("index") or 0),
            )
        return chunk_rows

    if sentences:
        buffer: List[Dict[str, Any]] = []
        for row in sentences:
            text = _stringify(row.get("text") or row.get("sentence"))
            if not text:
                continue
            candidate_text = " ".join([_stringify(item.get("text") or item.get("sentence")) for item in [*buffer, row] if _stringify(item.get("text") or item.get("sentence"))]).strip()
            if buffer and len(candidate_text) > chunk_size:
                append_row(
                    chunk_text=" ".join(_stringify(item.get("text") or item.get("sentence")) for item in buffer),
                    chunk_type="sentence_bundle",
                    chunk_index=len(chunk_rows) + 1,
                    char_start=buffer[0].get("char_start"),
                    char_end=buffer[-1].get("char_end"),
                    unit_start=int(buffer[0].get("index") or 0),
                    unit_end=int(buffer[-1].get("index") or 0),
                )
                buffer = [row]
            else:
                buffer.append(row)
        if buffer:
            append_row(
                chunk_text=" ".join(_stringify(item.get("text") or item.get("sentence")) for item in buffer),
                chunk_type="sentence_bundle",
                chunk_index=len(chunk_rows) + 1,
                char_start=buffer[0].get("char_start"),
                char_end=buffer[-1].get("char_end"),
                unit_start=int(buffer[0].get("index") or 0),
                unit_end=int(buffer[-1].get("index") or 0),
            )
    return chunk_rows


def write_chunk_shards(
    chunk_entries: Sequence[Dict[str, Any]],
    *,
    output_dir: Path,
    chunks_uid: str,
    source_scope: str,
    source_backend: str,
    source_doc_count: int,
    max_chunks_per_shard: int = 200,
) -> Dict[str, Any]:
    """将 chunk 条目写成分片文件与 manifest。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    shard_dir = (output_dir / "chunk_shards").resolve()
    shard_dir.mkdir(parents=True, exist_ok=True)
    shards: List[Dict[str, Any]] = []
    chunk_rows = list(chunk_entries or [])
    for start in range(0, len(chunk_rows), max(1, int(max_chunks_per_shard))):
        shard_rows = chunk_rows[start : start + max(1, int(max_chunks_per_shard))]
        shard_index = len(shards) + 1
        shard_path = (shard_dir / f"{chunks_uid}.part-{shard_index:03d}.jsonl").resolve()
        with shard_path.open("w", encoding="utf-8") as stream:
            for row in shard_rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        shards.append(
            {
                "shard_index": shard_index,
                "chunks_abs_path": str(shard_path),
                "chunk_count": len(shard_rows),
            }
        )

    manifest = {
        "schema": "aok.chunk_manifest.v1",
        "chunks_uid": chunks_uid,
        "source_scope": source_scope,
        "source_backend": source_backend,
        "source_doc_count": int(source_doc_count),
        "chunk_count": int(len(chunk_rows)),
        "status": DEFAULT_CHUNK_SET_STATUS,
        "created_at": _utc_now_iso(),
        "shards": shards,
    }
    manifest_path = (output_dir / "chunk_manifest.json").resolve()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "shard_paths": [Path(item["chunks_abs_path"]) for item in shards],
    }


def iter_chunk_files_from_manifest(manifest_path: Path) -> List[Path]:
    """从 chunk manifest 中解析出全部分片路径。"""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    shard_rows = manifest.get("shards") if isinstance(manifest.get("shards"), list) else []
    paths: List[Path] = []
    for item in shard_rows:
        shard_path = _stringify(item.get("chunks_abs_path"))
        if not shard_path:
            continue
        paths.append(Path(shard_path))
    return paths


__all__ = [
    "DEFAULT_CHUNK_SET_STATUS",
    "STRUCTURED_SCHEMA_VERSION",
    "build_chunk_entries_from_structured_data",
    "build_doc_record_from_structured_data",
    "build_segments_map",
    "build_structured_data_payload",
    "build_units_map",
    "extract_reference_lines_from_structured_data",
    "iter_chunk_files_from_manifest",
    "load_document_records_from_structured_source",
    "load_single_document_record",
    "load_structured_data",
    "normalize_full_text",
    "split_text_to_paragraphs",
    "split_text_to_sentences",
    "write_chunk_shards",
]