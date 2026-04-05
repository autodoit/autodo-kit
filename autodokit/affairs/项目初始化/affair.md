# 项目初始化

基于 AOK 内置模板初始化任务数据库、文献数据库、知识数据库和调度配置目录。

同时会在 `workspace/references` 下预创建 PDF 结构化结果的四个固定目录：

- `structured_local_pipeline_v2_reference_context`
- `structured_local_pipeline_v2_full_fine_grained`
- `structured_babeldoc_reference_context`
- `structured_babeldoc_full_fine_grained`

用于按“解析工具链 × 解析方案”组合分别存放同一篇文献的不同结构化结果。