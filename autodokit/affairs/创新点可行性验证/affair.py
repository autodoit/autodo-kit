"""创新点可行性验证事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import build_gate_review, innovation_feasibility_score, load_json_or_py
from autodokit.tools.atomic.task_aok.task_instance_dir import create_task_instance_dir, mirror_artifacts_to_legacy, resolve_legacy_output_dir
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


def _load_items(raw_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """加载待评分创新点。"""

    if raw_cfg.get("innovations"):
        return list(raw_cfg.get("innovations") or [])
    pool_csv = Path(str(raw_cfg.get("innovation_pool_csv") or ""))
    if pool_csv.exists():
        return pd.read_csv(pool_csv, dtype=str, keep_default_na=False).to_dict(orient="records")
    return []


@affair_auto_git_commit("A150")
def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    workspace_root = Path(str(raw_cfg.get("workspace_root") or config_path.parents[2]))
    if not workspace_root.is_absolute():
        raise ValueError(f"workspace_root 必须为绝对路径: {workspace_root}")
    legacy_output_dir = resolve_legacy_output_dir(raw_cfg, config_path)
    output_dir = create_task_instance_dir(workspace_root, "A150")

    items = _load_items(raw_cfg)
    scored_rows = [innovation_feasibility_score(item) for item in items]
    scored_table = pd.DataFrame(scored_rows)
    scored_path = output_dir / "innovation_feasibility_scores.csv"
    scored_table.to_csv(scored_path, index=False, encoding="utf-8-sig")

    promotable_count = 0 if scored_table.empty else int((scored_table["recommendation"] == "promote").sum())
    gate_review = build_gate_review(
        node_uid="A13",
        node_name="创新点可行性验证",
        summary=f"完成 {len(scored_table)} 条创新点评分，其中建议提升 {promotable_count} 条。",
        checks=[
            {"name": "innovation_count", "value": len(scored_table)},
            {"name": "promotable_count", "value": promotable_count},
        ],
        artifacts=[str(scored_path)],
        recommendation="pass" if promotable_count > 0 else ("revise" if len(scored_table) > 0 else "fallback"),
        score=90.0 if promotable_count > 0 else (70.0 if len(scored_table) > 0 else 20.0),
    )
    gate_path = output_dir / "gate_review.json"
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
    mirror_artifacts_to_legacy([scored_path, gate_path], legacy_output_dir, output_dir)
    return [scored_path, gate_path]