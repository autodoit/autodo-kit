# AOB统一业务事务

调用 `autodokit.tools.aob` 中的 6 个原子 AOB tool，并通过 `mode` 字段选择具体功能。

固定输出文件：

- `aob_business_result.json`

## mode 说明

- `validate_content`
  - 调用 `aob_validate_content`
  - 用途：校验 `libs` 或单个 AOL 输入路径是否合法。
  - 关键参数：`input_path`、`repo_root`

- `sync_items`
  - 调用 `aob_sync_items`
  - 用途：同步 `database/items.csv` 等内容库条目索引。
  - 关键参数：`strategy`、`dry_run`、`repo_root`

- `import_external_templates`
  - 调用 `aob_import_external_templates`
  - 用途：导入外部模板并联动入库。
  - 关键参数：`source_paths`、`target_library_dir_name`、`tags`

- `convert_workspace`
  - 调用 `aob_convert_workspace`
  - 用途：在模板项目内做跨引擎办公区转换。
  - 关键参数：`project_dir`、`source_engine`、`target_engine`

- `deploy_workflow`
  - 调用 `aob_deploy_workflow`
  - 用途：执行工作流安装部署。
  - 关键参数：`workflow`、`engine_ids`、`target_dir`

- `check_opencode_deploy_regression`
  - 调用 `aob_check_opencode_deploy_regression`
  - 用途：执行 OpenCode 部署后的最小回归检查。
  - 关键参数：`target_root`、`project_name`、`tags`

## 推荐用法

优先保持“一次事务只做一个动作”。即使统一为单事务，也应通过不同 `mode` 分次执行，避免把校验、导入、部署和回归混成一次不可审计的大调用。