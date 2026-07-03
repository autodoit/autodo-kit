# AOB用户级内容同步

调用 `autodokit.tools.aob.aob_update_user_content`，按“参与方解析 -> AOL 反编译 -> logical key / SQLite 基线判定 -> canonical 回写 -> 定向发布”的顺序执行用户级内容同步。

固定输出文件：

- `aob_update_user_content_result.json`

## 核心原理

一键同步不是文件级复制，而是跨引擎语义级同步。它引入 AOL（统一语义中介层），把 Claude Code、Copilot、OpenCode 等不同引擎工作区中的 Agent、Skill、Rule、Instruction 等配置统一反编译为逻辑条目（logical_key），通过 SQLite 注册表判定每条语义单元的最新变化侧（winner side），合成统一的最新 canonical AOL，再编译回各引擎格式。

完整算法步骤：

1. 解析同步参与方（显式路径或自动发现）
2. 可选备份所有参与方目录
3. 收集所有 side 的 AOL 快照（反编译各引擎工作区）
4. 去污染（过滤旧同步 bug 产生的 vendor 后缀条目）
5. AOL 扁平化为 logical entries
6. 查询 SQLite 注册表基线
7. 对每个 logical_key 执行 Winner 决策（Presence > Absence > 时间戳 > 优先级）
8. 回写 canonical.aol.json
9. AOC 编译并发布到所有参与方
10. 差量删除过期托管文件
11. 更新注册表 + 撤销账本

## 安全机制

- **前置备份**（默认开启）：同步前自动备份所有参与方到 `autodo-lib/datastore/`
- **沙盒演练**（`--simulate-only`）：在独立沙盒目录中执行完整同步，不修改任何真实文件
- **撤销账本**（默认开启）：记录所有增删改操作，支持回滚
- **注册表基线**：通过 SQLite 维护每个 logical_key × side 的变更历史，不依赖易变的文件 mtime
- **去污染**：自动过滤历史同步 bug 产生的 vendor 后缀条目

## 关键参数

- `target_paths`：显式同步参与方路径列表
- `home_dir`：用户家目录（配合 vendor 过滤自动发现）
- `engine_vendors`：引擎过滤（claude/copilot/opencode/gemini/codex）
- `ide_vendors`：IDE 过滤（vscode）
- `scopes`：范围过滤（global/system/user/project）
- `project_dirs`：project 范围的项目根列表
- `include_missing`：是否纳入不存在的候选目录
- `backup_dir`：备份根目录（默认 autodo-lib/datastore）
- `dry_run`：预演模式（不落盘）
- `skip_backup`：跳过前置备份（不推荐）
- `skip_items_sync`：跳过 items 索引同步
- `simulate_only`：沙盒演练模式
- `sandbox_dir`：沙盒根目录（默认 Downloads 时间戳目录）
- `repo_root`：AOB 仓库根目录