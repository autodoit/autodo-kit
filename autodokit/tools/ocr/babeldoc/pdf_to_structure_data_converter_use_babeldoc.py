"""PDF 转结构化数据：BabelDOC 转换器封装。

本模块在工具层封装使用 BabelDOC 将单个 PDF 转为“适合大模型读取与解析”的结构化数据。

设计说明（与开发者指南保持一致）：
- 事务层只消费绝对路径；本模块同样要求 `pdf_path` / `output_path` 为绝对路径。
- “相对路径 -> 绝对路径”的转换由调度层在写入 `.tmp/*.json` 前完成。
- BabelDOC 属于可选依赖。本模块采用延迟导入；未安装时会抛出带安装提示的 RuntimeError。

输出格式（当前版本约定）：
- 主输出为 JSON 文件（UTF-8），文件名通常为 `<pdf_stem>.structured.json`。
- JSON 内包含：
  - source: 源文件信息（文件名/绝对路径）
  - text: 抽取到的全文纯文本（稳定兜底，便于检索与 LLM 输入）
  - pages: 可选，按页抽取文本（若可用）
  - babeldoc_artifacts: BabelDOC 的产物目录与文件列表（用于追溯与二次处理，例如图表/版面）

为什么这样设计：
- BabelDOC 的“最终产物类型”在不同版本与模式下不稳定（不保证一定输出 md/html/xml）。
- 对 LLM 来说，最稳健的输入之一是“纯文本 + 结构化索引/元数据”。
- 因此这里以 JSON 作为主容器，同时保留 BabelDOC 产物引用，允许后续升级为更强的多模态/版面结构。

"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from autodokit.tools.ocr.classic.pdf_elements_extractors import (
    extract_images_with_pymupdf,
    extract_references_from_full_text,
)
from autodokit.tools.ocr.babeldoc.babeldoc_intermediate_artifacts import (
    export_babeldoc_intermediate_artifacts,
    parse_layout_elements_from_babeldoc_intermediate,
)
from autodokit.tools.ocr.classic.pdf_structured_data_tools import build_structured_data_payload


@dataclass(frozen=True)
class PdfToStructuredDataResult:
    """PDF 转结构化数据的结果。

    Attributes:
        structured_data: 结构化数据（可直接序列化为 JSON）。
        source_pdf_path: 源 PDF 的绝对路径。
        converter: 使用的转换器标识（"babeldoc"）。
    """

    structured_data: Dict[str, Any]  # 结构化数据
    source_pdf_path: Path  # 源 PDF 的绝对路径
    converter: str  # 使用的转换器标识


def _list_files_safe(dir_path: Path) -> list[dict[str, Any]]:
    """列出目录下文件（递归），并以 JSON 友好的形式返回。"""

    if not dir_path.exists() or not dir_path.is_dir():
        return []

    files: list[dict[str, Any]] = []
    for p in dir_path.rglob("*"):
        if not p.is_file():
            continue
        try:
            stat = p.stat()
            files.append(
                {
                    "path": str(p),
                    "name": p.name,
                    "suffix": p.suffix.lower(),
                    "size_bytes": int(stat.st_size),
                    "mtime": float(stat.st_mtime),
                }
            )
        except Exception:
            # 关键逻辑说明：产物目录可能包含临时文件/并发写入文件，列举失败不应影响主流程。
            continue
    return files


def convert_pdf_to_structured_data(
    pdf_path: Path,
    *,
    babeldoc: Optional[Dict[str, Any]] = None,
    task_type: str = "full_fine_grained",
    uid_literature: str = "",
    cite_key: str = "",
    source_metadata: Optional[Dict[str, Any]] = None,
) -> PdfToStructuredDataResult:
    """把单个 PDF 转为结构化数据（BabelDOC）。

    Args:
        pdf_path: PDF 文件绝对路径。
        babeldoc: BabelDOC 的配置字典（可选，透传）。常用字段示例：
            - lang_in: 源语言，默认 "zh"
            - lang_out: 目标语言，默认 "zh"（本工具默认 skip_translation，不走翻译链路）
            - debug: 是否启用 debug（会影响 BabelDOC 工作目录策略）
            - pages: 页码选择字符串（例如 "1-3,5"）

    Returns:
        PdfToStructuredDataResult: 转换结果。

    Raises:
        ValueError: 路径不是绝对路径或文件不存在。
        RuntimeError: BabelDOC 未安装或转换失败。
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

    cfg: Dict[str, Any] = dict(babeldoc or {})

    export_intermediate = bool(cfg.get("export_intermediate", False))
    parse_layout = bool(cfg.get("parse_layout", False))
    intermediate_copy_mode = str(cfg.get("intermediate_copy_mode") or "copy").strip().lower()
    intermediate_max_total_mb = int(cfg.get("intermediate_max_total_mb", 512))

    try:
        from babeldoc.format.pdf.high_level import translate  # type: ignore
        from babeldoc.format.pdf.translation_config import TranslationConfig  # type: ignore
        from babeldoc.translator.translator import BaseTranslator  # type: ignore
        from babeldoc.pdfminer.high_level import extract_text  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "未安装 BabelDOC 或 BabelDOC 版本不兼容。请先安装：pip install BabelDOC\n"
            f"原始错误：{exc}"
        ) from exc

    class _NoopTranslator(BaseTranslator):
        """不做任何翻译的占位 translator。"""

        name = "noop"  # 缓存键
        model = "noop"  # __str__ 会访问

        def __init__(self, lang_in: str, lang_out: str):
            super().__init__(lang_in=lang_in, lang_out=lang_out, ignore_cache=True)

        def do_translate(self, _text, rate_limit_params: dict = None):  # type: ignore[override]
            raise NotImplementedError("skip_translation 模式下不应调用 do_translate")

        def do_llm_translate(self, _text, rate_limit_params: dict = None):  # type: ignore[override]
            raise NotImplementedError("skip_translation 模式下不应调用 do_llm_translate")

    lang_in = str(cfg.get("lang_in") or "zh")
    lang_out = str(cfg.get("lang_out") or "zh")

    working_dir = Path(tempfile.mkdtemp(prefix="babeldoc_struct_working_"))
    output_dir = Path(tempfile.mkdtemp(prefix="babeldoc_struct_output_"))

    # 关键逻辑说明：
    # - 转结构化数据时，我们只需要 BabelDOC 做“版面解析与中间产物生成”。
    # - 因此默认 skip_translation=True，避免外部翻译依赖导致失败。
    skip_translation = bool(cfg.get("skip_translation", True))
    only_parse_generate_pdf = bool(cfg.get("only_parse_generate_pdf", True))

    try:
        tc = TranslationConfig(
            translator=_NoopTranslator(lang_in=lang_in, lang_out=lang_out),
            input_file=str(pdf_path),
            lang_in=lang_in,
            lang_out=lang_out,
            doc_layout_model=cfg.get("doc_layout_model"),
            output_dir=str(output_dir),
            working_dir=str(working_dir),
            debug=bool(cfg.get("debug", False)),
            pages=cfg.get("pages"),
            skip_translation=skip_translation,
            only_parse_generate_pdf=only_parse_generate_pdf,
            skip_scanned_detection=bool(cfg.get("skip_scanned_detection", False)),
            ocr_workaround=bool(cfg.get("ocr_workaround", False)),
            enhance_compatibility=bool(cfg.get("enhance_compatibility", False)),
        )
        translate_result = translate(tc)
        babeldoc_error: str | None = None
    except Exception as exc:
        # 关键逻辑说明：
        # - Windows 下 BabelDOC 可能在字体子集化等环节启动 multiprocessing 子进程。
        # - 对可编程调用/交互式环境，用户往往没有 "__main__" 保护，从而触发 spawn 报错。
        # - 我们不让整条结构化抽取链路失败：记录错误并继续用兜底全文 + 其他抽取器。
        translate_result = None
        babeldoc_error = str(exc)

    # 稳健兜底：用 BabelDOC 自带的 pdfminer 分支抽取纯文本。
    try:
        full_text = extract_text(str(pdf_path))
    except Exception as exc:
        # 关键逻辑说明：
        # - extract_text 可能被坏 PDF/加密 PDF 触发异常。
        # - 这里不让整条链路失败，保留空文本并记录错误。
        full_text = ""
        extract_error = str(exc)
    else:
        extract_error = None

    structured: Dict[str, Any] = build_structured_data_payload(
        pdf_path=pdf_path,
        backend="babeldoc",
        backend_family="babeldoc",
        task_type=task_type,
        full_text=full_text,
        extract_error=extract_error,
        text_meta={},
        uid_literature=uid_literature,
        cite_key=cite_key,
        title=str((source_metadata or {}).get("title") or ""),
        year=str((source_metadata or {}).get("year") or ""),
        references=[],
        images=[],
        tables=[],
        formulas=[],
        capabilities={},
        artifacts={},
        layout={
            "coord_system": "unknown",
            "pages": [],
            "elements": [],
            "sources": [],
            "parse_error": None,
        },
        extra_fields={
            "babeldoc_artifacts": {
                "working_dir": str(working_dir),
                "output_dir": str(output_dir),
                "files": _list_files_safe(output_dir),
                "translate_result": str(translate_result) if translate_result is not None else None,
                "babeldoc_error": babeldoc_error,
                "intermediate": {
                    "enabled": bool(export_intermediate),
                    "copy_mode": intermediate_copy_mode,
                    "max_total_mb": intermediate_max_total_mb,
                    "artifacts_dir": None,
                    "exported_files": [],
                },
            }
        },
    )

    # 关键逻辑说明：
    # - BabelDOC 产物目录的结构在不同版本中可能变化，此处不强依赖它的内部格式。
    # - 为了尽可能保留复杂信息，我们引入“可选抽取器”对原始 PDF 做二次抽取。
    artifacts_root = output_dir / "artifacts"
    images_dir = artifacts_root / "images"

    images, img_status = extract_images_with_pymupdf(pdf_path, output_dir=images_dir)
    structured["images"] = images
    structured["capabilities"]["images"] = {
        "enabled": bool(img_status.enabled),
        "disabled_reason": img_status.disabled_reason,
    }
    structured["artifacts"]["images_dir"] = str(images_dir)

    refs, ref_status = extract_references_from_full_text(full_text)
    structured["references"] = refs
    structured["capabilities"]["references"] = {
        "enabled": bool(ref_status.enabled),
        "disabled_reason": ref_status.disabled_reason,
    }

    # 导出与解析 BabelDOC 中间产物（可选）
    if export_intermediate or parse_layout:
        intermediate_dir = (output_dir / "artifacts" / "babeldoc_intermediate")
        structured["babeldoc_artifacts"]["intermediate"]["artifacts_dir"] = str(intermediate_dir)

        if export_intermediate:
            exported_files = export_babeldoc_intermediate_artifacts(
                working_dir=working_dir,
                output_dir=output_dir,
                artifacts_dir=intermediate_dir,
                copy_mode=intermediate_copy_mode,
                max_total_mb=intermediate_max_total_mb,
            )
            structured["babeldoc_artifacts"]["intermediate"]["exported_files"] = exported_files

        if parse_layout:
            parsed = parse_layout_elements_from_babeldoc_intermediate(
                working_dir=working_dir,
                output_dir=output_dir,
                max_files=int(cfg.get("parse_layout_max_files", 200)),
            )
            structured["layout"].update(parsed.layout)
            structured["layout"]["parse_error"] = parsed.parse_error

    return PdfToStructuredDataResult(
        structured_data=structured,
        source_pdf_path=pdf_path,
        converter="babeldoc",
    )


