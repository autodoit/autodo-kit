# API 手册

autodo-kit（AOK）对外公开两层 API：**运行时 API**（`autodokit.api`）与**工具 API**（`autodokit.tools`）。事务程序（affair）通过 `autodokit.run_affair()` 统一调用，逐项配置字段见 [AOK预置事务手册](AOK预置事务手册.md)。

---

## 1. 运行时 API

模块：`autodokit.api`

所有运行时函数均支持中英文参数别名（如 `事务唯一标识` / `affair_uid`），任选其一即可。

### 1.1 run_affair

执行事务并返回产物路径列表。

```python
def run_affair(
    affair_uid: str,
    config: dict | None = None,
    config_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> list[Path]
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `affair_uid` | `str` | 是 | 事务唯一标识，对应 `autodokit/affairs/<affair_uid>/`。 |
| `config` | `dict` | 否 | 运行时覆盖的配置字典。与 `config_path` 互斥。 |
| `config_path` | `str\|Path` | 否 | 事务配置 JSON 文件绝对路径。与 `config` 互斥。 |
| `workspace_root` | `str\|Path` | 否 | 工作区根目录；为空时取当前工作目录。 |

返回：`list[Path]` —— 产物文件绝对路径列表。

事务执行结束后自动运行统一后处理（任务台账、Git 快照、运行审计）。

示例：

```python
from autodokit import run_affair

