"""PDF 转 Markdown 的工具封装。

本模块用于在工具层封装“把单个 PDF 转为 Markdown 文本/文件”的能力，供事务复用。

设计说明：
- 事务实现层遵守本仓库约定：只消费绝对路径，不做任何相对路径解析/兜底。
- 具体的“相对路径 -> 绝对路径”转换由调度层在写入 `.tmp/*.json` 前完成。
- MarkItDown/BabelDOC 的选择通过配置提供；当前仅实现 MarkItDown。

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PdfToMarkdownResult:
    """PDF 转 Markdown 的结果。

    Attributes:
        markdown_text: 转换得到的 Markdown 文本。
        source_pdf_path: 源 PDF 的绝对路径。
        converter: 使用的转换器标识（例如 "markitdown"）。
    """

    markdown_text: str  # 转换得到的 Markdown 文本
    source_pdf_path: Path  # 源 PDF 的绝对路径
    converter: str  # 使用的转换器标识


def convert_pdf_to_markdown_text(
    pdf_path: Path,
    *,
    converter: str = "markitdown",
    markitdown_model: Optional[str] = None,
    babeldoc_placeholder: Optional[dict] = None,
) -> PdfToMarkdownResult:
    """把单个 PDF 转为 Markdown 文本。

    Args:
        pdf_path: PDF 文件绝对路径。
        converter: 转换器类型。目前仅支持 "markitdown"；"babeldoc" 作为占位。
        markitdown_model: MarkItDown 的可选模型/后端参数（占位，具体取决于未来适配）。
        babeldoc_placeholder: BabelDOC 的占位参数（暂不使用）。

    Returns:
        PdfToMarkdownResult: 转换结果（包含 markdown_text）。

    Raises:
        ValueError: 路径不是绝对路径、文件不存在或 converter 不支持。
        RuntimeError: MarkItDown 未安装或转换失败。
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

    conv = str(converter or "").strip().lower()
    if conv in {"markitdown", "microsoft_markitdown", "ms_markitdown"}:
        try:
            # 说明：MarkItDown 的 Python 包名通常为 `markitdown`。
            # 这里做延迟导入，避免在不使用该功能时引入硬依赖。
            from markitdown import MarkItDown  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "未安装 MarkItDown。请先安装：pip install markitdown\n"
                f"原始错误：{exc}"
            ) from exc

        # 关键逻辑说明：
        # - 这里直接调用库接口而非 shell 命令，避免不同平台的路径/编码差异。
        md = MarkItDown()

        try:
            result = md.convert(str(pdf_path))
        except Exception as exc:
            raise RuntimeError(f"MarkItDown 转换失败：{pdf_path}：{exc}") from exc

        markdown_text = getattr(result, "text_content", None)
        if markdown_text is None:
            # 兼容不同版本返回对象字段名
            markdown_text = getattr(result, "text", None)

        if not isinstance(markdown_text, str) or not markdown_text.strip():
            raise RuntimeError(f"MarkItDown 返回的 Markdown 为空：{pdf_path}")

        return PdfToMarkdownResult(
            markdown_text=markdown_text,
            source_pdf_path=pdf_path,
            converter="markitdown",
        )

    if conv in {"babeldoc"}:
        raise NotImplementedError(
            "BabelDOC 模式暂未实现（仅保留占位参数）。"
        )

    raise ValueError(f"不支持的 converter：{converter!r}（当前仅支持 'markitdown'）")


def convert_pdf_to_markdown_file(
    pdf_path: Path,
    output_md_path: Path,
    *,
    converter: str = "markitdown",
    encoding: str = "utf-8",
) -> Path:
    """把单个 PDF 转为 Markdown 文件。

    Args:
        pdf_path: PDF 文件绝对路径。
        output_md_path: 输出 Markdown 文件绝对路径。
        converter: 转换器类型，目前仅支持 "markitdown"。
        encoding: 输出文件编码。

    Returns:
        Path: 写出的 Markdown 文件路径。

    Raises:
        ValueError: 输入/输出路径不为绝对路径。
        RuntimeError: 转换失败。
    """

    if not pdf_path.is_absolute():
        raise ValueError(f"pdf_path 必须是绝对路径：{pdf_path}")
    if not output_md_path.is_absolute():
        raise ValueError(f"output_md_path 必须是绝对路径：{output_md_path}")

    output_md_path.parent.mkdir(parents=True, exist_ok=True)

    result = convert_pdf_to_markdown_text(pdf_path, converter=converter)
    output_md_path.write_text(result.markdown_text, encoding=encoding)
    return output_md_path

