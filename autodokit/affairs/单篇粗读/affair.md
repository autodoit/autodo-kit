# 单篇粗读

## 用途

- 该事务用于执行 `单篇粗读` 对应的业务逻辑。
- 面向“先粗后精”的主链流程，先快速抽取文献信息与参考文献，再把结果交给后续精读事务。

## 运行入口

- module: `autodokit.affairs.单篇粗读.affair`
- callable: `execute`
- pass_mode: `config_path`

## 参数说明

- 以 `affair.json.interface.inputs` 与代码实现为准。
- 建议至少提供：`input_structured_json`、`input_structured_dir` 或 `content_db`，以及 `output_dir`、`uid` 或 `doc_id`。

## 输出说明

- `rough_reading_{uid_or_doc_id}.md`：粗读笔记。
- `rough_reading_result_{uid_or_doc_id}.json`：结构化结果（可用于精读前置输入）。
- 若启用占位引文写入且设置 `content_db`，会更新统一内容主库。
