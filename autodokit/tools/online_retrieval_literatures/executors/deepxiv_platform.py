"""DeepXiv 执行器。"""

from __future__ import annotations

from typing import Any

from autodokit.tools.online_retrieval_literatures.deepxiv_client import download_single as deepxiv_download_single
from autodokit.tools.online_retrieval_literatures.deepxiv_client import search_metadata as deepxiv_search_metadata
from autodokit.tools.online_retrieval_literatures.orchestrators.input_normalizer import resolve_en_single_record


def execute_deepxiv_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """执行 DeepXiv metadata 检索。"""

    return deepxiv_search_metadata(payload)


def execute_deepxiv_single_download(payload: dict[str, Any]) -> dict[str, Any]:
    """执行 DeepXiv 单条 PDF 物化。"""

    record_payload = resolve_en_single_record(payload)
    if not isinstance(record_payload, dict):
        raise ValueError("deepxiv single download 需要 record，或可解析的 seed 输入。")
    return deepxiv_download_single(payload, record_payload)