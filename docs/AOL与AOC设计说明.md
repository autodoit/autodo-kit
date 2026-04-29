# AOL 与 AOC 设计说明（v0.2）

本文档定义当前生效的 AOL（autodo-lang）与 AOC（autodo compiler）方案。

## 1. 总体原则

- AOL 是一种 Markdown 形态 DSL，不是 JSON。
- `libs/` 原位目录（`agents`、`skills`、`rules` 等）中的 Markdown 文件是 AOL 单一真源。
- 部署时只做 AOL -> 目标引擎编译，不维护多份并行元数据。
- 不保留过时兼容路径。
- AOL 是统一语义层，不直接绑定任一引擎目录语法。

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

## 3. AOC 行为

- `validate`：校验 AOL Markdown 源码目录或单文件。
- `compile`：将 AOL 编译为 OpenCode / Claude / Copilot 目标目录。
- OpenCode 阻断策略默认严格执行，不提供放行开关。
- `validate` 会提示潜在引擎专有内容泄漏（作为治理告警）。
- `compile` 到 OpenCode 时会执行颜色标准化适配（命名色 -> Hex）。

## 4. 使用方式

```powershell
# 校验 AOL 源码目录（libs 原位）
python tools/aoc.py validate --input libs

# 编译到 OpenCode
python tools/aoc.py compile --input libs --engine opencode --output-dir /home/ethan/DemoProject

# 编译到 Claude
python tools/aoc.py compile --input libs --engine claude --output-dir /home/ethan/DemoProject

# 编译到 Copilot
python tools/aoc.py compile --input libs --engine copilot --output-dir /home/ethan/DemoProject
```

## 5. 与同步/部署的关系

- `python tools/library.py items sync` 会把 `libs/` 原位文件归一化为 AOL DSL。
- `python tools/deploy.py workflow ...` 会直接从 `libs/` 原位内容编译并部署到指定引擎。
- 可通过 `items sync --dry-run` 查看本次归一化统计（`agents_converted`、`skills_converted`、`rules_converted`）。
