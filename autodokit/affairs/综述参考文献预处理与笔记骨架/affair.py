"""综述参考文献预处理与笔记骨架事务。

A065 承接 A060 已就绪的综述解析资产，执行参考文献处理、标准笔记骨架生成，并写入 A080。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.affairs.候选文献视图构建.affair import (
    _collect_structured_variants,
    _load_global_config,
    _prepare_review_assets,
    _resolve_content_db_path,
    _resolve_logging_enabled,
    _resolve_workspace_root,
)
from autodokit.tools import append_aok_log_event, batch_rewrite_obsidian_note_timestamps, build_gate_review, load_json_or_py
from autodokit.tools.atomic.task_aok.task_instance_dir import create_task_instance_dir, mirror_artifacts_to_legacy, resolve_legacy_output_dir
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.bibliodb_sqlite import load_reading_queue_df, upsert_reading_queue_rows
from autodokit.tools.storage_backend import load_reference_main_table


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if path.exists() and path.is_file():
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    return pd.DataFrame()


def _load_note_paths_from_created_notes_csv(path: Path) -> list[Path]:
    table = _safe_read_csv(path)
    if table.empty or "note_path" not in table.columns:
        return []
    paths: list[Path] = []
    seen: set[str] = set()
    for raw_path in table["note_path"].tolist():
        text = str(raw_path or "").strip()
        if not text:
            continue
        note_path = Path(text).expanduser().resolve()
        key = str(note_path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(note_path)
    return paths


def _build_review_pool_from_queue(content_db: Path, literature_table: pd.DataFrame) -> pd.DataFrame:
    queue_df = load_reading_queue_df(
        content_db,
        stage="A065",
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


@affair_auto_git_commit("A065")
def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    if not isinstance(raw_cfg, dict):
        raise ValueError("A065 配置必须是字典")

    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    legacy_output_dir = resolve_legacy_output_dir(
        raw_cfg,
        config_path,
        default_path=workspace_root / "steps" / "A065_review_reference_preprocessing",
    )
    output_dir = create_task_instance_dir(workspace_root, "A065")

    global_config_path = workspace_root / "config" / "config.json"
    if not global_config_path.exists():
        global_config_path = None
    global_cfg = _load_global_config(global_config_path)
    logging_enabled = _resolve_logging_enabled(global_cfg)

    content_db, db_input_key = _resolve_content_db_path(raw_cfg, global_cfg)
    if content_db is None:
        raise ValueError("A065 需要 content_db（可由节点配置或 config.paths.content_db_path 提供）")

    literature_table = load_reference_main_table(content_db)
    review_read_pool = _build_review_pool_from_queue(content_db, literature_table)

    review_read_pool_path = workspace_root / "views" / "review_candidates" / "review_read_pool.csv"
    if review_read_pool.empty and review_read_pool_path.exists():
        review_read_pool = _safe_read_csv(review_read_pool_path)
    if review_read_pool.empty:
        raise FileNotFoundError("未找到可用的综述阅读池（A065 队列或 review_read_pool.csv）。")

    review_reading_batches_path = workspace_root / "batches" / "review_candidates" / "review_reading_batches.csv"
    review_reading_batches = _safe_read_csv(review_reading_batches_path)

    structured_variants = _collect_structured_variants(raw_cfg)
    prepared_assets = _prepare_review_assets(
        workspace_root=workspace_root,
        content_db=content_db,
        review_read_pool=review_read_pool,
        review_reading_batches=review_reading_batches,
        literature_table=literature_table,
        global_config_path=global_config_path,
        enable_reference_block_llm=bool(raw_cfg.get("enable_reference_block_llm", True)),
        reference_block_model=str(raw_cfg.get("reference_block_model") or ""),
        reference_block_max_items=int(raw_cfg.get("reference_block_max_items") or 120),
        structured_variants=structured_variants,
        structured_converter=str(raw_cfg.get("structured_converter") or "aliyun_multimodal"),
        structured_task_type=str(raw_cfg.get("structured_task_type") or "review_deep"),
        structured_overwrite=bool(raw_cfg.get("structured_overwrite") or raw_cfg.get("overwrite_parse_asset")),
        structured_generation_required=bool(raw_cfg.get("structured_generation_required", False)),
        structured_extractors=raw_cfg.get("structured_extractors") if isinstance(raw_cfg.get("structured_extractors"), dict) else None,
        api_key_file=str(raw_cfg.get("api_key_file") or ""),
        parse_model=str(raw_cfg.get("parse_model") or ""),
        structured_babeldoc=raw_cfg.get("structured_babeldoc") if isinstance(raw_cfg.get("structured_babeldoc"), dict) else None,
        strict_structured_only=bool(raw_cfg.get("strict_structured_only", True)),
        enable_reference_line_repair=bool(raw_cfg.get("enable_reference_line_repair", True)),
        reference_line_repair_model=str(raw_cfg.get("reference_line_repair_model") or "auto"),
        placeholder_source=str(raw_cfg.get("placeholder_source") or "placeholder_from_a065_review_scan"),
        run_uid_prefix="a065",
    )

    note_timezone = str(
        raw_cfg.get("note_timezone")
        or (global_cfg.get("runtime") or {}).get("default_note_timezone")
        or "Asia/Shanghai"
    ).strip() or "Asia/Shanghai"
    timezone_rewrite_result: Dict[str, Any] = {
        "target_timezone": note_timezone,
        "processed_count": 0,
        "changed_count": 0,
        "results": [],
    }
    validation_errors = list(prepared_assets.get("validation_errors") or [])
    created_notes_path = Path(str(prepared_assets.get("created_notes_path") or ""))
    if created_notes_path.exists():
        try:
            timezone_rewrite_result = batch_rewrite_obsidian_note_timestamps(
                note_paths=_load_note_paths_from_created_notes_csv(created_notes_path),
                target_timezone=note_timezone,
                fill_missing=True,
            )
        except Exception as exc:
            validation_errors.append(f"笔记时区标准化失败: {exc}")

    a080_queue_rows: List[Dict[str, Any]] = []
    for _, row in review_read_pool.fillna("").iterrows():
        uid_literature = str(row.get("uid_literature") or "").strip()
        cite_key = str(row.get("cite_key") or "").strip()
        if not uid_literature and not cite_key:
            continue
        a080_queue_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "stage": "A080",
                "source_affair": "A065",
                "queue_status": "queued",
                "priority": row.get("score") or row.get("priority") or 68.0,
                "bucket": "review_preprocessed",
                "preferred_next_stage": "A080",
                "recommended_reason": "A065 参考文献处理与标准笔记骨架完成，进入非综述候选构建入口",
                "theme_relation": str(raw_cfg.get("research_topic") or raw_cfg.get("topic") or "A065_topic"),
                "source_round": "a065",
                "run_uid": prepared_assets.get("quality_summary", {}).get("run_uid") or "",
                "scope_key": "a065",
                "is_current": 1,
            }
        )
    if a080_queue_rows:
        upsert_reading_queue_rows(content_db, a080_queue_rows)

    gate_review = build_gate_review(
        node_uid="A065",
        node_name="综述参考文献预处理与笔记骨架",
        summary=(
            f"完成 A065：阅读池 {len(review_read_pool)} 条，"
            f"创建/更新笔记 {prepared_assets.get('created_note_count', 0)} 条，"
            f"映射参考文献 {prepared_assets.get('mapped_reference_count', 0)} 条。"
        ),
        checks=[
            {"name": "review_read_pool_count", "value": len(review_read_pool)},
            {"name": "batch_count", "value": int(review_reading_batches['batch_id'].nunique()) if not review_reading_batches.empty and 'batch_id' in review_reading_batches.columns else 0},
            {"name": "created_note_count", "value": int(prepared_assets.get("created_note_count", 0))},
            {"name": "mapped_reference_count", "value": int(prepared_assets.get("mapped_reference_count", 0))},
            {"name": "reference_scan_skipped_count", "value": int(prepared_assets.get("reference_scan_skipped_count", 0))},
            {"name": "a080_queue_count", "value": len(a080_queue_rows)},
        ],
        artifacts=[
            str(review_read_pool_path),
            str(review_reading_batches_path),
            str(prepared_assets.get("created_notes_path")),
            str(prepared_assets.get("mapping_path")),
            str(prepared_assets.get("reference_scan_status_path")),
            str(prepared_assets.get("reference_dump_path")),
            str(prepared_assets.get("quality_summary_path")),
        ],
        recommendation="pass" if len(review_read_pool) > 0 and not validation_errors else "retry_current",
        score=90.0 if len(review_read_pool) > 0 and not validation_errors else 65.0,
        issues=validation_errors,
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "db_input_key": db_input_key,
            "research_topic": raw_cfg.get("research_topic") or raw_cfg.get("topic"),
            "source_review_read_pool_path": str(review_read_pool_path),
            "source_review_reading_batches_path": str(review_reading_batches_path),
            "reference_quality_summary": prepared_assets.get("quality_summary") or {},
            "a080_queue_count": len(a080_queue_rows),
            "note_timezone": note_timezone,
            "note_timezone_rewrite": timezone_rewrite_result,
        },
    )

    gate_path = output_dir / "gate_review.json"
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    append_aok_log_event(
        event_type="A065_REVIEW_REFERENCE_PREPROCESSING_COMPLETED",
        project_root=workspace_root,
        enabled=logging_enabled,
        affair_code="A065",
        handler_name="综述参考文献预处理与笔记骨架",
        agent_names=["ar_A065_综述参考文献预处理与笔记骨架事务智能体_v5"],
        skill_names=["ar_A065_综述参考文献预处理与笔记骨架_v5", "m_ObsidianMarkdown_v1"],
        reasoning_summary="承接 A060 解析资产，完成参考文献处理与笔记骨架生成并推进到 A080。",
        gate_review=gate_review,
        gate_review_path=gate_path,
        artifact_paths=[
            prepared_assets["created_notes_path"],
            prepared_assets["mapping_path"],
            prepared_assets["reference_scan_status_path"],
            prepared_assets["reference_dump_path"],
            prepared_assets["quality_summary_path"],
            gate_path,
        ],
        payload={
            "review_read_pool_count": len(review_read_pool),
            "batch_count": int(review_reading_batches['batch_id'].nunique()) if not review_reading_batches.empty and 'batch_id' in review_reading_batches.columns else 0,
            "created_note_count": int(prepared_assets.get("created_note_count", 0)),
            "mapped_reference_count": int(prepared_assets.get("mapped_reference_count", 0)),
            "reference_quality_summary": prepared_assets.get("quality_summary") or {},
            "a080_queue_count": len(a080_queue_rows),
            "note_timezone": note_timezone,
            "note_timezone_rewrite": timezone_rewrite_result,
        },
    )

    mirror_artifacts_to_legacy([gate_path], legacy_output_dir, output_dir)
    return [
        prepared_assets["created_notes_path"],
        prepared_assets["mapping_path"],
        prepared_assets["reference_scan_status_path"],
        prepared_assets["reference_dump_path"],
        prepared_assets["quality_summary_path"],
        gate_path,
    ]
