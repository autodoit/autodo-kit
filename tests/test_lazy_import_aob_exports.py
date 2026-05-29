"""AOB 懒加载导出回归测试。"""

from __future__ import annotations

import importlib

import autodokit as aok
from autodokit.tools import get_tool


def test_import_aob_package_should_not_require_full_tools_registry() -> None:
    """直接导入 AOB 子包时，不应被 tools 包级重导出阻塞。"""

    module = importlib.import_module("autodokit.tools.aob")

    assert callable(module.aob_backup_user_content)
    assert callable(module.aob_update_user_content)


def test_get_tool_should_lazy_load_aob_backup_entry() -> None:
    """get_tool 应可懒加载 AOB 公开函数。"""

    tool = get_tool("aob_backup_user_content")

    assert callable(tool)
    assert tool.__name__ == "aob_backup_user_content"


def test_autodokit_top_level_should_lazy_expose_run_affair() -> None:
    """autodokit 顶层应继续暴露 run_affair 契约。"""

    assert callable(aok.run_affair)