# AOB用户级内容聚合

调用 `autodokit.tools.aob.aob_aggregate_user_content`，把用户侧内容聚合为 `libs/aol/canonical.aol.json`。

固定输出文件：

- `aob_aggregate_user_content_result.json`

## 核心原理

把用户本地各 AI 引擎工作区（`.claude/`、`.copilot/`、`.opencode/` 等）中的 Agent、Skill、Rule、Instruction 等配置，通过 AOC 反编译为统一的 AOL（语义中介语言），合并去重后写入 `libs/aol/canonical.aol.json`。

聚合后的 canonical AOL 是所有后续操作（发布、同步）的统一真源。

## 来源范围控制

通过 `--scope` 控制扫描范围：
- `user`：当前用户家目录下的引擎工作区（默认值）
- `project`：项目根目录下各引擎 carrier 根（需配合 `--project-dir`）
- `global` / `system`：系统全局路径

也可以用 `--source-path` 显式指定目录，此时忽略 `--scope`。

## 关键参数

- `source_paths`：显式来源路径列表
- `home_dir`：覆盖自动发现的用户主目录
- `scopes`：自动发现范围（global/system/user/project）
- `project_dirs`：项目根目录列表（project 范围时使用）
- `dry_run`：预演模式（不写入 canonical.aol.json）
- `skip_items_sync`：聚合后跳过 items 索引同步
- `simulate_only`：沙盒演练模式
- `sandbox_dir`：沙盒根目录
- `repo_root`：AOB 仓库根目录