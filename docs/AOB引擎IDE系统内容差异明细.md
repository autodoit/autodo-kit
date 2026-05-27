# AOB引擎IDE系统内容差异明细

## 1. 文档目标

本文档用于把 AOB 当前涉及的四个维度统一收口到一份可对照的快照文档中：

1. AI 引擎供应商差异。
2. IDE 差异。
3. 操作系统差异。
4. AI 内容载体差异。

本文档覆盖两条不同但相关的链路：

1. AOC 正式编译/反编译链路。
2. AOB 用户级内容聚合/发布链路。

两条链路并不完全等价。部分供应商在用户级聚合/发布中可以被发现和投影，但并不是 AOC 的原生编译目标。

## 2. 真相源与阅读方式

本文档以以下文件为准：

1. `autodokit/tools/atomic/aob_runtime/aoc_tool.py`
2. `autodokit/tools/atomic/aob_runtime/library_tool.py`
3. `autodokit/tools/aob_workspace_pipeline.py`
4. `autodokit/tools/atomic/aob_runtime/workspace_profile_registry.py`
5. `autodo-lib/database/workspace_target_profiles.json`
6. `autodo-lib/database/engine_config_profiles.json`
7. `autodo-lib/database/aol_directory_mapping.json`

阅读本文档时需要先区分三个概念：

1. 原生编译目标：AOC 当前可直接编译到的目标引擎。
2. 用户级发现目标：AOB 当前可在本机自动发现或发布到的目录。
3. 映射目标：目录供应商不是 AOC 原生目标，但会被映射到最接近的语法族再进行编译。

## 3. 术语与状态标记

### 3.1 内容维度

本文档使用的 AI 内容维度包括：

| 内容维度 | 含义 |
| --- | --- |
| `project_instruction` | 项目级主说明/主提示词文件 |
| `rules` | 规则文件集合 |
| `skills` | 技能目录或技能文件集合 |
| `agents` | 代理定义 |
| `commands` | 命令载体 |
| `hooks` | hook 文件与 hook 索引 |
| `mcp` | MCP 服务配置 |
| `settings` | 源配置快照或目标配置补充字段 |
| `policies` | 审批、权限、沙箱等策略 |
| `extra_assets` | prompts、instructions、templates、plans、plugins 等附加载体 |
| `engine_overrides` | 引擎专有逃生口/覆盖层 |

### 3.2 能力状态

| 标记 | 含义 |
| --- | --- |
| `full` | AOC/AOB 当前能按主要语义完整承接 |
| `partial` | 可以生成文件或保留部分语义，但不是完全等价 |
| `mapped` | 不具备原生语法族，需先映射到其他引擎语法再投影 |
| `discovery-only` | 仅支持用户级发现/聚合/发布，不是正式编译目标 |
| `unsupported` | 当前没有正式支持 |

## 4. 引擎供应商总览

### 4.1 当前角色总表

| 供应商 | 在 AOC 中的角色 | 在 AOB 用户级聚合中的角色 | 在 AOB 用户级发布中的角色 | 归一化后的 AOC 目标 | 主要目录 | 当前状态 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `opencode` | 原生编译目标 | 自动发现 | 自动发布 | `opencode` | `.opencode` | `supported` | 额外存在项目级 `opencode.json` |
| `claude` | 原生编译目标 | 自动发现 | 自动发布 | `claude` | `.claude` | `supported` | 项目根和工作区内都可能出现 `CLAUDE.md` |
| `copilot` | 原生编译目标 | 自动发现 | 自动发布 | `copilot` | `.github`（工作区）/`.copilot`（用户级目录） | `supported` | 工作区部署与用户级目录是两套载体 |
| `gemini` | 原生编译目标 | 自动发现 | 自动发布 | `gemini` | `.gemini` | `supported` | 项目级主说明文件是 `GEMINI.md` |
| `codex` | 原生编译目标 | 自动发现 | 自动发布 | `codex` | `.codex` | `supported` | 项目级主说明文件是 `AGENTS.md` |
| `lingma` | 非原生编译目标 | 自动发现 | 自动发布 | `copilot` | `.lingma` | `experimental` | 发布时按 Copilot 语法族编译后投影 |
| `qoder` | 非原生编译目标 | 自动发现 | 自动发布 | `copilot` | `.qoder` | `experimental` | 发布时按 Copilot 语法族编译后投影 |
| `qwen` | 非原生编译目标 | 自动发现 | 自动发布 | `copilot` | `.qwen` | `experimental` | 发布时按 Copilot 语法族编译后投影 |

