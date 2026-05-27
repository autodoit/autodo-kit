# AOB 原子工具与统一业务事务设计说明

本文档定义 AOK 中 AOB 迁移能力的正式实现边界：保留 6 个原子 tool，事务层收口为 1 个统一业务事务，通过 `mode` 参数完成功能分派。

## 1. 设计目标

本设计的目标不是“把所有 AOB 能力都做成很多事务”，而是把可复用执行能力拆成最小但仍然合理的原子层，再用一个统一事务承接用户侧与编排侧调用。

核心目标如下：

- 降低事务数量，避免出现多个职责相近、命名相似的 AOB 事务入口。
- 保留原子执行能力，便于 Python 直调、自动化编排与后续复用。
- 让每个能力点都有清晰的参数契约、输入约束和结果输出。
- 让文档、事务与脚本入口三层保持同一口径。

## 2. 为什么是 6 个 tool

AOB 迁移链路本质上包含 6 类独立但经常被串联使用的动作：

1. 内容编译校验。
2. 内容库条目同步。
3. 外部模板导入。
4. 办公区跨引擎转换。
5. 工作流安装部署。
6. OpenCode 部署回归检查。

这 6 类动作之间既存在明显的输入输出依赖，又不存在必须强绑定为同一原子函数的必要性。将它们拆成 6 个 tool 的理由是：

- 每个 tool 只有单一职责，参数面更小，调用面更清楚。
- tool 层可以被事务、脚本、测试和其他自动化流程复用。
- 失败定位更直接，出错时可以只重跑某一步，而不是重跑整条链路。
- 未来新增新的 AOB 组合方式时，不需要改底层执行原语，只需组合这些 tool。

### 2.1 6 个 tool 的职责边界

- `aob_validate_content`
  - 职责：执行 `aoc validate`。
  - 输入：AOL 输入路径、AOB 仓库根目录。
  - 输出：退出码。
- `aob_sync_items`
  - 职责：执行 `items sync`。
  - 输入：同步策略、是否 dry-run、AOB 仓库根目录。
  - 输出：退出码。
  - 运行约定：工具层通过受控 `AOB_REPO_ROOT` 环境上下文把 `repo_root` 传入 library runtime；同步前会调用 AOC 包内归一化函数。
- `aob_import_external_templates`
  - 职责：导入外部模板，并联动同步/入库。
  - 输入：来源路径、目标目录名、标签、导入模式、覆盖策略、dry-run、仓库根目录。
  - 输出：退出码。
- `aob_convert_workspace`
  - 职责：执行模板项目跨引擎办公区转换。
  - 输入：项目目录、源引擎、目标引擎、标题、dry-run、canonical dump 路径、validation report 路径、报告目录、降级策略、能力模式、仓库根目录。
  - 输出：结果字典，包含 `status`、`code`、`stats`、`warnings`、`blocking_errors`、`gating_errors`、`canonical_dump_path`、`validation_report_path`、`capability_report`。
  - 支持引擎：`opencode`、`claude`、`copilot`、`gemini`、`codex`。
- `aob_deploy_workflow`
  - 职责：执行工作流安装部署。
  - 输入：workflow、engine_ids、target_dir、项目名、标签、冲突策略、健康检查开关、扩展策略、git 初始化模式、dry-run、仓库根目录。
  - 输出：退出码。
  - 支持引擎：`opencode`、`claude`、`copilot`、`gemini`、`codex`，允许在一次 dry-run/install 中传入完整五引擎列表。
- `aob_check_opencode_deploy_regression`
  - 职责：执行 OpenCode 部署回归检查。
  - 输入：target_root、仓库根目录、agents 目录、opencode.json 文件名、项目名、标签。
  - 输出：退出码。

## 3. 为什么是 1 个事务

事务层的目标不是复制所有底层能力，而是给 AOK 提供一个面向运行时的稳定业务入口。

将 AOB 事务层收口为 1 个统一业务事务的原因如下：

- 从用户视角看，AOB 关注的是“我现在要做哪一类动作”，而不是“我应该记住哪几个事务名”。
- 从维护视角看，多个 AOB 事务会很快演变成配置字段相似、说明重复、文档散乱的入口集合。
- 从编排视角看，`mode` 比“多个事务名 + 多份模板”更适合做统一调度。
- 从演进视角看，新增 AOB 功能时，只需扩展 `mode` 分支和对应 tool，而不需要继续增加事务目录。

因此，事务层只保留一个入口：`AOB统一业务事务`。

## 4. 统一事务的设计方式

统一事务通过 `mode` 参数决定调用哪个 tool。当前支持的模式如下：

