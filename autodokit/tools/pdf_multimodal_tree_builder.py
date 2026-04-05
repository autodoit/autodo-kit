"""高精度多模态解析结果的树构建、串联索引与质量评估工具。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple


ALLOWED_NODE_TYPES = {
    "document_title",
    "heading",
    "paragraph",
    "figure",
    "figure_caption",
    "table",
    "table_caption",
    "formula",
    "formula_caption",
    "footnote",
    "reference_item",
    "citation_anchor",
    "author_block",
    "affiliation_block",
    "abstract_block",
    "keywords_block",
}


def normalize_node_type(value: Any) -> str:
    """把模型返回的元素类型收敛为受控枚举。"""

    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    alias_map = {
        "title": "document_title",
        "paper_title": "document_title",
        "section_title": "heading",
        "subsection_title": "heading",
        "text": "paragraph",
        "body_text": "paragraph",
        "figure_image": "figure",
        "image": "figure",
        "equation": "formula",
        "references": "reference_item",
        "reference": "reference_item",
        "authors": "author_block",
        "author": "author_block",
        "affiliation": "affiliation_block",
        "abstract": "abstract_block",
        "keywords": "keywords_block",
    }
    normalized = alias_map.get(raw, raw)
    return normalized if normalized in ALLOWED_NODE_TYPES else "paragraph"


def build_elements_payload(
    *,
    source: Dict[str, Any],
    page_records: List[Dict[str, Any]],
    page_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """把逐页解析结果展平为统一元素流。"""

    page_map = {int(item.get("page_index") or 0): item for item in page_records}
    items: List[Dict[str, Any]] = []
    counter = 0
    for page_result in page_results:
        page_index = int(page_result.get("page_index") or 0)
        page_info = page_map.get(page_index) or {}
        for order, raw_element in enumerate(page_result.get("elements") or [], start=1):
            counter += 1
            node_type = normalize_node_type(raw_element.get("node_type"))
            bbox = raw_element.get("bbox") if isinstance(raw_element.get("bbox"), list) and len(raw_element.get("bbox")) == 4 else None
            items.append(
                {
                    "node_id": f"element_{counter:05d}",
                    "node_type": node_type,
                    "page_index": page_index,
                    "page_number": int(page_index + 1),
                    "bbox": bbox,
                    "reading_order": int(raw_element.get("reading_order") or order),
                    "text": str(raw_element.get("text") or "").strip(),
                    "confidence": float(raw_element.get("confidence") or 0.0),
                    "source_ref": {
                        "page_image_path": str(page_info.get("image_path") or ""),
                        "page_number": int(page_index + 1),
                    },
                    "heading_level": int(raw_element.get("heading_level") or 0),
                }
            )

    items.sort(key=lambda row: (int(row.get("page_index") or 0), int(row.get("reading_order") or 0), str(row.get("node_id") or "")))
    summary = Counter(str(item.get("node_type") or "") for item in items)
    return {
        "schema": "aok.pdf_multimodal_elements.v1",
        "source": dict(source),
        "items": items,
        "summary": {
            "element_count": int(len(items)),
            "by_type": dict(summary),
            "page_count": int(len(page_records)),
        },
    }


def build_structure_tree(elements_payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """根据元素流构建最小可用树结构。"""

    items = elements_payload.get("items") if isinstance(elements_payload.get("items"), list) else []
    nodes: List[Dict[str, Any]] = []
    element_to_node: Dict[str, str] = {}

    def add_node(node_type: str, *, parent_id: str | None, title: str = "", page_index: int | None = None, element_refs: List[str] | None = None) -> str:
        node_id = f"tree_{len(nodes) + 1:05d}"
        node = {
            "node_id": node_id,
            "parent_id": parent_id or "",
            "children_ids": [],
            "node_type": node_type,
            "title": title,
            "page_span": [page_index + 1, page_index + 1] if isinstance(page_index, int) else [],
            "element_refs": list(element_refs or []),
            "attachment_refs": [],
        }
        nodes.append(node)
        if parent_id:
            for candidate in nodes:
                if candidate["node_id"] == parent_id:
                    candidate["children_ids"].append(node_id)
                    if isinstance(page_index, int):
                        if not candidate["page_span"]:
                            candidate["page_span"] = [page_index + 1, page_index + 1]
                        else:
                            candidate["page_span"][0] = min(candidate["page_span"][0], page_index + 1)
                            candidate["page_span"][1] = max(candidate["page_span"][1], page_index + 1)
                    break
        return node_id

    root_id = add_node("document", parent_id=None, title=str((elements_payload.get("source") or {}).get("title") or ""))
    front_id = add_node("front_matter", parent_id=root_id)
    current_section_stack: Dict[int, str] = {}
    latest_group_by_page: Dict[tuple[int, str], str] = {}
    references_section_id = ""

    for item in items:
        item_id = str(item.get("node_id") or "")
        node_type = str(item.get("node_type") or "paragraph")
        text = str(item.get("text") or "").strip()
        page_index = int(item.get("page_index") or 0)

        if node_type == "document_title":
            element_to_node[item_id] = front_id
            continue

        if node_type in {"author_block", "affiliation_block", "abstract_block", "keywords_block"}:
            element_to_node[item_id] = front_id
            continue

        if node_type == "heading":
            level = int(item.get("heading_level") or 1)
            level = max(1, min(level, 6))
            parent_id = root_id if level == 1 else current_section_stack.get(level - 1, root_id)
            tree_type = "section" if level == 1 else "subsection"
            node_id = add_node(tree_type, parent_id=parent_id, title=text, page_index=page_index, element_refs=[item_id])
            current_section_stack[level] = node_id
            for key in list(current_section_stack.keys()):
                if key > level:
                    current_section_stack.pop(key, None)
            element_to_node[item_id] = node_id
            continue

        if node_type == "reference_item":
            if not references_section_id:
                references_section_id = add_node("references_section", parent_id=root_id, title="References")
            node_id = add_node("reference_item", parent_id=references_section_id, title=text[:80], page_index=page_index, element_refs=[item_id])
            element_to_node[item_id] = node_id
            continue

        parent_id = current_section_stack.get(max(current_section_stack.keys(), default=0), front_id) if current_section_stack else front_id
        if node_type in {"figure", "table", "formula"}:
            group_type = f"{node_type}_group"
            node_id = add_node(group_type, parent_id=parent_id, title=text[:80], page_index=page_index, element_refs=[item_id])
            latest_group_by_page[(page_index, node_type)] = node_id
            element_to_node[item_id] = node_id
            continue
        if node_type in {"figure_caption", "table_caption", "formula_caption"}:
            base_type = node_type.replace("_caption", "")
            node_id = latest_group_by_page.get((page_index, base_type), "")
            if node_id:
                for candidate in nodes:
                    if candidate["node_id"] == node_id:
                        candidate["element_refs"].append(item_id)
                        break
                element_to_node[item_id] = node_id
                continue

        node_id = add_node("paragraph_group", parent_id=parent_id, title=text[:80], page_index=page_index, element_refs=[item_id])
        element_to_node[item_id] = node_id

    return {
        "schema": "aok.pdf_structured_tree.v1",
        "source": dict(elements_payload.get("source") or {}),
        "root_id": root_id,
        "nodes": nodes,
    }, element_to_node


def build_quality_report(*, elements_payload: Dict[str, Any], tree_payload: Dict[str, Any], attachments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """生成最小质量报告。"""

    nodes = tree_payload.get("nodes") if isinstance(tree_payload.get("nodes"), list) else []
    items = elements_payload.get("items") if isinstance(elements_payload.get("items"), list) else []
    valid_parent_count = 0
    node_ids = {str(node.get("node_id") or "") for node in nodes}
    for node in nodes:
        parent_id = str(node.get("parent_id") or "")
        if not parent_id or parent_id in node_ids:
            valid_parent_count += 1
    tree_legal_rate = (valid_parent_count / len(nodes)) if nodes else 0.0
    return {
        "schema": "aok.pdf_multimodal_quality_report.v1",
        "element_count": int(len(items)),
        "tree_node_count": int(len(nodes)),
        "attachment_count": int(len(attachments)),
        "tree_legal_rate": round(tree_legal_rate, 4),
        "figure_like_count": int(sum(1 for item in items if str(item.get("node_type") or "") in {"figure", "table", "formula"})),
        "reference_item_count": int(sum(1 for item in items if str(item.get("node_type") or "") == "reference_item")),
        "warnings": [],
    }


def build_tree_linear_index(
    *,
    tree_payload: Dict[str, Any],
    elements_payload: Dict[str, Any],
    attachments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """遍历结构树，生成可重建内容顺序的串联索引。"""

    nodes = tree_payload.get("nodes") if isinstance(tree_payload.get("nodes"), list) else []
    root_id = str(tree_payload.get("root_id") or "")
    items = elements_payload.get("items") if isinstance(elements_payload.get("items"), list) else []

    node_map = {str(node.get("node_id") or ""): node for node in nodes}
    element_map = {str(item.get("node_id") or ""): item for item in items}
    attachment_map = {str(item.get("attachment_id") or ""): item for item in attachments}
    entries: List[Dict[str, Any]] = []

    def append_entry(entry: Dict[str, Any]) -> None:
        payload = dict(entry)
        payload["index"] = len(entries) + 1
        entries.append(payload)

    def _entry_page_index_from_node(node: Dict[str, Any]) -> int:
        page_span = node.get("page_span") if isinstance(node.get("page_span"), list) else []
        if len(page_span) >= 1 and isinstance(page_span[0], int):
            return int(page_span[0]) - 1
        return 10**9

    def visit(node_id: str, depth: int) -> None:
        node = node_map.get(node_id)
        if not node:
            return

        node_type = str(node.get("node_type") or "")
        title = str(node.get("title") or "").strip()
        if node_type in {"document", "section", "subsection", "references_section"}:
            append_entry(
                {
                    "entry_kind": "tree_node",
                    "node_id": node_id,
                    "parent_id": str(node.get("parent_id") or ""),
                    "depth": int(depth),
                    "node_type": node_type,
                    "page_index": _entry_page_index_from_node(node),
                    "reading_order": 0,
                    "text": title,
                    "attachment_refs": list(node.get("attachment_refs") or []),
                    "element_refs": list(node.get("element_refs") or []),
                }
            )

        element_refs = node.get("element_refs") if isinstance(node.get("element_refs"), list) else []
        for order, element_id in enumerate(element_refs, start=1):
            item = element_map.get(str(element_id))
            if not item:
                continue
            append_entry(
                {
                    "entry_kind": "element",
                    "node_id": node_id,
                    "element_id": str(element_id),
                    "parent_id": str(node.get("parent_id") or ""),
                    "depth": int(depth),
                    "node_type": node_type,
                    "element_type": str(item.get("node_type") or ""),
                    "page_index": int(item.get("page_index") or 0),
                    "reading_order": int(item.get("reading_order") or order),
                    "text": str(item.get("text") or "").strip(),
                    "bbox": item.get("bbox"),
                    "source_ref": dict(item.get("source_ref") or {}),
                }
            )

        attachment_refs = node.get("attachment_refs") if isinstance(node.get("attachment_refs"), list) else []
        for attachment_id in attachment_refs:
            attachment = attachment_map.get(str(attachment_id))
            if not attachment:
                continue
            append_entry(
                {
                    "entry_kind": "attachment",
                    "node_id": node_id,
                    "attachment_id": str(attachment_id),
                    "parent_id": str(node.get("parent_id") or ""),
                    "depth": int(depth),
                    "node_type": node_type,
                    "attachment_type": str(attachment.get("attachment_type") or ""),
                    "page_index": int(attachment.get("page_index") or 0),
                    "reading_order": 10**6,
                    "text": "",
                    "storage_path": str(attachment.get("storage_path") or ""),
                    "bbox": attachment.get("bbox"),
                }
            )

        children_ids = node.get("children_ids") if isinstance(node.get("children_ids"), list) else []
        for child_id in children_ids:
            visit(str(child_id), depth + 1)

    if root_id:
        visit(root_id, 0)

    return {
        "schema": "aok.pdf_tree_linear_index.v1",
        "source": dict(tree_payload.get("source") or {}),
        "root_id": root_id,
        "entries": entries,
        "summary": {
            "entry_count": int(len(entries)),
            "element_entry_count": int(sum(1 for entry in entries if entry.get("entry_kind") == "element")),
            "attachment_entry_count": int(sum(1 for entry in entries if entry.get("entry_kind") == "attachment")),
            "tree_node_entry_count": int(sum(1 for entry in entries if entry.get("entry_kind") == "tree_node")),
        },
    }


def render_reconstructed_markdown(
    linear_index_payload: Dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> str:
    """把串联索引渲染为尽量接近原文阅读顺序的 Markdown。"""

    entries = linear_index_payload.get("entries") if isinstance(linear_index_payload.get("entries"), list) else []
    source = linear_index_payload.get("source") if isinstance(linear_index_payload.get("source"), dict) else {}
    title = str(source.get("title") or source.get("pdf_name") or "Untitled").strip()
    lines: List[str] = [f"# {title}"]
    if str(source.get("year") or "").strip():
        lines.append("")
        lines.append(f"年份：{str(source.get('year') or '').strip()}")

    for entry in entries:
        kind = str(entry.get("entry_kind") or "")
        node_type = str(entry.get("node_type") or "")
        page_index = entry.get("page_index")
        if kind == "tree_node":
            text = str(entry.get("text") or "").strip()
            if not text or node_type == "document":
                continue
            lines.append("")
            if isinstance(page_index, int) and page_index >= 0:
                lines.append(f"[Page {page_index + 1}]")
            if node_type == "section":
                lines.append(f"## {text}")
            elif node_type == "subsection":
                lines.append(f"### {text}")
            elif node_type == "references_section":
                lines.append("## References")
            else:
                lines.append(text)
            continue

        if kind == "element":
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            element_type = str(entry.get("element_type") or "")
            lines.append("")
            if element_type == "reference_item":
                lines.append(f"- {text}")
            elif element_type in {"figure_caption", "table_caption", "formula_caption"}:
                lines.append(f"*{text}*")
            elif element_type in {"document_title", "heading"}:
                lines.append(text)
            else:
                lines.append(text)
            continue

        if kind == "attachment":
            attachment_type = str(entry.get("attachment_type") or "attachment")
            storage_path = str(entry.get("storage_path") or "").strip()
            if not storage_path:
                continue
            display_path = storage_path
            if output_dir is not None:
                try:
                    display_path = str(Path(storage_path).resolve().relative_to(output_dir.resolve())).replace("\\", "/")
                except Exception:
                    display_path = storage_path
            if attachment_type == "page":
                continue
            lines.append("")
            lines.append(f"[{attachment_type.upper()}] {display_path}")

    return "\n".join(lines).strip() + "\n"