补充说明：

1. `cursor` 在当前实现里更适合作为 IDE 供应商，而不是独立引擎供应商。
2. `cursor` 用户级目录会被标记为 `ide_vendor=cursor`、`engine_vendor=claude`，发布时按 Claude 语法族编译。
3. `lingma/qoder/qwen` 虽然拥有自己的目录名和 profile，但当前 AOC 原生编译目标仍只有五类：`opencode/claude/copilot/gemini/codex`。

### 4.2 原生编译目标内容能力矩阵

下表来自 `aob_workspace_pipeline.py` 的分层能力矩阵，表示目标引擎的当前承接级别：

| 内容维度 | `opencode` | `claude` | `copilot` | `gemini` | `codex` |
| --- | --- | --- | --- | --- | --- |
| `project_instruction` | `full` | `full` | `full` | `full` | `full` |
| `rules` | `full` | `full` | `full` | `partial` | `partial` |
| `skills` | `full` | `full` | `full` | `full` | `full` |
| `agents` | `full` | `full` | `full` | `full` | `partial` |
| `commands` | `full` | `full` | `partial` | `partial` | `partial` |
| `hooks` | `partial` | `full` | `partial` | `full` | `partial` |
| `mcp` | `full` | `full` | `partial` | `full` | `full` |
| `settings` | `partial` | `partial` | `partial` | `full` | `partial` |
| `policies` | `full` | `partial` | `partial` | `partial` | `full` |
| `modes` | `full` | `partial` | `partial` | `partial` | `partial` |
| `plugins` | `full` | `partial` | `partial` | `partial` | `partial` |
| `tools` | `full` | `partial` | `partial` | `partial` | `partial` |
| `themes` | `full` | `partial` | `partial` | `partial` | `partial` |
| `plans` | `full` | `partial` | `partial` | `partial` | `partial` |
| `engine_overrides` | `partial` | `partial` | `partial` | `partial` | `partial` |

解释：

1. `partial` 不代表完全没有载体，而是“文件可以写出，但宿主是否具备同等官方语义面”并不稳定。
2. 例如 `copilot` 当前会写出 `commands/` 和 `rules/`，但 capability 仍把 `commands` 判为 `partial`。
3. `codex` 当前没有单独的 `agents/` 目录输出，因此 `agents` 为 `partial`。

### 4.3 用户级发现/发布映射矩阵

| 用户级目录供应商 | 目录名 | 发布时使用的语法族 | 说明 |
| --- | --- | --- | --- |
| `copilot` | `.copilot` | `copilot` | 用户级目录存在，但工作区部署主路径是 `.github` |
| `claude` | `.claude` | `claude` | 原生 Claude 目录 |
| `codex` | `.codex` | `codex` | 原生 Codex 目录 |
| `gemini` | `.gemini` | `gemini` | 原生 Gemini 目录 |
| `opencode` | `.opencode` | `opencode` | 原生 OpenCode 目录 |
| `cursor` | `.cursor` | `claude` | Cursor 当前按 Claude 语法族处理 |
| `lingma` | `.lingma` | `copilot` | 非原生 AOC 目标，发布时映射 |
| `qoder` | `.qoder` | `copilot` | 非原生 AOC 目标，发布时映射 |
| `qwen` | `.qwen` | `copilot` | 非原生 AOC 目标，发布时映射 |

## 5. 各引擎的文件、文件夹、配置与元数据差异

