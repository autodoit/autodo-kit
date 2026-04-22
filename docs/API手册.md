# API手册

autodo-kit 对外公开的是“事务内容 + 事务工具 + 本地运行时 API”。默认由 autodo-kit 内置运行时执行事务；如安装 autodo-engine，可继续接入其高级调度能力。

## 0. 全量索引与文档边界

为避免“能力存在但手册里不容易定位”，本手册采用如下检索边界：

1. 事务逐项详解（全量索引 + 每事务字段表 + 示例）以 `docs/AOK预置事务手册.md` 为准。
2. 本文档聚焦“公开 API 契约与高频能力”，并补充关键模块的调用示例。
3. 用户公开工具清单以 `autodokit.tools.list_user_tools()` 为真相源。
4. 开发者工具清单以 `autodokit.tools.list_developer_tools()` 为真相源。

推荐先执行：

```powershell
python scripts/generate_affair_manual.py
python -c "import autodokit.tools as t; print('user_tools=', len(t.list_user_tools())); print('developer_tools=', len(t.list_developer_tools()))"
```

说明：`autodokit/affairs` 中若仅有 `affair.py` 而缺少 `affair.json`，默认不纳入正式可配置事务索引。

## 0. A080-A105 普通文献阅读状态契约

当前普通文献阅读主链的正式节点顺序是：A080 -> A090 -> A095 -> A100 -> A105。

状态真相源统一为 `literature_reading_state`：

1. A070 或上游综述链直接把普通文献候选写入 `pending_preprocess=1`。
2. A080/A090/A095/A100/A105 的正式当前态真相源统一为 `literature_reading_state`。

这条链显式区分 `待读` 与 `正读`：

- `pending_rough_read` / `pending_deep_read` 表示待进入下一轮处理。
- `in_rough_read` / `in_deep_read` 表示当前这一轮已被节点接管、正在处理。

### 0.1 中文清单名 <-> 英文字段名 <-> 节点读写表

| 中文清单名/状态 | 英文字段名 | 读节点 | 写节点 | 说明 |
| --- | --- | --- | --- | --- |
| 待预处理清单 | `pending_preprocess` | A080 | A070 入口灌入、A090、A100 | 新候选或尚未预处理的普通文献。 |
| 已预处理清单 | `preprocessed` | - | A080 | 已完成解析资产补齐与标准笔记骨架准备。 |
| 待泛读清单 | `pending_rough_read` | A090 | A080 | 等待下一轮进入泛读。 |
| 正泛读清单 | `in_rough_read` | - | A090 | 当前轮已被 A090 接管。 |
| 已泛读清单 | `rough_read_done` | A095 | A090 | 已完成逐篇泛读。 |
| 待研读清单 | `pending_deep_read` | A100 | A090 | 等待下一轮进入深读资产准备。 |
| 正研读清单 | `in_deep_read` | - | A100 | 当前轮已被 A100 接管。 |
| 已研读清单 | `deep_read_done` | A105 | A105 | 已完成至少一轮批判性研读并收口。 |
| 研读次数 | `deep_read_count` | A105 | A105 | 每完成一轮批判性研读加 1。 |
| 轻量分析已同步 | `analysis_light_synced` | - | A090 | 五类分析笔记已完成轻量补写。 |
| 批次分析已同步 | `analysis_batch_synced` | A095 | A095 | 当前条目已进入 A095 批次汇总。 |
| 正式分析已同步 | `analysis_formal_synced` | - | A105 | 五类分析笔记已完成正式修订。 |
| 创新点已同步 | `innovation_synced` | - | A105 | 创新点笔记已完成更新。 |
| 条目来源类型 | `source_origin` | A080/A090/A100 | A080 | 标记 `human`/`auto`/`legacy_queue`/`recovery`。 |
| 阅读目标 | `reading_objective` | A090/A100 | A080 | 逐文献的阅读目标说明。 |
| 用户提示语 | `manual_guidance` | A090/A100 | A080 | 逐文献阅读指令，用于影响粗读/深读输出。 |

### 0.2 当前实现流程

1. A080 读取 `pending_preprocess=1`，成功后写 `preprocessed=1` 和 `pending_rough_read=1`。
2. A090 先把当前条目从 `pending_rough_read=1` 迁到 `in_rough_read=1`，处理完成后写 `rough_read_done=1`，并按条件写 `pending_deep_read=1`。
3. A095 只消费 `rough_read_done=1 AND analysis_batch_synced=0`，不直接做单篇筛选。
4. A100 先把当前条目从 `pending_deep_read=1` 迁到 `in_deep_read=1`，处理完成后写 `deep_read_decision=parse_ready`。
5. A105 读取 `deep_read_decision=parse_ready`，完成批判性研读后写 `deep_read_done=1` 和 `deep_read_count += 1`。
6. A090 与 A100 都允许发现新候选，但不再一律回写到 `pending_preprocess=1`。
6. 若新候选已完成预处理（`preprocessed=1`），则直接进入 `pending_rough_read=1`。
7. 若新候选尚未完成预处理，则进入 `pending_preprocess=1`。
8. 若新候选已经 `rough_read_done=1`，则不再重复回到待泛读清单。

### 0.3 human_seed_contract（A080/A090/A100 共用）

为什么 A080/A090/A100 都允许写 `seed_items`：

1. 统一契约：三个节点读取同一配置结构，便于同一批 seed 在不同轮次复用，不需要按节点维护三套格式。
2. 人工纠偏：真实运行中人工干预常发生在中途；允许在 A090/A100 继续补 seed，可避免“必须回到 A080 才能加单”的流程阻塞。
3. 职责不变：虽然都可写，但节点仍按状态机消费；A080 只做预处理落位，A090 只做泛读，A100 只做深读，不会越权。
4. 审计一致：`source_origin`、`manual_guidance`、`reading_objective` 在同一状态表回写，便于追溯“谁在何阶段加了什么种子”。

建议在事务配置中统一提供以下结构：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `human_seed_contract.enabled` | bool | 是否启用人工 seed。 |
| `human_seed_contract.default_target_stage` | string | 默认目标阶段，`rough_read` 或 `deep_read`。 |
| `human_seed_contract.on_ambiguous` | string | cite_key 命中多条时策略，建议 `manual_review`。 |
| `human_seed_contract.on_missing` | string | cite_key 未命中时策略，建议 `route_to_a040`。 |
| `human_seed_contract.manual_guidance` | string | 全局默认提示语，可被条目覆盖。 |
| `human_seed_contract.reading_objective` | string | 全局默认阅读目标，可被条目覆盖。 |
| `human_seed_contract.seed_items` | array | 人工 seed 条目数组。 |

`seed_items` 单条建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `cite_key` | string | 目标文献引用键。 |
| `target_stage` | string | `rough_read` 或 `deep_read`。 |
| `manual_guidance` | string | 该文献的个性化阅读提示语。 |
| `reading_objective` | string | 该文献的个性化阅读目标。 |
| `priority` | number | 可选优先级。 |
| `tags` | array of strings | 可选标签，例如 `method_transfer`。 |

科学学科（Science of Science）示例模板：

```json
{
  "human_seed_contract": {
    "enabled": true,
    "default_target_stage": "rough_read",
    "on_ambiguous": "manual_review",
    "on_missing": "route_to_a040",
    "manual_guidance": "优先抽取研究问题、识别策略与可迁移的方法线索。",
    "reading_objective": "围绕科研产出、合作网络与资助机制构建可复用证据链。",
    "seed_items": [
      {
        "cite_key": "wang-2021-funding-and-team-science",
        "target_stage": "deep_read",
        "manual_guidance": "重点读识别策略与内生性处理，判断能否迁移到当前课题。",
        "reading_objective": "提炼资助政策影响科研合作产出的可检验机制。",
        "priority": 95,
        "tags": ["method_transfer", "identification", "mechanism_focus"]
      },
      {
        "cite_key": "liu-2019-citation-network-dynamics",
        "target_stage": "rough_read",
        "manual_guidance": "先看网络构建口径与数据清洗流程，记录可复用字段定义。",
        "reading_objective": "补齐引文网络指标构造与预处理步骤。",
        "priority": 80,
        "tags": ["data_cleaning", "empirical_reference", "network_metrics"]
      },
      {
        "cite_key": "chen-2023-ai-and-scientific-discovery",
        "target_stage": "rough_read",
        "manual_guidance": "关注 AI 工具介入科研发现流程的证据类型与边界条件。",
        "reading_objective": "为创新点池提供可讨论的机制假说。",
        "priority": 70,
        "tags": ["innovation_support", "hypothesis_generation"]
      }
    ]
  }
}
```

## 1. 桥接入口

### 1.1 autodokit.run_affair(...)

用途：通过 autodo-kit 内置运行时执行官方事务或用户覆盖事务。

典型参数：

- 候选文献视图构建事务
- 综述研读与研究地图生成事务
- 研究脉络梳理事务
- 创新点池构建事务
- 创新点可行性验证事务
### 1.2 autodokit.prepare_affair_config(...)

用途：调用 autodokit.tools 的统一路径预处理逻辑，对事务配置中的路径字段做绝对化。

补充说明：

- 候选与阅读相关事务不再依赖 `review_candidate_current_view`、`review_read_pool_current_view`、`review_priority_current_view` 这类旧 SQLite current view 作为运行时真相源。
- 新项目默认不再使用 `literature_reading_queue` 作为综述链到普通文献链的入口；普通文献阅读主链 A080-A105 统一以 `literature_reading_state` 为正式真相源。
- CSV 与 Markdown 导出物用于审计、人工阅读与兼容迁移，不作为 A080-A100 的正式当前态来源。

### 1.4 autodokit.import_user_affair(...)

用途：将用户功能程序导入为事务三件套目录（`affair.py`、`affair.json`、`affair.md`），并自动写入 `.autodokit/affair_registry.json`。名称冲突时自动追加 `_v正整数`。

### 1.5 autodokit.bootstrap_runtime(...)

用途：初始化本地运行时目录与注册表。

默认创建：

- `.autodokit/affairs/`
- `.autodokit/graphs/`
- `.autodokit/affair_registry.json`
- `.autodokit/graph_registry.json`

### 1.6 autodokit.register_graph(...)

用途：注册图配置到 `.autodokit/graphs/`，并写入图注册表。

典型参数：

- `graph_uid`
- `graph` 或 `graph_path`（二选一）
- `workspace_root`
- `overwrite`

### 1.7 autodokit.load_graph(...)

