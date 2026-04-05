# 综述预处理

## 概述
A060 综述预处理事务。仅承接 A050 已产出的阅读池，执行 parse asset 复用/补齐，并把可执行条目推进到 A065。

## 输入
- `workspace_root`：工作区绝对路径。
- `content_db`：文献主库 SQLite 路径。

## 输出
- `steps/A060_review_preprocessing/` 下的审计产物。
- `gate_review.json`（G060）。

## 说明
该事务与 A065 形成分层：A060 只做结构化资产准备，A065 再做参考文献处理和笔记骨架生成。
