"""路径工具子域。"""

from __future__ import annotations

from autodokit.tools import (
	find_repo_root,
	load_json_or_py,
	resolve_config_paths,
	resolve_path_from_base,
	resolve_path_with_workspace_root,
	resolve_paths_to_absolute,
	resolve_workflow_config_path,
)
from autodokit.tools.atomic.path.windows_long_filename_tools import (
	WindowsShortPathAlias,
	build_short_alias_name,
	materialize_short_alias,
	needs_short_alias,
)

__all__ = [
	"load_json_or_py",
	"find_repo_root",
	"resolve_path_from_base",
	"resolve_config_paths",
	"resolve_path_with_workspace_root",
	"resolve_paths_to_absolute",
	"resolve_workflow_config_path",
	"WindowsShortPathAlias",
	"needs_short_alias",
	"build_short_alias_name",
	"materialize_short_alias",
]
