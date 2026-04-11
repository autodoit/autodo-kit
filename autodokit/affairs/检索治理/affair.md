# 检索治理

统一处理 A040 的三阶段检索执行：本地检索、在线补检、在线获取。

## 当前职责

1. 在 `content_db` 中执行本地优先检索并生成缺口分析。
2. 按开关和触发策略调用 `run_online_retrieval_router(...)` 执行在线 metadata 补检。
3. 在在线 metadata 基础上按 `online_acquisition_mode` 执行 PDF 下载或 HTML 抽取。
4. 将在线结果与本地结果收口，回写 `content_db`，并产出 G040 审计所需文件。

## 核心开关

1. `enable_local_retrieval`：是否启用本地检索。
2. `enable_online_retrieval`：是否启用在线 metadata 补检。
3. `online_trigger_policy`：在线触发策略，支持 `gap_only`、`always`、`manual_seed_only`。
4. `online_acquisition_mode`：在线获取模式，支持 `none`、`download_pdf`、`html_extract`、`both`。

## 主要输出

1. `local_hits.json`
2. `gap_analysis.json`
3. `online_retrieval_result.json`
4. `online_acquisition_result.json`
5. `merged_retrieval_result.json`
6. `gate_review.json`
7. `retrieval_readable.md`