### 5.1 输出载体差异总表

| 差异项 | `opencode` | `claude` | `copilot` | `gemini` | `codex` |
| --- | --- | --- | --- | --- | --- |
| 工作区目录名 | `.opencode` | `.claude` | `.github` | `.gemini` | `.codex` |
| 项目级主说明文件 | 无固定项目根说明；主指令可写为 `.opencode/library.md` | `CLAUDE.md` | `.github/copilot-instructions.md` | `GEMINI.md` | `AGENTS.md` |
| 工作区主配置文件 | `.opencode/autodo.engine.config.json` | `.claude/settings.json` 与 `.claude/autodo.engine.config.json` | `.github/autodo.engine.config.json` | `.gemini/settings.json` 与 `.gemini/autodo.engine.config.json` | `.codex/config.json` 与 `.codex/autodo.engine.config.json` |
| 项目级配置文件 | `opencode.json` | 可额外生成项目根 `.mcp.json` | 无公开项目级 JSON，主要靠 `.github` | 无额外项目级 JSON | 无额外项目级 JSON |
| 代理文件后缀 | `.md` | `.md` | `.agent.md` | `.md` | 无单独代理文件 |
| 技能目录布局 | `skills/<name>/SKILL.md` | 相同 | 相同 | 相同 | 相同 |
| 规则目录 | `rules/*.md` | `.claude/rules/*.md` | `.github/rules/*.md` | `.gemini/rules/*.md` | `.codex/rules/*.md` |
| 命令目录 | `commands/*.md` | `.claude/commands/*.md` | `.github/commands/*.md` | `.gemini/commands/*.md` | `.codex/commands/*.md` |
| hooks 文件索引键 | `aolHooks` | `hooks.aolHookFiles` | `aolHooks` | `hooks.aolHookFiles` | `aolHooks` |
| MCP 主键 | `mcp.servers` | `mcpServers` | `mcpServers` | `mcpServers` | `mcp_servers` |
| 策略主键 | `permission` | `aolPolicies` | `aolPolicies` | `aolPolicies` | `approval_policy`、`sandbox_mode`、`aolPolicies` |
| canonical 摘要键 | `aolCanonical` | `aolCanonical` | `aolCanonical` | `aolCanonical` | `aolCanonical` |

### 5.2 配置字段语法差异表

| 配置维度 | `opencode` | `claude` | `copilot` | `gemini` | `codex` |
| --- | --- | --- | --- | --- | --- |
| MCP | `mcp.servers` | `mcpServers`，并可能额外写项目根 `.mcp.json` | `mcpServers` 写入 `.github/autodo.engine.config.json` | `mcpServers` | `mcp_servers` |
| Hooks 索引 | `aolHooks` | `hooks: { aolHookFiles: [...] }` | `aolHooks` | `hooks: { aolHookFiles: [...] }` | `aolHooks` |
| 策略投影 | `permission` + `aolPolicies` | `aolPolicies` | `aolPolicies` | `aolPolicies` | `approval_policy`、`sandbox_mode`、`aolPolicies` |
| 设置快照 | `aolSettings` | `aolSettings` | `aolSettings` | `aolSettings` | `aolSettings` |
| canonical 摘要 | `aolCanonical` | `aolCanonical` | `aolCanonical` | `aolCanonical` | `aolCanonical` |
| 原生覆盖层 | 先合并 `engine_native.opencode` | 先合并 `engine_native.claude` | 先合并 `engine_native.copilot` | 先合并 `engine_native.gemini` | 先合并 `engine_native.codex` |

### 5.3 反编译/读取源配置候选路径差异

| 源引擎 | 反编译时读取的配置候选路径 |
| --- | --- |
| `opencode` | `<workspace>/autodo.engine.config.json`、`<project>/opencode.json`、`<workspace>/opencode.json` |
| `claude` | `<workspace>/autodo.engine.config.json`、`<workspace>/settings.json`、`<project>/.mcp.json` |
| `copilot` | `<workspace>/autodo.engine.config.json`、`<workspace>/copilot-instructions.json`、`<workspace>/settings.json` |
| `gemini` | `<workspace>/autodo.engine.config.json`、`<workspace>/settings.json` |
| `codex` | `<workspace>/autodo.engine.config.json`、`<workspace>/config.json`、`<workspace>/config.toml` |

