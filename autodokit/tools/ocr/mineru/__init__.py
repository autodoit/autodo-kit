"""MinerU-based tools — 文档解析结构化转换器。

本包把 MinerU 作为与 MonkeyOCR 并列的完整文档解析工具后端接入 AOK：

- ``mineru_runner``：MinerU CLI 运行封装（后端选择、输出文件发现）。
- ``pdf_to_structure_data_converter_use_mineru``：把 MinerU 输出统一转成
  ``aok.pdf_structured.v3`` 结构化结果，供事务层与既有 consumers 直接复用。
"""

from __future__ import annotations

from autodokit.tools.ocr.mineru.mineru_runner import (
    DEFAULT_MINERU_BACKEND,
    DEFAULT_MINERU_EFFORT,
    discover_mineru_output_files,
    resolve_mineru_cli,
    run_mineru_single_pdf,
)
from autodokit.tools.ocr.mineru.pdf_to_structure_data_converter_use_mineru import (
    PdfToStructuredDataResult,
    convert_pdf_to_structured_data,
    convert_pdf_to_structured_data_file,
)

__all__ = [
    # ── CLI 运行 ──
    "resolve_mineru_cli",
    "run_mineru_single_pdf",
    "discover_mineru_output_files",
    # ── 结构化转换 ──
    "PdfToStructuredDataResult",
    "convert_pdf_to_structured_data",
    "convert_pdf_to_structured_data_file",
    # ── 常量 ──
    "DEFAULT_MINERU_BACKEND",
    "DEFAULT_MINERU_EFFORT",
]
