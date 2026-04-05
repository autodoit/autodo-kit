"""结果分析解读事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def analyze_results(statistical_summary: str, mechanism_points: list[str], significance_notes: list[str]) -> dict[str, Any]:
    """把统计结果转成可写作结论。"""

    narrative = statistical_summary.strip() or "结果摘要待补充。"
    if mechanism_points:
        narrative += " 可能机制包括：" + "、".join(mechanism_points) + "。"
    if significance_notes:
        narrative += " 显著性说明：" + "；".join(significance_notes) + "。"
    return {
        "status": "PASS",
        "mode": "results-analysis",
        "result": {
            "narrative": narrative,
            "figure_specs": ["主结果图", "机制分析图", "稳健性对比图"],
            "table_specs": ["基准回归表", "机制分析表", "异质性分析表"],
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = analyze_results(
        statistical_summary=str(raw_cfg.get("statistical_summary") or ""),
        mechanism_points=list(raw_cfg.get("mechanism_points") or []),
        significance_notes=list(raw_cfg.get("significance_notes") or []),
    )
    return write_affair_json_result(raw_cfg, config_path, "results_analysis_result.json", result)