说明：

1. 反编译候选路径通常比 emitter 实际写出的路径更宽，用于兼容历史或宿主私有格式。
2. `copilot` 是最明显的例子：当前 emitter 主要写 `.github/autodo.engine.config.json`，但反编译仍保留对 `copilot-instructions.json`、`settings.json` 的读取候选。

## 6. IDE 维度差异

### 6.1 工作区级 IDE/Profile 差异矩阵

| IDE 供应商 | 绑定引擎 | Windows | macOS | Linux | runtime_mode | 当前状态 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `opencode` | `opencode` | `.opencode` + `opencode.json` | 同 Windows | 同 Windows | `native` | `supported` | 三系统路径相对工作区一致 |
| `claude` | `claude` | `.claude/settings.json`、`.claude/autodo.engine.config.json`、`CLAUDE.md` | 同 Windows | 同 Windows | `native` | `supported` | 项目根和工作区内均可能持有 `CLAUDE.md` |
| `vscode` | `copilot` | `.github/autodo.engine.config.json`、`.github/copilot-instructions.md` | 同 Windows | 同 Windows | `extension` | `supported` | 工作区路径相对一致，用户级 prompts 路径受 OS 影响最大 |
| `gemini` | `gemini` | `.gemini/settings.json`、`.gemini/autodo.engine.config.json`、`GEMINI.md` | 同 Windows | 同 Windows | `native` | `supported` | 工作区路径相对一致 |
| `codex` | `codex` | `.codex/config.json`、`.codex/autodo.engine.config.json`、`AGENTS.md` | 同 Windows | 同 Windows | `native` | `supported` | 工作区路径相对一致 |
| `cursor` | `claude` | `.cursor/settings.json`、`.cursor/autodo.engine.config.json`、`CLAUDE.md` | 同 Windows | 同 Windows | `embedded` | `experimental` | 语法族按 Claude 处理 |
| `jetbrains` | `jetbrains` | `.idea/workspace.xml`、`.idea/misc.xml`、`.idea/.name` | 未登记 | 未登记 | `native` | `experimental` | 当前只有 Win11 profile |
| `qoder` | `qoder` | `.qoder/settings.json`、`.qoder/autodo.engine.config.json` | 未登记 | 未登记 | `native` | `experimental` | 当前只有 Win11 profile |
| `lingma` | `lingma` | `.lingma/settings.json`、`.lingma/autodo.engine.config.json` | 未登记 | 未登记 | `native` | `experimental` | 当前只有 Win11 profile |
| `qwen` | `qwen` | `.qwen/settings.json`、`.qwen/autodo.engine.config.json` | 未登记 | 未登记 | `native` | `experimental` | 当前只有 Win11 profile |

关键结论：

1. 对工作区级 profile 来说，Windows、macOS、Linux 的主要差异不是相对路径写法，而是 profile 是否登记、状态是否 `supported`。
2. 对支持的五类原生编译目标来说，三系统工作区相对路径基本一致。
3. 真正差异很大的地方主要在用户级 IDE 数据目录，而不是工作区内的相对路径。

### 6.2 用户级 IDE 路径差异矩阵

下表只讨论 AOB 当前已经显式登记或自动发现的用户级目录：

