"""tools 子包的轻量导出。

说明：
- 本项目中多个事务会使用 `from autodokit.tools import ...` 的方式导入工具函数。
- 当你将实现文件移动到 tools 子包后，需要在此处统一导出公共符号，以保持导入路径稳定。

注意：
- 这里仅做符号再导出，不改变工具函数行为。
"""

from __future__ import annotations

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

__all__ = [
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
