"""变量操作化事务。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List

from autodokit.tools import load_json_or_py

_PROXY_MAP: dict[str, list[str]] = {
    "系统性风险": ["srisk", "mes", "covar"],
    "流动性": ["bid_ask_spread", "amihud_illiquidity", "turnover"],
    "创新": ["patent_count", "rd_intensity", "new_product_ratio"],
}


def _slugify(text: str) -> str:
    """将中文/英文概念转换为变量名。"""

    english_only = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return english_only or "concept"


class VariableOperationalizationEngine:
    """变量操作化引擎。"""

    def run(self, concepts: list[str]) -> dict[str, Any]:
        """执行变量操作化。"""

        cleaned = [item.strip() for item in concepts if item.strip()]
        if not cleaned:
            raise ValueError("concepts 不能为空")

        items: list[dict[str, Any]] = []
        for concept in cleaned:
            proxies = ["custom_metric_1", "custom_metric_2"]
            for key, value in _PROXY_MAP.items():
                if key in concept:
                    proxies = value
                    break
            items.append(
                {
                    "concept": concept,
                    "variable_name": _slugify(concept),
                    "recommended_proxies": proxies,
                    "measurement_note": "建议在论文中补充口径定义、时间窗口与数据来源。",
                }
            )

        return {"count": len(items), "items": items}


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    cfg = load_json_or_py(config_path)
    result = VariableOperationalizationEngine().run(concepts=list(cfg.get("concepts") or []))
    output_dir = Path(str(cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError("output_dir 必须为绝对路径")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "variable_operationalization_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
