# API手册

autodo-kit 对外公开的是“事务内容 + 事务工具 + 少量桥接入口”。真正的运行时执行与调度 API 由 autodo-engine 提供。

## 1. 桥接入口

### 1.1 autodokit.run_affair(...)

用途：通过 autodo-engine 的运行时执行官方事务或用户覆盖事务。

典型参数：

- affair_uid：事务 UID
- config：字典配置
- config_path：配置文件路径
- workspace_root：工作区根目录

### 1.2 autodokit.prepare_affair_config(...)

用途：调用引擎侧统一路径预处理逻辑，对事务配置中的路径字段做绝对化。

### 1.3 autodokit.import_affair_module(...)

用途：按事务 UID 导入实际事务模块，优先读取 runner.module，必要时回退到源码文件路径加载。

### 1.4 autodokit.import_user_affair(...)

用途：将用户功能程序导入为事务三件套目录（`affair.py`、`affair.json`、`affair.md`），并自动写入事务管理数据库。名称冲突时自动追加 `_v正整数`。

## 2. autodokit.tools 导出

autodokit.tools 统一导出两类能力：

- 事务本仓实现：如 pandoc_tex_word_converter、task_docs、obsidian_exporter、metadata_dedup
- 引擎侧通用能力桥接：如 load_json_or_py、resolve_paths_to_absolute、build_registry、evaluate_expression

常用导出示例：

- load_json_or_py
- resolve_paths_to_absolute
- write_affair_json_result
- build_cnki_result
- load_dispatch_map
- evaluate_expression
- append_flow_trace_event

## 2.1 公共工具网关（autodokit.tools.gateway）

用途：提供 AOK 公共工具分级清单的统一读取接口，供 CLI、Agent 与 UI 查询。

公开入口：

- `读取公共工具清单(manifest_path=None) -> dict[str, Any]`
  - 读取 manifest 原始字典。
- `列出公共工具(exposure=None, kind=None, manifest_path=None) -> list[公共工具条目]`
  - 按暴露等级或工具类型过滤条目。
- `获取公共工具(tool_id, manifest_path=None) -> 公共工具条目 | None`
  - 按唯一标识获取单条工具记录。

Manifest 路径：

- `autodokit/tools/gateway/public_tools_manifest.json`

字段约定（初版）：

- `tool_id`：工具唯一标识
- `kind`：`python-symbol` 或 `script-entrypoint`
- `exposure`：`public-read` / `public-safe` / `internal`
- `module`：模块路径
- `symbol`：Python 符号名（脚本型可为空）
- `entrypoint`：脚本入口相对路径（函数型可为空）
- `summary`：用途说明
- `side_effect`：副作用说明
- `audit_mode`：审计方式说明

## 2.2 AOB 迁移入口（scripts/aob_tools）

用途：承接从 AOB 收敛到 AOK 的脚本型工具主入口。

当前主入口：

- `scripts/aob_tools/aoc.py`
- `scripts/aob_tools/deploy.py`
- `scripts/aob_tools/library.py`
- `scripts/aob_tools/regression_opencode_deploy_check.py`

路径解析约定：

- 默认优先使用同级 `autodo-lib` 作为 AOB 仓库根目录；
- 可通过环境变量 `AOB_REPO_ROOT` 覆盖；
- 相关脚本支持通过 `--repo-root` 显式传入。

## 2.3 文献数据库管理工具（autodokit.tools.bibliodb）

用途：提供文献数据库的基础管理能力，供业务事务直接调用。

核心接口：

- `init_empty_table(columns=None)`：初始化空文献数据库表。
- `generate_uid(first_author, year_int, title_norm, prefix=None)`：生成文献唯一标识 `uid`。
- `clean_title_text(title)`：生成 `clean_title`。
- `find_match(table, first_author, year, title, top_n=5)`：返回候选匹配列表。
- `upsert_record(table, bib_entry, source='imported', overwrite=False)`：插入或更新记录。
- `create_placeholder(table, first_author, year, title, clean_title, source='placeholder', extra=None)`：创建占位引文。
- `parse_reference_text(reference_text)`：从单条参考文献文本启发式提取 `first_author/year/title/clean_title`。
- `insert_placeholder_from_reference(table, reference_text, source='placeholder_from_reading', top_n=5, extra=None)`：执行“匹配已存在记录，否则插入占位引文”的一体化流程。
- `update_pdf_status(table, uid, has_pdf, pdf_path='')`：更新原文状态（`是否有原文`、`pdf_path`）。

字段约定（文献主表）：

- 标识：`uid`（唯一标识）、`id`（行号索引）
- 文本：`title`、`clean_title`、`title_norm`、`abstract_norm`
- 作者年份：`first_author`、`year`、`year_int`
- 管理：`is_placeholder`、`source`、`is_indexed`
- 原文：`是否有原文`、`pdf_path`

说明：`导入和预处理文献元数据` 事务会写出上述核心字段，并将 CSV 行索引列命名为 `id`。

补充说明：占位引文与标准引文共享同一套稳定 uid 生成规则。是否为占位引文由 `is_placeholder` 字段标识。

## 3. 事务模块契约

每个事务目录仅保留：

- affair.py：事务执行主体
- affair.json：纯业务参数模板
- affair.md：说明文档（用途、场景、参数、输出、示例）

事务目录应保持“业务三件套纯粹化”。事务管理所需 runner/node/governance 等元数据由事务管理系统数据库统一承载。

### 3.1 Skill渲染（`autodokit.affairs.Skill渲染.affair`）

用途：渲染指定 `SKILL.md` 并将结构化结果写入固定 JSON 文件。

公开入口：

- `execute(config_path: Path) -> list[Path]`
  - 从配置读取 `skill_path`、`params`、`output_dir`。
  - `params` 缺省时按 `{}` 处理。
  - 输出文件名固定为 `skill_render_result.json`。
- `render_skill(skill_path: str | Path, params: dict[str, Any]) -> dict[str, Any]`
  - 直接调用引擎侧 `SkillRenderer` 渲染单个 Skill 文件。
  - 返回结果字典包含 `status`、`mode`、`prompt`、`meta`、`skill_name`、`skill_path`。

配置字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `skill_path` | `str` | 是 | `SKILL.md` 的绝对路径。 |
| `params` | `dict[str, Any]` | 否 | 渲染参数字典；缺省按 `{}` 处理。 |
| `output_dir` | `str` | 否 | 输出目录绝对路径；为空时回退到 `config_path.parent`。 |

异常：

- `RuntimeError`：环境中缺少 `SkillRenderer`。
- `FileNotFoundError`：`skill_path` 指向的文件不存在。
- `ValueError`：`skill_path` 为空或不是绝对路径，或 `params` 不是字典，或 `output_dir` 不是绝对路径。

最小示例：

```python
from pathlib import Path
from autodokit.affairs.Skill渲染.affair import execute

outputs = execute(Path(r"D:/my_workspace/configs/skill_render.json").resolve())
print(outputs)
```

## 4. 不再由本仓提供的接口

以下接口已拆分到 autodo-engine：

- 流程图加载与注册
- 任务创建与推进
- taskdb / 决策 / 审计视图
- CLI 子命令
