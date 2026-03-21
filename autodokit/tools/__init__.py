"""AOK 工具统一导出入口。

本模块采用“直调函数优先”的设计：

1. 用户侧直接 `from autodokit.tools import 某工具` 后调用函数；
2. 开发侧通过开发者清单了解内部辅助工具；
3. 公开调用入口保持为“函数直调 + 分组导出”。
"""

from __future__ import annotations

from typing import Any, Callable

# 关键：统一从新目录再导出，保持外部导入路径稳定。
from autodoengine.utils.path_tools import (
    load_json_or_py,
    find_repo_root,
    resolve_path_from_base,
    resolve_config_paths,
    resolve_path_with_workspace_root,
    resolve_paths_to_absolute,
    resolve_workflow_config_path,
)
from autodoengine.utils.index_builders import (
    build_adjacency_matrix_df,
    build_inverted_from_adjacency,
    build_inverted_index,
    sparse_from_inverted,
)
from autodoengine.utils.affair_tags_db import (
    load_affair_tags,
    get_affairs_by_scenario,
    get_tags_by_affair,
)
from autodoengine.utils.expression_engine import (
    ExpressionEngineError,
    ExpressionEvalResult,
    evaluate_expression,
    evaluate_predicate,
)
from autodoengine.utils.node_execution import NodeExecutionResult
from autodoengine.utils.project_runtime import (
    load_json_file,
    resolve_config_path,
    resolve_workspace_root,
    summarize_workflow,
)
from autodoengine.utils.dispatch_map import load_dispatch_map
from autodoengine.utils.runtime_trace import append_flow_trace_event
from autodokit.tools.affair_result import ensure_absolute_output_dir, write_affair_json_result
from autodokit.tools.cnki_affair_helpers import build_cnki_result
from autodokit.tools.bibliodb import parse_reference_text, insert_placeholder_from_reference
from autodoengine.utils.affair_registry import (
    scan_affairs,
    validate_affair_manifest,
    build_registry,
    build_runtime_registry_view,
    build_module_alias_index,
    resolve_runner,
    get_affair_docs,
    lint_affairs,
)


_用户公开工具 = [
    "parse_reference_text",
    "insert_placeholder_from_reference",
    "build_cnki_result",
    "ensure_absolute_output_dir",
    "write_affair_json_result",
]

_开发者工具 = [
    "load_json_or_py",
    "find_repo_root",
    "resolve_path_from_base",
    "resolve_config_paths",
    "resolve_path_with_workspace_root",
    "resolve_paths_to_absolute",
    "resolve_workflow_config_path",
    "build_adjacency_matrix_df",
    "build_inverted_from_adjacency",
    "build_inverted_index",
    "sparse_from_inverted",
    "load_affair_tags",
    "get_affairs_by_scenario",
    "get_tags_by_affair",
    "ExpressionEngineError",
    "ExpressionEvalResult",
    "evaluate_expression",
    "evaluate_predicate",
    "NodeExecutionResult",
    "append_flow_trace_event",
    "ensure_absolute_output_dir",
    "write_affair_json_result",
    "build_cnki_result",
    "parse_reference_text",
    "insert_placeholder_from_reference",
    "load_dispatch_map",
    "load_json_file",
    "resolve_config_path",
    "resolve_workspace_root",
    "summarize_workflow",
    "scan_affairs",
    "validate_affair_manifest",
    "build_registry",
    "build_runtime_registry_view",
    "build_module_alias_index",
    "resolve_runner",
    "get_affair_docs",
    "lint_affairs",
]


def list_user_tools() -> list[str]:
    """返回面向用户公开的工具名列表。

    Returns:
        list[str]: 用户可直接导入与调用的工具函数名。

    Examples:
        >>> "parse_reference_text" in list_user_tools()
        True
    """

    return list(_用户公开工具)


def list_developer_tools() -> list[str]:
    """返回面向开发者的工具名列表。

    Returns:
        list[str]: 开发者可使用的工具函数名。

    Examples:
        >>> "load_json_or_py" in list_developer_tools()
        True
    """

    return list(_开发者工具)


def get_tool(tool_name: str, *, scope: str = "user") -> Callable[..., Any]:
    """按名称读取工具函数。

    Args:
        tool_name: 工具函数名。
        scope: 工具范围，支持 `user`、`developer`、`all`。

    Returns:
        Callable[..., Any]: 工具函数对象。

    Raises:
        KeyError: 工具不存在或不在指定范围内时抛出。

    Examples:
        >>> fn = get_tool("parse_reference_text")
        >>> callable(fn)
        True
    """

    target = str(tool_name or "").strip()
    if not target:
        raise KeyError("tool_name 不能为空")

    if scope == "user":
        allowed = set(_用户公开工具)
    elif scope == "developer":
        allowed = set(_开发者工具)
    else:
        allowed = set(_用户公开工具) | set(_开发者工具)

    if target not in allowed or target not in globals():
        raise KeyError(f"工具不存在或未在范围[{scope}]内公开：{target}")
    symbol = globals()[target]
    if not callable(symbol):
        raise KeyError(f"目标不是可调用工具：{target}")
    return symbol


__all__ = list(_用户公开工具)