用途：按 `graph_uid` 从本地图注册表加载图配置，或直接按 `graph_path` 读取。

### 1.8 autodokit.tools.workspace_path_migration.migrate_workspace_paths(...)

用途：在工作区迁移到新设备或新目录后，统一扫描并重写旧绝对路径。

典型参数：

- `workspace_root`：目标工作区根目录。
- `mappings`：路径映射列表，元素为 `PathMapping(old_root, new_root)`。
- `dry_run`：是否只预览不写入。
- `inventory_only`：是否仅扫描并输出命中清单。
- `scan_dirs`：需要扫描的工作区目录（默认包括 `config`、`steps`、`knowledge`、`views`、`batches`）。
- `sqlite_rel_paths`：需要处理的 SQLite 相对路径（默认包括 `database/content/content.db`、`database/logs/aok_log.db`、`database/tasks/tasks.db`）。
- `excluded_prefixes`：默认排除前缀之外的额外排除项。

相关结构：

- `PathMapping(old_root, new_root)`：路径映射配置。

行为说明：

- `inventory_only=True` 时只输出命中路径清单，不做写入。
- 默认会排除 `.copilot`、`C:/Windows`、`C:/Program Files` 以及外部盘前缀，减少误改风险。
- 工具会遍历 JSON、CSV、文本文件以及 SQLite 的文本列，匹配命中的旧绝对路径并按映射替换。
- 对于不在映射前缀内的外部路径，默认保持不变。

推荐调用示例：

```python
from autodokit.tools import PathMapping, migrate_workspace_paths

result = migrate_workspace_paths(
  workspace_root=r"D:/Research/workspace",
  mappings=[
    PathMapping(
      old_root=r"C:/Users/Ethan/CoreFiles/ProjectsFile/AcademicResearch-auto-workflow/workspace",
      new_root=r"D:/Research/workspace",
    ),
    PathMapping(
      old_root=r"C:/Users/Ethan/CoreFiles/ProjectsFile/AcademicResearch-auto-workflow",
      new_root=r"D:/Research",
    ),
  ],
  inventory_only=True,
)
```

### 1.9 autodokit.tools.run_online_retrieval_from_bib(...)

用途：根据 Bib 文件批量执行在线检索四项任务，并把中文/英文检索、下载、HTML 结构化抽取结果汇总到输出目录。

典型参数：

- `bib_path`：Bib 文件路径。
- `output_dir`：批处理输出目录。
- `max_pages`：中英文检索最大翻页数。
- `en_per_page`：英文检索每页返回条数。
- `en_sources`：英文来源列表。
- `max_entries`：可选，仅处理前 N 条 Bib 记录。
- `use_llm_matching`：是否启用阿里百炼小模型做英文候选匹配。
- `llm_api_key_file`：百炼 API Key 文件路径。

说明：

- 该工具属于通用批处理工具，不隶属于 `online_retrieval_literatures/` 目录。
- 工具内部仍然通过 `run_online_retrieval_router(...)` 进入在线检索三层结构，保持路由统一入口不变。

### 1.10 在线检索文献模块的结构口径

在线检索文献模块统一收敛到 `autodokit/tools/online_retrieval_literatures/`，公开调用仍只走 `run_online_retrieval_router(...)`。

当前建议按以下三层理解：

1. 请求画像层：`profiles/request_profile.py`，负责区分中文、英文、中英文不限。
2. 路由层：`router/route_entry.py` 与 `online_retrieval_router.py`，负责入口治理与策略分发。
3. 编排层：`orchestrators/*.py`、`policies/*.py`、`catalogs/*.py`，负责输入归一化、来源发现、来源选择、重试与批量组织。
4. 执行层：`executors/*.py` 与各 `zh_cnki_*`、`en_open_access_*`、`content_portal_spis.py`，负责单篇 metadata、download、structured extract。

用户不应直接调用的内部文件包括但不限于：

1. `online_retrieval_resolver.py`：输入归一化与兼容回退。
2. `online_retrieval_service.py`：路由分发与编排壳。
3. `school_foreign_database_portal.py`：学校数据库导航门户适配。
4. `en_chaoxing_portal_retry.py`：英文失败项学校门户重试。

### 1.11 A040 检索治理事务的特殊渠道参数

A040 的正式事务入口是 `autodokit.affairs.检索治理.affair.execute(...)`。当前特殊渠道不再通过独立 tools 模块承载，而是作为 A040 事务程序的参数分支执行。

常用参数：

- `enable_special_channel`：是否启用特殊渠道分支。
- `special_channel_mode`：特殊渠道模式，当前使用 `en_special_download` 或 `en_open_access_special`。
- `special_channel.cite_keys` / `special_channel.cite_keys_file`：限定处理的 cite_key。
- `special_channel.skip_existing`：是否跳过已具备 fulltext / pdf_path / primary_attachment_source_path / primary link 的条目。
- `attachments_target_dir`：成功下载后附件落盘目录，默认 `workspace/references/attachments`。
- `school_library_nav_url` / `library_nav_url` / `portal_url`：学校门户重试入口。

命名与回写口径：

1. 下载成功后，PDF 文件名统一为 `att-<cite_key>-<uid_attachment>.pdf`。
2. 下载后的内容主库更新应复用 A020 同源的 `bibliodb_sqlite.replace_reference_tables_only(...)` 链路。
3. 附件事实层以 `attachments` + `literature_attachment_links` 为准；`literature_attachments` 仅保留兼容投影。
4. A040 事务智能体应直接调用 A040 affair 程序，由事务程序根据参数走常规流程或特殊流程。
5. `executors/content_portal_cnki.py`、`executors/content_portal_spis.py`、`executors/open_platform.py`、`executors/navigation_portal.py`：执行层内部实现。

开发说明或排障记录中，建议优先引用 `docs/在线检索文献模块专题.md`，再补具体文件名，避免只说“在线检索模块”而不说清楚层级边界。

## 2. autodokit.tools 导出

`autodokit.tools` 采用“按函数直接调用”的公开方式，并按对象分为用户 API 与开发者 API。

### 2.1 面向用户 API

用途：提供可直接导入的稳定工具函数，便于 IDE 自动补全与形参提示。

推荐入口：

- `from autodokit.tools import <tool_name>`
- `list_user_tools() -> list[str]`：用户公开工具清单。

当前典型工具：

- `parse_reference_text(reference_text)`
- `insert_placeholder_from_reference(table, reference_text, ...)`
- `task_create_or_update(tasks, task, ...)`

建议先用以下函数做“可用能力发现”：

- `list_user_tools() -> list[str]`
- `list_developer_tools() -> list[str]`
- `get_tool(tool_name, scope='user'|'developer'|'all')`

### 2.1.1 LaTeX 子文件合并与 Word 转换能力

能力位置（5 个原子模块）：

- `autodokit.tools.latex_subfile_merger`
- `autodokit.tools.pandoc_runner`
- `autodokit.tools.latex_to_word`
- `autodokit.tools.word_to_latex`
- `autodokit.tools.docx_postprocess`

兼容入口（保留历史导入路径）：`autodokit.tools.pandoc_tex_word_converter`

#### 2.1.1.1 `autodokit.tools.latex_subfile_merger`

用途：递归展开 `\subfile{...}` 并合并为单个 tex 文件。

公开函数：

- `merge_latex_subfiles(main_tex_path, output_tex_path)`：读取主 tex，递归展开子文件，返回合并输出路径与日志列表。

#### 2.1.1.2 `autodokit.tools.pandoc_runner`

用途：统一封装 Pandoc 子进程执行与结果回传。

公开函数：

- `run_pandoc(command)`：执行 Pandoc 命令并返回 `PandocResult`，包含命令、返回码、标准输出与标准错误。

#### 2.1.1.3 `autodokit.tools.latex_to_word`

用途：将 tex 文档转换为 docx 文档。

公开函数：

- `convert_latex_to_word(input_tex_path, output_docx_path, ...)`：支持 `resource_path`、`resource_paths`、`include_in_header`、`reference_doc` 与 `toc`。

#### 2.1.1.4 `autodokit.tools.word_to_latex`

用途：将 doc/docx 文档转换为 tex 文档。

公开函数：

- `convert_word_to_latex(input_word_path, output_tex_path, ...)`：支持 `include_in_header` 与 `latex_template`。
- `DEFAULT_XELATEX_LATEX_TEMPLATE`：内置 XeLaTeX 默认模板。
- `PANDOC_TABLE_SUPPORT_MARKER` 与 `PANDOC_TABLE_SUPPORT_BLOCK`：Pandoc 表格补丁标记与补丁块。

内部辅助：

- `_needs_pandoc_table_support(tex_text)`：判断输出 tex 是否需要补表格支持。
- `_ensure_pandoc_latex_table_support(output_tex_path)`：在必要时把表格支持块插入到 tex 中。

#### 2.1.1.5 `autodokit.tools.docx_postprocess`

用途：对 docx 做标题编号与内容高亮后处理。

公开函数：

- `add_heading_numbering(input_docx_path, output_docx_path)`：为 Heading 1-9 添加文本编号。
- `highlight_tokens_in_docx(input_docx_path, output_docx_path)`：对 `【TODO】`、`【NOTE】`、`【文献】` 片段做标色。

事务入口：

- `autodokit.affairs.LaTeX转Word.affair.execute(config_path)`
- 若配置 `merge_subfiles=true`，事务会先调用 `merge_latex_subfiles(...)` 再做 Pandoc 转换。

最小示例（仅合并 subfiles）：

```python
from pathlib import Path
from autodokit.tools.pandoc_tex_word_converter import merge_latex_subfiles

out_tex, logs = merge_latex_subfiles(
  Path(r"D:/workspace/paper/main.tex"),
  Path(r"D:/workspace/paper/main_merged.tex"),
)
print(out_tex)
print("log_count=", len(logs))
```

### 2.2 MonkeyOCR Windows GPU 解析工具

本仓库把 Windows 原生 MonkeyOCR 单篇解析封装成两个可直接导入的工具函数：

```python
from autodokit.tools import prepare_monkeyocr_windows_runtime
from autodokit.tools import run_monkeyocr_windows_single_pdf
```

#### `prepare_monkeyocr_windows_runtime(...)`

用途：准备 Windows 原生运行时，包括安装 `huggingface_hub`、可选安装 `modelscope`、安装 `triton-windows<3.4`，并下载 MonkeyOCR 模型权重。

典型参数：

