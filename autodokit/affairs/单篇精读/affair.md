# 单篇精读

## 用途

- 该事务用于执行 `单篇精读` 对应的业务逻辑。

## 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

## 参数说明

- 以 `affair.json.interface.inputs` 与代码实现为准。
- 关键参数补充：
	- `use_llm`：是否调用大模型。默认 `false`，用于本地规则精读调试。
	- `user_prompt_template`：当 `use_llm=true` 时必填，建议由上游 skill 传入 `单篇精读要求.md` 的绝对路径；程序会在运行时读取该文件正文后再注入 `{title}`、`{year}`、`{text}`。
	- `content_db`：统一内容主库绝对路径。优先传入 `database/content/content.db`；旧 `references_db` 与 CSV 输入仅作兼容。
	- `insert_placeholders_from_references`：是否执行占位引文插入流程。
	- `reference_lines`：可手工提供参考文献行文本列表（用于无 LLM 场景下的调试）。

## 输出说明

- 以 `affair.json.interface.outputs` 与运行日志为准。
- 除精读笔记外，若启用了 `content_db`，还会更新统一内容主库中的文献主表。