| IDE/宿主 | Windows | macOS | Linux | 当前口径 |
| --- | --- | --- | --- | --- |
| VS Code 用户 prompts | `%APPDATA%/Code/User/prompts` | 未登记原生路径 | 未登记原生路径 | AOB 自动发现逻辑是 Windows 优先 |
| Cursor 用户 prompts | `%APPDATA%/Cursor/User/prompts` | 未登记原生路径 | 未登记原生路径 | AOB 自动发现逻辑是 Windows 优先 |
| Lingma 用户 prompts | `%APPDATA%/Lingma/User/prompts` | 未登记原生路径 | 未登记原生路径 | AOB 自动发现逻辑是 Windows 优先 |
| JetBrains 用户配置 | `%HOME%/AppData/Roaming/JetBrains`、`%HOME%/AppData/Local/JetBrains` | 未登记 | 未登记 | 仅 profile 登记，未接入 library 自动发现 |

实现边界说明：

1. `library_tool.py` 对 prompts 根目录的自动发现使用 `APPDATA`；如果 `APPDATA` 不存在，则回退到 `${HOME}/AppData/Roaming/...`。
2. 这意味着当前 prompts 自动发现是明显的 Windows 目录模型；在 macOS/Linux 上没有登记为原生路径。
3. 因此，macOS/Linux 下的 VS Code/Cursor/Lingma 用户 prompts 目录，目前不应被视为“已原生支持自动发现”。

### 6.3 用户级结构化根目录差异

结构化根目录的逻辑比 prompts 根目录简单，当前统一走 `${HOME}/.<vendor>`：

| 结构化目录 | Windows | macOS | Linux | 说明 |
| --- | --- | --- | --- | --- |
| `.copilot` | `${HOME}/.copilot` | `${HOME}/.copilot` | `${HOME}/.copilot` | 用户级聚合/发布可自动发现 |
| `.claude` | `${HOME}/.claude` | `${HOME}/.claude` | `${HOME}/.claude` | 用户级聚合/发布可自动发现 |
| `.codex` | `${HOME}/.codex` | `${HOME}/.codex` | `${HOME}/.codex` | 用户级聚合/发布可自动发现 |
| `.gemini` | `${HOME}/.gemini` | `${HOME}/.gemini` | `${HOME}/.gemini` | 用户级聚合/发布可自动发现 |
| `.opencode` | `${HOME}/.opencode` | `${HOME}/.opencode` | `${HOME}/.opencode` | 用户级聚合/发布可自动发现 |
| `.cursor` | `${HOME}/.cursor` | `${HOME}/.cursor` | `${HOME}/.cursor` | 目录供应商是 Cursor，语法族映射到 Claude |
| `.lingma` | `${HOME}/.lingma` | `${HOME}/.lingma` | `${HOME}/.lingma` | 语法族映射到 Copilot |
| `.qoder` | `${HOME}/.qoder` | `${HOME}/.qoder` | `${HOME}/.qoder` | 语法族映射到 Copilot |
| `.qwen` | `${HOME}/.qwen` | `${HOME}/.qwen` | `${HOME}/.qwen` | 语法族映射到 Copilot |

## 7. AI 内容载体的细分差异

### 7.1 `agents`

| 目标引擎 | 文件形态 |
| --- | --- |
| `opencode` | `agents/<id>.md` |
| `claude` | `.claude/agents/<id>.md` |
| `copilot` | `.github/agents/<id>.agent.md` |
| `gemini` | `.gemini/agents/<id>.md` |
| `codex` | 不输出单文件 agent，收敛到项目级 `AGENTS.md` |

### 7.2 `skills`

所有正式编译目标当前都采用相同布局：

| 目标引擎 | 技能布局 |
| --- | --- |
| 全部正式目标 | `<workspace>/skills/<skill-name>/SKILL.md` |

### 7.3 `rules`

| 目标引擎 | 规则目录 |
| --- | --- |
| `opencode` | `.opencode/rules/*.md` |
| `claude` | `.claude/rules/*.md` |
| `copilot` | `.github/rules/*.md` |
| `gemini` | `.gemini/rules/*.md` |
| `codex` | `.codex/rules/*.md` |

### 7.4 `prompts` 与 `instructions`

在 AOB 用户级发布中，prompts 根目录和结构化根目录处理方式不同：

