"""论文草稿事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from autodokit.tools import load_json_or_py


class PaperDraftEngine:
    """论文草稿引擎。"""

    def run(
        self,
        topic: str,
        contributions: list[str] | None = None,
        limitations: list[str] | None = None,
    ) -> dict[str, Any]:
        """生成论文草稿骨架文本。"""

        if not topic.strip():
            raise ValueError("topic 不能为空")

        final_contributions = contributions or ["提出可复现的研究流程", "构建可解释的实证策略"]
        final_limitations = limitations or ["样本期覆盖有限", "外部冲击识别仍依赖假设"]

        return {
            "topic": topic,
            "outline": {
                "introduction": f"本文围绕“{topic}”展开研究，聚焦研究动机、现实意义与文献缺口。",
                "method": "方法部分建议依次说明识别策略、变量定义、数据来源与稳健性检验。",
                "results": "结果部分建议区分主结果、机制分析与异质性分析，并明确经济含义。",
                "limitations": "；".join(final_limitations),
            },
            "contributions": final_contributions,
            "limitations": final_limitations,
        }


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    cfg = load_json_or_py(config_path)
    result = PaperDraftEngine().run(
        topic=str(cfg.get("topic") or ""),
        contributions=cfg.get("contributions"),
        limitations=cfg.get("limitations"),
    )
    output_dir = Path(str(cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError("output_dir 必须为绝对路径")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "paper_draft_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
