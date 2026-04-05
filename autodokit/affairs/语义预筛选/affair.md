# 语义预筛选

## 用途

- 该事务用于执行 `语义预筛选` 对应的业务逻辑。

## 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

## 参数说明

- 以 `affair.json.interface.inputs` 与代码实现为准。
- 关键参数补充：`content_db` 应指向统一内容主库绝对路径，优先使用 `database/content/content.db`；旧 `input_table_csv` 仅作兼容读取。

## 输出说明

- 以 `affair.json.interface.outputs` 与运行日志为准。
