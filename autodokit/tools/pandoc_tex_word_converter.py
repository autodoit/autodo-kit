"""TeX 与 Word 双向转换兼容入口。

说明：
- 该模块保留原有导入路径，避免外部调用中断。
- 实际实现已拆分为 5 个原子模块：
  1) `latex_subfile_merger.py`
  2) `pandoc_runner.py`
  3) `latex_to_word.py`
  4) `word_to_latex.py`
  5) `docx_postprocess.py`
"""

from __future__ import annotations

from .docx_postprocess import add_heading_numbering, highlight_tokens_in_docx
from .latex_subfile_merger import merge_latex_subfiles
from .latex_to_word import convert_latex_to_word
from .pandoc_runner import PandocResult, run_pandoc
from .word_to_latex import (
    DEFAULT_XELATEX_LATEX_TEMPLATE,
    PANDOC_TABLE_SUPPORT_BLOCK,
    PANDOC_TABLE_SUPPORT_MARKER,
    _ensure_pandoc_latex_table_support,
    _needs_pandoc_table_support,
    convert_word_to_latex,
)

__all__ = [
    "PandocResult",
    "DEFAULT_XELATEX_LATEX_TEMPLATE",
    "PANDOC_TABLE_SUPPORT_MARKER",
    "PANDOC_TABLE_SUPPORT_BLOCK",
    "merge_latex_subfiles",
    "run_pandoc",
    "convert_latex_to_word",
    "convert_word_to_latex",
    "add_heading_numbering",
    "highlight_tokens_in_docx",
    "_needs_pandoc_table_support",
    "_ensure_pandoc_latex_table_support",
]