- `monkeyocr_root`：MonkeyOCR 仓库根目录。
- `model_name`：模型名称，默认 `MonkeyOCR-pro-1.2B`。
- `download_source`：`huggingface` 或 `modelscope`。
- `python_executable`：Python 可执行文件路径，默认当前解释器。
- `pip_index_url`：可选 pip 镜像地址。
- `install_triton_windows`：是否安装 `triton-windows<3.4`。
- `models_dir`：可选权重目录；若不传，默认使用 `monkeyocr_root/model_weight`。

返回值要点：

- `model_dir`：最终权重目录。
- `official_model_dir`：官方下载目标目录。
- `weights_ready`：是否已准备好三类关键权重目录。
- `steps`：执行过的准备步骤。

#### `run_monkeyocr_windows_single_pdf(...)`

用途：在 Windows 上以 GPU 路线解析单篇 PDF，并把实时日志与产物返回给调用方。

典型参数：

- `input_pdf`：待解析 PDF 绝对路径。
- `output_dir`：输出根目录。
- `monkeyocr_root`：MonkeyOCR 仓库根目录。
- `models_dir`：权重目录，默认使用 `monkeyocr_root/model_weight`。
- `config_path`：本地配置文件路径，默认使用 `output_dir.parent/model_configs.local.yaml`。
- `device`：`cuda`、`cpu` 或 `mps`，本次成功解析使用 `cuda`。
- `gpu_visible_devices`：CUDA 可见设备号，默认 `0`。
- `ensure_runtime`：是否自动执行运行时准备步骤。
- `download_source`：权重下载源，默认 `huggingface`。
- `pip_index_url`：可选 pip 镜像地址。
- `log_path`：实时日志输出文件。
- `stream_output`：是否在终端实时打印解析日志。

返回值要点：

- `status`：运行状态，成功时为 `SUCCEEDED`。
- `device`：实际使用的设备。
- `gpu_name`：识别到的 GPU 名称。
- `model_name`：模型名称。
- `input_pdf`：输入 PDF 的绝对路径。
- `output_dir`：最终输出目录。
- `artifacts`：产物字典，包含 markdown、content_list、middle_json、可视化 PDF、images 目录、日志与配置文件。

示例：

```python
from pathlib import Path
from autodokit.tools import run_monkeyocr_windows_single_pdf

result = run_monkeyocr_windows_single_pdf(
  input_pdf=Path(r"D:\workspace\sandbox\test monkey ocr\input\“双支柱”调控与银行系统性风险——基于SRISK指标的实证分析.pdf"),
  output_dir=Path(r"D:\workspace\sandbox\test monkey ocr\output"),
  monkeyocr_root=Path(r"D:\workspace\sandbox\MonkeyOCR-main"),
  models_dir=Path(r"D:\workspace\sandbox\test monkey ocr\model_weight"),
  config_path=Path(r"D:\workspace\sandbox\test monkey ocr\model_configs.local.yaml"),
  log_path=Path(r"D:\workspace\sandbox\test monkey ocr\parse_direct_run.log"),
  device="cuda",
  gpu_visible_devices="0",
  ensure_runtime=False,
)
```

### 2.3 输出文件契约

MonkeyOCR 单篇解析的输出契约建议统一如下：

- `*.md`：面向人工阅读的最终解析文本。
- `*_content_list.json`：适合程序消费的内容元素列表。
- `*_middle.json`：中间层结构结果，适合排错与二次加工。
- `*_model.pdf`、`*_layout.pdf`、`*_spans.pdf`：三类可视化核查文件。
- `images/`：页面图片缓存。
- `model_configs.local.yaml`：本次运行的配置快照。
- `parse_direct_run.log`：实时日志文件。

在其他 Windows 11 设备上复现时，建议优先复用这套参数组合：`device=cuda`、`gpu_visible_devices=0`、`triton-windows<3.4`、`MonkeyOCR-pro-1.2B`，并把 `models_dir` 指向本机权重目录。

### 2.4 TeX DAG 管理工具

用于扫描论文仓库中的 TeX 引用关系，并安全更新 `\subfile`、`\input`、`\include` 和 `\documentclass[...]{subfiles}`。

推荐导入方式：

```python
from autodokit.tools import export_tex_graph, rewire_tex_reference, scan_tex_graph, set_tex_root
```

#### `scan_tex_graph(root_dir='.', exclude_glob=None)`

用途：扫描整个根目录下的 `.tex` 文件，返回引用图对象。

返回值：`TexGraph`。

#### `export_tex_graph(root_dir='.', format='text', output=None, exclude_glob=None)`

用途：导出引用图为 `text`、`json`、`mermaid` 或 `dot`。

如果传了 `output`，会直接写入文件；否则返回图对象，便于程序侧继续分析。

#### `rewire_tex_reference(...)`

用途：把父文件里的旧子节点引用切换到新子节点，并可选同步更新新子树的 `subfiles` 根引用。

常用参数：

- `root_dir`：论文仓库根目录。
- `parent`：父文件路径。
- `old_target`：旧子文件路径。
- `new_target`：新子文件路径。
- `sync_root`：是否同步更新新子文件的根引用。
- `recursive`：是否递归更新新子树的根引用。
- `dry_run`：是否只预演不写回。

#### `set_tex_root(...)`

用途：直接为某个子文件或子树重设 `subfiles` 根文件。

常用参数：

- `root_dir`：论文仓库根目录。
- `file`：目标子文件。
- `root`：新的主根文件。
- `recursive`：是否递归更新整个子树。
- `dry_run`：是否只预演不写回。

#### CLI 薄入口

安装后可直接使用：

```powershell
manage-tex-dag --help
```

或者在仓库内运行：

```powershell
python scripts/manage_tex_dag.py --help
```

命令分为三类：

1. `graph`：导出引用关系图。
2. `rewire`：重连父文件中的子文档引用。
3. `set-root`：更新子文件的 `subfiles` 根引用。
- `task_status_append(status_log, aok_task_uid, ...)`
- `task_gate_decision_record(gate_decisions, aok_task_uid, ...)`
- `task_handoff_record(handoffs, from_task_uid, to_task_uid, ...)`
- `task_relation_upsert(relations, source_task_uid, target_task_uid, ...)`
- `task_round_snapshot_register(round_views, aok_task_uid, ...)`
- `task_release_register(releases, aok_task_uid, ...)`
- `task_release_promote(releases, aok_task_uid, release_uid, ...)`
- `task_literature_binding_register(bindings, aok_task_uid, uid_literature, ...)`
- `task_knowledge_binding_register(bindings, aok_task_uid, uid_knowledge, ...)`
- `task_bind_literatures(tasks, aok_task_uid, literature_uids, ...)`
- `task_bind_knowledges(tasks, aok_task_uid, knowledge_uids, ...)`
- `task_artifact_register(tasks, artifacts, aok_task_uid, ...)`
- `task_bundle_export(artifacts, aok_task_uid, output_dir)`
- `task_get(tasks, artifacts, aok_task_uid)`
- `get_current_time_iso(timezone_name='Asia/Shanghai')`
- `convert_timestamp_to_timezone(timestamp, target_timezone='Asia/Shanghai', ...)`
- `rewrite_obsidian_note_timestamps(note_path, target_timezone='Asia/Shanghai', ...)`
- `batch_rewrite_obsidian_note_timestamps(note_paths=None, note_dir=None, target_timezone='Asia/Shanghai', ...)`
 - `build_cnki_result(...)`
 - `local_reference_lookup_and_materialize(...)`：本地参考文献清单检索与占位补录工具。
- `match_reference_citation_record(...)`：原子能力，按作者/年份/标题在文献主表中匹配候选记录。
- `upsert_reference_citation_placeholder(...)`：原子能力，插入或复用占位引文记录。
- `writeback_reference_citation_record(...)`：原子能力，把单条引文记录写回文献主表。
- `generate_reference_cite_key(...)`：原子能力，生成稳定 `cite_key`。
- `ensure_reference_citation_cite_key(...)`：原子能力，确保记录具备 `cite_key`（必要时写回）。
- `process_reference_citation(...)`：组合能力，内部串联“解析/匹配/占位/写回/生成引文”。
- `run_online_retrieval_from_bib(...)`：按 Bib 批量触发在线检索四项任务的通用工具。
  用途：把一段参考文献清单文本解析为单条引文，逐条在本地 `content.db` 的 `literatures` 表中做匹配；未命中时插入占位条目并写回数据库。

  函数签名（概要）：

  ```python
  from pathlib import Path
  from autodokit.tools import local_reference_lookup_and_materialize

  result = local_reference_lookup_and_materialize(
    content_db_path=Path("workspace/database/content/content.db"),
    reference_list_text=your_reference_text,
    workspace_root=Path("."),
    top_n=5,
    placeholder_source="placeholder_from_local_reference_lookup",
    print_to_stdout=False,
  )
  ```

  主要参数：
  - `content_db_path`：`str|Path`，目标内容主库（支持历史别名路径）。
  - `reference_list_text`：`str`，一段包含多条参考文献的文本（整段全文）。
  - `workspace_root`：`str|Path`，可选，工作区根目录；为空时将从 `content.db` 推断。
  - `top_n`：`int`，本地匹配候选上限。
  - `placeholder_source`：`str`，写入占位条目的 `source` 字段值。
  - `print_to_stdout`：`bool`，是否把结果打印到终端。

  返回值（字典，示例字段）：
  - `matched_view`：命中记录的视图列表。
  - `placeholder_view`：为未命中条目创建的占位条目列表。
  - `all_rows`：每条输入条目的处理详情数组（包含识别字段、匹配 UID、动作等）。
  - `summary`：质量汇总统计（命中数、占位数、写回行数等）。

  说明：该工具复用 `autodokit.tools.reference_citation_tools` 的原子链路（匹配/占位/写回/生成引文）；默认不会调用在线检索；占位条目会带有 `online_lookup_status: pending` 以便后续在线补全。
- `build_candidate_view_index(records, source_round=..., source_affair=...)`
- `build_candidate_readable_view(index_table, literature_table, ...)`
- `extract_review_candidates(readable_table)`
- `allocate_reading_batches(index_table, ...)`
- `build_research_trajectory(items, topic=...)`
- `build_gate_review(node_uid=..., node_name=..., summary=...)`
- `score_gate_review(review, ...)`
- `merge_human_gate_decision(review, human_decision=..., ...)`
- `innovation_pool_upsert(pool_table, innovation_item, ...)`
- `innovation_feasibility_score(innovation_item)`
- `ensure_absolute_output_dir(...)`
- `write_affair_json_result(...)`
- `resolve_model_plan(intent, ...)`
- `invoke_aliyun_llm(prompt=..., intent=..., ...)`

