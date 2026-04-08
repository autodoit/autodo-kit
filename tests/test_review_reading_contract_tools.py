from __future__ import annotations

import json
from pathlib import Path

from autodokit.tools.review_reading_packet_tools import resolve_review_text_by_priority
from autodokit.tools.review_synthesis_tools import extract_review_state_from_structured_file


def _write_structured(path: Path, *, raw_full_text: str, full_text: str) -> Path:
    payload = {
        "schema": "aok.pdf_structured.v3",
        "source": {
            "uid_literature": "lit-001",
            "cite_key": "review-001",
            "title": "测试综述",
            "year": "2025",
            "backend": "aliyun_multimodal",
            "pdf_abs_path": str(path.with_suffix(".pdf")),
        },
        "text": {
            "raw_full_text": raw_full_text,
            "full_text": full_text,
        },
        "segments": {},
        "references": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.resolve()


def test_resolve_review_text_by_priority_should_follow_contract() -> None:
    resolved = resolve_review_text_by_priority(
        {
            "raw_full_text": "raw layer",
            "full_text": "post layer",
        },
        clean_body="",
    )

    assert resolved["selected_source"] == "raw_full_text"
    assert resolved["selected_text"] == "raw layer"


def test_extract_review_state_from_structured_file_should_use_contract_order(tmp_path: Path) -> None:
    structured_path = _write_structured(
        tmp_path / "review-001.normalized.structured.json",
        raw_full_text="原始正文第一段。\n\n原始正文第二段。",
        full_text="后处理正文。",
    )

    review_state = extract_review_state_from_structured_file(
        str(structured_path),
        uid_literature="lit-001",
        cite_key="review-001",
        title="测试综述",
        year="2025",
    )

    assert review_state["full_text_source"] in {"clean_body", "raw_full_text"}
    assert "原始正文第一段" in str(review_state.get("full_text") or "")
    assert "后处理正文" not in str(review_state.get("full_text") or "")