- `validate_content`
- `sync_items`
- `import_external_templates`
- `convert_workspace`
- `deploy_workflow`
- `check_opencode_deploy_regression`

### 4.1 统一事务的职责

统一事务只负责三件事：

1. 读取配置并校验 `mode`。
2. 根据 `mode` 调用对应原子 tool。
3. 写出统一结果文件 `aob_business_result.json`。

它不负责实现具体执行逻辑，也不负责在内部复制 CLI 参数拼接逻辑。

### 4.2 统一事务的使用规则

- 一次事务调用只建议执行一个 `mode`。
- 不建议把校验、同步、导入、转换、部署和回归混成一次调用。
- 如果需要完整链路，应该由上层编排按顺序触发多个事务调用或多个 `mode` 调用。

## 5. 参数契约

统一事务的参数采用“总表 + 按 mode 选用子集”的方式。

### 5.1 总体原则

- `mode` 是唯一必需字段。
- 其余字段按具体 mode 选用。
- 未被当前 mode 使用的字段可以保留在配置中，但不参与执行。
- 所有路径字段都必须由调用方提供明确值，不在事务内部做路径拼接策略决策。

### 5.2 路径与仓库根目录

- `repo_root` 统一用于 AOB 仓库根目录覆盖。
- `sync_items` 与 `import_external_templates` 通过工具层环境上下文把 `repo_root` 传入 library runtime，不把 `repo_root` 当作 library CLI 参数。
- `convert_workspace` 的旧 CLI 子命令只消费项目目录与源/目标引擎；工具层不向该子命令透传 `repo_root`。
- `input_path`、`project_dir`、`target_dir`、`target_root` 等字段均表示显式业务输入，不应在事务中自动推导成隐藏路径。
- AOB 工具层保留默认值，仅作为兼容便捷入口，不作为业务逻辑的唯一来源。

### 5.4 跨引擎能力报告

`convert_workspace` 的 capability report 使用三层能力模型：

- `L1`：`project_instruction`、`rules`、`skills`、`agents`、`commands`。
- `L2`：`hooks`、`mcp`、`settings`、`policies`。
- `L3`：`modes`、`plugins`、`tools`、`themes`、`plans`、`engine_overrides`。

canonical AOL dump 会把 `hooks`、`mcp_servers`、`settings`、`policies`、`engine_native` 作为根字段保存。目标引擎完整承接的能力标记为 `kept`；只能保留或近似投影的能力标记为 `downgraded`；完全不能承接的能力标记为 `unsupported` 并触发阻断。

### 5.3 输入校验策略

- `validate_content`：要求 `input_path` 可用。
- `import_external_templates`：要求 `source_paths`、`target_library_dir_name`、`tags` 非空。
- `convert_workspace`：要求 `project_dir`、`source_engine`、`target_engine` 非空。
- `deploy_workflow`：要求 `target_dir` 非空。
- `check_opencode_deploy_regression`：要求 `target_root` 非空。

## 6. 推荐调用链

如果目标是完整的 AOB 迁移/部署流程，推荐顺序如下：

1. `validate_content`
2. `sync_items`
3. `import_external_templates`（如有外部模板导入）
4. `convert_workspace`（如需办公区跨引擎转换）
5. `deploy_workflow`
6. `check_opencode_deploy_regression`

这条顺序能把“准备、同步、转换、部署、验收”分成可独立重跑的阶段。

## 7. 兼容策略

当前设计明确不再新增多个 AOB 事务入口，也不保留分散的 AOB 子事务集合。

兼容策略仅保留在两层：

- tool 层：对外保持 `aob_*` 原子入口。
- CLI 层：保留 `scripts/aob_tools/*.py` 与 `scripts/run_*.py` 作为薄入口。

不再保留的兼容层包括：

- 多个同级 AOB 事务目录。
- 事务层中对原子动作的重复封装。

## 8. 设计收益

- 工具层复用强，事务层入口少。
- 失败定位更快，单步重跑成本低。
- 文档说明更集中，用户与开发者看到的是一套一致口径。
- 后续新增 AOB 能力时，只需增加 tool 或扩展 mode，不必继续分裂事务层。

## 9. 与现有文档的关系

- [API手册](API手册.md) 记录 tool API 与统一事务入口。
- [AOK预置事务手册](AOK预置事务手册.md) 记录事务级字段、示例与调用方式。
- [用户手册](用户手册.md) 记录面向使用者的推荐顺序和操作说明。

本文档则聚焦“为什么这样拆”和“为什么事务只保留 1 个入口”。