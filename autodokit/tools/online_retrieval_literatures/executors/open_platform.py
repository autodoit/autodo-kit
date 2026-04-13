"""开放平台执行器。"""

from __future__ import annotations

from typing import Any

from autodokit.tools.online_retrieval_literatures.en_open_access_search_metadata import search_metadata as en_search_metadata
from autodokit.tools.online_retrieval_literatures.en_open_access_single_fulltext_download import _to_record as en_to_record
from autodokit.tools.online_retrieval_literatures.en_open_access_single_fulltext_download import download_single as en_single_download
from autodokit.tools.online_retrieval_literatures.en_open_access_single_html_extract import extract_single as en_single_html
from autodokit.tools.online_retrieval_literatures.orchestrators.input_normalizer import resolve_en_single_record


def execute_open_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return en_search_metadata(payload)


def execute_open_single_download(payload: dict[str, Any]) -> dict[str, Any]:
    record_payload = resolve_en_single_record(payload)
    if not isinstance(record_payload, dict):
        raise ValueError("en_open_access single download 需要 record，或可解析的 seed 输入。")
    return en_single_download(payload, en_to_record(record_payload))


def execute_open_single_structured(payload: dict[str, Any]) -> dict[str, Any]:
    record_payload = resolve_en_single_record(payload)
    if not isinstance(record_payload, dict):
        raise ValueError("en_open_access single html_extract 需要 record，或可解析的 seed 输入。")
    return en_single_html(payload, record_payload)
