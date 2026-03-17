"""PDF 转结构化数据：本地流水线 v2（不依赖 BabelDOC）。

本模块实现“方案 2：常规转换”的本地流水线：
- 优先使用 PyMuPDF（fitz）做文本块提取（可带 bbox）与图片导出；
- 若缺失 PyMuPDF，则降级为 pdfminer.six 做全文提取；
- 参考文献抽取使用规则方法；
- 表格/公式/版面检测/OCR 目前仅做占位与 capability 记录（后续可插拔扩展）。

约定：
- 所有传入路径必须是绝对路径（由调度层预处理）。
- 本模块只使用本地可选依赖，不做网络调用。

"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from autodokit.tools.pdf_elements_extractors import (
    extract_images_with_pymupdf,
    extract_references_from_full_text,
)


@dataclass(frozen=True)
class PdfToStructuredDataResult:
    """PDF 转结构化数据结果。

    Attributes:
        structured_data: 结构化数据（可序列化为 JSON）。
        source_pdf_path: 源 PDF 绝对路径。
        converter: 转换器标识。
    """

    structured_data: Dict[str, Any]  # 结构化数据
    source_pdf_path: Path  # 源 PDF 绝对路径
    converter: str  # 转换器标识


def _cap(enabled: bool, disabled_reason: str | None = None) -> Dict[str, Any]:
    """构造 capabilities 的统一记录。"""

    return {
        "enabled": bool(enabled),
        "disabled_reason": disabled_reason,
    }


def _extract_text_fulltext_local(pdf_path: Path) -> tuple[str, str | None, Dict[str, Any]]:
    """抽取全文文本。

    优先策略：
    1) PyMuPDF：按 blocks 抽取文本并拼接（可扩展为保留 bbox 的 layout elements）。
    2) pdfminer.six：仅全文。

    Args:
        pdf_path: PDF 绝对路径。

    Returns:
        tuple: (full_text, extract_error, text_meta)
    """

    # 先尝试 PyMuPDF
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        parts: list[str] = []
        for page_index in range(len(doc)):
            page = doc[page_index]
            blocks = page.get_text("blocks")
            for b in blocks:
                text = b[4]
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        return "\n".join(parts), None, {"backend": "pymupdf"}
    except Exception as exc:
        pymupdf_err = str(exc)

    # 再尝试 pdfminer.six
    try:
        from pdfminer.high_level import extract_text  # type: ignore

        return extract_text(str(pdf_path)), None, {"backend": "pdfminer"}
    except Exception as exc:
        return "", f"PyMuPDF 失败：{pymupdf_err}；pdfminer 失败：{exc}", {"backend": "none"}


def convert_pdf_to_structured_data(
    pdf_path: Path,
    *,
    extractors: Optional[Dict[str, Any]] = None,
) -> PdfToStructuredDataResult:
    """把单个 PDF 转为结构化数据（本地流水线 v2）。

    Args:
        pdf_path: PDF 文件绝对路径。
        extractors: 抽取器开关（可选）。示例：
            - enable_images: bool
            - enable_references: bool
            - enable_tables: bool（占位）
            - enable_formulas: bool（占位）
            - enable_layout: bool（占位）
            - enable_ocr: bool（占位）

    Returns:
        PdfToStructuredDataResult: 转换结果。

    Raises:
        ValueError: pdf_path 非绝对路径或不存在。
    """

    if not isinstance(pdf_path, Path):
        pdf_path = Path(str(pdf_path))

    if not pdf_path.is_absolute():
        raise ValueError(
            "pdf_path 必须是绝对路径（应由调度层预处理为绝对路径）。"
            f"当前值={str(pdf_path)!r}"
        )

    if not pdf_path.exists():
        raise ValueError(f"PDF 文件不存在：{pdf_path}")

    ext_cfg: Dict[str, Any] = dict(extractors or {})
    enable_images = bool(ext_cfg.get("enable_images", True))
    enable_references = bool(ext_cfg.get("enable_references", True))

    # 预留：未来迭代
    enable_tables = bool(ext_cfg.get("enable_tables", False))
    enable_formulas = bool(ext_cfg.get("enable_formulas", False))
    enable_layout = bool(ext_cfg.get("enable_layout", False))
    enable_ocr = bool(ext_cfg.get("enable_ocr", False))

    full_text, extract_error, text_meta = _extract_text_fulltext_local(pdf_path)

    structured: Dict[str, Any] = {
        "schema": "aok.pdf_structured.v2",
        "source": {"pdf_name": pdf_path.name, "pdf_abs_path": str(pdf_path)},
        "text": {
            "full_text": full_text,
            "extract_error": extract_error,
            "meta": text_meta,
        },
        "images": [],
        "tables": [],
        "formulas": [],
        "references": [],
        "layout": {
            "coord_system": "unknown",
            "pages": [],
            "elements": [],
            "sources": [],
            "parse_error": None,
        },
        "capabilities": {
            "text": _cap(enabled=(extract_error is None), disabled_reason=extract_error),
            "images": _cap(enabled=False, disabled_reason="未执行"),
            "tables": _cap(enabled=False, disabled_reason="占位：未实现"),
            "formulas": _cap(enabled=False, disabled_reason="占位：未实现"),
            "layout": _cap(enabled=False, disabled_reason="占位：未实现"),
            "ocr": _cap(enabled=False, disabled_reason="占位：未实现"),
            "references": _cap(enabled=False, disabled_reason="未执行"),
        },
        "artifacts": {},
        "local_pipeline": {
            "version": "v2",
            "extractors": {
                "enable_images": enable_images,
                "enable_references": enable_references,
                "enable_tables": enable_tables,
                "enable_formulas": enable_formulas,
                "enable_layout": enable_layout,
                "enable_ocr": enable_ocr,
            },
        },
    }

    # 图片抽取（可选依赖：PyMuPDF）
    if enable_images:
        artifacts_root = pdf_path.parent / ".artifacts"  # 仅作为默认兜底，不承诺调度层会用该路径
        # 关键逻辑说明：convert 函数只负责生成结构化数据，不应决定最终落盘目录。
        # 这里将实际落盘目录交由 file 级函数设置。此处使用临时目录策略。

    # 实际图片落盘由 convert_pdf_to_structured_data_file 决定

    # 参考文献抽取
    if enable_references:
        refs, ref_status = extract_references_from_full_text(full_text)
        structured["references"] = refs
        structured["capabilities"]["references"] = _cap(
            enabled=bool(ref_status.enabled),
            disabled_reason=ref_status.disabled_reason,
        )

    # 占位 capability
    structured["capabilities"]["tables"] = _cap(enabled=False, disabled_reason="占位：本地表格抽取未实现")
    structured["capabilities"]["formulas"] = _cap(enabled=False, disabled_reason="占位：本地公式抽取未实现")
    structured["capabilities"]["layout"] = _cap(enabled=False, disabled_reason="占位：版面检测未实现")
    structured["capabilities"]["ocr"] = _cap(enabled=False, disabled_reason="占位：OCR 未实现")

    return PdfToStructuredDataResult(
        structured_data=structured,
        source_pdf_path=pdf_path,
        converter="local_pipeline_v2",
    )


def convert_pdf_to_structured_data_file(
    pdf_path: Path,
    output_path: Path,
    *,
    extractors: Optional[Dict[str, Any]] = None,
    artifacts_dir: Optional[Path] = None,
    encoding: str = "utf-8",
) -> Path:
    """把单个 PDF 转为结构化数据文件（JSON），并按需落盘产物。

    Args:
        pdf_path: PDF 绝对路径。
        output_path: 输出 JSON 绝对路径。
        extractors: 抽取器开关。
        artifacts_dir: 产物落盘目录（绝对路径）。如果不提供，则使用 `output_path.parent/artifacts/<pdf_stem>`。
        encoding: 输出编码。

    Returns:
        Path: 写出的 JSON 文件路径。

    Raises:
        ValueError: 输入/输出路径非绝对路径。
    """

    if not pdf_path.is_absolute():
        raise ValueError(f"pdf_path 必须是绝对路径：{pdf_path}")
    if not output_path.is_absolute():
        raise ValueError(f"output_path 必须是绝对路径：{output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if artifacts_dir is None:
        artifacts_dir = (output_path.parent / "artifacts" / pdf_path.stem).resolve()

    if not artifacts_dir.is_absolute():
        raise ValueError(f"artifacts_dir 必须是绝对路径：{artifacts_dir}")

    artifacts_dir.mkdir(parents=True, exist_ok=True)

    result = convert_pdf_to_structured_data(pdf_path, extractors=extractors)

    # 图片抽取（真正落盘的位置在这里确定）
    ext_cfg: Dict[str, Any] = dict(extractors or {})
    enable_images = bool(ext_cfg.get("enable_images", True))
    if enable_images:
        images_dir = (artifacts_dir / "images").resolve()
        images, img_status = extract_images_with_pymupdf(pdf_path, output_dir=images_dir)
        result.structured_data["images"] = images
        result.structured_data["capabilities"]["images"] = _cap(
            enabled=bool(img_status.enabled),
            disabled_reason=img_status.disabled_reason,
        )
        result.structured_data["artifacts"]["images_dir"] = str(images_dir)
    else:
        result.structured_data["capabilities"]["images"] = _cap(enabled=False, disabled_reason="已禁用")

    output_path.write_text(
        json.dumps(result.structured_data, ensure_ascii=False, indent=2),
        encoding=encoding,
    )
    return output_path

