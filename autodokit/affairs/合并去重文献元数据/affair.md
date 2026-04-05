# 合并去重文献元数据

## 用途

- 该事务用于执行 `合并去重文献元数据` 对应的业务逻辑。

## 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

## 参数说明

- 以 `affair.json.interface.inputs` 与代码实现为准。
- 关键参数补充：`input_table_path` / `output_table_path` 支持 `.db` 或兼容 CSV，适用于对主库导出表或历史 CSV 做去重，不再把 CSV 写死为唯一输入契约。

## 输出说明

- 以 `affair.json.interface.outputs` 与运行日志为准。