大模型统一路由说明（P1 起生效）：

- `resolve_model_plan(...)`：根据任务语义、质量/成本/时延/风险档位输出主模型与回退链。
- `invoke_aliyun_llm(...)`：按路由计划执行主模型调用，失败时按回退链重试，并返回统一 `attempts` 审计结构。
- `load_aliyun_llm_config(...)`：在 `model=auto/smart` 时内部走统一路由，不建议业务层自行实现选模分支。

### 2.1.1 在线检索文献模块

在线检索文献能力已统一收口到 `autodokit.tools.online_retrieval_literatures` 目录，对外正式入口只有：

- `run_online_retrieval_router(payload)`

调用约束：

1. 用户侧不要直接调用 `zh_cnki_*`、`en_open_access_*`、`open_access_literature_retrieval` 等子模块。
2. 所有在线检索相关配置文件都应维护在 `autodokit/tools/online_retrieval_literatures/` 目录。
3. 默认规则配置文件是 `autodokit/tools/online_retrieval_literatures/config.json`，由 router 自动注入到下游执行器。
4. 若需要覆盖默认规则，只能通过 router payload 显式传入 `retrieval_rules`，不要在子模块里单独分叉。

三层结构（2026-04 起）：

1. 请求画像层：`profiles/request_profile.py`，负责区分中文、英文、中英文不限等约束。
2. 路由层：`online_retrieval_router.py` + `router/route_entry.py`，负责统一入口、规则注入和调度选择。
3. 编排层：`orchestrators/*.py` + `policies/*.py` + `catalogs/*.py`，负责把 `entries` / `records` / `seed_items` / `cite_keys` / `pdf_paths` 统一转换为可执行载荷，并完成来源发现、来源选择和 retry。
4. 执行层：`executors/*.py` + `zh_cnki_*` / `en_open_access_*` / `content_portal_spis.py`，负责实际检索、下载、抽取。

用户不应直接调用的内部实现文件包括但不限于：

1. `online_retrieval_resolver.py`
2. `online_retrieval_service.py`
3. `school_foreign_database_portal.py`
4. `en_chaoxing_portal_retry.py`
5. `open_access_literature_retrieval.py`

这些文件属于内部编排与执行实现，不是普通用户 API。

新增输入契约（兼容旧 payload）：

- `seed_items`: `list[dict]`，每项可含 `cite_key`、`pdf_path`、`title`、`detail_url`。
- `cite_keys`: `list[str]`，用于批量输入文献引用键。
- `pdf_paths`: `list[str]`，用于批量输入 PDF 绝对路径。
- `content_db` / `content_db_path`: `str`，可选；提供后会优先尝试从 `literatures` 表补齐 `title` / `pdf_path`。
- `workspace_root`: `str`，当未显式提供 `content_db` 时，编排层会尝试使用 `<workspace_root>/database/content/content.db`。

解析策略说明：

- `zh_cnki batch download/html_extract`：若未传 `entries`，会自动尝试由编排层把 `seed_items` / `cite_keys` / `pdf_paths` 解析生成。
- `zh_cnki single download/html_extract`：若未传 `zh_query`（或 `query`）且未传 `detail_url`，会自动从编排结果补齐首条候选。
- `en_open_access single/batch download`：若未传 `record`（或 `records`），会自动由种子输入构造最小 `record` 载荷。

典型场景：

- 中文 CNKI 题录检索
- 中文 CNKI 单篇/批量 PDF 下载
- 中文 CNKI 单篇/批量 HTML 抽取
- 英文开放源题录检索与全文下载
- 学校数据库导航与超星门户相关流程
- 本地 `cite_key`/PDF 清单驱动的在线补检索（先由编排层归一，再由执行层执行）

路由治理与回归补充（P5 起生效）：

- `scripts/check_aliyun_routing_compliance.py`：扫描事务与工具中的硬编码模型默认值。
- `tests/test_aliyun_routing_minimal.py`：最小回归，覆盖路由计划解析、`auto` 配置加载、工具统一调用入口接管。

### 2.2 面向开发者 API

用途：提供事务实现、调度桥接与运行期辅助能力，不作为普通用户主入口。

入口：

- `list_developer_tools() -> list[str]`：开发者工具清单。
- `get_tool(tool_name, scope='user'|'developer'|'all')`：按名称获取可调用对象。

开发侧常用能力示例：

- `load_json_or_py`
- `resolve_paths_to_absolute`
- `evaluate_expression`
- `append_flow_trace_event`
- `build_registry`
- `build_mainline_affair_entry_registry`
- `write_mainline_affair_entry_registry`
- `resolve_mainline_affair_entry`

说明：

- 用户与开发者统一通过 `autodokit.tools` 的函数导出清单调用工具。
- 工具参数与返回保持函数自然签名，不强制统一 payload 结构。

### 2.2.1 PDF 工具套件总览

当前 `autodokit.tools` 正式 PDF 主链只保留 MonkeyOCR。

边界约束：

- 正式事务只允许消费 MonkeyOCR 解析资产及其共享运行时。
- 历史实验入口与旧多模态入口都已退出公开导出，不应再作为生产调用面。
- `autodokit.tools.llm_clients` 仍是正式保留的通用 LLM 调用入口，但其职责限于翻译、辅助筛选、抽取、判别等非 PDF 任务，不再承担正式 PDF 解析/旧多模态后处理主链。
- 若需要追溯旧实现，只能到 `autodokit/tools/old/` 查看归档源码。

### 2.2.2 已归档的旧 PDF 解析接口

以下接口已经退出正式公开 API：

- 旧阿里百炼多模态单篇解析入口
- 旧阿里百炼多模态批量管理入口
- 旧阿里百炼多模态后处理门面

约束：

- 正式 API 只保留 MonkeyOCR 主链与其共享运行时。
- 旧接口源码已归档到 `autodokit/tools/old/`，仅用于历史审计，不再提供公开参数表、示例或接入承诺。
- llm_clients 模块本身未归档；归档的是其中旧 PDF 多模态后处理兼容门面所对应的历史实现。
- 事务、脚本和文档不得再把这些旧接口当作当前推荐入口。

### 2.2.3 AOK 日志数据库工具（autodokit.tools.atomic.log_aok）

用途：提供 AOK 运行日志的 SQLite 初始化、校验、写入、查询与修复能力；日志后端异常时保持业务侧“非阻塞”。

核心接口：

- `resolve_aok_log_db_path(workspace_root, config_path=None)`：解析最终日志数据库文件绝对路径；当 `config/config.json` 中提供 `paths.log_db_path` 时优先按该值解析（相对路径基于 `workspace_root`）。
- `bootstrap_aok_logdb(project_root='.', logs_db_root=None, log_db_path=None, enabled=True)`：初始化日志库与必要数据表。
- `validate_aok_logdb(project_root='.', logs_db_root=None, log_db_path=None, enabled=True)`：校验日志目录、数据库文件与表结构。
- `append_aok_log_event(...)`：追加常规事件日志。
- `record_aok_log_artifact(...)`：登记产物与事件关联。
- `record_aok_gate_review(...)`：登记 gate 审计意见。
- `record_aok_human_decision(...)`：登记人工决策。
- `list_aok_log_events(...)`：按条件查询事件日志。
- `repair_aok_logdb(project_root='.', logs_db_root=None, log_db_path=None, enabled=True, dry_run=False)`：修复“数据库文件路径被目录占用”等异常形态，必要时隔离错误目录后重建 schema。

状态语义：

- `PASS`：操作成功。
- `SKIPPED`：按配置禁用，或在写入阶段因日志后端不可用而降级跳过（`reason` 常见值：`logging_disabled`、`logdb_unavailable`、`logdb_write_failed`）。
- `BLOCKED`：日志路径形态异常或初始化/校验失败（`reason` 常见值：`invalid_logdb_path_shape`、`logdb_root_create_failed`、`sqlite_bootstrap_failed`）。

`bootstrap_aok_logdb` 返回字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | `str` | `PASS` / `SKIPPED` / `BLOCKED`。 |
| `reason` | `str` | 非 `PASS` 时的原因码。 |
| `logdb_root` | `str` | 日志目录绝对路径。 |
| `db_path` | `str` | 日志数据库文件绝对路径。 |
| `created_files` | `list[str]` | 本次新建文件列表。 |
| `created_tables` | `list[str]` | 本次确认存在/创建的数据表列表。 |
| `errors` | `list[str]` | `BLOCKED` 时的错误列表。 |
| `warnings` | `list[str]` | 警告列表。 |

`repair_aok_logdb` 返回字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | `str` | `PASS` / `SKIPPED` / `BLOCKED`。 |
| `actions` | `list[str]` | 修复动作列表（如 `quarantine_directory:源->目标`、`bootstrap_schema:PASS`）。 |
| `quarantined_paths` | `list[str]` | 被隔离的历史异常目录路径。 |
| `dry_run` | `bool` | 是否为演练模式。 |

示例（修复后再写日志）：

```python
from autodokit.tools import repair_aok_logdb, append_aok_log_event

repair_result = repair_aok_logdb(project_root=".")
if repair_result["status"] == "PASS":
  append_aok_log_event(
    project_root=".",
    event_type="step.completed",
    handler_kind="local_script",
    handler_name="run_items_sync.py",
    payload={"status": "ok"},
  )
```

## 2.2.4 AOK 全局日志配置（config）

建议在 `workspace/config/config.json` 中提供最小 `logging` 配置：

```json
{
  "logging": {
    "enabled": true,
    "snapshot_mode": "log_only"
  },
  "paths": {
    "log_db_path": "workspace/database/logs/aok_log.db",
    "runtime_dir": "workspace/runtime",
    "logs_dir": "workspace/logs"
  }
}
```

`logging.snapshot_mode` 可选值与含义：

- `"log_only"`：仅写入结构化 SQLite 日志，不保存运行时快照（默认）。
- `"log_and_snapshot"`：写入 SQLite 日志并同时保存运行时快照到 `runtime_dir`（用于故障复现、审计与局部回放）。

注意：`runtime_dir` 仅在 `snapshot_mode` 为 `log_and_snapshot` 且 `logging.enabled=true` 时被创建与写入。

## 2.3 AOB 工具统一执行 API（autodokit.tools.aob_tools）

用途：将 AOB 历史执行能力统一收敛到 `autodokit.tools`，脚本层仅做参数组织与调用。

