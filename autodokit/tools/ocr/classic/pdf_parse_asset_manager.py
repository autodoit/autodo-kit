"""PDF 解析资产管理工具。

负责把 MonkeyOCR 单篇解析结果注册为统一可复用的解析资产，并补写
兼容旧消费者的 `aok.pdf_structured.v3` 文件入口。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from autodokit.path_compat import resolve_portable_path
from autodokit.tools.bibliodb_sqlite import (
    load_attachments_df,
    load_literatures_df,
    load_parse_assets_df,
    save_structured_state,
    upsert_parse_asset_rows,
)
from autodokit.tools.contentdb_sqlite import infer_workspace_root_from_content_db
from autodokit.tools.ocr.classic.pdf_elements_extractors import extract_text_with_rapidocr
from autodokit.tools.ocr.classic.pdf_structured_data_tools import build_structured_data_payload
from autodokit.tools.ocr.monkeyocr.monkeyocr_windows_tools import parse_pdf_with_monkeyocr_windows


UNIFIED_PARSE_ROOT_NAME = "structured_monkeyocr_full"
UNIFIED_PARSE_LEVEL = "monkeyocr_full"
_LEGACY_PARSE_LEVELS = ("review_deep", "non_review_rough", "non_review_deep")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _load_json_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_global_config(global_config_path: str | Path | None) -> Dict[str, Any]:
    if global_config_path is None:
        return {}
    path = Path(global_config_path)
    if not path.exists() or not path.is_file():
        return {}
    payload = _load_json_file(path)
    return payload if isinstance(payload, dict) else {}


def _safe_stem(text: str) -> str:
    value = _stringify(text)
    value = "".join("_" if ch in '\\/:*?\"<>|' else ch for ch in value)
    value = "_".join(value.split())
    return value or "untitled"


def _resolve_api_key_file(*, api_key_file: str | Path | None = None, global_config_path: str | Path | None = None) -> Path:
    explicit = _stringify(api_key_file)
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            raise ValueError(f"api_key_file 必须为绝对路径：{path}")
        if not path.exists() or not path.is_file():
            raise ValueError(f"api_key_file 不存在：{path}")
        return path.resolve()

    config_text = _stringify(global_config_path)
    if config_text:
        config_path = Path(config_text)
        if config_path.exists() and config_path.is_file():
            payload = _load_json_file(config_path)
            llm_cfg = payload.get("llm") if isinstance(payload.get("llm"), dict) else {}
            candidate = _stringify(llm_cfg.get("aliyun_api_key_file") or payload.get("aliyun_api_key_file"))
            if candidate:
                path = Path(candidate)
                if not path.is_absolute():
                    raise ValueError(f"aliyun_api_key_file 必须为绝对路径：{path}")
                if path.exists() and path.is_file():
                    return path.resolve()

    raise ValueError("未找到可用的阿里百炼 API Key 文件，请提供 api_key_file 或在 config.json 中配置 llm.aliyun_api_key_file")


def _resolve_model(*, model: str = "auto", global_config_path: str | Path | None = None) -> str:
    explicit = _stringify(model)
    if explicit and explicit.lower() != "auto":
        return explicit

    config_text = _stringify(global_config_path)
    if config_text:
        config_path = Path(config_text)
        if config_path.exists() and config_path.is_file():
            payload = _load_json_file(config_path)
            llm_cfg = payload.get("llm") if isinstance(payload.get("llm"), dict) else {}
            candidate = _stringify(
                llm_cfg.get("monkeyocr_parse_model")
                or llm_cfg.get("pdf_multimodal_parse_model")
                or llm_cfg.get("aliyun_pdf_parse_model")
                or llm_cfg.get("pdf_parse_model")
                or payload.get("monkeyocr_parse_model")
                or payload.get("pdf_multimodal_parse_model")
            )
            if candidate:
                return candidate

    return "auto"


def _resolve_monkeyocr_root(*, workspace_root: Path, raw_cfg: Dict[str, Any]) -> Path:
    def _normalize_candidate(path: Path) -> Path | None:
        direct = (path / "parse.py").resolve()
        if direct.exists() and direct.is_file():
            return path.resolve()
        nested = (path / "MonkeyOCR-main" / "parse.py").resolve()
        if nested.exists() and nested.is_file():
            return (path / "MonkeyOCR-main").resolve()
        return None

    def _discover_shared_root() -> Path | None:
        env_candidates = [
            _stringify(os.environ.get("MONKEYOCR_ROOT")),
            _stringify(os.environ.get("AUTODOKIT_MONKEYOCR_ROOT")),
        ]
        for candidate in env_candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.is_absolute():
                normalized = _normalize_candidate(path)
                if normalized is not None:
                    return normalized

        repo_root = Path(__file__).resolve().parents[4]
        candidates = [
            workspace_root / "pypackage",
            workspace_root / "pypackage" / "MonkeyOCR-main",
            workspace_root / "sandbox" / "MonkeyOCR-main",
            repo_root / "pypackage",
            repo_root / "pypackage" / "MonkeyOCR-main",
            repo_root / "sandbox" / "MonkeyOCR-main",
            repo_root / "sandbox" / "test monkey ocr cuda" / "MonkeyOCR-main",
            repo_root / "MonkeyOCR-main",
        ]
        for candidate in candidates:
            normalized = _normalize_candidate(candidate)
            if normalized is not None:
                return normalized
        return None

    candidate = _stringify(raw_cfg.get("monkeyocr_root"))
    if candidate:
        path = resolve_portable_path(candidate, base=workspace_root)
        normalized = _normalize_candidate(path)
        return normalized or path.resolve()

    discovered = _discover_shared_root()
    if discovered is not None:
        return discovered

    default_root = (workspace_root / "sandbox" / "MonkeyOCR-main").resolve()
    return default_root


def _resolve_monkeyocr_model_name(*, raw_cfg: Dict[str, Any]) -> str:
    candidate = _stringify(raw_cfg.get("monkeyocr_model_name") or raw_cfg.get("monkeyocr_model"))
    return candidate or "MonkeyOCR-pro-1.2B"


def parse_pdf_with_aliyun_multimodal(**kwargs: Any) -> Dict[str, Any]:
    """兼容旧调用名的 MonkeyOCR 单篇解析包装器。"""

    return parse_pdf_with_monkeyocr_windows(**kwargs)


def _resolve_sdk_backend(*, sdk_backend: str | None = None, global_config_path: str | Path | None = None) -> str | None:
    explicit = _stringify(sdk_backend)
    if explicit:
        return explicit

    config_text = _stringify(global_config_path)
    if config_text:
        config_path = Path(config_text)
        if config_path.exists() and config_path.is_file():
            payload = _load_json_file(config_path)
            llm_cfg = payload.get("llm") if isinstance(payload.get("llm"), dict) else {}
            candidate = _stringify(
                llm_cfg.get("pdf_multimodal_sdk_backend")
                or llm_cfg.get("aliyun_pdf_parse_sdk_backend")
                or llm_cfg.get("pdf_parse_sdk_backend")
                or payload.get("pdf_multimodal_sdk_backend")
            )
            if candidate:
                return candidate

    return None


def _resolve_literature_row(content_db: Path, *, uid_literature: str = "", cite_key: str = "", doc_id: str = "") -> Dict[str, Any]:
    table = load_literatures_df(content_db).fillna("")
    resolved_uid = _stringify(uid_literature)
    resolved_cite_key = _stringify(cite_key) or _stringify(doc_id)
    target = table
    if resolved_uid and "uid_literature" in table.columns:
        target = table[table["uid_literature"].astype(str) == resolved_uid]
    elif resolved_cite_key and "cite_key" in table.columns:
        target = table[table["cite_key"].astype(str) == resolved_cite_key]
    if target.empty:
        raise KeyError(f"未在 content.db 中找到目标文献：uid={resolved_uid!r}, cite_key={resolved_cite_key!r}")
    return dict(target.iloc[0].to_dict())


def _resolve_pdf_path(content_db: Path, literature_row: Dict[str, Any]) -> Path:
    uid_literature = _stringify(literature_row.get("uid_literature"))
    attachments = load_attachments_df(content_db).fillna("")
    if uid_literature and not attachments.empty and "uid_literature" in attachments.columns:
        rows = attachments[attachments["uid_literature"].astype(str) == uid_literature].copy()
        if not rows.empty:
            rows = rows.sort_values(by=["is_primary", "attachment_name"], ascending=[False, True])
            for _, row in rows.iterrows():
                candidate = _stringify(row.get("storage_path") or row.get("source_path"))
                if candidate:
                    path = Path(candidate)
                    if path.is_absolute() and path.exists() and path.is_file():
                        return path.resolve()

    pdf_path = _stringify(literature_row.get("pdf_path"))
    if pdf_path:
        path = Path(pdf_path)
        if path.is_absolute() and path.exists() and path.is_file():
            return path.resolve()
    raise ValueError(f"未找到可用 PDF 附件：uid_literature={uid_literature or _stringify(literature_row.get('cite_key'))}")


def _resolve_output_root(content_db: Path, parse_level: str) -> Path:
    workspace_root = infer_workspace_root_from_content_db(content_db)
    output_root = workspace_root / "references" / UNIFIED_PARSE_ROOT_NAME
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root.resolve()


def _normalize_lookup_key(text: str) -> str:
    value = _stringify(text).lower()
    if not value:
        return ""
    value = re.sub(r"\.[a-z0-9]{1,8}$", "", value)
    value = re.sub(r"[^\w\u4e00-\u9fff]", "", value)
    return value


def _discover_existing_asset_dir(output_root: Path, literature_row: Dict[str, Any]) -> Path | None:
    if not output_root.exists() or not output_root.is_dir():
        return None

    uid = _stringify(literature_row.get("uid_literature"))
    cite_key = _stringify(literature_row.get("cite_key"))
    title = _stringify(literature_row.get("title"))
    pdf_path = _stringify(literature_row.get("pdf_path"))
    pdf_stem = Path(pdf_path).stem if pdf_path else ""

    exact_keys = {item for item in (uid, cite_key, title, pdf_stem) if item}
    normalized_keys = {_normalize_lookup_key(item) for item in exact_keys if _normalize_lookup_key(item)}

    for child in output_root.iterdir():
        if not child.is_dir():
            continue
        if child.name in exact_keys:
            return child.resolve()
        if _normalize_lookup_key(child.name) in normalized_keys:
            return child.resolve()

    return None


def _pick_existing_markdown(asset_dir: Path) -> Path | None:
    preferred = [
        asset_dir / "reconstructed_content.md",
        asset_dir / "reconstructed_content_postprocessed.md",
        asset_dir / "reconstructed_content_raw.md",
        asset_dir / "reconstructed_content_pdf_text_fallback.md",
    ]
    for candidate in preferred:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    markdown_files = sorted([path for path in asset_dir.glob("*.md") if path.is_file()])
    if not markdown_files:
        return None
    return markdown_files[0].resolve()


def _build_elements_from_content_list(content_list_path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(content_list_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"items": []}

    if not isinstance(payload, list):
        return {"items": []}

    items: List[Dict[str, Any]] = []
    for idx, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            continue
        text = _stringify(row.get("text"))
        if not text:
            continue
        block_type = _stringify(row.get("type")) or "text"
        text_level = int(row.get("text_level") or 0)
        page_idx = int(row.get("page_idx") or 0)

        node_type = "paragraph"
        if idx == 1 and text_level >= 1:
            node_type = "document_title"
        elif block_type == "title" or text_level >= 1:
            node_type = "section_heading"
        elif "关键词" in text:
            node_type = "keywords_block"
        elif "摘 要" in text or text.startswith("摘要"):
            node_type = "abstract_block"

        items.append(
            {
                "node_id": f"legacy_{idx:06d}",
                "node_type": node_type,
                "text": text,
                "page_number": page_idx + 1,
                "reading_order": idx,
            }
        )

    return {"items": items}


def _bootstrap_existing_asset(
    *,
    content_db_path: Path,
    parse_level: str,
    literature_row: Dict[str, Any],
    output_root: Path,
    source_stage: str,
) -> Dict[str, Any] | None:
    asset_dir = _discover_existing_asset_dir(output_root, literature_row)
    if asset_dir is None:
        return None

    normalized_structured_path = (asset_dir / "normalized.structured.json").resolve()
    reconstructed_markdown_path = (asset_dir / "reconstructed_content.md").resolve()
    elements_path = (asset_dir / "elements.json").resolve()
    linear_index_path = (asset_dir / "linear_index.json").resolve()
    parse_record_path = (asset_dir / "parse_record.json").resolve()
    quality_report_path = (asset_dir / "quality_report.json").resolve()

    source_markdown = _pick_existing_markdown(asset_dir)
    if source_markdown is None:
        return None

    markdown_text = source_markdown.read_text(encoding="utf-8-sig")
    if not reconstructed_markdown_path.exists():
        reconstructed_markdown_path.write_text(markdown_text, encoding="utf-8")

    if not elements_path.exists():
        content_list_candidates = sorted(asset_dir.glob("*_content_list.json"))
        elements_payload = {"items": []}
        if content_list_candidates:
            elements_payload = _build_elements_from_content_list(content_list_candidates[0].resolve())
        elements_path.write_text(json.dumps(elements_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if not linear_index_path.exists():
        linear_index_payload = {
            "paragraphs": [
                {
                    "index": idx + 1,
                    "text": paragraph,
                }
                for idx, paragraph in enumerate([item for item in re.split(r"\n{2,}", markdown_text) if _stringify(item)])
            ]
        }
        linear_index_path.write_text(json.dumps(linear_index_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if not parse_record_path.exists():
        parse_record_payload = {
            "schema": "aok.pdf_monkeyocr_parse_record.v1",
            "tool": "bootstrap_existing_monkeyocr_asset",
            "llm_backend": "monkeyocr_windows",
            "llm_model": "external_preparsed",
            "output_dir": str(asset_dir),
        }
        parse_record_path.write_text(json.dumps(parse_record_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if not quality_report_path.exists():
        quality_report_payload = {
            "schema": "aok.pdf_monkeyocr_quality_report.v1",
            "status": "bootstrapped",
            "output_dir": str(asset_dir),
        }
        quality_report_path.write_text(json.dumps(quality_report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if not normalized_structured_path.exists():
        pdf_path = _resolve_pdf_path(content_db_path, literature_row)
        payload = build_structured_data_payload(
            pdf_path=pdf_path,
            backend="monkeyocr_windows",
            backend_family="monkeyocr",
            task_type=parse_level,
            full_text=markdown_text,
            extract_error="",
            uid_literature=_stringify(literature_row.get("uid_literature")),
            cite_key=_stringify(literature_row.get("cite_key")),
            title=_stringify(literature_row.get("title")),
            year=_stringify(literature_row.get("year")),
            artifacts={
                "asset_dir": str(asset_dir),
                "elements_path": str(elements_path),
                "linear_index_path": str(linear_index_path),
                "reconstructed_markdown_path": str(reconstructed_markdown_path),
                "parse_record_path": str(parse_record_path),
                "quality_report_path": str(quality_report_path),
            },
            capabilities={"parse_level": parse_level, "llm_backend": "monkeyocr_windows", "llm_model": "external_preparsed"},
        )
        normalized_structured_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parse_asset_row = {
        "uid_literature": _stringify(literature_row.get("uid_literature")),
        "cite_key": _stringify(literature_row.get("cite_key")),
        "parse_level": parse_level,
        "source_stage": _stringify(source_stage),
        "backend": "monkeyocr_windows",
        "task_type": parse_level,
        "asset_dir": str(asset_dir),
        "normalized_structured_path": str(normalized_structured_path),
        "reconstructed_markdown_path": str(reconstructed_markdown_path),
        "linear_index_path": str(linear_index_path),
        "elements_path": str(elements_path),
        "chunk_manifest_path": _stringify(asset_dir / "chunk_manifest.json"),
        "chunks_jsonl_path": _stringify(asset_dir / "chunks.jsonl"),
        "parse_record_path": str(parse_record_path),
        "quality_report_path": str(quality_report_path),
        "parse_status": "ready",
        "llm_model": "external_preparsed",
        "llm_backend": "monkeyocr_windows",
        "last_run_uid": _safe_stem(_stringify(literature_row.get("cite_key")) or _stringify(literature_row.get("uid_literature"))),
    }
    upsert_parse_asset_rows(content_db_path, [parse_asset_row])
    payload = _load_json_file(normalized_structured_path)
    text_payload = payload.get("text") if isinstance(payload.get("text"), dict) else {}
    references_payload = payload.get("references") if isinstance(payload.get("references"), list) else []
    save_structured_state(
        content_db_path,
        uid_literature=_stringify(literature_row.get("uid_literature")),
        structured_status="ready",
        structured_abs_path=str(normalized_structured_path),
        structured_backend="monkeyocr_windows",
        structured_task_type=parse_level,
        structured_updated_at=_stringify((payload.get("parse_profile") or {}).get("created_at")),
        structured_schema_version=_stringify(payload.get("schema")),
        structured_text_length=len(_stringify(text_payload.get("full_text"))),
        structured_reference_count=len(references_payload),
    )
    return parse_asset_row


def _extract_text_with_pymupdf(pdf_path: Path) -> tuple[str, Dict[str, Any]]:
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover
        return "", {
            "backend": "pymupdf_text",
            "enabled": False,
            "error": f"未安装 PyMuPDF（pymupdf）：{exc}",
            "page_count": 0,
            "recognized_pages": 0,
        }

    doc = fitz.open(str(pdf_path))
    page_count = int(doc.page_count)
    page_texts: list[str] = []
    recognized_pages = 0
    try:
        for page_index in range(page_count):
            page = doc.load_page(page_index)
            page_text = str(page.get_text("text") or "").strip()
            if page_text:
                recognized_pages += 1
                page_texts.append(f"[Page {page_index + 1}]\n\n{page_text}")
    finally:
        doc.close()

    return "\n\n".join(page_texts).strip(), {
        "backend": "pymupdf_text",
        "enabled": True,
        "page_count": page_count,
        "recognized_pages": recognized_pages,
    }


def _extract_pdf_text_fallback(pdf_path: Path) -> tuple[str, Dict[str, Any]]:
    text, meta = _extract_text_with_pymupdf(pdf_path)
    if text:
        return text, meta

    ocr_text, ocr_status, ocr_meta = extract_text_with_rapidocr(pdf_path)
    return ocr_text, {
        "backend": "rapidocr",
        "enabled": bool(ocr_status.enabled),
        "disabled_reason": _stringify(ocr_status.disabled_reason),
        **ocr_meta,
    }


def _select_existing_asset(
    content_db: Path,
    *,
    parse_level: str,
    uid_literature: str = "",
    cite_key: str = "",
) -> Dict[str, Any] | None:
    table = load_parse_assets_df(content_db, only_current=True, parse_statuses=["ready"]).fillna("")
    if table.empty:
        return None
    requested_level = _stringify(parse_level)
    allowed_levels = {requested_level, UNIFIED_PARSE_LEVEL}
    if requested_level in _LEGACY_PARSE_LEVELS:
        allowed_levels.update(_LEGACY_PARSE_LEVELS)
    table = table[table.get("parse_level", "").astype(str).isin({item for item in allowed_levels if item})]
    if table.empty:
        return None
    resolved_uid = _stringify(uid_literature)
    resolved_cite_key = _stringify(cite_key)
    if resolved_uid:
        table = table[table.get("uid_literature", "").astype(str) == resolved_uid]
    elif resolved_cite_key:
        table = table[table.get("cite_key", "").astype(str) == resolved_cite_key]
    if table.empty:
        return None

    def _level_priority(level: str) -> int:
        normalized = _stringify(level)
        if normalized == requested_level:
            return 0
        if normalized == UNIFIED_PARSE_LEVEL:
            return 1
        return 2

    sort_columns = []
    ascending = []
    if "updated_at" in table.columns:
        sort_columns.append("updated_at")
        ascending.append(False)
    if sort_columns:
        table = table.sort_values(by=sort_columns, ascending=ascending, kind="stable")

    ordered_rows = sorted(
        table.to_dict(orient="records"),
        key=lambda row: _level_priority(row.get("parse_level", "")),
    )
    for row in ordered_rows:
        candidate = dict(row)
        normalized_structured_path = Path(_stringify(candidate.get("normalized_structured_path")))
        if normalized_structured_path.exists() and normalized_structured_path.is_file():
            return candidate
    return None


def build_normalized_structured_from_multimodal_result(
    *,
    pdf_path: str | Path,
    parse_result: Dict[str, Any],
    parse_level: str,
    backend: str = "monkeyocr_windows",
    backend_family: str = "monkeyocr",
    uid_literature: str = "",
    cite_key: str = "",
    title: str = "",
    year: str = "",
) -> Path:
    """把解析目录资产转换为兼容旧消费者的 structured.json。"""

    pdf_file = Path(pdf_path).resolve()
    output_dir = Path(_stringify(parse_result.get("output_dir"))).resolve()
    if not output_dir.exists() or not output_dir.is_dir():
        raise ValueError(f"多模态输出目录不存在：{output_dir}")

    reconstructed_markdown_path = Path(_stringify(parse_result.get("reconstructed_markdown_path"))).resolve()
    linear_index_path = Path(_stringify(parse_result.get("linear_index_path"))).resolve()
    parse_record_path = Path(_stringify(parse_result.get("parse_record_path"))).resolve()
    quality_report_path = Path(_stringify(parse_result.get("quality_report_path"))).resolve()

    reconstructed_text = reconstructed_markdown_path.read_text(encoding="utf-8") if reconstructed_markdown_path.exists() else ""
    parse_record = _load_json_file(parse_record_path) if parse_record_path.exists() else {}
    artifacts: Dict[str, Any] = {
        "asset_dir": str(output_dir),
        "structured_tree_path": _stringify(parse_result.get("structured_tree_path")),
        "elements_path": _stringify(parse_result.get("elements_path")),
        "attachments_manifest_path": _stringify(parse_result.get("attachments_manifest_path")),
        "linear_index_path": str(linear_index_path) if linear_index_path.exists() else "",
        "chunk_manifest_path": _stringify(parse_result.get("chunk_manifest_path")),
        "chunks_jsonl_path": _stringify(parse_result.get("chunks_jsonl_path")),
        "reconstructed_markdown_path": str(reconstructed_markdown_path) if reconstructed_markdown_path.exists() else "",
        "parse_record_path": str(parse_record_path) if parse_record_path.exists() else "",
        "quality_report_path": str(quality_report_path) if quality_report_path.exists() else "",
    }
    payload = build_structured_data_payload(
        pdf_path=pdf_file,
        backend=backend,
        backend_family=backend_family,
        task_type=parse_level,
        full_text=reconstructed_text,
        extract_error="",
        uid_literature=uid_literature,
        cite_key=cite_key,
        title=title,
        year=year,
        artifacts=artifacts,
        capabilities={
            "parse_level": parse_level,
            "llm_model": _stringify(parse_record.get("llm_model") or parse_result.get("llm_model")),
            "llm_backend": _stringify(parse_record.get("llm_backend") or parse_result.get("llm_backend")),
        },
        extra_fields={
            "multimodal_parse_asset": {
                "schema": _stringify(parse_record.get("schema")),
                "output_dir": str(output_dir),
            }
        },
    )
    structured_path = (output_dir / "normalized.structured.json").resolve()
    structured_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return structured_path


def ensure_pdf_text_fallback_asset(
    *,
    content_db: str | Path,
    parse_level: str,
    uid_literature: str = "",
    cite_key: str = "",
    doc_id: str = "",
    source_stage: str = "",
    overwrite_existing: bool = False,
) -> Dict[str, Any]:
    """从原文 PDF 直接生成轻量结构化 fallback 资产。"""

    content_db_path = Path(content_db).resolve()
    literature_row = _resolve_literature_row(
        content_db_path,
        uid_literature=uid_literature,
        cite_key=cite_key,
        doc_id=doc_id,
    )
    resolved_uid = _stringify(literature_row.get("uid_literature"))
    resolved_cite_key = _stringify(literature_row.get("cite_key"))

    if not overwrite_existing:
        existing = _select_existing_asset(
            content_db_path,
            parse_level=parse_level,
            uid_literature=resolved_uid,
            cite_key=resolved_cite_key,
        )
        if existing is not None and _stringify(existing.get("backend")) == "pdf_text_fallback":
            return existing

    pdf_path = _resolve_pdf_path(content_db_path, literature_row)
    output_root = _resolve_output_root(content_db_path, parse_level)
    output_name = _safe_stem(resolved_cite_key or resolved_uid or pdf_path.stem)
    output_dir = (output_root / output_name).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    fallback_text, fallback_meta = _extract_pdf_text_fallback(pdf_path)
    reconstructed_markdown_path = (output_dir / "reconstructed_content_pdf_text_fallback.md").resolve()
    reconstructed_markdown_path.write_text(fallback_text, encoding="utf-8")

    artifacts = {
        "asset_dir": str(output_dir),
        "reconstructed_markdown_path": str(reconstructed_markdown_path),
        "fallback_mode": "original_pdf_direct_read",
    }
    payload = build_structured_data_payload(
        pdf_path=pdf_path,
        backend="pdf_text_fallback",
        backend_family="pdf_text_fallback",
        task_type=parse_level,
        full_text=fallback_text,
        extract_error="" if fallback_text else "pdf_text_fallback 未抽取到可用正文",
        text_meta=fallback_meta,
        uid_literature=resolved_uid,
        cite_key=resolved_cite_key,
        title=_stringify(literature_row.get("title")),
        year=_stringify(literature_row.get("year")),
        artifacts=artifacts,
        capabilities={
            "parse_level": parse_level,
            "fallback_mode": "original_pdf_direct_read",
        },
        extra_fields={
            "pdf_text_fallback_asset": {
                "source_stage": _stringify(source_stage),
                "output_dir": str(output_dir),
            }
        },
    )
    normalized_structured_path = (output_dir / "normalized.structured.json").resolve()
    normalized_structured_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parse_asset_row = {
        "uid_literature": resolved_uid,
        "cite_key": resolved_cite_key,
        "parse_level": parse_level,
        "source_stage": _stringify(source_stage),
        "backend": "pdf_text_fallback",
        "task_type": parse_level,
        "asset_dir": str(output_dir),
        "normalized_structured_path": str(normalized_structured_path),
        "reconstructed_markdown_path": str(reconstructed_markdown_path),
        "linear_index_path": "",
        "chunk_manifest_path": "",
        "chunks_jsonl_path": "",
        "parse_record_path": "",
        "quality_report_path": "",
        "parse_status": "ready",
        "llm_model": "",
        "llm_backend": "",
        "last_run_uid": output_name,
    }
    upsert_parse_asset_rows(content_db_path, [parse_asset_row])
    save_structured_state(
        content_db_path,
        uid_literature=resolved_uid,
        structured_status="ready",
        structured_abs_path=str(normalized_structured_path),
        structured_backend="pdf_text_fallback",
        structured_task_type=parse_level,
        structured_updated_at=_stringify((payload.get("parse_profile") or {}).get("created_at")),
        structured_schema_version=_stringify(payload.get("schema")),
        structured_text_length=len(_stringify((payload.get("text") or {}).get("full_text"))),
        structured_reference_count=len(payload.get("references") or []),
    )

    current = _select_existing_asset(
        content_db_path,
        parse_level=parse_level,
        uid_literature=resolved_uid,
        cite_key=resolved_cite_key,
    )
    return current or parse_asset_row


def ensure_multimodal_parse_asset(
    *,
    content_db: str | Path,
    parse_level: str,
    uid_literature: str = "",
    cite_key: str = "",
    doc_id: str = "",
    source_stage: str = "",
    api_key_file: str | Path | None = None,
    global_config_path: str | Path | None = None,
    overwrite_existing: bool = False,
    model: str = "auto",
    sdk_backend: str | None = None,
    max_pages: int | None = None,
) -> Dict[str, Any]:
    """确保目标文献具备指定 parse level 的多模态解析资产。"""

    content_db_path = Path(content_db).resolve()
    literature_row = _resolve_literature_row(
        content_db_path,
        uid_literature=uid_literature,
        cite_key=cite_key,
        doc_id=doc_id,
    )
    resolved_uid = _stringify(literature_row.get("uid_literature"))
    resolved_cite_key = _stringify(literature_row.get("cite_key"))

    if not overwrite_existing:
        existing = _select_existing_asset(
            content_db_path,
            parse_level=parse_level,
            uid_literature=resolved_uid,
            cite_key=resolved_cite_key,
        )
        if existing is not None:
            return existing

    output_root = _resolve_output_root(content_db_path, parse_level)
    bootstrapped = _bootstrap_existing_asset(
        content_db_path=content_db_path,
        parse_level=parse_level,
        literature_row=literature_row,
        output_root=output_root,
        source_stage=source_stage,
    )
    if bootstrapped is not None:
        existing = _select_existing_asset(
            content_db_path,
            parse_level=parse_level,
            uid_literature=resolved_uid,
            cite_key=resolved_cite_key,
        )
        if existing is not None:
            return existing

    pdf_path = _resolve_pdf_path(content_db_path, literature_row)
    output_name = _safe_stem(resolved_cite_key or resolved_uid or pdf_path.stem)
    workspace_root = infer_workspace_root_from_content_db(content_db_path)
    raw_cfg = _load_global_config(global_config_path)
    resolved_monkeyocr_root = _resolve_monkeyocr_root(workspace_root=workspace_root, raw_cfg=raw_cfg)
    resolved_monkeyocr_model_name = _resolve_monkeyocr_model_name(raw_cfg=raw_cfg)

    parse_result = parse_pdf_with_aliyun_multimodal(
        pdf_path=pdf_path,
        output_root=output_root,
        output_name=output_name,
        monkeyocr_root=resolved_monkeyocr_root,
        model_name=resolved_monkeyocr_model_name,
        uid_literature=resolved_uid,
        cite_key=resolved_cite_key,
        document_id=resolved_cite_key or resolved_uid,
        source_metadata={
            "title": _stringify(literature_row.get("title")),
            "year": _stringify(literature_row.get("year")),
            "language": _stringify(literature_row.get("language")),
        },
        max_pages=max_pages,
        overwrite_output=overwrite_existing,
        api_key_file=api_key_file,
        model=model,
        sdk_backend=sdk_backend,
    )
    normalized_structured_path = build_normalized_structured_from_multimodal_result(
        pdf_path=pdf_path,
        parse_result=parse_result,
        parse_level=parse_level,
        backend="monkeyocr_windows",
        backend_family="monkeyocr",
        uid_literature=resolved_uid,
        cite_key=resolved_cite_key,
        title=_stringify(literature_row.get("title")),
        year=_stringify(literature_row.get("year")),
    )
    structured_payload = _load_json_file(normalized_structured_path)
    text_payload = structured_payload.get("text") if isinstance(structured_payload.get("text"), dict) else {}
    references_payload = structured_payload.get("references") if isinstance(structured_payload.get("references"), list) else []

    parse_asset_row = {
        "uid_literature": resolved_uid,
        "cite_key": resolved_cite_key,
        "parse_level": parse_level,
        "source_stage": _stringify(source_stage),
        "backend": "monkeyocr_windows",
        "task_type": parse_level,
        "asset_dir": _stringify(parse_result.get("output_dir")),
        "normalized_structured_path": str(normalized_structured_path),
        "reconstructed_markdown_path": _stringify(parse_result.get("reconstructed_markdown_path")),
        "linear_index_path": _stringify(parse_result.get("linear_index_path")),
        "chunk_manifest_path": _stringify(parse_result.get("chunk_manifest_path")),
        "chunks_jsonl_path": _stringify(parse_result.get("chunks_jsonl_path")),
        "parse_record_path": _stringify(parse_result.get("parse_record_path")),
        "quality_report_path": _stringify(parse_result.get("quality_report_path")),
        "parse_status": "ready",
        "llm_model": _stringify(parse_result.get("llm_model")),
        "llm_backend": _stringify(parse_result.get("llm_backend")),
        "last_run_uid": _stringify(parse_result.get("output_name")),
    }
    upsert_parse_asset_rows(content_db_path, [parse_asset_row])
    save_structured_state(
        content_db_path,
        uid_literature=resolved_uid,
        structured_status="ready",
        structured_abs_path=str(normalized_structured_path),
        structured_backend="monkeyocr_windows",
        structured_task_type=parse_level,
        structured_updated_at=_stringify((structured_payload.get("parse_profile") or {}).get("created_at")),
        structured_schema_version=_stringify(structured_payload.get("schema")),
        structured_text_length=len(_stringify(text_payload.get("full_text"))),
        structured_reference_count=len(references_payload),
    )

    current = _select_existing_asset(
        content_db_path,
        parse_level=parse_level,
        uid_literature=resolved_uid,
        cite_key=resolved_cite_key,
    )
    return current or parse_asset_row


__all__ = [
    "build_normalized_structured_from_multimodal_result",
    "ensure_pdf_text_fallback_asset",
    "ensure_multimodal_parse_asset",
]
