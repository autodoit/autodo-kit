"""来源选择与访问探测编排器。"""

from __future__ import annotations

from typing import Any


def run_source_selection(payload: dict[str, Any], *, source: str, mode: str, action: str) -> dict[str, Any]:
    """执行来源选择编排。"""
    if source == "school_foreign_database_portal" and mode == "catalog" and action == "fetch":
        from autodokit.tools.online_retrieval_literatures.executors.navigation_portal import execute_navigation_catalog

        return execute_navigation_catalog(payload)
    raise ValueError(f"source selection 不支持的组合: source={source}, mode={mode}, action={action}")
