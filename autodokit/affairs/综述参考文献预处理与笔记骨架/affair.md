# 综述参考文献预处理与笔记骨架

## 概述
A065 承接 A060 已就绪的综述解析资产，执行参考文献扫描、cite_key 映射与标准笔记骨架生成，并把下游入口写入 A080。

## 输入
- `workspace_root`：工作区绝对路径。
- `content_db`：文献主库 SQLite 路径。
- `review_read_pool_path`：兼容输入，默认优先使用 `literature_reading_queue(stage='A065')` 当前态。
- `review_reading_batches_path`：A050 产出的 `review_reading_batches.csv`。

## 输出
- `steps/A065_review_reference_preprocessing/` 下的审计产物。
- `gate_review.json`（G065）。

## 说明
A065 是 A060 的后续节点，专门负责参考文献处理与笔记骨架，不再由 A060 承担该职责。
