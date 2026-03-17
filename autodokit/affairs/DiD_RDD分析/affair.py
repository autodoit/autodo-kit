"""DiD/RDD 分析事务。"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any, List

from autodokit.tools import load_json_or_py


def _safe_mean(values: list[float]) -> float:
    """计算均值并处理空列表。"""

    return mean(values) if values else 0.0


class DidRddPipelineEngine:
    """最小化 DiD/RDD 分析引擎。"""

    def run(
        self,
        panel_rows: list[dict[str, Any]],
        outcome_field: str = "outcome",
        treated_field: str = "treated",
        post_field: str = "post",
        running_field: str = "running_var",
        cutoff: float = 0.0,
    ) -> dict[str, Any]:
        """执行最小化 DiD/RDD 分析。"""

        if not panel_rows:
            raise ValueError("panel_rows 不能为空")

        treated_post = [
            float(row.get(outcome_field, 0.0))
            for row in panel_rows
            if int(row.get(treated_field, 0)) == 1 and int(row.get(post_field, 0)) == 1
        ]
        treated_pre = [
            float(row.get(outcome_field, 0.0))
            for row in panel_rows
            if int(row.get(treated_field, 0)) == 1 and int(row.get(post_field, 0)) == 0
        ]
        control_post = [
            float(row.get(outcome_field, 0.0))
            for row in panel_rows
            if int(row.get(treated_field, 0)) == 0 and int(row.get(post_field, 0)) == 1
        ]
        control_pre = [
            float(row.get(outcome_field, 0.0))
            for row in panel_rows
            if int(row.get(treated_field, 0)) == 0 and int(row.get(post_field, 0)) == 0
        ]

        did_estimate = (_safe_mean(treated_post) - _safe_mean(treated_pre)) - (
            _safe_mean(control_post) - _safe_mean(control_pre)
        )

        left_band = [
            float(row.get(outcome_field, 0.0))
            for row in panel_rows
            if float(row.get(running_field, 0.0)) < cutoff
        ]
        right_band = [
            float(row.get(outcome_field, 0.0))
            for row in panel_rows
            if float(row.get(running_field, 0.0)) >= cutoff
        ]
        rdd_jump = _safe_mean(right_band) - _safe_mean(left_band)

        return {
            "sample_size": len(panel_rows),
            "did": {
                "estimate": did_estimate,
                "treated_post_mean": _safe_mean(treated_post),
                "treated_pre_mean": _safe_mean(treated_pre),
                "control_post_mean": _safe_mean(control_post),
                "control_pre_mean": _safe_mean(control_pre),
            },
            "rdd": {
                "cutoff": cutoff,
                "jump": rdd_jump,
                "left_mean": _safe_mean(left_band),
                "right_mean": _safe_mean(right_band),
            },
        }


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    cfg = load_json_or_py(config_path)
    result = DidRddPipelineEngine().run(
        panel_rows=list(cfg.get("panel_rows") or []),
        outcome_field=str(cfg.get("outcome_field") or "outcome"),
        treated_field=str(cfg.get("treated_field") or "treated"),
        post_field=str(cfg.get("post_field") or "post"),
        running_field=str(cfg.get("running_field") or "running_var"),
        cutoff=float(cfg.get("cutoff") or 0.0),
    )

    output_dir = Path(str(cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError("output_dir 必须为绝对路径")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "did_rdd_pipeline_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
