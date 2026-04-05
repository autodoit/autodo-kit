# PDF文件转结构化数据文件

## 用途

- 该事务用于执行 `PDF文件转结构化数据文件` 对应的业务逻辑。

## 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

## 参数说明

- 以 `affair.json.interface.inputs` 与代码实现为准。
- 关键参数补充：
	- `content_db`：统一内容主库绝对路径。提供后，事务会按 `converter + task_type` 自动把结构化结果落到 `workspace/references` 下的固定四组合目录，并同步回写对应文献记录。
	- `output_structured_dir`：可显式指定绝对路径；若留空且已提供 `content_db`，则按四组合契约自动推导。
	- `converter`：当前支持 `local_pipeline_v2` 与历史兼容 `babeldoc`。
	- `task_type`：当前按 `reference_context` 与 `full_fine_grained` 两种方案参与四组合路由。

## 输出说明

- 以 `affair.json.interface.outputs` 与运行日志为准。
- 当启用 `content_db` 自动路由时，结构化结果默认写入以下四个固定目录之一：
	- `workspace/references/structured_local_pipeline_v2_reference_context`
	- `workspace/references/structured_local_pipeline_v2_full_fine_grained`
	- `workspace/references/structured_babeldoc_reference_context`
	- `workspace/references/structured_babeldoc_full_fine_grained`
