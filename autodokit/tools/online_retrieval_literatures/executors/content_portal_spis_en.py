"""SPIS 英文链执行器。"""

from __future__ import annotations

from typing import Any

from autodokit.tools.online_retrieval_literatures.executors.open_platform import (
    execute_open_metadata,
    execute_open_single_download,
    execute_open_single_structured,
)


def execute_spis_en_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return execute_open_metadata(payload)


def execute_spis_en_single_download(payload: dict[str, Any]) -> dict[str, Any]:
    return execute_open_single_download(payload)


def execute_spis_en_single_structured(payload: dict[str, Any]) -> dict[str, Any]:
    return execute_open_single_structured(payload)
