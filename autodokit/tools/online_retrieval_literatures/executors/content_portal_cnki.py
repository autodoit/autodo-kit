"""CNKI 内容门户执行器。"""

from __future__ import annotations

from typing import Any

from autodokit.tools.online_retrieval_literatures.zh_cnki_search_metadata import search_metadata as zh_search_metadata
from autodokit.tools.online_retrieval_literatures.zh_cnki_single_fulltext_download import download_single as zh_single_download
from autodokit.tools.online_retrieval_literatures.zh_cnki_single_html_extract import extract_single as zh_single_html
from autodokit.tools.online_retrieval_literatures.orchestrators.input_normalizer import resolve_content_single_payload


def execute_cnki_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return zh_search_metadata(payload)


def execute_cnki_single_download(payload: dict[str, Any]) -> dict[str, Any]:
    resolved_payload = resolve_content_single_payload(payload, query_field="zh_query")
    return zh_single_download(resolved_payload)


def execute_cnki_single_structured(payload: dict[str, Any]) -> dict[str, Any]:
    resolved_payload = resolve_content_single_payload(payload, query_field="query")
    return zh_single_html(resolved_payload)
