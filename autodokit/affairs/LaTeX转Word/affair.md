# LaTeX转Word

## 用途

- 该事务用于执行 `LaTeX转Word` 对应的业务逻辑。

## 运行入口

- module: `autodokit.affairs.<affair_name>.affair`
- callable: `execute`
- pass_mode: `config_path`

## 参数说明

- 主要配置字段（均建议使用绝对路径）：
  - `input_tex_file`：输入 `tex` 文件。
  - `output_docx_file`：输出 `docx` 文件。
  - `merge_subfiles`：是否先展开 `\subfile{...}` 并合并。
  - `merged_tex_output`：可选，合并后 tex 输出路径。
  - `resource_path`：Pandoc 资源路径。
	- 可传目录；
	- 也可直接传 `.dotx/.docx`，将自动映射为 `--reference-doc`，同时其父目录仍参与 `--resource-path`。
  - `reference_doc`：可选，显式指定 Pandoc `--reference-doc`。
  - `include_in_header`：可选，Pandoc `--include-in-header`。
  - `drop_tex_elements`：可选字符串列表，按“标签块/label/章节名”过滤 tex 元素（如：`封面`、`致谢`、`原创声明`、`版权说明`）。
  - `toc`：是否生成目录。
  - `add_heading_numbering`：是否做标题编号后处理。
  - `highlight_tokens`：是否做 TODO/NOTE/文献高亮后处理。
  - `dry_run`：是否仅预览执行计划。
  - `output_log`：可选日志文件。

示例：

```json
{
  "input_tex_file": "/home/ethan/work/paper/main.tex",
  "output_docx_file": "/home/ethan/work/paper/output/paper.docx",
  "merge_subfiles": true,
  "resource_path": "/home/ethan/work/paper/templates/论文模板.dotx",
  "drop_tex_elements": ["封面", "致谢", "原创声明", "版权说明"],
  "toc": true
}
```

## 输出说明

- 以 `affair.json.interface.outputs` 与运行日志为准。
