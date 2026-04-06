"""阿里百炼多模态 PDF 单篇解析工具。

本工具只负责单篇 PDF 的阿里百炼多模态解析，不接入 BabelDOC 或旧 PDF 解析链。
默认始终生成结构树、线性索引、chunks、解析记录和质量报告，并为每个 PDF
创建独立输出目录。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from typing import Any, Dict, Iterable, List, Optional, Sequence

from autodokit.tools.llm_clients import AliyunDashScopeClient, LLMConfigError, load_aliyun_llm_config
from autodokit.tools.llm_parsing import LLMOutputParseError, parse_json_object_from_text
from autodokit.tools.pdf_elements_extractors import extract_images_with_pymupdf, extract_references_from_full_text
from autodokit.tools.pdf_multimodal_tree_builder import (
    build_elements_payload,
    build_quality_report,
    build_tree_linear_index,
    build_structure_tree,
    render_reconstructed_markdown,
)
from autodokit.tools.pdf_page_image_tools import crop_image_by_normalized_bbox, render_pdf_pages_to_png


_DEFAULT_CHUNK_TARGET_TYPES = {
    "document_title",
    "heading",
    "paragraph",
    "abstract_block",
    "keywords_block",
    "reference_item",
    "figure_caption",
    "table_caption",
    "formula_caption",
    "author_block",
    "affiliation_block",
    "footnote",
}


def _is_data_inspection_failed_error(exc: Exception) -> bool:
    """判断是否为阿里百炼内容审核拦截错误。"""

    text = str(exc or "")
    lowered = text.lower()
    return "datainspectionfailed" in lowered or "data_inspection_failed" in lowered


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _resolve_path(path: str | Path, *, field_name: str, require_file: bool = False) -> Path:
    resolved = Path(path).expanduser().resolve()
    if require_file and (not resolved.exists() or not resolved.is_file()):
        raise ValueError(f"{field_name} 必须是存在的文件：{resolved}")
    return resolved


def _slugify_output_name(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("._-")
    return text[:80] if text else ""


def generate_aok_pdf_parse_uid() -> str:
    """生成默认输出目录名。

    Returns:
        str: 时间戳加随机后缀的 UID。
    """

    stamp = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"aok_pdf_parse_{stamp}_{suffix}"


def resolve_aok_pdf_parse_output_dir(
    output_root: str | Path,
    *,
    output_name: str | None = None,
    overwrite_output: bool = False,
) -> tuple[Path, str]:
    """解析单篇输出目录。

    Args:
        output_root: 输出根目录。
        output_name: 可选目录名。
        overwrite_output: 是否允许覆盖既有目录。

    Returns:
        tuple[Path, str]: 目标输出目录与最终目录名。
    """

    root = _resolve_path(output_root, field_name="output_root")
    root.mkdir(parents=True, exist_ok=True)
    final_name = _slugify_output_name(output_name or "") or generate_aok_pdf_parse_uid()
    final_dir = (root / final_name).resolve()
    if final_dir.exists() and any(final_dir.iterdir()) and not overwrite_output:
        raise FileExistsError(f"输出目录已存在且非空：{final_dir}")
    final_dir.mkdir(parents=True, exist_ok=True)
    return final_dir, final_name


def _build_page_prompt(*, page_number: int, page_text: str, title: str, year: str, language: str) -> str:
    text_excerpt = str(page_text or "").strip()
    if len(text_excerpt) > 4000:
        text_excerpt = text_excerpt[:4000] + "\n...[truncated]..."
    return (
        "请只输出一个 JSON 对象，不要输出解释。\n"
        "你正在解析一篇学术文献的单页图像。\n"
        f"文献标题：{title or '未知标题'}\n"
        f"年份：{year or '未知年份'}\n"
        f"语言提示：{language or 'auto'}\n"
        f"当前页码：{page_number}\n"
        "任务：识别该页中的关键元素，并输出受控 JSON。\n"
        "受控 node_type 仅允许以下枚举：document_title, heading, paragraph, figure, figure_caption, table, table_caption, formula, formula_caption, footnote, reference_item, citation_anchor, author_block, affiliation_block, abstract_block, keywords_block。\n"
        "bbox 使用 0 到 1000 的归一化坐标 [x1, y1, x2, y2]；不确定时填 null。\n"
        "heading_level 仅对 heading 有效，范围 1-6；其他类型填 0。\n"
        "输出格式：{\"page_index\": 整数, \"page_summary\": 字符串, \"elements\": [{\"node_type\": 字符串, \"text\": 字符串, \"confidence\": 0到1数字, \"bbox\": 数组或null, \"heading_level\": 整数, \"reading_order\": 整数}]}\n"
        "如果页面主要是参考文献，请尽量拆成多个 reference_item。\n"
        f"可用文本层摘录（可能有噪声，仅作辅助）：\n{text_excerpt}"
    )


def _fallback_page_result(*, page_index: int, page_text: str) -> Dict[str, Any]:
    text = str(page_text or "").strip()
    references, _ = extract_references_from_full_text(text)
    elements: List[Dict[str, Any]] = []
    if references:
        for idx, item in enumerate(references, start=1):
            elements.append(
                {
                    "node_type": "reference_item",
                    "text": str(item.get("raw") or item.get("text") or "").strip(),
                    "confidence": 0.35,
                    "bbox": None,
                    "heading_level": 0,
                    "reading_order": idx,
                }
            )
    elif text:
        paragraphs = [segment.strip() for segment in text.split("\n\n") if segment.strip()]
        for idx, paragraph in enumerate(paragraphs[:8], start=1):
            elements.append(
                {
                    "node_type": "paragraph",
                    "text": paragraph,
                    "confidence": 0.2,
                    "bbox": None,
                    "heading_level": 0,
                    "reading_order": idx,
                }
            )
    return {
        "page_index": int(page_index),
        "page_summary": "fallback_local_text",
        "elements": elements,
    }


def _parse_page_with_model(
    *,
    client: AliyunDashScopeClient,
    page_record: Dict[str, Any],
    title: str,
    year: str,
    language: str,
    debug_dir: Path | None,
    temperature: float,
    max_output_tokens: int,
) -> Dict[str, Any]:
    prompt = _build_page_prompt(
        page_number=int(page_record.get("page_number") or 0),
        page_text=str(page_record.get("text") or ""),
        title=title,
        year=year,
        language=language,
    )
    raw_text = client.generate_multimodal_text(
        prompt=prompt,
        image_paths=[str(page_record.get("image_path") or "")],
        system="你是学术文献版面解析器，只输出受控 JSON。",
        temperature=temperature,
        max_tokens=max_output_tokens,
        extra={"response_format": {"type": "json_object"}},
    )
    payload, _ = parse_json_object_from_text(
        raw_text,
        debug_dir=debug_dir,
        debug_prefix=f"page_{int(page_record.get('page_number') or 0):04d}",
    )
    if "page_index" not in payload:
        payload["page_index"] = int(page_record.get("page_index") or 0)
    if not isinstance(payload.get("elements"), list):
        payload["elements"] = []
    return payload


def _build_sanitized_page_image(
    *,
    image_path: Path,
    output_dir: Path,
    page_number: int,
) -> Path:
    """生成用于重试的净化页图，降低误触审核概率。"""

    try:
        from PIL import Image, ImageOps  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("未安装 Pillow，无法生成净化页图。") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    sanitized_path = (output_dir / f"page_{int(page_number):04d}_sanitized.png").resolve()
    with Image.open(image_path) as raw:
        image = raw.convert("RGB")
        # 自动对比度 + 灰度，优先保留文本结构并减弱图像噪声。
        image = ImageOps.autocontrast(image, cutoff=1)
        image = image.convert("L")
        # 轻量降采样，减少局部纹理噪声引发的误判。
        width, height = image.size
        resized = image.resize((max(1, int(width * 0.92)), max(1, int(height * 0.92))))
        resized.save(sanitized_path)
    return sanitized_path


def _materialize_special_attachments(
    *,
    attachments_root: Path,
    elements_payload: Dict[str, Any],
    element_to_node: Dict[str, str],
    enable_figure_crop: bool,
    enable_table_crop: bool,
    enable_formula_crop: bool,
    start_index: int = 0,
) -> List[Dict[str, Any]]:
    items = elements_payload.get("items") if isinstance(elements_payload.get("items"), list) else []
    page_image_map: Dict[int, Path] = {}
    for item in items:
        page_index = int(item.get("page_index") or 0)
        source_ref = item.get("source_ref") if isinstance(item.get("source_ref"), dict) else {}
        page_image_text = str(source_ref.get("page_image_path") or "").strip()
        if not page_image_text:
            continue
        page_image_path = Path(page_image_text)
        if not page_image_path.is_absolute() or not page_image_path.exists() or not page_image_path.is_file():
            continue
        page_image_map[page_index] = page_image_path

    enabled_map = {
        "figure": enable_figure_crop,
        "table": enable_table_crop,
        "formula": enable_formula_crop,
    }
    folder_map = {
        "figure": "figures",
        "table": "tables",
        "formula": "formulas",
    }

    results: List[Dict[str, Any]] = []
    for item in items:
        node_type = str(item.get("node_type") or "")
        if node_type not in folder_map or not enabled_map[node_type]:
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        page_index = int(item.get("page_index") or 0)
        page_image_path = page_image_map.get(page_index)
        if page_image_path is None or not page_image_path.exists():
            continue
        output_path = (
            attachments_root
            / folder_map[node_type]
            / f"{node_type}_{page_index + 1:04d}_{str(item.get('node_id') or '')}.png"
        ).resolve()
        if not crop_image_by_normalized_bbox(page_image_path, output_path=output_path, bbox=bbox):
            continue
        results.append(
            {
                "attachment_id": f"attachment_{start_index + len(results) + 1:05d}",
                "attachment_type": node_type,
                "storage_path": str(output_path),
                "page_index": int(page_index),
                "bbox": list(bbox),
                "linked_node_id": element_to_node.get(str(item.get("node_id") or ""), ""),
                "render_method": "crop_from_page_image",
            }
        )
    return results


def _build_chunk_units(linear_index_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = linear_index_payload.get("entries") if isinstance(linear_index_payload.get("entries"), list) else []
    units: List[Dict[str, Any]] = []
    for entry in entries:
        kind = str(entry.get("entry_kind") or "")
        page_index = int(entry.get("page_index") or 0)
        if kind == "tree_node":
            node_type = str(entry.get("node_type") or "")
            text = str(entry.get("text") or "").strip()
            if not text or node_type == "document":
                continue
            if node_type == "section":
                unit_text = f"## {text}"
            elif node_type == "subsection":
                unit_text = f"### {text}"
            elif node_type == "references_section":
                unit_text = "## References"
            else:
                unit_text = text
            units.append(
                {
                    "entry_id": f"tree::{entry.get('node_id')}",
                    "page_index": page_index,
                    "text": unit_text,
                    "node_type": node_type,
                    "source_node_id": str(entry.get("node_id") or ""),
                }
            )
            continue

        if kind == "element":
            element_type = str(entry.get("element_type") or "")
            text = str(entry.get("text") or "").strip()
            if not text or element_type not in _DEFAULT_CHUNK_TARGET_TYPES:
                continue
            if element_type == "reference_item":
                unit_text = f"- {text}"
            elif element_type in {"figure_caption", "table_caption", "formula_caption"}:
                unit_text = f"*{text}*"
            else:
                unit_text = text
            units.append(
                {
                    "entry_id": f"element::{entry.get('element_id')}",
                    "page_index": page_index,
                    "text": unit_text,
                    "node_type": element_type,
                    "source_node_id": str(entry.get("node_id") or ""),
                }
            )
            continue

        if kind == "attachment":
            attachment_type = str(entry.get("attachment_type") or "")
            if attachment_type not in {"figure", "table", "formula"}:
                continue
            storage_path = str(entry.get("storage_path") or "").strip()
            if not storage_path:
                continue
            units.append(
                {
                    "entry_id": f"attachment::{entry.get('attachment_id')}",
                    "page_index": page_index,
                    "text": f"[{attachment_type.upper()}] {Path(storage_path).name}",
                    "node_type": attachment_type,
                    "source_node_id": str(entry.get("node_id") or ""),
                }
            )
    return units


def build_aliyun_multimodal_chunks(
    linear_index_payload: Dict[str, Any],
    *,
    chunk_max_chars: int = 2200,
    chunk_overlap_chars: int = 200,
) -> Dict[str, Any]:
    """根据线性索引生成顺序分块结果。"""

    if chunk_max_chars <= 0:
        raise ValueError("chunk_max_chars 必须大于 0")
    if chunk_overlap_chars < 0:
        raise ValueError("chunk_overlap_chars 不能小于 0")
    if chunk_overlap_chars >= chunk_max_chars:
        raise ValueError("chunk_overlap_chars 必须小于 chunk_max_chars")

    source = dict(linear_index_payload.get("source") or {})
    units = _build_chunk_units(linear_index_payload)
    chunks: List[Dict[str, Any]] = []

    current_texts: List[str] = []
    current_entry_ids: List[str] = []
    current_node_ids: List[str] = []
    current_pages: List[int] = []

    def flush_chunk() -> None:
        if not current_texts:
            return
        merged_text = "\n\n".join(current_texts).strip()
        if not merged_text:
            return
        page_span = [min(current_pages) + 1, max(current_pages) + 1] if current_pages else [0, 0]
        chunks.append(
            {
                "chunk_id": f"chunk_{len(chunks) + 1:05d}",
                "text": merged_text,
                "char_count": len(merged_text),
                "page_span": page_span,
                "source_entry_ids": list(current_entry_ids),
                "source_node_ids": list(dict.fromkeys(current_node_ids)),
            }
        )

    for unit in units:
        unit_text = str(unit["text"])
        projected = "\n\n".join([*current_texts, unit_text]).strip()
        if current_texts and len(projected) > chunk_max_chars:
            flush_chunk()
            overlap_seed = ""
            if chunk_overlap_chars > 0 and chunks:
                overlap_seed = chunks[-1]["text"][-chunk_overlap_chars:].strip()
            current_texts[:] = [overlap_seed] if overlap_seed else []
            current_entry_ids[:] = []
            current_node_ids[:] = []
            current_pages[:] = []
        current_texts.append(unit_text)
        current_entry_ids.append(str(unit["entry_id"]))
        current_node_ids.append(str(unit["source_node_id"]))
        current_pages.append(int(unit["page_index"]))

    flush_chunk()

    return {
        "schema": "aok.pdf_multimodal_chunks.v1",
        "source": source,
        "chunks": chunks,
        "summary": {
            "chunk_count": len(chunks),
            "total_chars": sum(int(chunk["char_count"]) for chunk in chunks),
            "chunk_max_chars": int(chunk_max_chars),
            "chunk_overlap_chars": int(chunk_overlap_chars),
        },
    }


def _write_chunks(output_dir: Path, chunks_payload: Dict[str, Any]) -> tuple[Path, Path]:
    chunk_manifest_path = (output_dir / "chunk_manifest.json").resolve()
    chunks_jsonl_path = (output_dir / "chunks.jsonl").resolve()
    chunk_manifest_path.write_text(json.dumps(chunks_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with chunks_jsonl_path.open("w", encoding="utf-8") as stream:
        for chunk in chunks_payload.get("chunks") or []:
            stream.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    return chunk_manifest_path, chunks_jsonl_path


def parse_pdf_with_aliyun_multimodal(
    pdf_path: str | Path,
    output_root: str | Path,
    *,
    output_name: str | None = None,
    api_key_file: str | Path,
    model: str = "auto",
    sdk_backend: str | None = None,
    base_url: str | None = None,
    language: str = "",
    document_id: str = "",
    uid_literature: str = "",
    cite_key: str = "",
    source_metadata: Optional[Dict[str, Any]] = None,
    start_page: int = 1,
    end_page: int | None = None,
    max_pages: int | None = None,
    page_dpi: int = 180,
    max_retries: int = 3,
    retry_backoff_seconds: float = 2.0,
    temperature: float = 0.1,
    max_output_tokens: int = 4096,
    enable_embedded_image_extract: bool = True,
    enable_figure_crop: bool = True,
    enable_table_crop: bool = True,
    enable_formula_crop: bool = True,
    chunk_max_chars: int = 2200,
    chunk_overlap_chars: int = 200,
    write_debug_payloads: bool = True,
    overwrite_output: bool = False,
) -> Dict[str, Any]:
    """执行单篇阿里百炼多模态 PDF 解析。

    Args:
        pdf_path: 待解析 PDF 路径。
        output_root: 输出根目录。
        output_name: 可选单篇输出目录名；为空时自动生成 UID。
        api_key_file: 阿里百炼 API Key 文件路径。
        model: 模型名，默认 auto。
        sdk_backend: 可选 SDK 后端；未指定时按模型与路由提示自动决定。
        base_url: 可选自定义 OpenAI 兼容地址。
        language: 语言提示，例如 zh/en。
        document_id: 可选文档标识。
        uid_literature: 可选 literature UID。
        cite_key: 可选 cite key。
        source_metadata: 可选源元数据。
        start_page: 起始页码，从 1 开始。
        end_page: 结束页码，None 表示到末页。
        max_pages: 最多处理页数。
        page_dpi: 页图 DPI。
        max_retries: 每页最大重试次数。
        retry_backoff_seconds: 重试等待秒数。
        temperature: 采样温度。
        max_output_tokens: 最大输出 token。
        enable_embedded_image_extract: 是否抽取内嵌图片。
        enable_figure_crop: 是否裁切 figure 附件。
        enable_table_crop: 是否裁切 table 附件。
        enable_formula_crop: 是否裁切 formula 附件。
        chunk_max_chars: 分块最大字符数。
        chunk_overlap_chars: 分块重叠字符数。
        write_debug_payloads: 是否写调试输出。
        overwrite_output: 是否允许覆盖既有非空输出目录。

    Returns:
        Dict[str, Any]: 结果摘要。
    """

    pdf_file = _resolve_path(pdf_path, field_name="pdf_path", require_file=True)
    api_key_file_path = _resolve_path(api_key_file, field_name="api_key_file", require_file=True)
    if start_page < 1:
        raise ValueError("start_page 必须大于等于 1")
    if end_page is not None and end_page < start_page:
        raise ValueError("end_page 不能小于 start_page")

    output_dir, final_output_name = resolve_aok_pdf_parse_output_dir(
        output_root,
        output_name=output_name,
        overwrite_output=overwrite_output,
    )

    attachments_root = (output_dir / "attachments").resolve()
    pages_dir = (attachments_root / "pages").resolve()
    images_dir = (attachments_root / "images").resolve()
    for folder in [pages_dir, images_dir, attachments_root / "figures", attachments_root / "tables", attachments_root / "formulas"]:
        folder.mkdir(parents=True, exist_ok=True)

    debug_dir = (output_dir / "debug").resolve() if write_debug_payloads else None
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)

    source = {
        "document_id": str(document_id or "").strip(),
        "uid_literature": str(uid_literature or "").strip(),
        "cite_key": str(cite_key or "").strip(),
        "title": str((source_metadata or {}).get("title") or "").strip(),
        "year": str((source_metadata or {}).get("year") or "").strip(),
        "language": str(language or (source_metadata or {}).get("language") or "").strip(),
        "pdf_name": pdf_file.name,
        "pdf_abs_path": str(pdf_file),
        "backend": "aok_pdf_aliyun_multimodal_parse.v1",
        "output_name": final_output_name,
    }

    page_records = render_pdf_pages_to_png(pdf_file, output_dir=pages_dir, dpi=page_dpi, max_pages=max_pages)
    if end_page is None:
        filtered_page_records = [item for item in page_records if int(item.get("page_number") or 0) >= start_page]
    else:
        filtered_page_records = [
            item
            for item in page_records
            if start_page <= int(item.get("page_number") or 0) <= int(end_page)
        ]
    if not filtered_page_records:
        raise ValueError("筛选后没有可处理的页面")

    embedded_images: List[Dict[str, Any]] = []
    embedded_image_status_enabled = False
    embedded_image_disabled_reason = "未启用内嵌图片抽取"
    if enable_embedded_image_extract:
        embedded_images, image_status = extract_images_with_pymupdf(pdf_file, output_dir=images_dir)
        embedded_image_status_enabled = bool(image_status.enabled)
        embedded_image_disabled_reason = str(image_status.disabled_reason or "")

    llm_cfg = load_aliyun_llm_config(
        model=model,
        api_key_file=str(api_key_file_path),
        sdk_backend=sdk_backend,
        base_url=base_url,
        affair_name="阿里百炼多模态 PDF 单篇解析",
        route_hints={
            "task_type": "vision",
            "need_vision": True,
            "budget_tier": "premium",
            "prefer_quality": True,
        },
    )
    client = AliyunDashScopeClient(llm_cfg)

    page_results: List[Dict[str, Any]] = []
    sanitized_pages_dir = (debug_dir / "sanitized_pages").resolve() if debug_dir is not None else (output_dir / "_sanitized_pages").resolve()
    for page_record in filtered_page_records:
        last_error = ""
        inspection_blocked = False
        inspection_retry_used = False
        for attempt in range(1, max_retries + 1):
            try:
                page_result = _parse_page_with_model(
                    client=client,
                    page_record=page_record,
                    title=source["title"],
                    year=source["year"],
                    language=source["language"],
                    debug_dir=debug_dir,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                if attempt > 1:
                    page_result["retry_count"] = attempt - 1
                page_result["inspection_blocked"] = inspection_blocked
                page_result["inspection_retry_used"] = inspection_retry_used
                page_results.append(page_result)
                break
            except Exception as exc:  # noqa: BLE001
                if _is_data_inspection_failed_error(exc):
                    inspection_blocked = True
                    try:
                        sanitized_path = _build_sanitized_page_image(
                            image_path=Path(str(page_record.get("image_path") or "")).resolve(),
                            output_dir=sanitized_pages_dir,
                            page_number=int(page_record.get("page_number") or 0),
                        )
                        patched_page_record = dict(page_record)
                        patched_page_record["image_path"] = str(sanitized_path)
                        page_result = _parse_page_with_model(
                            client=client,
                            page_record=patched_page_record,
                            title=source["title"],
                            year=source["year"],
                            language=source["language"],
                            debug_dir=debug_dir,
                            temperature=temperature,
                            max_output_tokens=max_output_tokens,
                        )
                        page_result["retry_count"] = attempt
                        page_result["inspection_blocked"] = True
                        page_result["inspection_retry_used"] = True
                        page_result["inspection_retry_image_path"] = str(sanitized_path)
                        page_results.append(page_result)
                        inspection_retry_used = True
                        break
                    except Exception as sanitized_exc:  # noqa: BLE001
                        last_error = f"inspection_failed_after_sanitized_retry: {sanitized_exc}"
                        page_result = _fallback_page_result(
                            page_index=int(page_record.get("page_index") or 0),
                            page_text=str(page_record.get("text") or ""),
                        )
                        page_result["fallback_reason"] = last_error
                        page_result["retry_count"] = attempt
                        page_result["inspection_blocked"] = True
                        page_result["inspection_retry_used"] = True
                        page_results.append(page_result)
                        break
                last_error = str(exc)
                if attempt >= max_retries:
                    page_result = _fallback_page_result(
                        page_index=int(page_record.get("page_index") or 0),
                        page_text=str(page_record.get("text") or ""),
                    )
                    page_result["fallback_reason"] = last_error
                    page_result["retry_count"] = attempt - 1
                    page_result["inspection_blocked"] = inspection_blocked
                    page_result["inspection_retry_used"] = inspection_retry_used
                    page_results.append(page_result)
                    break
                sleep(max(float(retry_backoff_seconds), 0.0))

    elements_payload = build_elements_payload(source=source, page_records=filtered_page_records, page_results=page_results)
    tree_payload, element_to_node = build_structure_tree(elements_payload)

    attachments: List[Dict[str, Any]] = []
    for page_record in filtered_page_records:
        attachments.append(
            {
                "attachment_id": f"attachment_{len(attachments) + 1:05d}",
                "attachment_type": "page",
                "storage_path": str(page_record.get("image_path") or ""),
                "page_index": int(page_record.get("page_index") or 0),
                "bbox": None,
                "linked_node_id": tree_payload.get("root_id") or "",
                "render_method": "page_raster",
            }
        )
    for image in embedded_images:
        attachments.append(
            {
                "attachment_id": f"attachment_{len(attachments) + 1:05d}",
                "attachment_type": "image",
                "storage_path": str(image.get("image_path") or ""),
                "page_index": int(image.get("page_index") or 0),
                "bbox": None,
                "linked_node_id": "",
                "render_method": "pymupdf_embedded_image",
            }
        )
    attachments.extend(
        _materialize_special_attachments(
            attachments_root=attachments_root,
            elements_payload=elements_payload,
            element_to_node=element_to_node,
            enable_figure_crop=enable_figure_crop,
            enable_table_crop=enable_table_crop,
            enable_formula_crop=enable_formula_crop,
            start_index=len(attachments),
        )
    )

    for node in tree_payload.get("nodes") or []:
        element_refs = node.get("element_refs") if isinstance(node.get("element_refs"), list) else []
        node["attachment_refs"] = [
            attachment["attachment_id"]
            for attachment in attachments
            if attachment.get("linked_node_id") == node.get("node_id")
        ]
        if not node.get("title") and element_refs:
            first_ref = str(element_refs[0])
            for item in elements_payload.get("items") or []:
                if str(item.get("node_id") or "") == first_ref:
                    node["title"] = str(item.get("text") or "")[:80]
                    break

    linear_index_payload = build_tree_linear_index(
        tree_payload=tree_payload,
        elements_payload=elements_payload,
        attachments=attachments,
    )
    quality_report = build_quality_report(
        elements_payload=elements_payload,
        tree_payload=tree_payload,
        attachments=attachments,
    )
    reconstructed_markdown = render_reconstructed_markdown(linear_index_payload, output_dir=output_dir)
    chunks_payload = build_aliyun_multimodal_chunks(
        linear_index_payload,
        chunk_max_chars=chunk_max_chars,
        chunk_overlap_chars=chunk_overlap_chars,
    )

    parse_record = {
        "schema": "aok.pdf_aliyun_multimodal_parse_record.v1",
        "created_at": _utc_now_iso(),
        "backend": source["backend"],
        "pdf_path": str(pdf_file),
        "output_name": final_output_name,
        "page_count": int(len(filtered_page_records)),
        "llm_enabled": True,
        "llm_model": str(llm_cfg.model),
        "llm_backend": str(llm_cfg.sdk_backend),
        "llm_region": str(llm_cfg.region),
        "llm_base_url": str(llm_cfg.base_url or ""),
        "routing_info": dict(llm_cfg.routing_info or {}),
        "embedded_image_extractor_enabled": bool(embedded_image_status_enabled),
        "embedded_image_extractor_disabled_reason": embedded_image_disabled_reason,
        "page_results": [
            {
                "page_index": int(item.get("page_index") or 0),
                "page_summary": str(item.get("page_summary") or ""),
                "element_count": int(len(item.get("elements") or [])),
                "fallback_reason": str(item.get("fallback_reason") or ""),
                "retry_count": int(item.get("retry_count") or 0),
                "inspection_blocked": bool(item.get("inspection_blocked") or False),
                "inspection_retry_used": bool(item.get("inspection_retry_used") or False),
            }
            for item in page_results
        ],
    }

    structured_tree_path = (output_dir / "structured_tree.json").resolve()
    elements_path = (output_dir / "elements.json").resolve()
    attachments_manifest_path = (output_dir / "attachments_manifest.json").resolve()
    linear_index_path = (output_dir / "linear_index.json").resolve()
    reconstructed_markdown_path = (output_dir / "reconstructed_content.md").resolve()
    parse_record_path = (output_dir / "parse_record.json").resolve()
    quality_report_path = (output_dir / "quality_report.json").resolve()
    result_path = (output_dir / "result.json").resolve()

    structured_tree_path.write_text(json.dumps(tree_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elements_path.write_text(json.dumps(elements_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    attachments_manifest_path.write_text(
        json.dumps({"schema": "aok.pdf_multimodal_attachments.v1", "items": attachments}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    linear_index_path.write_text(json.dumps(linear_index_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    reconstructed_markdown_path.write_text(reconstructed_markdown, encoding="utf-8")
    parse_record_path.write_text(json.dumps(parse_record, ensure_ascii=False, indent=2), encoding="utf-8")
    quality_report_path.write_text(json.dumps(quality_report, ensure_ascii=False, indent=2), encoding="utf-8")
    chunk_manifest_path, chunks_jsonl_path = _write_chunks(output_dir, chunks_payload)

    result = {
        "tool": "aok_pdf_aliyun_multimodal_parse",
        "pdf_path": str(pdf_file),
        "output_root": str(_resolve_path(output_root, field_name="output_root")),
        "output_dir": str(output_dir),
        "output_name": final_output_name,
        "structured_tree_path": str(structured_tree_path),
        "elements_path": str(elements_path),
        "attachments_manifest_path": str(attachments_manifest_path),
        "linear_index_path": str(linear_index_path),
        "chunk_manifest_path": str(chunk_manifest_path),
        "chunks_jsonl_path": str(chunks_jsonl_path),
        "reconstructed_markdown_path": str(reconstructed_markdown_path),
        "parse_record_path": str(parse_record_path),
        "quality_report_path": str(quality_report_path),
        "page_count": int(len(filtered_page_records)),
        "element_count": int((elements_payload.get("summary") or {}).get("element_count") or 0),
        "attachment_count": int(len(attachments)),
        "chunk_count": int((chunks_payload.get("summary") or {}).get("chunk_count") or 0),
        "llm_enabled": True,
        "llm_model": str(llm_cfg.model),
        "llm_backend": str(llm_cfg.sdk_backend),
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


__all__ = [
    "build_aliyun_multimodal_chunks",
    "generate_aok_pdf_parse_uid",
    "parse_pdf_with_aliyun_multimodal",
    "resolve_aok_pdf_parse_output_dir",
]