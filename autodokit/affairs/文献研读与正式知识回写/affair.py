"""A100 文献精解析资产化事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import append_aok_log_event, build_gate_review, load_json_or_py
from autodokit.tools.bibliodb_sqlite import load_reading_state_df, upsert_reading_state_rows
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.ocr.aliyun_multimodal.aliyun_multimodal_postprocess_tools import postprocess_aliyun_multimodal_parse_outputs
from autodokit.tools.ocr.classic.pdf_parse_asset_manager import ensure_multimodal_parse_asset, ensure_pdf_text_fallback_asset
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


OUTPUT_INDEX = "a100_deep_parse_index.csv"
OUTPUT_GATE = "gate_review.json"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _resolve_workspace_root(config_path: Path, raw_cfg: Dict[str, Any]) -> Path:
    candidate = _stringify(raw_cfg.get("workspace_root"))
    if candidate:
        path = Path(candidate)
        if not path.is_absolute():
            raise ValueError(f"workspace_root 必须为绝对路径: {path}")
        return path
    return config_path.parents[2]


def _resolve_output_dir(config_path: Path, raw_cfg: Dict[str, Any]) -> Path:
    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(f"output_dir 必须为绝对路径: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


@affair_auto_git_commit("A100")
def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    output_dir = _resolve_output_dir(config_path, raw_cfg)
    content_db, _ = resolve_content_db_config(
        raw_cfg,
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None

    state_df = load_reading_state_df(content_db, flag_filters={"pending_deep_read": 1})
    max_items = int(raw_cfg.get("max_items") or 3)
    if max_items > 0:
        state_df = state_df.head(max_items).reset_index(drop=True)

    parse_model = _stringify(raw_cfg.get("parse_model")) or "auto"
    overwrite_parse_asset = bool(raw_cfg.get("overwrite_parse_asset", False))
    allow_pdf_text_fallback_on_parse_failure = bool(raw_cfg.get("allow_pdf_text_fallback_on_parse_failure", True))
    enable_aliyun_postprocess = bool(raw_cfg.get("enable_aliyun_postprocess", True))
    enable_llm_basic_cleanup = bool(raw_cfg.get("enable_llm_basic_cleanup", True))
    basic_cleanup_llm_model = _stringify(raw_cfg.get("basic_cleanup_llm_model")) or "qwen3.5-flash"
    basic_cleanup_llm_sdk_backend = _stringify(raw_cfg.get("basic_cleanup_llm_sdk_backend")) or None
    basic_cleanup_llm_region = _stringify(raw_cfg.get("basic_cleanup_llm_region")) or "cn-beijing"
    enable_llm_structure_resolution = bool(raw_cfg.get("enable_llm_structure_resolution", True))
    structure_llm_model = _stringify(raw_cfg.get("structure_llm_model")) or "qwen3.5-plus"
    structure_llm_sdk_backend = _stringify(raw_cfg.get("structure_llm_sdk_backend")) or None
    structure_llm_region = _stringify(raw_cfg.get("structure_llm_region")) or "cn-beijing"
    enable_llm_contamination_filter = bool(raw_cfg.get("enable_llm_contamination_filter", True))
    contamination_llm_model = _stringify(raw_cfg.get("contamination_llm_model")) or "qwen3-max"
    contamination_llm_sdk_backend = _stringify(raw_cfg.get("contamination_llm_sdk_backend")) or None
    contamination_llm_region = _stringify(raw_cfg.get("contamination_llm_region")) or "cn-beijing"
    postprocess_rewrite_structured = bool(raw_cfg.get("postprocess_rewrite_structured", True))
    postprocess_rewrite_markdown = bool(raw_cfg.get("postprocess_rewrite_markdown", True))
    postprocess_keep_page_markers = bool(raw_cfg.get("postprocess_keep_page_markers", False))

    result_rows: List[Dict[str, Any]] = []
    state_updates: List[Dict[str, Any]] = []
    failures: List[str] = []
    postprocess_success_count = 0

    for _, row in state_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        source_origin = _stringify(row.get("source_origin")) or "auto"
        upsert_reading_state_rows(
            content_db,
            [
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "pending_deep_read": 0,
                    "in_deep_read": 1,
                    "deep_read_done": 0,
                    "deep_read_decision": "in_parse",
                }
            ],
        )
        try:
            parse_asset = ensure_multimodal_parse_asset(
                content_db=content_db,
                parse_level="non_review_deep",
                uid_literature=uid_literature,
                cite_key=cite_key,
                source_stage="A100",
                global_config_path=workspace_root / "config" / "config.json",
                overwrite_existing=overwrite_parse_asset,
                model=parse_model,
            )
            postprocess_summary: Dict[str, Any] = {}
            if enable_aliyun_postprocess:
                postprocess_summary = postprocess_aliyun_multimodal_parse_outputs(
                    normalized_structured_path=_stringify(parse_asset.get("normalized_structured_path")),
                    reconstructed_markdown_path=_stringify(parse_asset.get("reconstructed_markdown_path")),
                    rewrite_structured=postprocess_rewrite_structured,
                    rewrite_markdown=postprocess_rewrite_markdown,
                    keep_page_markers=postprocess_keep_page_markers,
                    enable_llm_basic_cleanup=enable_llm_basic_cleanup,
                    basic_cleanup_llm_model=basic_cleanup_llm_model,
                    basic_cleanup_llm_sdk_backend=basic_cleanup_llm_sdk_backend,
                    basic_cleanup_llm_region=basic_cleanup_llm_region,
                    enable_llm_structure_resolution=enable_llm_structure_resolution,
                    structure_llm_model=structure_llm_model,
                    structure_llm_sdk_backend=structure_llm_sdk_backend,
                    structure_llm_region=structure_llm_region,
                    enable_llm_contamination_filter=enable_llm_contamination_filter,
                    contamination_llm_model=contamination_llm_model,
                    contamination_llm_sdk_backend=contamination_llm_sdk_backend,
                    contamination_llm_region=contamination_llm_region,
                    config_path=workspace_root / "config" / "config.json",
                )
                postprocess_success_count += 1
            structured_json = _stringify(parse_asset.get("normalized_structured_path"))
            state_updates.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "source_origin": source_origin,
                    "pending_deep_read": 0,
                    "in_deep_read": 0,
                    "deep_read_done": 0,
                    "deep_read_decision": "parse_ready",
                    "deep_read_reason": (
                        "A100 已完成 non_review_deep 解析资产准备，"
                        "等待 A105 执行批判性研读与标准笔记写回。"
                    ),
                }
            )
            result_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "structured_json": structured_json,
                    "asset_dir": _stringify(parse_asset.get("asset_dir")),
                    "parse_status": _stringify(parse_asset.get("parse_status")) or "ready",
                    "postprocess_enabled": int(enable_aliyun_postprocess),
                    "postprocess_ok": int(bool(postprocess_summary) or (not enable_aliyun_postprocess)),
                    "postprocess_removed_noise_lines": int(postprocess_summary.get("removed_noise_lines") or 0),
                    "postprocess_llm_basic_cleanup_status": _stringify(postprocess_summary.get("llm_basic_cleanup_status")),
                    "postprocess_llm_structure_status": _stringify(postprocess_summary.get("llm_structure_resolution_status")),
                    "postprocess_contamination_removed_block_count": int(postprocess_summary.get("contamination_removed_block_count") or 0),
                    "postprocess_markdown_path": _stringify(postprocess_summary.get("postprocessed_markdown_path")),
                    "postprocess_audit_path": _stringify(postprocess_summary.get("postprocess_audit_path")),
                }
            )
        except Exception as exc:
            fallback_asset: Dict[str, Any] = {}
            fallback_exc: Exception | None = None
            if allow_pdf_text_fallback_on_parse_failure:
                try:
                    fallback_asset = ensure_pdf_text_fallback_asset(
                        content_db=content_db,
                        parse_level="non_review_deep",
                        uid_literature=uid_literature,
                        cite_key=cite_key,
                        source_stage="A100",
                        overwrite_existing=True,
                    )
                except Exception as fallback_error:
                    fallback_exc = fallback_error

            if fallback_asset:
                state_updates.append(
                    {
                        "uid_literature": uid_literature,
                        "cite_key": cite_key,
                        "source_origin": source_origin,
                        "pending_deep_read": 0,
                        "in_deep_read": 0,
                        "deep_read_done": 0,
                        "deep_read_decision": "pdf_fallback_ready",
                        "deep_read_reason": f"A100 多模态解析失败，已切换为原文 PDF 直读旁路。原始错误：{exc}",
                    }
                )
                result_rows.append(
                    {
                        "uid_literature": uid_literature,
                        "cite_key": cite_key,
                        "structured_json": _stringify(fallback_asset.get("normalized_structured_path")),
                        "asset_dir": _stringify(fallback_asset.get("asset_dir")),
                        "parse_status": "fallback_ready",
                        "postprocess_enabled": 0,
                        "postprocess_ok": 0,
                        "postprocess_removed_noise_lines": 0,
                        "postprocess_llm_basic_cleanup_status": "skipped_pdf_text_fallback",
                        "postprocess_llm_structure_status": "skipped_pdf_text_fallback",
                        "postprocess_contamination_removed_block_count": 0,
                        "postprocess_markdown_path": _stringify(fallback_asset.get("reconstructed_markdown_path")),
                        "postprocess_audit_path": "",
                    }
                )
                failures.append(f"{cite_key}: 多模态解析失败，已降级为原文 PDF 直读旁路: {exc}")
            else:
                reason = str(exc) if fallback_exc is None else f"{exc}; fallback 失败: {fallback_exc}"
                failures.append(f"{cite_key}: 深读失败: {reason}")
                state_updates.append(
                    {
                        "uid_literature": uid_literature,
                        "cite_key": cite_key,
                        "pending_deep_read": 1,
                        "in_deep_read": 0,
                        "deep_read_done": 0,
                        "deep_read_decision": "parse_failed",
                        "deep_read_reason": reason,
                    }
                )

    if state_updates:
        upsert_reading_state_rows(content_db, state_updates)

    result_df = pd.DataFrame(result_rows)
    index_path = output_dir / OUTPUT_INDEX
    result_df.to_csv(index_path, index=False, encoding="utf-8-sig")

    gate_review = build_gate_review(
        node_uid="A100",
        node_name="文献精解析资产化",
        summary=(
            f"完成 deep parse 准备 {len(result_rows)} 篇；"
            f"后处理成功 {postprocess_success_count} 篇；失败 {len(failures)} 篇。"
        ),
        checks=[
            {"name": "deep_parse_ready_count", "value": len(result_rows)},
            {"name": "postprocess_success_count", "value": postprocess_success_count},
            {"name": "failure_count", "value": len(failures)},
        ],
        artifacts=[str(index_path)],
        recommendation="pass" if result_rows else "retry_current",
        score=max(45.0, 93.0 - len(failures) * 10.0),
        issues=failures,
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "enable_aliyun_postprocess": enable_aliyun_postprocess,
            "postprocess_rewrite_structured": postprocess_rewrite_structured,
            "postprocess_rewrite_markdown": postprocess_rewrite_markdown,
            "postprocess_keep_page_markers": postprocess_keep_page_markers,
            "enable_llm_basic_cleanup": enable_llm_basic_cleanup,
            "basic_cleanup_llm_model": basic_cleanup_llm_model,
            "basic_cleanup_llm_sdk_backend": basic_cleanup_llm_sdk_backend,
            "basic_cleanup_llm_region": basic_cleanup_llm_region,
            "enable_llm_structure_resolution": enable_llm_structure_resolution,
            "structure_llm_model": structure_llm_model,
            "structure_llm_sdk_backend": structure_llm_sdk_backend,
            "structure_llm_region": structure_llm_region,
            "enable_llm_contamination_filter": enable_llm_contamination_filter,
            "contamination_llm_model": contamination_llm_model,
            "contamination_llm_sdk_backend": contamination_llm_sdk_backend,
            "contamination_llm_region": contamination_llm_region,
            "allow_pdf_text_fallback_on_parse_failure": allow_pdf_text_fallback_on_parse_failure,
        },
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        append_aok_log_event(
            event_type="A100_DEEP_READING_COMPLETED",
            project_root=workspace_root,
            affair_code="A100",
            handler_name="文献精解析资产化",
            agent_names=["ar_A100_文献研读与正式知识回写事务智能体_v6"],
            skill_names=[],
            reasoning_summary="消费 literature_reading_state.pending_deep_read=1，仅完成 non_review_deep 解析资产准备并移交 A105。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=[str(index_path)],
        )
    except Exception:
        pass

    return [index_path]

