"""autodo-kit 包入口。"""

from __future__ import annotations

from autodokit.api import (
    bootstrap_runtime,
    create_task,
    import_affair_module,
    import_user_affair,
    load_graph,
    prepare_affair_config,
    register_graph,
    run_affair,
    run_task_step,
    run_task_until_terminal,
    run_task_until_wait,
)
import autodokit.api as api
from autodokit.tools import get_tool, list_developer_tools, list_user_tools


def list_tools() -> list[str]:
    """返回用户侧公开工具列表。"""

    return list_user_tools()


__all__ = [
    "api",
    "import_affair_module",
    "import_user_affair",
    "prepare_affair_config",
    "run_affair",
    "bootstrap_runtime",
    "create_task",
    "run_task_step",
    "run_task_until_terminal",
    "run_task_until_wait",
    "load_graph",
    "register_graph",
    "list_tools",
    "list_user_tools",
    "list_developer_tools",
    "get_tool",
]