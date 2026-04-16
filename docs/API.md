# API 文档

导出函数：

- `convert_text(tex: str) -> Tuple[str, int, int, List[Tuple[str,str,str]]]`：
  - 描述：将输入字符串中的行内和展示数学定界符进行替换，返回（新文本，行内替换数，展示替换数，示例替换列表）。

- `process_file(input_path: str, output_path: str, backup: bool=True, dry_run: bool=False) -> None`：
  - 描述：处理单个文件，支持备份与 dry-run 模式；会打印处理摘要。

- `collect_unescaped_dollar_lines(tex: str, max_items: int=20) -> Tuple[int, List[Tuple[int,str]]]`：
  - 描述：用于检查文本中剩余未转义的 `$`，返回计数与行示例，便于定位问题。

- `build_skip_ranges(tex: str) -> List[Tuple[int,int]]`：
  - 描述：内部工具，返回需跳过替换的区间（如 verbatim、已存在的 `\\(...\\)`/`\\[...\\]`）。

示例：见 `docs/README.md`。如需将此包发布到 PyPI 或添加 CLI 参数增强（并发、目录批量处理等），可以继续扩展。
