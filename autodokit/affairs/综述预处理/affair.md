# 综述预处理

## 概述
本事务保留为历史兼容与局部补位事务。

它执行综述 parse asset 的复用/补齐，并把可执行条目推进到后续综述处理阶段；但它不再是 AcademicResearch-auto-workflow 当前主链中 A060 的官方 AOK 映射。

## 输入
- `workspace_root`：工作区绝对路径。
- `content_db`：文献主库 SQLite 路径。

## 输出
- `steps/A060_review_preprocessing/` 下的审计产物。
- `gate_review.json`（G060）。

## 说明
1. 当前主链的 A060 官方入口已经切换为 `autodokit.affairs.候选文献视图构建.affair.execute`。
2. 本事务仅在历史链路回放、局部补位或兼容排障场景下保留使用。
3. 该事务与 A065 形成过往分层：本事务只做结构化资产准备，A065 再做参考文献处理和笔记骨架生成。
