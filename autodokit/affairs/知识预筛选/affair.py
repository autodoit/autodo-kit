"""知识预筛选事务。

提供轻量可执行的主题词匹配预筛选能力，并保持与 ARK 兼容的
`KnowledgePrescreenEngine` / `KnowledgePrescreenResult` 结构。
"""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List

from autodokit.tools import load_json_or_py


def normalize_text(value: str) -> str:
    """规范化文本。

    Args:
        value: 原始文本。

    Returns:
        规范化后的文本。
    """

    return re.sub(r"\s+", " ", value).strip().lower()


@dataclass(slots=True, frozen=True)
class KnowledgePrescreenCandidate:
    """知识预筛选候选项。

    Args:
        item_uid: 文献 UID。
        title: 文献标题。
        score: 匹配得分。
        decision: 决策结果。
        reasons: 决策理由。
    """

    item_uid: str
    title: str
    score: float
    decision: str
    reasons: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class KnowledgePrescreenResult:
    """知识预筛选结果。

    Args:
        focus: 预筛选主题。
        candidates: 入选候选集合。
        excluded: 剔除集合。
        next_node: 推荐后续节点。
    """

    focus: str
    candidates: tuple[KnowledgePrescreenCandidate, ...]
    excluded: tuple[KnowledgePrescreenCandidate, ...]
    next_node: str

    def to_dict(self) -> dict[str, Any]:
        """导出为可序列化字典。

        Returns:
            可序列化结果。
        """

        return {
            "focus": self.focus,
            "candidates": [asdict(candidate) for candidate in self.candidates],
            "excluded": [asdict(candidate) for candidate in self.excluded],
            "next_node": self.next_node,
        }


class KnowledgePrescreenEngine:
    """知识预筛选引擎。"""

    def run(
        self,
        focus: str,
        items: list[dict[str, Any]] | None = None,
        literature_items_path: str | Path | None = None,
        include_terms: list[str] | None = None,
        exclude_terms: list[str] | None = None,
        min_score: float = 1.0,
    ) -> KnowledgePrescreenResult:
        """执行知识预筛选。

        Args:
            focus: 预筛选主题。
            items: 直接传入的文献记录。
            literature_items_path: 文献数据库路径。
            include_terms: 额外强制纳入关键词。
            exclude_terms: 剔除关键词。
            min_score: 最小入选得分。

        Returns:
            预筛选结果。
        """

        records = items or self._load_items_from_csv(literature_items_path)
        include_tokens = self._build_tokens(focus=focus, include_terms=include_terms)
        exclude_tokens = {normalize_text(term) for term in exclude_terms or [] if term.strip()}

        candidates: list[KnowledgePrescreenCandidate] = []
        excluded: list[KnowledgePrescreenCandidate] = []
        for record in records:
            text = " ".join(
                [
                    str(record.get("title") or ""),
                    str(record.get("authors") or ""),
                    str(record.get("abstract") or ""),
                    " ".join(record.get("tags") or []),
                ]
            )
            normalized_text = normalize_text(text)
            reasons: list[str] = []
            if any(token and token in normalized_text for token in exclude_tokens):
                reasons.append("命中排除词")
                excluded.append(
                    KnowledgePrescreenCandidate(
                        item_uid=str(record.get("item_uid") or ""),
                        title=str(record.get("title") or ""),
                        score=0.0,
                        decision="exclude",
                        reasons=tuple(reasons),
                    )
                )
                continue

            score = 0.0
            for token in include_tokens:
                if token and token in normalized_text:
                    score += 1.0
                    reasons.append(f"命中关键词:{token}")

            decision = "candidate" if score >= min_score else "exclude"
            candidate = KnowledgePrescreenCandidate(
                item_uid=str(record.get("item_uid") or ""),
                title=str(record.get("title") or ""),
                score=score,
                decision=decision,
                reasons=tuple(reasons) if reasons else ("未命中足够主题词",),
            )
            if decision == "candidate":
                candidates.append(candidate)
            else:
                excluded.append(candidate)

        candidates.sort(key=lambda item: (-item.score, item.title))
        excluded.sort(key=lambda item: (item.score, item.title))
        return KnowledgePrescreenResult(
            focus=focus,
            candidates=tuple(candidates),
            excluded=tuple(excluded),
            next_node="literature_reading",
        )

    def _build_tokens(self, focus: str, include_terms: list[str] | None) -> set[str]:
        """构建主题词集合。

        Args:
            focus: 主题描述。
            include_terms: 外部追加主题词。

        Returns:
            主题词集合。
        """

        tokens = {normalize_text(token) for token in re.split(r"[\s,，;；/]+", focus) if token.strip()}
        for token in include_terms or []:
            if token.strip():
                tokens.add(normalize_text(token))
        return tokens

    def _load_items_from_csv(self, literature_items_path: str | Path | None) -> list[dict[str, Any]]:
        """从文献数据库加载条目。

        Args:
            literature_items_path: 文献数据库路径。

        Returns:
            文献记录列表。
        """

        if literature_items_path is None:
            return []
        path = Path(literature_items_path)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置路径。

    Returns:
        输出文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    result = KnowledgePrescreenEngine().run(
        focus=str(raw_cfg.get("focus") or ""),
        items=raw_cfg.get("items"),
        literature_items_path=raw_cfg.get("literature_items_path"),
        include_terms=raw_cfg.get("include_terms"),
        exclude_terms=raw_cfg.get("exclude_terms"),
        min_score=float(raw_cfg.get("min_score") or 1.0),
    )

    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={str(raw_cfg.get('output_dir') or '')!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / "knowledge_prescreen_result.json"
    out_path.write_text(
        __import__("json").dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return [out_path]
