# A110 研究脉络梳理

## 用途

- 该事务用于执行 `文献矩阵` 对应的业务逻辑。
- 在 AcademicResearch-auto-workflow 当前主链口径中，本事务对应 A110“研究脉络梳理”的官方 AOK 入口。

## 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

## 参数说明

- 以 `affair.json.interface.inputs` 与代码实现为准。

## 输出说明

- 以 `affair.json.interface.outputs` 与运行日志为准。
