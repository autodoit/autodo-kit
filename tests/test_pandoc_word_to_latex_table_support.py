"""Pandoc Word->LaTeX 表格兼容性测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autodokit.tools.pandoc_tex_word_converter import (
    PANDOC_TABLE_SUPPORT_MARKER,
    _ensure_pandoc_latex_table_support,
    _needs_pandoc_table_support,
)


class TestPandocWordToLatexTableSupport(unittest.TestCase):
    """测试 Pandoc 表格支持补丁。

    Args:
        无。

    Returns:
        None。

    Raises:
        AssertionError: 当断言失败时抛出。

    Examples:
        >>> case = TestPandocWordToLatexTableSupport()
        >>> isinstance(case, unittest.TestCase)
        True
    """

    def test_detect_longtable_markers(self) -> None:
        """检测到 Pandoc longtable 相关语法时应返回 True。"""

        tex_text = r"""
\documentclass{article}
\begin{document}
\begin{longtable}[]{@{} >{\centering\arraybackslash}p{(\linewidth - 2\tabcolsep) * \real{0.5}} @{} }
\toprule\noalign{}
A & B \\
\midrule\noalign{}
\endhead
x & y \\
\bottomrule\noalign{}
\end{longtable}
\end{document}
"""
        self.assertTrue(_needs_pandoc_table_support(tex_text))

    def test_patch_support_block_once(self) -> None:
        """补丁应插入一次且不重复插入。"""

        original_tex = r"""
\documentclass{article}
\usepackage{xeCJK}
\begin{document}
\begin{longtable}[]{@{} >{\centering\arraybackslash}p{(\linewidth - 2\tabcolsep) * \real{0.5}} @{} }
\toprule\noalign{}
A & B \\
\midrule\noalign{}
\endhead
x & y \\
\bottomrule\noalign{}
\end{longtable}
\end{document}
""".lstrip()

        with tempfile.TemporaryDirectory() as temp_dir:
            tex_path = Path(temp_dir) / "sample.tex"
            tex_path.write_text(original_tex, encoding="utf-8")

            _ensure_pandoc_latex_table_support(tex_path)
            patched_once = tex_path.read_text(encoding="utf-8")
            self.assertIn(PANDOC_TABLE_SUPPORT_MARKER, patched_once)
            self.assertEqual(patched_once.count(PANDOC_TABLE_SUPPORT_MARKER), 1)
            self.assertIn(r"\usepackage{longtable}", patched_once)
            self.assertIn(r"\usepackage{booktabs}", patched_once)
            self.assertIn(r"\usepackage{array}", patched_once)
            self.assertIn(r"\usepackage{calc}", patched_once)
            self.assertIn(r"\begin{document}", patched_once)

            _ensure_pandoc_latex_table_support(tex_path)
            patched_twice = tex_path.read_text(encoding="utf-8")
            self.assertEqual(patched_twice.count(PANDOC_TABLE_SUPPORT_MARKER), 1)


if __name__ == "__main__":
    unittest.main()

