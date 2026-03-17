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

    import re

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

    # 常见编号：1. / 1、/ [1] / (1)
    pattern = re.compile(r"(?:\n|\r|\r\n)\s*(\[\d+]\s*|\(\d+\)\s*|\d+\s*[.、])")
    parts = pattern.split(ref_block)

    # split 结果形如： [header_text, marker1, item1, marker2, item2, ...]
    references: list[dict[str, Any]] = []
    if len(parts) <= 2:
        # 没切开就直接整段作为一个条目返回
        references.append({"index": 1, "raw": ref_block.strip(), "source": "regex"})
        return references, ExtractorStatus(enabled=True)

    it = iter(parts[1:])
    item_idx = 0
    for marker, item in zip(it, it):
        raw = (item or "").strip()
        if not raw:
            continue
        item_idx += 1
        references.append(
            {
                "index": int(item_idx),
                "marker": marker.strip(),
                "raw": raw,
                "source": "regex",
            }
        )
        if max_items is not None and item_idx >= max_items:
            break

    return references, ExtractorStatus(enabled=True)

