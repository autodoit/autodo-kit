"""独立的 Pandoc LaTeX -> Word 工具包装模块。"""
from __future__ import annotations

from .latex_to_word import convert_latex_to_word
from .pandoc_runner import PandocResult

__all__ = ["PandocResult", "convert_latex_to_word"]
