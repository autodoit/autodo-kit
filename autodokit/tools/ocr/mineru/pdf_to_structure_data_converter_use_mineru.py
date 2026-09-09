"""PDF 转结构化数据：MinerU 转换器封装。

本模块在工具层封装 MinerU，将单个 PDF 转为“适合大模型读取与解析”的统一结构化
数据（``aok.pdf_structured.v3``），与 MonkeyOCR / BabelDOC / local_pipeline_v2
并列，供事务层与既有 consumers 复用。

设计说明：
- 事务层只消费绝对路径；本模块同样要求 ``pdf_path`` / ``output_path`` 为绝对路径。
- MinerU 属于可选依赖（CLI 工具）。未安装或调用失败时抛出带安装提示的
  ``RuntimeError``。
- 输出格式与 ``build_structured_data_payload`` 完全一致，因此下游
  （``load_structured_data`` / ``extract_reference_lines_from_structured_data``）
  无需任何改动即可消费 MinerU 结果。

MinerU 输出映射（优先 ``*_content_list_v2.json``，回退 ``*_content_list.json``）：
- text/title → 全文（按阅读顺序拼接，保留标题层级）
- table → tables（HTML body + 标题/脚注）
- equation → formulas（LaTeX）
- list/index → 列表块并入全文
- image/chart → images（图片路径 + 标题/脚注）
- header/footer/page_number/page_footnote → 作为辅助块保留在 layout.aux
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from autodokit.tools.ocr.classic.pdf_elements_extractors import (
    extract_images_with_pymupdf,
    extract_references_from_full_text,
)
from autodokit.tools.ocr.classic.pdf_structured_data_tools import build_structured_data_payload
from autodokit.tools.ocr.mineru.mineru_runner import (
    discover_mineru_output_files,
    resolve_mineru_cli,
    run_mineru_single_pdf,
)


@dataclass(frozen=True)
class PdfToStructuredDataResult:
    """PDF 转结构化数据的结果。

    Attributes:
        structured_data: 结构化数据（可直接序列化为 JSON）。
        source_pdf_path: 源 PDF 的绝对路径。
        converter: 使用的转换器标识（"mineru"）。
    """

    structured_data: Dict[str, Any]
    source_pdf_path: Path
    converter: str


# 在 content_list 中代表“正文可读内容”的类型（按阅读顺序拼进全文）。
_TEXT_BLOCK_TYPES = {"text", "title", "list", "index"}
# 需要保留但不会成为正文主干的辅助块类型。
_AUX_BLOCK_TYPES = {"header", "footer", "page_number", "aside_text", "page_footnote"}
_IMAGE_BLOCK_TYPES = {"image", "chart"}
_TABLE_BLOCK_TYPES = {"table"}
_EQUATION_BLOCK_TYPES = {"equation", "equation_interline"}


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _listify(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [_stringify(item) for item in value if _stringify(item)]
    return [_stringify(value)]


def _join_texts(values: Sequence[Any]) -> str:
    """把列表块/标题块等拼接为纯文本。"""

    parts: List[str] = []
    for value in values:
        text = _stringify(value)
        if text:
            parts.append(text)
    return " ".join(parts)


def _extract_text_from_content_list_item(item: Dict[str, Any]) -> str:
    """从 content_list / content_list_v2 单条 item 抽取可读文本。"""

    item_type = _stringify(item.get("type")).lower()
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    text = ""

    # content_list_v2 结构：type + content dict
    if item_type == "paragraph":
        text = _join_texts(content.get("paragraph_content") or [])
    elif item_type == "title":
        text = _join_texts(content.get("title_content") or [])
    elif item_type in {"list", "index"}:
        text = _join_texts(content.get("list_items") or item.get("list_items") or [])
    elif item_type in {"text", "title", "list", "index"}:
        # content_list v1 结构
        text = _stringify(item.get("text") or content.get("text"))
        if not text:
            text = _join_texts(item.get("list_items") or content.get("list_items") or [])
    elif item_type in _IMAGE_BLOCK_TYPES:
        text = _join_texts(item.get("image_caption") or content.get("image_caption") or [])
    elif item_type in _TABLE_BLOCK_TYPES:
        text = _join_texts(item.get("table_caption") or content.get("table_caption") or [])
    elif item_type in _EQUATION_BLOCK_TYPES:
        text = _stringify(item.get("text") or content.get("math_content") or "")
    elif item_type == "code":
        text = _stringify(item.get("code_body") or content.get("code_content") or "")
    return text


def _extract_formula_text(item: Dict[str, Any]) -> str:
    """从 content_list 单条 item 抽取公式 LaTeX。"""

    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    text = _stringify(item.get("text") or content.get("math_content") or "")
    if text:
        return text
    return _stringify(item.get("text_format") or content.get("math_type") or "")


def _extract_table_body(item: Dict[str, Any]) -> str:
    """从 content_list 单条 item 抽取表格 HTML body。"""

    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    return _stringify(item.get("table_body") or content.get("table_content") or "")


def _extract_layout_pages(content_list: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """从 content_list 构造 layout 摘要。"""

    pages: Dict[int, List[Dict[str, Any]]] = {}
    aux: List[Dict[str, Any]] = []
    for item in content_list:
        page_idx = int(item.get("page_idx") or 0)
        bbox = item.get("bbox") if isinstance(item.get("bbox"), (list, tuple)) else None
        entry: Dict[str, Any] = {
            "type": _stringify(item.get("type")),
            "bbox": [float(value) for value in bbox] if bbox else None,
        }
        if _stringify(item.get("type")).lower() in _AUX_BLOCK_TYPES:
            entry["text"] = _extract_text_from_content_list_item(item)
            aux.append(entry)
            continue
        pages.setdefault(int(page_idx), []).append(entry)

    return {
        "coord_system": "mineru_content_list_bbox_0_1000",
        "pages": [
            {"page_idx": page_index, "elements": entries}
            for page_index, entries in sorted(pages.items())
        ],
        "elements": [entry for entries in pages.values() for entry in entries],
        "sources": ["content_list"],
        "aux": aux,
        "parse_error": None,
    }


def _load_mineru_content_list(output_dir: Path) -> tuple[List[Dict[str, Any]], str, Path | None]:
    """优先读取 content_list_v2.json，回退到 content_list.json。

    Args:
        output_dir: MinerU 输出目录。

    Returns:
        (items, source_name, path)
    """

    for name in ("*_content_list_v2.json", "*_content_list.json"):
        candidates = sorted(output_dir.glob(name))
        if not candidates:
            continue
        path = candidates[0]
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            # v2 是「按页分组」的两层结构，v1 是扁平列表
            if payload and isinstance(payload[0], list):
                flattened: List[Dict[str, Any]] = []
                for page_items in payload:
                    if isinstance(page_items, list):
                        flattened.extend(item for item in page_items if isinstance(item, dict))
                return flattened, f"{path.stem.split('_')[-2:]}-v2", path
            return [item for item in payload if isinstance(item, dict)], name, path
    return [], "", None


def convert_pdf_to_structured_data(
    pdf_path: Path,
    *,
    mineru: Optional[Dict[str, Any]] = None,
    task_type: str = "full_fine_grained",
    uid_literature: str = "",
    cite_key: str = "",
    source_metadata: Optional[Dict[str, Any]] = None,
) -> PdfToStructuredDataResult:
    """把单个 PDF 转为结构化数据（MinerU）。

    Args:
        pdf_path: PDF 文件绝对路径。
        mineru: MinerU 配置字典（可选，透传给 runner）。常用字段示例：
            - backend: "hybrid-engine" | "pipeline" | "vlm-engine" ...
            - effort: "medium" | "high"
            - method: "auto" | "txt" | "ocr"
            - lang: "ch"（pipeline 后端生效）
            - formula / table / image_analysis: bool
            - cli_path: 显式指定 mineru 可执行文件
            - timeout_seconds: 超时（默认 7200）
        task_type: 结构化任务类型，默认 full_fine_grained。
        uid_literature: 文献 UID（可选）。
        cite_key: 题录键（可选）。
        source_metadata: 来源元数据（可选），常用 title / year。

    Returns:
        PdfToStructuredDataResult: 转换结果。

    Raises:
        ValueError: 路径非绝对路径或文件不存在时抛出。
        RuntimeError: MinerU 未安装或转换失败时抛出。
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

    cfg: Dict[str, Any] = dict(mineru or {})
    import tempfile

    output_dir = Path(str(cfg.get("output_dir") or tempfile.mkdtemp(prefix="mineru_struct_output_")))
    if not output_dir.is_absolute():
        raise ValueError(f"MinerU output_dir 必须是绝对路径：{output_dir}")

    # 提前校验 CLI 可用性（可选依赖的明确报错）
    resolve_mineru_cli(cfg.get("cli_path"))

    run_result = run_mineru_single_pdf(
        pdf_path,
        output_dir,
        backend=str(cfg.get("backend") or "hybrid-engine"),
        effort=str(cfg.get("effort") or "medium"),
        method=str(cfg.get("method") or "auto"),
        lang=str(cfg.get("lang") or "ch"),
        formula=bool(cfg.get("formula", True)),
        table=bool(cfg.get("table", True)),
        image_analysis=bool(cfg.get("image_analysis", True)),
        start_page=cfg.get("start_page"),
        end_page=cfg.get("end_page"),
        client_side_output=bool(cfg.get("client_side_output", True)),
        cli_path=cfg.get("cli_path"),
        timeout_seconds=int(cfg.get("timeout_seconds") or 7200),
        env=cfg.get("env") if isinstance(cfg.get("env"), dict) else None,
    )

    content_list, content_source, content_path = _load_mineru_content_list(run_result.output_dir)
    if not content_list:
        # 某些后端/版本可能只输出 markdown，此时用 markdown 兜底全文。
        markdown_path = next(iter(sorted(run_result.output_dir.glob("*.md"))), None)
        if markdown_path is None:
            raise RuntimeError(
                f"MinerU 运行完成但未发现 content_list 或 markdown 产物：{run_result.output_dir}"
            )
        full_text = markdown_path.read_text(encoding="utf-8", errors="replace")
        full_text_source = f"markdown:{markdown_path.name}"
    else:
        text_parts: List[str] = []
        tables: List[Dict[str, Any]] = []
        formulas: List[Dict[str, Any]] = []
        images: List[Dict[str, Any]] = []
        for item in content_list:
            item_type = _stringify(item.get("type")).lower()
            text = _extract_text_from_content_list_item(item)
            if item_type in _TABLE_BLOCK_TYPES:
                body = _extract_table_body(item)
                tables.append(
                    {
                        "table_html": body,
                        "table_caption": _listify(item.get("table_caption") or item.get("content", {}).get("table_caption")),
                        "table_footnote": _listify(item.get("table_footnote") or item.get("content", {}).get("table_footnote")),
                        "page_idx": int(item.get("page_idx") or 0),
                        "bbox": item.get("bbox"),
                    }
                )
                if text:
                    text_parts.append(text)
            elif item_type in _EQUATION_BLOCK_TYPES:
                formula_text = _extract_formula_text(item)
                formulas.append(
                    {
                        "latex": formula_text,
                        "text": formula_text,
                        "page_idx": int(item.get("page_idx") or 0),
                        "bbox": item.get("bbox"),
                    }
                )
                if formula_text:
                    text_parts.append(formula_text)
            elif item_type in _IMAGE_BLOCK_TYPES:
                img_path = _stringify(item.get("img_path") or item.get("content", {}).get("image_path") or "")
                images.append(
                    {
                        "image_path": str((run_result.output_dir / img_path).resolve()) if img_path else "",
                        "image_caption": _listify(item.get("image_caption") or item.get("content", {}).get("image_caption")),
                        "image_footnote": _listify(item.get("image_footnote") or item.get("content", {}).get("image_footnote")),
                        "page_idx": int(item.get("page_idx") or 0),
                        "bbox": item.get("bbox"),
                        "source": "mineru",
                    }
                )
                if text:
                    text_parts.append(text)
            elif item_type == "code":
                if text:
                    text_parts.append(text)
            elif text:
                text_parts.append(text)

        full_text = "\n\n".join(part for part in text_parts if part.strip())
        full_text_source = content_source or "content_list"

    # 参考文献抽取（规则方法）
    refs, ref_status = extract_references_from_full_text(full_text)

    layout = _extract_layout_pages(content_list) if content_list else {
        "coord_system": "mineru_markdown",
        "pages": [],
        "elements": [],
        "sources": ["markdown"],
        "aux": [],
        "parse_error": None,
    }

    images_meta: List[Dict[str, Any]] = []
    if content_list:
        images_meta = images
    else:
        # markdown 兜底时用 PyMuPDF 抽取内嵌图片
        images_dir = run_result.output_dir / "images"
        images_meta, _img_status = extract_images_with_pymupdf(pdf_path, output_dir=images_dir)

    structured: Dict[str, Any] = build_structured_data_payload(
        pdf_path=pdf_path,
        backend="mineru",
        backend_family="mineru",
        task_type=task_type,
        full_text=full_text,
        extract_error=None,
        text_meta={
            "content_source": full_text_source,
            "mineru_output_dir": str(run_result.output_dir),
            "mineru_backend": str(cfg.get("backend") or "hybrid-engine"),
            "mineru_effort": str(cfg.get("effort") or "medium"),
            "content_list_path": str(content_path) if content_path else "",
            "command": " ".join(run_result.command),
        },
        uid_literature=uid_literature,
        cite_key=cite_key,
        title=str((source_metadata or {}).get("title") or ""),
        year=str((source_metadata or {}).get("year") or ""),
        references=refs,
        images=images_meta,
        tables=tables,
        formulas=formulas,
        layout=layout,
        capabilities={
            "text": {"enabled": True, "disabled_reason": None},
            "images": {"enabled": True, "disabled_reason": None},
            "tables": {"enabled": bool(cfg.get("table", True)), "disabled_reason": None},
            "formulas": {"enabled": bool(cfg.get("formula", True)), "disabled_reason": None},
            "layout": {"enabled": True, "disabled_reason": None},
            "references": {"enabled": bool(ref_status.enabled), "disabled_reason": ref_status.disabled_reason},
        },
        artifacts={
            "mineru_output_dir": str(run_result.output_dir),
            "mineru_files": discover_mineru_output_files(run_result.output_dir),
        },
        extra_fields={
            "mineru": {
                "backend": str(cfg.get("backend") or "hybrid-engine"),
                "effort": str(cfg.get("effort") or "medium"),
                "content_list_source": full_text_source,
                "files": discover_mineru_output_files(run_result.output_dir),
            }
        },
    )

    return PdfToStructuredDataResult(
        structured_data=structured,
        source_pdf_path=pdf_path,
        converter="mineru",
    )


def convert_pdf_to_structured_data_file(
    pdf_path: Path,
    output_path: Path,
    *,
    mineru: Optional[Dict[str, Any]] = None,
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
        mineru: MinerU 配置字典（可选，透传）。
        encoding: 输出编码，默认 utf-8。
        task_type: 结构化任务类型，默认 full_fine_grained。
        uid_literature: 文献 UID（可选）。
        cite_key: 题录键（可选）。
        source_metadata: 来源元数据（可选），常用 title / year。

    Returns:
        Path: 写出的 JSON 文件绝对路径。

    Raises:
        ValueError: 路径非绝对路径时抛出。
    """

    pdf = Path(pdf_path)
    out = Path(output_path)
    if not pdf.is_absolute():
        raise ValueError(f"pdf_path 必须是绝对路径：{pdf}")
    if not out.is_absolute():
        raise ValueError(f"output_path 必须是绝对路径：{out}")

    result = convert_pdf_to_structured_data(
        pdf,
        mineru=mineru,
        task_type=task_type,
        uid_literature=uid_literature,
        cite_key=cite_key,
        source_metadata=source_metadata,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result.structured_data, ensure_ascii=False, indent=2),
        encoding=encoding,
    )
    return out
