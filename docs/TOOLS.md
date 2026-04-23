# 工具索引（Tools Index）

本页是 `autodokit.tools` 的快速入口索引，不替代源码签名，也不重复完整 API 说明。

公开工具与开发者工具的真相源分别是：

1. `autodokit.tools.list_user_tools()`
2. `autodokit.tools.list_developer_tools()`
3. `autodokit.tools.get_tool(name, scope=...)`

完整调用契约、参数表、返回值与示例统一收录在 [API手册](API手册.md)；事务全量手册收录在 [AOK预置事务手册](AOK预置事务手册.md)。

## 快速分组

### 文献与引用

- `parse_reference_text`
- `insert_placeholder_from_reference`
- `literature_upsert`
- `literature_insert_placeholder`
- `literature_match`
- `literature_attach_file`
- `literature_bind_standard_note`
- `literature_get`

### 参考文献扫描与占位

- `extract_reference_lines_from_attachment`
- `parse_reference_text_with_llm`
- `process_reference_citation`
- `match_reference_citation_record`
- `upsert_reference_citation_placeholder`
- `writeback_reference_citation_record`
- `generate_reference_cite_key`
- `ensure_reference_citation_cite_key`
- `refine_reference_lines_with_llm`
- `build_reference_quality_summary`
- `build_online_lookup_placeholder_fields`

### 知识库与笔记

- `generate_knowledge_uid`
- `knowledge_note_register`
- `knowledge_note_validate_obsidian`
- `knowledge_bind_literature_standard_note`
- `knowledge_base_generate`
- `knowledge_index_sync_from_note`
- `knowledge_attachment_register`
- `knowledge_sync_note`
- `knowledge_attach_file`
- `knowledge_get`
- `knowledge_find_by_literature`

### 包级运行时 API（不属于 `autodokit.tools` 导出）

- `run_affair`
- `prepare_affair_config`
- `import_affair_module`
- `bootstrap_runtime`
- `register_graph`
- `load_graph`

### 工具检索与清单

- `list_tools`
- `list_user_tools`
- `list_developer_tools`
- `get_tool`

### 在线检索与迁移

- `run_online_retrieval_router`
- `run_online_retrieval_from_bib`
- `migrate_workspace_paths`
- `PathMapping`

### 直接查源码

当需要精确签名或示例时，优先查看：

1. [API手册](API手册.md)
2. `autodokit/tools/__init__.py`
3. 各工具模块的函数 docstring 与 `demos/scripts/` 示例

上次更新: 2026-04-22
