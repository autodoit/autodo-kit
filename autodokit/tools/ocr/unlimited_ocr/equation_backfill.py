"""用 Unlimited-OCR 回填 MonkeyOCR middle.json 中为空的行间公式。

典型场景：数字原生（LaTeX 生成）PDF 用「MonkeyOCR 布局 + 原生文字层文本」
重建后，行间公式区域在文字层中无法取到可读文本，需要 OCR 视觉模型补出
LaTeX。本工具只补空的 ``interline_equation`` span，不覆盖已有内容。

坐标系约定（实测）：Unlimited-OCR 检测坐标为归一化×1000 坐标系，匹配
只按归一化 y 最近邻（见 ``unlimited_ocr_engine.match_by_normalized_y``）。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from autodokit.tools.ocr.unlimited_ocr.quality_gates import (
    clean_latex,
    is_degenerate,
    is_valid_latex,
)
from autodokit.tools.ocr.unlimited_ocr.unlimited_ocr_engine import (
    match_by_normalized_y,
    parse_detections,
)

logger = logging.getLogger(__name__)

__all__ = ["fill_empty_equations"]


def _collect_empty_equation_spans(page_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """收集一页内所有内容为空的行间公式 span。"""
    spans = []
    for para in page_info.get("para_blocks", []):
        for line in para.get("lines", []):
            for span in line.get("spans", []):
                if span.get("type") == "interline_equation" \
                        and not (span.get("content") or "").strip():
                    spans.append(span)
    return spans


def fill_empty_equations(
    pdf_path: str | Path,
    middle_json_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    model_path: str | Path | None = None,
    render_width: int = 1024,
    max_tokens: int = 8192,
    match_threshold: float = 0.05,
    backup_suffix: str | None = ".before_eq_fill",
    page_filter: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """回填 middle.json 中为空的行间公式并写回。

    流程：对每个含空公式的页面，按 ``render_width`` 渲染整页为位图送
    Unlimited-OCR；解析 equation 检测；按归一化 y 最近邻匹配空公式；
    经质量门控（有效且非退化）后写回 ``span.content``。

    Args:
        pdf_path: 源 PDF 路径。
        middle_json_path: MonkeyOCR middle.json 路径（就地写回）。
        workspace_root: 宿主工程根目录（用于解析默认模型位置）。
        model_path: 可选的显式模型目录。
        render_width: 渲染宽度（像素）。
        max_tokens: 单页输出 token 上限。
        match_threshold: 归一化 y 匹配阈值。
        backup_suffix: 写回前的备份后缀；None 表示不备份
            （备份名取首个执行时的状态）。
        page_filter: 可选，仅处理这些页码（0 基）。

    Returns:
        统计字典：``{pages, spans, filled, unfilled: [{page, bbox}]}``。

    Raises:
        ImportError: 缺少 mlx-vlm / pymupdf。
        FileNotFoundError: PDF 或 middle.json 不存在。

    Examples:
        >>> stats = fill_empty_equations(
        ...     "/path/paper.pdf", "/path/paper_dir/paper_middle.json",
        ...     workspace_root="/path/AcademicResearch-auto-workflow")
        >>> stats["spans"] == stats["filled"]  # 全部回填成功
        True
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

    stats: Dict[str, Any] = {"pages": 0, "spans": 0, "filled": 0, "unfilled": []}

    for pidx, page_info in enumerate(middle.get("pdf_info", [])):
        if page_filter is not None and pidx not in page_filter:
            continue
        empty_spans = _collect_empty_equation_spans(page_info)
        if not empty_spans:
            continue

        stats["pages"] += 1
        page_rect = doc[pidx].rect
        zoom = render_width / page_rect.width
        pix = doc[pidx].get_pixmap(matrix=fitz.Matrix(zoom, zoom))

        img_path = Path(f"{middle_json_path.parent}/{middle_json_path.stem}_eqfill_p{pidx:02d}.png")
        pix.save(str(img_path))
        try:
            raw = ocr_image(model, processor, img_path, max_tokens=max_tokens)
        finally:
            img_path.unlink(missing_ok=True)

        eq_dets = [d for d in parse_detections(raw) if d["type"] == "equation"]
        mapping = match_by_normalized_y(
            [sp.get("bbox") or [0, 0, 0, 0] for sp in empty_spans],
            [d["box"] for d in eq_dets],
            page_rect.height,
            threshold=match_threshold,
        )

        for span_idx, det_idx in mapping.items():
            stats["spans"] += 1
            latex = clean_latex(eq_dets[det_idx]["content"])
            if latex and is_valid_latex(latex) and not is_degenerate(latex):
                empty_spans[span_idx]["content"] = latex
                stats["filled"] += 1
            else:
                stats["unfilled"].append({
                    "page": pidx, "bbox": empty_spans[span_idx].get("bbox"),
                    "reason": "degenerate_or_invalid",
                })
        for i, sp in enumerate(empty_spans):
            if i not in mapping:
                stats["spans"] += 1
                stats["unfilled"].append({
                    "page": pidx, "bbox": sp.get("bbox"), "reason": "unmatched",
                })
        logger.info(
            "[eq-fill] page %d: empty=%d dets=%d matched=%d filled=%d",
            pidx, len(empty_spans), len(eq_dets), len(mapping),
            stats["filled"],
        )

    if stats["filled"] or stats["spans"]:
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
