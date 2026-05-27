"""A095 泛读批次分析汇总事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import append_aok_log_event, build_gate_review, load_json_or_py
from autodokit.tools.atomic.task_aok.task_instance_dir import create_task_instance_dir, mirror_artifacts_to_legacy, resolve_legacy_output_dir
from autodokit.tools.bibliodb_sqlite import load_reading_queue_df, load_reading_state_df, upsert_reading_queue_rows, upsert_reading_state_rows
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.reading_state_tools import ANALYSIS_NOTE_SPECS, append_markdown_section, resolve_analysis_note_paths
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


OUTPUT_SUMMARY = "a095_batch_summary.md"
OUTPUT_GATE = "gate_review.json"
OUTPUT_RELATED_ITEMS_CSV = "related_literature_items.csv"
OUTPUT_RELATED_ITEMS_MD = "related_literature_items.md"


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


def _build_a100_queue_rows(state_df: pd.DataFrame) -> List[Dict[str, Any]]:
    queue_rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for _, row in state_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        identity = (uid_literature, cite_key)
        if identity in seen or not uid_literature:
            continue
        if int(row.get("deep_read_done") or 0) == 1:
            continue
        seen.add(identity)
        queue_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "stage": "A100",
                "source_affair": "A095",
                "queue_status": "queued",
                "priority": row.get("priority") or 80,
                "bucket": "non_review_batch_summary",
                "preferred_next_stage": "A105",
                "recommended_reason": _stringify(row.get("rough_read_reason")) or "A095 批次汇总完成，进入 A100 深度解析准备",
                "theme_relation": _stringify(row.get("theme_relation")) or "a095_to_a100",
                "source_round": "a095",
                "scope_key": "a095_to_a100",
                "is_current": 1,
            }
        )
    return queue_rows


def _write_related_literature_items(output_dir: Path, frame: pd.DataFrame) -> list[Path]:
    snapshot_columns = [
        "uid_literature",
        "cite_key",
        "title",
        "rough_read_reason",
        "theme_relation",
        "analysis_batch_synced",
        "last_batch_id",
    ]
    available_columns = [column for column in snapshot_columns if column in frame.columns]
    snapshot_df = frame[available_columns].copy() if available_columns else pd.DataFrame()

    csv_path = output_dir / OUTPUT_RELATED_ITEMS_CSV
    md_path = output_dir / OUTPUT_RELATED_ITEMS_MD
    snapshot_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    label_map = {
        "uid_literature": "文献 UID",
        "cite_key": "题录键",
        "title": "标题",
        "rough_read_reason": "粗读结论",
        "theme_relation": "主题关系",
        "analysis_batch_synced": "批次分析已同步",
        "last_batch_id": "最近批次 ID",
    }
    lines = ["# A095 相关文献条目", "", f"共 {len(snapshot_df)} 条。", ""]
    if snapshot_df.empty:
        lines.append("当前任务没有产出可记录的相关文献条目。")
    else:
        for index, row in snapshot_df.fillna("").iterrows():
            title = _stringify(row.get("title")) or _stringify(row.get("cite_key")) or _stringify(row.get("uid_literature")) or f"条目 {index + 1}"
            lines.append(f"## {index + 1}. {title}")
            for column in available_columns:
                value = _stringify(row.get(column))
                if not value:
                    continue
                lines.append(f"- {label_map.get(column, column)}：{value}")
            lines.append("")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return [csv_path, md_path]


@affair_auto_git_commit("A095")
def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    legacy_output_dir = resolve_legacy_output_dir(raw_cfg, config_path)
    output_dir = create_task_instance_dir(workspace_root, "A095")
    content_db, _ = resolve_content_db_config(
        raw_cfg,
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None

    batch_size = int(raw_cfg.get("batch_size") or 10)
    analysis_note_paths = resolve_analysis_note_paths(workspace_root, raw_cfg)
    state_df = load_reading_state_df(content_db, flag_filters={"rough_read_done": 1, "analysis_batch_synced": 0})
    if batch_size > 0:
        state_df = state_df.head(batch_size).reset_index(drop=True)

    summary_lines: List[str] = ["# A095 泛读批次分析汇总", ""]
    state_updates: List[Dict[str, Any]] = []
    for _, row in state_df.fillna("").iterrows():
        cite_key = _stringify(row.get("cite_key")) or _stringify(row.get("uid_literature"))
        title = _stringify(row.get("title")) or cite_key
        reason = _stringify(row.get("rough_read_reason")) or "已完成 A090 泛读"
        summary_lines.append(f"- {cite_key}《{title}》：{reason}")
        for key, spec in ANALYSIS_NOTE_SPECS.items():
            append_markdown_section(
                analysis_note_paths[key],
                spec["title"],
                [f"- A095 批次汇总：{cite_key}《{title}》已进入批次综合观察。"],
            )
        state_updates.append(
            {
                "uid_literature": _stringify(row.get("uid_literature")),
                "cite_key": cite_key,
                "analysis_batch_synced": 1,
                "last_batch_id": _stringify(raw_cfg.get("batch_id")) or output_dir.name,
            }
        )

    summary_path = output_dir / OUTPUT_SUMMARY
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    related_item_paths = _write_related_literature_items(output_dir, state_df)
    a100_queue_rows = _build_a100_queue_rows(state_df)
    if state_updates:
        upsert_reading_state_rows(content_db, state_updates)
    if a100_queue_rows:
        upsert_reading_queue_rows(content_db, a100_queue_rows)

    current_a100_queue_df = load_reading_queue_df(content_db, stage="A100", only_current=True)
    current_batch_uids = {
        _stringify(row.get("uid_literature"))
        for _, row in state_df.fillna("").iterrows()
        if _stringify(row.get("uid_literature"))
    }
    queued_a100_count = 0
    if not current_a100_queue_df.empty and current_batch_uids:
        queued_a100_count = int(
            current_a100_queue_df.get("uid_literature", pd.Series(dtype=str)).astype(str).isin(current_batch_uids).sum()
        )

    gate_review = build_gate_review(
        node_uid="A095",
        node_name="泛读批次分析汇总",
        summary=f"完成批次汇总 {len(state_updates)} 篇，写入/确认 A100 队列 {queued_a100_count} 条。",
        checks=[
            {"name": "batch_item_count", "value": len(state_updates)},
            {"name": "a100_queue_count", "value": queued_a100_count},
        ],
        artifacts=[str(summary_path), *[str(path) for path in related_item_paths]],
        recommendation="pass" if state_updates else "pause_current",
        score=90.0 if state_updates else 55.0,
        issues=[] if state_updates else ["当前没有待汇总的 A090 完成条目。"],
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "a100_queue_count": queued_a100_count,
        },
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        append_aok_log_event(
            event_type="A095_BATCH_SUMMARY_COMPLETED",
            project_root=workspace_root,
            affair_code="A095",
            handler_name="泛读批次分析汇总",
            agent_names=["ar_A095_泛读批次分析汇总事务智能体_v1"],
            skill_names=[],
            reasoning_summary="对 rough_read_done=1 且 analysis_batch_synced=0 的文献做批次汇总补写，并正式写入 A100 阶段队列。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=[summary_path, gate_path],
            payload={"batch_item_count": len(state_updates), "a100_queue_count": queued_a100_count},
        )
    except Exception:
        pass

    mirror_artifacts_to_legacy([summary_path, *related_item_paths, gate_path], legacy_output_dir, output_dir)
    return [summary_path, *related_item_paths, gate_path]
