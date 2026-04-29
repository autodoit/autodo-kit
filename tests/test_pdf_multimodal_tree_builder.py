"""高精度多模态结构树工具测试。"""

from __future__ import annotations

from autodokit.tools.old.ocr.aliyun_multimodal.pdf_multimodal_tree_builder import (
    build_elements_payload,
    build_quality_report,
    build_tree_linear_index,
    build_structure_tree,
    normalize_node_type,
    render_reconstructed_markdown,
)


def test_normalize_node_type_should_map_aliases() -> None:
    """应把常见别名映射到受控枚举。"""

    assert normalize_node_type("title") == "document_title"
    assert normalize_node_type("image") == "figure"
    assert normalize_node_type("unknown") == "paragraph"


def test_build_structure_tree_should_group_sections_and_references() -> None:
    """应能从元素流构建 section 与 references_section。"""

    source = {"title": "Demo Document", "backend": "multimodal_high_precision_v1"}
    page_records = [{"page_index": 0, "page_number": 1, "image_path": "/tmp/page_0001.png"}]
    page_results = [
        {
            "page_index": 0,
            "elements": [
                {"node_type": "title", "text": "Demo Document", "confidence": 0.9, "bbox": None, "heading_level": 0, "reading_order": 1},
                {"node_type": "heading", "text": "Introduction", "confidence": 0.9, "bbox": None, "heading_level": 1, "reading_order": 2},
                {"node_type": "paragraph", "text": "First paragraph.", "confidence": 0.8, "bbox": None, "heading_level": 0, "reading_order": 3},
                {"node_type": "reference_item", "text": "[1] Example reference", "confidence": 0.8, "bbox": None, "heading_level": 0, "reading_order": 4},
            ],
        }
    ]

    elements_payload = build_elements_payload(source=source, page_records=page_records, page_results=page_results)
    tree_payload, _ = build_structure_tree(elements_payload)
    quality = build_quality_report(elements_payload=elements_payload, tree_payload=tree_payload, attachments=[])

    node_types = [str(node.get("node_type") or "") for node in tree_payload["nodes"]]
    assert "document" in node_types
    assert "front_matter" in node_types
    assert "section" in node_types
    assert "references_section" in node_types
    assert quality["tree_legal_rate"] == 1.0


def test_build_tree_linear_index_should_stitch_tree_elements_and_attachments() -> None:
    """应生成可按顺序重建内容的串联索引。"""

    source = {"title": "Demo Document", "backend": "multimodal_high_precision_v1"}
    page_records = [{"page_index": 0, "page_number": 1, "image_path": "/tmp/page_0001.png"}]
    page_results = [
        {
            "page_index": 0,
            "elements": [
                {"node_type": "title", "text": "Demo Document", "confidence": 0.9, "bbox": None, "heading_level": 0, "reading_order": 1},
                {"node_type": "heading", "text": "Introduction", "confidence": 0.9, "bbox": None, "heading_level": 1, "reading_order": 2},
                {"node_type": "paragraph", "text": "First paragraph.", "confidence": 0.8, "bbox": None, "heading_level": 0, "reading_order": 3},
            ],
        }
    ]

    elements_payload = build_elements_payload(source=source, page_records=page_records, page_results=page_results)
    tree_payload, _ = build_structure_tree(elements_payload)
    attachments = [
        {
            "attachment_id": "attachment_00001",
            "attachment_type": "figure",
            "storage_path": "/tmp/figure_0001.png",
            "page_index": 0,
            "bbox": [1, 2, 3, 4],
            "linked_node_id": "tree_00003",
            "render_method": "crop_from_page_image",
        }
    ]
    tree_payload["nodes"][2]["attachment_refs"] = ["attachment_00001"]

    linear_index = build_tree_linear_index(
        tree_payload=tree_payload,
        elements_payload=elements_payload,
        attachments=attachments,
    )
    markdown_text = render_reconstructed_markdown(linear_index)

    assert linear_index["schema"] == "aok.pdf_tree_linear_index.v1"
    assert linear_index["summary"]["entry_count"] >= 3
    assert "Introduction" in markdown_text
    assert "First paragraph." in markdown_text


def test_build_elements_payload_should_prefer_canonical_page_index() -> None:
    """当模型回传页号错误时，应优先使用 canonical_page_index。"""

    source = {"title": "Demo Document", "backend": "multimodal_high_precision_v1"}
    page_records = [
        {"page_index": 0, "page_number": 1, "image_path": "/tmp/page_0001.png"},
        {"page_index": 1, "page_number": 2, "image_path": "/tmp/page_0002.png"},
    ]
    page_results = [
        {
            "page_index": 0,
            "canonical_page_index": 1,
            "page_parse_status": "inspection_failed_fallback",
            "elements": [
                {
                    "node_type": "paragraph",
                    "text": "Fallback content on page 2.",
                    "confidence": 0.2,
                    "bbox": None,
                    "heading_level": 0,
                    "reading_order": 1,
                }
            ],
        }
    ]

    elements_payload = build_elements_payload(source=source, page_records=page_records, page_results=page_results)
    item = elements_payload["items"][0]

    assert item["page_index"] == 1
    assert item["page_number"] == 2
    assert item["page_parse_status"] == "inspection_failed_fallback"
