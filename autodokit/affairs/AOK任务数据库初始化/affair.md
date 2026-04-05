# AOK任务数据库初始化

初始化 AOK 003 版任务数据库骨架，创建以下最小结构：

- `database/tasks/tasks.csv`
- `database/tasks/task_artifacts.csv`
- `tasks/`

本事务与旧版 `任务数据库初始化` 事务隔离，避免混用 AOE 语义字段与文件结构。
