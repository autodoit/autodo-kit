"""文献阅读规划事务。

根据预筛选候选生成阅读队列、矩阵字段和精读提示模板，
并保持与 ARK 兼容的 `LiteratureReadingEngine` / `LiteratureReadingPlan`。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List

from autodokit.tools import load_json_or_py


@dataclass(slots=True, frozen=True)
class LiteratureReadingQueueItem:
    """阅读队列条目。

    Args:
        uid_literature: 文献 UID。
        title: 文献标题。
        priority: 阅读优先级。
        reading_goal: 阅读目标。
        extraction_targets: 抽取目标字段。
    """

    uid_literature: str
    title: str
    priority: str
    reading_goal: str
    extraction_targets: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class LiteratureReadingPlan:
    """文献阅读计划。

    Args:
        focus: 阅读主题。
        queue: 阅读队列。
        matrix_columns: 文献矩阵字段。
        deep_read_template: 单篇精读模板。
        next_node: 推荐后续节点。
    """

    focus: str
    queue: tuple[LiteratureReadingQueueItem, ...]
    matrix_columns: tuple[str, ...]
    deep_read_template: tuple[str, ...]
    next_node: str

    def to_dict(self) -> dict[str, Any]:
        """导出为可序列化字典。

        Returns:
            可序列化结果。
        """

        return {
            "focus": self.focus,
            "queue": [asdict(item) for item in self.queue],
            "matrix_columns": list(self.matrix_columns),
            "deep_read_template": list(self.deep_read_template),
            "next_node": self.next_node,
        }


class LiteratureReadingEngine:
    """文献阅读与知识抽取引擎。"""

    def run(
        self,
        focus: str,
        candidates: list[dict[str, Any]],
        max_items: int = 12,
    ) -> LiteratureReadingPlan:
        """构建文献阅读计划。

        Args:
            focus: 阅读主题。
            candidates: 预筛选后的候选条目。
            max_items: 最大阅读条目数。

        Returns:
            阅读计划。
        """

        queue: list[LiteratureReadingQueueItem] = []
        for index, candidate in enumerate(candidates[:max_items], start=1):
            score = float(candidate.get("score") or 0.0)
            priority = self._score_to_priority(score=score, order=index)
            queue.append(
                LiteratureReadingQueueItem(
                    uid_literature=str(candidate.get("uid_literature") or candidate.get("item_uid") or ""),
                    title=str(candidate.get("title") or ""),
                    priority=priority,
                    reading_goal=f"围绕主题“{focus}”抽取变量、方法、识别前提和可复用结论",
                    extraction_targets=(
                        "研究问题",
                        "研究对象",
                        "数据来源",
                        "被解释变量",
                        "核心解释变量",
                        "识别策略",
                        "关键结论",
                        "可复用证据",
                    ),
                )
            )

        return LiteratureReadingPlan(
            focus=focus,
            queue=tuple(queue),
            matrix_columns=(
                "uid_literature",
                "title",
                "research_question",
                "sample",
                "data_source",
                "dependent_variable",
                "independent_variable",
                "identification_strategy",
                "findings",
                "evidence_path",
            ),
            deep_read_template=(
                "这篇文献解决了什么问题？",
                "作者使用了什么数据与样本？",
                "核心变量如何定义？",
                "识别策略依赖哪些前提？",
                "结论能否迁移到当前研究？",
                "哪一部分最值得进入知识库？",
            ),
            next_node="rag_evidence_synthesis",
        )

    def _score_to_priority(self, score: float, order: int) -> str:
        """将筛选得分映射为阅读优先级。

        Args:
            score: 预筛选得分。
            order: 排序位置。

        Returns:
            阅读优先级。
        """

        if score >= 3 or order <= 3:
            return "high"
        if score >= 1.5 or order <= 8:
            return "medium"
        return "low"


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置路径。

    Returns:
        输出文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    result = LiteratureReadingEngine().run(
        focus=str(raw_cfg.get("focus") or ""),
        candidates=list(raw_cfg.get("candidates") or []),
        max_items=int(raw_cfg.get("max_items") or 12),
    )

    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={str(raw_cfg.get('output_dir') or '')!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / "literature_reading_plan.json"
    out_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
