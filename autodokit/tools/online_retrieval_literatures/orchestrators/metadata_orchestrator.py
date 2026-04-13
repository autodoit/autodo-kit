"""metadata 编排器。"""

from __future__ import annotations

from typing import Any

from autodokit.tools.online_retrieval_literatures.catalogs import source_family
from autodokit.tools.online_retrieval_literatures.executors.content_portal_cnki import execute_cnki_metadata
from autodokit.tools.online_retrieval_literatures.executors.content_portal_spis import execute_spis_metadata
from autodokit.tools.online_retrieval_literatures.executors.open_platform import execute_open_metadata


def run_metadata(payload: dict[str, Any], *, source: str, request_profile: str) -> dict[str, Any]:
    """执行 metadata 编排。

    Args:
        payload: 原始路由 payload。
        source: 规范化后的来源。
        request_profile: 请求画像。

    Returns:
        dict[str, Any]: metadata 执行结果。
    """
    family = source_family(source)
    if family == "content_portal":
        if source == "zh_cnki":
            return execute_cnki_metadata(payload)
        if source == "spis":
            return execute_spis_metadata(payload, request_profile=request_profile)
    if family == "open_platform":
        return execute_open_metadata(payload)
    raise ValueError(f"metadata 不支持的来源: source={source}")
