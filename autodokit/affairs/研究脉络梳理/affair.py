"""研究脉络梳理事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import build_gate_review, build_research_trajectory, load_json_or_py
from autodokit.tools.atomic.task_aok.task_instance_dir import create_task_instance_dir, mirror_artifacts_to_legacy, resolve_legacy_output_dir
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


def _load_items(raw_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """加载输入条目。"""

    if raw_cfg.get("items"):
        return list(raw_cfg.get("items") or [])
    input_csv = Path(str(raw_cfg.get("input_csv") or ""))
    if input_csv.exists():
        return pd.read_csv(input_csv, dtype=str, keep_default_na=False).to_dict(orient="records")
    return []


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
    trajectory = build_research_trajectory(items, topic=str(raw_cfg.get("topic") or "未命名主题"))
    trajectory_path = output_dir / "research_trajectory.json"
    trajectory_path.write_text(json.dumps(trajectory, ensure_ascii=False, indent=2), encoding="utf-8")

    gate_review = build_gate_review(
        node_uid="A10",
        node_name="研究脉络梳理",
        summary=f"生成研究脉络时间线，覆盖 {trajectory.get('item_count', 0)} 条记录。",
        checks=[{"name": "item_count", "value": trajectory.get("item_count", 0)}],
        artifacts=[str(trajectory_path)],
        recommendation="pass" if trajectory.get("item_count", 0) > 0 else "revise",
        score=86.0 if trajectory.get("item_count", 0) > 0 else 35.0,
    )
    gate_path = output_dir / "gate_review.json"
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
    mirror_artifacts_to_legacy([trajectory_path, gate_path], legacy_output_dir, output_dir)
    return [trajectory_path, gate_path]