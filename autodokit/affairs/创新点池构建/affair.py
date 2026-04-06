"""创新点池构建事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import build_gate_review, innovation_pool_upsert, init_empty_innovation_pool_table, load_json_or_py
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


NOVELTY_METHODS = {
    "类比法": "把相邻领域成熟方法迁移到当前主题",
    "假设条件修改法": "改变现有模型关键前提并形成新命题",
    "组合法": "把不同机制或方法拼接为新分析框架",
    "特殊到一般法": "从典型案例提升为一般性研究命题",
    "问题导向法": "围绕现有理论无法解释的问题提出新方案",
}


def _generate_innovation_items(raw_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """根据 gap 与主题生成候选创新点。"""

    topic = str(raw_cfg.get("topic") or "未命名主题")
    gaps = list(raw_cfg.get("gaps") or ["现有研究缺少具体可落地的机制识别"])
    scenario = str(raw_cfg.get("scenario") or topic)
    data_source = str(raw_cfg.get("data_source") or "待补充具体数据来源")
    method_family = str(raw_cfg.get("method_family") or "待补充具体模型")
    output_form = str(raw_cfg.get("output_form") or "待补充具体量化产出")
    items: List[Dict[str, Any]] = []
    for gap in gaps:
        for novelty_type, description in NOVELTY_METHODS.items():
            items.append(
                {
                    "title": f"{topic}-{novelty_type}-{gap[:20]}",
                    "source_gap": gap,
                    "method_family": method_family,
                    "scenario": scenario,
                    "data_source": data_source,
                    "output_form": output_form,
                    "novelty_type": novelty_type,
                    "evidence_refs": description,
                }
            )
    return items


@affair_auto_git_commit("A140")
def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(f"output_dir 必须为绝对路径: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    pool_table = init_empty_innovation_pool_table()
    generated_items = _generate_innovation_items(raw_cfg)
    for item in generated_items:
        pool_table, _, _ = innovation_pool_upsert(pool_table, item)

    pool_path = output_dir / "innovation_pool.csv"
    pool_table.to_csv(pool_path, index=False, encoding="utf-8-sig")

    gate_review = build_gate_review(
        node_uid="A12",
        node_name="创新点池构建",
        summary=f"生成 {len(pool_table)} 条候选创新点。",
        checks=[{"name": "innovation_count", "value": len(pool_table)}],
        artifacts=[str(pool_path)],
        recommendation="pass" if len(pool_table) > 0 else "revise",
        score=92.0 if len(pool_table) > 0 else 30.0,
    )
    gate_path = output_dir / "gate_review.json"
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
    return [pool_path, gate_path]