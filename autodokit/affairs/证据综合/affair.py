"""证据综合事务。

对候选证据文本进行最小化 RAG 综合，输出证据矩阵与综合摘要。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List

from autodokit.tools import load_json_or_py


@dataclass(slots=True, frozen=True)
class EvidenceMatrixEntry:
    """证据矩阵条目。

    Args:
        evidence_id: 证据序号。
        title: 证据标题。
        claim: 核心论断。
        relevance: 相关性标签。
    """

    evidence_id: int
    title: str
    claim: str
    relevance: str


@dataclass(slots=True, frozen=True)
class RagEvidenceSynthesisResult:
    """证据综合结果。

    Args:
        question: 研究问题。
        evidence_count: 证据数量。
        evidence_matrix: 证据矩阵。
        synthesis: 综合结论摘要。
    """

    question: str
    evidence_count: int
    evidence_matrix: tuple[EvidenceMatrixEntry, ...]
    synthesis: str

    def to_dict(self) -> dict[str, Any]:
        """导出为可序列化字典。

        Returns:
            可序列化结果。
        """

        return {
            "question": self.question,
            "evidence_count": self.evidence_count,
            "evidence_matrix": [asdict(item) for item in self.evidence_matrix],
            "synthesis": self.synthesis,
        }


class RagEvidenceSynthesisEngine:
    """RAG 证据综合引擎。"""

    def run(
        self,
        question: str,
        passages: list[dict[str, str]],
        top_k: int = 3,
    ) -> RagEvidenceSynthesisResult:
        """执行证据综合。

        Args:
            question: 研究问题。
            passages: 候选证据文本列表。
            top_k: 输出证据条目上限。

        Returns:
            证据综合结果。

        Raises:
            ValueError: 问题为空或 `top_k` 非正时抛出。
        """

        if not question.strip():
            raise ValueError("question 不能为空")
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")

        normalized: list[dict[str, str]] = []
        for item in passages:
            title = item.get("title", "").strip()
            content = item.get("content", "").strip()
            if not title and not content:
                continue
            normalized.append({"title": title or "未命名证据", "content": content})

        selected = normalized[:top_k]
        evidence_matrix = tuple(
            EvidenceMatrixEntry(
                evidence_id=index + 1,
                title=item["title"],
                claim=item["content"][:180],
                relevance="high" if index == 0 else "medium",
            )
            for index, item in enumerate(selected)
        )
        synthesis = "；".join(entry.claim for entry in evidence_matrix if entry.claim) or "暂无可用证据"

        return RagEvidenceSynthesisResult(
            question=question,
            evidence_count=len(evidence_matrix),
            evidence_matrix=evidence_matrix,
            synthesis=synthesis,
        )


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置路径。

    Returns:
        输出文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    result = RagEvidenceSynthesisEngine().run(
        question=str(raw_cfg.get("question") or ""),
        passages=list(raw_cfg.get("passages") or []),
        top_k=int(raw_cfg.get("top_k") or 3),
    )

    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={str(raw_cfg.get('output_dir') or '')!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / "rag_evidence_synthesis_result.json"
    out_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
