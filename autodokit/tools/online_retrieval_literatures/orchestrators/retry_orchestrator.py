"""retry 编排器。"""

from __future__ import annotations

from typing import Any


def run_retry(payload: dict[str, Any], *, source: str, mode: str, action: str) -> dict[str, Any]:
    """执行 retry 编排。"""
    if mode == "retry" and action == "chaoxing_portal" and source == "en_open_access":
        from autodokit.tools.online_retrieval_literatures.executors.navigation_portal import execute_navigation_retry

        return execute_navigation_retry(payload)
    raise ValueError(f"retry 不支持的组合: source={source}, mode={mode}, action={action}")
