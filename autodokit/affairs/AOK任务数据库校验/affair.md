# AOK任务数据库校验

校验 AOK 003 版任务数据库最小契约：

- `database/tasks/tasks.csv`
- `database/tasks/task_artifacts.csv`
- `tasks/`

并执行一致性检查（任务目录存在性、任务产物路径存在性、可用时的文献/知识 UID 引用校验）。

本事务与旧版 `任务数据库校验` 事务隔离，避免混用 AOE 语义校验规则。

- `content_db`：可选统一内容主库绝对路径；显式传入时会同时用于文献 UID 与知识 UID 的存在性校验。