核心接口：

- `run_aob_aoc(argv=None)`
- `run_aob_deploy(argv=None)`
- `run_aob_library(argv=None)`
- `run_aob_regression_opencode_deploy_check(argv=None)`
- `run_aob_workflow_deploy(...)`
- `run_aob_items_sync(...)`
- `run_aob_external_templates_import(...)`
- `run_aob_workspace_convert(...)`

路径解析约定：

- 默认优先使用同级 `autodo-lib` 作为 AOB 仓库根目录；
- 可通过环境变量 `AOB_REPO_ROOT` 覆盖；
- 支持通过参数 `repo_root/--repo-root` 显式传入。

## 2.4 文献数据库管理工具（autodokit.tools.bibliodb）

用途：提供文献数据库的基础管理能力，供业务事务直接调用。

核心接口：

- `init_empty_literatures_table()`：初始化空文献主表 DataFrame（兼容层；SQLite 为主库）。
- `init_empty_attachments_table()`：初始化空文献附件表 DataFrame（兼容层；SQLite 为主库）。
- `init_empty_table(columns=None, table_kind='literatures')`：按表类型初始化空表。
- `generate_uid(first_author, year_int, title_norm, prefix=None)`：生成文献唯一标识 `uid_literature`。
- `clean_title_text(title)`：生成 `clean_title`。
- `literature_match(table, first_author, year, title, top_n=5)`：返回候选匹配列表。
- `literature_upsert(table, literature, overwrite=True)`：按 003 主表契约插入或更新记录。
- `literature_insert_placeholder(table, first_author, year, title, clean_title, source='placeholder', extra=None)`：创建占位引文。
- `parse_reference_text(reference_text)`：从单条参考文献文本启发式提取 `first_author/year/title/clean_title`。
- `insert_placeholder_from_reference(table, reference_text, source='placeholder_from_reading', top_n=5, extra=None)`：执行“匹配已存在记录，否则插入占位引文”的一体化流程。
- `literature_attach_file(literatures, attachments, uid_literature, attachment_name, attachment_type='fulltext', is_primary=1, note='')`：写入文献附件关系，并联动主表原文状态。
- `literature_bind_standard_note(literatures, uid_literature, standard_note_uid)`：绑定文献标准笔记 UID。
- `literature_get(literatures, attachments, uid_literature)`：读取单条文献及其附件集合。
- `update_pdf_status(table, uid, has_pdf, pdf_path='')`：保留的过渡接口，会落到 `has_fulltext` 与 `primary_attachment_name` 语义上执行。

字段约定（文献主表）：

- 标识：`uid_literature`、`cite_key`、`id`
- 文本：`title`、`clean_title`、`title_norm`、`abstract`、`keywords`
- 作者年份：`first_author`、`authors`、`year`、`entry_type`
- 管理：`is_placeholder`、`source_type`、`origin_path`、`standard_note_uid`
- 原文：`has_fulltext`、`primary_attachment_name`

字段约定（文献附件表）：

- 标识：`uid_attachment`、`uid_literature`、`id`
- 文件：`attachment_name`、`attachment_type`、`file_ext`
- 路径：`storage_path`、`source_path`
- 管理：`checksum`、`is_primary`、`status`

说明：自 SQLite 主库并库改造完成后，文献管理系统与知识管理系统默认共享同一个内容主库 `database/content/content.db`。`database/references/references.db`、`database/knowledge/knowledge.db` 仍可作为显式输入路径被兼容读取，但不再是默认主契约。上述 DataFrame 接口保留为兼容层与中间处理层；如仍存在 `uid`、`has_pdf`、`pdf_path` 等旧列，当前工具层会做最小过渡映射。

新增 SQLite-first 接口：

- `init_references_db(db_path)`：初始化文献 SQLite 主库的兼容入口；新项目优先使用 `init_content_db(db_path)`。
- `load_reference_tables(db_path=..., references_root=...)`：读取文献主表与附件表。
- `persist_reference_tables(literatures_df, attachments_df, db_path=..., references_root=...)`：写回文献 SQLite 主库。
- `load_reference_main_table(input_path)`：按路径读取文献主表，支持 `.db` 与旧 `.csv`。
- `persist_reference_main_table(table, output_path)`：按路径写回文献主表，支持 `.db` 与旧 `.csv`。
- `init_knowledge_db(db_path)`：初始化知识 SQLite 主库的兼容入口；新项目优先使用 `init_content_db(db_path)`。
- `load_knowledge_tables(db_path=..., knowledge_root=...)`：读取知识索引表与附件表。
- `persist_knowledge_tables(index_df, attachments_df, db_path=..., knowledge_root=...)`：写回知识 SQLite 主库。
- `load_knowledge_index_table(input_path)`：按路径读取知识索引主表，支持 `.db` 与旧 `.csv`。
- `init_content_db(db_path)`：初始化统一内容主库。
- `resolve_content_db_path(db_path)`：把旧的平铺 `database/*.db` 路径解析到统一内容主库路径。
- `load_knowledge_literature_links_df(db_path)`：读取知识-文献关系表。
- `load_knowledge_evidence_links_df(db_path)`：读取知识证据关系表。

本轮新增的结构化/分块状态接口：

- `load_chunk_sets_df(db_path)`：读取 `literature_chunk_sets` 批次索引表。
- `load_chunks_df(db_path)`：读取 `literature_chunks` 明细索引表。
- `save_structured_state(db_path, ..., uid_literature=...)`：按文献 UID 回写 `structured_*` 状态字段。
- `get_structured_state(db_path, uid_literature)`：读取单篇文献的结构化状态。
- `replace_chunk_set_records(db_path, chunk_set_row=..., chunk_rows=...)`：按 `chunks_uid` 整批替换 chunk 批次与 chunk 明细。

新增字段约定（`literatures` 主表）：

- `文献语种`：规范化语种字段。优先值为 `zh-cn`、`en`；其他语种保留为小写标签（如 `fr`、`de`、`ja`）。
- `structured_status`：结构化状态，如 `ready`。
- `structured_abs_path`：结构化 JSON 的绝对路径。
- `structured_backend`：生成后端，如 `local_pipeline_v2`、`babeldoc`。
- `structured_task_type`：解析任务类型，如 `reference_context`、`full_fine_grained`。
- `structured_updated_at`：结构化结果更新时间。
- `structured_schema_version`：当前固定为 `aok.pdf_structured.v3`。
- `structured_text_length`：结构化全文字符数。
- `structured_reference_count`：结构化结果中的参考文献条数。

新增表约定：

- `literature_chunk_sets`：记录一批 chunk 的 manifest 级元数据，核心字段包括 `chunks_uid`、`chunks_abs_path`、`source_scope`、`source_backend`、`chunk_count`、`source_doc_count`。
- `literature_chunks`：记录单个 chunk 的索引信息，核心字段包括 `chunk_id`、`chunks_uid`、`uid_literature`、`cite_key`、`shard_abs_path`、`chunk_index`、`chunk_type`、`char_start`、`char_end`、`text_length`。

新增 structured/chunk 工具：

- `build_structured_data_payload(...)`：构造统一 `aok.pdf_structured.v3` 结果。
- `load_single_document_record(...)`：优先从 structured 输入解析单篇旧兼容文档记录。
- `load_document_records_from_structured_source(...)`：从 structured 目录或 `references.db` 批量生成兼容文档记录。
- `build_chunk_entries_from_structured_data(...)`：直接从 structured payload 生成 chunk 条目。
- `write_chunk_shards(...)`：写出 chunk shards 与 `chunk_manifest.json`。
- `iter_chunk_files_from_manifest(manifest_path)`：从 manifest 解析实际 chunk 分片路径。
- `extract_review_state_from_structured_file(...)`：从 structured JSON 直接构造 A06 review state。

补充说明：占位引文与标准引文共享同一套稳定 UID 生成规则。是否为占位引文由 `is_placeholder` 字段标识。

## 2.5 知识数据库管理工具（autodokit.tools.knowledgedb）

用途：提供以 Obsidian Markdown 为主、统一内容主库为辅的知识索引与附件管理能力。`knowledge_index.csv` 不再是运行时主库，而是导出/迁移格式。

核心接口：

- `init_empty_knowledge_index_table()`：初始化空知识索引表。
- `init_empty_knowledge_attachments_table()`：初始化空知识附件表。
- `generate_knowledge_uid(note_path, title)`：生成稳定知识笔记 UID。
- `knowledge_upsert(index_table, record, overwrite=True)`：插入或更新知识索引记录。
- `knowledge_sync_note(index_table, note_path, workspace_root=None)`：从 Markdown frontmatter 解析并同步知识索引。
- `knowledge_note_register(note_path, title, ...)`：创建带标准 frontmatter 的知识笔记并返回索引记录。
- `knowledge_note_validate_obsidian(note_path)`：校验 Obsidian 笔记 frontmatter 是否符合 004 契约。
- `knowledge_bind_literature_standard_note(note_path, uid_literature, ...)`：将知识笔记绑定为文献标准笔记。
- `knowledge_base_generate(views_dir)`：生成知识库视图模板（`knowledge_index.base`、`literature_notes.base`）。
- `knowledge_index_sync_from_note(index_table, note_path, workspace_root=None)`：`knowledge_sync_note` 的兼容包装接口。
- `knowledge_attachment_register(index_table, attachments_table, uid_knowledge, attachment_name, ...)`：`knowledge_attach_file` 的兼容包装接口。
- `knowledge_attach_file(index_table, attachments_table, uid_knowledge, attachment_name, ...)`：维护知识附件关系。
- `knowledge_get(index_table, attachments_table, uid_knowledge)`：读取单条知识记录及其附件集合。
- `knowledge_find_by_literature(index_table, uid_literature='', cite_key='', note_type='')`：按文献绑定信息查找知识笔记。

时间元数据约定：

- `knowledge_note_register(...)` 与 `knowledge_bind_literature_standard_note(...)` 现在默认使用北京时间 `Asia/Shanghai` 写入 frontmatter 的 `created`、`updated`。
- `task_docs.create_latest_files(...)` 生成的任务文档 frontmatter `created` 也默认使用北京时间 `Asia/Shanghai`。
- 如果历史笔记仍保留 UTC 或其它时区，可调用 `rewrite_obsidian_note_timestamps(...)` 或 `batch_rewrite_obsidian_note_timestamps(...)` 批量改写。
- `suspicious_mismatch` 是参考文献映射结果字段，不是 `literatures` 主表标签；真正落库的占位事实由 `is_placeholder`、`placeholder_reason`、`placeholder_status` 等字段承载。

