"""在线检索编排调度器。"""

from __future__ import annotations

from typing import Any, Callable

from autodokit.tools.online_retrieval_literatures.catalogs import canonical_source
from autodokit.tools.online_retrieval_literatures.cnki_paged_retrieval import run_pipeline as run_cnki_pipeline
from autodokit.tools.online_retrieval_literatures.contracts import finalize_result
from autodokit.tools.online_retrieval_literatures.en_open_access_pipeline import run_pipeline as run_english_pipeline
from autodokit.tools.online_retrieval_literatures.policies import assert_supported_combo
from autodokit.tools.online_retrieval_literatures.profiles import infer_request_profile
from autodokit.tools.online_retrieval_literatures.orchestrators.download_orchestrator import run_download
from autodokit.tools.online_retrieval_literatures.orchestrators.metadata_orchestrator import run_metadata
from autodokit.tools.online_retrieval_literatures.orchestrators.retry_orchestrator import run_retry
from autodokit.tools.online_retrieval_literatures.orchestrators.source_selection_orchestrator import run_source_selection
from autodokit.tools.online_retrieval_literatures.orchestrators.structured_orchestrator import run_structured_extract


DebugHandler = Callable[[dict[str, Any]], dict[str, Any]]


def dispatch_request(
    payload: dict[str, Any],
    *,
    debug_handler: DebugHandler | None = None,
) -> dict[str, Any]:
    source = canonical_source(str(payload.get("source") or ""))
    mode = str(payload.get("mode") or "").strip()
    action = str(payload.get("action") or "").strip()
    request_profile = infer_request_profile(payload)
    payload = dict(payload)
    payload["source"] = source
    payload["request_profile"] = request_profile

    assert_supported_combo(source, mode, action)

    if source == "all" and mode == "debug" and action == "run":
        if debug_handler is not None:
            result = debug_handler(payload)
            return finalize_result(result, source=source, mode=mode, action=action, request_profile=request_profile)
        return {
            "status": "BLOCKED",
            "error_type": "RuntimeError",
            "error": "未提供 debug_handler，无法执行 all/debug/run。",
            "source": source,
            "mode": mode,
            "action": action,
            "request_profile": request_profile,
        }

    if source == "zh_cnki" and mode == "debug" and action == "pipeline":
        result = run_cnki_pipeline(payload)
        return finalize_result(result, source=source, mode=mode, action=action, request_profile=request_profile)

    if source == "en_open_access" and mode == "debug" and action == "pipeline":
        result = run_english_pipeline(payload)
        return finalize_result(result, source=source, mode=mode, action=action, request_profile=request_profile)

    if action == "metadata":
        result = run_metadata(payload, source=source, request_profile=request_profile)
    elif action == "download":
        result = run_download(payload, source=source, mode=mode, request_profile=request_profile)
    elif action == "html_extract":
        result = run_structured_extract(payload, source=source, mode=mode, request_profile=request_profile)
    elif action == "chaoxing_portal":
        result = run_retry(payload, source=source, mode=mode, action=action)
    elif action == "fetch":
        result = run_source_selection(payload, source=source, mode=mode, action=action)
    else:
        raise ValueError(f"不支持的动作: source={source}, mode={mode}, action={action}")

    return finalize_result(result, source=source, mode=mode, action=action, request_profile=request_profile)
