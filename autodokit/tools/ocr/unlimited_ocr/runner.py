"""Unlimited-OCR 后处理统一入口：公式回填 + 表格修复一键链路。

对应「MonkeyOCR 布局 + 原生文字层文本」重建后的补丁管线：文本取自
原生文字层（100% 准确），仅公式与表格需要视觉 OCR 补齐。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from autodokit.tools.ocr.unlimited_ocr.equation_backfill import (
    fill_empty_equations,
)
from autodokit.tools.ocr.unlimited_ocr.table_repair import repair_invalid_tables

logger = logging.getLogger(__name__)

__all__ = ["run_unlimited_ocr_postprocess"]


def run_unlimited_ocr_postprocess(
    pdf_path: str | Path,
    middle_json_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    model_path: str | Path | None = None,
    fix_equations: bool = True,
    fix_tables: bool = True,
) -> Dict[str, Any]:
    """对一篇已重建的论文执行 Unlimited-OCR 后处理（公式 + 表格）。

    执行顺序：先回填空行间公式，再修复无效表格。两步各自独立备份
    （``*.before_eq_fill.json`` / ``*.before_table_fix.json``）。

    Args:
        pdf_path: 源 PDF 路径。
        middle_json_path: MonkeyOCR middle.json 路径（就地写回）。
        workspace_root: 宿主工程根目录（用于解析默认模型位置
            ``pypackage/model_weight/Unlimited-OCR-4bit``）。
        model_path: 可选的显式模型目录。
        fix_equations: 是否执行公式回填。
        fix_tables: 是否执行表格修复。

    Returns:
        ``{"status": "SUCCEEDED"|"NOOP", "equations": {...}|None,
        "tables": {...}|None}``。表格修复失败清单非空时，调用方应按
        ``failed[].reason`` 提示回退原生文字层确定性重建。

    Raises:
        ValueError: 两个开关同时关闭。

    Examples:
        >>> result = run_unlimited_ocr_postprocess(
        ...     "/path/paper.pdf", "/path/paper_dir/paper_middle.json",
        ...     workspace_root="/path/AcademicResearch-auto-workflow")
        >>> result["status"]
        'SUCCEEDED'
    """
    if not fix_equations and not fix_tables:
        raise ValueError("fix_equations 与 fix_tables 不能同时关闭")

    result: Dict[str, Any] = {"equations": None, "tables": None}

    if fix_equations:
        result["equations"] = fill_empty_equations(
            pdf_path, middle_json_path,
            workspace_root=workspace_root, model_path=model_path,
        )
    if fix_tables:
        result["tables"] = repair_invalid_tables(
            pdf_path, middle_json_path,
            workspace_root=workspace_root, model_path=model_path,
        )

    eq_done = (not fix_equations) or (
        result["equations"]["spans"] == result["equations"]["filled"]
        if result["equations"]["spans"] else True
    )
    tbl_done = (not fix_tables) or not result["tables"]["failed"]
    result["status"] = "SUCCEEDED" if (eq_done and tbl_done) else "PARTIAL"
    if result["status"] == "PARTIAL":
        logger.warning(
            "Unlimited-OCR 后处理存在未覆盖项，建议对失败区域回退原生文字层"
            "确定性重建；equations=%s tables_failed=%s",
            None if result["equations"] is None else result["equations"]["unfilled"],
            None if result["tables"] is None else result["tables"]["failed"],
        )
    return result
