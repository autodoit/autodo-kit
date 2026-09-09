"""Unlimited-OCR (mlx-vlm) 工具包：Apple Silicon 本地文档 OCR 补丁链路。

定位：作为「MonkeyOCR 布局 + 原生文字层文本」主链的补丁层——
数字原生 PDF 的文本取自原生文字层（100% 准确），仅公式与表格由
Unlimited-OCR 视觉识别补齐。

模块分工：
- ``unlimited_ocr_engine``: 模型加载、单页推理、检测解析、归一化坐标匹配
- ``quality_gates``: 退化判定与 LaTeX/表格质量门控
- ``equation_backfill``: 回填 middle.json 中为空的行间公式
- ``table_repair``: 修复 middle.json 中无效的表格
- ``runner``: ``run_unlimited_ocr_postprocess`` 一键链路

模型权重规范：默认位于宿主工程 ``pypackage/model_weight/Unlimited-OCR-4bit``，
可用 ``workspace_root`` 自动解析，或用 ``model_path`` 显式指定。
"""

from autodokit.tools.ocr.unlimited_ocr.equation_backfill import (
    fill_empty_equations,
)
from autodokit.tools.ocr.unlimited_ocr.quality_gates import (
    clean_latex,
    is_degenerate,
    is_valid_latex,
    is_valid_table_html,
)
from autodokit.tools.ocr.unlimited_ocr.runner import run_unlimited_ocr_postprocess
from autodokit.tools.ocr.unlimited_ocr.table_repair import repair_invalid_tables
from autodokit.tools.ocr.unlimited_ocr.unlimited_ocr_engine import (
    load_unlimited_ocr_model,
    match_by_normalized_y,
    normalize_det_y,
    normalize_source_y,
    ocr_image,
    parse_detections,
    resolve_unlimited_ocr_model_path,
)

__all__ = [
    "clean_latex",
    "fill_empty_equations",
    "is_degenerate",
    "is_valid_latex",
    "is_valid_table_html",
    "load_unlimited_ocr_model",
    "match_by_normalized_y",
    "normalize_det_y",
    "normalize_source_y",
    "ocr_image",
    "parse_detections",
    "repair_invalid_tables",
    "resolve_unlimited_ocr_model_path",
    "run_unlimited_ocr_postprocess",
]