| 目标布局 | 发布规则 |
| --- | --- |
| `structured_root` | 接收完整 AOC 编译结果 |
| `prompt_root` | 只投影 `.prompt.md` 与 `.instructions.md` |

这意味着：

1. VS Code/Cursor/Lingma 的 `User/prompts` 不会收到 `settings.json`、`CLAUDE.md`、`AGENTS.md` 之类结构化文件。
2. 用户级 prompts 根目录不是完整工作区壳子，只是提示词/指令子集载体。

### 7.5 `settings`、`policies`、`mcp`、`hooks`

| 内容类型 | 当前差异点 |
| --- | --- |
| `settings` | 统一保留为 `aolSettings`，但工作区主配置文件名随引擎变化 |
| `policies` | `opencode` 偏 `permission`；`codex` 额外拆出 `approval_policy` 与 `sandbox_mode`；其他引擎主要保存在 `aolPolicies` |
| `mcp` | 键名有三种语法：`mcp.servers`、`mcpServers`、`mcp_servers` |
| `hooks` | 键名分裂为 `aolHooks` 与 `hooks.aolHookFiles` 两族，同时 hook 文件本体仍按相对路径写出 |

## 8. 当前实现中的关键边界与注意事项

### 8.1 `workspace_target_profiles.json` 与 `engine_config_profiles.json` 不是同一层

两者职责不同：

1. `workspace_target_profiles.json` 负责“工作区目标 profile”的路径、OS、IDE、状态登记。
2. `engine_config_profiles.json` 更接近“引擎级配置模板”或通用 profile 草案。

最典型的例子是 `copilot`：

| 文件 | 对 Copilot 的配置路径口径 |
| --- | --- |
| `workspace_target_profiles.json` | `.github/autodo.engine.config.json` |
| `workspace_profile_registry.py` | `.github/autodo.engine.config.json` |
| `aoc_tool.py` 当前 emitter | `.github/autodo.engine.config.json` |
| `engine_config_profiles.json` | `.copilot/autodo.engine.config.json` |

因此，在当前 AOB/AOC 工作区部署、转换与文档说明中，应把 `.github/autodo.engine.config.json` 视为现行工作区口径；`engine_config_profiles.json` 中的 `.copilot/...` 更适合作为引擎级模板参考，而不是当前 emitter 的最终落点。

### 8.2 `canonical.aol.json` 的语义边界

需要区分两件事：

1. 从手工维护角度看，`libs/` Markdown 仍是 AOL 语义层的长期内容源。
2. 从 AOB 用户级聚合/发布链路看，`libs/aol/canonical.aol.json` 是当前运行时真源。

也就是说：

1. 手工编辑与内容治理主要面向 `libs/agents`、`libs/skills`、`libs/rules` 等目录。
2. 用户级内容的“聚合后再发布”主链，当前显式依赖 `canonical.aol.json`。

### 8.3 用户级 prompts 自动发现是 Windows 优先实现

这是当前系统差异里最需要特别说明的一点：

1. 工作区路径基本是相对路径，跨 OS 差异小。
2. 用户级结构化根目录统一是 `${HOME}/.<vendor>`，跨 OS 差异也小。
3. 真正受 OS 影响大的，是 IDE 的用户 prompts 目录；当前实现只把 Windows 目录模型显式登记为自动发现路径。

## 9. 面向后续扩展的建议

1. 若新增新的原生引擎供应商，必须同时更新：
   - `aoc_tool.py` 的编译/反编译逻辑；
   - `aob_workspace_pipeline.py` 的能力矩阵；
   - `workspace_target_profiles.json` 的 OS/IDE profile；
   - 本文档中的差异矩阵。
2. 若要把 macOS/Linux 的 IDE 用户 prompts 自动发现做成正式支持，应先把原生路径口径补进 profile 或 library runtime，而不是继续依赖 `${HOME}/AppData/Roaming/...` 回退。
3. 若要让 `lingma/qoder/qwen` 不再走 `mapped` 路径，必须先为它们建立原生 AOC emitter，而不是只扩目录名。