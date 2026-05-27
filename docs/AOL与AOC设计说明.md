# AOL 与 AOC 设计说明

本文档定义当前生效的 AOL（autodo-lang）与 AOC（autodo compiler）方案。

## 1. 总体原则

- AOL 是一种 Markdown 形态 DSL，不是 JSON。
- `libs/` 原位目录（`agents`、`skills`、`rules` 等）中的 Markdown 文件是 AOL 单一真源。
- 部署时只做 AOL -> 目标引擎编译，不维护多份并行元数据。
- 不保留过时兼容路径。
- AOL 是统一语义层，不直接绑定任一引擎目录语法。
- canonical dump 是 AOB 转换过程中的 JSON 快照，用于报告、审计和回放，不作为人工维护的 AOL 源码格式。

### 1.1 统一语义层与适配层边界

- 统一语义层（AOL）：表达角色意图、能力描述、规则内容、技能正文、语义标签。
- 引擎适配层（AOC + `database/engine_config_profiles.json`）：表达模型参数、权限策略、目录路径、引擎专有字段。

### 1.2 AOL 禁止项（强约束）

- 禁止在 AOL 正文中硬编码引擎专有路径：如 `.claude/`、`.opencode/`、`.github/`、`~/.claude/`。
- 禁止在 AOL 中硬编码项目级引擎配置文件名：如 `opencode.json`、`AGENTS.md`。
- 如需表达“规则目录/技能目录”，应使用语义化占位或由 AOC 适配期注入。

## 2. AOL 文件结构

### 2.0 指定目录集合（libs 原位归一化范围）

`items sync` 触发 AOL 归一化时，目录范围由 `database/aol_directory_mapping.json` 控制。

默认配置：

```json
{
	"agent_dirs": ["agents"],
	"skill_dirs": ["skills"],
	"skill_layout_mode": "strict",
	"allow_legacy_skill_layout": true,
	"strict_skill_required_dirs": ["scripts", "references"],
	"rule_dirs": ["rules", "prompts", "hooks", "settings", "templates", "instructions"]
}
```

说明：
- `agent_dirs`：按 `*.md` 扫描并按 Agent 语义归一化。
- `skill_dirs`：默认按严格模式扫描 Skill。
- `skill_layout_mode`：`strict`（默认）或 `compat`。
- `allow_legacy_skill_layout`：在 `strict` 下是否兼容文件式 Skill（`skills/*.skill.md`）。
- `strict_skill_required_dirs`：严格模式下 Skill 目录必须存在的子目录（默认 `scripts/`、`references/`）。
- `rule_dirs`：`rules` 目录按 `*.md` 扫描；其他目录按 `**/*.md` 递归扫描，并并入 Rule 集合（以目录名前缀生成稳定 rule id）。
- 当配置文件不存在、JSON 非法或字段缺失时，AOC 自动回退到内置默认映射。

### 2.1 代理文件

`agents/*.md`：

- `aol_version`
- `kind: agent`
- `id`
- `description`
- `mode`
- `model`（可选）
- `color`（可选）
- `tools`（可选）
- 正文即提示词内容

说明：
- `description` 支持 YAML 多行块标量（`|`）。
- `color` 在 AOC 编译到 OpenCode 时会自动标准化为 `#RRGGBB`。

### 2.2 技能文件

默认严格模式下：`skills/<skill-name>/SKILL.md`，并要求 `skills/<skill-name>/scripts/` 与 `skills/<skill-name>/references/` 存在。

兼容模式（或开启严格模式兼容开关）下，仍可识别：`skills/*.skill.md`。

Skill frontmatter 语义字段：

- `aol_version`
- `kind: skill`
- `name`
- `description`
- `meta_*`（可选）
- 正文即技能内容

### 2.3 规则文件

`rules/*.md`：

- `aol_version`
- `kind: rule`
- `id`
- 正文即规则文本

### 2.4 根对象字段

AOC 在从引擎办公区反编译 AOL 时，会把以下跨引擎配置提升为 AOL 根对象字段：

