# AOK预置事务手册

本文档由 `scripts/generate_affair_manual.py` 自动生成，用于聚合仓库内全部 AOK 预置事务的使用说明。

## 1. 使用原则

- 推荐调用方式：优先使用 `autodokit.run_affair(...)`，保持与事务管理系统一致。
- 路径处理规则：业务配置中的路径字段应在调度前预处理为绝对路径，再传给事务。
- 本手册的内容来源于每个事务目录下的 `affair.py`、`affair.json`、`affair.md`，以及事务管理系统元数据覆盖表。

## 2. 分类索引

- 事务总数：97
- 分类数：19

- decision 类事务: 1
- output 类事务: 1
- sink 类事务: 2
- transform 类事务: 42
- unknown 类事务: 10
- 任务文档事务: 4
- 图节点事务 / calc: 1
- 图节点事务 / compare: 1
- 图节点事务 / container: 1
- 图节点事务 / end: 1
- 图节点事务 / fork: 1
- 图节点事务 / if: 1
- 图节点事务 / input: 1
- 图节点事务 / merge: 1
- 图节点事务 / output: 1
- 图节点事务 / start: 1
- 图节点事务 / switch: 1
- 文献处理事务: 20
- 格式转换事务: 6

## 3. 全量索引表

| 事务 | 领域 | 节点类型 | pass_mode | 目录 |
| --- | --- | --- | --- | --- |
| AOB一键办公区转换 | business |  | config_path | autodokit/affairs/AOB一键办公区转换 |
| AOB一键安装部署 | business |  | config_path | autodokit/affairs/AOB一键安装部署 |
| AOK三库联动示例 | business |  | config_path | autodokit/affairs/AOK三库联动示例 |
| AOK任务数据库初始化 | business |  | config_path | autodokit/affairs/AOK任务数据库初始化 |
| AOK任务数据库校验 | business |  | config_path | autodokit/affairs/AOK任务数据库校验 |
| CAJ文件转PDF | business | process | config_path | autodokit/affairs/CAJ文件转PDF |
| CNKI全文下载规划 | business | transform | config_path | autodokit/affairs/CNKI全文下载规划 |
| CNKI单篇详情提取 | business | transform | config_path | autodokit/affairs/CNKI单篇详情提取 |
| CNKI基础检索 | business | transform | config_path | autodokit/affairs/CNKI基础检索 |
| CNKI期刊指标提取 | business | transform | config_path | autodokit/affairs/CNKI期刊指标提取 |
| CNKI期刊检索 | business | transform | config_path | autodokit/affairs/CNKI期刊检索 |
| CNKI期刊目录提取 | business | transform | config_path | autodokit/affairs/CNKI期刊目录提取 |
| CNKI桥接 | business | transform | config_path | autodokit/affairs/CNKI桥接 |
| CNKI结果解析 | business | transform | config_path | autodokit/affairs/CNKI结果解析 |
| CNKI翻页导航 | business | transform | config_path | autodokit/affairs/CNKI翻页导航 |
| CNKI题录导出 | business | transform | config_path | autodokit/affairs/CNKI题录导出 |
| CNKI高级检索 | business | transform | config_path | autodokit/affairs/CNKI高级检索 |
| DiD_RDD分析 | business | transform | config_path | autodokit/affairs/DiD_RDD分析 |
| LaTeX转Word | business | transform | config_path | autodokit/affairs/LaTeX转Word |
| node_runtime_retry_probe | business | transform | config_path | autodokit/affairs/node_runtime_retry_probe |
| Obsidian关联导出 | business | sink | config_path | autodokit/affairs/Obsidian关联导出 |
| PDF文件转md文件 | business | source | config_path | autodokit/affairs/PDF文件转md文件 |
| PDF文件转结构化数据文件 | business | transform | config_path | autodokit/affairs/PDF文件转结构化数据文件 |
| Skill渲染 | business |  | config_path | autodokit/affairs/Skill渲染 |
| task_docs_aggregate | business | merge | config_path | autodokit/affairs/task_docs_aggregate |
| task_docs_archive | business | sink | config_path | autodokit/affairs/task_docs_archive |
| task_docs_create_latest | business | source | config_path | autodokit/affairs/task_docs_create_latest |
| task_docs_finalize_latest | business | sink | config_path | autodokit/affairs/task_docs_finalize_latest |
| Word转LaTeX | business | transform | config_path | autodokit/affairs/Word转LaTeX |
| 中文本地资源管理 | business | transform | config_path | autodokit/affairs/中文本地资源管理 |
| 中文网页采集 | business | transform | config_path | autodokit/affairs/中文网页采集 |
| 任务数据库初始化 | business | transform | config_path | autodokit/affairs/任务数据库初始化 |
| 任务数据库回放 | business | transform | config_path | autodokit/affairs/任务数据库回放 |
| 任务数据库校验 | business | transform | config_path | autodokit/affairs/任务数据库校验 |
| 候选文献视图构建 | business |  | config_path | autodokit/affairs/候选文献视图构建 |
| 公开数据获取 | business | transform | config_path | autodokit/affairs/公开数据获取 |
| 创新点可行性验证 | business |  | config_path | autodokit/affairs/创新点可行性验证 |
| 创新点池构建 | business |  | config_path | autodokit/affairs/创新点池构建 |
| 单篇粗读 | business |  | config_path | autodokit/affairs/单篇粗读 |
| 单篇精读 | business | sink | config_path | autodokit/affairs/单篇精读 |
| 单轮调度派发 | business | transform | config_path | autodokit/affairs/单轮调度派发 |
| 变量操作化 | business | transform | config_path | autodokit/affairs/变量操作化 |
| 合并去重bibtex | business | transform | config_path | autodokit/affairs/合并去重bibtex |
| 合并去重文献元数据 | business | transform | config_path | autodokit/affairs/合并去重文献元数据 |
| 向量化与索引构建 | business | transform | config_path | autodokit/affairs/向量化与索引构建 |
| 图节点_calc | graph | calc | config_path | autodokit/affairs/图节点_calc |
| 图节点_compare | graph | compare | config_path | autodokit/affairs/图节点_compare |
| 图节点_container | graph | container | config_path | autodokit/affairs/图节点_container |
| 图节点_end | graph | end | config_path | autodokit/affairs/图节点_end |
| 图节点_fork | graph | fork | config_path | autodokit/affairs/图节点_fork |
| 图节点_if | graph | if | config_path | autodokit/affairs/图节点_if |
| 图节点_input | graph | input | config_path | autodokit/affairs/图节点_input |
| 图节点_merge | graph | merge | config_path | autodokit/affairs/图节点_merge |
| 图节点_output | graph | output | config_path | autodokit/affairs/图节点_output |
| 图节点_start | graph | start | config_path | autodokit/affairs/图节点_start |
| 图节点_switch | graph | switch | config_path | autodokit/affairs/图节点_switch |
| 外审意见接收 | business | decision | config_path | autodokit/affairs/外审意见接收 |
| 实证四件套 | business | transform | config_path | autodokit/affairs/实证四件套 |
| 审稿回复 | business | transform | config_path | autodokit/affairs/审稿回复 |
| 审稿意见拆解 | business | transform | config_path | autodokit/affairs/审稿意见拆解 |
| 导入和预处理文献元数据 | business | source | config_path | autodokit/affairs/导入和预处理文献元数据 |
| 工作区自检 | business | transform | config_path | autodokit/affairs/工作区自检 |
| 工作流执行 | business | transform | config_path | autodokit/affairs/工作流执行 |
| 引文核验 | business | transform | config_path | autodokit/affairs/引文核验 |
| 成果归档发布 | business | output | config_path | autodokit/affairs/成果归档发布 |
| 数据工程样本构建 | business | transform | config_path | autodokit/affairs/数据工程样本构建 |
| 文献矩阵 | business | source | config_path | autodokit/affairs/文献矩阵 |
| 文献阅读规划 | business | transform | config_path | autodokit/affairs/文献阅读规划 |
| 方法白名单选择 | business | transform | config_path | autodokit/affairs/方法白名单选择 |
| 期刊投稿 | business | transform | config_path | autodokit/affairs/期刊投稿 |
| 本地文献导入 | business | transform | config_path | autodokit/affairs/本地文献导入 |
| 检索治理 | business | transform | config_path | autodokit/affairs/检索治理 |
| 模型路由派发 | business | transform | config_path | autodokit/affairs/模型路由派发 |
| 清洗bibtex文件 | business | transform | config_path | autodokit/affairs/清洗bibtex文件 |
| 生成关键词集合 | business | source | config_path | autodokit/affairs/生成关键词集合 |
| 生成文献元数据关系图 | business | transform | config_path | autodokit/affairs/生成文献元数据关系图 |
| 白名单治理检查 | business | transform | config_path | autodokit/affairs/白名单治理检查 |
| 百炼SDK接入检查 | business | transform | config_path | autodokit/affairs/百炼SDK接入检查 |
| 知识预筛选 | business | transform | config_path | autodokit/affairs/知识预筛选 |
| 研究构思 | business | transform | config_path | autodokit/affairs/研究构思 |
| 研究脉络梳理 | business |  | config_path | autodokit/affairs/研究脉络梳理 |
| 研究诚信检查 | business | transform | config_path | autodokit/affairs/研究诚信检查 |
| 管理文档单元数据库 | business | transform | config_path | autodokit/affairs/管理文档单元数据库 |
| 结果分析解读 | business | transform | config_path | autodokit/affairs/结果分析解读 |
| 综述研读与研究地图生成 | business |  | config_path | autodokit/affairs/综述研读与研究地图生成 |
| 综述草稿生成 | business | sink | config_path | autodokit/affairs/综述草稿生成 |
| 自动化导入知网研学专题 | business | process | config_path | autodokit/affairs/自动化导入知网研学专题 |
| 解析与分块 | business | transform | config_path | autodokit/affairs/解析与分块 |
| 计量环境配置 | business | transform | config_path | autodokit/affairs/计量环境配置 |
| 订阅文献访问治理 | business | transform | config_path | autodokit/affairs/订阅文献访问治理 |
| 论文整编写作 | business | transform | config_path | autodokit/affairs/论文整编写作 |
| 论文自审 | business | transform | config_path | autodokit/affairs/论文自审 |
| 论文草稿 | business | transform | config_path | autodokit/affairs/论文草稿 |
| 证据综合 | business | transform | config_path | autodokit/affairs/证据综合 |
| 语义预筛选 | business | transform | config_path | autodokit/affairs/语义预筛选 |
| 项目初始化 | business | transform | config_path | autodokit/affairs/项目初始化 |

## 4. decision 类事务

### 外审意见接收

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 外审意见接收 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 外审意见接收 |
| 目录 | autodokit/affairs/外审意见接收 |
| Runner.module | autodokit.affairs.外审意见接收.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/外审意见接收/affair.md |

#### 模块说明

外审意见接收事务。

#### 事务 Markdown 说明摘录

- 外审意见接收

接收编辑决定与审稿意见，输出后续分流建议。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| decision | 否 | "" | "" |
| editor_notes | 否 | "" | "" |
| review_comments | 否 | [] | [] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| decision | 否 | "" | "" |
| editor_notes | 否 | "" | "" |
| review_comments | 否 | [] | [] |

#### node.config JSON 示例

