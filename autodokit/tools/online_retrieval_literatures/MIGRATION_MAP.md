# online_retrieval_literatures 迁移表

## 说明

本文件用于记录旧模块职责迁移到新三层结构后的映射。

## 旧模块到新模块映射

| 旧模块 | 旧职责 | 新模块 | 新职责 |
| --- | --- | --- | --- |
| online_retrieval_router.py | 统一入口 + 直接分发 | router/route_entry.py | 统一入口，仅转发到编排调度 |
| online_retrieval_resolver.py | 输入解析 | orchestrators/input_normalizer.py | 输入规范化与 seed 补齐 |
| online_retrieval_service.py | source/mode/action 分发 | orchestrators/request_dispatcher.py | 调度中枢 + 能力矩阵校验 |
| zh_cnki_batch_* | 批量处理 | orchestrators/download_orchestrator.py / orchestrators/structured_orchestrator.py | 批量编排，循环单篇执行 |
| en_open_access_batch_* | 批量处理 | orchestrators/download_orchestrator.py / orchestrators/structured_orchestrator.py | 批量编排，循环单篇执行 |
| school_foreign_database_portal.py | 门户目录抓取 | executors/navigation_portal.py + orchestrators/source_selection_orchestrator.py | 导航执行 + 来源选择编排 |
| en_chaoxing_portal_retry.py | 门户重试 | executors/navigation_portal.py + orchestrators/retry_orchestrator.py | 重试执行 + retry 编排 |

## 删除状态

1. online_retrieval_resolver.py：已删除。
2. online_retrieval_service.py：已删除。

## 当前三层结构

1. 路由层：router/
2. 编排层：orchestrators/
3. 执行层：executors/
4. 辅助层：contracts/、profiles/、policies/、catalogs/
