# autodo-kit: Math Delimiter Conversion Utility

快速说明：将文档中常见的 Markdown/LaTeX 数学定界符从 `$...$` / `$$...$$` 转换为 TeX 推荐的 `\(...\)` / `\[...\]`，并跳过代码/verbaitm 等环境。

快速使用：

- 作为命令行工具（安装后提供 `math-delimiters` 命令）：

  ```bash
  math-delimiters \
    --input-dir "C:\\path\\to\\texfiles" \
    --input-file myfile.tex \
    --dry-run
  ```

- 作为库调用：

  ```python
  from autodokit.tools.math_delimiter_converter import convert_text, process_file

  new_text, inline_count, display_count, examples = convert_text(old_text)
  process_file('in.tex', 'out.tex', backup=True, dry_run=False)
  ```

文件位置：包位于 `autodo-kit/autodo_kit/`，文档位于 `autodo-kit/docs/`。
