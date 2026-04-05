"""A095 泛读批次分析汇总事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import append_aok_log_event, build_gate_review, load_json_or_py
from autodokit.tools.bibliodb_sqlite import load_reading_state_df, upsert_reading_state_rows
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.reading_state_tools import ANALYSIS_NOTE_SPECS, append_markdown_section, resolve_analysis_note_paths


OUTPUT_SUMMARY = "a095_batch_summary.md"
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
    if state_updates:
        upsert_reading_state_rows(content_db, state_updates)

    gate_review = build_gate_review(
        node_uid="A095",
        node_name="泛读批次分析汇总",
        summary=f"完成批次汇总 {len(state_updates)} 篇。",
        checks=[{"name": "batch_item_count", "value": len(state_updates)}],
        artifacts=[str(summary_path)],
        recommendation="pass" if state_updates else "pause_current",
        score=90.0 if state_updates else 55.0,
        issues=[] if state_updates else ["当前没有待汇总的 A090 完成条目。"],
        metadata={"workspace_root": str(workspace_root), "content_db": str(content_db)},
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        append_aok_log_event(
            event_type="A095_BATCH_SUMMARY_COMPLETED",
            project_root=workspace_root,
            handler_name="泛读批次分析汇总",
            agent_names=["ar_A095_泛读批次分析汇总事务智能体_v1"],
            skill_names=[],
            reasoning_summary="对 rough_read_done=1 且 analysis_batch_synced=0 的文献做批次汇总补写。",
            payload={"batch_item_count": len(state_updates)},
        )
    except Exception:
        pass

    return [summary_path, gate_path]
