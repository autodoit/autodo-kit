"""在线检索下载/抽取规则判定工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_BOOK_TOKENS = [
    "著作",
    "专著",
    "图书",
    "book",
    "books",
    "monograph",
    "monographs",
    "textbook",
    "handbook",
]

DEFAULT_CNKI_THESIS_TOKENS = [
    "学位论文",
    "博士",
    "硕士",
    "博士学位",
    "硕士学位",
    "dissertation",
    "thesis",
    "cmfd",
    "cdfd",
]


@dataclass
class PolicyDecision:
    skip: bool
    reason: str
    matched_tokens: list[str]


def _lower_tokens(values: list[str]) -> list[str]:
    return [str(item).strip().lower() for item in values if str(item).strip()]


def _collect_text(record: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in [
        "title",
        "journal",
        "database",
        "doc_type",
        "document_type",
        "literature_type",
        "source_type",
        "type",
        "category",
        "record_type",
        "detail_url",
        "href",
        "landing_url",
        "pdf_url",
    ]:
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return " ".join(parts).lower()


def _match_tokens(text: str, tokens: list[str]) -> list[str]:
    lowered = _lower_tokens(tokens)
    return [token for token in lowered if token and token in text]


def evaluate_policy(record: dict[str, Any], rules: dict[str, Any], *, channel: str, source: str) -> PolicyDecision:
    text = _collect_text(record)

    book_tokens = list(rules.get("book_type_tokens") or DEFAULT_BOOK_TOKENS)
    thesis_tokens = list(rules.get("cnki_thesis_tokens") or DEFAULT_CNKI_THESIS_TOKENS)

    if channel == "download" and bool(rules.get("skip_books_for_download", True)):
        matched = _match_tokens(text, book_tokens)
        if matched:
            return PolicyDecision(skip=True, reason="book_skipped_for_download", matched_tokens=matched)

    if channel == "html_extract" and bool(rules.get("skip_books_for_html_extract", True)):
        matched = _match_tokens(text, book_tokens)
        if matched:
            return PolicyDecision(skip=True, reason="book_skipped_for_html_extract", matched_tokens=matched)

    if (
        channel == "html_extract"
        and source == "zh_cnki"
        and bool(rules.get("skip_cnki_thesis_html_extract", True))
    ):
        matched = _match_tokens(text, thesis_tokens)
        if matched:
            return PolicyDecision(skip=True, reason="cnki_thesis_skipped_for_html_extract", matched_tokens=matched)

    return PolicyDecision(skip=False, reason="", matched_tokens=[])
