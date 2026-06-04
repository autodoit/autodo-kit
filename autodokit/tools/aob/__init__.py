"""AOB 工具子包统一入口。

本包是 AOB 公开工具的规范入口：

1. 原子业务 API 统一从 ``autodokit.tools.aob`` 导出；
2. 复杂实现仍由 ``aob_tools`` / ``aob_atomic_tools`` / ``aob_workspace_pipeline`` 承载；
3. 顶层 ``autodokit.tools`` 仅保留兼容性懒加载，不再作为文档主入口。
"""

from __future__ import annotations

from .aob_atomic_tools import (
	aob_aggregate_user_content,
	aob_backup_user_content,
	aob_check_opencode_deploy_regression,
	aob_convert_workspace,
	aob_deploy_workflow,
	aob_import_external_templates,
	aob_list_undo_sessions,
	aob_publish_user_content,
	aob_sync_items,
	aob_undo_sync,
	aob_update_user_content,
	aob_validate_content,
)
from .aob_tools import (
	run_aob_aoc,
	run_aob_aggregate_user_content,
	run_aob_backup_user_content,
	run_aob_deploy,
	run_aob_external_templates_import,
	run_aob_items_sync,
	run_aob_library,
	run_aob_publish_user_content,
	run_aob_regression_opencode_deploy_check,
	run_aob_update_user_content,
	run_aob_workflow_deploy,
)
from .aob_workspace_pipeline import execute_workspace_conversion_pipeline

__all__ = [
	"aob_validate_content",
	"aob_sync_items",
	"aob_import_external_templates",
	"aob_aggregate_user_content",
	"aob_publish_user_content",
	"aob_backup_user_content",
	"aob_update_user_content",
	"aob_convert_workspace",
	"aob_deploy_workflow",
	"aob_check_opencode_deploy_regression",
	"aob_undo_sync",
	"aob_list_undo_sessions",
	"run_aob_aoc",
	"run_aob_deploy",
	"run_aob_library",
	"run_aob_items_sync",
	"run_aob_aggregate_user_content",
	"run_aob_backup_user_content",
	"run_aob_publish_user_content",
	"run_aob_update_user_content",
	"run_aob_external_templates_import",
	"run_aob_workflow_deploy",
	"run_aob_regression_opencode_deploy_check",
	"execute_workspace_conversion_pipeline",
]
