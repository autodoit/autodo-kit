"""研究脉络梳理事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import build_gate_review, build_research_trajectory, load_json_or_py
from autodokit.tools.atomic.task_aok.task_instance_dir import create_task_instance_dir, mirror_artifacts_to_legacy, resolve_legacy_output_dir
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


OUTPUT_RELATED_ITEMS_CSV = "related_literature_items.csv"
OUTPUT_RELATED_ITEMS_MD = "related_literature_items.md"


def _load_items(raw_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """加载输入条目。"""

    if raw_cfg.get("items"):
        return list(raw_cfg.get("items") or [])
    input_csv = Path(str(raw_cfg.get("input_csv") or ""))
    if input_csv.exists():
        return pd.read_csv(input_csv, dtype=str, keep_default_na=False).to_dict(orient="records")
    return []


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _write_related_literature_items(output_dir: Path, items: List[Dict[str, Any]]) -> list[Path]:
    frame = pd.DataFrame(items)
    snapshot_columns = ["uid", "title", "year", "research_question", "method", "data"]
    available_columns = [column for column in snapshot_columns if column in frame.columns]
    snapshot_df = frame[available_columns].copy() if available_columns else pd.DataFrame()

    csv_path = output_dir / OUTPUT_RELATED_ITEMS_CSV
    md_path = output_dir / OUTPUT_RELATED_ITEMS_MD
    snapshot_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    label_map = {
        "uid": "文献 UID",
        "title": "标题",
        "year": "年份",
        "research_question": "研究问题",
        "method": "方法",
        "data": "数据",
    }
    lines = ["# A120 相关文献条目", "", f"共 {len(snapshot_df)} 条。", ""]
    if snapshot_df.empty:
        lines.append("当前任务没有可记录的相关文献条目。")
    else:
        for index, row in snapshot_df.fillna("").iterrows():
            title = _stringify(row.get("title")) or _stringify(row.get("uid")) or f"条目 {index + 1}"
            lines.append(f"## {index + 1}. {title}")
            for column in available_columns:
                value = _stringify(row.get(column))
                if not value:
                    continue
                lines.append(f"- {label_map.get(column, column)}：{value}")
            lines.append("")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return [csv_path, md_path]


@affair_auto_git_commit("A120")
def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    workspace_root = Path(str(raw_cfg.get("workspace_root") or config_path.parents[2]))
    if not workspace_root.is_absolute():
        raise ValueError(f"workspace_root 必须为绝对路径: {workspace_root}")
    legacy_output_dir = resolve_legacy_output_dir(raw_cfg, config_path)
    output_dir = create_task_instance_dir(workspace_root, "A120")

    items = _load_items(raw_cfg)
    related_paths = _write_related_literature_items(output_dir, items)
    trajectory = build_research_trajectory(items, topic=str(raw_cfg.get("topic") or "未命名主题"))
    trajectory_path = output_dir / "research_trajectory.json"
    trajectory_path.write_text(json.dumps(trajectory, ensure_ascii=False, indent=2), encoding="utf-8")

    gate_review = build_gate_review(
        node_uid="A10",
        node_name="研究脉络梳理",
        summary=f"生成研究脉络时间线，覆盖 {trajectory.get('item_count', 0)} 条记录。",
        checks=[{"name": "item_count", "value": trajectory.get("item_count", 0)}],
        artifacts=[str(trajectory_path), *(str(path) for path in related_paths)],
        recommendation="pass" if trajectory.get("item_count", 0) > 0 else "revise",
        score=86.0 if trajectory.get("item_count", 0) > 0 else 35.0,
    )
    gate_path = output_dir / "gate_review.json"
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
    mirror_artifacts_to_legacy([trajectory_path, gate_path, *related_paths], legacy_output_dir, output_dir)
    return [trajectory_path, gate_path, *related_paths]