主链入口注册表接口：

- `build_mainline_affair_entry_registry(workspace_root, node_inputs=None, ...)`：生成 A010-A160 主链入口注册表负载。
- `write_mainline_affair_entry_registry(output_path, workspace_root, node_inputs=None, ...)`：把主链入口注册表写到 JSON 文件。
- `resolve_mainline_affair_entry(node_code, registry)`：从注册表中解析单个节点入口。

字段约定（知识索引表）：

- 标识：`uid_knowledge`、`id`
- 笔记：`note_name`、`note_path`、`note_type`、`title`、`status`
- 元数据：`tags`、`aliases`、`source_type`、`evidence_uids`
- 文献绑定：`uid_literature`、`cite_key`
- 关系：`attachment_uids`

跨域关系表约定：

- `knowledge_literature_links`：知识笔记与文献对象之间的显式关系表；当前至少包含 `uid_knowledge`、`uid_literature`、`relation_type`、`is_primary`、`cite_key`、`source_field`。
- `knowledge_evidence_links`：知识笔记的证据链接表；当前至少包含 `uid_knowledge`、`evidence_type`、`target_uid`、`evidence_role`、`source_field`。
- `knowledge_index.uid_literature`、`knowledge_index.evidence_uids` 仍保留为兼容缓存字段，但跨域事实源已收敛到上述关系表。

校验规则（`knowledge_note_validate_obsidian`）：

- 必填键：`uid_knowledge`、`title`、`note_type`、`status`
- `uid_knowledge` 必须是字符串；`evidence_uids` 必须是列表
- 当 `note_type=literature_standard_note` 时，必须提供 `uid_literature`

字段约定（知识附件表）：

- 标识：`uid_attachment`、`uid_knowledge`、`id`
- 文件：`attachment_name`、`attachment_type`、`file_ext`
- 路径：`storage_path`、`source_path`
- 管理：`checksum`、`status`

## 2.6 AOK 任务数据库管理工具（隔离版）

用途：提供与旧任务数据库语义隔离的 AOK 003 任务管理最小能力，路径位于 `autodokit.tools.atomic.task_aok`，并通过 `autodokit.tools` 统一导出。

核心接口：

- `init_empty_tasks_table()`：初始化空任务主表。
- `init_empty_task_artifacts_table()`：初始化空任务产物表。
- `init_empty_task_status_log_table()`：初始化任务状态日志表。
- `init_empty_task_gate_decisions_table()`：初始化闸门决策表。
- `init_empty_task_handoffs_table()`：初始化任务交接表。
- `init_empty_task_relations_table()`：初始化任务关系表。
- `init_empty_task_round_views_table()`：初始化轮次快照表。
- `init_empty_task_releases_table()`：初始化任务发布表。
- `init_empty_task_literature_bindings_table()`：初始化任务-文献绑定明细表。
- `init_empty_task_knowledge_bindings_table()`：初始化任务-知识绑定明细表。
- `task_create_or_update(tasks, task, workspace_root=None, overwrite=True, ensure_workspace_dir=True)`：创建或更新任务主表记录。
- `task_status_append(status_log, aok_task_uid, status, ...)`：追加任务状态流转日志。
- `task_gate_decision_record(gate_decisions, aok_task_uid, gate_uid, decision, ...)`：登记闸门决策。
- `task_handoff_record(handoffs, from_task_uid, to_task_uid, ...)`：登记任务交接。
- `task_relation_upsert(relations, source_task_uid, target_task_uid, relation_type, ...)`：维护任务之间的关系。
- `task_round_snapshot_register(round_views, aok_task_uid, round_uid, ...)`：登记轮次快照与对应视图。
- `task_release_register(releases, aok_task_uid, release_name, ...)`：登记阶段发布物。
- `task_release_promote(releases, aok_task_uid, release_uid, ...)`：把发布记录提升为目标状态。
- `task_literature_binding_register(bindings, aok_task_uid, uid_literature, ...)`：登记任务与文献的单条绑定事实。
- `task_knowledge_binding_register(bindings, aok_task_uid, uid_knowledge, ...)`：登记任务与知识的单条绑定事实。
- `task_bind_literatures(tasks, aok_task_uid, literature_uids, validate_exists=None)`：绑定文献 UID 列表。
- `task_bind_knowledges(tasks, aok_task_uid, knowledge_uids, validate_exists=None)`：绑定知识 UID 列表。
- `task_artifact_register(tasks, artifacts, aok_task_uid, artifact_name, artifact_type, artifact_path, ...)`：登记任务产物。
- `task_bundle_export(artifacts, aok_task_uid, output_dir)`：导出任务产物集合。
- `task_get(tasks, artifacts, aok_task_uid)`：读取任务详情与产物列表。
- `bootstrap_aok_taskdb(project_root='.', tasks_db_root=None, tasks_workspace_root=None)`：初始化 AOK 任务数据库骨架，支持显式指定元数据目录与任务工作区目录。
- `validate_aok_taskdb(project_root='.', tasks_db_root=None, tasks_workspace_root=None, references_db=None, knowledge_db=None)`：校验 AOK 任务数据库一致性。默认使用统一内容主库 `database/content/content.db`；若显式传参，`references_db` 与 `knowledge_db` 可继续作为兼容入口，并解析到同一内容主库路径。

字段约定（任务主表）：

- 标识：`aok_task_uid`
- 基本信息：`task_name`、`task_goal`、`task_status`
- 目录：`workspace_dir`
- 引用关系：`literature_uids`、`knowledge_uids`
- 时间：`created_at`、`updated_at`

字段约定（任务产物表）：

- 关联：`aok_task_uid`
- 描述：`artifact_name`、`artifact_type`
- 路径：`artifact_path`
- 说明：`note`
- 时间：`created_at`

字段约定（新增扩展表）：

- 状态日志表：`aok_task_uid`、`status`、`reason`、`operator`、`created_at`
- 闸门决策表：`aok_task_uid`、`gate_uid`、`decision`、`score`、`note`、`created_at`
- 任务交接表：`from_task_uid`、`to_task_uid`、`handoff_type`、`note`、`created_at`
- 任务关系表：`source_task_uid`、`target_task_uid`、`relation_type`、`note`、`updated_at`
- 轮次快照表：`aok_task_uid`、`round_uid`、`round_name`、`view_path`、`created_at`
- 发布表：`aok_task_uid`、`release_uid`、`release_name`、`release_type`、`release_path`、`status`、`created_at`、`updated_at`
- 任务-文献绑定表：`aok_task_uid`、`uid_literature`、`binding_type`、`created_at`
- 任务-知识绑定表：`aok_task_uid`、`uid_knowledge`、`binding_type`、`created_at`

说明：

- 该隔离版工具只实现任务“组织与引用”能力，不复制文献主表和知识主索引事实。
- `bootstrap_aok_taskdb` 默认优先使用 `database/tasking/` 作为元数据根目录，若历史项目仍使用 `database/tasks/`，会自动回退兼容。
- `validate_aok_taskdb` 会在相关文件存在时校验 `literature_uids` 与 `knowledge_uids` 的跨表存在性，并检查扩展表之间的任务引用一致性；默认按统一内容主库契约解析，若项目目录结构与默认约定不同，可通过 `tasks_db_root`、`tasks_workspace_root` 以及兼容参数 `references_db`、`knowledge_db` 显式传入路径。

### 本地 Git 快照与极简任务账本（autodokit.tools.atomic.task_aok.git_snapshot_ledger）

用途：在单个 workspace 根目录内提供“本地-only”的 Git 快照能力和与之配套的极简 SQLite 任务账本，便于在事务闸门（gate）通过时做可追溯的提交记录与回滚预案登记。

模块位置：`autodokit/tools/atomic/task_aok/git_snapshot_ledger.py`

主要函数一览：

- `ledger_init(workspace_root, ledger_db_path=None) -> dict`：初始化极简账本。默认路径为 `workspace_root/database/tasks/tasks.db`。
- `ledger_record_task_run(workspace_root, *, task_uid, workflow_uid, node_code, gate_code, decision, status, ...) -> dict`：登记一次节点运行结果（低级写入接口）。
- `ledger_record_git_snapshot(... ) -> dict`：登记 Git 快照元数据（低级写入接口）。
- `ledger_record_rollback(... ) -> dict`：登记回滚记录（preview/plan 或 done）。
- `ledger_get_snapshot_by_task_uid(workspace_root, *, task_uid, ledger_db_path=None) -> dict | None`：按 `task_uid` 查询最近一次快照与运行记录。
- `git_workspace_init(workspace_root, *, branch='main') -> dict`：在 workspace 下初始化本地 Git 仓库（不 push）。
- `git_create_snapshot_for_task(workspace_root, *, task_uid, workflow_uid, node_code, gate_code, commit_message=None, tag_name=None, includes_attachments=False, ledger_db_path=None) -> dict`：执行 `git add -A`、`git commit`、`git tag`，并把快照写入账本与日志摘要。返回结构包含 `status`, `git_snapshot`, `summary_path`, `commit_hash`。
- `git_rollback_by_task_uid(workspace_root, *, source_task_uid, target_task_uid, mode='preview', ledger_db_path=None) -> dict`：按目标 `task_uid` 查到 commit hash 并登记回滚计划（`mode='preview'` 时仅登记，不执行实际回滚）。

快照与账本产物位置：

- 账本（SQLite）：`workspace_root/database/tasks/tasks.db`（可通过 `ledger_db_path` 覆盖）。
- 快照 summary（JSON）：`workspace_root/logs/git_snapshots/{task_uid}.json`。
- Tag 命名约定：`aok/task/{task_uid}`（默认由 `git_create_snapshot_for_task` 生成）。

使用约束与注意事项：

- 本模块仅作本地记录与协助决策之用，不会自动 push 到远端仓库；tag 也只存在于本地仓库。
- `git_rollback_by_task_uid` 当前只登记回滚计划或完成记录，不执行 `git reset`/checkout 等破坏性操作；实际恢复需人工审计并在安全流程下运行回滚命令。
- 为避免在无全局 git config 的环境中提交失败，模块会为 subprocess 设置默认的 `GIT_AUTHOR_*`/`GIT_COMMITTER_*` 环境变量；CI 可显式设置全局 config 或允许默认值。
- `.gitignore` 默认只忽略运行态日志数据库 `database/logs/aok_log.db`；其余 workspace 内容默认纳入 Git 管理，包括附件与产物。

