"""实证四件套事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from autodokit.tools import load_json_or_py


class EmpiricalFourPackEngine:
    """实证四件套封装引擎。"""

    def run(
        self,
        baseline_summary: str,
        mechanism_points: list[str],
        robustness_checks: list[str],
        heterogeneity_groups: list[str],
    ) -> dict[str, Any]:
        """执行四件套封装。"""

        if not baseline_summary.strip():
            raise ValueError("baseline_summary 不能为空")

        return {
            "baseline": {"summary": baseline_summary, "status": "completed"},
            "mechanism": {"points": [p for p in mechanism_points if p.strip()], "status": "completed"},
            "robustness": {"checks": [c for c in robustness_checks if c.strip()], "status": "completed"},
            "heterogeneity": {"groups": [g for g in heterogeneity_groups if g.strip()], "status": "completed"},
        }


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    cfg = load_json_or_py(config_path)
    result = EmpiricalFourPackEngine().run(
        baseline_summary=str(cfg.get("baseline_summary") or ""),
        mechanism_points=list(cfg.get("mechanism_points") or []),
        robustness_checks=list(cfg.get("robustness_checks") or []),
        heterogeneity_groups=list(cfg.get("heterogeneity_groups") or []),
    )
    output_dir = Path(str(cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError("output_dir 必须为绝对路径")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "empirical_four_pack_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
