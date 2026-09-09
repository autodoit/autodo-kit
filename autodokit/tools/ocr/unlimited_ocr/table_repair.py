"""用 Unlimited-OCR 修复 middle.json 中无效（退化/为空）的表格。

MonkeyOCR MLX 后端的 VLM 退化常把表格产物写成重复循环垃圾（如
``H9H9H9…``）；本工具按表格 bbox 裁剪渲染（减少视觉 token、放大细节）
后送 Unlimited-OCR 重新识别，提取 ``<table>…</table>`` 写回
``table_body`` span 的 ``html`` 字段。仅替换当前无效的表格，不覆盖有效内容。

已知边界：超大表格（输出超过 ``max_tokens``）或密集重复矩阵（LaTeX
array）仍可能退化或空输出；此时应回退到原生文字层做确定性重建，
而不是无限重试。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from autodokit.tools.ocr.unlimited_ocr.quality_gates import is_valid_table_html

logger = logging.getLogger(__name__)

__all__ = ["repair_invalid_tables"]

_TABLE_RE = re.compile(r"<table>.*?</table>", re.S | re.I)


def _table_body_spans(para: Dict[str, Any]) -> List[Dict[str, Any]]:
    """取 table 块下 table_body 的全部 span。"""
    return [
        sp
        for blk in para.get("blocks", [])
        if blk.get("type") == "table_body"
        for ln in blk.get("lines", [])
        for sp in ln.get("spans", [])
    ]


def repair_invalid_tables(
    pdf_path: str | Path,
    middle_json_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    model_path: str | Path | None = None,
    render_width: int = 1600,
    crop_padding: float = 4.0,
    max_tokens: int = 32768,
    backup_suffix: str | None = ".before_table_fix",
    page_filter: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """修复 middle.json 中无效的表格并写回。

    Args:
        pdf_path: 源 PDF 路径。
        middle_json_path: MonkeyOCR middle.json 路径（就地写回）。
        workspace_root: 宿主工程根目录（用于解析默认模型位置）。
        model_path: 可选的显式模型目录。
        render_width: 裁剪区渲染宽度（像素）。
        crop_padding: 裁剪外扩（PDF 点）。
        max_tokens: 单表格输出 token 上限。
        backup_suffix: 写回前的备份后缀；None 表示不备份。
        page_filter: 可选，仅处理这些页码（0 基）。

    Returns:
        统计字典：``{tables, repaired, failed: [{page, bbox, reason}]}``。

    Raises:
        ImportError: 缺少 mlx-vlm / pymupdf。
        FileNotFoundError: PDF 或 middle.json 不存在。

    Examples:
        >>> stats = repair_invalid_tables(
        ...     "/path/paper.pdf", "/path/paper_dir/paper_middle.json",
        ...     workspace_root="/path/AcademicResearch-auto-workflow")
        >>> stats["failed"]  # 仍失败者需回退文字层确定性重建
        []
    """
    import fitz  # pymupdf

    from autodokit.tools.ocr.unlimited_ocr.unlimited_ocr_engine import (
        load_unlimited_ocr_model,
        ocr_image,
    )

    pdf_path = Path(pdf_path).expanduser().resolve()
    middle_json_path = Path(middle_json_path).expanduser().resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    if not middle_json_path.exists():
        raise FileNotFoundError(middle_json_path)

    middle = json.loads(middle_json_path.read_text(encoding="utf-8"))
    doc = fitz.open(str(pdf_path))
    model, processor = load_unlimited_ocr_model(workspace_root, model_path)

    stats: Dict[str, Any] = {"tables": 0, "repaired": 0, "failed": []}

    for pidx, page_info in enumerate(middle.get("pdf_info", [])):
        if page_filter is not None and pidx not in page_filter:
            continue
        for para in page_info.get("para_blocks", []):
            if para.get("type") != "table":
                continue
            spans = _table_body_spans(para)
            if not spans:
                continue
            current = spans[0].get("html") or ""
            if is_valid_table_html(current):
                continue  # 仅修复无效表格

            stats["tables"] += 1
            bbox = para.get("bbox")
            if not bbox:
                stats["failed"].append(
                    {"page": pidx, "bbox": None, "reason": "no_bbox"}
                )
                continue

            x0, y0, x1, y1 = bbox
            clip = fitz.Rect(
                x0 - crop_padding, y0 - crop_padding,
                x1 + crop_padding, y1 + crop_padding,
            )
            zoom = render_width / clip.width
            pix = doc[pidx].get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
            img_path = middle_json_path.parent / f"{middle_json_path.stem}_tabfix_p{pidx:02d}.png"
            pix.save(str(img_path))
            try:
                raw = ocr_image(model, processor, img_path, max_tokens=max_tokens)
            finally:
                img_path.unlink(missing_ok=True)

            tables = _TABLE_RE.findall(raw)
            if tables:
                for sp in spans:
                    sp["html"] = tables[0]
                stats["repaired"] += 1
                logger.info("[table-fix] page %d: repaired (%d chars)", pidx, len(tables[0]))
            else:
                stats["failed"].append({
                    "page": pidx, "bbox": bbox,
                    "reason": "no_table_in_output（疑似退化/截断，建议文字层重建）",
                })
                logger.warning("[table-fix] page %d: no table in output (%d chars)", pidx, len(raw))

    if stats["repaired"]:
        if backup_suffix:
            backup = middle_json_path.with_name(
                middle_json_path.stem + backup_suffix + middle_json_path.suffix
            )
            if not backup.exists():
                shutil.copy2(middle_json_path, backup)
        middle_json_path.write_text(
            json.dumps(middle, ensure_ascii=False), encoding="utf-8"
        )
    return stats