最小使用示例：

```python
from pathlib import Path
from autodokit.tools.atomic.task_aok.git_snapshot_ledger import (
  ledger_init,
  git_workspace_init,
  git_create_snapshot_for_task,
  git_rollback_by_task_uid,
)

root = Path.cwd()
ledger_init(root)
git_workspace_init(root)
res = git_create_snapshot_for_task(
  root,
  task_uid="task-20260403-001",
  workflow_uid="wf-xyz",
  node_code="nodeA",
  gate_code="pass_next",
  commit_message="AOK snapshot for task-20260403-001",
)
print(res["summary_path"], res["commit_hash"])

# 预览回滚（仅登记计划）
preview = git_rollback_by_task_uid(root, source_task_uid="task-20260403-002", target_task_uid="task-20260403-001", mode="preview")
print(preview)
```

建议：把 `git_create_snapshot_for_task` 在事务的 `pass_next` hook（或类似的闸门通过回调）中作为非阻塞写记录调用；出现异常时记录日志并允许事务继续（避免因快照失败阻断主链）。

## 2.7 研究流程支持工具（autodokit.tools.research_workflow_tools）

用途：提供论文文献工程化流程 M1-M3 所需的最小公开支持能力。

核心接口：

- `init_empty_candidate_view_table()`：初始化候选文献视图表。
- `init_empty_reading_batch_table()`：初始化阅读批次表。
- `init_empty_innovation_pool_table()`：初始化创新点池表。
- `build_candidate_view_index(records, source_round=..., source_affair=..., min_score=..., top_k=...)`：把候选记录构建为轻量索引视图。
- `build_candidate_readable_view(index_table, literature_table, ...)`：将索引视图与文献主表合并为人类可读视图。
- `extract_review_candidates(readable_table)`：从候选视图中抽取综述优先池。
- `allocate_reading_batches(index_table, batch_size=..., review_uid_set=...)`：按优先级生成阅读批次。
- `build_research_trajectory(items, topic=...)`：基于候选条目生成研究脉络摘要。
- `build_gate_review(node_uid=..., node_name=..., summary=..., ...)`：构造统一闸门审计报告。
- `score_gate_review(review, pass_threshold=...)`：为闸门报告补充建议动作。
- `merge_human_gate_decision(review, human_decision=..., ...)`：把人工决策合并回闸门报告。
- `innovation_pool_upsert(pool_table, innovation_item, ...)`：插入或更新创新点池记录。
- `innovation_feasibility_score(innovation_item)`：输出创新点四维可行性评分。

典型使用场景：

- 候选文献视图构建事务
- 综述研读与研究地图生成事务
- 研究脉络梳理事务
- 创新点池构建事务
- 创新点可行性验证事务

## 3. 事务模块契约

每个事务目录仅保留：

- affair.py：事务执行主体
- affair.json：纯业务参数模板
- affair.md：说明文档（用途、场景、参数、输出、示例）

事务目录应保持“业务三件套纯粹化”。事务管理所需 runner/node/governance 等元数据由事务管理系统数据库统一承载。

### 3.1 AOK 独立任务事务（隔离版）

用途：为 AOK 003 任务管理系统提供独立事务入口，不复用旧版面向 AOE 语义的任务事务。

事务目录：

- `autodokit/affairs/AOK任务数据库初始化`
- `autodokit/affairs/AOK任务数据库校验`

对应输出文件：

- `aok_taskdb_bootstrap_result.json`
- `aok_taskdb_validate_result.json`

说明：

- 该组事务只调用 `autodokit.tools.atomic.task_aok` 导出的 AOK 任务工具。
- 旧事务 `任务数据库初始化`、`任务数据库校验` 保留原语义，不与本组混用。

### 3.2 Skill渲染（`autodokit.affairs.Skill渲染.affair`）

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

### 3.3 AOB 常用事务（新增）

- `AOB一键安装部署`
  - 入口：`autodokit/affairs/AOB一键安装部署/affair.py`
  - 固定输出：`aob_one_click_deploy_result.json`
- `AOB一键办公区转换`
  - 入口：`autodokit/affairs/AOB一键办公区转换/affair.py`
  - 固定输出：`aob_workspace_convert_result.json`

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

### 3.3 AOK三库联动示例（`autodokit.affairs.AOK三库联动示例.affair`）

用途：演示最近开发的三库联动最小闭环（统一内容主库 + 知识笔记资产 + AOK 任务库）。

执行链路：

1. 从 BibTeX 导入文献并写入统一内容主库；
2. 从 Zotero RDF `files/` 嵌套目录手动提取附件并复制到 `references/attachments/`；
3. 基于文献生成知识标准笔记，并把关联事实同步到统一内容主库；
4. 创建 AOK 任务并绑定文献/知识 UID，登记产物并导出任务包。

配置字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `project_root` | `str` | 是 | 示例工作区绝对路径。 |
| `bib_path` | `str` | 是 | BibTeX 测试数据绝对路径。 |
| `rdf_files_root` | `str` | 是 | Zotero RDF 的 `files/` 根目录绝对路径（非扁平结构）。 |
| `max_bib_records` | `int` | 否 | 最多导入文献条目数，默认 `3`。 |
| `max_attachments` | `int` | 否 | 最多提取复制附件数，默认 `6`。 |
| `output_dir` | `str` | 是 | 输出目录绝对路径。 |

输出文件：

- `aok_triple_db_demo_result.json`

默认示例配置：

- `demos/settings/配置文件/aok_triple_db_demo.json`

### 3.4 单篇粗读（`autodokit.affairs.单篇粗读.affair`）

用途：在单篇精读前提供“快速扫描 + 参考文献抽取 + 占位引文回写”的前置事务。

公开入口：

- `execute(config_path: Path) -> list[Path]`
  - 从配置读取 `input_structured_json`、`input_structured_dir`、`content_db`、`output_dir`、`uid/doc_id` 等字段。
  - 读取目标文献后生成粗读笔记与结构化 JSON 结果。
  - 可选将参考文献写入 `bibliography_csv` 占位引文。

配置字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `output_dir` | `str` | 是 | 输出目录绝对路径。 |
| `uid` | `str\|int` | 否 | 目标文献 UID，未提供时可用 `doc_id`。 |
| `doc_id` | `str` | 否 | 目标文献 doc_id，提供时优先匹配。 |
| `content_db` | `str` | 否 | 统一内容主库绝对路径；存在时会按 `structured_abs_path` 定位目标文献并回写占位引文。 |
| `insert_placeholders_from_references` | `bool` | 否 | 是否回写占位引文，默认 `true`。 |
| `reference_lines` | `list[str]` | 否 | 外部补充参考文献行，会与文内提取结果合并。 |
| `max_preview_chars` | `int` | 否 | 正文预览最大字符数，默认 `4000`。 |
| `input_structured_json` | `str` | 否 | 单篇 `structured.json` 绝对路径；提供时优先读取。 |
| `input_structured_dir` | `str` | 否 | 结构化结果目录绝对路径；按 `uid/doc_id` 匹配目标文献。 |

输出文件：

- `rough_reading_{uid_or_doc_id}.md`
- `rough_reading_result_{uid_or_doc_id}.json`

异常：

- `ValueError`：关键路径不是绝对路径或目标文献不存在时抛出。

说明：当前 `单篇粗读` 只支持 `input_structured_json`、`input_structured_dir` 与 `content_db` 中登记的 `structured_abs_path` 这三类 structured 输入。

### 3.5 单篇精读（`autodokit.affairs.单篇精读.affair`）

用途：生成单篇精读 Markdown 笔记，可选择本地规则草稿或 LLM 精读。

公开入口：

- `execute(config_path: Path) -> list[Path]`
  - 优先从 structured 输入读取目标文献；若未提供单文件或目录输入，则从 `content_db` 中登记的 `structured_abs_path` 定位目标文献。
  - `use_llm=false` 时走本地规则摘要；`use_llm=true` 时调用 DashScope 客户端。

配置字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `output_dir` | `str` | 是 | 输出目录绝对路径。 |
| `uid` / `uid_literature` | `str` | 否 | 目标文献 UID。 |
| `doc_id` | `str` | 否 | 目标文献 doc_id，提供时优先。 |
| `input_structured_json` | `str` | 否 | 单篇 `structured.json` 绝对路径。 |
| `input_structured_dir` | `str` | 否 | 结构化目录绝对路径。 |
| `content_db` | `str` | 否 | 统一内容主库绝对路径；可用于匹配 `structured_abs_path` 并回写占位引文。 |
| `use_llm` | `bool` | 否 | 是否调用模型，默认 `false`。 |
| `model` | `str` | 否 | 模型名，默认 `qwen-plus`。 |
| `system_prompt` | `str` | 否 | 系统提示词。 |
| `user_prompt_template` | `str` | 否 | 仅在 `use_llm=true` 时使用，可为绝对路径或模板正文。 |
| `max_chars` | `int` | 否 | 输入文本最大字符数，默认 `12000`。 |
| `insert_placeholders_from_references` | `bool` | 否 | 是否插入占位引文，默认 `true`。 |

输出文件：

- `single_reading_{uid_or_doc_id}.md`

### 3.6 PDF 文件转结构化数据文件（`autodokit.affairs.PDF文件转结构化数据文件.affair`）

用途：批量把 PDF 转成统一 `aok.pdf_structured.v3` 结果，并可把状态回写到 `content.db`。

说明：这是传统 PDF 结构化套件的事务入口，不包含阿里百炼多模态结构树与线性索引逻辑。

配置字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `input_pdf_dir` | `str` | 是 | 输入 PDF 目录绝对路径，仅扫描当前层。 |
| `output_structured_dir` | `str` | 是 | 输出结构化结果目录绝对路径。 |
| `converter` | `str` | 否 | `local_pipeline_v2` 或 `babeldoc`，默认 `local_pipeline_v2`。 |
| `task_type` | `str` | 否 | 解析模式，常用 `reference_context`、`full_fine_grained`。 |
| `content_db` | `str` | 否 | 统一内容主库绝对路径；提供后会回写 `structured_*` 字段。 |
| `overwrite` | `bool` | 否 | 是否覆盖已有 `.structured.json`。 |
| `extractors` | `dict` | 否 | 本地流水线抽取器配置。 |
| `babeldoc` | `dict` | 否 | BabelDOC 配置。 |
| `output_log` | `str` | 否 | 过程日志绝对路径。 |

输出文件：