- `project_instruction`：项目级指令文本。
- `commands`：命令定义列表，主要来自引擎命令目录或可迁移命令载体。
- `hooks`：生命周期 hook 载体列表，结构与附加载体一致，包含 `relative_path` 与 `content`。
- `mcp_servers`：MCP 服务注册表，统一从 `mcpServers`、`mcp_servers` 或 `mcp.servers` 抽取。
- `settings`：源引擎配置快照，包含 `sourceEngine` 与 `sourceConfigs`。
- `policies`：权限、审批、安全与沙箱策略，覆盖 `permission`、`permissions`、`approval`、`approval_policy`、`sandbox`、`sandbox_mode`、`security` 等键。
- `engine_native`：引擎原生逃生口，用于保留目标引擎可直接消费或不可无损通用化的字段。
- `extra_assets`：prompts、workflows、templates、context、docs、instructions、governance、modes、plugins、tools、themes、plans 等可迁移附加载体。

这些字段共同构成 AOB `convert_workspace` 的 canonical AOL dump。目标引擎无法完整承接的字段不会静默丢弃，必须在 capability report 中呈现为 `downgraded` 或 `unsupported`。

## 3. AOC 行为

- `validate`：校验 AOL Markdown 源码目录或单文件。
- `compile`：将 AOL 编译为 OpenCode、Claude、Copilot、Gemini、Codex 目标目录。
- OpenCode 阻断策略默认严格执行，不提供放行开关。
- `validate` 会提示潜在引擎专有内容泄漏（作为治理告警）。
- `compile` 到 OpenCode 时会执行颜色标准化适配（命名色 -> Hex）。
- 从办公区反编译 AOL 时，AOC 会读取五类办公区目录：`.opencode`、`.claude`、`.github`、`.gemini`、`.codex`。
- 编译到 Claude/Gemini/Codex 等目标时，AOC 会在目标配置中写入 MCP、hooks、settings、policies 与 `aolCanonical` 摘要；Copilot 无等价公开配置面时，会把这些字段保存在 `.github/autodo.engine.config.json`。

### 3.1 能力分层

AOB capability report 使用以下分层：

- `L1` 基础通用层：`project_instruction`、`rules`、`skills`、`agents`、`commands`。
- `L2` 扩展能力层：`hooks`、`mcp`、`settings`、`policies`。
- `L3` 引擎逃生口：`modes`、`plugins`、`tools`、`themes`、`plans`、`engine_overrides`。

支持结果使用三种状态：

- `full`：目标引擎可按语义完整承接。
- `partial`：目标引擎可保留或近似投影，但语义可能降级。
- `unsupported`：目标引擎无法承接且不能安全保留，请求该能力时会阻断转换。

## 4. 使用方式

```bash
# 校验 AOL 源码目录（libs 原位）
python scripts/aob_tools/aoc.py validate --input libs

# 编译到 OpenCode
python scripts/aob_tools/aoc.py compile --input libs --engine opencode --output-dir /home/ethan/DemoProject

# 编译到 Claude
python scripts/aob_tools/aoc.py compile --input libs --engine claude --output-dir /home/ethan/DemoProject

# 编译到 Copilot
python scripts/aob_tools/aoc.py compile --input libs --engine copilot --output-dir /home/ethan/DemoProject

# 编译到 Gemini
python scripts/aob_tools/aoc.py compile --input libs --engine gemini --output-dir /home/ethan/DemoProject

# 编译到 Codex
python scripts/aob_tools/aoc.py compile --input libs --engine codex --output-dir /home/ethan/DemoProject
```

## 5. 与同步/部署的关系

- `python scripts/aob_tools/library.py items sync` 会把 `libs/` 原位文件归一化为 AOL DSL。
- `python scripts/aob_tools/deploy.py workflow ...` 会直接从 `libs/` 原位内容编译并部署到指定引擎。
- 可通过 `items sync --dry-run` 查看本次归一化统计（`agents_converted`、`skills_converted`、`rules_converted`）。
