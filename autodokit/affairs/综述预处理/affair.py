"""综述预处理事务。

A060 仅负责综述结构化解析资产准备，不执行参考文献映射与笔记骨架生成。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.affairs.候选文献视图构建.affair import (
    _collect_structured_variants,
    _ensure_structured_reference_lines,
    _load_global_config,
    _resolve_content_db_path,
    _resolve_logging_enabled,
    _resolve_workspace_root,
)
from autodokit.tools import append_aok_log_event, build_gate_review, load_json_or_py
from autodokit.tools.atomic.task_aok.task_instance_dir import create_task_instance_dir, mirror_artifacts_to_legacy, resolve_legacy_output_dir
from autodokit.tools.llm_clients import postprocess_aliyun_multimodal_parse_outputs
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.bibliodb_sqlite import load_reading_queue_df, load_review_state_df, upsert_reading_queue_rows, upsert_review_state_rows
from autodokit.tools.storage_backend import load_reference_main_table
from autodokit.tools.time_utils import now_compact


def _safe_read_csv(path: Path) -> pd.DataFrame:
    """安全读取 CSV。

    Args:
        path: CSV 文件绝对路径。

    Returns:
        DataFrame。文件不存在时返回空表。
    """

    if path.exists() and path.is_file():
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    return pd.DataFrame()


def _build_review_pool_from_queue(content_db: Path, literature_table: pd.DataFrame) -> pd.DataFrame:
    """从 stage=A060 队列构建当前 review_read_pool。"""

    queue_df = load_reading_queue_df(
        content_db,
        stage="A060",
        only_current=True,
        queue_statuses=["queued", "candidate", "in_progress"],
    )
    if queue_df.empty:
        return pd.DataFrame()
    merged = queue_df.copy()
    merged["uid_literature"] = merged.get("uid_literature", pd.Series(dtype=str)).astype(str)
    if literature_table is not None and not literature_table.empty and "uid_literature" in literature_table.columns:
        literature = literature_table.copy()
        literature["uid_literature"] = literature.get("uid_literature", pd.Series(dtype=str)).astype(str)
        merged = merged.merge(literature, on="uid_literature", how="left", suffixes=("_queue", ""))
    merged["cite_key"] = merged.get("cite_key", merged.get("cite_key_queue", pd.Series(dtype=str))).fillna("")
    return merged.fillna("")


def _build_review_pool_from_state(content_db: Path, literature_table: pd.DataFrame) -> pd.DataFrame:
    """从 review_state 构建 A060 输入池。"""

    state_df = load_review_state_df(content_db, flag_filters={"pending_review_parse": 1})
    if state_df.empty:
        return pd.DataFrame()
    merged = state_df.copy()
    merged["uid_literature"] = merged.get("uid_literature", pd.Series(dtype=str)).astype(str)
    if literature_table is not None and not literature_table.empty and "uid_literature" in literature_table.columns:
        literature = literature_table.copy()
        literature["uid_literature"] = literature.get("uid_literature", pd.Series(dtype=str)).astype(str)
        merged = merged.merge(literature, on="uid_literature", how="left", suffixes=("_state", ""))
    merged["cite_key"] = merged.get("cite_key", merged.get("cite_key_state", pd.Series(dtype=str))).fillna("")
    return merged.fillna("")


def _build_a065_queue_rows(
    review_read_pool: pd.DataFrame,
    *,
    run_uid: str,
    topic: str,
) -> List[Dict[str, Any]]:
    """构建 A060 -> A065 队列。"""

    rows: List[Dict[str, Any]] = []
    for _, row in review_read_pool.fillna("").iterrows():
        uid_literature = str(row.get("uid_literature") or "").strip()
        cite_key = str(row.get("cite_key") or "").strip()
        if not uid_literature and not cite_key:
            continue
        rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "stage": "A065",
                "source_affair": "A060",
                "queue_status": "queued",
                "priority": row.get("score") or row.get("priority") or 68.0,
                "bucket": "review_parse_ready",
                "preferred_next_stage": "A080",
                "recommended_reason": "A060 结构化解析资产已就绪，进入 A065 引文与骨架处理",
                "theme_relation": topic,
                "source_round": "a060",
                "run_uid": run_uid,
                "scope_key": "a060_to_a065",
                "is_current": 1,
            }
        )
    return rows


@affair_auto_git_commit("A060")
def execute(config_path: Path) -> List[Path]:
    """执行 A060 综述结构化解析资产准备。

    Args:
        config_path: 节点配置文件路径。

    Returns:
        产物路径列表。

    Raises:
        ValueError: 当缺少 content_db 时抛出。
        FileNotFoundError: 当 A050 必需输入缺失时抛出。
    """

    raw_cfg = load_json_or_py(config_path)
    if not isinstance(raw_cfg, dict):
        raise ValueError("A060 配置必须是字典")

    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    legacy_output_dir = resolve_legacy_output_dir(
        raw_cfg,
        config_path,
        default_path=workspace_root / "steps" / "A060_review_preprocessing",
    )
    output_dir = create_task_instance_dir(workspace_root, "A060")

    global_config_path = workspace_root / "config" / "config.json"
    if not global_config_path.exists():
        global_config_path = None
    global_cfg = _load_global_config(global_config_path)
    logging_enabled = _resolve_logging_enabled(global_cfg)

    content_db, db_input_key = _resolve_content_db_path(raw_cfg, global_cfg)
    if content_db is None:
        raise ValueError("A060 需要 content_db（可由节点配置或 config.paths.content_db_path 提供）")

    literature_table = load_reference_main_table(content_db)
    review_read_pool = _build_review_pool_from_state(content_db, literature_table)
    if review_read_pool.empty:
        review_read_pool = _build_review_pool_from_queue(content_db, literature_table)

    review_read_pool_path = workspace_root / "views" / "review_candidates" / "review_read_pool.csv"
    if review_read_pool.empty and review_read_pool_path.exists():
        review_read_pool = _safe_read_csv(review_read_pool_path)
    if review_read_pool.empty:
        raise FileNotFoundError("未找到可用的综述阅读池（A060 队列或 review_read_pool.csv）。")

    review_reading_batches_path = workspace_root / "batches" / "review_candidates" / "review_reading_batches.csv"
    review_reading_batches = _safe_read_csv(review_reading_batches_path)

    structured_variants = _collect_structured_variants(raw_cfg)
    enable_aliyun_postprocess = bool(raw_cfg.get("enable_aliyun_postprocess", True))
    enable_llm_basic_cleanup = bool(raw_cfg.get("enable_llm_basic_cleanup", True))
    basic_cleanup_llm_model = str(raw_cfg.get("basic_cleanup_llm_model") or "qwen3.5-flash").strip() or "qwen3.5-flash"
    basic_cleanup_llm_sdk_backend = str(raw_cfg.get("basic_cleanup_llm_sdk_backend") or "").strip() or None
    basic_cleanup_llm_region = str(raw_cfg.get("basic_cleanup_llm_region") or "cn-beijing").strip() or "cn-beijing"
    enable_llm_structure_resolution = bool(raw_cfg.get("enable_llm_structure_resolution", True))
    structure_llm_model = str(raw_cfg.get("structure_llm_model") or "qwen3.5-plus").strip() or "qwen3.5-plus"
    structure_llm_sdk_backend = str(raw_cfg.get("structure_llm_sdk_backend") or "").strip() or None
    structure_llm_region = str(raw_cfg.get("structure_llm_region") or "cn-beijing").strip() or "cn-beijing"
    enable_llm_contamination_filter = bool(raw_cfg.get("enable_llm_contamination_filter", True))
    contamination_llm_model = str(raw_cfg.get("contamination_llm_model") or "qwen3-max").strip() or "qwen3-max"
    contamination_llm_sdk_backend = str(raw_cfg.get("contamination_llm_sdk_backend") or "").strip() or None
    contamination_llm_region = str(raw_cfg.get("contamination_llm_region") or "cn-beijing").strip() or "cn-beijing"
    postprocess_rewrite_structured = bool(raw_cfg.get("postprocess_rewrite_structured", True))
    postprocess_rewrite_markdown = bool(raw_cfg.get("postprocess_rewrite_markdown", True))
    postprocess_keep_page_markers = bool(raw_cfg.get("postprocess_keep_page_markers", False))
    parse_status_rows: List[Dict[str, Any]] = []
    ready_count = 0
    postprocess_success_count = 0
    for _, row in review_read_pool.fillna("").iterrows():
        record = dict(row)
        uid_literature = str(record.get("uid_literature") or "").strip()
        cite_key = str(record.get("cite_key") or "").strip()
        source_record = record
        if not literature_table.empty and uid_literature and "uid_literature" in literature_table.columns:
            matched = literature_table[literature_table["uid_literature"].astype(str) == uid_literature]
            if not matched.empty:
                source_record = dict(matched.iloc[0].to_dict())

        status = "ready"
        reason = ""
        used_structured = False
        structured_path = ""
        postprocess_summary: Dict[str, Any] = {}
        try:
            _, source_record, _, _, used_structured = _ensure_structured_reference_lines(
                source_record=source_record,
                workspace_root=workspace_root,
                content_db=content_db,
                working_literature=literature_table,
                structured_variants=structured_variants,
                structured_converter=str(raw_cfg.get("structured_converter") or "aliyun_multimodal"),
                structured_task_type=str(raw_cfg.get("structured_task_type") or "review_deep"),
                structured_overwrite=bool(raw_cfg.get("structured_overwrite") or raw_cfg.get("overwrite_parse_asset")),
                structured_generation_required=bool(raw_cfg.get("structured_generation_required", True)),
                structured_extractors=raw_cfg.get("structured_extractors") if isinstance(raw_cfg.get("structured_extractors"), dict) else None,
                api_key_file=str(raw_cfg.get("api_key_file") or ""),
                parse_model=str(raw_cfg.get("parse_model") or ""),
                structured_babeldoc=raw_cfg.get("structured_babeldoc") if isinstance(raw_cfg.get("structured_babeldoc"), dict) else None,
            )
            structured_path = str(source_record.get("structured_abs_path") or "")
            if used_structured:
                if enable_aliyun_postprocess and structured_path:
                    postprocess_summary = postprocess_aliyun_multimodal_parse_outputs(
                        normalized_structured_path=structured_path,
                        reconstructed_markdown_path=str(Path(structured_path).parent / "reconstructed_content.md"),
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
                        api_key_file=str(raw_cfg.get("api_key_file") or "") or None,
                    )
                    postprocess_success_count += 1
                ready_count += 1
            else:
                status = "not_ready"
                reason = "未命中 structured 资产。"
        except Exception as exc:
            status = "failed"
            reason = str(exc)

        parse_status_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "status": status,
                "used_structured": int(used_structured),
                "structured_abs_path": structured_path,
                "postprocess_enabled": int(enable_aliyun_postprocess),
                "postprocess_ok": int(bool(postprocess_summary) or (not enable_aliyun_postprocess)),
                "postprocess_removed_noise_lines": int(postprocess_summary.get("removed_noise_lines") or 0),
                "postprocess_llm_basic_cleanup_status": str(postprocess_summary.get("llm_basic_cleanup_status") or ""),
                "postprocess_llm_structure_status": str(postprocess_summary.get("llm_structure_resolution_status") or ""),
                "postprocess_contamination_removed_block_count": int(postprocess_summary.get("contamination_removed_block_count") or 0),
                "postprocess_markdown_path": str(postprocess_summary.get("postprocessed_markdown_path") or ""),
                "reason": reason,
            }
        )

    parse_status_path = output_dir / "parse_asset_status.csv"
    pd.DataFrame(parse_status_rows).to_csv(parse_status_path, index=False, encoding="utf-8-sig")

    run_uid = f"a060-{now_compact()}"
    topic = str(raw_cfg.get("research_topic") or raw_cfg.get("topic") or "A060_topic")
    a065_queue_rows = _build_a065_queue_rows(review_read_pool, run_uid=run_uid, topic=topic)
    if a065_queue_rows:
        upsert_reading_queue_rows(content_db, a065_queue_rows)
    review_state_rows: List[Dict[str, Any]] = []
    for _, row in review_read_pool.fillna("").iterrows():
        uid_literature = str(row.get("uid_literature") or "").strip()
        cite_key = str(row.get("cite_key") or "").strip()
        if not uid_literature and not cite_key:
            continue
        review_state_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "source_stage": "A060",
                "pending_review_parse": 0,
                "review_parse_ready": 1,
                "pending_reference_preprocess": 1,
                "reference_preprocessed": 0,
            }
        )
    if review_state_rows:
        upsert_review_state_rows(content_db, review_state_rows)

    gate_review = build_gate_review(
        node_uid="A060",
        node_name="综述预处理",
        summary=(
            f"完成综述结构化资产准备：阅读池 {len(review_read_pool)} 条，"
            f"structured 就绪 {ready_count} 条，后处理成功 {postprocess_success_count} 条，进入 A065 队列 {len(a065_queue_rows)} 条。"
        ),
        checks=[
            {"name": "review_read_pool_count", "value": len(review_read_pool)},
            {"name": "batch_count", "value": int(review_reading_batches['batch_id'].nunique()) if not review_reading_batches.empty and 'batch_id' in review_reading_batches.columns else 0},
            {"name": "structured_ready_count", "value": ready_count},
            {"name": "postprocess_success_count", "value": postprocess_success_count},
            {"name": "structured_failed_count", "value": sum(1 for item in parse_status_rows if item["status"] == "failed")},
            {"name": "a065_queue_count", "value": len(a065_queue_rows)},
        ],
        artifacts=[
            str(review_read_pool_path),
            str(review_reading_batches_path),
            str(parse_status_path),
        ],
        recommendation="pass" if len(review_read_pool) > 0 and ready_count > 0 else "retry_current",
        score=90.0 if len(review_read_pool) > 0 and ready_count > 0 else 65.0,
        issues=[item["reason"] for item in parse_status_rows if item["status"] == "failed" and item.get("reason")],
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "db_input_key": db_input_key,
            "research_topic": raw_cfg.get("research_topic") or raw_cfg.get("topic"),
            "source_review_read_pool_path": str(review_read_pool_path),
            "source_review_reading_batches_path": str(review_reading_batches_path),
            "a065_queue_count": len(a065_queue_rows),
            "structured_ready_count": ready_count,
            "postprocess_success_count": postprocess_success_count,
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
            "run_uid": run_uid,
        },
    )

    gate_path = output_dir / "gate_review.json"
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    append_aok_log_event(
        event_type="A060_REVIEW_PREPROCESSING_COMPLETED",
        project_root=workspace_root,
        enabled=logging_enabled,
        affair_code="A060",
        handler_name="综述预处理",
        agent_names=["ar_A060_综述预处理事务智能体_v5"],
        skill_names=["ar_A060_综述预处理_v5", "m_ObsidianMarkdown_v1"],
        reasoning_summary="承接 A050 阅读池，完成 parse asset 预热并推进到 A065。",
        gate_review=gate_review,
        gate_review_path=gate_path,
        artifact_paths=[parse_status_path, gate_path],
        payload={
            "review_read_pool_count": len(review_read_pool),
            "batch_count": int(review_reading_batches['batch_id'].nunique()) if not review_reading_batches.empty and 'batch_id' in review_reading_batches.columns else 0,
            "structured_ready_count": ready_count,
            "postprocess_success_count": postprocess_success_count,
            "enable_llm_basic_cleanup": enable_llm_basic_cleanup,
            "enable_llm_structure_resolution": enable_llm_structure_resolution,
            "enable_llm_contamination_filter": enable_llm_contamination_filter,
            "a065_queue_count": len(a065_queue_rows),
            "run_uid": run_uid,
        },
    )

    mirror_artifacts_to_legacy([parse_status_path, gate_path], legacy_output_dir, output_dir)
    return [
        parse_status_path,
        gate_path,
    ]