- `<cite_key_or_uid>.structured.json`
- `pdf_to_structured_manifest.json`
- 可选 `output_log`

### 3.7 解析与分块（`autodokit.affairs.解析与分块.affair`）

用途：从 `structured.json` 或 `content.db` 中登记的 structured 资产生成 chunk 结果。

当前推荐输入：

- `input_structured_dir`
- `content_db`

结构化主链新增字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `input_structured_dir` | `str` | 否 | 结构化目录绝对路径。 |
| `content_db` | `str` | 否 | 统一内容主库绝对路径；存在时会自动收集 `structured_abs_path`。 |
| `source_scope` | `str` | 否 | chunk 来源范围标识，默认 `structured`。 |
| `source_backend` | `str` | 否 | chunk 来源后端标识，默认 `structured_json`。 |
| `chunk_shard_size` | `int` | 否 | 每个 shard 最大 chunk 数，默认 `200`。 |
| `chunks_uid` | `str` | 否 | 批次 UID；为空时自动生成。 |

输出文件：

- `chunk_manifest.json`
- `chunk_stats.json`
- `chunk_shards/*.jsonl`

说明：若提供 `content_db`，事务会同步写入 `literature_chunk_sets` 与 `literature_chunks`。

### 3.8 向量化与索引构建（`autodokit.affairs.向量化与索引构建.affair`）

用途：把 chunk 输入做 TF-IDF 向量化。

新增输入策略：

1. 优先读取 `input_chunk_manifest_json`。
2. 其次可通过 `content_db + chunks_uid` 从 `literature_chunk_sets` 定位 manifest。

配置字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `output_dir` | `str` | 是 | 输出目录绝对路径。 |
| `input_chunk_manifest_json` | `str` | 否 | chunk manifest 绝对路径。 |
| `content_db` | `str` | 否 | 统一内容主库绝对路径。 |
| `chunks_uid` | `str` | 否 | 目标 chunk 批次 UID。 |
| `vectorizer_type` | `str` | 否 | 当前仅支持 `tfidf`。 |
| `max_features` | `int` | 否 | 最大词表大小。 |
| `ngram_range` | `list[int]` | 否 | ngram 范围。 |

输出文件：

- `tfidf.npz`
- `vocab.json`
- `chunk_meta.jsonl`
- `vector_manifest.json`

### 3.9 综述草稿生成（`autodokit.affairs.综述草稿生成.affair`）

用途：基于矩阵、structured 输入或 `content.db` 中登记的 structured 资产生成综述草稿。

输入优先级：

1. `input_matrix_jsonl`
2. `input_structured_dir` 或 `content_db`

新增字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `input_structured_dir` | `str` | 否 | 结构化目录绝对路径。 |

### 3.10 模型路由派发（`autodokit.affairs.模型路由派发.affair`）

用途：生成可执行的大模型路由计划，并可选执行一次真实调用用于联调验证。

公开入口：

- `execute(config_path: Path) -> list[Path]`
- 内部核心：`run_model_routing_affair(...)`

配置字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `task_type` | `str` | 否 | 任务类型：`general`、`vision`、`long_text`、`math_reasoning`、`coding`。 |
| `quality_tier` | `str` | 否 | 质量档位：`standard`、`high`。 |
| `budget_level` | `str` | 否 | 旧预算字段（兼容）：`low`/`medium`/`high`。 |
| `latency_level` | `str` | 否 | 旧时延字段（兼容）：`low`/`medium`/`high`。 |
| `risk_level` | `str` | 否 | 风险级别：`low`/`medium`/`high`/`strict`。 |
| `region` | `str` | 否 | 目标地域，默认 `cn-beijing`。 |
| `input_chars` | `int` | 否 | 输入字符数估计，用于成本估算。 |
| `model` | `str` | 否 | 显式锁定模型；为空时走自动路由。 |
| `mainland_only` | `bool` | 否 | 为 `true` 时强制使用中国内地地域。 |
| `run_inference` | `bool` | 否 | 是否执行真实调用，默认 `false`。 |
| `prompt` | `str` | 否 | 当 `run_inference=true` 时必填。 |
| `system_prompt` | `str` | 否 | 可选系统提示词。 |
| `max_tokens` | `int` | 否 | 最大输出 token，默认 `1024`。 |
| `temperature` | `float` | 否 | 温度参数，默认 `0.2`。 |
| `env_api_key_name` | `str` | 否 | API Key 环境变量名，默认 `DASHSCOPE_API_KEY`。 |
| `api_key_file` | `str` | 否 | 可选 API Key 文件路径。 |
| `config_path` | `str` | 否 | 可选配置路径。 |

输出文件：

- `model_routing_dispatch_result.json`

输出关键字段：

- `result.decision.primary_model`：主模型。
- `result.decision.fallback_models`：回退模型链。
- `result.decision.estimated_input_tokens`：输入 token 估算。
- `result.decision.estimated_cost_range`：单次调用成本估算区间（元）。
- `result.invocation`：真实调用结果（或 `SKIPPED`）。
| `content_db` | `str` | 否 | 统一内容主库绝对路径。 |

输出文件：

- `review_draft.md`

### 3.10 候选文献视图构建与综述研读缓存策略

以下两个事务本轮未新增复杂配置字段，但公开行为已同步调整：

- `候选文献视图构建`：若 `literatures.structured_abs_path` 指向的文件存在，优先从 structured JSON 提取 `reference_lines` 与 `reference_line_details`，不再重复读取 PDF。
- `综述研读与研究地图生成`：优先调用 `extract_review_state_from_structured_file(...)` 生成 review state；默认文献主库路径按 `database/content/content.db` 契约解析。

## 4. 不再由本仓提供的接口

以下接口已拆分到 autodo-engine：

- 流程图加载与注册
- 任务创建与推进
- taskdb / 决策 / 审计视图
- CLI 子命令

## 5. demos 工具直调用例

- `demos/scripts/demo_tool_user_import_call.py`：用户公开工具直接导入调用。
- `demos/scripts/demo_tool_developer_get_tool_call.py`：开发者工具按名称读取并调用。
- `demos/scripts/demo_tool_cli_call.py`：通过 `python -m autodokit.tools.adapters.cli` 调用工具。

# 6. 内容主库新契约补记

自 content.db 进入 SQLite 主库阶段后，以下规则是新项目默认口径：

- 程序只读写物理表；SQLite 视图允许存在，但只用于人类查询、巡检与排查。
- 任何名为 `view` 的下游产物，默认优先理解为 CSV 导出物、阶段快照或人类可读对象；若数据库内存在同名视图，也不应作为程序写入目标。
- A010 初始化脚本 `C:\Users\Ethan\.copilot\skills\A010_项目初始化_v5\scripts\generate_config.py` 的自检重点，应改为确认“主链不向视图写入”，而不是要求 `content.db` 零视图；新版模板统一写 `workspace/tasks/`，并默认只生成 snapshot 计划等待人类确认。
- `review_read_pool_current_view`、`review_candidate_current_view`、`review_priority_current_view` 与中文阅读状态视图可继续保留为只读对象，不再视为需要从库中清除的异常残留。

附件与标签关系补记：

- `literature_tags` 是文献-标签的简化 n 对 n 关系表。
- `literature_attachments` 当前属于迁移期兼容扁平表，同时承载关系边与附件元数据。
- 新的规范化方向是拆分为 `attachments`（附件实体表）与 `literature_attachment_links`（文献-附件关系表），以支持附件去重、共享与版本治理。
- A020 与 A040 都应把附件事实同步写入上述两层表；在线下载文件不能只落磁盘不入库。
- `attachments` 表中的附件来源字段可用于区分本地导入、在线下载、补件回流等来源；任务级审计应同步登记 `来源事务`。
- 已匹配主附件的默认物理文件名应使用稳定附件 UID 派生基名；`cite_key` 保留给引文回链、标准笔记与人类阅读，不再承担磁盘命名职责。
- 未命中的孤儿附件建议隔离到独立目录，并以 JSON 清单形式交给人工复核，而不是继续混放在正式附件目录。

## 7. 附录：AOK CLI 工具（aok_tool）简介

项目内新增了轻量命令行工具包 `tools/aok_tool`，用于对 AOK 运行时日志与阅读队列执行常见检查与写入操作。工具目的是提供一个可复用的本地运维入口，便于脚本化操作与审计。

安装位置（仓库内）：

- `tools/aok_tool/aok.py` — 主入口，支持子命令 `write-log` 与 `list-queue`。
- `tools/aok_tool/__init__.py` — 包标记。
- `tools/aok_tool/README.md` — 使用说明与示例。

主要子命令：

- `write-log`：把一段文本写入 AOK 日志数据库（`workspace/database/logs/aok_log.db`），可通过 `--message` 传入字符串，或 `--message-file` 指定文件，或从标准输入读取。
  - 典型示例：
    - `python tools/aok_tool/aok.py write-log --workspace workspace --message "已完成 A080，准备启动 A090"`
    - `python tools/aok_tool/aok.py write-log --workspace workspace --message-file ./notes/summary.txt`

- `list-queue`：读取工作区内容数据库（`workspace/database/content/content.db`）并按阶段列出候选队列简要视图（JSON 输出）。支持 `--stage` 指定阶段（如 `A060`、`A080`、`A090`），`--limit` 控制返回数量。
  - 典型示例：
    - `python tools/aok_tool/aok.py list-queue --workspace workspace --stage A060 --limit 10`

参数约定：

- `--workspace` / `-w`：工作区根目录（相对于仓库根）；如果省略，工具尝试使用当前工作目录的 `workspace/` 子目录。
- `--stage`：阅读队列阶段（`A060`/`A080`/`A090`/`A100` 等）。
- `--message` / `--message-file`：写日志时使用。

行为说明：

- `write-log` 会使用 `autodokit.tools.atomic.log_aok` 的填写契约（`append_aok_log_event`）进行写入，优先尊重 `workspace/config/config.json` 中的 `paths.log_db_path` 配置。
- 工具对数据库不可用的情况保持容错：尝试修复或返回友好错误，而非抛出未捕获异常。
- `list-queue` 只是只读视图，默认不修改 `content.db`。

建议：将常用检查脚本或 CI 步骤调用该工具，以保持日志写入与队列检查的一致性。工具为轻量运维入口，不替代事务级别的事务实现。

若需把该工具注册为可执行模块（`python -m tools.aok_tool.aok` 或打包后 `pip install -e .`），可在仓库级 packaging/CI 中加入对应条目。

--


