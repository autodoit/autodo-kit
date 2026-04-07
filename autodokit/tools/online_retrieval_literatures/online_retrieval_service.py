"""在线检索功能分发层。"""

from __future__ import annotations

from typing import Any, Callable

from .cnki_paged_retrieval import run_pipeline as run_cnki_pipeline
from .en_chaoxing_portal_retry import retry_failed_records as retry_en_failed_records_via_chaoxing
from .en_open_access_batch_fulltext_download import download_batch as en_batch_download
from .en_open_access_pipeline import run_pipeline as run_english_pipeline
from .en_open_access_search_metadata import search_metadata as en_search_metadata
from .en_open_access_single_fulltext_download import _to_record as en_to_record
from .en_open_access_single_fulltext_download import download_single as en_single_download
from .online_retrieval_resolver import (
    resolve_en_batch_records_payload,
    resolve_en_single_record_payload,
    resolve_zh_cnki_entries,
    resolve_zh_cnki_single_payload,
)
from .school_foreign_database_portal import fetch_school_foreign_databases
from .zh_cnki_batch_fulltext_download import download_batch as zh_batch_download
from .zh_cnki_batch_html_extract import extract_batch as zh_batch_html
from .zh_cnki_search_metadata import search_metadata as zh_search_metadata
from .zh_cnki_single_fulltext_download import download_single as zh_single_download
from .zh_cnki_single_html_extract import extract_single as zh_single_html


def _raise_unsupported(source: str, mode: str, action: str) -> None:
    raise ValueError(f"不支持的路由组合: source={source}, mode={mode}, action={action}")


def _raise_missing_batch_payload(scope: str) -> None:
    raise ValueError(
        f"{scope} 需要 entries/records，或可解析的 cite_keys/pdf_paths/seed_items 输入。"
    )


def dispatch(
    payload: dict[str, Any],
    *,
    debug_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """执行在线检索功能分发。"""

    source = str(payload.get("source") or "").strip()
    mode = str(payload.get("mode") or "").strip()
    action = str(payload.get("action") or "").strip()

    if source == "all" and mode == "debug" and action == "run":
        if debug_handler is None:
            return {
                "status": "BLOCKED",
                "error_type": "RuntimeError",
                "error": "未提供 debug_handler，无法执行 all/debug/run。",
            }
        return debug_handler(payload)

    if source == "zh_cnki" and mode == "search" and action == "metadata":
        return zh_search_metadata(payload)

    if source == "zh_cnki" and mode == "single" and action == "download":
        resolved_payload = resolve_zh_cnki_single_payload(payload, query_field="zh_query")
        return zh_single_download(resolved_payload)

    if source == "zh_cnki" and mode == "single" and action == "html_extract":
        resolved_payload = resolve_zh_cnki_single_payload(payload, query_field="query")
        return zh_single_html(resolved_payload)

    if source == "zh_cnki" and mode == "batch" and action == "download":
        entries = resolve_zh_cnki_entries(payload)
        if not entries:
            _raise_missing_batch_payload("zh_cnki batch download")
        return zh_batch_download(payload, entries)

    if source == "zh_cnki" and mode == "batch" and action == "html_extract":
        entries = resolve_zh_cnki_entries(payload)
        if not entries:
            _raise_missing_batch_payload("zh_cnki batch html_extract")
        return zh_batch_html(payload, entries)

    if source == "en_open_access" and mode == "search" and action == "metadata":
        return en_search_metadata(payload)

    if source == "en_open_access" and mode == "single" and action == "download":
        record_payload = resolve_en_single_record_payload(payload)
        if not isinstance(record_payload, dict):
            raise ValueError("en_open_access single download 需要 record，或可解析的 cite_keys/pdf_paths/seed_items。")
        return en_single_download(payload, en_to_record(record_payload))

    if source == "en_open_access" and mode == "batch" and action == "download":
        records = resolve_en_batch_records_payload(payload)
        if not records:
            _raise_missing_batch_payload("en_open_access batch download")
        return en_batch_download(payload, records)

    if source == "chaoxing_portal" and mode == "catalog" and action == "fetch":
        return fetch_school_foreign_databases(payload)

    if source == "school_foreign_database_portal" and mode == "catalog" and action == "fetch":
        return fetch_school_foreign_databases(payload)

    if source == "school_database_portal" and mode == "catalog" and action == "fetch":
        return fetch_school_foreign_databases(payload)

    if source == "en_open_access" and mode == "retry" and action == "chaoxing_portal":
        return retry_en_failed_records_via_chaoxing(payload)

    if source == "zh_cnki" and mode == "debug" and action == "pipeline":
        return run_cnki_pipeline(payload)

    if source == "en_open_access" and mode == "debug" and action == "pipeline":
        return run_english_pipeline(payload)

    _raise_unsupported(source, mode, action)
