"""SPIS 内容门户执行器。

SPIS 作为统一门户入口，内部按画像做“顺序尝试链”：
1. zh: 先中文链，再英文链。
2. en: 先英文链，再中文链。
3. mixed: 先英文链，再中文链。
"""

from __future__ import annotations

from typing import Any

from autodokit.tools.online_retrieval_literatures.executors.content_portal_spis_en import (
    execute_spis_en_metadata,
    execute_spis_en_single_download,
    execute_spis_en_single_structured,
)
from autodokit.tools.online_retrieval_literatures.executors.content_portal_spis_zh import (
    execute_spis_zh_metadata,
    execute_spis_zh_single_download,
    execute_spis_zh_single_structured,
)


def _run_spis_chain(payload: dict[str, Any], *, request_profile: str, zh_func: Any, en_func: Any) -> dict[str, Any]:
    patched_payload = dict(payload)
    patched_payload["source"] = "spis"

    if request_profile == "zh":
        chain = [("spis_zh", zh_func), ("spis_en", en_func)]
    elif request_profile == "en":
        chain = [("spis_en", en_func), ("spis_zh", zh_func)]
    else:
        chain = [("spis_en", en_func), ("spis_zh", zh_func)]

    errors: list[dict[str, str]] = []
    for index, (delegate, func) in enumerate(chain, start=1):
        try:
            result = dict(func(patched_payload))
            result["spis_delegate"] = delegate
            result["spis_chain_index"] = index
            result["spis_fallback_used"] = index > 1
            return result
        except Exception as exc:  # noqa: BLE001
            errors.append({"delegate": delegate, "error": f"{exc.__class__.__name__}: {exc}"})

    return {
        "status": "BLOCKED",
        "error_type": "RuntimeError",
        "error": "SPIS 顺序尝试链全部失败。",
        "spis_chain_errors": errors,
    }


def execute_spis_metadata(payload: dict[str, Any], *, request_profile: str) -> dict[str, Any]:
    return _run_spis_chain(payload, request_profile=request_profile, zh_func=execute_spis_zh_metadata, en_func=execute_spis_en_metadata)


def execute_spis_single_download(payload: dict[str, Any], *, request_profile: str) -> dict[str, Any]:
    return _run_spis_chain(
        payload,
        request_profile=request_profile,
        zh_func=execute_spis_zh_single_download,
        en_func=execute_spis_en_single_download,
    )


def execute_spis_single_structured(payload: dict[str, Any], *, request_profile: str) -> dict[str, Any]:
    return _run_spis_chain(
        payload,
        request_profile=request_profile,
        zh_func=execute_spis_zh_single_structured,
        en_func=execute_spis_en_single_structured,
    )