outputs = run_affair(
    affair_uid="检索治理",
    config_path="workspace/config/affairs_config/A040.zh_cnki.json",
    workspace_root="/home/ethan/workspace",
)
print(outputs)
```

### 1.2 prepare_affair_config

加载并解析事务配置，将所有路径字段转换为绝对路径。

```python
def prepare_affair_config(
    config: dict | None = None,
    config_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> dict
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `config` | `dict` | 否 | 运行时配置字典。 |
| `config_path` | `str\|Path` | 否 | 配置文件路径。与 `config` 互斥。 |
| `workspace_root` | `str\|Path` | 否 | 工作区根目录。 |

返回：`dict` —— 路径已绝对化的配置字典。

### 1.3 import_affair_module

按事务 UID 导入 Python 模块对象。

```python
def import_affair_module(
    affair_uid: str,
    workspace_root: str | Path | None = None,
) -> ModuleType
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `affair_uid` | `str` | 是 | 事务唯一标识。 |
| `workspace_root` | `str\|Path` | 否 | 工作区根目录。 |

返回：`ModuleType` —— 事务模块，其 `execute(config_path)` 可直调。

### 1.4 bootstrap_runtime

初始化本地运行时目录与注册表（`.autodokit/`）。

```python
def bootstrap_runtime(
    workspace_root: str | Path | None = None,
) -> dict
```

返回字典字段：`status`、`workspace_root`、`runtime_root`、`affairs_root`、`graphs_root`、`affair_registry_path`、`graph_registry_path`。

### 1.5 import_user_affair

将用户 Python 脚本导入为标准事务三件套（`affair.py` + `affair.json` + `affair.md`），并写入注册表。

```python
def import_user_affair(
    source: str | Path,
    affair_uid: str | None = None,
    workspace_root: str | Path | None = None,
    config_template: dict | None = None,
    doc_title: str | None = None,
    overwrite: bool = False,
) -> dict
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `source` | `str\|Path` | 是 | 用户 Python 脚本路径。 |
| `affair_uid` | `str` | 否 | 事务标识；默认取文件名。 |
| `workspace_root` | `str\|Path` | 否 | 工作区根目录。 |
| `config_template` | `dict` | 否 | 配置模板。 |
| `doc_title` | `str` | 否 | 文档标题。 |
| `overwrite` | `bool` | 否 | 是否覆盖同名事务，默认 `False`。 |

返回字段：`status`、`affair_uid`、`affair_dir`、`affair_py`、`affair_json`、`affair_md`、`affair_registry`。

### 1.6 register_graph

注册流程图配置到本地运行时。

```python
def register_graph(
    graph_uid: str,
    graph: dict | None = None,
    graph_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    overwrite: bool = False,
) -> dict
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `graph_uid` | `str` | 是 | 流程图唯一标识。 |
| `graph` | `dict` | 二选一 | 流程图配置字典。 |
| `graph_path` | `str\|Path` | 二选一 | 流程图配置文件路径。 |
| `workspace_root` | `str\|Path` | 否 | 工作区根目录。 |
| `overwrite` | `bool` | 否 | 是否覆盖同名图，默认 `False`。 |

### 1.7 load_graph

按 UID 或文件路径加载流程图配置。

```python
def load_graph(
    graph_uid: str | None = None,
    graph_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> dict
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `graph_uid` | `str` | 至少一个 | 流程图唯一标识。 |
| `graph_path` | `str\|Path` | 至少一个 | 流程图文件路径。 |
| `workspace_root` | `str\|Path` | 否 | 工作区根目录。 |

---

## 2. 工具 API

模块：`autodokit.tools`

直接导入即可调用：

```python
from autodokit.tools import literature_upsert, parse_reference_text
```

工具发现：

| 函数 | 返回 | 说明 |
| --- | --- | --- |
| `list_user_tools()` | `list[str]` | 用户公开工具名列表。 |
| `list_developer_tools()` | `list[str]` | 开发者工具名列表。 |
| `get_tool(name, scope)` | `Callable` | 按名称获取工具函数。`scope` 可选 `"user"`、`"developer"`、`"all"`。 |

---

### 2.1 文献与引用工具

#### literature_upsert

```python
def literature_upsert(
    table: DataFrame,
    literature: dict,
    overwrite: bool = True,
) -> dict
```

按 `uid_文献` 或 `cite_key` 插入或更新文献主表记录。返回更新后的行数据。

#### literature_insert_placeholder

```python
def literature_insert_placeholder(
    table: DataFrame,
    first_author: str,
    year: int,
    title: str,
    clean_title: str,
    source: str = "placeholder",
    extra: dict | None = None,
) -> dict
```

创建占位引文记录并写入主表。

#### literature_match

```python
def literature_match(
    table: DataFrame,
    first_author: str,
    year: int,
    title: str,
    top_n: int = 5,
) -> list[dict]
```

按作者/年份/标题在文献主表中匹配候选记录。

#### literature_attach_file

```python
def literature_attach_file(
    literatures: DataFrame,
    attachments: DataFrame,
    uid_文献: str,
    attachment_name: str,
    attachment_type: str = "fulltext",
    is_primary: int = 1,
    note: str = "",
) -> dict
```

写入文献附件关系，联动主表原文状态。

#### literature_bind_standard_note

```python
def literature_bind_standard_note(
    literatures: DataFrame,
    uid_文献: str,
    uid_标准笔记: str,
) -> dict
```

将标准笔记 UID 绑定到文献记录。

#### literature_get

```python
def literature_get(
    literatures: DataFrame,
    attachments: DataFrame,
    uid_文献: str,
) -> dict
```

读取单条文献及其附件集合。

#### parse_reference_text

```python
def parse_reference_text(reference_text: str) -> dict
```

从单条参考文献文本中提取 `first_author`、`year`、`title`、`clean_title`。

#### insert_placeholder_from_reference

```python
def insert_placeholder_from_reference(
    table: DataFrame,
    reference_text: str,
    source: str = "placeholder_from_reading",
    top_n: int = 5,
    extra: dict | None = None,
) -> dict
```

匹配已有记录，否则插入占位引文。

#### extract_reference_lines_from_attachment

```python
def extract_reference_lines_from_attachment(
    attachment_path: str | Path,
) -> dict
```

从 PDF 附件文末提取参考文献文本行。

---

### 2.2 参考文献处理工具

按原子链路组合：解析 → 匹配 → 占位 → 写回 → 生成引文键。

| 函数 | 说明 |
| --- | --- |
| `process_reference_citation(ref_text, content_db_path, ...)` | 组合能力：串联解析/匹配/占位/写回/生成引文。 |
| `match_reference_citation_record(author, year, title, ...)` | 在文献主表中匹配候选记录。 |
| `upsert_reference_citation_placeholder(...)` | 插入或复用占位引文记录。 |
| `writeback_reference_citation_record(...)` | 单条引文记录写回文献主表。 |
| `generate_reference_cite_key(first_author, year, title_norm)` | 生成稳定 `cite_key`。 |
| `ensure_reference_citation_cite_key(...)` | 确保记录具备 `cite_key`，必要时写回。 |
| `parse_reference_text_with_llm(text, ...)` | 用阿里百炼模型解析参考文献文本。 |
| `refine_reference_lines_with_llm(lines, ...)` | 用 LLM 精炼参考文献行。 |
| `build_reference_quality_summary(...)` | 生成参考文献质量摘要。 |
| `build_online_lookup_placeholder_fields(...)` | 构造在线检索占位字段。 |

#### local_reference_lookup_and_materialize

```python
def local_reference_lookup_and_materialize(
    content_db_path: str | Path,
    reference_list_text: str,
    workspace_root: str | Path | None = None,
    top_n: int = 5,
    placeholder_source: str = "placeholder_from_local_reference_lookup",
    print_to_stdout: bool = False,
) -> dict
```

将一段参考文献文本逐一在 `content.db` 中匹配；未命中时插入占位条目。

返回值字段：`matched_view`、`placeholder_view`、`all_rows`、`summary`。

#### incremental_import_bib_into_content_db

```python
def incremental_import_bib_into_content_db(
    bib_path: str | Path,
    content_db_path: str | Path,
    workspace_root: str | Path,
    ...
) -> dict
```

BibTeX 增量导入统一内容主库。

---

### 2.3 知识库工具

| 函数 | 说明 |
| --- | --- |
| `generate_knowledge_uid(note_path, title)` | 生成稳定知识笔记 UID。 |
| `knowledge_note_register(note_path, title, ...)` | 创建带标准 frontmatter 的知识笔记。 |
| `knowledge_note_validate_obsidian(note_path)` | 校验 Obsidian 笔记 frontmatter。 |
| `knowledge_bind_literature_standard_note(note_path, uid_文献, ...)` | 将知识笔记绑定为文献标准笔记。 |
| `knowledge_upsert(index_table, record, overwrite=True)` | 插入或更新知识索引记录。 |
| `knowledge_sync_note(index_table, note_path, ...)` | 从 Markdown frontmatter 同步知识索引。 |
| `knowledge_attach_file(index_table, attachments, uid_知识, ...)` | 维护知识附件关系。 |
| `knowledge_get(index_table, attachments, uid_知识)` | 读取单条知识记录及附件。 |
| `knowledge_find_by_literature(index_table, uid_文献, cite_key, note_type)` | 按文献绑定查找知识笔记。 |
| `knowledge_base_generate(views_dir)` | 生成知识库视图模板（`.base` 文件）。 |
| `knowledge_index_sync_from_note(...)` | `knowledge_sync_note` 的兼容别名。 |
| `knowledge_attachment_register(...)` | `knowledge_attach_file` 的兼容别名。 |

---

### 2.4 候选视图与批次工具

| 函数 | 说明 |
| --- | --- |
| `build_candidate_view_index(records, source_round, source_affair, min_score, top_k)` | 构建候选文献索引视图。 |
| `build_candidate_readable_view(index_table, literature_table, ...)` | 索引视图与文献主表合并为可读视图。 |
| `build_review_candidate_views(...)` | 构建综述候选视图。 |
| `build_non_review_candidate_views(...)` | 构建非综述候选视图。 |
| `extract_review_candidates(readable_table)` | 从候选视图中抽取综述优先池。 |
| `allocate_reading_batches(index_table, batch_size, review_uid_set)` | 按优先级生成阅读批次。 |
| `build_research_trajectory(items, topic)` | 生成研究脉络摘要。 |
| `build_gate_review(node_uid, node_name, summary, ...)` | 构造闸门审计报告。 |
| `score_gate_review(review, pass_threshold)` | 为闸门报告补充建议动作。 |
| `merge_human_gate_decision(review, human_decision, ...)` | 将人工决策合并回闸门报告。 |

---

### 2.5 综述综合工具

| 函数 | 说明 |
| --- | --- |
| `build_review_consensus_rows(...)` | 构建共识行。 |
| `build_review_controversy_rows(...)` | 构建争议行。 |
| `build_review_future_rows(...)` | 构建未来方向行。 |
| `build_review_general_reading_list(...)` | 构建泛读清单。 |
| `build_review_must_read_originals(...)` | 构建必读原始文献清单。 |
| `extract_review_state_from_attachment(...)` | 从 PDF 附件提取综述状态。 |
| `extract_review_state_from_structured_file(structured_path)` | 从 structured JSON 直接构造综述状态。 |
| `sentence_line_from_review_state(...)` | 综述状态转为单行摘要。 |
| `build_review_reading_packet(...)` | 构建综述阅读包。 |
| `resolve_review_text_by_priority(...)` | 按优先级解析综述文本。 |

---

### 2.6 创新点工具

#### innovation_pool_upsert

```python
def innovation_pool_upsert(
    pool_table: DataFrame,
    innovation_item: dict,
    ...
) -> dict
```

插入或更新创新点池记录。

#### innovation_feasibility_score

```python
def innovation_feasibility_score(innovation_item: dict) -> dict
```

输出创新点四维可行性评分（价值、数据、方法、时间）。

---

### 2.7 PDF/结构化数据工具

| 函数 | 说明 |
| --- | --- |
| `build_structured_data_payload(...)` | 构造统一 `aok.pdf_structured.v3` 结果。 |
| `load_structured_data(structured_path)` | 加载 structured JSON。 |
| `extract_reference_lines_from_structured_data(...)` | 从 structured 数据提取参考文献行。 |
| `extract_pdf_elements_from_structured_data(...)` | 从 structured 数据提取 PDF 元素。 |
| `extract_pdf_elements_from_structured_file(path)` | 从 structured JSON 文件提取 PDF 元素。 |
| `render_pdf_pages_to_png(pdf_path, output_dir, ...)` | PDF 页面渲染为 PNG。 |
| `crop_image_by_normalized_bbox(img_path, bbox, ...)` | 按归一化边界框裁剪图像。 |
| `load_single_document_record(...)` | 从 structured 输入解析旧兼容文档记录。 |
| `load_document_records_from_structured_source(...)` | 批量生成兼容文档记录。 |
| `build_doc_record_from_structured_data(...)` | 从 structured 数据构造文档记录。 |
| `build_chunk_entries_from_structured_data(...)` | 从 structured payload 生成 chunk 条目。 |
| `write_chunk_shards(chunks, output_dir, ...)` | 写出 chunk shards 与 manifest。 |
| `iter_chunk_files_from_manifest(manifest_path)` | 从 manifest 解析 chunk 分片路径。 |

---

### 2.8 AOB 用户内容工具

AOB（Autodo Office Business）负责 `autodo-lib` 内容库与用户本地 AI 办公区之间的聚合、发布、同步、备份与转换。

**原子入口（事务直调用）**：

| 函数 | 说明 |
| --- | --- |
| `aob_validate_content(input_path, repo_root)` | 执行 AOC 内容合法性校验。 |
| `aob_sync_items(strategy, dry_run, repo_root)` | 同步内容库清单 `database/items.csv`。 |
| `aob_aggregate_user_content(source_paths, scopes, project_dirs, home_dir, dry_run, ...)` | 聚合用户级 AI 内容到 canonical AOL。 |
| `aob_publish_user_content(target_paths, scopes, project_dirs, home_dir, engine_vendors, ide_vendors, ...)` | 将 canonical AOL 发布回用户办公区。 |
| `aob_backup_user_content(target_paths, scopes, project_dirs, home_dir, backup_dir, ...)` | 备份用户级 AI 内容。 |
| `aob_update_user_content(target_paths, scopes, project_dirs, home_dir, ...)` | 一键双向同步：备份→反编译→判定→写回→发布。 |
| `aob_import_external_templates(...)` | 导入外部模板并联动同步。 |
| `aob_convert_workspace(...)` | 跨引擎办公区转换（如 `.opencode` ↔ `.claude`）。 |
| `aob_deploy_workflow(...)` | 按 workflow + engine 安装部署。 |
| `aob_check_opencode_deploy_regression(...)` | OpenCode 最小部署回归检查。 |

**CLI 兼容入口**：

| 函数 | 对应的原子入口 |
| --- | --- |
| `run_aob_aoc(argv)` | AOC CLI 兼容封装。 |
| `run_aob_deploy(argv)` | `aob_deploy_workflow`。 |
| `run_aob_library(argv)` | `aob_sync_items`。 |
| `run_aob_workflow_deploy(...)` | `aob_deploy_workflow`。 |
| `run_aob_items_sync(...)` | `aob_sync_items`。 |
| `run_aob_aggregate_user_content(...)` | `aob_aggregate_user_content`。 |
| `run_aob_publish_user_content(...)` | `aob_publish_user_content`。 |
| `run_aob_backup_user_content(...)` | `aob_backup_user_content`。 |
| `run_aob_update_user_content(...)` | `aob_update_user_content`。 |
| `run_aob_external_templates_import(...)` | `aob_import_external_templates`。 |
| `run_aob_workspace_convert(...)` | `aob_convert_workspace`。 |
| `run_aob_regression_opencode_deploy_check(argv)` | `aob_check_opencode_deploy_regression`。 |

原子入口的 `scopes` 参数支持 `"global"`、`"system"`、`"user"`、`"project"`；`project_dirs` 用于指定项目根列表。

---

### 2.9 在线检索工具

#### run_online_retrieval_router

```python
def run_online_retrieval_router(payload: dict) -> dict
```

在线检索统一入口。内部按请求画像→路由→编排→执行四层处理。

payload 核心字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source` | `str` | 来源：`zh_cnki`、`en_open_access`、`deepxiv`、`school_foreign_database_portal`。 |
| `mode` | `str` | 模式：`metadata`、`download`、`html_extract`、`catalog`。 |
| `action` | `str` | 动作：`search`、`single`、`batch`、`fetch`。 |
| `seed_items` | `list[dict]` | 可选，每项可含 `cite_key`、`pdf_path`、`title`、`detail_url`。 |
| `cite_keys` | `list[str]` | 可选，批量文献引用键。 |
| `pdf_paths` | `list[str]` | 可选，批量 PDF 路径。 |
| `content_db` / `content_db_path` | `str` | 可选，提供后自动补齐 `title`/`pdf_path`。 |
| `retrieval_rules` | `dict` | 可选，覆盖默认规则。 |

#### run_online_retrieval_from_bib

```python
def run_online_retrieval_from_bib(payload: dict) -> dict
```

根据 Bib 文件批量执行在线检索（通过路由层统一入口）。

payload 核心字段：`bib_path`、`output_dir`、`max_pages`、`en_per_page`、`en_sources`、`max_entries`、`use_llm_matching`、`llm_api_key_file`。

#### manage_online_retrieval_daily_usage

```python
def manage_online_retrieval_daily_usage(payload: dict) -> dict
```

管理在线检索 provider 的每日请求次数（如 DeepXiv 配额）。

payload 核心字段：`action`（`record`/`get`/`list`/`reset`）、`provider`（默认 `deepxiv`）、`count`、`date`、`daily_limit`、`event_kind`、`endpoint_family`、`timezone_name`。

返回字段：`count`、`daily_limit`、`remaining`、`usage_ratio`、`by_event`、`by_endpoint`。

---

### 2.10 事务请求总线

模块：`autodokit.tools.affair_request_bus`

将 A020/A040/A045/A050/A055 登记为正式事务请求，并完成装载与 dispatch。

| 函数 | 说明 |
| --- | --- |
| `register_a020_import_request(...)` | A020 导入请求登记。 |
| `register_a040_retrieval_request(...)` | A040 检索请求登记。 |
| `register_a040_requests_from_feedback(...)` | 批量从阅读反馈登记 A040 请求。 |
| `register_a045_download_request(...)` | A045 下载请求登记。 |
| `register_a050_preprocess_request(...)` | A050 预处理请求登记。 |
| `register_a055_preprocess_request(...)` | A055 统一预处理执行请求登记。 |
| `load_affair_request_payload(request_uid, ...)` | 装载请求 payload。 |
| `build_affair_request_runtime_config(...)` | 生成 runtime config。 |
| `dispatch_affair_request(request_uid, ...)` | 分发单条请求。 |
| `dispatch_pending_affair_requests(...)` | 分发待处理请求清单。 |

请求数据流：

1. 请求主记录写入 `tasks.db.事务请求`。

---

### 2.11 CrossRef 题录验证工具

模块：`autodokit.tools.atomic.crossref`

通过 CrossRef REST API 验证文献题录的元数据准确性，支持三条粒度：

| 函数 | 说明 |
| --- | --- |
| `crossref_search(title, author_last, rows, timeout)` | CrossRef API 检索，返回结构化题录列表。 |
| `crossref_match_score(bib_title, bib_author, results, pass_threshold)` | 计算 bib 条目与 CrossRef 结果的匹配评分（0-100）。 |
| `crossref_verify_single(title, author_raw, bib_year, pass_threshold, rate_limit)` | 单条文献验证，返回 PASS/PARTIAL 判定。 |
| `crossref_batch_verify(entries, batch_size, pass_threshold, rate_limit, progress_callback)` | 批量验证，支持进度回调。 |
| `crossref_verify_tracker(tracker_path, pass_threshold, rate_limit, filter_is_chinese, inplace)` | 直接读取 JSONL 追踪文件并批量验证。 |

#### crossref_search

```python
def crossref_search(
    title: str,
    author_last: str = "",
    rows: int = 5,
    timeout: int = 30,
    user_agent: str = "AOK-BibVerifier/1.0",
) -> list[dict]
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | `str` | 是 | 文献标题（自动截断至 200 字符）。 |
| `author_last` | `str` | 否 | 作者姓氏。 |
| `rows` | `int` | 否 | 最多返回条数，默认 5。 |
| `timeout` | `int` | 否 | HTTP 超时秒数，默认 30。 |
| `user_agent` | `str` | 否 | 请求 UA 标识。 |

返回列表每项含：`title`、`author`、`year`、`journal`、`doi`、`score`。

#### crossref_match_score

```python
def crossref_match_score(
    bib_title: str,
    bib_author: str,
    crossref_results: list[dict],
    pass_threshold: int = 50,
) -> tuple[float, dict | None]
```

评分构成：标题词重叠（60 分）+ 作者姓氏匹配（20 分）+ API 评分归一化（20 分）。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `bib_title` | `str` | 是 | 待验证文献标题。 |
| `bib_author` | `str` | 是 | 作者字符串，如 `"Acemoglu D and Ozdaglar A"`。 |
| `crossref_results` | `list[dict]` | 是 | `crossref_search()` 返回的结果。 |
| `pass_threshold` | `int` | 否 | PASS 阈值，默认 50。 |

返回 `(best_score, best_result)`。

#### crossref_verify_single

```python
def crossref_verify_single(
    title: str,
    author_raw: str,
    bib_year: str = "",
    pass_threshold: int = 50,
    rate_limit: float = 0.8,
) -> dict
```

返回 dict 含 `status`（`PASS`/`PARTIAL`）、`score`、`doi`、`matched_year`、`notes`、`checked_at`。

#### crossref_batch_verify

```python
def crossref_batch_verify(
    entries: list[dict],
    batch_size: int = 20,
    pass_threshold: int = 50,
    rate_limit: float = 0.8,
    progress_callback: collections.abc.Callable | None = None,
) -> list[dict]
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `entries` | `list[dict]` | 是 | 待验证条目列表，每条需含 `cite_key`、`title`、`author`、`year`。 |
| `rate_limit` | `float` | 否 | API 调用间隔（秒），默认 0.8。 |
| `progress_callback` | `callable` | 否 | `fn(processed, total, result_dict)`。 |

#### crossref_verify_tracker

```python
def crossref_verify_tracker(
    tracker_path: str | Path,
    pass_threshold: int = 50,
    rate_limit: float = 0.8,
    filter_is_chinese: bool | None = False,
    inplace: bool = True,
) -> dict
```

直接读取 `bib_verification_tracker.jsonl`，自动筛选待验证条目并执行 CrossRef 验证。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `tracker_path` | `str\|Path` | 是 | JSONL 追踪文件路径。 |
| `filter_is_chinese` | `bool\|None` | 否 | `False`=仅英文，`True`=仅中文，`None`=全部。 |
| `inplace` | `bool` | 否 | 是否直接更新追踪文件，默认 `True`。 |

返回运行摘要：`total`、`pass_count`、`partial_count`、`status_summary`。

示例：

```python
from autodokit.tools import crossref_verify_tracker

summary = crossref_verify_tracker(
    "tasks/bib_verification_tracker.jsonl",
    filter_is_chinese=False,
)
print(f"PASS={summary['pass_count']} PARTIAL={summary['partial_count']}")
```
2. payload 写入 `workspace/tasks/requests/<UID>/payload.json`。
3. dispatch 前从 `affair_entry_registry.json` 解析 `config_path`。
4. 通过 `run_affair()` 执行。
5. 结果写入 `workspace/tasks/requests/<UID>/dispatch_result.json`。

---

### 2.11 任务数据库工具

模块：`autodokit.tools.atomic.task_aok`

| 函数 | 说明 |
| --- | --- |
| `bootstrap_aok_taskdb(project_root, ...)` | 初始化 AOK 任务数据库骨架。 |
| `validate_aok_taskdb(project_root, ...)` | 校验 AOK 任务数据库一致性。 |
| `task_create_or_update(tasks, task, workspace_root, ...)` | 创建或更新任务主表记录。 |
| `task_get(tasks, artifacts, uid_任务)` | 读取任务详情与产物列表。 |
| `task_bind_literatures(tasks, uid_任务, 文献UID列表, ...)` | 绑定文献 UID 列表。 |
| `task_bind_knowledges(tasks, uid_任务, 知识UID列表, ...)` | 绑定知识 UID 列表。 |
| `task_artifact_register(tasks, artifacts, uid_任务, ...)` | 登记任务产物。 |
| `task_bundle_export(artifacts, uid_任务, output_dir)` | 导出任务产物集合。 |
| `task_status_append(status_log, uid_任务, status, ...)` | 追加任务状态流转日志。 |
| `task_gate_decision_record(gate_decisions, uid_任务, ...)` | 登记闸门决策。 |
| `task_handoff_record(handoffs, uid_来源任务, uid_目标任务, ...)` | 登记任务交接。 |
| `task_relation_upsert(relations, uid_来源任务, uid_目标任务, ...)` | 维护任务关系。 |
| `task_round_snapshot_register(round_views, uid_任务, ...)` | 登记轮次快照。 |
| `task_release_register(releases, uid_任务, ...)` | 登记阶段发布物。 |
| `task_release_promote(releases, uid_任务, uid_发布, ...)` | 发布提升。 |
| `task_literature_binding_register(bindings, uid_任务, uid_文献, ...)` | 登记任务-文献绑定。 |
| `task_knowledge_binding_register(bindings, uid_任务, uid_知识, ...)` | 登记任务-知识绑定。 |

配套 Git 快照子模块（`autodokit.tools.atomic.task_aok.git_snapshot_ledger`）：

| 函数 | 说明 |
| --- | --- |
| `ledger_init(workspace_root, ...)` | 初始化极简任务账本。 |
| `ledger_record_task_run(...)` | 登记节点运行结果。 |
| `git_workspace_init(workspace_root, ...)` | 在 workspace 下初始化本地 Git 仓库。 |
| `git_create_snapshot_for_task(workspace_root, ...)` | 执行 `git add -A`、`git commit`、`git tag` 并写账本。 |
| `git_rollback_by_task_uid(workspace_root, ...)` | 按 `task_uid` 登记回滚计划。 |

---

### 2.12 日志工具

模块：`autodokit.tools.atomic.log_aok`

| 函数 | 说明 |
| --- | --- |
| `bootstrap_aok_logdb(project_root, ...)` | 初始化日志库。 |
| `validate_aok_logdb(project_root, ...)` | 校验日志库。 |
| `append_aok_log_event(project_root, event_type, ...)` | 追加常规事件日志。 |
| `list_aok_log_events(project_root, ...)` | 按条件查询事件日志。 |
| `record_aok_log_artifact(...)` | 登记产物与事件关联。 |
| `record_aok_gate_review(...)` | 登记 gate 审计意见。 |
| `record_aok_human_decision(...)` | 登记人工决策。 |
| `repair_aok_logdb(project_root, ...)` | 修复日志库异常形态。 |

状态语义：`PASS`（成功）、`SKIPPED`（跳过）、`BLOCKED`（阻断）。

---

### 2.13 数据库管理工具

#### 统一内容主库

| 函数 | 说明 |
| --- | --- |
| `init_content_db(db_path)` | 初始化统一内容主库（建表、补列、补索引、刷新视图）。 |
| `resolve_content_db_path(db_path)` | 旧平铺路径解析到统一路径。 |

#### 文献数据库（SQLite-first）

| 函数 | 说明 |
| --- | --- |
| `init_references_db(db_path)` | 初始化文献主库（兼容入口）。 |
| `load_reference_tables(db_path, ...)` | 读取文献主表与附件表。 |
| `persist_reference_tables(literatures_df, attachments_df, db_path, ...)` | 写回文献主库。 |
| `save_reference_tables(...)` | `persist_reference_tables` 别名。 |

#### 知识数据库（SQLite-first）

| 函数 | 说明 |
| --- | --- |
| `init_knowledge_db(db_path)` | 初始化知识主库（兼容入口）。 |
| `load_knowledge_tables(db_path, ...)` | 读取知识索引表与附件表。 |
| `persist_knowledge_tables(index_df, attachments_df, db_path, ...)` | 写回知识主库。 |
| `load_index_df(...)` | 读取知识索引表。 |
| `load_knowledge_attachments_df(...)` | 读取知识附件表。 |
| `save_knowledge_tables(...)` | `persist_knowledge_tables` 别名。 |

#### content.db 直接读写

| 函数 | 说明 |
| --- | --- |
| `load_literatures_df(db_path)` | 读取文献主表。 |
| `load_literature_attachment_links_df(db_path)` | 读取文献附件关联。 |
| `load_literature_attachments_df(db_path)` | 读取附件总视图。 |
| `load_attachment_entities_df(db_path)` | 读取附件实体表。 |
| `load_literature_tags_df(db_path)` | 读取文献标签关联。 |
| `load_author_entities_df(db_path)` | 读取作者表。 |
| `load_literature_author_links_df(db_path)` | 读取文献作者关联。 |
| `load_knowledge_literature_links_df(db_path)` | 读取知识-文献关系表。 |
| `load_knowledge_evidence_links_df(db_path)` | 读取知识证据关系表。 |

#### 文献主表附属工具

| 函数 | 说明 |
| --- | --- |
| `build_literature_main_table(...)` | 构造文献主表。 |
| `build_literature_main_audit_csv(...)` | 生成文献主表审计 CSV。 |
| `build_literature_attachment_inverted_index(...)` | 构造附件倒排索引。 |
| `build_literature_tag_inverted_index(...)` | 构造标签倒排索引。 |
| `build_entity_to_literatures_csv(...)` | 构造实体-文献映射 CSV。 |
| `build_stable_attachment_uid(...)` | 生成稳定附件 UID。 |

#### chunk 状态接口

| 函数 | 说明 |
| --- | --- |
| `load_chunk_sets_df(db_path)` | 读取 chunk 批次索引表。 |
| `load_chunks_df(db_path)` | 读取 chunk 明细索引表。 |
| `save_structured_state(db_path, uid_文献, ...)` | 回写 `structured_*` 状态字段。 |
| `get_structured_state(db_path, uid_文献)` | 读取单篇文献结构化状态。 |
| `replace_chunk_set_records(db_path, chunk_set_row, chunk_rows)` | 整批替换 chunk 批次与明细。 |

---

### 2.14 路径迁移工具

#### PathMapping

```python
@dataclass
class PathMapping:
    old_root: str
    new_root: str
```

#### migrate_workspace_paths

```python
def migrate_workspace_paths(
    workspace_root: str | Path,
    mappings: list[PathMapping],
    dry_run: bool = False,
    inventory_only: bool = False,
    scan_dirs: list[str] | None = None,
    sqlite_rel_paths: list[str] | None = None,
    excluded_prefixes: list[str] | None = None,
) -> dict
```

工作区迁移到新设备或目录后，统一扫描并重写旧绝对路径。

当 `inventory_only=True` 时只输出命中清单；默认排除 `.copilot` 与 Windows 系统目录。

---

### 2.15 翻译工具

| 函数 | 说明 |
| --- | --- |
| `translate_literature_metadata(payload)` | 翻译文献元数据（标题、摘要、关键词）。 |
| `translate_standard_note(payload)` | 翻译标准笔记内容。 |
| `translate_parse_asset_text(payload)` | 翻译解析资产生文本。 |
| `run_literature_translation(config)` | 批量文献翻译事务入口。 |

常量：`DEFAULT_TRANSLATION_POLICY`。

---

### 2.16 数据清洗工具

| 函数 | 说明 |
| --- | --- |
| `normalize_primary_fulltext_attachment_names(payload)` | 主附件规范化命名。 |
| `resolve_primary_attachment_normalization_settings(...)` | 解析主附件命名设置。 |
| `refresh_author_entities(payload)` | 作者清洗与回填。 |
| `preprocess_author_names_with_aliyun(payload)` | 用阿里百炼预处理作者姓名。 |
| `normalize_content_db_author_names_with_aliyun(payload)` | 对 content.db 执行作者姓名回填。 |
| `detect_and_clean_literature_title_braces(payload)` | 标题花括号检测与清洗。 |
| `isolate_unmatched_attachments(payload)` | 孤儿附件隔离。 |

---

### 2.17 Obsidian 时间工具

| 函数 | 说明 |
| --- | --- |
| `get_current_time_iso(timezone_name="Asia/Shanghai")` | 当前时间 ISO 字符串。 |
| `convert_timestamp_to_timezone(timestamp, target_timezone, ...)` | 时间戳时区转换。 |
| `rewrite_obsidian_note_timestamps(note_path, target_timezone, ...)` | 改写单篇笔记时间字段时区。 |
| `batch_rewrite_obsidian_note_timestamps(note_paths, note_dir, target_timezone, ...)` | 批量改写。 |

常量：`DEFAULT_OBSIDIAN_NOTE_TIMEZONE`（`"Asia/Shanghai"`）、`DEFAULT_OBSIDIAN_TIME_FIELDS`。

---

### 2.18 CNKI 工具

#### build_cnki_result

```python
def build_cnki_result(...) -> dict
```

将 CNKI 检索结果解析为标准题录记录。

---

### 2.19 TeX DAG 工具

```python
from autodokit.tools import scan_tex_graph, export_tex_graph, rewire_tex_reference, set_tex_root
```

| 函数 | 说明 |
| --- | --- |
| `scan_tex_graph(root_dir, exclude_glob)` | 扫描 `.tex` 引用关系，返回 `TexGraph`。 |
| `export_tex_graph(root_dir, format, output, exclude_glob)` | 导出引用图为 `text`/`json`/`mermaid`/`dot`。 |
| `rewire_tex_reference(root_dir, parent, old_target, new_target, sync_root, recursive, dry_run)` | 重连父文件中的子文档引用。 |
| `set_tex_root(root_dir, file, root, recursive, dry_run)` | 重设子文件的 `subfiles` 根引用。 |

---

### 2.20 MonkeyOCR 工具

多后端文档解析工具，支持二维正交执行架构：

| | 本地 (local) | 远端 (remote) |
|---|---|---|
| **CUDA** | Windows + NVIDIA GPU | SSH 远端 |
| **MLX** | macOS Apple Silicon GPU | SSH 远端 |
| **CPU** | 纯 CPU（需人工确认） | SSH 远端 |

#### 统一入口: run_monkeyocr_single_pdf

```python
from autodokit.tools import run_monkeyocr_single_pdf

def run_monkeyocr_single_pdf(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    runtime_settings: dict,
    execution_mode: Literal["auto", "local", "remote"] = "auto",
    compute_backend: Literal["auto", "cuda", "mlx", "cpu"] = "auto",
    output_name: str | None = None,
    timeout: int = 3600,
    poll_interval: int = 10,
    allow_local_fallback: bool = True,
) -> dict
```

全自动解析单篇 PDF。默认 `execution_mode="auto"` 优先远端，失败回退本地。
本地模式下默认 `compute_backend="auto"` 自动检测：CUDA → MLX → CPU（需人工确认）。

返回字段：`status`、`backend`、`gpu_name`、`input_pdf`、`output_dir`、`artifacts`。

#### CUDA 后端: prepare_monkeyocr_windows_runtime / run_monkeyocr_windows_single_pdf

仅限 Windows + NVIDIA GPU。

```python
from autodokit.tools import prepare_monkeyocr_windows_runtime, run_monkeyocr_windows_single_pdf
```

```python
def prepare_monkeyocr_windows_runtime(
    monkeyocr_root: str | Path,
    model_name: str = "MonkeyOCR-pro-1.2B",
    download_source: str = "huggingface",
    python_executable: str | None = None,
    pip_index_url: str | None = None,
    install_triton_windows: bool = True,
    models_dir: str | Path | None = None,
) -> dict
```

安装依赖并下载模型权重。返回字段：`model_dir`、`weights_ready`、`steps`。

```python
def run_monkeyocr_windows_single_pdf(
    input_pdf: str | Path,
    output_dir: str | Path,
    monkeyocr_root: str | Path,
    models_dir: str | Path | None = None,
    config_path: str | Path | None = None,
    device: str = "cuda",
    gpu_visible_devices: str = "0",
    ensure_runtime: bool = False,
    download_source: str = "huggingface",
    pip_index_url: str | None = None,
    log_path: str | Path | None = None,
    stream_output: bool = False,
) -> dict
```

以 GPU 路线解析单篇 PDF。返回字段：`status`、`device`、`gpu_name`、`input_pdf`、`output_dir`、`artifacts`。

#### MLX 后端: prepare_monkeyocr_mlx_runtime / run_monkeyocr_mlx_single_pdf

仅限 macOS Apple Silicon (ARM64)。使用 MLX-VLM 调用 Metal GPU。

```python
from autodokit.tools import prepare_monkeyocr_mlx_runtime, run_monkeyocr_mlx_single_pdf
```

```python
def prepare_monkeyocr_mlx_runtime(
    monkeyocr_root: str | Path,
    model_name: str = "MonkeyOCR-pro-1.2B",
    download_source: str = "huggingface",
    python_executable: str | Path | None = None,
    pip_index_url: str | None = None,
    models_dir: str | Path | None = None,
) -> dict
```

安装 mlx、mlx-vlm 等依赖并下载模型权重。返回字段：`model_dir`、`mlx_ready`、`steps`。

```python
def run_monkeyocr_mlx_single_pdf(
    input_pdf: str | Path,
    output_dir: str | Path,
    monkeyocr_root: str | Path,
    models_dir: str | Path | None = None,
    config_path: str | Path | None = None,
    device: str | None = None,
    ensure_runtime: bool = False,
    download_source: str = "huggingface",
    pip_index_url: str | None = None,
    log_path: str | Path | None = None,
    stream_output: bool = False,
) -> dict
```

以 MLX/Apple GPU 路线解析单篇 PDF。返回字段同上。

#### 设备检测工具

```python
from autodokit.tools import detect_cuda, detect_mlx, detect_available_backends, get_best_backend, get_gpu_name
```

| 函数 | 返回 | 说明 |
| --- | --- | --- |
| `detect_cuda()` | `bool` | PyTorch CUDA 是否可用 |
| `detect_mlx()` | `bool` | Apple MLX 是否可用 |
| `detect_available_backends()` | `list[str]` | 按优先级排列的可用后端 |
| `get_best_backend()` | `str` | 最优后端 (`"cuda"` / `"mlx"` / `"cpu"`) |
| `get_gpu_name()` | `str \| None` | GPU 名称 |

#### CPU 回退确认

```python
from autodokit.tools import confirm_cpu_fallback
```

当自动检测无 GPU 可用时，`confirm_cpu_fallback(reason=...)` 会在 stderr 打印警告并通过 `input()` 等待用户确认。不确认则 `SystemExit(1)`。在 CI 环境中可设置环境变量 `MONKEYOCR_CPU_AUTO_CONFIRM=1` 跳过交互。

#### 远端管理

```python
from autodokit.tools import run_monkeyocr_remote, stop_remote_monkeyocr_jobs, launch_remote_tmux_command
```

| 函数 | 说明 |
| --- | --- |
| `run_monkeyocr_remote(...)` | 显式远端运行（兼容旧入口） |
| `stop_remote_monkeyocr_jobs(settings)` | 停止远端遗留的 tmux/parse.py |
| `launch_remote_tmux_command(settings, remote_command=...)` | 在远端 tmux 中执行命令 |

---

### 2.21 通用辅助工具

| 函数 | 说明 |
| --- | --- |
| `ensure_absolute_output_dir(output_dir, config_path)` | 确保输出目录为绝对路径并可创建。 |
| `write_affair_json_result(output_dir, filename, data)` | 将事务结果写入固定 JSON 文件。 |
| `load_json_or_py(path)` | 加载 JSON 或 Python 配置文件。 |
| `find_repo_root(path)` | 向上查找仓库根目录（`.git` 或 `pyproject.toml`）。 |
| `resolve_path_from_base(base, raw_path)` | 基于基路径解析相对路径。 |
| `resolve_paths_to_absolute(config, workspace_root)` | 递归将配置中的路径字段绝对化。 |
| `resolve_path_with_workspace_root(workspace_root, raw_path)` | 基于工作区根解析路径。 |
| `resolve_workflow_config_path(path)` | 解析工作流配置路径。 |
| `append_flow_trace_event(trace_file, event)` | 追加流程跟踪事件到 JSONL。 |
| `evaluate_expression(expression, names)` | 安全表达式求值。返回 `ExpressionEvalResult`。 |
| `evaluate_predicate(expression, names)` | 安全谓词求值，返回 `bool`。 |

#### Zotero RDF 转换

```python
def convert_zotero_rdf_to_a020_incremental_package(
    rdf_path: str | Path,
    ...
) -> dict
```

将 Zotero 导出的 RDF 转为 A020 增量导入输入包。

#### Zotero 标签提取

```python
def extract_zotero_all_tags(
    endpoint: str | None = None,
    concurrency: int = 20,
    progress_callback: Any = None,
) -> dict
```

通过 cookjohn MCP 从 Zotero 提取所有条目的标签，去重统计。

- `endpoint`: MCP HTTP 端点，默认 `http://127.0.0.1:23120/mcp`。
- `concurrency`: 并发线程数。
- `progress_callback`: 可选进度回调 `(done, total, tags_found) -> None`。

返回统一结果字典，`data.tags` 为 `[{tag, count, type}]` 格式。

```python
def save_zotero_tags_to_jsonl(
    output_path: str | Path,
    endpoint: str | None = None,
    concurrency: int = 20,
) -> dict
```

提取并保存为 JSONL 文件，每条记录包含 `tag`、`count`、`type`（auto/manual）字段。

---

### 2.14 会议转写工具（third_party）

**部署位置**：`third_party/meeting-transcriber-whispercpp/`

跨平台通用会议录音转写调度器，按设备自动选择最优后端。

#### 统一入口 CLI

```bash
python scripts/transcribe_meeting.py \
    --backend auto \
    --audio meeting.m4a \
    --output-dir ./output \
    --language zh --threads 8
```

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `--backend` | `auto\|apple-whispercpp\|cuda-funasr` | `auto` | 转写后端。`auto` 自动检测 Apple Silicon → apple-whispercpp |
| `--audio` | `str` | **必填** | 音频文件路径（m4a/mp3/wav/flac/ogg） |
| `--output-dir` | `str` | `.` | 输出目录 |
| `--model` | `str` | `small` | whisper 模型 (tiny/base/small/medium/large)，仅 apple-whispercpp |
| `--language` | `str` | `auto` | 语言代码 (zh/en/ja/auto) |
| `--threads` | `int` | `4` | CPU 线程数 |
| `--vad` | flag | 否 | 启用 VAD 过滤静音段 |
| `--prompt` | `str` | 无 | 初始提示文本辅助识别 |
| `--no-gpu` | flag | 否 | 禁用 GPU 加速 |

以下参数仅 `cuda-funasr` 后端生效：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `--thesis` | `str` | 无 | 论文 TeX 路径（CUDA 后端必需） |
| `--n-speakers` | `int` | `4` | 预估说话人数 |
| `--speaker-aliases` | `str` | `导师,我,LH,WX` | 说话人别名 |
| `--diarization-backend` | `str` | `auto` | 说话人分离后端 (pyannote/kmeans) |

#### 后端架构

```
transcribe_meeting.py (统一调度入口)
├── apple-whispercpp → third_party/meeting-transcriber-whispercpp/bin/transcribe_meeting_apple.py
│    └── whisper.cpp + Metal GPU（macOS Apple Silicon，本地离线）
└── cuda-funasr → scripts/transcribe_meeting_cuda_legacy.py
     └── FunASR + pyannote/kmeans（Windows/NVIDIA GPU，含说话人分离）
```

#### 输出格式

**apple-whispercpp**：TXT（纯文本）、JSON（分段+时间戳）、CSV、`_会议记录.md`（带时间戳分段）

**cuda-funasr**：完整会议记录（成稿版）+ 会议记录整理稿（纪要版），含说话人标注

#### Python 直接调用

```python
# 通过 subprocess 调用 Apple wrapper
import subprocess, sys
from pathlib import Path

wrapper = Path("third_party/meeting-transcriber-whispercpp/bin/transcribe_meeting_apple.py")
subprocess.run([
    sys.executable, str(wrapper),
    "--audio", "meeting.m4a",
    "--output-dir", "output/",
    "--language", "zh", "--threads", "8",
], check=True)
```

---

## 3. 事务索引

所有事务统一通过 `autodokit.run_affair(affair_uid="...", config_path="...")` 调用。

事务配置模板位于 `autodokit/affairs/<事务名>/affair.json`。运行时可通过 `config` 参数覆盖任意字段。

### 3.1 事务全量表

以下列出所有具备 `affair.py` 的事务（共约 90 个）。仅含 `affair.json` 而无 `affair.py` 的事务暂不可通过 `run_affair()` 直调。

| 事务名 | 配置模板 | 主要输出 |
| --- | --- | --- |
| 导入和预处理文献元数据 | `affair.json` | `import_result.json` |
| 检索治理 | `affair.json` | `a040_result.json` |
| 文献下载与主附件入库 | —（委托检索治理） | `a045_result.json` |
| 统一文献预处理解析 | `affair.json` | `gate_review.json` / `a055_*.json` |
| 候选文献视图构建 | `affair.json` | 候选视图 CSV / JSON |
| 综述预处理 | `affair.json` | —（委托候选文献视图构建） |
| 非综述候选种子生成 | — | `a075_seed_candidates.json` |
| 非综述候选视图构建 | `affair.json` | 非综述候选视图 |
| 普通文献研读候选视图构建 | — | 研读候选视图 |
| 文献研读与正式知识回写 | `affair.json` | 标准笔记 / 知识回写 |
| 文献矩阵 | `affair.json` | 文献矩阵输出 |
| 创新点池构建 | `affair.json` | 创新点池 |
| 单篇粗读 | `affair.json` | `rough_reading_{uid}.md` + `.json` |
| 单篇精读 | `affair.json` | `single_reading_{uid}.md` |
| PDF文件转结构化数据文件 | `affair.json` | `{cite_key}.structured.json` + manifest |
| 解析与分块 | `affair.json` | `chunk_manifest.json` + shards |
| 向量化与索引构建 | `affair.json` | `tfidf.npz` + `vocab.json` |
| 综述草稿生成 | `affair.json` | `review_draft.md` |
| 模型路由派发 | `affair.json` | `model_routing_dispatch_result.json` |
| AOK任务数据库初始化 | `affair.json` | `aok_taskdb_bootstrap_result.json` |
| AOK任务数据库校验 | `affair.json` | `aok_taskdb_validate_result.json` |
| AOB统一业务事务 | `affair.json` | `aob_business_result.json` |
| Skill渲染 | `affair.json` | `skill_render_result.json` |
| LaTeX转Word | `affair.json` | `.docx` |
| Word转LaTeX | `affair.json` | `.tex` |
| AOK三库联动示例 | `affair.json` | `aok_triple_db_demo_result.json` |
| 项目初始化 | `affair.json` | 三库初始化产物 |
| 工作区自检 | `affair.json` | 自检报告 |
| 工作流执行 | `affair.json` | 流程图执行结果 |
| 生成关键词集合 | `affair.json` | 关键词集合 |
| 合并去重bibtex | `affair.json` | 去重后 bib 文件 |
| 合并去重文献元数据 | `affair.json` | 去重后元数据 |
| 清洗bibtex文件 | `affair.json` | 清洗后 bib |
| 生成文献元数据关系图 | `affair.json` | 关系图 |
| 语义预筛选 | `affair.json` | 预筛选结果 |
| 知识预筛选 | `affair.json` | 预筛选结果 |
| 白名单治理检查 | `affair.json` | 治理检查报告 |
| 百炼SDK接入检查 | `affair.json` | 接入检查报告 |
| 引文核验 | `affair.json` | 引文核验结果 |
| 文献阅读规划 | `affair.json` | 阅读规划 |
| 标准文献笔记生成 | `affair.json` | 标准笔记 |
| 阅读优先级生成 | `affair.json` | 优先级清单 |
| 本地文献导入 | `affair.json` | 导入结果 |
| 自动化导入知网研学专题 | `affair.json` | 导入结果 |
| 变量操作化 | `affair.json` | 变量定义 |
| 数据工程样本构建 | `affair.json` | 样本数据 |
| 计量环境配置 | `affair.json` | 环境配置 |
| 实证四件套 | `affair.json` | 实证结果 |
| DiD_RDD分析 | `affair.json` | 分析结果 |
| 方法白名单选择 | `affair.json` | 方法选择 |
| 结果分析解读 | `affair.json` | 分析解读 |
| 研究构思 | `affair.json` | 研究构思 |
| 研究诚信检查 | `affair.json` | 诚信检查报告 |
| 证据综合 | `affair.json` | 证据综合 |
| 论文草稿 | `affair.json` | 论文草稿 |
| 论文整编写作 | `affair.json` | 整编结果 |
| 论文自审 | `affair.json` | 自审报告 |
| 审稿意见拆解 | `affair.json` | 拆解结果 |
| 审稿回复 | `affair.json` | 回复草稿 |
| 外审意见接收 | `affair.json` | 分流建议 |
| 期刊投稿 | `affair.json` | 投稿材料 |
| 成果归档发布 | `affair.json` | 归档产物 |
| 中文本地资源管理 | `affair.json` | 资源清单 |
| 中文网页采集 | `affair.json` | 采集内容 |
| 公开数据获取 | `affair.json` | 数据文件 |
| 管理文档单元数据库 | `affair.json` | 文档单元 |
| 订阅文献访问治理 | `affair.json` | 治理报告 |
| CNKI基础检索 | `affair.json` | 检索结果 |
| CNKI高级检索 | `affair.json` | 检索结果 |
| CNKI结果解析 | `affair.json` | 解析结果 |
| CNKI单篇详情提取 | `affair.json` | 详情数据 |
| CNKI题录导出 | `affair.json` | 题录文件 |
| CNKI翻页导航 | `affair.json` | 翻页结果 |
| CNKI全文下载规划 | `affair.json` | 下载规划 |
| CNKI期刊检索 | `affair.json` | 期刊列表 |
| CNKI期刊目录提取 | `affair.json` | 目录数据 |
| CNKI期刊指标提取 | `affair.json` | 指标数据 |
| CAJ文件转PDF | `affair.json` | PDF 文件 |
| MonkeyOCR批量解析PDF | `affair.json` | OCR 解析结果 |
| PDF文件转md文件 | `affair.json` | Markdown 文件 |
| Obsidian关联导出 | `affair.json` | 导出文件 |
| 单轮调度派发 | `affair.json` | 调度结果 |
| node_runtime_retry_probe | `affair.json` | 探针结果 |
| task_docs_create_latest | `affair.json` | 任务文档 |
| task_docs_aggregate | `affair.json` | 聚合文档 |
| task_docs_finalize_latest | `affair.json` | 定稿文档 |
| task_docs_archive | `affair.json` | 归档文档 |
| AOB用户级内容聚合 | `affair.json` | canonical AOL |
| AOB用户级内容发布 | `affair.json` | 发布结果 |
| AOB用户级内容同步 | `affair.json` | 同步结果 |
| AOB用户级内容备份 | `affair.json` | 备份快照 |

图节点事务（`图节点_start`、`图节点_end`、`图节点_input`、`图节点_output`、`图节点_calc`、`图节点_compare`、`图节点_container`、`图节点_fork`、`图节点_if`、`图节点_merge`、`图节点_switch`）供 autodo-engine 流程图运行时消费，不在本手册展开。

### 3.2 调用示例

```python
from autodokit import run_affair

# 执行检索治理事务
outputs = run_affair(
    affair_uid="检索治理",
    config_path="workspace/config/affairs_config/A040.zh_cnki.json",
)

# 执行单篇精读（运行时覆盖配置）
outputs = run_affair(
    affair_uid="单篇精读",
    config={
        "content_db": "workspace/database/content/content.db",
        "uid_文献": "lit-abc123",
        "use_llm": True,
        "output_dir": "workspace/output/deep_read",
    },
    workspace_root="/home/ethan/workspace",
)
```

详细配置字段说明见 [AOK预置事务手册](AOK预置事务手册.md)。

---

## 4. 辅助入口

### 事务发现与内省

```python
from autodokit.tools import scan_affairs, build_registry, lint_affairs, get_affair_docs

# 扫描全部事务
affairs = scan_affairs()

# 构建注册表
registry = build_registry()

# 检查事务清单完整性
findings = lint_affairs()

# 读取事务文档
docs = get_affair_docs("检索治理")
```

### 模型路由

```python
from autodokit.tools import resolve_model_plan, invoke_aliyun_llm, load_aliyun_llm_config
```

| 函数 | 说明 |
| --- | --- |
| `resolve_model_plan(intent, ...)` | 根据任务语义与质量/成本/时延档位输出主模型与回退链。 |
| `invoke_aliyun_llm(prompt, intent, ...)` | 按路由计划执行调用，失败时按回退链重试，返回 `attempts` 审计。 |
| `load_aliyun_llm_config(...)` | 加载阿里百炼配置（内部走统一路由）。 |

### Word/LaTeX 双向转换

AOK 提供 Word ↔ LaTeX 双向转换能力，Word→LaTeX 默认使用 docx2tex 后端（格式保真度高），Pandoc 作为备选。

#### 模块架构

| 模块 | 功能 | 后端 |
| --- | --- | --- |
| `word_to_latex.py` | Word→LaTeX 双后端主入口 | docx2tex / pandoc |
| `latex_to_word.py` | LaTeX→Word | pandoc |
| `docx2tex_runner.py` | docx2tex 命令执行与可用性检查 | docx2tex |
| `docx2tex_converter.py` | docx2tex 转换封装 + xelatex 后处理 | docx2tex |
| `docx2tex_postprocess.py` | pdflatex→xelatex 前导区替换 + 引用处理 | docx2tex |
| `pandoc_runner.py` | Pandoc 命令执行 | both |
| `pandoc_tex_word_converter.py` | 兼容入口（保留历史导入路径） | both |
| `latex_subfile_merger.py` | `\subfile{}` 递归合并 | — |
| `docx_postprocess.py` | Word 后处理（标题编号、高亮） | — |

#### convert_word_to_latex（主入口）

```python
def convert_word_to_latex(
    input_word_path: Path,
    output_tex_path: Path,
    *,
    backend: Literal["docx2tex", "pandoc"] = "docx2tex",
    include_in_header: Path | None = None,
    latex_template: Path | None = None,
    docx2tex_config: Path | None = None,
    docx2tex_table_model: str | None = None,
    fallback_on_error: bool = True,
    xelatex_postprocess: bool = True,
    bibtex_mode: bool = False,
    compile_after: bool = False,
) -> ConversionResult
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `input_word_path` | `Path` | 是 | 输入的 Word 文件绝对路径。 |
| `output_tex_path` | `Path` | 是 | 输出的 LaTeX 文件绝对路径。 |
| `backend` | `Literal` | 否 | 转换后端：`"docx2tex"`（默认）/ `"pandoc"`。 |
| `fallback_on_error` | `bool` | 否 | docx2tex 失败时自动降级到 Pandoc。 |
| `xelatex_postprocess` | `bool` | 否 | docx2tex 后端输出后执行 xelatex 兼容处理。 |
| `bibtex_mode` | `bool` | 否 | 后处理中提取纯文本引文生成 `.bib`。 |
| `compile_after` | `bool` | 否 | 转换后运行 xelatex 编译输出（默认 False）。 |
| `docx2tex_config` | `Path` | 否 | docx2tex 自定义配置文件。 |
| `docx2tex_table_model` | `str` | 否 | 表格模型：`tabularx`/`tabular`/`htmltabs`。 |

返回 `ConversionResult`：`backend_used`、`return_code`、`output_tex_path`、`fell_back`、`fallback_reason`。

使用示例:
```python
from pathlib import Path
from autodokit.tools.word_to_latex import convert_word_to_latex

# Word → LaTeX（docx2tex + xelatex 后处理）
result = convert_word_to_latex(Path("paper.docx"), Path("paper.tex"))

# 使用 Pandoc 后端
result = convert_word_to_latex(Path("paper.docx"), Path("paper.tex"), backend="pandoc")

# 提取引文生成 .bib
result = convert_word_to_latex(
    Path("paper.docx"), Path("paper.tex"), bibtex_mode=True,
)
print(f"后端: {result.backend_used}, 降级: {result.fell_back}")
```

#### convert_latex_to_word

```python
def convert_latex_to_word(
    input_tex_path: Path,
    output_docx_path: Path,
    *,
    resource_path: Path | None = None,
    resource_paths: Sequence[Path] | None = None,
    include_in_header: Path | None = None,
    reference_doc: Path | None = None,
    toc: bool = True,
) -> PandocResult
```

#### postprocess_docx2tex_for_xelatex

```python
def postprocess_docx2tex_for_xelatex(
    input_tex_path: Path,
    output_tex_path: Path,
    *,
    bibtex_mode: bool = False,
    bib_output_path: Path | None = None,
) -> dict
```

将 docx2tex 原始 pdflatex 输出转为 xelatex 可编译格式。处理步骤：① 移除 `fontenc`/`inputenc`/`babel`/`txfonts` → ② 插入 `fontspec`+`xeCJK` → ③ 注释不可用图片 → ④ 处理引用（no-bibtex/bibtex）。

#### check_docx2tex_available

```python
def check_docx2tex_available() -> bool
```

检查 docx2tex 是否可用（Java + d2t 脚本）。

#### 其他工具

| 函数 | 说明 |
| --- | --- |
| `merge_latex_subfiles(main_tex, output_tex)` | 递归展开 `\subfile{}` 并合并为单个 `.tex`。 |
| `run_pandoc(command)` | 执行 Pandoc 命令并返回结果。 |
| `add_heading_numbering(input_docx, output_docx)` | Word 标题编号后处理。 |
| `highlight_tokens_in_docx(input_docx, output_docx)` | Word 内容高亮后处理。 |

### 2.21 大模型 Provider 与密钥安全工具（统一入口）

所有大模型相关工具统一收口在 `autodokit/tools/atomic/llm/` 子域，只提供一个入口：

```python
from autodokit.tools.atomic.llm import invoke_llm, invoke_aliyun_llm, mask_api_key
```

子模块：`llm_clients`（客户端 + 模型路由 + 阿里百炼）、`llm_providers`（多后端抽象）、
`llm_parsing`（输出解析）、`secrets_manager`（密钥与脱敏）。

「大模型调用」抽象为独立维度：`LLMProvider` 是一级概念，阿里百炼只是 provider 之一，
LM Studio 是第二个内置 provider。密钥统一存放于 `~/.config/autodo-suite/secrets/`
（权限 600 / 700），任何 provider 的密钥均不落代码、文档、日志。

#### 密钥安全

| 函数 | 说明 |
| --- | --- |
| `mask_api_key(key, keep_head=3, keep_tail=4)` | 密钥脱敏，返回 `sk-***末尾4位`。 |
| `secrets_dir()` | 统一密钥仓库目录（默认 `~/.config/autodo-suite/secrets/`，可用 `AUTODO_SUITE_SECRETS_DIR` 覆盖）。 |
| `secret_path(name)` | 逻辑密钥名 → 密钥文件路径（如 `bailian` → `bailian-api-key.txt`）。 |
| `ensure_secrets_layout()` | 初始化密钥仓库目录（权限 700）。 |
| `iter_secret_candidates(name)` | 密钥候选路径列表（按优先级）。 |

#### Provider 管理

```python
from autodokit.tools import list_providers, get_provider, resolve_provider, is_local_online
```

| 函数 | 说明 |
| --- | --- |
| `list_providers()` | 已注册 provider 名列表（`["bailian", "lmstudio"]`）。 |
| `get_provider(name)` | 按名称获取 `LLMProvider` 定义（含 base_url / 默认模型 / 密钥名 / 是否本地）。 |
| `resolve_provider(name="auto")` | 解析 provider：`auto` 时本地（lmstudio）在线则优先，否则回退 bailian。 |
| `is_local_online(provider, timeout=1.5)` | 探测本地 provider 服务是否在线（GET `/v1/models`）。 |

#### 统一调用

```python
def invoke_llm(
    *,
    prompt: str,
    system: str | None = None,
    provider: str = "auto",
    model: str = "",
    base_url: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.2,
    config_path=None,
    route_hints=None,
) -> dict
```

统一调用入口，返回 `status` / `provider` / `selected_model` / `response` / `error`。

```python
def build_llm_client(provider="auto", *, model="", base_url="", ...) -> tuple[AliyunLLMClient, str]
```

按 provider 构造客户端（复用 `AliyunLLMClient`），返回（客户端、解析后的 provider 名）。

#### 配置扩展（config.json）

```jsonc
{
  "llm": {
    "default_provider": "auto",
    "providers": {
      "bailian":  { "model": "qwen-plus" },
      "lmstudio": { "model": "<本地模型名>", "base_url": "http://127.0.0.1:1234/v1" }
    }
  }
}
```

`load_provider_config(config_path)` 读取 providers 覆盖配置；老配置（无 `providers` 字段）
自动回退为 `bailian` 单 provider，保持兼容。

#### 模型路由派发事务（provider 维度）

`autodokit.affairs.模型路由派发` 的配置新增 `provider` 字段（默认 `auto`）：
决策结果包含 `provider`、`provider_display`、`provider_base_url`、`provider_is_local`；
`run_inference=true` 时按选定 provider 实际调用。

---

### 2.22 超长会话批量读取工具

```python
from autodokit.tools import batch_read_pairs_by_llm
```

```python
def batch_read_pairs_by_llm(
    store_root,
    *,
    pair_ids=None,
    provider="auto",
    model="",
    prompt_template="...",
    system_prompt=None,
    max_tokens=2048,
    temperature=0.2,
    result_path=None,
    resume=True,
) -> dict
```

逐 Pair 调用大模型批量读取会话：每个 Pair（一组问答）单独调用一次大模型，
天然规避超长上下文问题。`resume=True` 时跳过已处理 Pair（断点续跑，
结果逐条落盘到 `<store>/index_db/pair_llm_results.json`）。

返回：`total` / `processed` / `skipped` / `failed` / `result_path` / `results`。

```python
# 配套检索入口（既有）
from autodokit.tools import import_chat_session_markdown, get_chat_pair_info, repair_exported_chat_markdown
```

---

## 5. 约定

### 路径处理

- 所有公开 API 接受绝对路径；相对路径需在调用前通过 `resolve_paths_to_absolute` 转换。
- 事务配置中的路径字段由 `prepare_affair_config` / `run_affair` 自动绝对化。

### 中文物理字段

`content.db` 中的物理表与列使用中文名（如 `文献主表`、`uid_文献`、`cite_key`）。DataFrame 接口保留英文逻辑字段作为 Python 调用层输入输出，工具层负责映射。

### 命名治理白名单

以下字段为英文例外，不做中译：

- `uid_` 前缀字段
- `cite_key`、`source_cite_key`
- `bib_*` 前缀字段

### 不向后兼容

项目按不向后兼容方式演进。过时的 API、配置字段、文档直接删除，不保留兼容壳层。
