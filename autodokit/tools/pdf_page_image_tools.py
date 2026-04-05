"""PDF 页图与区域裁剪工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence


def _require_absolute_file(path: Path, *, field_name: str) -> None:
    if not path.is_absolute():
        raise ValueError(f"{field_name} 必须是绝对路径：{path}")
    if not path.exists() or not path.is_file():
        raise ValueError(f"{field_name} 必须是存在的文件：{path}")


def render_pdf_pages_to_png(
    pdf_path: Path,
    *,
    output_dir: Path,
    dpi: int = 180,
    max_pages: int | None = None,
) -> List[Dict[str, Any]]:
    """把 PDF 渲染为逐页 PNG。"""

    _require_absolute_file(pdf_path, field_name="pdf_path")
    if not output_dir.is_absolute():
        raise ValueError(f"output_dir 必须是绝对路径：{output_dir}")

    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("未安装 PyMuPDF（pymupdf），无法渲染页图。") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    document = fitz.open(str(pdf_path))
    try:
        for page_index in range(document.page_count):
            if max_pages is not None and page_index >= max_pages:
                break
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
            image_path = (output_dir / f"page_{page_index + 1:04d}.png").resolve()
            pixmap.save(str(image_path))
            rows.append(
                {
                    "page_index": int(page_index),
                    "page_number": int(page_index + 1),
                    "image_path": str(image_path),
                    "width": int(pixmap.width),
                    "height": int(pixmap.height),
                    "text": str(page.get_text("text") or "").strip(),
                    "source": "pymupdf_page_raster",
                }
            )
    finally:
        document.close()
    return rows


def crop_image_by_normalized_bbox(
    image_path: Path,
    *,
    output_path: Path,
    bbox: Sequence[float] | Sequence[int],
) -> bool:
    """按 0-1000 归一化 bbox 从页图裁剪区域。"""

    _require_absolute_file(image_path, field_name="image_path")
    if not output_path.is_absolute():
        raise ValueError(f"output_path 必须是绝对路径：{output_path}")
    if len(list(bbox)) != 4:
        return False

    try:
        from PIL import Image  # type: ignore
    except Exception:
        return False

    with Image.open(image_path) as img:
        width, height = img.size
        x1, y1, x2, y2 = [float(v) for v in bbox]
        left = max(0, min(width, round(width * x1 / 1000.0)))
        top = max(0, min(height, round(height * y1 / 1000.0)))
        right = max(0, min(width, round(width * x2 / 1000.0)))
        bottom = max(0, min(height, round(height * y2 / 1000.0)))
        if right <= left or bottom <= top:
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.crop((left, top, right, bottom)).save(output_path)
    return True