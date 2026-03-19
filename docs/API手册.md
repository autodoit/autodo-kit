# API手册

autodo-kit 对外公开的是“事务内容 + 事务工具 + 少量桥接入口”。真正的运行时执行与调度 API 由 autodo-engine 提供。

## 1. 桥接入口

### 1.1 autodokit.run_affair(...)

用途：通过 autodo-engine 的运行时执行官方事务或用户覆盖事务。

典型参数：

- affair_uid：事务 UID
- config：字典配置
- config_path：配置文件路径
- workspace_root：工作区根目录

### 1.2 autodokit.prepare_affair_config(...)

用途：调用引擎侧统一路径预处理逻辑，对事务配置中的路径字段做绝对化。

### 1.3 autodokit.import_affair_module(...)

用途：按事务 UID 导入实际事务模块，优先读取 runner.module，必要时回退到源码文件路径加载。

### 1.4 autodokit.import_user_affair(...)

用途：将用户功能程序导入为事务三件套目录（`affair.py`、`affair.json`、`affair.md`），并自动写入事务管理数据库。名称冲突时自动追加 `_v正整数`。

## 2. autodokit.tools 导出

autodokit.tools 统一导出两类能力：

- 事务本仓实现：如 pandoc_tex_word_converter、task_docs、obsidian_exporter、metadata_dedup
- 引擎侧通用能力桥接：如 load_json_or_py、resolve_paths_to_absolute、build_registry、evaluate_expression

常用导出示例：

- load_json_or_py
- resolve_paths_to_absolute
- write_affair_json_result
- build_cnki_result
- load_dispatch_map
- evaluate_expression
- append_flow_trace_event

## 3. 事务模块契约

每个事务目录通常包含：

- affair.py：事务执行主体
- affair.json：纯业务参数模板
- affair.md：说明文档（用途、场景、参数、输出、示例）

事务目录应保持“业务三件套纯粹化”。事务管理所需 runner/node/governance 等元数据由事务管理系统数据库统一承载。

## 4. 不再由本仓提供的接口

以下接口已拆分到 autodo-engine：

- 流程图加载与注册
- 任务创建与推进
- taskdb / 决策 / 审计视图
- CLI 子命令
