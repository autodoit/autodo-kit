# AOK三库联动示例

演示 AOK 最新三库联动最小闭环：

1. 从 BibTeX 导入文献主表记录；
2. 从 Zotero RDF `files/` 嵌套目录手动提取并复制附件到 `references/attachments/`；
3. 生成知识标准笔记并同步 `knowledge.db`；
4. 创建 AOK 任务、绑定文献/知识 UID，并登记产物后导出任务包。

## 输入参数

- `project_root`：示例工作区绝对路径。
- `bib_path`：BibTeX 文件绝对路径。
- `rdf_files_root`：Zotero RDF 的 `files/` 目录绝对路径（嵌套目录）。
- `max_bib_records`：最多导入 Bib 条目数量。
- `max_attachments`：最多复制附件数量。
- `output_dir`：结果输出目录绝对路径。

## 输出

- `aok_triple_db_demo_result.json`

其中包含：

- 三库 CSV 文件路径；
- 生成的知识笔记路径；
- 手动提取复制后的附件路径；
- 任务包导出结果。
