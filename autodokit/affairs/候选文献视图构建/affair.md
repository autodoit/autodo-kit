# 候选文献视图构建

## 用途

本事务服务 A05 节点，用于直接从统一内容主库生成综述候选视图、阅读池和阅读批次，并把入口写入 A060。

## 输入

1. `content_db`：统一内容主库绝对路径。A05 直接从 `content.db` 读取文献主表；旧 `literature_csv` / `input_csv` 仅作兼容。
2. `research_topic`、`topic_terms`、`topic_keyword_groups`、`required_topic_group_indices`、`recent_years` 等主题直筛参数。
3. 主题筛选参数用于 A050 直题筛选，结构化解析和参考文献处理在 A060/A065 执行。

## 输出

1. `review_candidate_pool_index.csv`
2. `review_candidate_pool_readable.csv`
3. `review_priority_view.csv`
4. `review_deep_read_queue_seed.csv`
5. `review_read_pool.csv`
6. `review_already_read_exit_view.csv`
7. `review_reading_batches.csv`
8. `gate_review.json`
9. `literature_reading_queue(stage='A060')` 当前态队列行

## 说明

1. A05 前半段允许绕开 A03，直接按研究主题、关键词组和年份窗口从内容主库筛出综述候选。
2. A05 不再负责逐篇 parse 预热、reference 清洗、占位映射与标准笔记骨架生成，这些职责已下沉到 A060/A065。
3. AOK 日志是否写入由 `workspace/config/config.json` 的 `logging.enabled` 控制；关闭时不得影响 A05 主流程。
