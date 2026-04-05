"""PDF 结构化要素抽取器（可选依赖）。

本模块提供一组“后处理抽取器”，用于在上游仅提供兜底全文时，进一步从 PDF 中抽取图片、表格、参考列表等结构化要素。

设计原则：
- 依赖尽量可选：未安装时应返回“禁用原因”，而不是让整条事务链路失败。
- 输出 JSON 友好：所有字段可直接被 `json.dumps` 序列化。
- 只做抽取：不在此处做路径绝对化（由调度层负责），但会要求调用方传入绝对路径。

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


_RAPIDOCR_ENGINE: Any | None = None


@dataclass(frozen=True)
class ExtractorStatus:
    """抽取器启用状态。

    Attributes:
        enabled: 是否启用。
        disabled_reason: 未启用原因（enabled=False 时填写）。
    """

    enabled: bool
    disabled_reason: str | None = None


def _require_absolute_file(path: Path, *, field_name: str) -> None:
    """校验路径为存在的绝对文件路径。"""

    if not path.is_absolute():
        raise ValueError(f"{field_name} 必须是绝对路径：{path}")
    if not path.exists() or not path.is_file():
        raise ValueError(f"{field_name} 必须是存在的文件：{path}")


def extract_images_with_pymupdf(
    pdf_path: Path,
    *,
    output_dir: Path,
    max_images: int | None = None,
) -> tuple[list[dict[str, Any]], ExtractorStatus]:
    """使用 PyMuPDF 从 PDF 抽取内嵌图片。

    Args:
        pdf_path: PDF 绝对路径。
        output_dir: 图片输出目录（绝对路径）。
        max_images: 可选，最多抽取图片数。None 表示不限制。

    Returns:
        tuple: (images, status)
            - images: 图片元素数组。
            - status: 抽取器状态。

    Notes:
        - PyMuPDF 返回的图像可能包含重复（同一图片在多页复用）。本实现按页遍历并逐一导出，便于追溯。
        - 对于扫描型 PDF，如果图像就是整页扫描图，通常也可以被抽取到。
    """

    _require_absolute_file(pdf_path, field_name="pdf_path")
    if not output_dir.is_absolute():
        raise ValueError(f"output_dir 必须是绝对路径：{output_dir}")

    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover
        return [], ExtractorStatus(enabled=False, disabled_reason=f"未安装 PyMuPDF（pymupdf）：{exc}")

    output_dir.mkdir(parents=True, exist_ok=True)

    images: list[dict[str, Any]] = []
    extracted = 0

    doc = fitz.open(str(pdf_path))
    try:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            img_list = page.get_images(full=True)
            for img_pos, img in enumerate(img_list):
                if max_images is not None and extracted >= max_images:
                    return images, ExtractorStatus(enabled=True)

                xref = img[0]
                try:
                    base = doc.extract_image(xref)
                except Exception:
                    # 关键逻辑说明：遇到异常图片（损坏/不支持编码）时，跳过而不是终止整份 PDF。
                    continue

                img_bytes = base.get("image")
                img_ext = str(base.get("ext") or "png").lower()

                # 文件名：<pdfstem>_p{page}_{n}.{ext}
                out_name = f"{pdf_path.stem}_p{page_index + 1}_{img_pos + 1}.{img_ext}"
                out_path = (output_dir / out_name)
                try:
                    out_path.write_bytes(img_bytes)
                except Exception:
                    continue

                images.append(
                    {
                        "page_index": int(page_index),
                        "page_number": int(page_index + 1),
                        "image_path": str(out_path),
                        "ext": img_ext,
                        "source": "pymupdf",
                        "xref": int(xref),
                    }
                )
                extracted += 1
    finally:
        doc.close()

    return images, ExtractorStatus(enabled=True)


def _truncate_reference_item(raw: str) -> str:
    """截断参考文献条目中的非参考后缀。"""

    text = (raw or "").strip()
    if not text:
        return ""

    stop_markers = ["［基金项目］", "[基金项目]", "基金项目", "［作者简介］", "[作者简介]", "作者简介", "（上接", "(上接"]
    stop_positions = [text.find(marker) for marker in stop_markers if text.find(marker) != -1]
    if stop_positions:
        text = text[: min(stop_positions)].strip()
    return text


def _split_reference_block_lines(ref_block: str) -> list[tuple[str, str]]:
    """把 references 文本块拆成逐条候选。

    Returns:
        列表元素为 (marker, raw_text)；marker 为空字符串表示无编号条目。
    """

    import re

    numbered_pattern = re.compile(r"(?:(?:\n|\r|\r\n)\s*|^)(\[\d+\]|［\d+］|\(\d+\)|（\d+）|\d+\s*[.、．])\s*")
    numbered_matches = list(numbered_pattern.finditer(ref_block))
    if numbered_matches:
        chunks: list[tuple[str, str]] = []
        for idx, match in enumerate(numbered_matches):
            start = match.end()
            end = numbered_matches[idx + 1].start() if idx + 1 < len(numbered_matches) else len(ref_block)
            raw = _truncate_reference_item(ref_block[start:end])
            if raw:
                chunks.append((match.group(1).strip(), raw))
        return chunks

    bullet_chunks: list[tuple[str, str]] = []
    current: list[str] = []
    for raw_line in ref_block.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith(("- ", "* ", "• ")):
            if current:
                candidate = _truncate_reference_item(" ".join(current))
                if candidate:
                    bullet_chunks.append(("", candidate))
            current = [stripped[2:].strip()]
            continue
        if current:
            current.append(stripped)
    if current:
        candidate = _truncate_reference_item(" ".join(current))
        if candidate:
            bullet_chunks.append(("", candidate))
    return bullet_chunks


def _get_rapidocr_engine() -> Any:
    """延迟加载 RapidOCR 引擎。"""

    global _RAPIDOCR_ENGINE
    if _RAPIDOCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        _RAPIDOCR_ENGINE = RapidOCR()
    return _RAPIDOCR_ENGINE


def extract_text_with_rapidocr(
    pdf_path: Path,
    *,
    dpi: int = 200,
    max_pages: int | None = None,
) -> tuple[str, ExtractorStatus, dict[str, Any]]:
    """使用 RapidOCR 对 PDF 页面渲染图做文字识别。

    Args:
        pdf_path: PDF 绝对路径。
        dpi: 页面渲染分辨率，越高越清晰但越慢。
        max_pages: 可选，最多处理页数。

    Returns:
        tuple: (text, status, meta)
            - text: 识别出的纯文本。
            - status: 抽取器状态。
            - meta: 识别过程元数据。
    """

    _require_absolute_file(pdf_path, field_name="pdf_path")

    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover
        return "", ExtractorStatus(enabled=False, disabled_reason=f"未安装 PyMuPDF（pymupdf）：{exc}"), {
            "backend": "rapidocr",
            "page_count": 0,
            "recognized_pages": 0,
            "ocr_error": f"未安装 PyMuPDF（pymupdf）：{exc}",
        }

    try:
        engine = _get_rapidocr_engine()
    except Exception as exc:  # pragma: no cover
        return "", ExtractorStatus(enabled=False, disabled_reason=f"未安装 RapidOCR：{exc}"), {
            "backend": "rapidocr",
            "page_count": 0,
            "recognized_pages": 0,
            "ocr_error": f"未安装 RapidOCR：{exc}",
        }

    doc = fitz.open(str(pdf_path))
    total_pages = int(doc.page_count)
    page_texts: list[str] = []
    recognized_pages = 0
    try:
        for page_index in range(total_pages):
            if max_pages is not None and page_index >= max_pages:
                break
            page = doc.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
            ocr_result = engine(pixmap.tobytes("png"))
            detections = ocr_result[0] if isinstance(ocr_result, tuple) and ocr_result else []
            page_lines: list[str] = []
            for item in detections or []:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                text = str(item[1] or "").strip()
                if text:
                    page_lines.append(text)
            if page_lines:
                recognized_pages += 1
                page_texts.append("\n".join(page_lines))
    finally:
        doc.close()

    full_text = "\n\n".join(page_texts).strip()
    meta = {
        "backend": "rapidocr",
        "dpi": int(dpi),
        "page_count": total_pages,
        "recognized_pages": int(recognized_pages),
    }
    if full_text:
        return full_text, ExtractorStatus(enabled=True), meta
    return "", ExtractorStatus(enabled=True, disabled_reason="OCR 已运行但未识别到可用文本"), {
        **meta,
        "ocr_error": "OCR 已运行但未识别到可用文本",
    }


def extract_references_from_full_text(
    full_text: str,
    *,
    max_items: int | None = 200,
) -> tuple[list[dict[str, Any]], ExtractorStatus]:
    """从全文文本中做规则参考列表抽取（最小可用版）。

    Args:
        full_text: PDF 的全文纯文本。
        max_items: 最多输出条目数。

    Returns:
        tuple: (references, status)

    Notes:
        - 该方法不依赖 PDF 版面结构，鲁棒但精度有限。
        - 先定位“参考文献/References”段落（常见写法），再按常见编号模式切分。
    """

    text = (full_text or "").strip()
    if not text:
        return [], ExtractorStatus(enabled=True, disabled_reason="全文为空，无法抽取参考列表")

    # 关键逻辑说明：长篇 PDF 中“参考文献/References”段落通常在文末，先从后往前找可减少误匹配。
    markers = ["参考文献", "References", "REFERENCES"]
    idx = -1
    for m in markers:
        idx = text.rfind(m)
        if idx != -1:
            break
    if idx == -1:
        return [], ExtractorStatus(enabled=True, disabled_reason="未在全文中定位到参考列表段落")

    ref_block = text[idx:]

    references: list[dict[str, Any]] = []
    chunks = _split_reference_block_lines(ref_block)
    if not chunks:
        references.append({"index": 1, "raw": ref_block.strip(), "source": "regex"})
        return references, ExtractorStatus(enabled=True)

    for item_idx, (marker, raw) in enumerate(chunks, start=1):
        item = {
            "index": int(item_idx),
            "raw": raw,
            "source": "regex",
        }
        if marker:
            item["marker"] = marker
        references.append(item)
        if max_items is not None and item_idx >= max_items:
            break

    return references, ExtractorStatus(enabled=True)

