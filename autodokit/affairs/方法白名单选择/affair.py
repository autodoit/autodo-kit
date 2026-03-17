"""方法白名单选择事务。

在候选方法列表中按白名单约束筛选可用识别策略，
并保持与 ARK 兼容的状态与结果结构。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List

from autodokit.tools import load_json_or_py

_DEFAULT_WHITELIST: tuple[str, ...] = (
    "did",
    "rdd",
    "event_study",
    "iv",
    "psm",
)


@dataclass(slots=True, frozen=True)
class MethodWhitelistSelectionResult:
    """方法白名单筛选结果。

    Args:
        whitelist: 生效白名单。
        selected: 入选方法。
        rejected: 拒绝方法。
    """

    whitelist: tuple[str, ...]
    selected: tuple[str, ...]
    rejected: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """导出为可序列化字典。

        Returns:
            可序列化结果。
        """

        return {
            "whitelist": list(self.whitelist),
            "selected": list(self.selected),
            "rejected": list(self.rejected),
        }


class MethodWhitelistSelectionEngine:
    """方法白名单选择引擎。"""

    def run(
        self,
        candidate_methods: list[str],
        whitelist: list[str] | None = None,
        top_k: int = 3,
    ) -> MethodWhitelistSelectionResult:
        """执行白名单筛选。

        Args:
            candidate_methods: 候选方法列表。
            whitelist: 可选白名单。
            top_k: 返回前 k 个入选方法。

        Returns:
            白名单筛选结果。

        Raises:
            ValueError: `top_k` 非正数时抛出。
        """

        if top_k < 1:
            raise ValueError("top_k 必须大于等于 1")

        active_whitelist = {item.lower().strip() for item in (whitelist or list(_DEFAULT_WHITELIST)) if item.strip()}
        normalized_candidates = [item.lower().strip() for item in candidate_methods if item.strip()]

        selected = [item for item in normalized_candidates if item in active_whitelist][:top_k]
        rejected = [item for item in normalized_candidates if item not in active_whitelist]

        return MethodWhitelistSelectionResult(
            whitelist=tuple(sorted(active_whitelist)),
            selected=tuple(selected),
            rejected=tuple(rejected),
        )


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置路径。

    Returns:
        输出文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    result = MethodWhitelistSelectionEngine().run(
        candidate_methods=list(raw_cfg.get("candidate_methods") or []),
        whitelist=raw_cfg.get("whitelist"),
        top_k=int(raw_cfg.get("top_k") or 3),
    )

    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={str(raw_cfg.get('output_dir') or '')!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / "method_whitelist_selection_result.json"
    out_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
