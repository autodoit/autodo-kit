"""A095 普通文献研读候选视图构建事务。

A095 消费正式 `A095` 阶段队列，执行普通文献粗读、轻量分析与批次汇总，
并把可进入深读的条目正式推进到 A100。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.affairs.非综述候选视图构建 import affair as a080_rough_affair
from autodokit.tools import append_aok_log_event, build_gate_review, load_json_or_py
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.atomic.task_aok.task_instance_dir import (
    create_task_instance_dir,
    mirror_artifacts_to_legacy,
    resolve_legacy_output_dir,
)
from autodokit.tools.bibliodb_sqlite import load_reading_queue_df, load_reading_state_df
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.storage_backend import load_reference_tables


def _build_a095_ready_df(queue_df: pd.DataFrame, state_df: pd.DataFrame) -> pd.DataFrame:
    if queue_df.empty:
        return pd.DataFrame()
    queue_df = queue_df.fillna("").copy()
    queue_df["uid_literature"] = queue_df.get("uid_literature", pd.Series(dtype=str)).astype(str)
    state_df = state_df.fillna("").copy()
    state_df["uid_literature"] = state_df.get("uid_literature", pd.Series(dtype=str)).astype(str)
    merge_columns = [
        column
        for column in ["uid_literature", "reading_objective", "manual_guidance", "theme_relation", "source_origin", "priority"]
        if column in state_df.columns
    ]
    if "uid_literature" not in merge_columns:
        return queue_df
    merged = queue_df.merge(
        state_df[merge_columns].drop_duplicates(subset=["uid_literature"]),
        on="uid_literature",
        how="left",
        suffixes=("", "_state"),
    )
    return merged.fillna("")


@affair_auto_git_commit("A095")
def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    if not isinstance(raw_cfg, dict):
        raise ValueError("A095 配置必须是字典")

    workspace_root = a080_rough_affair._resolve_workspace_root(config_path, raw_cfg)
    legacy_output_dir = resolve_legacy_output_dir(
        raw_cfg,
        config_path,
        default_path=workspace_root / "tasks" / "A095_reading_candidate_build",
    )
    output_dir = create_task_instance_dir(workspace_root, "A095")

    content_db, _ = resolve_content_db_config(
        raw_cfg,
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None

    max_items = int(raw_cfg.get("max_items") or raw_cfg.get("batch_size") or 0)
    literatures_df, attachments_df, _ = load_reference_tables(db_path=content_db)
    state_df = load_reading_state_df(content_db)
    queue_df = load_reading_queue_df(
        content_db,
        stage="A095",
        only_current=True,
        queue_statuses=["queued", "candidate", "in_progress"],
    )
    ready_df = _build_a095_ready_df(queue_df, state_df)
    if max_items > 0 and not ready_df.empty:
        ready_df = ready_df.head(max_items).reset_index(drop=True)

    merged_artifact_paths: List[Path] = []
    merged_summary: Dict[str, Any] = {"rough_read_count": 0, "a100_queue_count": 0, "rough_read_failures": []}
    if not ready_df.empty:
        merged_artifact_paths, merged_summary = a080_rough_affair._run_rough_read_and_batch_summary(
            raw_cfg=raw_cfg,
            workspace_root=workspace_root,
            output_dir=output_dir,
            content_db=content_db,
            literature_table=literatures_df,
            attachment_table=attachments_df,
            ready_df=ready_df,
            source_stage="A095",
            output_prefix="a095",
        )

    consumed_a095_queue_count = a080_rough_affair._consume_current_stage_queue_rows(content_db, stage="A095", ready_df=ready_df)

    gate_review = build_gate_review(
        node_uid="A095",
        node_name="普通文献研读候选视图构建",
        summary=(
            f"消费 A095 输入池 {len(ready_df)} 条；"
            f"粗读完成 {merged_summary.get('rough_read_count', 0)} 条；"
            f"写入 A100 队列 {merged_summary.get('a100_queue_count', 0)} 条；"
            f"消费 A095 兼容队列 {consumed_a095_queue_count} 条。"
        ),
        checks=[
            {"name": "a095_input_count", "value": len(ready_df)},
            {"name": "rough_read_count", "value": merged_summary.get("rough_read_count", 0)},
            {"name": "a100_queue_count", "value": merged_summary.get("a100_queue_count", 0)},
            {"name": "consumed_a095_queue_count", "value": consumed_a095_queue_count},
        ],
        artifacts=[*[str(path) for path in merged_artifact_paths]],
        recommendation="pass_next" if merged_summary.get("a100_queue_count", 0) > 0 else "retry_current",
        score=max(50.0, 94.0 - len(list(merged_summary.get("rough_read_failures") or [])) * 4.0),
        issues=list(merged_summary.get("rough_read_failures") or []),
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "upstream_stage": "A080",
            "downstream_stage": "A100",
            "rough_read_count": merged_summary.get("rough_read_count", 0),
            "a100_queue_count": merged_summary.get("a100_queue_count", 0),
        },
    )
    gate_path = output_dir / "gate_review.json"
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    artifact_paths = [gate_path, *merged_artifact_paths]
    mirror_artifacts_to_legacy(artifact_paths, legacy_output_dir, output_dir)

    try:
        append_aok_log_event(
            event_type="A095_READING_CANDIDATE_READY",
            project_root=workspace_root,
            affair_code="A095",
            handler_name="普通文献研读候选视图构建",
            agent_names=["ar_A095_普通文献研读候选视图构建事务智能体_v7"],
            skill_names=[],
            reasoning_summary="消费 A095 阶段队列，完成普通文献粗读与批次汇总，并把可深读条目推进到 A100。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=artifact_paths,
            payload={
                "input_count": len(ready_df),
                "rough_read_count": merged_summary.get("rough_read_count", 0),
                "a100_queue_count": merged_summary.get("a100_queue_count", 0),
                "consumed_a095_queue_count": consumed_a095_queue_count,
            },
        )
    except Exception:
        pass

    return artifact_paths