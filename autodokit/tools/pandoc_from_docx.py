"""独立的 Pandoc Word -> LaTeX 工具包装模块。"""
from __future__ import annotations

from .pandoc_runner import PandocResult
from .word_to_latex import convert_word_to_latex

__all__ = ["PandocResult", "convert_word_to_latex"]
