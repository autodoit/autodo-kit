"""PDF 结构化元素提取工具测试（从 BabelDOC）。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import extract_pdf_elements_from_structured_data, extract_pdf_elements_from_structured_file


def test_extract_pdf_elements_from_structured_data_should_flatten_sections() -> None:
    """应能把 layout、images、references 统一展平。"""

    structured = {
        "schema": "aok.pdf_structured.v2",
        "source": {"pdf_name": "sample.pdf", "pdf_abs_path": "D:/sample.pdf"},
        "capabilities": {"images": {"enabled": True}, "references": {"enabled": True}},
        "layout": {
            "parse_error": None,
            "elements": [
                {
                    "page_index": 0,
                    "type": "paragraph",
                    "bbox": [10, 20, 30, 40],
                    "text": "Systemic risk matters.",
                }
            ],
        },
        "images": [
            {
                "page_index": 1,
                "page_number": 2,
                "image_path": "D:/artifacts/p2_1.png",
                "xref": 12,
            }
        ],
        "references": [
            {
                "index": 1,
                "raw": "[1] Example reference entry.",
                "source": "regex",
            }
        ],
        "tables": [],
        "formulas": [],
    }

    result = extract_pdf_elements_from_structured_data(structured)

    assert result["schema"] == "aok.pdf_structured_elements.v1"
    assert result["summary"]["element_count"] == 3
    assert result["summary"]["by_type"]["paragraph"] == 1
    assert result["summary"]["by_type"]["image"] == 1
    assert result["summary"]["by_type"]["reference"] == 1


def test_extract_pdf_elements_from_structured_file_should_write_output(tmp_path: Path) -> None:
    """应能从文件读取并写出结果。"""

    input_path = (tmp_path / "sample.structured.json").resolve()
    output_path = (tmp_path / "sample.elements.json").resolve()

    input_path.write_text(
        """
{
  "schema": "aok.pdf_structured.v2",
  "source": {"pdf_name": "sample.pdf", "pdf_abs_path": "D:/sample.pdf"},
  "layout": {"elements": []},
  "images": [],
  "references": [
    {"index": 1, "raw": "ref one"}
  ],
  "tables": [],
  "formulas": []
}
        """.strip(),
        encoding="utf-8",
    )

    result = extract_pdf_elements_from_structured_file(input_path, output_path=output_path)

    assert result["summary"]["element_count"] == 1
    assert output_path.exists() is True
