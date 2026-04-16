"""SPIS 中文链执行器。"""

from __future__ import annotations

from typing import Any

from autodokit.tools.online_retrieval_literatures.executors.content_portal_cnki import (
    execute_cnki_metadata,
    execute_cnki_single_download,
    execute_cnki_single_structured,
)


def execute_spis_zh_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return execute_cnki_metadata(payload)


def execute_spis_zh_single_download(payload: dict[str, Any]) -> dict[str, Any]:
    return execute_cnki_single_download(payload)


def execute_spis_zh_single_structured(payload: dict[str, Any]) -> dict[str, Any]:
    return execute_cnki_single_structured(payload)
