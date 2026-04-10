"""MonkeyOCR 清单驱动解析运行时。

本模块用于在不改动既有 MonkeyOCR tools 的前提下，把
文献清单驱动的批量解析能力接入 A060、A080、A100。
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd

from autodokit.tools.bibliodb_sqlite import save_structured_state, upsert_parse_asset_rows
from autodokit.tools.contentdb_sqlite import infer_workspace_root_from_content_db
from autodokit.tools.llm_clients import postprocess_aliyun_multimodal_parse_outputs
from autodokit.tools.ocr.classic.pdf_parse_asset_manager import (
    _bootstrap_existing_asset,
    _load_global_config,
    _resolve_literature_row,
    _resolve_monkeyocr_model_name,
    _resolve_monkeyocr_root,
    _resolve_output_root,
    _resolve_pdf_path,
    _select_existing_asset,
    build_normalized_structured_from_multimodal_result,
)
from autodokit.tools.ocr.monkeyocr.monkeyocr_windows_tools import parse_pdf_with_monkeyocr_windows


MANIFEST_CSV_NAME = "parse_manifest.csv"
MANIFEST_MD_NAME = "parse_manifest.readable.md"
MANAGEMENT_CSV_NAME = "management_table.csv"
BATCH_REPORT_NAME = "batch_report.json"
HANDOFF_NAME = "handoff.json"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _safe_stem(text: str) -> str:
    value = _stringify(text)
    value = "".join("_" if char in '\\/:*?\"<>|' else char for char in value)
    value = "_".join(value.split())
    return value or "untitled"


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = _stringify(value).lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "on", "enabled", "是"}


def _normalize_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _resolve_path(value: Any, *, base_dir: Path | None = None) -> str:
    text = _stringify(value)
    if not text:
        return ""
    path = Path(text)
    if not path.is_absolute():
        if base_dir is None:
            raise ValueError(f"路径必须为绝对路径：{path}")
        path = (base_dir / path).resolve()
    return str(path.resolve())


def resolve_postprocess_settings(raw_cfg: Mapping[str, Any], *, workspace_root: Path) -> Dict[str, Any]:
    return {
        "enabled": bool(raw_cfg.get("enable_aliyun_postprocess", True)),
        "rewrite_structured": bool(raw_cfg.get("postprocess_rewrite_structured", True)),
        "rewrite_markdown": bool(raw_cfg.get("postprocess_rewrite_markdown", True)),
        "keep_page_markers": bool(raw_cfg.get("postprocess_keep_page_markers", False)),
        "enable_llm_basic_cleanup": bool(raw_cfg.get("enable_llm_basic_cleanup", True)),
        "basic_cleanup_llm_model": _stringify(raw_cfg.get("basic_cleanup_llm_model")) or "qwen3.5-flash",
        "basic_cleanup_llm_sdk_backend": _stringify(raw_cfg.get("basic_cleanup_llm_sdk_backend")) or None,
        "basic_cleanup_llm_region": _stringify(raw_cfg.get("basic_cleanup_llm_region")) or "cn-beijing",
        "enable_llm_structure_resolution": bool(raw_cfg.get("enable_llm_structure_resolution", True)),
        "structure_llm_model": _stringify(raw_cfg.get("structure_llm_model")) or "qwen3.5-plus",
        "structure_llm_sdk_backend": _stringify(raw_cfg.get("structure_llm_sdk_backend")) or None,
        "structure_llm_region": _stringify(raw_cfg.get("structure_llm_region")) or "cn-beijing",
        "enable_llm_contamination_filter": bool(raw_cfg.get("enable_llm_contamination_filter", True)),
        "contamination_llm_model": _stringify(raw_cfg.get("contamination_llm_model")) or "qwen3-max",
        "contamination_llm_sdk_backend": _stringify(raw_cfg.get("contamination_llm_sdk_backend")) or None,
        "contamination_llm_region": _stringify(raw_cfg.get("contamination_llm_region")) or "cn-beijing",
        "config_path": str((workspace_root / "config" / "config.json").resolve()),
        "api_key_file": _stringify(raw_cfg.get("api_key_file")) or None,
    }


def resolve_parse_runtime_settings(
    raw_cfg: Mapping[str, Any],
    *,
    workspace_root: Path,
    global_config_path: Path | None,
) -> Dict[str, Any]:
    global_cfg = _load_global_config(global_config_path)
    global_runtime = global_cfg.get("pdf_parse_runtime") if isinstance(global_cfg.get("pdf_parse_runtime"), dict) else {}
    node_runtime = raw_cfg.get("pdf_parse_runtime") if isinstance(raw_cfg.get("pdf_parse_runtime"), dict) else {}
    merged: Dict[str, Any] = {}
    if isinstance(global_runtime, dict):
        merged.update(global_runtime)
    if isinstance(node_runtime, dict):
        merged.update(node_runtime)

    monkey_root_cfg = dict(merged)
    if not monkey_root_cfg.get("monkeyocr_root") and global_cfg.get("monkeyocr_root"):
        monkey_root_cfg["monkeyocr_root"] = global_cfg.get("monkeyocr_root")
    if not monkey_root_cfg.get("monkeyocr_model_name") and merged.get("model_name"):
        monkey_root_cfg["monkeyocr_model_name"] = merged.get("model_name")
    if not monkey_root_cfg.get("monkeyocr_model_name") and global_cfg.get("monkeyocr_model_name"):
        monkey_root_cfg["monkeyocr_model_name"] = global_cfg.get("monkeyocr_model_name")
    if not monkey_root_cfg.get("monkeyocr_model") and global_cfg.get("monkeyocr_model"):
        monkey_root_cfg["monkeyocr_model"] = global_cfg.get("monkeyocr_model")

    runtime_root = _resolve_path(
        merged.get("runtime_root") or workspace_root / "runtime" / "monkeyocr",
        base_dir=workspace_root,
    )
    lock_name = _stringify(merged.get("lock_name")) or "monkeyocr_gpu"
    config_path = _resolve_path(merged.get("config_path"), base_dir=workspace_root) if merged.get("config_path") else ""
    models_dir = _resolve_path(merged.get("models_dir"), base_dir=workspace_root) if merged.get("models_dir") else ""
    python_executable = _resolve_path(merged.get("python_executable"), base_dir=workspace_root) if merged.get("python_executable") else ""

    return {
        "backend": _stringify(merged.get("backend")) or "monkeyocr_windows",
        "device": _stringify(merged.get("device")) or "cuda",
        "gpu_visible_devices": _stringify(merged.get("gpu_visible_devices")) or "0",
        "max_retries": _normalize_int(merged.get("max_retries"), 2),
        "skip_existing": _normalize_bool(merged.get("skip_existing"), True),
        "ensure_runtime": _normalize_bool(merged.get("ensure_runtime"), True),
        "download_source": _stringify(merged.get("download_source")) or "huggingface",
        "pip_index_url": _stringify(merged.get("pip_index_url")) or None,
        "runtime_root": runtime_root,
        "lock_name": lock_name,
        "acquire_gpu_lock": _normalize_bool(merged.get("acquire_gpu_lock"), True),
        "models_dir": models_dir,
        "config_path": config_path,
        "python_executable": python_executable,
        "monkeyocr_root": str(_resolve_monkeyocr_root(workspace_root=workspace_root, raw_cfg=monkey_root_cfg)),
        "model_name": _stringify(merged.get("model_name")) or _resolve_monkeyocr_model_name(raw_cfg=monkey_root_cfg),
    }


def build_parse_manifest_df(
    *,
    content_db: Path,
    source_df: pd.DataFrame,
    source_stage: str,
    upstream_stage: str,
    parse_level: str,
    literature_scope: str,
    max_items: int = 0,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for index, row in enumerate(source_df.fillna("").to_dict(orient="records"), start=1):
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        title = _stringify(row.get("title"))
        priority_rank = _normalize_int(row.get("priority_rank") or row.get("priority") or index, index)
        pdf_path = _stringify(row.get("pdf_path"))
        failure_reason = ""

        if uid_literature or cite_key:
            try:
                literature_row = _resolve_literature_row(content_db, uid_literature=uid_literature, cite_key=cite_key)
                if not title:
                    title = _stringify(literature_row.get("title"))
                if not cite_key:
                    cite_key = _stringify(literature_row.get("cite_key"))
                if not uid_literature:
                    uid_literature = _stringify(literature_row.get("uid_literature"))
                if not pdf_path:
                    try:
                        pdf_path = str(_resolve_pdf_path(content_db, literature_row))
                    except Exception as exc:
                        failure_reason = str(exc)
            except Exception as exc:
                failure_reason = str(exc)

        manifest_status = "queued" if pdf_path and not failure_reason else "failed"
        rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "title": title,
                "pdf_path": pdf_path,
                "parse_level": parse_level,
                "source_stage": source_stage,
                "upstream_stage": upstream_stage,
                "priority_rank": priority_rank,
                "literature_scope": literature_scope,
                "manifest_status": manifest_status,
                "asset_dir": "",
                "normalized_structured_path": "",
                "reconstructed_markdown_path": "",
                "parse_record_path": "",
                "quality_report_path": "",
                "run_summary": "",
                "failure_reason": failure_reason,
            }
        )

    manifest_df = pd.DataFrame(rows)
    if manifest_df.empty:
        return manifest_df
    manifest_df = manifest_df.sort_values(by=["priority_rank", "cite_key", "uid_literature"], ascending=[True, True, True]).reset_index(drop=True)
    if max_items > 0:
        manifest_df = manifest_df.head(max_items).reset_index(drop=True)
    return manifest_df


def _manifest_to_markdown(manifest_df: pd.DataFrame, *, title: str) -> str:
    lines = [f"# {title}", "", f"总条目数：{len(manifest_df)}", ""]
    if manifest_df.empty:
        lines.append("暂无待解析条目。")
        return "\n".join(lines) + "\n"
    lines.extend([
        "| priority_rank | cite_key | parse_level | source_stage | manifest_status | failure_reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for _, row in manifest_df.fillna("").iterrows():
        lines.append(
            "| {priority_rank} | {cite_key} | {parse_level} | {source_stage} | {manifest_status} | {failure_reason} |".format(
                priority_rank=_stringify(row.get("priority_rank")),
                cite_key=_stringify(row.get("cite_key")),
                parse_level=_stringify(row.get("parse_level")),
                source_stage=_stringify(row.get("source_stage")),
                manifest_status=_stringify(row.get("manifest_status")),
                failure_reason=_stringify(row.get("failure_reason")),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_parse_manifest_artifacts(output_dir: Path, manifest_df: pd.DataFrame) -> tuple[Path, Path]:
    manifest_path = output_dir / MANIFEST_CSV_NAME
    readable_path = output_dir / MANIFEST_MD_NAME
    manifest_df.to_csv(manifest_path, index=False, encoding="utf-8-sig")
    readable_path.write_text(_manifest_to_markdown(manifest_df, title="parse_manifest"), encoding="utf-8")
    return manifest_path, readable_path


def _lock_path(workspace_root: Path, runtime_settings: Mapping[str, Any]) -> Path:
    runtime_root = Path(str(runtime_settings.get("runtime_root") or workspace_root / "runtime" / "monkeyocr")).resolve()
    locks_dir = runtime_root / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    return locks_dir / f"{_safe_stem(_stringify(runtime_settings.get('lock_name')) or 'monkeyocr_gpu')}.lock"


@contextmanager
def gpu_lock(workspace_root: Path, runtime_settings: Mapping[str, Any], *, holder_name: str) -> Iterable[Path | None]:
    if not _normalize_bool(runtime_settings.get("acquire_gpu_lock"), True):
        yield None
        return
    lock_path = _lock_path(workspace_root, runtime_settings)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"GPU 锁已被占用：{lock_path}") from exc
    try:
        os.write(fd, holder_name.encode("utf-8", errors="ignore"))
        yield lock_path
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _register_parse_asset(
    *,
    content_db: Path,
    parse_level: str,
    source_stage: str,
    literature_row: Mapping[str, Any],
    parse_result: Mapping[str, Any],
) -> Dict[str, Any]:
    pdf_path = _resolve_pdf_path(content_db, literature_row)
    resolved_uid = _stringify(literature_row.get("uid_literature"))
    resolved_cite_key = _stringify(literature_row.get("cite_key"))
    normalized_structured_path = build_normalized_structured_from_multimodal_result(
        pdf_path=pdf_path,
        parse_result=dict(parse_result),
        parse_level=parse_level,
        backend="monkeyocr_windows",
        backend_family="monkeyocr",
        uid_literature=resolved_uid,
        cite_key=resolved_cite_key,
        title=_stringify(literature_row.get("title")),
        year=_stringify(literature_row.get("year")),
    )
    structured_payload = json.loads(normalized_structured_path.read_text(encoding="utf-8-sig"))
    text_payload = structured_payload.get("text") if isinstance(structured_payload.get("text"), dict) else {}
    references_payload = structured_payload.get("references") if isinstance(structured_payload.get("references"), list) else []
    parse_asset_row = {
        "uid_literature": resolved_uid,
        "cite_key": resolved_cite_key,
        "parse_level": parse_level,
        "source_stage": source_stage,
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
        "llm_backend": _stringify(parse_result.get("llm_backend")) or "monkeyocr_windows",
        "last_run_uid": _stringify(parse_result.get("output_name")) or _safe_stem(resolved_cite_key or resolved_uid),
    }
    upsert_parse_asset_rows(content_db, [parse_asset_row])
    save_structured_state(
        content_db,
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
    return parse_asset_row


def _run_single_manifest_item(
    *,
    content_db: Path,
    parse_level: str,
    source_stage: str,
    row: Mapping[str, Any],
    runtime_settings: Mapping[str, Any],
    overwrite_existing: bool,
) -> tuple[str, Dict[str, Any], bool]:
    uid_literature = _stringify(row.get("uid_literature"))
    cite_key = _stringify(row.get("cite_key"))
    literature_row = _resolve_literature_row(content_db, uid_literature=uid_literature, cite_key=cite_key)
    existing = None
    if not overwrite_existing:
        existing = _select_existing_asset(content_db, parse_level=parse_level, uid_literature=uid_literature, cite_key=cite_key)
        if existing is not None:
            return "skipped", dict(existing), True
    output_root = _resolve_output_root(content_db, parse_level)
    bootstrapped = _bootstrap_existing_asset(
        content_db_path=content_db,
        parse_level=parse_level,
        literature_row=dict(literature_row),
        output_root=output_root,
        source_stage=source_stage,
    )
    if bootstrapped is not None and not overwrite_existing:
        existing = _select_existing_asset(content_db, parse_level=parse_level, uid_literature=uid_literature, cite_key=cite_key)
        if existing is not None:
            return "skipped", dict(existing), True
    pdf_path = _resolve_pdf_path(content_db, literature_row)
    output_name = _safe_stem(cite_key or uid_literature or pdf_path.stem)
    parse_result = parse_pdf_with_monkeyocr_windows(
        pdf_path=pdf_path,
        output_root=output_root,
        output_name=output_name,
        monkeyocr_root=str(runtime_settings.get("monkeyocr_root") or ""),
        models_dir=str(runtime_settings.get("models_dir") or "") or None,
        config_path=str(runtime_settings.get("config_path") or "") or None,
        model_name=_stringify(runtime_settings.get("model_name")) or "MonkeyOCR-pro-1.2B",
        device=_stringify(runtime_settings.get("device")) or "cuda",
        gpu_visible_devices=_stringify(runtime_settings.get("gpu_visible_devices")) or "0",
        ensure_runtime=_normalize_bool(runtime_settings.get("ensure_runtime"), True),
        download_source=_stringify(runtime_settings.get("download_source")) or "huggingface",
        pip_index_url=_stringify(runtime_settings.get("pip_index_url")) or None,
        python_executable=str(runtime_settings.get("python_executable") or "") or None,
        stream_output=False,
    )
    asset_row = _register_parse_asset(
        content_db=content_db,
        parse_level=parse_level,
        source_stage=source_stage,
        literature_row=literature_row,
        parse_result=parse_result,
    )
    return "succeeded", asset_row, False


def run_parse_manifest(
    *,
    content_db: Path,
    source_df: pd.DataFrame,
    output_dir: Path,
    source_stage: str,
    upstream_stage: str,
    downstream_stage: str,
    parse_level: str,
    literature_scope: str,
    runtime_settings: Mapping[str, Any],
    postprocess_settings: Mapping[str, Any] | None,
    global_config_path: Path | None,
    overwrite_existing: bool,
    max_items: int = 0,
) -> Dict[str, Any]:
    workspace_root = infer_workspace_root_from_content_db(content_db)
    manifest_df = build_parse_manifest_df(
        content_db=content_db,
        source_df=source_df,
        source_stage=source_stage,
        upstream_stage=upstream_stage,
        parse_level=parse_level,
        literature_scope=literature_scope,
        max_items=max_items,
    )
    manifest_path, readable_path = write_parse_manifest_artifacts(output_dir, manifest_df)
    results: List[Dict[str, Any]] = []
    failures: List[str] = []
    succeeded_count = 0
    skipped_count = 0
    failed_count = 0
    lock_error = ""
    lock_path = ""
    try:
        with gpu_lock(workspace_root, runtime_settings, holder_name=f"{source_stage}:{output_dir.name}") as held_lock_path:
            lock_path = str(held_lock_path or "")
            for _, row in manifest_df.fillna("").iterrows():
                row_dict = dict(row.to_dict())
                start = time.perf_counter()
                uid_literature = _stringify(row_dict.get("uid_literature"))
                cite_key = _stringify(row_dict.get("cite_key")) or uid_literature
                title = _stringify(row_dict.get("title")) or cite_key
                manifest_status = _stringify(row_dict.get("manifest_status")) or "queued"
                failure_reason = _stringify(row_dict.get("failure_reason"))
                used_existing_asset = False
                asset_row: Dict[str, Any] = {}
                postprocess_summary: Dict[str, Any] = {}
                if manifest_status == "failed":
                    failed_count += 1
                    results.append({
                        **row_dict,
                        "title": title,
                        "manifest_status": "failed",
                        "failure_reason": failure_reason or "manifest_precheck_failed",
                        "run_summary": failure_reason or "manifest_precheck_failed",
                        "used_existing_asset": 0,
                        "postprocess_enabled": 0,
                        "postprocess_ok": 0,
                        "postprocess_llm_basic_cleanup_status": "",
                        "postprocess_llm_structure_status": "",
                        "postprocess_contamination_removed_block_count": 0,
                        "duration_seconds": round(time.perf_counter() - start, 6),
                    })
                    failures.append(f"{cite_key}: {failure_reason or 'manifest_precheck_failed'}")
                    continue
                try:
                    manifest_status, asset_row, used_existing_asset = _run_single_manifest_item(
                        content_db=content_db,
                        parse_level=parse_level,
                        source_stage=source_stage,
                        row=row_dict,
                        runtime_settings=runtime_settings,
                        overwrite_existing=overwrite_existing,
                    )
                    if postprocess_settings and _normalize_bool(postprocess_settings.get("enabled"), True):
                        normalized_structured_path = _stringify(asset_row.get("normalized_structured_path"))
                        reconstructed_markdown_path = _stringify(asset_row.get("reconstructed_markdown_path"))
                        if normalized_structured_path:
                            postprocess_summary = postprocess_aliyun_multimodal_parse_outputs(
                                normalized_structured_path=normalized_structured_path,
                                reconstructed_markdown_path=reconstructed_markdown_path,
                                rewrite_structured=bool(postprocess_settings.get("rewrite_structured", True)),
                                rewrite_markdown=bool(postprocess_settings.get("rewrite_markdown", True)),
                                keep_page_markers=bool(postprocess_settings.get("keep_page_markers", False)),
                                enable_llm_basic_cleanup=bool(postprocess_settings.get("enable_llm_basic_cleanup", True)),
                                basic_cleanup_llm_model=_stringify(postprocess_settings.get("basic_cleanup_llm_model")) or "qwen3.5-flash",
                                basic_cleanup_llm_sdk_backend=postprocess_settings.get("basic_cleanup_llm_sdk_backend"),
                                basic_cleanup_llm_region=_stringify(postprocess_settings.get("basic_cleanup_llm_region")) or "cn-beijing",
                                enable_llm_structure_resolution=bool(postprocess_settings.get("enable_llm_structure_resolution", True)),
                                structure_llm_model=_stringify(postprocess_settings.get("structure_llm_model")) or "qwen3.5-plus",
                                structure_llm_sdk_backend=postprocess_settings.get("structure_llm_sdk_backend"),
                                structure_llm_region=_stringify(postprocess_settings.get("structure_llm_region")) or "cn-beijing",
                                enable_llm_contamination_filter=bool(postprocess_settings.get("enable_llm_contamination_filter", True)),
                                contamination_llm_model=_stringify(postprocess_settings.get("contamination_llm_model")) or "qwen3-max",
                                contamination_llm_sdk_backend=postprocess_settings.get("contamination_llm_sdk_backend"),
                                contamination_llm_region=_stringify(postprocess_settings.get("contamination_llm_region")) or "cn-beijing",
                                config_path=postprocess_settings.get("config_path"),
                                api_key_file=postprocess_settings.get("api_key_file"),
                            )
                    if manifest_status == "skipped":
                        skipped_count += 1
                    else:
                        succeeded_count += 1
                    results.append({
                        **row_dict,
                        "title": title,
                        "manifest_status": manifest_status,
                        "asset_dir": _stringify(asset_row.get("asset_dir")),
                        "normalized_structured_path": _stringify(asset_row.get("normalized_structured_path")),
                        "reconstructed_markdown_path": _stringify(asset_row.get("reconstructed_markdown_path")),
                        "parse_record_path": _stringify(asset_row.get("parse_record_path")),
                        "quality_report_path": _stringify(asset_row.get("quality_report_path")),
                        "run_summary": "existing_asset_reused" if used_existing_asset else "parse_ready",
                        "failure_reason": "",
                        "used_existing_asset": int(used_existing_asset),
                        "postprocess_enabled": int(bool(postprocess_settings and _normalize_bool(postprocess_settings.get("enabled"), True))),
                        "postprocess_ok": int(bool(postprocess_summary) or not bool(postprocess_settings and _normalize_bool(postprocess_settings.get("enabled"), True))),
                        "postprocess_llm_basic_cleanup_status": _stringify(postprocess_summary.get("llm_basic_cleanup_status")),
                        "postprocess_llm_structure_status": _stringify(postprocess_summary.get("llm_structure_resolution_status")),
                        "postprocess_contamination_removed_block_count": _normalize_int(postprocess_summary.get("contamination_removed_block_count"), 0),
                        "duration_seconds": round(time.perf_counter() - start, 6),
                    })
                except Exception as exc:
                    failed_count += 1
                    failure_reason = str(exc)
                    failures.append(f"{cite_key}: {failure_reason}")
                    results.append({
                        **row_dict,
                        "title": title,
                        "manifest_status": "failed",
                        "failure_reason": failure_reason,
                        "run_summary": failure_reason,
                        "used_existing_asset": 0,
                        "postprocess_enabled": int(bool(postprocess_settings and _normalize_bool(postprocess_settings.get("enabled"), True))),
                        "postprocess_ok": 0,
                        "postprocess_llm_basic_cleanup_status": "",
                        "postprocess_llm_structure_status": "",
                        "postprocess_contamination_removed_block_count": 0,
                        "duration_seconds": round(time.perf_counter() - start, 6),
                    })
    except Exception as exc:
        lock_error = str(exc)
        failed_count = len(manifest_df)
        succeeded_count = 0
        skipped_count = 0
        results = []
        for _, row in manifest_df.fillna("").iterrows():
            row_dict = dict(row.to_dict())
            cite_key = _stringify(row_dict.get("cite_key")) or _stringify(row_dict.get("uid_literature"))
            failures.append(f"{cite_key}: {lock_error}")
            results.append({
                **row_dict,
                "manifest_status": "failed",
                "failure_reason": lock_error,
                "run_summary": lock_error,
                "used_existing_asset": 0,
                "postprocess_enabled": int(bool(postprocess_settings and _normalize_bool(postprocess_settings.get("enabled"), True))),
                "postprocess_ok": 0,
                "postprocess_llm_basic_cleanup_status": "",
                "postprocess_llm_structure_status": "",
                "postprocess_contamination_removed_block_count": 0,
                "duration_seconds": 0.0,
            })
    results_df = pd.DataFrame(results)
    if results_df.empty:
        results_df = manifest_df.copy()
    final_manifest_path, final_readable_path = write_parse_manifest_artifacts(output_dir, results_df)
    management_path = output_dir / MANAGEMENT_CSV_NAME
    results_df.to_csv(management_path, index=False, encoding="utf-8-sig")
    batch_report = {
        "source_stage": source_stage,
        "upstream_stage": upstream_stage,
        "downstream_stage": downstream_stage,
        "parse_level": parse_level,
        "literature_scope": literature_scope,
        "total": int(len(results_df)),
        "succeeded_count": int(succeeded_count),
        "skipped_count": int(skipped_count),
        "failed_count": int(failed_count),
        "lock_error": lock_error,
        "lock_path": lock_path,
        "runtime": {key: value for key, value in dict(runtime_settings).items() if key not in {"python_executable"}},
    }
    batch_report_path = output_dir / BATCH_REPORT_NAME
    batch_report_path.write_text(json.dumps(batch_report, ensure_ascii=False, indent=2), encoding="utf-8")
    handoff_payload = {
        "source_stage": source_stage,
        "downstream_stage": downstream_stage,
        "parse_level": parse_level,
        "success_count": int(succeeded_count + skipped_count),
        "failed_count": int(failed_count),
        "ready_items": results_df[results_df.get("manifest_status", pd.Series(dtype=str)).astype(str).isin(["succeeded", "skipped"])][[column for column in ["uid_literature", "cite_key", "normalized_structured_path"] if column in results_df.columns]].fillna("").to_dict(orient="records"),
        "failure_items": results_df[results_df.get("manifest_status", pd.Series(dtype=str)).astype(str) == "failed"][[column for column in ["uid_literature", "cite_key", "failure_reason"] if column in results_df.columns]].fillna("").to_dict(orient="records"),
    }
    handoff_path = output_dir / HANDOFF_NAME
    handoff_path.write_text(json.dumps(handoff_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "manifest_df": results_df,
        "manifest_path": final_manifest_path,
        "readable_manifest_path": final_readable_path,
        "management_table_path": management_path,
        "batch_report_path": batch_report_path,
        "handoff_path": handoff_path,
        "failures": failures,
        "counts": {
            "total": int(len(results_df)),
            "succeeded": int(succeeded_count),
            "skipped": int(skipped_count),
            "failed": int(failed_count),
        },
        "lock_error": lock_error,
    }


__all__ = [
    "build_parse_manifest_df",
    "resolve_parse_runtime_settings",
    "resolve_postprocess_settings",
    "run_parse_manifest",
    "write_parse_manifest_artifacts",
]
