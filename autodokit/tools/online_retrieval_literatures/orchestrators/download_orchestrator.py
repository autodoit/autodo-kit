"""download 编排器。"""

from __future__ import annotations

from typing import Any

from autodokit.tools.online_retrieval_literatures.catalogs import source_family
from autodokit.tools.online_retrieval_literatures.executors.content_portal_cnki import execute_cnki_single_download
from autodokit.tools.online_retrieval_literatures.executors.content_portal_spis import execute_spis_single_download
from autodokit.tools.online_retrieval_literatures.executors.open_platform import execute_open_single_download
from autodokit.tools.online_retrieval_literatures.orchestrators.input_normalizer import resolve_content_portal_entries, resolve_en_batch_records


def _build_payload_from_entry(base_payload: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    payload = dict(base_payload)
    title = str(entry.get("title") or "")
    detail_url = str(entry.get("detail_url") or "")
    payload["zh_query"] = payload.get("zh_query") or title
    payload["detail_url"] = payload.get("detail_url") or detail_url
    payload["title"] = payload.get("title") or title
    return payload


def run_download(payload: dict[str, Any], *, source: str, mode: str, request_profile: str) -> dict[str, Any]:
    """执行 download 编排。

    Args:
        payload: 原始路由 payload。
        source: 规范化后的来源。
        mode: single 或 batch。
        request_profile: 请求画像。

    Returns:
        dict[str, Any]: download 结果。
    """
    family = source_family(source)

    if mode == "single":
        if family == "content_portal":
            if source == "zh_cnki":
                return execute_cnki_single_download(payload)
            if source == "spis":
                return execute_spis_single_download(payload, request_profile=request_profile)
        if family == "open_platform":
            return execute_open_single_download(payload)
        raise ValueError(f"single download 不支持的来源: source={source}")

    if mode == "batch":
        if family == "content_portal":
            entries = resolve_content_portal_entries(payload)
            if not entries:
                raise ValueError("content portal batch download 需要 entries 或可解析 seed 输入。")
            records = []
            for entry in entries:
                entry_payload = _build_payload_from_entry(payload, entry)
                title = str(entry.get("title") or "")
                detail_url = str(entry.get("detail_url") or "")
                if source == "zh_cnki":
                    result = execute_cnki_single_download(entry_payload)
                elif source == "spis":
                    result = execute_spis_single_download(entry_payload, request_profile=request_profile)
                else:
                    raise ValueError(f"batch download 不支持的内容门户: source={source}")
                records.append(
                    {
                        "title": title,
                        "detail_url": detail_url,
                        "status": result.get("status", "BLOCKED"),
                        "result": result,
                    }
                )
            pass_count = sum(1 for item in records if str(item.get("status")) == "PASS")
            return {
                "status": "PASS" if records else "BLOCKED",
                "source": source,
                "mode": "batch",
                "action": "download",
                "record_count": len(records),
                "download_count": pass_count,
                "records": records,
            }

        if family == "open_platform":
            seed_records = resolve_en_batch_records(payload)
            if not seed_records:
                raise ValueError("open platform batch download 需要 records 或可解析 seed 输入。")
            records = []
            for record_payload in seed_records:
                single_payload = dict(payload)
                single_payload["record"] = record_payload
                result = execute_open_single_download(single_payload)
                records.append(
                    {
                        "title": str(record_payload.get("title") or ""),
                        "status": result.get("status", "BLOCKED"),
                        "result": result,
                    }
                )
            pass_count = sum(1 for item in records if str(item.get("status")) == "PASS")
            return {
                "status": "PASS" if records else "BLOCKED",
                "source": source,
                "mode": "batch",
                "action": "download",
                "record_count": len(records),
                "download_count": pass_count,
                "records": records,
            }

    raise ValueError(f"download 不支持的组合: source={source}, mode={mode}")
