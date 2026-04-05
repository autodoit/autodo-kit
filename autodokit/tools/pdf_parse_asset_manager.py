"""PDF 解析资产管理工具。

负责把阿里百炼多模态解析结果注册为统一可复用的解析资产，并补写
兼容旧消费者的 `aok.pdf_structured.v3` 文件入口。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from autodokit.tools.aok_pdf_aliyun_multimodal_parse import parse_pdf_with_aliyun_multimodal
from autodokit.tools.bibliodb_sqlite import (
    load_attachments_df,
    load_literatures_df,
    load_parse_assets_df,
    save_structured_state,
    upsert_parse_asset_rows,
)
from autodokit.tools.contentdb_sqlite import infer_workspace_root_from_content_db
from autodokit.tools.pdf_structured_data_tools import build_structured_data_payload


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _load_json_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


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
                llm_cfg.get("pdf_multimodal_parse_model")
                or llm_cfg.get("aliyun_pdf_parse_model")
                or llm_cfg.get("pdf_parse_model")
                or payload.get("pdf_multimodal_parse_model")
            )
            if candidate:
                return candidate

    return "auto"


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
    output_root = workspace_root / "references" / f"structured_aliyun_multimodal_{parse_level}"
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root.resolve()


def _select_existing_asset(
    content_db: Path,
    *,
    parse_level: str,
    uid_literature: str = "",
    cite_key: str = "",
) -> Dict[str, Any] | None:
    table = load_parse_assets_df(content_db, parse_level=parse_level, only_current=True, parse_statuses=["ready"]).fillna("")
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
    candidate = dict(table.iloc[0].to_dict())
    normalized_structured_path = Path(_stringify(candidate.get("normalized_structured_path")))
    if normalized_structured_path.exists() and normalized_structured_path.is_file():
        return candidate
    return None


def build_normalized_structured_from_multimodal_result(
    *,
    pdf_path: str | Path,
    parse_result: Dict[str, Any],
    parse_level: str,
    uid_literature: str = "",
    cite_key: str = "",
    title: str = "",
    year: str = "",
) -> Path:
    """把多模态目录资产转换为兼容旧消费者的 structured.json。"""

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
        backend="aliyun_multimodal",
        backend_family="aliyun_multimodal",
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

    pdf_path = _resolve_pdf_path(content_db_path, literature_row)
    resolved_api_key_file = _resolve_api_key_file(api_key_file=api_key_file, global_config_path=global_config_path)
    output_root = _resolve_output_root(content_db_path, parse_level)
    output_name = _safe_stem(resolved_cite_key or resolved_uid or pdf_path.stem)

    resolved_model = _resolve_model(model=model, global_config_path=global_config_path)
    resolved_sdk_backend = _resolve_sdk_backend(sdk_backend=sdk_backend, global_config_path=global_config_path)

    parse_result = parse_pdf_with_aliyun_multimodal(
        pdf_path=pdf_path,
        output_root=output_root,
        output_name=output_name,
        api_key_file=resolved_api_key_file,
        model=resolved_model,
        sdk_backend=resolved_sdk_backend,
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
    )
    normalized_structured_path = build_normalized_structured_from_multimodal_result(
        pdf_path=pdf_path,
        parse_result=parse_result,
        parse_level=parse_level,
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
        "backend": "aliyun_multimodal",
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
        structured_backend="aliyun_multimodal",
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
    "ensure_multimodal_parse_asset",
]