"""工具门面懒加载回归测试。

验证 `autodokit.tools` 的门面契约：`get_tool` 按作用域解析工具，
`autodokit` 顶层暴露 `run_affair`。
"""

from __future__ import annotations

import pytest

import autodokit as aok
from autodokit.tools import get_tool


def test_get_tool_should_resolve_user_scope_tool() -> None:
    """get_tool 应可懒加载用户作用域工具。"""

    tool = get_tool("crossref_verify_single")

    assert callable(tool)
    assert tool.__name__ == "crossref_verify_single"


def test_get_tool_should_reject_unknown_name() -> None:
    """未知工具名应被拒绝，而不是静默返回空。"""

    with pytest.raises(Exception):
        get_tool("no_such_tool_name_xyz")


def test_autodokit_top_level_should_lazy_expose_run_affair() -> None:
    """autodokit 顶层应继续暴露 run_affair 契约。"""

    assert callable(aok.run_affair)
