# 候选文献视图构建

## 用途

本事务用于直接从统一内容主库生成综述候选视图、阅读池和阅读批次。

在 AcademicResearch-auto-workflow 当前主链口径中，本事务对应 A060“综述候选文献视图构建”的官方 AOK 入口。

## 输入

1. `content_db`：统一内容主库绝对路径。本事务直接从 `content.db` 读取文献主表；旧 `literature_csv` / `input_csv` 仅作兼容。
2. `research_topic`、`topic_terms`、`topic_keyword_groups`、`required_topic_group_indices`、`recent_years` 等主题直筛参数。
3. 主题筛选参数用于 A050 直题筛选；综述候选视图、阅读池和共享预备资产入口由当前事务承担；参考文献处理与笔记骨架在 A065 执行。
4. `persist_review_views_to_content_db`：默认 `false`。关闭时仅输出 CSV 产物并推进中文状态链，不把 `review_*` 英文中间表写入 `content.db`。

## 输出

1. `review_candidate_pool_index.csv`
2. `review_candidate_pool_readable.csv`
3. `review_priority_view.csv`
4. `review_deep_read_queue_seed.csv`
5. `review_read_pool.csv`
6. `review_already_read_exit_view.csv`
7. `review_reading_batches.csv`
8. `gate_review.json`
9. 综述链相关当前态队列与桥接入口

## 说明

1. 前置筛选阶段允许按研究主题、关键词组和年份窗口直接从内容主库筛出综述候选。
2. 当前事务负责综述候选池、阅读池、批次以及共享预备资产入口，但不负责 reference 清洗、占位映射与标准笔记骨架生成，这些职责由 A065 接续承担。
3. AOK 日志是否写入由 `workspace/config/config.json` 的 `logging.enabled` 控制；关闭时不得影响主流程。
4. 如需兼容旧链路，可显式将 `persist_review_views_to_content_db=true`，此时才会写入 legacy `review_*` 表。
