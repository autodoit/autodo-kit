"""Unlimited-OCR 输出质量门控与文本规整。

Unlimited-OCR（百度，DeepSeek-OCR 衍生）在超大/密集重复内容上会出现退化
循环（如 LaTeX array 列说明符 'c c c…' 重复）或空输出；本模块提供统一的
退化判定与 LaTeX 规整工具，供回填链路做质量门控。
"""

from __future__ import annotations

import re

__all__ = [
    "clean_latex",
    "is_degenerate",
    "is_valid_latex",
    "is_valid_table_html",
]


def clean_latex(text: str) -> str:
    """规整公式文本：去掉 ``\\[ \\]`` / ``\\( \\)`` 包裹，压成单行。

    保留 ``\\tag`` 编号与内部结构。

    Args:
        text: 模型输出的原始公式文本。

    Returns:
        压成单行、去掉外层定界符的公式字符串。

    Examples:
        >>> clean_latex("\\\\[\\nE = mc^2\\\\tag{1}\\n\\\\]")
        'E = mc^2\\\\tag{1}'
    """
    text = re.sub(r"^\s*\\\[", "", text.strip())
    text = re.sub(r"\\\]\s*$", "", text)
    text = re.sub(r"^\s*\\\(", "", text.strip())
    text = re.sub(r"\\\)\s*$", "", text)
    return " ".join(ln.strip() for ln in text.split("\n") if ln.strip())


def is_degenerate(text: str, limit: int = 3000, run_threshold: int = 15) -> bool:
    """判定输出是否为退化产物。

    退化特征（命中任一即判退化）：
    1. 超长输出（默认 >3000 字符，通常为截断前的循环堆积）；
    2. 混入 HTML 表格标签循环（``<td>``/``<table>``）；
    3. 存在连续相同 token 长游程（如 ``c c c c…`` 列说明符循环）。

    注意：合法矩阵本身含大量重复集合（如 ``{s_0^3, s_1^3}`` 在多行出现），
    不能用全局重复率判定，必须用连续游程判定。

    Args:
        text: 待判定文本。
        limit: 长度上限（字符）。
        run_threshold: 连续相同 token 的游程阈值。

    Returns:
        True 表示内容退化，应拒绝使用。

    Examples:
        >>> is_degenerate(" ".join(["c"] * 50))
        True
        >>> is_degenerate(r"\\left[ \\begin{array}{cc} 1 & 2 \\\\ 3 & 4 \\end{array} \\right]")
        False
    """
    if len(text) > limit:
        return True
    if "<td>" in text or "<table>" in text:
        return True
    tokens = text.split()
    run = 1
    for a, b in zip(tokens, tokens[1:]):
        run = run + 1 if a == b else 1
        if run >= run_threshold:
            return True
    return False


def is_valid_latex(text: str, min_core_chars: int = 3) -> bool:
    """公式质量门控：拒绝纯空格/反斜杠/单字符等无效结果。

    Args:
        text: 待判定公式文本。
        min_core_chars: 去掉反斜杠与空格后的最少字符数。

    Returns:
        True 表示公式内容有效。

    Examples:
        >>> is_valid_latex("c")
        False
        >>> is_valid_latex(r"E = mc^2")
        True
    """
    core = text.replace("\\", "").replace(" ", "")
    return len(core) >= min_core_chars


def is_valid_table_html(html: str) -> bool:
    """判定表格产物是否为有效表格（而非退化物）。

    有效标准：非空且以 ``<table`` 开头，或以 ``|`` 开头的 Markdown 表格
    （如确定性重建产物）。

    Args:
        html: 表格内容（HTML 或 Markdown 行）。

    Returns:
        True 表示内容可作为表格使用。
    """
    if not html or not html.strip():
        return False
    stripped = html.strip()
    return stripped.lower().startswith("<table") or stripped.startswith("|")