def convert_pdf_to_structured_data_file(
    pdf_path: Path,
    output_path: Path,
    *,
    babeldoc: Optional[Dict[str, Any]] = None,
    encoding: str = "utf-8",
    task_type: str = "full_fine_grained",
    uid_literature: str = "",
    cite_key: str = "",
    source_metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """把单个 PDF 转为结构化数据文件（JSON）。

    Args:
        pdf_path: PDF 文件绝对路径。
        output_path: 输出 JSON 文件绝对路径。
        babeldoc: BabelDOC 配置（可选）。
        encoding: 输出文件编码。

    Returns:
        Path: 写出的 JSON 文件路径。

    Raises:
        ValueError: 输入/输出路径不为绝对路径。
        RuntimeError: 转换失败。
    """

    if not pdf_path.is_absolute():
        raise ValueError(f"pdf_path 必须是绝对路径：{pdf_path}")
    if not output_path.is_absolute():
        raise ValueError(f"output_path 必须是绝对路径：{output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = convert_pdf_to_structured_data(
        pdf_path,
        babeldoc=babeldoc,
        task_type=task_type,
        uid_literature=uid_literature,
        cite_key=cite_key,
        source_metadata=source_metadata,
    )
    output_path.write_text(
        json.dumps(result.structured_data, ensure_ascii=False, indent=2),
        encoding=encoding,
    )
    return output_path