```json
{
  "decision": "",
  "review_comments": [],
  "editor_notes": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "decision": "",
  "review_comments": [],
  "editor_notes": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("外审意见接收",
    config={'decision': '', 'review_comments': [], 'editor_notes': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.外审意见接收.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 5. output 类事务

### 成果归档发布

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 成果归档发布 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 成果归档发布 |
| 目录 | autodokit/affairs/成果归档发布 |
| Runner.module | autodokit.affairs.成果归档发布.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/成果归档发布/affair.md |

#### 模块说明

成果归档发布事务。

#### 事务 Markdown 说明摘录

- 成果归档发布

完成终稿归档、复现包发布与项目关闭记录。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| archive_files | 否 | [] | [] |
| manuscript_title | 否 | "" | "" |
| publication_status | 否 | "" | "" |
| release_note | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| archive_files | 否 | [] | [] |
| manuscript_title | 否 | "" | "" |
| publication_status | 否 | "" | "" |
| release_note | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "manuscript_title": "",
  "publication_status": "",
  "archive_files": [],
  "release_note": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "manuscript_title": "",
  "publication_status": "",
  "archive_files": [],
  "release_note": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("成果归档发布",
    config={'manuscript_title': '',
     'publication_status': '',
     'archive_files': [],
     'release_note': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.成果归档发布.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 6. sink 类事务

### Obsidian关联导出

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | Obsidian关联导出 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 Obsidian关联导出 |
| 目录 | autodokit/affairs/Obsidian关联导出 |
| Runner.module | autodokit.affairs.Obsidian关联导出.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/Obsidian关联导出/affair.md |

#### 模块说明

事务：Obsidian 关联导出。

该事务用于把主笔记及其关联笔记/附件打包导出，支持 dry-run 预览。

#### 事务 Markdown 说明摘录

- Obsidian关联导出

- 用途

- 该事务用于执行 `Obsidian关联导出` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

- 无

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

- 无

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("Obsidian关联导出",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.Obsidian关联导出.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 单篇精读

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 单篇精读 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 单篇精读 |
| 目录 | autodokit/affairs/单篇精读 |
| Runner.module | autodokit.affairs.单篇精读.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/单篇精读/affair.md |

#### 模块说明

单篇精读笔记（占位可运行版）。

本脚本用于对单篇文献生成“精读笔记”。

本版实现保持简单：
- 从 `input_structured_json`、`input_structured_dir` 或 `content_db` 读取目标文献全文（优先）
- 拼接一个较短的提示词
- 调用阿里百炼（DashScope）生成笔记
- 将结果写入 output_dir 下的 markdown 文件

注意：
- 不在代码中写任何 key；请通过环境变量 `DASHSCOPE_API_KEY` 或本地文件注入。
- 本脚本不做“复杂的容错/重试/降级”。缺依赖就让用户自行安装。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。

#### 事务 Markdown 说明摘录

- 单篇精读

- 用途

- 该事务用于执行 `单篇精读` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| docs | docs | jsonl |

#### interface.outputs

- 无

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| docs | docs | jsonl |

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| bibliography_csv | 否 | "" | "" |
| content_db | 否 | "" | "" |
| doc_id | 否 | null | null |
| input_structured_dir | 否 | "" | "" |
| input_structured_json | 否 | "" | "" |
| insert_placeholders_from_references | 否 | true | true |
| max_chars | 否 | 12000 | 12000 |
| model | 否 | "qwen-plus" | "qwen-plus" |
| output_dir | 否 | "workflows/workflow_单篇精读/output/05_single_reading" | "workflows/workflow_单篇精读/output/05_single_reading" |
| reference_lines | 否 | [] | [] |
| system_prompt | 否 | "你是一名严谨的学术研究助理。请用中文输出，结构清晰。" | "你是一名严谨的学术研究助理。请用中文输出，结构清晰。" |
| uid | 否 | 1 | 1 |
| use_llm | 否 | false | false |
| user_prompt_template | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| content_db | 否 | "" | "" |
| doc_id | 否 | null | null |
| input_structured_dir | 否 | "" | "" |
| input_structured_json | 否 | "" | "" |
| max_chars | 否 | 12000 | 12000 |
| model | 否 | "qwen-plus" | "qwen-plus" |
| output_dir | 否 | "workflows/workflow_单篇精读/output/05_single_reading" | "workflows/workflow_单篇精读/output/05_single_reading" |
| system_prompt | 否 | "你是一名严谨的学术研究助理。请用中文输出，结构清晰。" | "你是一名严谨的学术研究助理。请用中文输出，结构清晰。" |
| uid | 否 | 1 | 1 |

#### node.config JSON 示例

```json
{
  "content_db": "",
  "input_structured_json": "",
  "input_structured_dir": "",
  "output_dir": "workflows/workflow_单篇精读/output/05_single_reading",
  "uid": 1,
  "doc_id": null,
  "model": "qwen-plus",
  "system_prompt": "你是一名严谨的学术研究助理。请用中文输出，结构清晰。",
  "max_chars": 12000
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "content_db": "",
  "input_structured_json": "",
  "input_structured_dir": "",
  "output_dir": "workflows/workflow_单篇精读/output/05_single_reading",
  "uid": 1,
  "doc_id": null,
  "use_llm": false,
  "model": "qwen-plus",
  "system_prompt": "你是一名严谨的学术研究助理。请用中文输出，结构清晰。",
  "user_prompt_template": "",
  "max_chars": 12000,
  "bibliography_csv": "",
  "insert_placeholders_from_references": true,
  "reference_lines": []
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("单篇精读",
  config={'content_db': '',
   'input_structured_json': '',
   'input_structured_dir': '',
     'output_dir': 'workflows/workflow_单篇精读/output/05_single_reading',
     'uid': 1,
     'doc_id': None,
     'use_llm': False,
     'model': 'qwen-plus',
     'system_prompt': '你是一名严谨的学术研究助理。请用中文输出，结构清晰。',
     'user_prompt_template': '',
     'max_chars': 12000,
     'bibliography_csv': '',
     'insert_placeholders_from_references': True,
     'reference_lines': []},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.单篇精读.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 7. transform 类事务

### CNKI全文下载规划

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CNKI全文下载规划 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CNKI全文下载规划 |
| 目录 | autodokit/affairs/CNKI全文下载规划 |
| Runner.module | autodokit.affairs.CNKI全文下载规划.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CNKI全文下载规划/affair.md |

#### 模块说明

CNKI 全文下载规划事务。

#### 事务 Markdown 说明摘录

- CNKI全文下载规划

评估全文下载条件并生成后续文本抽取衔接计划。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| detail_url | 否 | "" | "" |
| file_format | 否 | "pdf" | "pdf" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| detail_url | 否 | "" | "" |
| file_format | 否 | "pdf" | "pdf" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "detail_url": "",
  "file_format": "pdf",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "detail_url": "",
  "file_format": "pdf",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CNKI全文下载规划",
    config={'detail_url': '',
     'file_format': 'pdf',
     'access_type': 'closed',
     'metadata': {},
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CNKI全文下载规划.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### CNKI单篇详情提取

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CNKI单篇详情提取 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CNKI单篇详情提取 |
| 目录 | autodokit/affairs/CNKI单篇详情提取 |
| Runner.module | autodokit.affairs.CNKI单篇详情提取.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CNKI单篇详情提取/affair.md |

#### 模块说明

CNKI 单篇详情提取事务。

#### 事务 Markdown 说明摘录

- CNKI单篇详情提取

生成单篇详情抽取与下载衔接计划。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| detail_url | 否 | "" | "" |
| export_id | 否 | "" | "" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| title_hint | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| detail_url | 否 | "" | "" |
| export_id | 否 | "" | "" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| title_hint | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "detail_url": "",
  "title_hint": "",
  "export_id": "",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "detail_url": "",
  "title_hint": "",
  "export_id": "",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CNKI单篇详情提取",
    config={'detail_url': '',
     'title_hint': '',
     'export_id': '',
     'access_type': 'closed',
     'metadata': {},
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CNKI单篇详情提取.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### CNKI期刊指标提取

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CNKI期刊指标提取 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CNKI期刊指标提取 |
| 目录 | autodokit/affairs/CNKI期刊指标提取 |
| Runner.module | autodokit.affairs.CNKI期刊指标提取.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CNKI期刊指标提取/affair.md |

#### 模块说明

CNKI 期刊指标提取事务。

#### 事务 Markdown 说明摘录

- CNKI期刊指标提取

生成期刊指标、收录标签和评价字段的提取计划。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| detail_url | 否 | "" | "" |
| journal_name | 否 | "" | "" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| detail_url | 否 | "" | "" |
| journal_name | 否 | "" | "" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "journal_name": "",
  "detail_url": "",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "journal_name": "",
  "detail_url": "",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CNKI期刊指标提取",
    config={'journal_name': '',
     'detail_url': '',
     'access_type': 'closed',
     'metadata': {},
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CNKI期刊指标提取.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### CNKI期刊目录提取

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CNKI期刊目录提取 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CNKI期刊目录提取 |
| 目录 | autodokit/affairs/CNKI期刊目录提取 |
| Runner.module | autodokit.affairs.CNKI期刊目录提取.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CNKI期刊目录提取/affair.md |

#### 模块说明

CNKI 期刊目录提取事务。

#### 事务 Markdown 说明摘录

- CNKI期刊目录提取

生成刊期目录提取计划，并衔接单篇详情提取。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| download_original | 否 | false | false |
| issue | 否 | "" | "" |
| journal_name | 否 | "" | "" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| year | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| download_original | 否 | false | false |
| issue | 否 | "" | "" |
| journal_name | 否 | "" | "" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| year | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "journal_name": "",
  "year": "",
  "issue": "",
  "download_original": false,
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "journal_name": "",
  "year": "",
  "issue": "",
  "download_original": false,
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CNKI期刊目录提取",
    config={'journal_name': '',
     'year': '',
     'issue': '',
     'download_original': False,
     'access_type': 'closed',
     'metadata': {},
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CNKI期刊目录提取.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### CNKI桥接

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CNKI桥接 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CNKI桥接 |
| 目录 | autodokit/affairs/CNKI桥接 |
| Runner.module | autodokit.affairs.CNKI桥接.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CNKI桥接/affair.md |

#### 模块说明

CNKI 桥接事务执行入口。

#### 事务 Markdown 说明摘录

- CNKI桥接

- 事务说明

- 该事务提供 CNKI 相关技能的规划能力封装。
- 输入 `mode` 决定调用的 planner 构建方法。
- 输出统一写入 `cnki_bridge_result.json`。

- 输入约定

- `mode`: 规划模式，例如 `cnki-search`、`cnki-export`。
- 其余参数按对应模式透传。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| mode | 否 | "cnki-search" | "cnki-search" |
| output_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| mode | 否 | "cnki-search" | "cnki-search" |
| output_dir | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "mode": "cnki-search",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "mode": "cnki-search",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CNKI桥接",
    config={'mode': 'cnki-search', 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CNKI桥接.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### CNKI结果解析

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CNKI结果解析 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CNKI结果解析 |
| 目录 | autodokit/affairs/CNKI结果解析 |
| Runner.module | autodokit.affairs.CNKI结果解析.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CNKI结果解析/affair.md |

#### 模块说明

CNKI 结果解析事务。

#### 事务 Markdown 说明摘录

- CNKI结果解析

把结果页地址和页码转成结构化解析计划。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| current_page | 否 | 1 | 1 |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| page_url | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| current_page | 否 | 1 | 1 |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| page_url | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "page_url": "",
  "current_page": 1,
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "page_url": "",
  "current_page": 1,
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CNKI结果解析",
    config={'page_url': '',
     'current_page': 1,
     'access_type': 'closed',
     'metadata': {},
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CNKI结果解析.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### CNKI翻页导航

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CNKI翻页导航 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CNKI翻页导航 |
| 目录 | autodokit/affairs/CNKI翻页导航 |
| Runner.module | autodokit.affairs.CNKI翻页导航.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CNKI翻页导航/affair.md |

#### 模块说明

CNKI 翻页导航事务。

#### 事务 Markdown 说明摘录

- CNKI翻页导航

生成翻页、跳页和排序切换计划。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| action | 否 | "next" | "next" |
| current_page | 否 | 1 | 1 |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| sort_by | 否 | "relevance" | "relevance" |
| target_page | 否 | null | null |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| action | 否 | "next" | "next" |
| current_page | 否 | 1 | 1 |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| sort_by | 否 | "relevance" | "relevance" |
| target_page | 否 | null | null |

#### node.config JSON 示例

```json
{
  "action": "next",
  "current_page": 1,
  "target_page": null,
  "sort_by": "relevance",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "action": "next",
  "current_page": 1,
  "target_page": null,
  "sort_by": "relevance",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CNKI翻页导航",
    config={'action': 'next',
     'current_page': 1,
     'target_page': None,
     'sort_by': 'relevance',
     'access_type': 'closed',
     'metadata': {},
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CNKI翻页导航.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### CNKI题录导出

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CNKI题录导出 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CNKI题录导出 |
| 目录 | autodokit/affairs/CNKI题录导出 |
| Runner.module | autodokit.affairs.CNKI题录导出.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CNKI题录导出/affair.md |

#### 模块说明

CNKI 题录导出事务。

#### 事务 Markdown 说明摘录

- CNKI题录导出

生成 RIS、GB/T 等导出计划，供题录入库流程使用。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| detail_url | 否 | "" | "" |
| export_mode | 否 | "ris" | "ris" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| detail_url | 否 | "" | "" |
| export_mode | 否 | "ris" | "ris" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "detail_url": "",
  "export_mode": "ris",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "detail_url": "",
  "export_mode": "ris",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CNKI题录导出",
    config={'detail_url': '',
     'export_mode': 'ris',
     'access_type': 'closed',
     'metadata': {},
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CNKI题录导出.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### DiD_RDD分析

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | DiD_RDD分析 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 DiD_RDD分析 |
| 目录 | autodokit/affairs/DiD_RDD分析 |
| Runner.module | autodokit.affairs.DiD_RDD分析.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/DiD_RDD分析/affair.md |

#### 模块说明

DiD/RDD 分析事务。

#### 事务 Markdown 说明摘录

- DiD_RDD分析

执行最小化 DiD/RDD 估计并输出结构化结果。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| panel_rows | 否 | [] | [] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| panel_rows | 否 | [] | [] |

#### node.config JSON 示例

```json
{
  "panel_rows": [],
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "panel_rows": [],
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("DiD_RDD分析",
    config={'panel_rows': [], 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.DiD_RDD分析.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### node_runtime_retry_probe

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | node_runtime_retry_probe |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 node_runtime_retry_probe |
| 目录 | autodokit/affairs/node_runtime_retry_probe |
| Runner.module | autodokit.affairs.node_runtime_retry_probe.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/node_runtime_retry_probe/affair.md |

#### 模块说明

Node Runtime 重试探针事务。

该事务用于 S7 回归 demo：
- 在前 N 次执行时抛出可重试异常（TimeoutError/ConnectionError）；
- 超过阈值后成功并输出报告文件。

#### 事务 Markdown 说明摘录

- node_runtime_retry_probe

- 用途

- 该事务用于执行 `node_runtime_retry_probe` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("node_runtime_retry_probe",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.node_runtime_retry_probe.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 中文本地资源管理

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 中文本地资源管理 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 中文本地资源管理 |
| 目录 | autodokit/affairs/中文本地资源管理 |
| Runner.module | autodokit.affairs.中文本地资源管理.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/中文本地资源管理/affair.md |

#### 模块说明

中文本地资源管理事务。

#### 事务 Markdown 说明摘录

- 中文本地资源管理

初始化中文文献、本地附件与原始数据目录结构，供后续导入与整理事务使用。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| attachments_dir_name | 否 | "attachments" | "attachments" |
| bib_dir_name | 否 | "bib" | "bib" |
| output_dir | 否 | "" | "" |
| raw_data_dir_name | 否 | "raw_data" | "raw_data" |
| root_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| attachments_dir_name | 否 | "attachments" | "attachments" |
| bib_dir_name | 否 | "bib" | "bib" |
| output_dir | 否 | "" | "" |
| raw_data_dir_name | 否 | "raw_data" | "raw_data" |
| root_dir | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "root_dir": "",
  "bib_dir_name": "bib",
  "attachments_dir_name": "attachments",
  "raw_data_dir_name": "raw_data",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "root_dir": "",
  "bib_dir_name": "bib",
  "attachments_dir_name": "attachments",
  "raw_data_dir_name": "raw_data",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("中文本地资源管理",
    config={'root_dir': '',
     'bib_dir_name': 'bib',
     'attachments_dir_name': 'attachments',
     'raw_data_dir_name': 'raw_data',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.中文本地资源管理.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 中文网页采集

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 中文网页采集 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 中文网页采集 |
| 目录 | autodokit/affairs/中文网页采集 |
| Runner.module | autodokit.affairs.中文网页采集.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/中文网页采集/affair.md |

#### 模块说明

中文网页采集事务。

#### 事务 Markdown 说明摘录

- 中文网页采集

规划中文网页采集、正文抽取与结果落盘动作。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| query | 否 | "" | "" |
| seed_urls | 否 | [] | [] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| query | 否 | "" | "" |
| seed_urls | 否 | [] | [] |

#### node.config JSON 示例

```json
{
  "query": "",
  "seed_urls": [],
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "query": "",
  "seed_urls": [],
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("中文网页采集",
    config={'query': '', 'seed_urls': [], 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.中文网页采集.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 任务数据库初始化

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 任务数据库初始化 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 任务数据库初始化 |
| 目录 | autodokit/affairs/任务数据库初始化 |
| Runner.module | autodokit.affairs.任务数据库初始化.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/任务数据库初始化/affair.md |

#### 模块说明

任务数据库初始化事务。

#### 事务 Markdown 说明摘录

- 任务数据库初始化

初始化 `database/tasks` 下的基础 CSV、JSONL 和 manifest 文件。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "." | "." |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "." | "." |

#### node.config JSON 示例

```json
{
  "project_root": ".",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_root": ".",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("任务数据库初始化",
    config={'project_root': '.', 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.任务数据库初始化.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 任务数据库回放

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 任务数据库回放 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 任务数据库回放 |
| 目录 | autodokit/affairs/任务数据库回放 |
| Runner.module | autodokit.affairs.任务数据库回放.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/任务数据库回放/affair.md |

#### 模块说明

任务数据库回放事务。

#### 事务 Markdown 说明摘录

- 任务数据库回放

读取 `execution_runs.jsonl` 并输出回放事件摘要。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "." | "." |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "." | "." |

#### node.config JSON 示例

```json
{
  "project_root": ".",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_root": ".",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("任务数据库回放",
    config={'project_root': '.', 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.任务数据库回放.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 任务数据库校验

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 任务数据库校验 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 任务数据库校验 |
| 目录 | autodokit/affairs/任务数据库校验 |
| Runner.module | autodokit.affairs.任务数据库校验.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/任务数据库校验/affair.md |

#### 模块说明

任务数据库校验事务。

#### 事务 Markdown 说明摘录

- 任务数据库校验

检查任务数据库关键文件是否存在，并输出缺失项。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "." | "." |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "." | "." |

#### node.config JSON 示例

```json
{
  "project_root": ".",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_root": ".",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("任务数据库校验",
    config={'project_root': '.', 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.任务数据库校验.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 公开数据获取

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 公开数据获取 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 公开数据获取 |
| 目录 | autodokit/affairs/公开数据获取 |
| Runner.module | autodokit.affairs.公开数据获取.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/公开数据获取/affair.md |

#### 模块说明

公开数据获取事务。

#### 事务 Markdown 说明摘录

- 公开数据获取

规划公开数据源的试拉、批量拉取与异常恢复动作，并输出结构化请求方案。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "open" | "open" |
| metadata | 否 | {} | {} |
| object_type | 否 | "dataset" | "dataset" |
| output_dir | 否 | "" | "" |
| query | 否 | "" | "" |
| region_type | 否 | "global" | "global" |
| source_type | 否 | "online" | "online" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "open" | "open" |
| metadata | 否 | {} | {} |
| object_type | 否 | "dataset" | "dataset" |
| output_dir | 否 | "" | "" |
| query | 否 | "" | "" |
| region_type | 否 | "global" | "global" |
| source_type | 否 | "online" | "online" |

#### node.config JSON 示例

```json
{
  "query": "",
  "object_type": "dataset",
  "source_type": "online",
  "region_type": "global",
  "access_type": "open",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "query": "",
  "object_type": "dataset",
  "source_type": "online",
  "region_type": "global",
  "access_type": "open",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("公开数据获取",
    config={'query': '',
     'object_type': 'dataset',
     'source_type': 'online',
     'region_type': 'global',
     'access_type': 'open',
     'metadata': {},
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.公开数据获取.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 单轮调度派发

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 单轮调度派发 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 单轮调度派发 |
| 目录 | autodokit/affairs/单轮调度派发 |
| Runner.module | autodokit.affairs.单轮调度派发.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/单轮调度派发/affair.md |

#### 模块说明

单轮调度派发事务。

#### 事务 Markdown 说明摘录

- 单轮调度派发

根据当前任务目标和派发表选择下一跳事务。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| current_transaction_uid | 否 | "" | "" |
| goal | 否 | "" | "" |
| output_dir | 否 | "" | "" |
| payload | 否 | {} | {} |
| project_root | 否 | "." | "." |
| task_uid | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| current_transaction_uid | 否 | "" | "" |
| goal | 否 | "" | "" |
| output_dir | 否 | "" | "" |
| payload | 否 | {} | {} |
| project_root | 否 | "." | "." |
| task_uid | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "task_uid": "",
  "goal": "",
  "payload": {},
  "project_root": ".",
  "current_transaction_uid": "",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "task_uid": "",
  "goal": "",
  "payload": {},
  "project_root": ".",
  "current_transaction_uid": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("单轮调度派发",
    config={'task_uid': '',
     'goal': '',
     'payload': {},
     'project_root': '.',
     'current_transaction_uid': '',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.单轮调度派发.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 变量操作化

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 变量操作化 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 变量操作化 |
| 目录 | autodokit/affairs/变量操作化 |
| Runner.module | autodokit.affairs.变量操作化.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/变量操作化/affair.md |

#### 模块说明

变量操作化事务。

#### 事务 Markdown 说明摘录

- 变量操作化

将研究概念映射为可观测变量定义与推荐代理指标。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| concepts | 否 | [] | [] |
| output_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| concepts | 否 | [] | [] |
| output_dir | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "concepts": [],
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "concepts": [],
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("变量操作化",
    config={'concepts': [], 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.变量操作化.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 合并去重bibtex

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 合并去重bibtex |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 合并去重bibtex |
| 目录 | autodokit/affairs/合并去重bibtex |
| Runner.module | autodokit.affairs.合并去重bibtex.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/合并去重bibtex/affair.md |

#### 模块说明

合并去重bibtex脚本。

该脚本扫描指定目录下的 .bib 文件，解析并合并条目，按配置的去重策略进行去重并输出合并后的 .bib（或 JSON/CSV）。

主要功能：
- 提供 programmatic API `merge_bib_files` 以便被单元测试或其他脚本调用。
- 提供 CLI 接口用于命令行运行。

注意：该脚本使用 `bibtexparser` 作为首选解析/导出库（项目的 `requirements.txt` 已包含该依赖）。

#### 事务 Markdown 说明摘录

- 合并去重bibtex

- 用途

- 该事务用于执行 `合并去重bibtex` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("合并去重bibtex",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.合并去重bibtex.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 实证四件套

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 实证四件套 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 实证四件套 |
| 目录 | autodokit/affairs/实证四件套 |
| Runner.module | autodokit.affairs.实证四件套.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/实证四件套/affair.md |

#### 模块说明

实证四件套事务。

#### 事务 Markdown 说明摘录

- 实证四件套

封装基准回归、机制分析、稳健性检验、异质性分析摘要。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| baseline_summary | 否 | "" | "" |
| heterogeneity_groups | 否 | [] | [] |
| mechanism_points | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| robustness_checks | 否 | [] | [] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| baseline_summary | 否 | "" | "" |
| heterogeneity_groups | 否 | [] | [] |
| mechanism_points | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| robustness_checks | 否 | [] | [] |

#### node.config JSON 示例

```json
{
  "baseline_summary": "",
  "mechanism_points": [],
  "robustness_checks": [],
  "heterogeneity_groups": [],
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "baseline_summary": "",
  "mechanism_points": [],
  "robustness_checks": [],
  "heterogeneity_groups": [],
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("实证四件套",
    config={'baseline_summary': '',
     'mechanism_points': [],
     'robustness_checks': [],
     'heterogeneity_groups': [],
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.实证四件套.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 审稿回复

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 审稿回复 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 审稿回复 |
| 目录 | autodokit/affairs/审稿回复 |
| Runner.module | autodokit.affairs.审稿回复.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/审稿回复/affair.md |

#### 模块说明

审稿回复事务。

#### 事务 Markdown 说明摘录

- 审稿回复

生成审稿意见逐条回复草稿与行动建议。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| comments | 否 | [] | [] |
| manuscript_title | 否 | "" | "" |
| output_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| comments | 否 | [] | [] |
| manuscript_title | 否 | "" | "" |
| output_dir | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "comments": [],
  "manuscript_title": "",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "comments": [],
  "manuscript_title": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("审稿回复",
    config={'comments': [], 'manuscript_title': '', 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.审稿回复.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 审稿意见拆解

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 审稿意见拆解 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 审稿意见拆解 |
| 目录 | autodokit/affairs/审稿意见拆解 |
| Runner.module | autodokit.affairs.审稿意见拆解.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/审稿意见拆解/affair.md |

#### 模块说明

审稿意见拆解事务。

#### 事务 Markdown 说明摘录

- 审稿意见拆解

将审稿意见按“补分析、补写作、解释说明”三类路径拆解。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| comments | 否 | [] | [] |
| manuscript_title | 否 | "" | "" |
| output_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| comments | 否 | [] | [] |
| manuscript_title | 否 | "" | "" |
| output_dir | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "comments": [],
  "manuscript_title": "",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "comments": [],
  "manuscript_title": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("审稿意见拆解",
    config={'comments': [], 'manuscript_title': '', 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.审稿意见拆解.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 工作区自检

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 工作区自检 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 工作区自检 |
| 目录 | autodokit/affairs/工作区自检 |
| Runner.module | autodokit.affairs.工作区自检.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/工作区自检/affair.md |

#### 模块说明

工作区自检事务。

#### 事务 Markdown 说明摘录

- 工作区自检

扫描工作区治理结构、根目录浏览器数据泄漏和 `.gitignore` 基础规则，并按需落盘报告。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| auto_migrate | 否 | false | false |
| mode | 否 | "full" | "full" |
| output_dir | 否 | "" | "" |
| project_root | 否 | "" | "" |
| report_dir | 否 | "" | "" |
| write_report | 否 | true | true |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| auto_migrate | 否 | false | false |
| mode | 否 | "full" | "full" |
| output_dir | 否 | "" | "" |
| project_root | 否 | "" | "" |
| report_dir | 否 | "" | "" |
| write_report | 否 | true | true |

#### node.config JSON 示例

```json
{
  "project_root": "",
  "mode": "full",
  "auto_migrate": false,
  "write_report": true,
  "report_dir": "",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_root": "",
  "mode": "full",
  "auto_migrate": false,
  "write_report": true,
  "report_dir": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("工作区自检",
    config={'project_root': '',
     'mode': 'full',
     'auto_migrate': False,
     'write_report': True,
     'report_dir': '',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.工作区自检.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 工作流执行

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 工作流执行 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 工作流执行 |
| 目录 | autodokit/affairs/工作流执行 |
| Runner.module | autodokit.affairs.工作流执行.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/工作流执行/affair.md |

#### 模块说明

工作流执行事务。

#### 事务 Markdown 说明摘录

- 工作流执行

读取工作流文件并输出摘要或执行规划结果，供 ARK 的工作流技能直接转接。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| dry_run | 否 | false | false |
| output_dir | 否 | "" | "" |
| workflow_path | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| dry_run | 否 | false | false |
| output_dir | 否 | "" | "" |
| workflow_path | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "workflow_path": "",
  "dry_run": false,
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "workflow_path": "",
  "dry_run": false,
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("工作流执行",
    config={'workflow_path': '', 'dry_run': False, 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.工作流执行.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 引文核验

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 引文核验 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 引文核验 |
| 目录 | autodokit/affairs/引文核验 |
| Runner.module | autodokit.affairs.引文核验.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/引文核验/affair.md |

#### 模块说明

引文核验事务。

#### 事务 Markdown 说明摘录

- 引文核验

核验正文引文是否都能在参考文献中找到对应项，并输出缺失清单。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| citations | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| references | 否 | [] | [] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| citations | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| references | 否 | [] | [] |

#### node.config JSON 示例

```json
{
  "citations": [],
  "references": [],
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "citations": [],
  "references": [],
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("引文核验",
    config={'citations': [], 'references': [], 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.引文核验.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 数据工程样本构建

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 数据工程样本构建 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 数据工程样本构建 |
| 目录 | autodokit/affairs/数据工程样本构建 |
| Runner.module | autodokit.affairs.数据工程样本构建.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/数据工程样本构建/affair.md |

#### 模块说明

数据工程样本构建事务。

#### 事务 Markdown 说明摘录

- 数据工程样本构建

将变量设计与原始数据转换为可用于实证分析的样本底表。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| dataset_sources | 否 | [] | [] |
| join_keys | 否 | [] | [] |
| output_table | 否 | "" | "" |
| variable_specs | 否 | [] | [] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| dataset_sources | 否 | [] | [] |
| join_keys | 否 | [] | [] |
| output_table | 否 | "" | "" |
| variable_specs | 否 | [] | [] |

#### node.config JSON 示例

```json
{
  "dataset_sources": [],
  "join_keys": [],
  "variable_specs": [],
  "output_table": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "dataset_sources": [],
  "join_keys": [],
  "variable_specs": [],
  "output_table": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("数据工程样本构建",
    config={'dataset_sources': [], 'join_keys': [], 'variable_specs': [], 'output_table': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.数据工程样本构建.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 方法白名单选择

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 方法白名单选择 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 方法白名单选择 |
| 目录 | autodokit/affairs/方法白名单选择 |
| Runner.module | autodokit.affairs.方法白名单选择.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/方法白名单选择/affair.md |

#### 模块说明

方法白名单选择事务。

在候选方法列表中按白名单约束筛选可用识别策略，
并保持与 ARK 兼容的状态与结果结构。

#### 事务 Markdown 说明摘录

- 方法白名单选择

在候选方法中按白名单筛选可用识别策略，并输出入选与拒绝列表。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| candidate_methods | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| top_k | 否 | 3 | 3 |
| whitelist | 否 | [] | [] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| candidate_methods | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| top_k | 否 | 3 | 3 |
| whitelist | 否 | [] | [] |

#### node.config JSON 示例

```json
{
  "candidate_methods": [],
  "whitelist": [],
  "top_k": 3,
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "candidate_methods": [],
  "whitelist": [],
  "top_k": 3,
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("方法白名单选择",
    config={'candidate_methods': [], 'whitelist': [], 'top_k': 3, 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.方法白名单选择.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 期刊投稿

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 期刊投稿 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 期刊投稿 |
| 目录 | autodokit/affairs/期刊投稿 |
| Runner.module | autodokit.affairs.期刊投稿.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/期刊投稿/affair.md |

#### 模块说明

期刊投稿事务。

#### 事务 Markdown 说明摘录

- 期刊投稿

整理投稿包、登记版本并生成投稿记录。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| manuscript_title | 否 | "" | "" |
| package_files | 否 | [] | [] |
| target_journal | 否 | "" | "" |
| version_tag | 否 | "v1" | "v1" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| manuscript_title | 否 | "" | "" |
| package_files | 否 | [] | [] |
| target_journal | 否 | "" | "" |
| version_tag | 否 | "v1" | "v1" |

#### node.config JSON 示例

```json
{
  "manuscript_title": "",
  "target_journal": "",
  "package_files": [],
  "version_tag": "v1"
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "manuscript_title": "",
  "target_journal": "",
  "package_files": [],
  "version_tag": "v1"
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("期刊投稿",
    config={'manuscript_title': '', 'target_journal': '', 'package_files': [], 'version_tag': 'v1'},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.期刊投稿.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 模型路由派发

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 模型路由派发 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 模型路由派发 |
| 目录 | autodokit/affairs/模型路由派发 |
| Runner.module | autodokit.affairs.模型路由派发.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/模型路由派发/affair.md |

#### 模块说明

模型路由派发事务。

#### 事务 Markdown 说明摘录

- 模型路由派发

根据任务类型、质量、预算、时延和风险生成模型选择结果。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| budget_level | 否 | "medium" | "medium" |
| latency_level | 否 | "medium" | "medium" |
| mainland_only | 否 | true | true |
| output_dir | 否 | "" | "" |
| quality_tier | 否 | "standard" | "standard" |
| risk_level | 否 | "medium" | "medium" |
| task_type | 否 | "general" | "general" |
| workspace_root | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| budget_level | 否 | "medium" | "medium" |
| latency_level | 否 | "medium" | "medium" |
| mainland_only | 否 | true | true |
| output_dir | 否 | "" | "" |
| quality_tier | 否 | "standard" | "standard" |
| risk_level | 否 | "medium" | "medium" |
| task_type | 否 | "general" | "general" |
| workspace_root | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "task_type": "general",
  "quality_tier": "standard",
  "budget_level": "medium",
  "latency_level": "medium",
  "risk_level": "medium",
  "mainland_only": true,
  "workspace_root": "",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "task_type": "general",
  "quality_tier": "standard",
  "budget_level": "medium",
  "latency_level": "medium",
  "risk_level": "medium",
  "mainland_only": true,
  "workspace_root": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("模型路由派发",
    config={'task_type': 'general',
     'quality_tier': 'standard',
     'budget_level': 'medium',
     'latency_level': 'medium',
     'risk_level': 'medium',
     'mainland_only': True,
     'workspace_root': '',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.模型路由派发.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 清洗bibtex文件

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 清洗bibtex文件 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 清洗bibtex文件 |
| 目录 | autodokit/affairs/清洗bibtex文件 |
| Runner.module | autodokit.affairs.清洗bibtex文件.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/清洗bibtex文件/affair.md |

#### 模块说明

清洗 BibTeX 文件事务。

本事务用于处理“作者栏（author 字段）末尾多余分号”的常见脏数据：
- 单个作者被错误地写成 "Author;"；
- 多个作者用分号分隔时，最后一个作者末尾也多了一个 ";"。

事务行为（保持低风险、尽量不改变语义）：
- 仅对每条记录的 `author` 字段做清洗。
- 先移除尾部（末尾）一个或多个分号以及其后的空白。
- 对常见的分号分隔作者（`;` / `；`）规范化为 BibTeX 标准分隔符 ` and `，以便 Zotero 正确拆分多作者。
- 若已是 `and` 分隔，则仅做空白规范化，不重复改写。

输入/输出契约（必须遵守开发者指南）：
- 所有参与业务 IO 的路径字段必须为绝对路径；若收到相对路径应直接失败。

Args:
    config_path: 调度器写出的合并后临时配置文件路径（.json）。

Returns:
    清洗后写出的 BibTeX 文件路径列表（通常为 1 个文件）。

Examples:
    >>> from pathlib import Path
    >>> # 说明：此处仅展示调用方式；具体配置由调度器写入 .tmp/*.json
    >>> # from autodokit.affairs.清洗bibtex文件 import execute
    >>> # execute(Path(r"C:\workspace\.tmp\affair_config.json"))

#### 事务 Markdown 说明摘录

- 清洗bibtex文件

- 用途

- 该事务用于执行 `清洗bibtex文件` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("清洗bibtex文件",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.清洗bibtex文件.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 白名单治理检查

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 白名单治理检查 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 白名单治理检查 |
| 目录 | autodokit/affairs/白名单治理检查 |
| Runner.module | autodokit.affairs.白名单治理检查.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/白名单治理检查/affair.md |

#### 模块说明

白名单治理检查事务。

#### 事务 Markdown 说明摘录

- 白名单治理检查

检查申请权限范围与已批准白名单之间是否存在越权，并给出签发建议。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| approved_scopes | 否 | [] | [] |
| change_reason | 否 | "" | "" |
| operator | 否 | "" | "" |
| output_dir | 否 | "" | "" |
| requested_scopes | 否 | [] | [] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| approved_scopes | 否 | [] | [] |
| change_reason | 否 | "" | "" |
| operator | 否 | "" | "" |
| output_dir | 否 | "" | "" |
| requested_scopes | 否 | [] | [] |

#### node.config JSON 示例

```json
{
  "requested_scopes": [],
  "approved_scopes": [],
  "operator": "",
  "change_reason": "",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "requested_scopes": [],
  "approved_scopes": [],
  "operator": "",
  "change_reason": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("白名单治理检查",
    config={'requested_scopes': [],
     'approved_scopes': [],
     'operator': '',
     'change_reason': '',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.白名单治理检查.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 百炼SDK接入检查

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 百炼SDK接入检查 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 百炼SDK接入检查 |
| 目录 | autodokit/affairs/百炼SDK接入检查 |
| Runner.module | autodokit.affairs.百炼SDK接入检查.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/百炼SDK接入检查/affair.md |

#### 模块说明

百炼 SDK 接入检查事务。

#### 事务 Markdown 说明摘录

- 百炼SDK接入检查

检查百炼 API Key 文件、默认模型与端点配置是否具备运行前提，并写出结构化检查结果。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| endpoint | 否 | "https://dashscope.aliyuncs.com/compatible-mode/v1" | "https://dashscope.aliyuncs.com/compatible-mode/v1" |
| key_file | 否 | "" | "" |
| model | 否 | "qwen-plus" | "qwen-plus" |
| output_dir | 否 | "" | "" |
| workspace_root | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| endpoint | 否 | "https://dashscope.aliyuncs.com/compatible-mode/v1" | "https://dashscope.aliyuncs.com/compatible-mode/v1" |
| key_file | 否 | "" | "" |
| model | 否 | "qwen-plus" | "qwen-plus" |
| output_dir | 否 | "" | "" |
| workspace_root | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "key_file": "",
  "model": "qwen-plus",
  "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "workspace_root": "",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "key_file": "",
  "model": "qwen-plus",
  "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "workspace_root": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("百炼SDK接入检查",
    config={'key_file': '',
     'model': 'qwen-plus',
     'endpoint': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
     'workspace_root': '',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.百炼SDK接入检查.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 研究构思

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 研究构思 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 研究构思 |
| 目录 | autodokit/affairs/研究构思 |
| Runner.module | autodokit.affairs.研究构思.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/研究构思/affair.md |

#### 模块说明

研究构思事务。

#### 事务 Markdown 说明摘录

- 研究构思

把一个宽泛主题整理成研究问题、假设和阶段路线图。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| literature_gaps | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| target_journal | 否 | "" | "" |
| topic | 否 | "" | "" |
| variable_ideas | 否 | [] | [] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| literature_gaps | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| target_journal | 否 | "" | "" |
| topic | 否 | "" | "" |
| variable_ideas | 否 | [] | [] |

#### node.config JSON 示例

```json
{
  "topic": "",
  "literature_gaps": [],
  "variable_ideas": [],
  "target_journal": "",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "topic": "",
  "literature_gaps": [],
  "variable_ideas": [],
  "target_journal": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("研究构思",
    config={'topic': '',
     'literature_gaps': [],
     'variable_ideas': [],
     'target_journal': '',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.研究构思.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 研究诚信检查

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 研究诚信检查 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 研究诚信检查 |
| 目录 | autodokit/affairs/研究诚信检查 |
| Runner.module | autodokit.affairs.研究诚信检查.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/研究诚信检查/affair.md |

#### 模块说明

研究诚信检查事务。

执行最小可复用的文本扫描规则，识别疑似密钥硬编码与私钥片段。

#### 事务 Markdown 说明摘录

- 研究诚信检查

扫描项目文本文件中的疑似密钥硬编码与私钥片段，输出命中明细与统计摘要。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| include_extensions | 否 | [".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt"] | [".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt"] |
| output_dir | 否 | "" | "" |
| project_root | 否 | "" | "" |
| strict | 否 | false | false |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| include_extensions | 否 | [".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt"] | [".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt"] |
| output_dir | 否 | "" | "" |
| project_root | 否 | "" | "" |
| strict | 否 | false | false |

#### node.config JSON 示例

```json
{
  "project_root": "",
  "strict": false,
  "include_extensions": [
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".txt"
  ],
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_root": "",
  "strict": false,
  "include_extensions": [
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".txt"
  ],
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("研究诚信检查",
    config={'project_root': '',
     'strict': False,
     'include_extensions': ['.py', '.md', '.json', '.yaml', '.yml', '.toml', '.txt'],
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.研究诚信检查.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 管理文档单元数据库

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 管理文档单元数据库 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 管理文档单元数据库 |
| 目录 | autodokit/affairs/管理文档单元数据库 |
| Runner.module | autodokit.affairs.管理文档单元数据库.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/管理文档单元数据库/affair.md |

#### 模块说明

构建文档单元数据库事务。

本事务仅做一件事：
- 从原始文档目录（当前仅支持 .md/.tex）读取文件，按“单元”切分（标题/段落/公式/图表/代码块/引文等），
  然后把每个单元落盘到 Unit DB，并写出索引数据库（units.jsonl/units.csv）。

为何单独做成事务：
- 方便把“知识库预处理”作为独立可重复的步骤运行；
- 便于后续事务（检索/向量化/阅读辅助）复用同一份 Unit DB。

配置字段（均必须为绝对路径，由调度层统一绝对化，符合开发者指南）：
- input_documents_dir: 原始文档目录（绝对路径，仅 md/tex）。
- unit_db_dir: Unit DB 根目录（绝对路径，例如 <workspace_root>/data/文档单元数据库）。

输出：
- <unit_db_dir>/data/*.txt
- <unit_db_dir>/units.jsonl
- <unit_db_dir>/units.csv
- <output_dir>/unit_db_stats.json（可选）

输出文件说明（目的与主要字段）

下面对常见输出文件的作用与字段做说明，便于调用者和维护者理解生成产物的结构与用途：

units.jsonl（主索引，行分隔 JSON）
- 作用：主索引文件，追加写入模式，记录每个文档单元（unit）的元信息，便于流式读取和后续处理（例如向量化、检索索引构建）。
- 每一行（JSON 对象）典型字段：
  - unit_uid: 单元唯一标识（稳定哈希，可用于文件名与跨运行追踪）。
  - unit_type: 单元类型（例如 paragraph/heading/equation 等）。
  - unit_index: 单元在源文档中的序号（从 0 开始）。
  - doc_name: 文档名（通常为文件 stem）。
  - doc_uid: 可选文档 UID（如有外部生成）。
  - source_rel_path: 源文件相对路径（相对于文档输入根，使用 / 分隔）。
  - source_abs_path: 源文件绝对路径（便于定位源文档）。
  - unit_file: 对应的单元内容文件路径（data 目录下的 .txt 文件）。
  - created_at: 写入时间戳（包含微秒与随机后缀，用于调试与排序）。
  - prev_unit_uid / next_unit_uid: 相邻单元的 unit_uid，便于按文档顺序串联。
  - heading_level / context_heading_text / context_heading_level: 常用上下文字段，表示单元所在的标题层级与最近的上下文标题文本。
  - extra_doc_meta: 写入时附加的文档级元信息（例如 doc_sha1、workflow 标识等），通常为对象/字典。
  - unit_meta: 单元级的原始 meta（来自分块器），可包含更多上下文信息。

units.csv（CSV 汇总）
- 作用：从 JSONL 重建的表格形式索引，便于用 Excel 或 pandas 快速查看与筛选。
- 说明：CSV 包含与 JSONL 等价的列；其中复杂字段（extra_doc_meta、unit_meta）被序列化为 JSON 字符串，以避免列爆炸。

data/*.txt（单元内容文件）
- 作用：每个单元的原始文本内容以 UTF-8 文本文件存储，便于人工检查与外部工具读取。
- 命名与格式：文件名为 {unit_uid}.txt，编码 UTF-8，内容为单元文本（末尾含换行）。
- 说明：索引中的 unit_file 字段指向这些文件的绝对路径；在删除单元时，管理逻辑可选择同时删除对应的 .txt 文件。

unit_db_stats.json / unit_db_manage_stats.json（运行统计与路径汇总）
- 作用：记录本次事务的输入/输出路径、变更统计与参数设置，便于审计、后续步骤接入与调试。
- 典型字段（可能根据具体事务略有差别）：
  - input_documents_dir: 本次扫描的输入文档根目录（绝对路径）。
  - unit_db_dir: Unit DB 根目录（绝对路径）。
  - documents_added: 被判定为新增的文档数量（仅管理事务）。
  - documents_removed: 被判定为删除的文档数量（仅管理事务）。
  - documents_modified: 被判定为修改的文档数量（仅管理事务）。
  - documents_processed / documents: 实际被处理的文档数（按场景命名不同）。
  - units_written: 本次写入的单元总数（整数）。
  - index_jsonl / index_csv / data_dir: 生成产物的路径（用于快速定位）。
  - allowed_suffixes: 允许的源文件后缀列表（例如 [".md", ".tex"]）。
  - change_detect_strategy: 变更检测策略（如 mtime_size / hash / mtime_size_then_hash）。
  - full_rebuild: 是否执行了全量重建（布尔）。

doc_manifest.json（扫描清单与变更明细）
- 作用：当管理事务开启文档持久化 manifest 时，写出本次扫描结果的详细清单，便于审计与增量逻辑验证。
- 结构与字段：
  - scan: 一个对象，键为源文档的相对路径，值为该文档的扫描状态信息，典型子字段：
    - rel: 源文档相对路径（/ 分隔）。
    - abs: 源文档绝对路径。
    - mtime_ns: 文件修改时间（纳秒）。
    - size: 文件大小（字节）。
    - sha1:（可选）在使用 hash 策略时记录的文件内容哈希。
  - added: 新检测到的文档列表（相对路径字符串）。
  - removed: 被检测为删除的文档列表。
  - modified: 被判定为修改的文档列表。

一致性与使用建议
- 推荐在每次运行后用 stats 中的 units_written 与 data 目录中文件数或 units.jsonl 的行数做一致性检查，确保索引与落盘文件匹配。
- 注意：write_units_to_db 采用 JSONL 追加写入以提高性能；管理事务在结束时会调用重写索引以清理历史脏行并重建 CSV，从而保持索引整洁。

Args:
    config_path: 调度器写入的临时配置文件路径。

Returns:
    写出的文件路径列表。

#### 事务 Markdown 说明摘录

- 管理文档单元数据库

- 用途

- 该事务用于执行 `管理文档单元数据库` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| documents | documents | dir |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| unit_db | unit_db | dir |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| documents | documents | dir |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| unit_db | unit_db | dir |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| input_documents_dir | 否 | "data/文献原文数据" | "data/文献原文数据" |
| output_dir | 否 | "workflows/workflow_管理文档单元数据库/data/01_unit_db" | "workflows/workflow_管理文档单元数据库/data/01_unit_db" |
| unit_db_dir | 否 | "data/文档单元数据库" | "data/文档单元数据库" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| input_documents_dir | 否 | "data/文献原文数据" | "data/文献原文数据" |
| output_dir | 否 | "workflows/workflow_管理文档单元数据库/data/01_unit_db" | "workflows/workflow_管理文档单元数据库/data/01_unit_db" |
| unit_db_dir | 否 | "data/文档单元数据库" | "data/文档单元数据库" |

#### node.config JSON 示例

```json
{
  "input_documents_dir": "data/文献原文数据",
  "unit_db_dir": "data/文档单元数据库",
  "output_dir": "workflows/workflow_管理文档单元数据库/data/01_unit_db"
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "input_documents_dir": "data/文献原文数据",
  "unit_db_dir": "data/文档单元数据库",
  "output_dir": "workflows/workflow_管理文档单元数据库/data/01_unit_db"
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("管理文档单元数据库",
    config={'input_documents_dir': 'data/文献原文数据',
     'unit_db_dir': 'data/文档单元数据库',
     'output_dir': 'workflows/workflow_管理文档单元数据库/data/01_unit_db'},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.管理文档单元数据库.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 结果分析解读

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 结果分析解读 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 结果分析解读 |
| 目录 | autodokit/affairs/结果分析解读 |
| Runner.module | autodokit.affairs.结果分析解读.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/结果分析解读/affair.md |

#### 模块说明

结果分析解读事务。

#### 事务 Markdown 说明摘录

- 结果分析解读

把统计摘要转成论文可用的叙述、图表规格和表格规格。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| mechanism_points | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| significance_notes | 否 | [] | [] |
| statistical_summary | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| mechanism_points | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| significance_notes | 否 | [] | [] |
| statistical_summary | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "statistical_summary": "",
  "mechanism_points": [],
  "significance_notes": [],
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "statistical_summary": "",
  "mechanism_points": [],
  "significance_notes": [],
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("结果分析解读",
    config={'statistical_summary': '',
     'mechanism_points': [],
     'significance_notes': [],
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.结果分析解读.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 计量环境配置

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 计量环境配置 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 计量环境配置 |
| 目录 | autodokit/affairs/计量环境配置 |
| Runner.module | autodokit.affairs.计量环境配置.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/计量环境配置/affair.md |

#### 模块说明

计量环境配置事务。

#### 事务 Markdown 说明摘录

- 计量环境配置

生成 Python/R/Stata 计量运行时准备状态摘要。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "" | "" |
| python_baseline | 否 | "3.13" | "3.13" |
| require_r | 否 | true | true |
| require_stata | 否 | false | false |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "" | "" |
| python_baseline | 否 | "3.13" | "3.13" |
| require_r | 否 | true | true |
| require_stata | 否 | false | false |

#### node.config JSON 示例

```json
{
  "project_root": "",
  "require_r": true,
  "require_stata": false,
  "python_baseline": "3.13",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_root": "",
  "require_r": true,
  "require_stata": false,
  "python_baseline": "3.13",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("计量环境配置",
    config={'project_root': '',
     'require_r': True,
     'require_stata': False,
     'python_baseline': '3.13',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.计量环境配置.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 论文整编写作

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 论文整编写作 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 论文整编写作 |
| 目录 | autodokit/affairs/论文整编写作 |
| Runner.module | autodokit.affairs.论文整编写作.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/论文整编写作/affair.md |

#### 模块说明

论文整编写作事务。

#### 事务 Markdown 说明摘录

- 论文整编写作

把各章节材料和证据点整编成一份连续草稿。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| evidence_points | 否 | [] | [] |
| journal_style | 否 | "general" | "general" |
| output_dir | 否 | "" | "" |
| section_materials | 否 | {} | {} |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| evidence_points | 否 | [] | [] |
| journal_style | 否 | "general" | "general" |
| output_dir | 否 | "" | "" |
| section_materials | 否 | {} | {} |

#### node.config JSON 示例

```json
{
  "section_materials": {},
  "evidence_points": [],
  "journal_style": "general",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "section_materials": {},
  "evidence_points": [],
  "journal_style": "general",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("论文整编写作",
    config={'section_materials': {},
     'evidence_points': [],
     'journal_style': 'general',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.论文整编写作.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 论文自审

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 论文自审 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 论文自审 |
| 目录 | autodokit/affairs/论文自审 |
| Runner.module | autodokit.affairs.论文自审.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/论文自审/affair.md |

#### 模块说明

论文自审事务。

#### 事务 Markdown 说明摘录

- 论文自审

从结构完整性、图表准备和关键章节覆盖情况做内部自审。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| figures | 否 | [] | [] |
| manuscript_title | 否 | "" | "" |
| output_dir | 否 | "" | "" |
| sections | 否 | {} | {} |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| figures | 否 | [] | [] |
| manuscript_title | 否 | "" | "" |
| output_dir | 否 | "" | "" |
| sections | 否 | {} | {} |

#### node.config JSON 示例

```json
{
  "manuscript_title": "",
  "sections": {},
  "figures": [],
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "manuscript_title": "",
  "sections": {},
  "figures": [],
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("论文自审",
    config={'manuscript_title': '', 'sections': {}, 'figures': [], 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.论文自审.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 论文草稿

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 论文草稿 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 论文草稿 |
| 目录 | autodokit/affairs/论文草稿 |
| Runner.module | autodokit.affairs.论文草稿.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/论文草稿/affair.md |

#### 模块说明

论文草稿事务。

#### 事务 Markdown 说明摘录

- 论文草稿

基于主题、贡献与局限生成论文草稿骨架。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| contributions | 否 | [] | [] |
| limitations | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| topic | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| contributions | 否 | [] | [] |
| limitations | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| topic | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "topic": "",
  "contributions": [],
  "limitations": [],
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "topic": "",
  "contributions": [],
  "limitations": [],
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("论文草稿",
    config={'topic': '', 'contributions': [], 'limitations': [], 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.论文草稿.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 证据综合

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 证据综合 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 证据综合 |
| 目录 | autodokit/affairs/证据综合 |
| Runner.module | autodokit.affairs.证据综合.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/证据综合/affair.md |

#### 模块说明

证据综合事务。

对候选证据文本进行最小化 RAG 综合，输出证据矩阵与综合摘要。

#### 事务 Markdown 说明摘录

- 证据综合

对候选证据执行最小化 RAG 综合，输出证据矩阵与摘要结论。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| passages | 否 | [] | [] |
| question | 否 | "" | "" |
| top_k | 否 | 3 | 3 |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| passages | 否 | [] | [] |
| question | 否 | "" | "" |
| top_k | 否 | 3 | 3 |

#### node.config JSON 示例

```json
{
  "question": "",
  "passages": [],
  "top_k": 3,
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "question": "",
  "passages": [],
  "top_k": 3,
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("证据综合",
    config={'question': '', 'passages': [], 'top_k': 3, 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.证据综合.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 项目初始化

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 项目初始化 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 项目初始化 |
| 目录 | autodokit/affairs/项目初始化 |
| Runner.module | autodokit.affairs.项目初始化.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/项目初始化/affair.md |

#### 模块说明

项目初始化事务。

#### 事务 Markdown 说明摘录

- 项目初始化

基于 AOK 内置模板初始化任务数据库、文献数据库、知识数据库和调度配置目录。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "project_root": "",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_root": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("项目初始化",
    config={'project_root': '', 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.项目初始化.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 8. unknown 类事务

### AOB一键办公区转换

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | AOB一键办公区转换 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/AOB一键办公区转换 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/AOB一键办公区转换/affair.md |

#### 模块说明

AOB 一键办公区转换事务。

#### 事务 Markdown 说明摘录

- AOB一键办公区转换

调用 `autodokit.tools.run_aob_workspace_convert` 执行模板项目办公区跨引擎转换。

固定输出文件：

- `aob_workspace_convert_result.json`

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| dry_run | 否 | true | true |
| output_dir | 否 | "" | "" |
| project_dir | 否 | "" | "" |
| repo_root | 否 | "" | "" |
| source_engine | 否 | "opencode" | "opencode" |
| target_engine | 否 | "claude" | "claude" |
| title | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_dir": "",
  "source_engine": "opencode",
  "target_engine": "claude",
  "title": "",
  "dry_run": true,
  "repo_root": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("AOB一键办公区转换",
    config={'project_dir': '',
     'source_engine': 'opencode',
     'target_engine': 'claude',
     'title': '',
     'dry_run': True,
     'repo_root': '',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from  import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### AOB一键安装部署

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | AOB一键安装部署 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/AOB一键安装部署 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/AOB一键安装部署/affair.md |

#### 模块说明

AOB 一键安装部署事务。

#### 事务 Markdown 说明摘录

- AOB一键安装部署

调用 `autodokit.tools.run_aob_workflow_deploy` 执行工作流一键部署。

固定输出文件：

- `aob_one_click_deploy_result.json`

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| dry_run | 否 | true | true |
| engine_ids | 否 | ["opencode"] | ["opencode"] |
| extras | 否 | "none" | "none" |
| git_init_mode | 否 | "auto" | "auto" |
| on_conflict | 否 | "skip" | "skip" |
| output_dir | 否 | "" | "" |
| project_name | 否 | "" | "" |
| repo_root | 否 | "" | "" |
| skip_health_check | 否 | false | false |
| tags | 否 | "" | "" |
| target_dir | 否 | "" | "" |
| workflow | 否 | "academic" | "academic" |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "workflow": "academic",
  "engine_ids": [
    "opencode"
  ],
  "target_dir": "",
  "project_name": "",
  "tags": "",
  "on_conflict": "skip",
  "skip_health_check": false,
  "extras": "none",
  "git_init_mode": "auto",
  "dry_run": true,
  "repo_root": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("AOB一键安装部署",
    config={'workflow': 'academic',
     'engine_ids': ['opencode'],
     'target_dir': '',
     'project_name': '',
     'tags': '',
     'on_conflict': 'skip',
     'skip_health_check': False,
     'extras': 'none',
     'git_init_mode': 'auto',
     'dry_run': True,
     'repo_root': '',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from  import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### AOK三库联动示例

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | AOK三库联动示例 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/AOK三库联动示例 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/AOK三库联动示例/affair.md |

#### 模块说明

AOK 三库联动示例事务。

该事务用于演示最近落地的三库协同最小闭环：
1. 内容主库：从 BibTeX 导入条目并登记附件；
2. 知识笔记资产：生成文献标准笔记，并把关联事实同步到统一内容主库；
3. 任务库：创建 AOK 任务并绑定文献/知识 UID，再登记产物。

特别说明：
- 输入的 RDF 数据目录是 Zotero 嵌套结构，事务会手动把 `files/` 下附件提取并复制到
  示例工作区 `references/attachments/` 目录，不依赖扁平目录结构。

#### 事务 Markdown 说明摘录

- AOK三库联动示例

演示 AOK 最新三库联动最小闭环：

1. 从 BibTeX 导入文献主表记录并写入统一内容主库；
2. 从 Zotero RDF `files/` 嵌套目录手动提取并复制附件到 `references/attachments/`；
3. 生成知识标准笔记，并把关联事实同步到统一内容主库；
4. 创建 AOK 任务、绑定文献/知识 UID，并登记产物后导出任务包。

- 输入参数

- `project_root`：示例工作区绝对路径。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| bib_path | 否 | "" | "" |
| max_attachments | 否 | 6 | 6 |
| max_bib_records | 否 | 3 | 3 |
| output_dir | 否 | "" | "" |
| project_root | 否 | "" | "" |
| rdf_files_root | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_root": "",
  "bib_path": "",
  "rdf_files_root": "",
  "max_bib_records": 3,
  "max_attachments": 6,
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("AOK三库联动示例",
    config={'project_root': '',
     'bib_path': '',
     'rdf_files_root': '',
     'max_bib_records': 3,
     'max_attachments': 6,
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from  import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### AOK任务数据库初始化

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | AOK任务数据库初始化 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/AOK任务数据库初始化 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/AOK任务数据库初始化/affair.md |

#### 模块说明

AOK 旧任务数据库初始化事务。

本事务仍保留在代码库中，仅用于迁移期读取旧 taskdb 结构。
新流程应改用运行基线与日志基线，不再把 taskdb 作为主契约。

#### 事务 Markdown 说明摘录

- AOK任务数据库初始化

初始化 AOK 003 版任务数据库骨架，创建以下最小结构：

- `database/tasks/tasks.csv`
- `database/tasks/task_artifacts.csv`
- `tasks/`

本事务与旧版 `任务数据库初始化` 事务隔离，避免混用 AOE 语义字段与文件结构。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "." | "." |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_root": ".",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("AOK任务数据库初始化",
    config={'project_root': '.', 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from  import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### AOK任务数据库校验

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | AOK任务数据库校验 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/AOK任务数据库校验 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/AOK任务数据库校验/affair.md |

#### 模块说明

AOK 旧任务数据库校验事务。

本事务仍保留在代码库中，仅用于迁移期读取旧 taskdb 结构。
新流程应改用运行基线与日志基线，不再把 taskdb 作为主契约。

#### 事务 Markdown 说明摘录

- AOK任务数据库校验

校验 AOK 003 版任务数据库最小契约：

- `database/tasks/tasks.csv`
- `database/tasks/task_artifacts.csv`
- `tasks/`

并执行一致性检查（任务目录存在性、任务产物路径存在性、可用时的文献/知识 UID 引用校验）。

本事务与旧版 `任务数据库校验` 事务隔离，避免混用 AOE 语义校验规则。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| project_root | 否 | "." | "." |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_root": ".",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("AOK任务数据库校验",
    config={'project_root': '.', 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from  import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### Skill渲染

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | Skill渲染 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/Skill渲染 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/Skill渲染/affair.md |

#### 模块说明

Skill 渲染事务。

#### 事务 Markdown 说明摘录

- Skill渲染

- 用途

该事务用于接收 `SKILL.md` 文件绝对路径与参数字典，调用引擎中的 Skill 渲染器生成最终 Prompt 文本，并输出结构化结果 JSON。

- 运行入口

- module: `autodokit.affairs.Skill渲染.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| params | 否 | {} | {} |
| skill_path | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "skill_path": "",
  "params": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("Skill渲染",
    config={'skill_path': '', 'params': {}, 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from  import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 创新点可行性验证

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 创新点可行性验证 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/创新点可行性验证 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/创新点可行性验证/affair.md |

#### 模块说明

创新点可行性验证事务。

#### 事务 Markdown 说明摘录

- 创新点可行性验证

- 用途

服务 A13 节点，对创新点池条目做数据、方法、场景、产出四维评分。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| innovation_pool_csv | 否 | "" | "" |
| innovations | 否 | [] | [] |
| output_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "innovation_pool_csv": "",
  "innovations": [],
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("创新点可行性验证",
    config={'innovation_pool_csv': '', 'innovations': [], 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from  import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 创新点池构建

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 创新点池构建 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/创新点池构建 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/创新点池构建/affair.md |

#### 模块说明

创新点池构建事务。

#### 事务 Markdown 说明摘录

- 创新点池构建

- 用途

服务 A12 节点，围绕研究缺口与知识框架构建编号化创新点池。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| data_source | 否 | "" | "" |
| gaps | 否 | [] | [] |
| method_family | 否 | "" | "" |
| output_dir | 否 | "" | "" |
| output_form | 否 | "" | "" |
| scenario | 否 | "" | "" |
| topic | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "topic": "",
  "gaps": [],
  "scenario": "",
  "data_source": "",
  "method_family": "",
  "output_form": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("创新点池构建",
    config={'topic': '',
     'gaps': [],
     'scenario': '',
     'data_source': '',
     'method_family': '',
     'output_form': '',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from  import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 单篇粗读

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 单篇粗读 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/单篇粗读 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/单篇粗读/affair.md |

#### 模块说明

单篇文献粗读事务。

该事务用于在“单篇精读”之前做快速预处理：
- 读取目标文献的结构化结果（`*.structured.json`）；
- 提取参考文献行并可选回写占位引文；
- 生成粗读笔记与结构化 JSON 结果，供后续精读链路复用。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件路径列表。

Examples:
    >>> from pathlib import Path
    >>> from autodokit.affairs.单篇粗读.affair import execute
    >>> execute(Path(r"D:/workspace/configs/single_rough_reading.json"))

#### 事务 Markdown 说明摘录

- 单篇粗读

- 用途

- 该事务用于执行 `单篇粗读` 对应的业务逻辑。
- 面向“先粗后精”的主链流程，先快速抽取文献信息与参考文献，再把结果交给后续精读事务。

- 运行入口

- module: `autodokit.affairs.单篇粗读.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| doc_id | 否 | null | null |
| content_db | 否 | "" | "" |
| input_structured_dir | 否 | "" | "" |
| input_structured_json | 否 | "" | "" |
| insert_placeholders_from_references | 否 | true | true |
| max_preview_chars | 否 | 4000 | 4000 |
| output_dir | 否 | "workflows/workflow_单篇粗读/output/05_single_rough_reading" | "workflows/workflow_单篇粗读/output/05_single_rough_reading" |
| reference_lines | 否 | [] | [] |
| uid | 否 | 1 | 1 |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "content_db": "",
  "input_structured_json": "",
  "input_structured_dir": "",
  "output_dir": "workflows/workflow_单篇粗读/output/05_single_rough_reading",
  "uid": 1,
  "doc_id": null,
  "insert_placeholders_from_references": true,
  "reference_lines": [],
  "max_preview_chars": 4000
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("单篇粗读",
  config={'content_db': '',
   'input_structured_json': '',
   'input_structured_dir': '',
     'output_dir': 'workflows/workflow_单篇粗读/output/05_single_rough_reading',
     'uid': 1,
     'doc_id': None,
     'insert_placeholders_from_references': True,
     'reference_lines': [],
     'max_preview_chars': 4000},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from  import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 研究脉络梳理

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 研究脉络梳理 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/研究脉络梳理 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/研究脉络梳理/affair.md |

#### 模块说明

研究脉络梳理事务。

#### 事务 Markdown 说明摘录

- 研究脉络梳理

- 用途

服务 A10 节点，整理时间演进型研究脉络，并输出统一闸门审计结果。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| input_csv | 否 | "" | "" |
| items | 否 | [] | [] |
| output_dir | 否 | "" | "" |
| topic | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "topic": "",
  "input_csv": "",
  "items": [],
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("研究脉络梳理",
    config={'topic': '', 'input_csv': '', 'items': [], 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from  import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 9. 任务文档事务

### task_docs_aggregate

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | task_docs_aggregate |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 task_docs_aggregate |
| 目录 | autodokit/affairs/task_docs_aggregate |
| Runner.module | autodokit.affairs.task_docs_aggregate.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/task_docs_aggregate/affair.md |

#### 模块说明

事务：聚合任务文档产物生成汇总。

本事务把【通用文档管理工作流】中的 `aggregate_task.py` 工程化为 AOK affair。

输入（config.json，核心字段）：
- root_dir: 扫描根目录（必填）
- task_name: 任务名称（必填）
- output_dir: 输出目录（必填）
- uid_mode: UID 模式（可选，默认 timestamp-us-rand）
- uid_random_length: 随机后缀长度（可选，默认 2）
- dry_run: 是否不写文件（可选，默认 false）

输出：
- 汇总文件路径列表（找不到源文件则返回空列表）。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。

#### 事务 Markdown 说明摘录

- task_docs_aggregate

- 用途

- 该事务用于执行 `task_docs_aggregate` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("task_docs_aggregate",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.task_docs_aggregate.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### task_docs_archive

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | task_docs_archive |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 task_docs_archive |
| 目录 | autodokit/affairs/task_docs_archive |
| Runner.module | autodokit.affairs.task_docs_archive.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/task_docs_archive/affair.md |

#### 模块说明

事务：归档任务文档（移动到 archives 并更新 tags）。

输入（config，核心字段）：
- root_dir: 扫描根目录（必填）
- task_name: 任务名（必填）
- archive_dir: 归档目录（可选；默认 <root_dir>/archives）
- include_latest: 是否包含 latest（可选，默认 false）
- dry_run: 是否干运行（可选，默认 false）

输出：
- 移动后的文件路径列表。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。

#### 事务 Markdown 说明摘录

- task_docs_archive

- 用途

- 该事务用于执行 `task_docs_archive` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

- 无

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

- 无

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("task_docs_archive",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.task_docs_archive.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### task_docs_create_latest

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | task_docs_create_latest |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 task_docs_create_latest |
| 目录 | autodokit/affairs/task_docs_create_latest |
| Runner.module | autodokit.affairs.task_docs_create_latest.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/task_docs_create_latest/affair.md |

#### 模块说明

事务：创建任务 latest 文档。

本事务把【通用文档管理工作流】中的 `create_latest.py` 工程化为 AOK affair。

输入（config.json，核心字段）：
- task_name: 任务名称（必填）
- doc_types: 文档类型列表，例如 ["需求","设计","过程"]（必填）
- output_dir: 输出目录（必填）
- uid_mode: UID 模式（可选，默认 timestamp-us-rand）
- uid_random_length: 随机后缀长度（可选，默认 2）
- overwrite: 是否覆盖已存在文件（可选，默认 false）

输出：
- 写出的 Markdown 文件路径列表。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。

#### 事务 Markdown 说明摘录

- task_docs_create_latest

- 用途

- 该事务用于执行 `task_docs_create_latest` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

- 无

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

- 无

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("task_docs_create_latest",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.task_docs_create_latest.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### task_docs_finalize_latest

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | task_docs_finalize_latest |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 task_docs_finalize_latest |
| 目录 | autodokit/affairs/task_docs_finalize_latest |
| Runner.module | autodokit.affairs.task_docs_finalize_latest.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/task_docs_finalize_latest/affair.md |

#### 模块说明

事务：latest→UID 固化（重命名 + 同步 frontmatter）。

把 `任务名-需求/设计/过程-latest.md` 固化为 `任务名-需求/设计/过程-<UID>.md`。

UID 来源：
- 默认从 frontmatter 的 tags 中读取 `#时间戳/<UID>`。
- 可选：当缺失时生成 UID 并回写（generate_if_missing=true）。

输入（config，核心字段）：
- root_dir: 扫描根目录（必填）
- task_name: 任务名称（必填）
- doc_types: 类型列表（可选，默认 ["需求","设计","过程"]）
- generate_if_missing: UID 缺失时是否生成并回写（可选，默认 false）
- uid_mode / uid_random_length: 生成 UID 时使用（可选）
- dry_run: 是否干运行（可选，默认 false）

输出：
- 固化后的文件路径列表。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。

#### 事务 Markdown 说明摘录

- task_docs_finalize_latest

- 用途

- 该事务用于执行 `task_docs_finalize_latest` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

- 无

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

- 无

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("task_docs_finalize_latest",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.task_docs_finalize_latest.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 10. 图节点事务 / calc

### 图节点_calc

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 图节点_calc |
| 领域 | graph |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 图节点_calc |
| 目录 | autodokit/affairs/图节点_calc |
| Runner.module | autodokit.affairs.图节点_calc.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/图节点_calc/affair.md |

#### 模块说明

图节点事务：calc。

本事务用于执行常见计算表达式。
P1 阶段使用受限表达式执行器实现最小可运行能力。

#### 事务 Markdown 说明摘录

- 图节点_calc

- 用途

- 该事务用于执行 `图节点_calc` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| result | result | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| result | result | any |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| allow_unsafe_eval | 否 | false | false |
| expression | 否 | "" | "" |
| expression_mode | 否 | "safe" | "safe" |
| variables | 否 | {} | {} |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| allow_unsafe_eval | 否 | false | false |
| expression | 否 | "" | "" |
| expression_mode | 否 | "safe" | "safe" |
| variables | 否 | {} | {} |

#### node.config JSON 示例

```json
{
  "expression": "",
  "expression_mode": "safe",
  "allow_unsafe_eval": false,
  "variables": {}
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "expression": "",
  "expression_mode": "safe",
  "allow_unsafe_eval": false,
  "variables": {}
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("图节点_calc",
    config={'expression': '',
     'expression_mode': 'safe',
     'allow_unsafe_eval': False,
     'variables': {}},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.图节点_calc.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 11. 图节点事务 / compare

### 图节点_compare

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 图节点_compare |
| 领域 | graph |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 图节点_compare |
| 目录 | autodokit/affairs/图节点_compare |
| Runner.module | autodokit.affairs.图节点_compare.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/图节点_compare/affair.md |

#### 模块说明

图节点事务：compare。

本事务用于执行比较判断（含不等号判断）。
P1 阶段提供最小比较能力并输出分支方向。

#### 事务 Markdown 说明摘录

- 图节点_compare

- 用途

- 该事务用于执行 `图节点_compare` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| left | left | any |
| right | right | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| true | true | any |
| false | false | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| left | left | any |
| right | right | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| true | true | any |
| false | false | any |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| left | 否 | null | null |
| operator | 否 | "!=" | "!=" |
| right | 否 | null | null |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| left | 否 | null | null |
| operator | 否 | "!=" | "!=" |
| right | 否 | null | null |

#### node.config JSON 示例

```json
{
  "left": null,
  "operator": "!=",
  "right": null
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "left": null,
  "operator": "!=",
  "right": null
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("图节点_compare",
    config={'left': None, 'operator': '!=', 'right': None},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.图节点_compare.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 12. 图节点事务 / container

### 图节点_container

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 图节点_container |
| 领域 | graph |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 图节点_container |
| 目录 | autodokit/affairs/图节点_container |
| Runner.module | autodokit.affairs.图节点_container.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/图节点_container/affair.md |

#### 模块说明

图节点事务：container。

本事务用于表达可嵌套容器节点及其循环配置。
P1 阶段仅解析并回显容器循环参数。

#### 事务 Markdown 说明摘录

- 图节点_container

- 用途

- 该事务用于执行 `图节点_container` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| allow_unsafe_eval | 否 | false | false |
| container_name | 否 | "container" | "container" |
| expression_mode | 否 | "safe" | "safe" |
| loop | 否 | {"enabled": false, "max_iterations": 1, "stop_condition": ""} | {"enabled": false, "max_iterations": 1, "stop_condition": ""} |
| variables | 否 | {} | {} |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| allow_unsafe_eval | 否 | false | false |
| container_name | 否 | "container" | "container" |
| expression_mode | 否 | "safe" | "safe" |
| loop | 否 | {"enabled": false, "max_iterations": 1, "stop_condition": ""} | {"enabled": false, "max_iterations": 1, "stop_condition": ""} |
| variables | 否 | {} | {} |

#### node.config JSON 示例

```json
{
  "container_name": "container",
  "expression_mode": "safe",
  "allow_unsafe_eval": false,
  "variables": {},
  "loop": {
    "enabled": false,
    "max_iterations": 1,
    "stop_condition": ""
  }
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "container_name": "container",
  "expression_mode": "safe",
  "allow_unsafe_eval": false,
  "variables": {},
  "loop": {
    "enabled": false,
    "max_iterations": 1,
    "stop_condition": ""
  }
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("图节点_container",
    config={'container_name': 'container',
     'expression_mode': 'safe',
     'allow_unsafe_eval': False,
     'variables': {},
     'loop': {'enabled': False, 'max_iterations': 1, 'stop_condition': ''}},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.图节点_container.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 13. 图节点事务 / end

### 图节点_end

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 图节点_end |
| 领域 | graph |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 图节点_end |
| 目录 | autodokit/affairs/图节点_end |
| Runner.module | autodokit.affairs.图节点_end.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/图节点_end/affair.md |

#### 模块说明

图节点事务：end。

本事务用于表示流程的结束节点。
P1 阶段仅提供可调度与可观测占位实现。

#### 事务 Markdown 说明摘录

- 图节点_end

- 用途

- 该事务用于执行 `图节点_end` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

- 无

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| node_role | 否 | "end" | "end" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| node_role | 否 | "end" | "end" |

#### node.config JSON 示例

```json
{
  "node_role": "end"
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "node_role": "end"
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("图节点_end",
    config={'node_role': 'end'},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.图节点_end.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 14. 图节点事务 / fork

### 图节点_fork

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 图节点_fork |
| 领域 | graph |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 图节点_fork |
| 目录 | autodokit/affairs/图节点_fork |
| Runner.module | autodokit.affairs.图节点_fork.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/图节点_fork/affair.md |

#### 模块说明

图节点事务：fork。

本事务用于将流程分发到多个并发分支。
P1 阶段仅输出分支规划信息，不直接调度并发执行。

#### 事务 Markdown 说明摘录

- 图节点_fork

- 用途

- 该事务用于执行 `图节点_fork` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| branch_1 | branch_1 | any |
| branch_2 | branch_2 | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| branch_1 | branch_1 | any |
| branch_2 | branch_2 | any |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| branches | 否 | ["branch_1", "branch_2"] | ["branch_1", "branch_2"] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| branches | 否 | ["branch_1", "branch_2"] | ["branch_1", "branch_2"] |

#### node.config JSON 示例

```json
{
  "branches": [
    "branch_1",
    "branch_2"
  ]
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "branches": [
    "branch_1",
    "branch_2"
  ]
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("图节点_fork",
    config={'branches': ['branch_1', 'branch_2']},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.图节点_fork.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 15. 图节点事务 / if

### 图节点_if

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 图节点_if |
| 领域 | graph |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 图节点_if |
| 目录 | autodokit/affairs/图节点_if |
| Runner.module | autodokit.affairs.图节点_if.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/图节点_if/affair.md |

#### 模块说明

图节点事务：if。

本事务用于执行布尔条件判断，并给出分支命中结果。
P1 阶段仅提供最小可运行判断能力。

#### 事务 Markdown 说明摘录

- 图节点_if

- 用途

- 该事务用于执行 `图节点_if` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| true | true | any |
| false | false | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| true | true | any |
| false | false | any |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| condition | 否 | false | false |
| default | 否 | false | false |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| condition | 否 | false | false |
| default | 否 | false | false |

#### node.config JSON 示例

```json
{
  "condition": false,
  "default": false
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "condition": false,
  "default": false
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("图节点_if",
    config={'condition': False, 'default': False},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.图节点_if.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 16. 图节点事务 / input

### 图节点_input

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 图节点_input |
| 领域 | graph |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 图节点_input |
| 目录 | autodokit/affairs/图节点_input |
| Runner.module | autodokit.affairs.图节点_input.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/图节点_input/affair.md |

#### 模块说明

图节点事务：input。

本事务用于表示通用数据导入入口节点。
P1 阶段仅回显输入元信息。

#### 事务 Markdown 说明摘录

- 图节点_input

- 用途

- 该事务用于执行 `图节点_input` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

- 无

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| data | data | any |

#### node.inputs

- 无

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| data | data | any |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| input_name | 否 | "input" | "input" |
| input_source | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| input_name | 否 | "input" | "input" |
| input_source | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "input_name": "input",
  "input_source": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "input_name": "input",
  "input_source": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("图节点_input",
    config={'input_name': 'input', 'input_source': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.图节点_input.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 17. 图节点事务 / merge

### 图节点_merge

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 图节点_merge |
| 领域 | graph |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 图节点_merge |
| 目录 | autodokit/affairs/图节点_merge |
| Runner.module | autodokit.affairs.图节点_merge.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/图节点_merge/affair.md |

#### 模块说明

图节点事务：merge。

本事务用于多分支汇聚。
P5 阶段由控制流引擎负责“等待所有已激活上游”语义，本事务只做可观测输出。

#### 事务 Markdown 说明摘录

- 图节点_merge

- 用途

- 该事务用于执行 `图节点_merge` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| max_wait_retries | 否 | null | null |
| merge_strategy | 否 | "wait_all_activated" | "wait_all_activated" |
| on_timeout | 否 | "fail" | "fail" |
| quorum | 否 | 1 | 1 |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| max_wait_retries | 否 | null | null |
| merge_strategy | 否 | "wait_all_activated" | "wait_all_activated" |
| on_timeout | 否 | "fail" | "fail" |
| quorum | 否 | 1 | 1 |

#### node.config JSON 示例

```json
{
  "merge_strategy": "wait_all_activated",
  "quorum": 1,
  "max_wait_retries": null,
  "on_timeout": "fail"
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "merge_strategy": "wait_all_activated",
  "quorum": 1,
  "max_wait_retries": null,
  "on_timeout": "fail"
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("图节点_merge",
    config={'merge_strategy': 'wait_all_activated',
     'quorum': 1,
     'max_wait_retries': None,
     'on_timeout': 'fail'},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.图节点_merge.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 18. 图节点事务 / output

### 图节点_output

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 图节点_output |
| 领域 | graph |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 图节点_output |
| 目录 | autodokit/affairs/图节点_output |
| Runner.module | autodokit.affairs.图节点_output.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/图节点_output/affair.md |

#### 模块说明

图节点事务：output。

本事务用于表示通用数据导出节点。
P1 阶段仅回显导出元信息。

#### 事务 Markdown 说明摘录

- 图节点_output

- 用途

- 该事务用于执行 `图节点_output` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| data | data | any |

#### interface.outputs

- 无

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| data | data | any |

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_name | 否 | "output" | "output" |
| output_target | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_name | 否 | "output" | "output" |
| output_target | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "output_name": "output",
  "output_target": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "output_name": "output",
  "output_target": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("图节点_output",
    config={'output_name': 'output', 'output_target': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.图节点_output.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 19. 图节点事务 / start

### 图节点_start

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 图节点_start |
| 领域 | graph |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 图节点_start |
| 目录 | autodokit/affairs/图节点_start |
| Runner.module | autodokit.affairs.图节点_start.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/图节点_start/affair.md |

#### 模块说明

图节点事务：start。

本事务用于表示流程的开始节点。
P1 阶段仅提供可调度与可观测占位实现。

#### 事务 Markdown 说明摘录

- 图节点_start

- 用途

- 该事务用于执行 `图节点_start` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

- 无

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| next | next | any |

#### node.inputs

- 无

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| next | next | any |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| node_role | 否 | "start" | "start" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| node_role | 否 | "start" | "start" |

#### node.config JSON 示例

```json
{
  "node_role": "start"
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "node_role": "start"
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("图节点_start",
    config={'node_role': 'start'},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.图节点_start.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 20. 图节点事务 / switch

### 图节点_switch

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 图节点_switch |
| 领域 | graph |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 图节点_switch |
| 目录 | autodokit/affairs/图节点_switch |
| Runner.module | autodokit.affairs.图节点_switch.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/图节点_switch/affair.md |

#### 模块说明

图节点事务：switch。

本事务用于根据路由标签进行多路分支选择。
P5 阶段提供最小可运行实现。

#### 事务 Markdown 说明摘录

- 图节点_switch

- 用途

- 该事务用于执行 `图节点_switch` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| case_a | case_a | any |
| case_b | case_b | any |
| default | default | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| case_a | case_a | any |
| case_b | case_b | any |
| default | default | any |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| allow_unsafe_eval | 否 | false | false |
| cases | 否 | {"case_a": ["A"], "case_b": ["B"]} | {"case_a": ["A"], "case_b": ["B"]} |
| default_label | 否 | "default" | "default" |
| expression_mode | 否 | "safe" | "safe" |
| route_expression | 否 | "" | "" |
| switch_value | 否 | "A" | "A" |
| variables | 否 | {} | {} |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| allow_unsafe_eval | 否 | false | false |
| cases | 否 | {"case_a": ["A"], "case_b": ["B"]} | {"case_a": ["A"], "case_b": ["B"]} |
| default_label | 否 | "default" | "default" |
| expression_mode | 否 | "safe" | "safe" |
| route_expression | 否 | "" | "" |
| switch_value | 否 | "A" | "A" |
| variables | 否 | {} | {} |

#### node.config JSON 示例

```json
{
  "switch_value": "A",
  "route_expression": "",
  "expression_mode": "safe",
  "allow_unsafe_eval": false,
  "variables": {},
  "cases": {
    "case_a": [
      "A"
    ],
    "case_b": [
      "B"
    ]
  },
  "default_label": "default"
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "switch_value": "A",
  "route_expression": "",
  "expression_mode": "safe",
  "allow_unsafe_eval": false,
  "variables": {},
  "cases": {
    "case_a": [
      "A"
    ],
    "case_b": [
      "B"
    ]
  },
  "default_label": "default"
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("图节点_switch",
    config={'switch_value': 'A',
     'route_expression': '',
     'expression_mode': 'safe',
     'allow_unsafe_eval': False,
     'variables': {},
     'cases': {'case_a': ['A'], 'case_b': ['B']},
     'default_label': 'default'},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.图节点_switch.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 21. 文献处理事务

### CNKI基础检索

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CNKI基础检索 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CNKI基础检索 |
| 目录 | autodokit/affairs/CNKI基础检索 |
| Runner.module | autodokit.affairs.CNKI基础检索.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CNKI基础检索/affair.md |

#### 模块说明

CNKI 基础检索事务。

#### 事务 Markdown 说明摘录

- CNKI基础检索

生成 CNKI 基础检索计划，并给出下一跳结果解析事务。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| page | 否 | 1 | 1 |
| query | 否 | "" | "" |
| sort_by | 否 | "relevance" | "relevance" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| page | 否 | 1 | 1 |
| query | 否 | "" | "" |
| sort_by | 否 | "relevance" | "relevance" |

#### node.config JSON 示例

```json
{
  "query": "",
  "page": 1,
  "sort_by": "relevance",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "query": "",
  "page": 1,
  "sort_by": "relevance",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CNKI基础检索",
    config={'query': '',
     'page': 1,
     'sort_by': 'relevance',
     'access_type': 'closed',
     'metadata': {},
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CNKI基础检索.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### CNKI期刊检索

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CNKI期刊检索 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CNKI期刊检索 |
| 目录 | autodokit/affairs/CNKI期刊检索 |
| Runner.module | autodokit.affairs.CNKI期刊检索.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CNKI期刊检索/affair.md |

#### 模块说明

CNKI 期刊检索事务。

#### 事务 Markdown 说明摘录

- CNKI期刊检索

生成目标期刊搜索计划，并衔接期刊指标提取。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| journal_query | 否 | "" | "" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| journal_query | 否 | "" | "" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "journal_query": "",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "journal_query": "",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CNKI期刊检索",
    config={'journal_query': '', 'access_type': 'closed', 'metadata': {}, 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CNKI期刊检索.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### CNKI高级检索

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CNKI高级检索 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CNKI高级检索 |
| 目录 | autodokit/affairs/CNKI高级检索 |
| Runner.module | autodokit.affairs.CNKI高级检索.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CNKI高级检索/affair.md |

#### 模块说明

CNKI 高级检索事务。

#### 事务 Markdown 说明摘录

- CNKI高级检索

生成带作者、期刊、年份和字段条件的高级检索计划。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| author | 否 | "" | "" |
| end_year | 否 | "" | "" |
| field_type | 否 | "SU" | "SU" |
| journal | 否 | "" | "" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| query | 否 | "" | "" |
| source_types | 否 | [] | [] |
| start_year | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "closed" | "closed" |
| author | 否 | "" | "" |
| end_year | 否 | "" | "" |
| field_type | 否 | "SU" | "SU" |
| journal | 否 | "" | "" |
| metadata | 否 | {} | {} |
| output_dir | 否 | "" | "" |
| query | 否 | "" | "" |
| source_types | 否 | [] | [] |
| start_year | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "query": "",
  "author": "",
  "journal": "",
  "start_year": "",
  "end_year": "",
  "source_types": [],
  "field_type": "SU",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "query": "",
  "author": "",
  "journal": "",
  "start_year": "",
  "end_year": "",
  "source_types": [],
  "field_type": "SU",
  "access_type": "closed",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CNKI高级检索",
    config={'query': '',
     'author': '',
     'journal': '',
     'start_year': '',
     'end_year': '',
     'source_types': [],
     'field_type': 'SU',
     'access_type': 'closed',
     'metadata': {},
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CNKI高级检索.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 候选文献视图构建

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 候选文献视图构建 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/候选文献视图构建 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/候选文献视图构建/affair.md |

#### 模块说明

候选文献视图构建事务。

#### 事务 Markdown 说明摘录

- 候选文献视图构建

- 用途

根据预筛选或检索结果生成 task 内部使用的候选视图与阅读批次。

事务执行后会把当前筛选态写回统一内容主库的 `literatures` 主表，
并重建 `review_candidate_current_view`、`review_read_pool_current_view`、`review_priority_current_view` 三个固定查询视图。
`review_candidate_pool_index`、`review_candidate_pool_readable`、`review_priority_view`、`review_read_pool`、`review_deep_read_queue_seed`、`review_already_read_exit_view`、`review_reading_batches` 仅保留为 steps/视图快照 CSV，不再作为内容主库实体表持久化。

说明：这些 current view 仅属于历史兼容描述；新项目应以 `content.db` 六表 + 阅读队列表 + steps/CSV 导出物为准，不再创建 SQLite 视图。

- 输出

1. candidate_pool_index.csv
2. candidate_pool_readable.csv
3. review_priority_view.csv
4. reading_batches.csv
5. gate_review.json

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| batch_size | 否 | 10 | 10 |
| candidates | 否 | [] | [] |
| input_csv | 否 | "" | "" |
| literature_csv | 否 | "" | "" |
| min_score | 否 | 0.0 | 0.0 |
| output_dir | 否 | "" | "" |
| source_affair | 否 | "review_candidate_views" | "review_candidate_views" |
| source_round | 否 | "round_01" | "round_01" |
| top_k | 否 | 200 | 200 |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "input_csv": "",
  "literature_csv": "",
  "candidates": [],
  "output_dir": "",
  "source_round": "round_01",
  "source_affair": "review_candidate_views",
  "min_score": 0.0,
  "top_k": 200,
  "batch_size": 10
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("候选文献视图构建",
    config={'input_csv': '',
     'literature_csv': '',
     'candidates': [],
     'output_dir': '',
     'source_round': 'round_01',
    'source_affair': 'review_candidate_views',
     'min_score': 0.0,
     'top_k': 200,
     'batch_size': 10},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from  import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 合并去重文献元数据

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 合并去重文献元数据 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 合并去重文献元数据 |
| 目录 | autodokit/affairs/合并去重文献元数据 |
| Runner.module | autodokit.affairs.合并去重文献元数据.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/合并去重文献元数据/affair.md |

#### 模块说明

合并去重文献元数据脚本。

该脚本以“文献元数据主表 CSV”为输入（通常由 `导入和预处理文献元数据` 事务生成），
将其读入为 pandas DataFrame，并按指定的去重策略生成“去重后的 CSV”。

当前版本仅做去重输出，不做跨行字段级合并（字段合并在后续版本再实现）。

主要功能：
- 提供 programmatic API `dedup_metadata_csv` 以便被调度器或其他脚本调用。
- 提供 CLI 接口用于命令行运行。

去重策略（默认）：
- 优先按 DOI 去重（归一化 DOI）。
- 对缺失 DOI 的记录，再用 title + authors + year 的归一化键去重。

注意：
- 本脚本不修改 `合并去重bibtex.py`，其事务仍可按原方式处理 .bib 文件。

#### 事务 Markdown 说明摘录

- 合并去重文献元数据

- 用途

- 该事务用于执行 `合并去重文献元数据` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("合并去重文献元数据",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.合并去重文献元数据.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 向量化与索引构建

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 向量化与索引构建 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 向量化与索引构建 |
| 目录 | autodokit/affairs/向量化与索引构建 |
| Runner.module | autodokit.affairs.向量化与索引构建.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/向量化与索引构建/affair.md |

#### 模块说明

向量化与索引构建事务（第一版：TF-IDF）。

本事务将 `chunks.jsonl` 向量化并生成可用于检索的基础索引。

第一版选择 TF-IDF 的原因：
- 不依赖外部模型与 API，便于在调试阶段快速闭环。
- 足以支撑“关键词/语义近似检索”的基础能力，为后续接入 embedding 打地基。

输出：
- `tfidf.npz`：稀疏矩阵（行=chunk，列=term）
- `vocab.json`：词表与 ID 映射
- `chunk_meta.jsonl`：chunk_id -> uid/doc_id/meta 的映射
- `vector_manifest.json`：统计与参数回显

Args:
    config_path: 调度器传入配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。

Examples:
    >>> from autodokit.affairs.向量化与索引构建 import execute
    >>> execute(Path('workflows/workflow_010/workflow.json'))

#### 事务 Markdown 说明摘录

- 向量化与索引构建

- 用途

- 该事务用于执行 `向量化与索引构建` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| chunks | chunks | jsonl |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| index | index | dir |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| chunks | chunks | jsonl |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| index | index | dir |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| content_db | 否 | "" | "" |
| chunks_uid | 否 | "" | "" |
| input_chunk_manifest_json | 否 | "workflows/workflow_解析与分块/output/03_chunk/chunk_manifest.json" | "workflows/workflow_解析与分块/output/03_chunk/chunk_manifest.json" |
| max_features | 否 | 20000 | 20000 |
| ngram_range | 否 | [1, 2] | [1, 2] |
| output_dir | 否 | "workflows/workflow_向量化与索引构建/output/04_vector_index" | "workflows/workflow_向量化与索引构建/output/04_vector_index" |
| vectorizer_type | 否 | "tfidf" | "tfidf" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| content_db | 否 | "" | "" |
| chunks_uid | 否 | "" | "" |
| input_chunk_manifest_json | 否 | "workflows/workflow_解析与分块/output/03_chunk/chunk_manifest.json" | "workflows/workflow_解析与分块/output/03_chunk/chunk_manifest.json" |
| max_features | 否 | 20000 | 20000 |
| ngram_range | 否 | [1, 2] | [1, 2] |
| output_dir | 否 | "workflows/workflow_向量化与索引构建/output/04_vector_index" | "workflows/workflow_向量化与索引构建/output/04_vector_index" |
| vectorizer_type | 否 | "tfidf" | "tfidf" |

#### node.config JSON 示例

```json
{
  "input_chunk_manifest_json": "workflows/workflow_解析与分块/output/03_chunk/chunk_manifest.json",
  "output_dir": "workflows/workflow_向量化与索引构建/output/04_vector_index",
  "vectorizer_type": "tfidf",
  "max_features": 20000,
  "ngram_range": [
    1,
    2
  ]
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "input_chunk_manifest_json": "workflows/workflow_解析与分块/output/03_chunk/chunk_manifest.json",
  "output_dir": "workflows/workflow_向量化与索引构建/output/04_vector_index",
  "vectorizer_type": "tfidf",
  "max_features": 20000,
  "ngram_range": [
    1,
    2
  ]
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("向量化与索引构建",
  config={'input_chunk_manifest_json': 'workflows/workflow_解析与分块/output/03_chunk/chunk_manifest.json',
     'output_dir': 'workflows/workflow_向量化与索引构建/output/04_vector_index',
     'vectorizer_type': 'tfidf',
     'max_features': 20000,
     'ngram_range': [1, 2]},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.向量化与索引构建.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 导入和预处理文献元数据

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 导入和预处理文献元数据 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 导入和预处理文献元数据 |
| 目录 | autodokit/affairs/导入和预处理文献元数据 |
| Runner.module | autodokit.affairs.导入和预处理文献元数据.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/导入和预处理文献元数据/affair.md |

#### 模块说明

导入和预处理文献元数据

本脚本将 BibTeX 文献导入为 Pandas 数据表，并生成管理字段。

说明：
- 本事务只负责“导入 + 预处理 + 主表落盘”。
- bibtex_path 支持：
  - 单个 BibTeX 文件（.bib/.txt 等，只要内容是 BibTeX 即可）；
  - 一个目录：会遍历该目录下所有 .bib 文件并合并导入（不递归、不去重）。

#### 事务 Markdown 说明摘录

- 导入和预处理文献元数据

- 用途

- 该事务用于执行 `导入和预处理文献元数据` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

- 无

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| table | table | csv |

#### node.inputs

- 无

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| table | table | csv |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| bibtex_path | 否 | "workspace/references/bib/library.bib" | "workspace/references/bib/library.bib" |
| has_pdf_enable | 否 | true | true |
| output_dir | 否 | "workspace/steps/A02_import_and_preprocess" | "workspace/steps/A02_import_and_preprocess" |
| output_table_csv | 否 | "文献数据表.csv" | "文献数据表.csv" |
| outputs | 否 | {"literature_relations_csv": "literature_relations.csv", "tags_to_literatures_csv": "tags_to_literatures.csv", "attachments_to_literatures_csv": "attachments_to_literatures.csv", "tags_inverted_index_pkl": "tags_inverted_index.pkl", "tags_csc_npz": "tags_csc.npz", "tags_entity_index_csv": "tags_entity_index.csv", "attachments_inverted_index_pkl": "attachments_inverted_index.pkl", "attachments_csc_npz": "attachments_csc.npz", "attachments_entity_index_csv": "attachments_entity_index.csv"} | {"literature_relations_csv": "literature_relations.csv", "tags_to_literatures_csv": "tags_to_literatures.csv", "attachments_to_literatures_csv": "attachments_to_literatures.csv", "tags_inverted_index_pkl": "tags_inverted_index.pkl", "tags_csc_npz": "tags_csc.npz", "tags_entity_index_csv": "tags_entity_index.csv", "attachments_inverted_index_pkl": "attachments_inverted_index.pkl", "attachments_csc_npz": "attachments_csc.npz", "attachments_entity_index_csv": "attachments_entity_index.csv"} |
| pdf_dir | 否 | "workspace/references/attachments" | "workspace/references/attachments" |
| pdf_match_mode | 否 | "title" | "title" |
| sqlite_db_path | 否 | "workspace/database/content/content.db" | "workspace/database/content/content.db" |
| storage_backend | 否 | "sqlite" | "sqlite" |
| tag_list | 否 | ["主题A", "主题B"] | ["主题A", "主题B"] |
| tag_match_fields | 否 | ["title", "abstract", "keywords"] | ["title", "abstract", "keywords"] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| bibtex_path | 否 | "data/题录元数据" | "data/题录元数据" |
| has_pdf_enable | 否 | true | true |
| output_dir | 否 | "workflows/workflow_导入和预处理文献元数据/data/题录导出文件" | "workflows/workflow_导入和预处理文献元数据/data/题录导出文件" |
| pdf_dir | 否 | "data/文献原文数据" | "data/文献原文数据" |
| pdf_match_mode | 否 | "title" | "title" |
| tag_list | 否 | ["topic", "signal", "relation", "governance"] | ["topic", "signal", "relation", "governance"] |
| tag_match_fields | 否 | ["title", "abstract", "keywords"] | ["title", "abstract", "keywords"] |

#### node.config JSON 示例

```json
{
  "bibtex_path": "data/题录元数据",
  "output_dir": "workflows/workflow_导入和预处理文献元数据/data/题录导出文件",
  "pdf_dir": "data/文献原文数据",
  "tag_list": [
    "graph",
    "risk",
    "bank",
    "systemic"
  ],
  "tag_match_fields": [
    "title",
    "abstract",
    "keywords"
  ],
  "has_pdf_enable": true,
  "pdf_match_mode": "title"
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "bibtex_path": "workspace/references/bib/library.bib",
  "pdf_dir": "workspace/references/attachments",
  "output_dir": "workspace/steps/A02_import_and_preprocess",
  "output_table_csv": "文献数据表.csv",
  "storage_backend": "sqlite",
  "sqlite_db_path": "workspace/database/content/content.db",
  "has_pdf_enable": true,
  "pdf_match_mode": "title",
  "tag_list": [
    "主题A",
    "主题B"
  ],
  "tag_match_fields": [
    "title",
    "abstract",
    "keywords"
  ],
  "outputs": {
    "literature_relations_csv": "literature_relations.csv",
    "tags_to_literatures_csv": "tags_to_literatures.csv",
    "attachments_to_literatures_csv": "attachments_to_literatures.csv",
    "tags_inverted_index_pkl": "tags_inverted_index.pkl",
    "tags_csc_npz": "tags_csc.npz",
    "tags_entity_index_csv": "tags_entity_index.csv",
    "attachments_inverted_index_pkl": "attachments_inverted_index.pkl",
    "attachments_csc_npz": "attachments_csc.npz",
    "attachments_entity_index_csv": "attachments_entity_index.csv"
  }
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("导入和预处理文献元数据",
    config={'bibtex_path': 'workspace/references/bib/library.bib',
     'pdf_dir': 'workspace/references/attachments',
    'output_dir': 'workspace/steps/A02_import_and_preprocess',
     'output_table_csv': '文献数据表.csv',
     'storage_backend': 'sqlite',
    'sqlite_db_path': 'workspace/database/content/content.db',
     'has_pdf_enable': True,
     'pdf_match_mode': 'title',
    'tag_list': ['主题A', '主题B'],
     'tag_match_fields': ['title', 'abstract', 'keywords'],
     'outputs': {'literature_relations_csv': 'literature_relations.csv',
                 'tags_to_literatures_csv': 'tags_to_literatures.csv',
                 'attachments_to_literatures_csv': 'attachments_to_literatures.csv',
                 'tags_inverted_index_pkl': 'tags_inverted_index.pkl',
                 'tags_csc_npz': 'tags_csc.npz',
                 'tags_entity_index_csv': 'tags_entity_index.csv',
                 'attachments_inverted_index_pkl': 'attachments_inverted_index.pkl',
                 'attachments_csc_npz': 'attachments_csc.npz',
                 'attachments_entity_index_csv': 'attachments_entity_index.csv'}},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.导入和预处理文献元数据.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 文献矩阵

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 文献矩阵 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 文献矩阵 |
| 目录 | autodokit/affairs/文献矩阵 |
| Runner.module | autodokit.affairs.文献矩阵.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/文献矩阵/affair.md |

#### 模块说明

批量文献矩阵（P1，占位可运行版）。

本脚本用于生成“文献矩阵”表格：对每篇文献抽取同一组字段（研究问题/方法/数据/结论/贡献/局限）。

本版实现保持简单：
- 从 `input_structured_dir` 或 `content_db` 读取前 N 篇（或指定 uid 列表）
- 对每篇文献单独调用一次大模型，得到结构化 YAML/JSON 风格文本
- 汇总写出一个 `matrix.jsonl`（一行一篇）和一个简易 `matrix.csv`

这样做的好处：
- 实现简单，便于逐步迭代。
- 不依赖复杂的 Map-Reduce 框架或向量检索。

Args:
    config_path: 调度器传入的配置文件路径。

Returns:
    写出的文件 Path 列表。

#### 事务 Markdown 说明摘录

- 文献矩阵

- 用途

- 该事务用于执行 `文献矩阵` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

- 无

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| result | result | jsonl |

#### node.inputs

- 无

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| result | result | jsonl |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| content_db | 否 | "" | "" |
| input_structured_dir | 否 | "" | "" |
| limit | 否 | 20 | 20 |
| max_chars | 否 | 8000 | 8000 |
| model | 否 | "qwen-plus" | "qwen-plus" |
| output_dir | 否 | "output/matrix" | "output/matrix" |
| uids | 否 | null | null |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| content_db | 否 | "" | "" |
| input_structured_dir | 否 | "" | "" |
| limit | 否 | 20 | 20 |
| max_chars | 否 | 8000 | 8000 |
| model | 否 | "qwen-plus" | "qwen-plus" |
| output_dir | 否 | "output/matrix" | "output/matrix" |
| uids | 否 | null | null |

#### node.config JSON 示例

```json
{
  "input_structured_dir": "",
  "content_db": "",
  "output_dir": "output/matrix",
  "limit": 20,
  "uids": null,
  "model": "qwen-plus",
  "max_chars": 8000
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "input_structured_dir": "",
  "content_db": "",
  "output_dir": "output/matrix",
  "limit": 20,
  "uids": null,
  "model": "qwen-plus",
  "max_chars": 8000
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("文献矩阵",
  config={'input_structured_dir': '',
   'content_db': '',
     'output_dir': 'output/matrix',
     'limit': 20,
     'uids': None,
     'model': 'qwen-plus',
     'max_chars': 8000},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.文献矩阵.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 文献阅读规划

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 文献阅读规划 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 文献阅读规划 |
| 目录 | autodokit/affairs/文献阅读规划 |
| Runner.module | autodokit.affairs.文献阅读规划.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/文献阅读规划/affair.md |

#### 模块说明

文献阅读规划事务。

根据预筛选候选生成阅读队列、矩阵字段和精读提示模板，
并保持与 ARK 兼容的 `LiteratureReadingEngine` / `LiteratureReadingPlan`。

#### 事务 Markdown 说明摘录

- 文献阅读规划

按候选得分生成阅读队列、矩阵字段与精读模板。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| candidates | 否 | [] | [] |
| focus | 否 | "" | "" |
| max_items | 否 | 12 | 12 |
| output_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| candidates | 否 | [] | [] |
| focus | 否 | "" | "" |
| max_items | 否 | 12 | 12 |
| output_dir | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "focus": "",
  "candidates": [],
  "max_items": 12,
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "focus": "",
  "candidates": [],
  "max_items": 12,
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("文献阅读规划",
    config={'focus': '', 'candidates': [], 'max_items': 12, 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.文献阅读规划.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 本地文献导入

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 本地文献导入 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 本地文献导入 |
| 目录 | autodokit/affairs/本地文献导入 |
| Runner.module | autodokit.affairs.本地文献导入.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/本地文献导入/affair.md |

#### 模块说明

本地文献导入事务。

该事务负责扫描本地 `bib` / `rdf` 元数据与附件引用关系，
并在需要时把结果持久化到项目文献数据库模板目录。

#### 事务 Markdown 说明摘录

- 本地文献导入

扫描本地 `bib` / `rdf` 文件并生成结构化文献条目与附件关系。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| persist | 否 | false | false |
| project_root | 否 | "" | "" |
| source_paths | 否 | [] | [] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| output_dir | 否 | "" | "" |
| persist | 否 | false | false |
| project_root | 否 | "" | "" |
| source_paths | 否 | [] | [] |

#### node.config JSON 示例

```json
{
  "project_root": "",
  "source_paths": [],
  "persist": false,
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "project_root": "",
  "source_paths": [],
  "persist": false,
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("本地文献导入",
    config={'project_root': '', 'source_paths': [], 'persist': False, 'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.本地文献导入.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 检索治理

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 检索治理 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 检索治理 |
| 目录 | autodokit/affairs/检索治理 |
| Runner.module | autodokit.affairs.检索治理.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/检索治理/affair.md |

#### 模块说明

检索治理事务。

#### 事务 Markdown 说明摘录

- 检索治理

统一处理检索请求的授权判定、结果码和后续路由。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "open" | "open" |
| metadata | 否 | {} | {} |
| object_type | 否 | "literature" | "literature" |
| output_dir | 否 | "" | "" |
| query | 否 | "" | "" |
| region_type | 否 | "global" | "global" |
| request_uid | 否 | "" | "" |
| source_type | 否 | "online" | "online" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_type | 否 | "open" | "open" |
| metadata | 否 | {} | {} |
| object_type | 否 | "literature" | "literature" |
| output_dir | 否 | "" | "" |
| query | 否 | "" | "" |
| region_type | 否 | "global" | "global" |
| request_uid | 否 | "" | "" |
| source_type | 否 | "online" | "online" |

#### node.config JSON 示例

```json
{
  "request_uid": "",
  "query": "",
  "object_type": "literature",
  "source_type": "online",
  "region_type": "global",
  "access_type": "open",
  "metadata": {},
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "request_uid": "",
  "query": "",
  "object_type": "literature",
  "source_type": "online",
  "region_type": "global",
  "access_type": "open",
  "metadata": {},
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("检索治理",
    config={'request_uid': '',
     'query': '',
     'object_type': 'literature',
     'source_type': 'online',
     'region_type': 'global',
     'access_type': 'open',
     'metadata': {},
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.检索治理.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 生成关键词集合

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 生成关键词集合 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 生成关键词集合 |
| 目录 | autodokit/affairs/生成关键词集合 |
| Runner.module | autodokit.affairs.生成关键词集合.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/生成关键词集合/affair.md |

#### 模块说明

生成关键词集合事务。

本事务的目标：
- 输入自然语言描述与初始关键词集合，调用大语言模型生成扩展关键词集合（中英文与短语）。
- 支持将关键词按研究领域进行初步分类，生成每个研究领域的关键词集合，并计算领域集合的笛卡尔积组合。
- 将生成结果写入指定输出目录，供后续预筛选或检索使用。

输入（必需）：
- description: 自然语言描述（研究主题/问题/范围）。
- initial_keywords: 初始关键词列表（中文或中英混合）。

输出（必需产物）：
- keyword_set.json: 结构化结果（包含领域划分、各领域关键词集合、笛卡尔积组合等）。
- keyword_set.txt: 扁平关键词列表（每行一个，来自 all_keywords）。
- keyword_pairs.txt: 领域组合串列表（每行一个，例如 "主题维度A | 主题维度B" 的关键词组合）。
- keyword_debug.json: 调试信息（LLM 两阶段解析与参考资料统计）。
- keyword_domains.json: 中间结构（按领域聚合关键词与跨领域短语）。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。

Examples:
    >>> from pathlib import Path
    >>> # 注意：Windows/某些 IDE 对中文模块名的静态解析可能不完善，但运行时可正常 import
    >>> from autodokit.affairs import 生成关键词集合 as keyword_set_affair
    >>> keyword_set_affair.execute(Path("workflows/workflow_生成关键词集合/workflow.json"))

#### 事务 Markdown 说明摘录

- 生成关键词集合

- 用途

- 该事务用于执行 `生成关键词集合` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

- 无

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| keywords | keywords | dir |

#### node.inputs

- 无

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| keywords | keywords | dir |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| description | 否 | "研究主题：围绕主题A与主题B的交叉问题，关注关键变量、作用路径与响应策略。" | "研究主题：围绕主题A与主题B的交叉问题，关注关键变量、作用路径与响应策略。" |
| dry_run | 否 | false | false |
| include_chinese | 否 | true | true |
| include_english | 否 | true | true |
| include_phrases | 否 | true | true |
| max_domain_keywords | 否 | 40 | 40 |
| max_keywords | 否 | 80 | 80 |
| max_pairs | 否 | 2000 | 2000 |
| model | 否 | "qwen-plus" | "qwen-plus" |
| output_debug_name | 否 | "keyword_debug.json" | "keyword_debug.json" |
| output_dir | 否 | "workflows/workflow_生成关键词集合/data/01_keyword_set" | "workflows/workflow_生成关键词集合/data/01_keyword_set" |
| output_domains_name | 否 | "keyword_domains.json" | "keyword_domains.json" |
| output_json_name | 否 | "keyword_set.json" | "keyword_set.json" |
| output_pairs_name | 否 | "keyword_pairs.txt" | "keyword_pairs.txt" |
| output_txt_name | 否 | "keyword_set.txt" | "keyword_set.txt" |
| reference_materials_dir | 否 | "workflows/workflow_生成关键词集合/data/00_reference_materials" | "workflows/workflow_生成关键词集合/data/00_reference_materials" |
| reference_materials_max_chars | 否 | 20000 | 20000 |
| reference_materials_max_files | 否 | 20 | 20 |
| research_domains | 否 | {"主题维度A": ["主题A", "核心对象", "关键变量", "关联关系"], "主题维度B": ["主题B", "作用路径", "响应机制", "应用场景"], "方法维度": ["基线方案", "对照方案"]} | {"主题维度A": ["主题A", "核心对象", "关键变量", "关联关系"], "主题维度B": ["主题B", "作用路径", "响应机制", "应用场景"], "方法维度": ["基线方案", "对照方案"]} |
| temperature | 否 | 0.2 | 0.2 |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| description | 否 | "研究主题：围绕主题A与主题B的交叉问题，关注关键变量、作用路径与响应策略。" | "研究主题：围绕主题A与主题B的交叉问题，关注关键变量、作用路径与响应策略。" |
| dry_run | 否 | false | false |
| include_chinese | 否 | true | true |
| include_english | 否 | true | true |
| include_phrases | 否 | true | true |
| max_domain_keywords | 否 | 40 | 40 |
| max_keywords | 否 | 80 | 80 |
| max_pairs | 否 | 2000 | 2000 |
| model | 否 | "qwen-plus" | "qwen-plus" |
| output_debug_name | 否 | "keyword_debug.json" | "keyword_debug.json" |
| output_dir | 否 | "workflows/workflow_生成关键词集合/data/01_keyword_set" | "workflows/workflow_生成关键词集合/data/01_keyword_set" |
| output_domains_name | 否 | "keyword_domains.json" | "keyword_domains.json" |
| output_json_name | 否 | "keyword_set.json" | "keyword_set.json" |
| output_pairs_name | 否 | "keyword_pairs.txt" | "keyword_pairs.txt" |
| output_txt_name | 否 | "keyword_set.txt" | "keyword_set.txt" |
| reference_materials_dir | 否 | "workflows/workflow_生成关键词集合/data/00_reference_materials" | "workflows/workflow_生成关键词集合/data/00_reference_materials" |
| reference_materials_max_chars | 否 | 20000 | 20000 |
| reference_materials_max_files | 否 | 20 | 20 |
| research_domains | 否 | {"主题维度A": ["主题A", "核心对象", "关键变量", "关联关系"], "主题维度B": ["主题B", "作用路径", "响应机制", "应用场景"], "方法维度": ["基线方案", "对照方案"]} | {"主题维度A": ["主题A", "核心对象", "关键变量", "关联关系"], "主题维度B": ["主题B", "作用路径", "响应机制", "应用场景"], "方法维度": ["基线方案", "对照方案"]} |
| temperature | 否 | 0.2 | 0.2 |

#### node.config JSON 示例

```json
{
  "description": "研究主题：围绕主题A与主题B的交叉问题，关注关键变量、作用路径与响应策略。",
  "research_domains": {
    "主题维度A": [
      "主题A",
      "核心对象",
      "关键变量",
      "关联关系"
    ],
    "主题维度B": [
      "主题B",
      "作用路径",
      "响应机制",
      "应用场景"
    ],
    "方法维度": [
      "基线方案",
      "对照方案"
    ]
  },
  "reference_materials_dir": "workflows/workflow_生成关键词集合/data/00_reference_materials",
  "reference_materials_max_files": 20,
  "reference_materials_max_chars": 20000,
  "output_dir": "workflows/workflow_生成关键词集合/data/01_keyword_set",
  "output_json_name": "keyword_set.json",
  "output_txt_name": "keyword_set.txt",
  "output_pairs_name": "keyword_pairs.txt",
  "output_debug_name": "keyword_debug.json",
  "output_domains_name": "keyword_domains.json",
  "model": "qwen-plus",
  "temperature": 0.2,
  "max_keywords": 80,
  "include_chinese": true,
  "include_english": true,
  "include_phrases": true,
  "max_domain_keywords": 40,
  "max_pairs": 2000,
  "dry_run": false
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "description": "研究主题：围绕主题A与主题B的交叉问题，关注关键变量、作用路径与响应策略。",
  "research_domains": {
    "主题维度A": [
      "主题A",
      "核心对象",
      "关键变量",
      "关联关系"
    ],
    "主题维度B": [
      "主题B",
      "作用路径",
      "响应机制",
      "应用场景"
    ],
    "方法维度": [
      "基线方案",
      "对照方案"
    ]
  },
  "reference_materials_dir": "workflows/workflow_生成关键词集合/data/00_reference_materials",
  "reference_materials_max_files": 20,
  "reference_materials_max_chars": 20000,
  "output_dir": "workflows/workflow_生成关键词集合/data/01_keyword_set",
  "output_json_name": "keyword_set.json",
  "output_txt_name": "keyword_set.txt",
  "output_pairs_name": "keyword_pairs.txt",
  "output_debug_name": "keyword_debug.json",
  "output_domains_name": "keyword_domains.json",
  "model": "qwen-plus",
  "temperature": 0.2,
  "max_keywords": 80,
  "include_chinese": true,
  "include_english": true,
  "include_phrases": true,
  "max_domain_keywords": 40,
  "max_pairs": 2000,
  "dry_run": false
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("生成关键词集合",
    config={'description': '研究主题：围绕主题A与主题B的交叉问题，关注关键变量、作用路径与响应策略。',
     'research_domains': {'主题维度A': ['主题A', '核心对象', '关键变量', '关联关系'],
                '主题维度B': ['主题B', '作用路径', '响应机制', '应用场景'],
                '方法维度': ['基线方案', '对照方案']},
     'reference_materials_dir': 'workflows/workflow_生成关键词集合/data/00_reference_materials',
     'reference_materials_max_files': 20,
     'reference_materials_max_chars': 20000,
     'output_dir': 'workflows/workflow_生成关键词集合/data/01_keyword_set',
     'output_json_name': 'keyword_set.json',
     'output_txt_name': 'keyword_set.txt',
     'output_pairs_name': 'keyword_pairs.txt',
     'output_debug_name': 'keyword_debug.json',
     'output_domains_name': 'keyword_domains.json',
     'model': 'qwen-plus',
     'temperature': 0.2,
     'max_keywords': 80,
     'include_chinese': True,
     'include_english': True,
     'include_phrases': True,
     'max_domain_keywords': 40,
     'max_pairs': 2000,
     'dry_run': False},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.生成关键词集合.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 生成文献元数据关系图

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 生成文献元数据关系图 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 生成文献元数据关系图 |
| 目录 | autodokit/affairs/生成文献元数据关系图 |
| Runner.module | autodokit.affairs.生成文献元数据关系图.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/生成文献元数据关系图/affair.md |

#### 模块说明

生成文献元数据关系图（二分图）事务。

本事务用于从“文献元数据主表”构建并落盘三类实体
（作者、关键词、标签）与文献之间的二分图数据。

设计原因：
- 二分图/反向索引属于“派生数据”，强依赖去重与字段清洗策略；
- 将其与“导入与预处理”解耦，可让用户在合并去重之后再生成图数据，避免重复计算与错误传播。

输出格式说明见：`docs/二分图输出格式说明.md`。

#### 事务 Markdown 说明摘录

- 生成文献元数据关系图

- 用途

- 该事务用于执行 `生成文献元数据关系图` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("生成文献元数据关系图",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.生成文献元数据关系图.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 知识预筛选

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 知识预筛选 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 知识预筛选 |
| 目录 | autodokit/affairs/知识预筛选 |
| Runner.module | autodokit.affairs.知识预筛选.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/知识预筛选/affair.md |

#### 模块说明

知识预筛选事务。

提供轻量可执行的主题词匹配预筛选能力，并保持与 ARK 兼容的
`KnowledgePrescreenEngine` / `KnowledgePrescreenResult` 结构。

#### 事务 Markdown 说明摘录

- 知识预筛选

根据主题词与排除词对候选文献进行快速筛选，并输出候选与排除结果。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| exclude_terms | 否 | [] | [] |
| focus | 否 | "" | "" |
| include_terms | 否 | [] | [] |
| items | 否 | [] | [] |
| literature_items_path | 否 | "" | "" |
| min_score | 否 | 1.0 | 1.0 |
| output_dir | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| exclude_terms | 否 | [] | [] |
| focus | 否 | "" | "" |
| include_terms | 否 | [] | [] |
| items | 否 | [] | [] |
| literature_items_path | 否 | "" | "" |
| min_score | 否 | 1.0 | 1.0 |
| output_dir | 否 | "" | "" |

#### node.config JSON 示例

```json
{
  "focus": "",
  "items": [],
  "literature_items_path": "",
  "include_terms": [],
  "exclude_terms": [],
  "min_score": 1.0,
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "focus": "",
  "items": [],
  "literature_items_path": "",
  "include_terms": [],
  "exclude_terms": [],
  "min_score": 1.0,
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("知识预筛选",
    config={'focus': '',
     'items': [],
     'literature_items_path': '',
     'include_terms': [],
     'exclude_terms': [],
     'min_score': 1.0,
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.知识预筛选.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 综述研读与研究地图生成

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 综述研读与研究地图生成 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 |  |
| 目录 | autodokit/affairs/综述研读与研究地图生成 |
| Runner.module |  |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/综述研读与研究地图生成/affair.md |

#### 模块说明

综述研读与研究地图生成事务。

本事务复用上游事务已创建的阅读池、标准笔记和结构化附件，
对综述型输入做句子级回填与审计汇总，并输出 G06 门禁结果。

#### 事务 Markdown 说明摘录

- 综述研读与研究地图生成

- 用途

服务综述研读链路，基于既有阅读池回填标准笔记、更新结构化附件，并生成闸门审计结果。

读取顺序说明：

1. 若显式提供 `review_read_pool_csv`，优先读取该绝对路径文件。
2. 若未提供，则优先读取统一内容主库中的 `review_read_pool_current_view`。
3. 若当前视图缺失，再回退到 `workspace/views/review_candidates/review_read_pool.csv`。
4. 仅为兼容旧数据时，最后才回退到旧表 `review_read_pool`。

说明：新项目不再生成 `review_read_pool_current_view` 这类 SQLite 视图；`review_read_pool.csv` 应理解为导出物或阶段快照，主状态以 `literature_reading_state` 为准。

- 输出

1. 更新上游事务已预创建的标准笔记与结构化附件
2. gate_review.json

#### interface.inputs

- 无

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| gate_review | gate_review | json |

#### node.inputs

- 无

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| gate_review | gate_review | json |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| content_db | 否 | "" | "" |
| output_dir | 否 | "" | "" |
| review_read_pool_csv | 否 | "" | "" |
| topic | 否 | "" | "" |
| workspace_root | 否 | "" | "" |

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{
  "workspace_root": "",
  "content_db": "",
  "review_read_pool_csv": "",
  "topic": "",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "workspace_root": "",
  "content_db": "",
  "review_read_pool_csv": "",
  "topic": "",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("综述研读与研究地图生成",
  config={'workspace_root': str(workspace_root),
   'content_db': str(workspace_root / 'database' / 'content' / 'content.db'),
   'review_read_pool_csv': '',
   'topic': '',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.综述研读与研究地图生成.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 综述草稿生成

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 综述草稿生成 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 综述草稿生成 |
| 目录 | autodokit/affairs/综述草稿生成 |
| Runner.module | autodokit.affairs.综述草稿生成.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/综述草稿生成/affair.md |

#### 模块说明

综述草稿生成（P1，占位可运行版）。

本脚本用于基于若干篇候选文献生成一个“综述草稿”。

本版实现保持简单：
- 从 `matrix.jsonl`（推荐）或 structured/content_db（兜底）读取材料
- 让模型按给定的提纲输出 markdown 草稿
- 输出到 output_dir 下的 `review_draft.md`

为什么优先基于 matrix：
- 先把每篇文献抽取成统一字段，综述阶段 prompt 更短、更稳定。

Args:
    config_path: 调度器传入的配置文件路径。

Returns:
    写出的文件 Path 列表。

#### 事务 Markdown 说明摘录

- 综述草稿生成

- 用途

- 该事务用于执行 `综述草稿生成` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | jsonl |

#### interface.outputs

- 无

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | jsonl |

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| content_db | 否 | null | null |
| input_matrix_jsonl | 否 | "output/matrix/matrix.jsonl" | "output/matrix/matrix.jsonl" |
| input_structured_dir | 否 | null | null |
| max_items | 否 | 30 | 30 |
| model | 否 | "qwen-plus" | "qwen-plus" |
| outline | 否 | null | null |
| output_dir | 否 | "output/review" | "output/review" |
| title | 否 | "综述草稿" | "综述草稿" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| content_db | 否 | null | null |
| input_matrix_jsonl | 否 | "output/matrix/matrix.jsonl" | "output/matrix/matrix.jsonl" |
| input_structured_dir | 否 | null | null |
| max_items | 否 | 30 | 30 |
| model | 否 | "qwen-plus" | "qwen-plus" |
| outline | 否 | null | null |
| output_dir | 否 | "output/review" | "output/review" |
| title | 否 | "综述草稿" | "综述草稿" |

#### node.config JSON 示例

```json
{
  "input_matrix_jsonl": "output/matrix/matrix.jsonl",
  "input_structured_dir": null,
  "content_db": null,
  "output_dir": "output/review",
  "title": "综述草稿",
  "outline": null,
  "model": "qwen-plus",
  "max_items": 30
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "input_matrix_jsonl": "output/matrix/matrix.jsonl",
  "input_structured_dir": null,
  "content_db": null,
  "output_dir": "output/review",
  "title": "综述草稿",
  "outline": null,
  "model": "qwen-plus",
  "max_items": 30
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("综述草稿生成",
    config={'input_matrix_jsonl': 'output/matrix/matrix.jsonl',
  'input_structured_dir': None,
  'content_db': None,
     'output_dir': 'output/review',
     'title': '综述草稿',
     'outline': None,
     'model': 'qwen-plus',
     'max_items': 30},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.综述草稿生成.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 自动化导入知网研学专题

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 自动化导入知网研学专题 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 自动化导入知网研学专题 |
| 目录 | autodokit/affairs/自动化导入知网研学专题 |
| Runner.module | autodokit.affairs.自动化导入知网研学专题.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/自动化导入知网研学专题/affair.md |

#### 模块说明

CNKI 搜索结果页面自动化收藏脚本（基于 Playwright，针对 Edge）。

# #DEBUG 暂时还未调试，不可以直接投入运行。
# #HACK 警告： 危险！该程序会自动在你的 CNKI 账号里批量执行收藏操作！请务必先仔细阅读以下说明，理解脚本行为，并做好充分准备（例如先在测试账号或小范围内验证）。错误的使用可能导致大量不必要的收藏或者丢失有用数据、甚至账号问题。

目的
- 在 CNKI 搜索结果页上循环执行：全选 -> 收藏到专题 -> 翻页（按 ArrowRight），直到最后一页或遇到人工中断（例如验证码）。

重要说明（你需要手动执行的部分，以及脚本与人的交互）

1) 初始准备（在你运行脚本前请执行）
   - 在本地确保已安装 Playwright：

     ```powershell
     python -m pip install playwright
     python -m playwright install
     ```

   - 启动脚本后脚本会以一个独立的 Edge profile（位于脚本同目录的 `cnki_user_data`）打开一个 Edge 窗口。这个配置默认不会改动你系统 Edge 的默认 profile。但请注意：切勿把 `USER_DATA_DIR` 指向系统 Edge 的主 profile，避免覆盖/损坏已有收藏。

   - 在脚本打开的新 Edge 窗口中，请手动完成以下操作（仅需在最初页做一次）:
     1. 登录 CNKI（若尚未登录）；
     2. 在搜索结果页设置排序为“相关度”（你之前已设置，这里再次确认）；
     3. 设置每页显示 50 条；
     4. 选择并确认要收藏到的目标“专题”（脚本可尝试选择专题，但最好先在页面中手动选好以降低复杂性）。

   - 上述准备完成并确认页面处于搜索结果列表时，回到终端并按回车继续（脚本在此处会等待）。

2) 运行时的自动化与人工交互（脚本行为）
   - 每页的操作顺序：
     1) 点击“全选”；等待约 ACTION_DELAY（默认 1.5s）；
     2) 点击“收藏到专题”；等待约 ACTION_DELAY（默认 1.5s）；
     3) 模拟按下键盘 ArrowRight 翻页；按键后至少等待 PAGE_NAV_DELAY（默认 4.0s）；
     4) 重复直到到达最后一页或达到 `max_pages`。

   - 当脚本检测到疑似人机验证（验证码）时，会：
     1) 在终端打印提示并暂停执行，等待你在浏览器中完成验证（脚本不会自动跳过验证码）；
     2) 验证完成后，回到终端按回车，脚本会继续执行后续循环。

   - 验证检测策略包括但不限于：页面文本关键词（如“验证码”、“请验证”）、可见的模态对话（role=dialog）、可疑 iframe（autodokit/title 包含 captcha/geetest/verify）或常见类名（.captcha、.geetest 等）。检测到任一策略即触发暂停。

3) 如何在不影响现有收藏的前提下测试脚本（建议的安全步骤）
   - 推荐先做 Dry Run：临时注释掉脚本中真正执行收藏的行（`collect_to_topic(page, topic_name)`），只测试“全选”和翻页逻辑；确认行为正确后再恢复收藏操作。
   - 或者把 `max_pages` 设置为 1 或 2 来做小范围验证；确认正确后再放开。
   - 如果你希望脚本永远不改动你的真是收藏，可在脚本中添加或使用 `DRY_RUN=True` 变体（此脚本默认没有 DRY_RUN，但你可手动注释收藏调用）。

4) 在运行中遇到验证码时的建议操作流程（快速参考）
   1. 脚本在终端提示出现验证码并暂停；
   2. 切到 Edge 浏览器窗口，按要求完成滑块/图形/短信等验证；
   3. 验证通过且页面恢复正常后，回终端按回车让脚本继续循环；
   4. 若验证未能生效或页面仍提示验证，脚本会再次检测并继续等待（可重复按回车尝试或手动刷新页面）。

5) 取消/中断
   - 如需立即停止脚本，按终端中的 Ctrl+C。再次运行脚本会从起始 URL 重新开始（当前脚本不保存进度）。

6) 日志与调试
   - 脚本会把运行日志写入与脚本同目录下的 `cnki_auto_favorite.log`；遇到问题先查看日志。
   - 若需要更进一步调试（例如确认定位器），可以在脚本中临时加入 `page.pause()` 或 `page.screenshot()` 来辅助定位。

7) 其他说明
   - 本脚本采用多候选定位器策略（文本、role、常见 class/id），但网站前端随时可能变化，调试时可能需要根据页面 DOM 微调定位器。
   - 如果你希望我把 `DRY_RUN` 或进度保存功能加入脚本，请告诉我，我可以在不运行任何操作的前提下更新代码并交付给你。

使用示例（在 PowerShell 中）

```powershell
# 安装 Playwright（若尚未安装）
python -m pip install playwright
python -m playwright install

# 运行脚本（会打开一个新的 Edge 窗口）
python .utodo-kitffairs\自动化导入知网研学专题.py
```

模块其余部分实现自动化逻辑：定位器、验证码检测、点击重试与循环控制（见下文代码）。

#### 事务 Markdown 说明摘录

- 自动化导入知网研学专题

- 用途

- 该事务用于执行 `自动化导入知网研学专题` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("自动化导入知网研学专题",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.自动化导入知网研学专题.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 解析与分块

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 解析与分块 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 解析与分块 |
| 目录 | autodokit/affairs/解析与分块 |
| Runner.module | autodokit.affairs.解析与分块.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/解析与分块/affair.md |

#### 模块说明

解析与分块事务（通用说明）。

本事务的目标（一句话）：
- 把每篇文章的长文本拆成多个可管理的小段（chunk），方便检索和逐段交给模型或人工阅读。

为什么需要它（使用角度，通俗）：
- 长文本一次性交给模型会超过上下文限制或导致模型失焦。把文章切成小段可以：
  - 让检索只返回最相关的小段，提升效率；
  - 使模型逐段处理并汇总为准确的摘要/笔记。

本事务做什么（技术摘要，便于理解）：
- 读取 `input_structured_dir` 或 `content_db` 中登记的结构化结果，按段落单元优先进行分块，并写入 chunk 分片与索引表。

输入（必需）：
- `input_structured_dir` 或 `content_db`：结构化主链输入，包含 `structured_abs_path` 等状态字段。

输出（必需产物）：
- chunk 分片文件：`chunk_shards/*.jsonl`。
- 分片清单：`chunk_manifest.json`。
- SQLite 索引：`literature_chunk_sets` 与 `literature_chunks`。

在自动化流程中的位置（示例）：
- 场景：你想在一批长文档中快速定位“政策冲击”相关内容，分块后检索能迅速返回最相关的小段；或把这些段落交给模型分别摘要再合并。

何时用（简短建议）：
- 在你需要做检索/自动摘要/或把文章交给模型逐段分析时使用。若只想人工全文阅读，可不分块。

运行示例（项目 `workflow_010`）：
- 运行整个 flow（含提取与分块）:

  py main.py

- 单独运行本事务：

    py -c "from pathlib import Path; from autodo-kit.affairs.解析与分块 import execute; execute(Path('workflows/workflow_010/workflow.json'))"

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表（chunks.jsonl、chunk_stats.json）。

Examples:
    >>> from pathlib import Path
    >>> from autodokit.affairs.解析与分块 import execute
    >>> execute(Path('workflows/workflow_010/workflow.json'))

#### 事务 Markdown 说明摘录

- 解析与分块

- 用途

- 该事务用于执行 `解析与分块` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| docs | docs | jsonl |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| chunks | chunks | jsonl |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| docs | docs | jsonl |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| chunks | chunks | jsonl |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| chunk_size | 否 | 1500 | 1500 |
| chunk_shard_size | 否 | 200 | 200 |
| chunks_uid | 否 | "" | "" |
| content_db | 否 | "workflows/workspace/database/content/content.db" | "workflows/workspace/database/content/content.db" |
| min_chunk_size | 否 | 200 | 200 |
| output_dir | 否 | "workflows/workflow_解析与分块/output/03_chunk" | "workflows/workflow_解析与分块/output/03_chunk" |
| source_backend | 否 | "structured_json" | "structured_json" |
| source_scope | 否 | "structured" | "structured" |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| chunk_size | 否 | 1500 | 1500 |
| chunk_shard_size | 否 | 200 | 200 |
| chunks_uid | 否 | "" | "" |
| content_db | 否 | "workflows/workspace/database/content/content.db" | "workflows/workspace/database/content/content.db" |
| min_chunk_size | 否 | 200 | 200 |
| output_dir | 否 | "workflows/workflow_解析与分块/output/03_chunk" | "workflows/workflow_解析与分块/output/03_chunk" |
| source_backend | 否 | "structured_json" | "structured_json" |
| source_scope | 否 | "structured" | "structured" |

#### node.config JSON 示例

```json
{
  "content_db": "workflows/workspace/database/content/content.db",
  "output_dir": "workflows/workflow_解析与分块/output/03_chunk",
  "chunk_size": 1500,
  "min_chunk_size": 200,
  "chunk_shard_size": 200
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "content_db": "workflows/workspace/database/content/content.db",
  "output_dir": "workflows/workflow_解析与分块/output/03_chunk",
  "chunk_size": 1500,
  "min_chunk_size": 200,
  "chunk_shard_size": 200
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("解析与分块",
  config={'content_db': 'workflows/workspace/database/content/content.db',
     'output_dir': 'workflows/workflow_解析与分块/output/03_chunk',
     'chunk_size': 1500,
   'min_chunk_size': 200,
   'chunk_shard_size': 200},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.解析与分块.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 订阅文献访问治理

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 订阅文献访问治理 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 订阅文献访问治理 |
| 目录 | autodokit/affairs/订阅文献访问治理 |
| Runner.module | autodokit.affairs.订阅文献访问治理.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/订阅文献访问治理/affair.md |

#### 模块说明

订阅文献访问治理事务。

#### 事务 Markdown 说明摘录

- 订阅文献访问治理

评估订阅文献是否需要人工授权、校园网环境或已具备直接访问条件。

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_scope | 否 | "campus" | "campus" |
| auth_mode | 否 | "manual" | "manual" |
| output_dir | 否 | "" | "" |
| target_records | 否 | [] | [] |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| access_scope | 否 | "campus" | "campus" |
| auth_mode | 否 | "manual" | "manual" |
| output_dir | 否 | "" | "" |
| target_records | 否 | [] | [] |

#### node.config JSON 示例

```json
{
  "target_records": [],
  "access_scope": "campus",
  "auth_mode": "manual",
  "output_dir": ""
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "target_records": [],
  "access_scope": "campus",
  "auth_mode": "manual",
  "output_dir": ""
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("订阅文献访问治理",
    config={'target_records': [],
     'access_scope': 'campus',
     'auth_mode': 'manual',
     'output_dir': ''},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.订阅文献访问治理.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 语义预筛选

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | 语义预筛选 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 语义预筛选 |
| 目录 | autodokit/affairs/语义预筛选 |
| Runner.module | autodokit.affairs.语义预筛选.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/语义预筛选/affair.md |

#### 模块说明

基于主题的文献语义预筛选事务（面向社会科学研究者的通俗说明）。

本事务的目标（用一句话说明）：
- 从已有的题录/元数据表中，快速筛选出“值得详细阅读”的候选文献，减少后续精读与模型调用的工作量。

为什么需要它（学术角度，通俗）：
- 在做综述或选题初期，你可能有数百条题录（题名/摘要/关键词）。这一步相当于人工阅读书名与摘要，先把看起来相关的 50~100 篇放进“要读”名单，后续才花时间精读。

本事务做什么（技术摘要，便于理解）：
- 读取由 `导入和预处理文献元数据` 产生的 `文献数据表.csv`。
- 根据配置的关键词规则、是否有本地 PDF、年份范围等做快速筛选。
- 可选启用一个“轻量语义”占位打分（基于词覆盖率），后续可替换为 embedding 相似度。

输入（必需）：
- `input_table_csv`：由导入事务生成的主表 CSV（含 title, abstract, keywords, pdf_path, year 等字段）。

输出（必需产物）：
- `review_candidates.csv`：候选清单（含 uid、title、score、reason、pdf_path）。
- `review_excluded.csv`：被排除的记录（含原因）。
- `prescreen_report.json`：运行统计与配置回显，便于审计。

在学术流程中的位置（示例）：
- 场景 A（选题）：你有 800 条题录，先运行预筛选把候选降到 80 条，再进入 PDF 抽取与精读；这样节省大量人工/API 成本。
- 场景 B（文献回顾）：老师给你一个主题说明（topic.txt），把该文本作为 `semantic_queries`，快速找到与主题最接近的文献。

何时用（简短建议）：
- 如果你的文献条目少（<20），可以跳过此步，直接做 PDF 提取与人工精读；
- 如果条目多（几十到上千），强烈建议先运行本事务以削减规模。

运行示例（项目 `workflow_010`）：
- 在 `workflows/workflow_010/workflow.json` 已配置时，直接运行：

  py main.py

- 单独运行（示例）：

  py -c "from pathlib import Path; from autodo-kit.affairs.语义预筛选 import execute; execute(Path('workflows/workflow_010/workflow.json'))"

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表（候选 CSV、排除 CSV、报告 JSON）。

Examples:
    >>> from pathlib import Path
    >>> from autodokit.affairs.语义预筛选 import execute
    >>> execute(Path('workflows/workflow_010/workflow.json'))

#### 事务 Markdown 说明摘录

- 语义预筛选

- 用途

- 该事务用于执行 `语义预筛选` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| table | table | csv |
| keywords | keywords | dir |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| prescreen | prescreen | dir |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| table | table | csv |
| keywords | keywords | dir |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| prescreen | prescreen | dir |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| exclude_domains | 否 | ["方法维度"] | ["方法维度"] |
| include_domains | 否 | ["主题维度A", "主题维度B"] | ["主题维度A", "主题维度B"] |
| include_if_has_pdf | 否 | true | true |
| input_keywords | 否 | "workflows/workflow_生成关键词集合/data/01_keyword_set" | "workflows/workflow_生成关键词集合/data/01_keyword_set" |
| input_table_csv | 否 | "workflows/workflow_导入和预处理文献元数据/data/题录导出文件/文献数据表.csv" | "workflows/workflow_导入和预处理文献元数据/data/题录导出文件/文献数据表.csv" |
| output_dir | 否 | "workflows/workflow_语义预筛选/data/01_prescreen" | "workflows/workflow_语义预筛选/data/01_prescreen" |
| semantic_enable | 否 | false | false |
| semantic_queries | 否 | [] | [] |
| top_k | 否 | 80 | 80 |
| year_range | 否 | null | null |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| exclude_domains | 否 | ["方法维度"] | ["方法维度"] |
| include_domains | 否 | ["主题维度A", "主题维度B"] | ["主题维度A", "主题维度B"] |
| include_if_has_pdf | 否 | true | true |
| input_keywords | 否 | "workflows/workflow_生成关键词集合/data/01_keyword_set" | "workflows/workflow_生成关键词集合/data/01_keyword_set" |
| input_table_csv | 否 | "workflows/workflow_导入和预处理文献元数据/data/题录导出文件/文献数据表.csv" | "workflows/workflow_导入和预处理文献元数据/data/题录导出文件/文献数据表.csv" |
| output_dir | 否 | "workflows/workflow_语义预筛选/data/01_prescreen" | "workflows/workflow_语义预筛选/data/01_prescreen" |
| semantic_enable | 否 | false | false |
| semantic_queries | 否 | [] | [] |
| top_k | 否 | 80 | 80 |
| year_range | 否 | null | null |

#### node.config JSON 示例

```json
{
  "input_table_csv": "workflows/workflow_导入和预处理文献元数据/data/题录导出文件/文献数据表.csv",
  "input_keywords": "workflows/workflow_生成关键词集合/data/01_keyword_set",
  "output_dir": "workflows/workflow_语义预筛选/data/01_prescreen",
  "include_if_has_pdf": true,
  "include_domains": [
    "主题维度A",
    "主题维度B"
  ],
  "exclude_domains": [
    "方法维度"
  ],
  "year_range": null,
  "top_k": 80,
  "semantic_enable": false,
  "semantic_queries": []
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "input_table_csv": "workflows/workflow_导入和预处理文献元数据/data/题录导出文件/文献数据表.csv",
  "input_keywords": "workflows/workflow_生成关键词集合/data/01_keyword_set",
  "output_dir": "workflows/workflow_语义预筛选/data/01_prescreen",
  "include_if_has_pdf": true,
  "include_domains": [
    "主题维度A",
    "主题维度B"
  ],
  "exclude_domains": [
    "方法维度"
  ],
  "year_range": null,
  "top_k": 80,
  "semantic_enable": false,
  "semantic_queries": []
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("语义预筛选",
    config={'input_table_csv': 'workflows/workflow_导入和预处理文献元数据/data/题录导出文件/文献数据表.csv',
     'input_keywords': 'workflows/workflow_生成关键词集合/data/01_keyword_set',
     'output_dir': 'workflows/workflow_语义预筛选/data/01_prescreen',
     'include_if_has_pdf': True,
    'include_domains': ['主题维度A', '主题维度B'],
    'exclude_domains': ['方法维度'],
     'year_range': None,
     'top_k': 80,
     'semantic_enable': False,
     'semantic_queries': []},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.语义预筛选.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```


## 22. 格式转换事务

### CAJ文件转PDF

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | CAJ文件转PDF |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 CAJ文件转PDF |
| 目录 | autodokit/affairs/CAJ文件转PDF |
| Runner.module | autodokit.affairs.CAJ文件转PDF.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/CAJ文件转PDF/affair.md |

#### 模块说明

CAJ 文件转 PDF 事务（占位实现 — 需要人工操作）

本文件提供一个事务占位实现以便在工作流中声明 "CAJ文件转PDF" 的步骤。
该事务不实现自动化的 CAJ -> PDF 转换逻辑；相反，工作流与文档会说明如何使用第三方工具或在线服务（例如 https://caj2pdf.cn/batch ）进行批量转换，用户在外部完成转换并手动把导出的 PDF 放入指定的 `output_dir`。

本占位实现的目的：
- 在调度器/工作流层面占位该事务，使工作流完整；
- 在运行时给出清晰的日志/返回值，提醒使用者需手动完成转换并把产物放到指定位置；
- 简单地返回 `output_dir` 中已经存在的 PDF 列表（如果有的话）。

注意：本文件遵循仓库的事务约定——不做任何路径绝对化或路径修复；调度器应该在传入的合并后配置中保证路径已为绝对路径。

Args:
    config_path: 合并后的事务配置文件路径（由调度器写入的临时 JSON 文件），类型为 `Path` 或可被 `Path()` 接受的字符串。

Returns:
    List[Path]: 如果 `output_dir` 中已有 PDF 文件，则返回这些 PDF 的路径列表；否则返回空列表（表示需要人工将转换产物放入该目录）。

Raises:
    ValueError: 当 `config_path` 不存在或无法解析为 JSON 时抛出。

#### 事务 Markdown 说明摘录

- CAJ文件转PDF

- 用途

- 该事务用于执行 `CAJ文件转PDF` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

- 无

#### interface.outputs

- 无

#### node.inputs

- 无

#### node.outputs

- 无

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("CAJ文件转PDF",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.CAJ文件转PDF.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### LaTeX转Word

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | LaTeX转Word |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 LaTeX转Word |
| 目录 | autodokit/affairs/LaTeX转Word |
| Runner.module | autodokit.affairs.LaTeX转Word.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/LaTeX转Word/affair.md |

#### 模块说明

事务： LaTeX 转 Word。

该事务用于编排 LaTeX -> Word 转换流程，支持：
- 可选的 `\subfile` 递归合并。
- Pandoc 转换。
- 可选的 docx 后处理（标题编号、TODO/NOTE/文献标色）。
- dry-run 预览。

#### 事务 Markdown 说明摘录

- LaTeX转Word

- 用途

- 该事务用于执行 `LaTeX转Word` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("LaTeX转Word",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.LaTeX转Word.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### PDF文件转md文件

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | PDF文件转md文件 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 PDF文件转md文件 |
| 目录 | autodokit/affairs/PDF文件转md文件 |
| Runner.module | autodokit.affairs.PDF文件转md文件.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/PDF文件转md文件/affair.md |

#### 模块说明

事务：PDF 文件转 Markdown 文件。

本事务用于批量将一个文件夹（不含子文件夹）内的所有 `.pdf` 文件转换为同名 `.md` 文件。

约定（务必遵守）：
- 事务只消费绝对路径；任何相对路径都视为调度层/配置层缺陷，本事务将直接报错。
- 路径绝对化由调度器在写入 `.tmp/*.json` 前完成。

#### 事务 Markdown 说明摘录

- PDF文件转md文件

- 用途

- 该事务用于执行 `PDF文件转md文件` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

- 无

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| md_dir | md_dir | dir |

#### node.inputs

- 无

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| md_dir | md_dir | dir |

#### 业务参数表（affair.json）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| babeldoc | 否 | {"enabled": false, "note": "这里放 BabelDOC 需要的参数（占位/透传）"} | {"enabled": false, "note": "这里放 BabelDOC 需要的参数（占位/透传）"} |
| converter | 否 | "babeldoc" | "babeldoc" |
| input_pdf_dir | 否 | "data/文献原文数据" | "data/文献原文数据" |
| output_log | 否 | "workflows/workflow_PDF文件转md文件/data/pdf_to_md_manifest.log" | "workflows/workflow_PDF文件转md文件/data/pdf_to_md_manifest.log" |
| output_md_dir | 否 | "data/文献原文转md数据" | "data/文献原文转md数据" |
| overwrite | 否 | false | false |

#### 节点默认配置表（node_template.config）

| 字段 | 必填 | 默认值 | 示例值 |
| --- | --- | --- | --- |
| babeldoc | 否 | {"enabled": false, "note": "这里放 BabelDOC 需要的参数（占位/透传）"} | {"enabled": false, "note": "这里放 BabelDOC 需要的参数（占位/透传）"} |
| converter | 否 | "babeldoc" | "babeldoc" |
| input_pdf_dir | 否 | "data/文献原文数据" | "data/文献原文数据" |
| output_log | 否 | "workflows/workflow_PDF文件转md文件/data/pdf_to_md_manifest.log" | "workflows/workflow_PDF文件转md文件/data/pdf_to_md_manifest.log" |
| output_md_dir | 否 | "data/文献原文转md数据" | "data/文献原文转md数据" |
| overwrite | 否 | false | false |

#### node.config JSON 示例

```json
{
  "input_pdf_dir": "data/文献原文数据",
  "output_md_dir": "data/文献原文转md数据",
  "converter": "babeldoc",
  "babeldoc": {
    "enabled": false,
    "note": "这里放 BabelDOC 需要的参数（占位/透传）"
  },
  "overwrite": false,
  "output_log": "workflows/workflow_PDF文件转md文件/data/pdf_to_md_manifest.log"
}
```

#### affair.json 业务参数 JSON 示例

```json
{
  "input_pdf_dir": "data/文献原文数据",
  "output_md_dir": "data/文献原文转md数据",
  "converter": "babeldoc",
  "babeldoc": {
    "enabled": false,
    "note": "这里放 BabelDOC 需要的参数（占位/透传）"
  },
  "overwrite": false,
  "output_log": "workflows/workflow_PDF文件转md文件/data/pdf_to_md_manifest.log"
}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("PDF文件转md文件",
    config={'input_pdf_dir': 'data/文献原文数据',
     'output_md_dir': 'data/文献原文转md数据',
     'converter': 'babeldoc',
     'babeldoc': {'enabled': False, 'note': '这里放 BabelDOC 需要的参数（占位/透传）'},
     'overwrite': False,
     'output_log': 'workflows/workflow_PDF文件转md文件/data/pdf_to_md_manifest.log'},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.PDF文件转md文件.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### PDF文件转结构化数据文件

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | PDF文件转结构化数据文件 |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 PDF文件转结构化数据文件 |
| 目录 | autodokit/affairs/PDF文件转结构化数据文件 |
| Runner.module | autodokit.affairs.PDF文件转结构化数据文件.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/PDF文件转结构化数据文件/affair.md |

#### 模块说明

事务：PDF 文件转结构化数据文件。

本事务用于批量将一个文件夹（不含子文件夹）内的所有 `.pdf` 文件转换为“适合大模型读取与解析”的结构化文档数据。

设计目标：
- 面向复杂论文 PDF：尽量保留表格/公式/图注等信息的可追溯结构。
- 输出以 JSON 为主，必要时允许包含多模态占位（例如图片引用路径、页码、bbox）。

约定（务必遵守）：
- 事务只消费绝对路径；任何相对路径都视为调度层/配置层缺陷，本事务将直接报错。
- 路径绝对化由调度器在写入 `.tmp/*.json` 前完成。

#### 事务 Markdown 说明摘录

- PDF文件转结构化数据文件

- 用途

- 该事务用于执行 `PDF文件转结构化数据文件` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("PDF文件转结构化数据文件",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.PDF文件转结构化数据文件.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### Word转LaTeX

#### 基本信息

| 字段 | 值 |
| --- | --- |
| 事务名 | Word转LaTeX |
| 领域 | business |
| 所有者 | aok |
| 版本 | migrated |
| 描述 | 事务 Word转LaTeX |
| 目录 | autodokit/affairs/Word转LaTeX |
| Runner.module | autodokit.affairs.Word转LaTeX.affair |
| Runner.callable | execute |
| Runner.pass_mode | config_path |
| 文档源 | autodokit/affairs/Word转LaTeX/affair.md |

#### 模块说明

事务： Word 转 LaTeX。

该事务用于编排 Word -> LaTeX 转换流程，支持：
- Pandoc 反向转换。
- 可选 LaTeX 模板。
- 可选 include-in-header。
- dry-run 预览。

#### 事务 Markdown 说明摘录

- Word转LaTeX

- 用途

- 该事务用于执行 `Word转LaTeX` 对应的业务逻辑。

- 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

#### interface.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### interface.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### node.inputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| in | in | any |

#### node.outputs

| 端口键 | 名称 | 类型/定义 |
| --- | --- | --- |
| out | out | any |

#### 业务参数表（affair.json）

- 无

#### 节点默认配置表（node_template.config）

- 无

#### node.config JSON 示例

```json
{}
```

#### affair.json 业务参数 JSON 示例

```json
{}
```

#### 推荐调用示例：run_affair

```python
from pathlib import Path
import autodokit as aok

workspace_root = Path(r"D:/my_workspace").resolve()
outputs = aok.run_affair("Word转LaTeX",
    config={},
    workspace_root=workspace_root,
)
print(outputs)
```

#### 高级调用示例：直接导入模块

```python
from pathlib import Path
from autodokit.affairs.Word转LaTeX.affair import execute

config_path = Path(r"D:/my_workspace/configs/affair_config.json").resolve()
outputs = execute(config_path)
print(outputs)
```

### 已退役：从PDF提取可检索文本

该事务已退役，不再属于当前 PDF 主链。

- 当前推荐链路为：`PDF文件转结构化数据文件` -> `解析与分块` -> `向量化与索引构建`。
- 单篇粗读、单篇精读、综述草稿生成与综述研读事务均优先消费 `*.structured.json` 或 `content.db` 中登记的 `structured_abs_path`。
- `docs.jsonl` 不再作为本仓 PDF 处理工具的正式输入契约。
