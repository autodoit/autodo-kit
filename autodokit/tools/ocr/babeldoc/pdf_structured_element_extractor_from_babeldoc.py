"""PDF 结构化 JSON 元素提取工具。

本模块负责从 AOK 当前的 PDF 结构化主表示中，提取适合下游检索、审阅、
多模态调度和审计的统一元素列表。

设计目标：
- 统一消费 `aok.pdf_structured.v2` 结构；
- 尽可能兼容字段缺失、弱结构和 BabelDOC 中间产物解析不稳定的情况；
- 输出 JSON 友好结果，便于直接落盘、索引或送给 LLM/视觉模型。

当前支持的元素来源：
- layout.elements
- images
- references
- tables
- formulas

注意：
- 本工具不重新解析 PDF；它只处理已经生成好的 structured JSON。
- 若 structured JSON 中某类元素尚未抽取成功，本工具会在 summary 中如实反映。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _stable_hash(payload: str) -> str:
    """生成稳定短哈希。"""

    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _load_json(path: Path) -> Dict[str, Any]:
    """读取结构化 JSON。"""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"structured JSON 顶层必须是对象：{path}")
    return raw


def _coerce_int(value: Any) -> Optional[int]:
    """将页码等值转换为 int。"""

    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _coerce_bbox(value: Any) -> Optional[Dict[str, float]]:
    """把 bbox 值转换为统一格式。"""

    if value is None:
        return None

    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            x0, y0, x1, y1 = [float(v) for v in value]
            return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
        except Exception:
            return None

    if isinstance(value, dict):
        keys = set(value.keys())
        if {"x0", "y0", "x1", "y1"}.issubset(keys):
            try:
                return {
                    "x0": float(value["x0"]),
                    "y0": float(value["y0"]),
                    "x1": float(value["x1"]),
                    "y1": float(value["y1"]),
                }
            except Exception:
                return None
        if {"left", "top", "right", "bottom"}.issubset(keys):
            try:
                return {
                    "x0": float(value["left"]),
                    "y0": float(value["top"]),
                    "x1": float(value["right"]),
                    "y1": float(value["bottom"]),
                }
            except Exception:
                return None

    return None


def _build_element_uid(*, element_type: str, page_index: Optional[int], anchor: str) -> str:
    """生成元素稳定 UID。"""

    page_token = "na" if page_index is None else str(page_index)
    digest = _stable_hash(f"{element_type}|{page_token}|{anchor}")
    return f"el-{element_type}-{page_token}-{digest}"


def _normalize_layout_elements(layout: Dict[str, Any]) -> List[Dict[str, Any]]:
    """规范化 layout.elements。"""

    raw_elements = layout.get("elements") if isinstance(layout, dict) else []
    if not isinstance(raw_elements, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for item in raw_elements:
        if not isinstance(item, dict):
            continue

        page_index = _coerce_int(
            item.get("page_index")
            if item.get("page_index") is not None
            else item.get("page")
        )
        element_type = str(item.get("type") or "layout_item").strip() or "layout_item"
        bbox = _coerce_bbox(item.get("bbox"))
        text = item.get("text") if isinstance(item.get("text"), str) else None
        source_artifact = str(item.get("source_artifact") or "")

        anchor = json.dumps(
            {
                "bbox": bbox,
                "text": (text or "")[:200],
                "source_artifact": source_artifact,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        normalized.append(
            {
                "element_uid": _build_element_uid(
                    element_type=element_type,
                    page_index=page_index,
                    anchor=anchor,
                ),
                "element_type": element_type,
                "source_section": "layout.elements",
                "page_index": page_index,
                "page_number": None if page_index is None else page_index + 1,
                "bbox": bbox,
                "text": text,
                "artifact_path": source_artifact or None,
                "meta": {
                    "raw_type": item.get("type"),
                },
            }
        )

    return normalized


def _normalize_image_elements(images: Iterable[Any]) -> List[Dict[str, Any]]:
    """规范化 images。"""

    normalized: List[Dict[str, Any]] = []
    for item in images:
        if not isinstance(item, dict):
            continue

        page_index = _coerce_int(item.get("page_index"))
        image_path = str(item.get("image_path") or "")
        anchor = json.dumps(
            {
                "image_path": image_path,
                "xref": item.get("xref"),
                "page_index": page_index,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        normalized.append(
            {
                "element_uid": _build_element_uid(
                    element_type="image",
                    page_index=page_index,
                    anchor=anchor,
                ),
                "element_type": "image",
                "source_section": "images",
                "page_index": page_index,
                "page_number": _coerce_int(item.get("page_number")) or (None if page_index is None else page_index + 1),
                "bbox": None,
                "text": None,
                "artifact_path": image_path or None,
                "meta": {
                    "ext": item.get("ext"),
                    "xref": item.get("xref"),
                    "source": item.get("source"),
                },
            }
        )

    return normalized


def _normalize_reference_elements(references: Iterable[Any]) -> List[Dict[str, Any]]:
    """规范化 references。"""

    normalized: List[Dict[str, Any]] = []
    for item in references:
        if not isinstance(item, dict):
            continue

        raw = str(item.get("raw") or "").strip()
        if not raw:
            continue

        anchor = json.dumps(
            {
                "index": item.get("index"),
                "raw": raw[:400],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        normalized.append(
            {
                "element_uid": _build_element_uid(
                    element_type="reference",
                    page_index=None,
                    anchor=anchor,
                ),
                "element_type": "reference",
                "source_section": "references",
                "page_index": None,
                "page_number": None,
                "bbox": None,
                "text": raw,
                "artifact_path": None,
                "meta": {
                    "index": item.get("index"),
                    "marker": item.get("marker"),
                    "source": item.get("source"),
                },
            }
        )

    return normalized


def _normalize_generic_elements(items: Iterable[Any], *, source_section: str, element_type: str) -> List[Dict[str, Any]]:
    """规范化 tables/formulas 等弱结构数组。"""

    normalized: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            page_index = _coerce_int(item.get("page_index") or item.get("page"))
            bbox = _coerce_bbox(item.get("bbox") or item.get("box") or item.get("rect"))
            text = item.get("text") if isinstance(item.get("text"), str) else None
            artifact_path = str(item.get("artifact_path") or item.get("image_path") or "")
            anchor = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)[:1000]
            meta = dict(item)
        else:
            page_index = None
            bbox = None
            text = str(item)
            artifact_path = ""
            anchor = text[:400]
            meta = {"raw": item}

        normalized.append(
            {
                "element_uid": _build_element_uid(
                    element_type=element_type,
                    page_index=page_index,
                    anchor=anchor,
                ),
                "element_type": element_type,
                "source_section": source_section,
                "page_index": page_index,
                "page_number": None if page_index is None else page_index + 1,
                "bbox": bbox,
                "text": text,
                "artifact_path": artifact_path or None,
                "meta": meta,
            }
        )

    return normalized


def _count_by(items: Iterable[Dict[str, Any]], *, key: str) -> Dict[str, int]:
    """按字段计数。"""

    counts: Dict[str, int] = {}
    for item in items:
        value = item.get(key)
        label = "null" if value is None else str(value)
        counts[label] = counts.get(label, 0) + 1
    return counts


def extract_pdf_elements_from_structured_data(
    structured_data: Dict[str, Any],
    *,
    include_sections: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """从 PDF 结构化主表示中提取统一元素列表。

    Args:
        structured_data: `aok.pdf_structured.v2` 对象。
        include_sections: 限制提取的来源分区，例如 `layout.elements`、`images`。

    Returns:
        dict: 统一元素结果，包含 summary 与 elements。
    """

    if not isinstance(structured_data, dict):
        raise ValueError("structured_data 必须是字典")

    allowed = set(str(x).strip() for x in include_sections or [])
    use_filter = bool(allowed)

    elements: List[Dict[str, Any]] = []

    def should_include(section: str) -> bool:
        return (not use_filter) or (section in allowed)

    layout = structured_data.get("layout") if isinstance(structured_data.get("layout"), dict) else {}
    if should_include("layout.elements"):
        elements.extend(_normalize_layout_elements(layout))

    images = structured_data.get("images") if isinstance(structured_data.get("images"), list) else []
    if should_include("images"):
        elements.extend(_normalize_image_elements(images))

    references = structured_data.get("references") if isinstance(structured_data.get("references"), list) else []
    if should_include("references"):
        elements.extend(_normalize_reference_elements(references))

    tables = structured_data.get("tables") if isinstance(structured_data.get("tables"), list) else []
    if should_include("tables"):
        elements.extend(_normalize_generic_elements(tables, source_section="tables", element_type="table"))

    formulas = structured_data.get("formulas") if isinstance(structured_data.get("formulas"), list) else []
    if should_include("formulas"):
        elements.extend(_normalize_generic_elements(formulas, source_section="formulas", element_type="formula"))

    elements.sort(
        key=lambda item: (
            10**9 if item.get("page_index") is None else int(item["page_index"]),
            str(item.get("element_type") or ""),
            str(item.get("element_uid") or ""),
        )
    )

    summary = {
        "element_count": len(elements),
        "by_type": _count_by(elements, key="element_type"),
        "by_page": _count_by(elements, key="page_number"),
        "by_source_section": _count_by(elements, key="source_section"),
        "capabilities": structured_data.get("capabilities") if isinstance(structured_data.get("capabilities"), dict) else {},
        "layout_parse_error": ((structured_data.get("layout") or {}).get("parse_error") if isinstance(structured_data.get("layout"), dict) else None),
        "babeldoc_error": (((structured_data.get("babeldoc_artifacts") or {}).get("babeldoc_error")) if isinstance(structured_data.get("babeldoc_artifacts"), dict) else None),
    }

    return {
        "schema": "aok.pdf_structured_elements.v1",
        "source": structured_data.get("source") if isinstance(structured_data.get("source"), dict) else {},
        "summary": summary,
        "elements": elements,
    }


def extract_pdf_elements_from_structured_file(
    structured_json_path: Path,
    *,
    output_path: Optional[Path] = None,
    include_sections: Optional[Iterable[str]] = None,
    encoding: str = "utf-8",
) -> Dict[str, Any]:
    """从结构化 JSON 文件提取元素，并可选写回磁盘。

    Args:
        structured_json_path: 结构化 JSON 绝对路径。
        output_path: 可选输出 JSON 路径。
        include_sections: 限制提取来源分区。
        encoding: 输出编码。

    Returns:
        dict: 提取结果。
    """

    if not structured_json_path.is_absolute():
        raise ValueError(f"structured_json_path 必须是绝对路径：{structured_json_path}")
    if not structured_json_path.exists() or not structured_json_path.is_file():
        raise ValueError(f"structured_json_path 必须是存在的文件：{structured_json_path}")

    structured_data = _load_json(structured_json_path)
    result = extract_pdf_elements_from_structured_data(
        structured_data,
        include_sections=include_sections,
    )

    if output_path is not None:
        if not output_path.is_absolute():
            raise ValueError(f"output_path 必须是绝对路径：{output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding=encoding,
        )

    return result


__all__ = [
    "extract_pdf_elements_from_structured_data",
    "extract_pdf_elements_from_structured_file",
]