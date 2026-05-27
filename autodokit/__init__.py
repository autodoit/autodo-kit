"""autodo-kit 包入口。"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str | None]] = {
    "api": ("autodokit.api", None),
    "bootstrap_runtime": ("autodokit.api", "bootstrap_runtime"),
    "create_task": ("autodokit.api", "create_task"),
    "import_affair_module": ("autodokit.api", "import_affair_module"),
    "import_user_affair": ("autodokit.api", "import_user_affair"),
    "load_graph": ("autodokit.api", "load_graph"),
    "prepare_affair_config": ("autodokit.api", "prepare_affair_config"),
    "register_graph": ("autodokit.api", "register_graph"),
    "run_affair": ("autodokit.api", "run_affair"),
    "run_task_step": ("autodokit.api", "run_task_step"),
    "run_task_until_terminal": ("autodokit.api", "run_task_until_terminal"),
    "run_task_until_wait": ("autodokit.api", "run_task_until_wait"),
    "list_user_tools": ("autodokit.tools", "list_user_tools"),
    "list_developer_tools": ("autodokit.tools", "list_developer_tools"),
    "get_tool": ("autodokit.tools", "get_tool"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'autodokit' has no attribute {name!r}")

    module_path, attr_name = target
    module = importlib.import_module(module_path)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS) | set(__all__))


def list_tools() -> list[str]:
    """返回用户侧公开工具列表。"""

    return __getattr__("list_user_tools")()


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