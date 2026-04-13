"""SPIS 内容门户执行器。

当前仓库尚未提供独立 SPIS 抓取实现，因此采用
“画像驱动委派”策略：
1. 中文画像优先走 CNKI 执行器。
2. 英文画像优先走开放平台执行器。
3. mixed 画像先尝试开放平台，再回退 CNKI。
"""

from __future__ import annotations

from typing import Any

from autodokit.tools.online_retrieval_literatures.executors.content_portal_cnki import (
    execute_cnki_metadata,
    execute_cnki_single_download,
    execute_cnki_single_structured,
)
from autodokit.tools.online_retrieval_literatures.executors.open_platform import (
    execute_open_metadata,
    execute_open_single_download,
    execute_open_single_structured,
)


def _delegate(payload: dict[str, Any], *, request_profile: str, zh_func: Any, en_func: Any) -> dict[str, Any]:
    patched_payload = dict(payload)
    patched_payload["source"] = "spis"

    if request_profile == "zh":
        result = zh_func(patched_payload)
        result["spis_delegate"] = "zh_cnki"
        return result

    if request_profile == "en":
        result = en_func(patched_payload)
        result["spis_delegate"] = "en_open_access"
        return result

    try:
        result = en_func(patched_payload)
        result["spis_delegate"] = "en_open_access"
        result["spis_fallback_used"] = False
        return result
    except Exception:  # noqa: BLE001
        fallback = zh_func(patched_payload)
        fallback["spis_delegate"] = "zh_cnki"
        fallback["spis_fallback_used"] = True
        return fallback


def execute_spis_metadata(payload: dict[str, Any], *, request_profile: str) -> dict[str, Any]:
    return _delegate(payload, request_profile=request_profile, zh_func=execute_cnki_metadata, en_func=execute_open_metadata)


def execute_spis_single_download(payload: dict[str, Any], *, request_profile: str) -> dict[str, Any]:
    return _delegate(payload, request_profile=request_profile, zh_func=execute_cnki_single_download, en_func=execute_open_single_download)


def execute_spis_single_structured(payload: dict[str, Any], *, request_profile: str) -> dict[str, Any]:
    return _delegate(payload, request_profile=request_profile, zh_func=execute_cnki_single_structured, en_func=execute_open_single_structured)
