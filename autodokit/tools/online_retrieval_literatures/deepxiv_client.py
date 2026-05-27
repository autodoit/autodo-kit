"""DeepXiv 检索与下载客户端。"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from autodokit.tools.online_retrieval_literatures.online_retrieval_usage_tools import manage_online_retrieval_daily_usage


_DEFAULT_ENDPOINT_FAMILY = "arxiv"
_DEFAULT_BASE_TEMPLATE = "https://data.rag.ac.cn/{endpoint_family}/"


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = _normalize_text(value).lower()
    if not text:
        return bool(default)
    return text in {"1", "true", "yes", "y", "on"}


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,;，；|]", value) if item.strip()]
    return [value]


def _safe_name(value: Any) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", _normalize_text(value))
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    return cleaned or "deepxiv_record"


def _resolve_output_dir(config: dict[str, Any], default_relative: str) -> Path:
    raw = _normalize_text(config.get("output_dir"))
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(default_relative).expanduser().resolve()


def _resolve_token(config: dict[str, Any]) -> str:
    direct = _normalize_text(config.get("deepxiv_token"))
    if direct:
        return direct

    env_name = _normalize_text(config.get("deepxiv_token_env")) or "DEEPXIV_TOKEN"
    env_value = _normalize_text(os.environ.get(env_name))
    if env_value:
        return env_value

    token_file = _normalize_text(config.get("deepxiv_token_file"))
    if token_file:
        path = Path(token_file).expanduser().resolve()
        if path.exists() and path.is_file():
            return _normalize_text(path.read_text(encoding="utf-8"))
    return ""


def _build_base_url(config: dict[str, Any]) -> tuple[str, str]:
    endpoint_family = _normalize_text(
        config.get("deepxiv_endpoint_family") or config.get("deepxiv_repository") or _DEFAULT_ENDPOINT_FAMILY
    ).lower() or _DEFAULT_ENDPOINT_FAMILY
    base_url = _normalize_text(config.get("deepxiv_base_url")) or _DEFAULT_BASE_TEMPLATE.format(endpoint_family=endpoint_family)
    if not base_url.endswith("/"):
        base_url = f"{base_url}/"
    return base_url, endpoint_family


def _build_headers(token: str, *, accept: str) -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": "academic-research-kit/0.2",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_json(config: dict[str, Any], params: dict[str, Any]) -> tuple[dict[str, Any], str]:
    base_url, _ = _build_base_url(config)
    _, endpoint_family = _build_base_url(config)
    token = _resolve_token(config)
    timeout = max(5, _coerce_int(config.get("deepxiv_timeout_seconds"), 20))
    normalized_params = {
        key: value
        for key, value in params.items()
        if value is not None and value != "" and value != []
    }
    request_url = f"{base_url}?{urllib.parse.urlencode(normalized_params, doseq=True)}"
    request = urllib.request.Request(
        request_url,
        headers=_build_headers(token, accept="application/json, text/plain, */*"),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"DeepXiv HTTP {exc.code}: {detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepXiv 请求失败: {exc.reason}") from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DeepXiv 返回非 JSON 响应: {payload[:240]}") from exc
    manage_online_retrieval_daily_usage(
        {
            "action": "record",
            "provider": "deepxiv",
            "count": 1,
            "event_kind": "api_request",
            "endpoint_family": endpoint_family,
            "daily_limit": _coerce_int(config.get("deepxiv_daily_limit"), 10000),
            "counter_path": _normalize_text(config.get("deepxiv_usage_counter_file")),
            "timezone_name": _normalize_text(config.get("timezone_name") or config.get("timezone") or "Asia/Shanghai"),
        }
    )
    if not isinstance(data, dict):
        return {"items": list(data) if isinstance(data, list) else [data]}, request_url
    return data, request_url


def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    for key in ("results", "items", "records", "data", "papers", "hits", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates = value
            break
        if isinstance(value, dict):
            for nested_key in ("results", "items", "records", "data"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    candidates = nested
                    break
            if candidates:
                break
    if not candidates and payload:
        if any(key in payload for key in ("title", "paper_id", "arxiv_id", "pmc_id", "id")):
            candidates = [payload]
    return [dict(item) for item in candidates if isinstance(item, dict)]


def _normalize_authors(value: Any) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = _normalize_text(item.get("name") or item.get("author") or item.get("full_name"))
            else:
                name = _normalize_text(item)
            if name:
                out.append(name)
        return out
    text = _normalize_text(value)
    if not text:
        return []
    return [item.strip() for item in re.split(r"[,;，；|]", text) if item.strip()]


def _normalize_keywords(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(_normalize_text(item) for item in value if _normalize_text(item))
    return _normalize_text(value)


def _pick_first(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        text = _normalize_text(item.get(key))
        if text:
            return text
    return ""


def _normalize_record(item: dict[str, Any], *, endpoint_family: str, source_filter: str) -> dict[str, Any]:
    source_id = _pick_first(item, "source_id", "paper_id", "id", "arxiv_id", "biorxiv_id", "medrxiv_id", "pmc_id")
    pdf_url = _pick_first(item, "pdf_url", "download_url", "download_link", "pdf_link", "fulltext_pdf")
    landing_url = _pick_first(item, "landing_url", "detail_url", "paper_url", "markdown_url", "url")
    detail_url = pdf_url or landing_url
    title = _pick_first(item, "title", "paper_title", "name")

    return {
        "source": "deepxiv",
        "source_id": source_id,
        "title": title,
        "year": _pick_first(item, "year", "published_year", "publish_year", "publication_year"),
        "journal": _pick_first(item, "journal", "venue", "source", "publisher") or endpoint_family,
        "authors": _normalize_authors(item.get("authors") or item.get("author_names") or item.get("author")),
        "abstract": _pick_first(item, "abstract", "summary", "tldr", "brief"),
        "keywords": _normalize_keywords(item.get("keywords") or item.get("keyword")),
        "landing_url": landing_url,
        "detail_url": detail_url,
        "pdf_url": pdf_url,
        "doi": _pick_first(item, "doi"),
        "raw": {
            **dict(item),
            "deepxiv_endpoint_family": endpoint_family,
            "deepxiv_source_filter": source_filter,
        },
    }


def _build_search_params(config: dict[str, Any], query: str) -> dict[str, Any]:
    top_k = _coerce_int(config.get("deepxiv_top_k"), 0)
    if top_k <= 0:
        max_pages = max(1, _coerce_int(config.get("max_pages"), 1))
        per_page = max(1, _coerce_int(config.get("per_page"), 20))
        top_k = max_pages * per_page

    params: dict[str, Any] = {
        "type": "retrieve",
        "query": query,
        "top_k": top_k,
        "offset": max(0, _coerce_int(config.get("deepxiv_offset"), 0)),
    }

    source_filter = _normalize_text(config.get("deepxiv_source_filter"))
    if source_filter:
        params["source"] = source_filter
    if "deepxiv_use_fine_rerank" in config:
        params["use_fine_rerank"] = 1 if _coerce_bool(config.get("deepxiv_use_fine_rerank")) else 0
    if "deepxiv_return_contents" in config:
        params["return_contents"] = 1 if _coerce_bool(config.get("deepxiv_return_contents")) else 0
    if "deepxiv_return_roc" in config:
        params["return_roc"] = 1 if _coerce_bool(config.get("deepxiv_return_roc")) else 0

    for raw_key, param_key in (
        ("deepxiv_authors", "authors"),
        ("deepxiv_orgs", "orgs"),
        ("deepxiv_categories", "categories"),
        ("deepxiv_date_search_type", "date_search_type"),
        ("deepxiv_date_str", "date_str"),
    ):
        value = config.get(raw_key)
        if value is None:
            continue
        if raw_key in {"deepxiv_authors", "deepxiv_orgs", "deepxiv_categories"}:
            items = [str(item).strip() for item in _coerce_list(value) if str(item).strip()]
            if items:
                params[param_key] = ",".join(items)
            continue
        text = _normalize_text(value)
        if text:
            params[param_key] = text

    min_citation = _coerce_int(config.get("deepxiv_min_citation"), -1)
    if min_citation >= 0:
        params["min_citation"] = min_citation
    return params


def search_metadata(config: dict[str, Any]) -> dict[str, Any]:
    query = _normalize_text(config.get("query") or config.get("zh_query"))
    if not query:
        for item in [dict(entry) for entry in list(config.get("seed_items") or []) if isinstance(entry, dict)]:
            query = _normalize_text(item.get("title") or item.get("cite_key"))
            if query:
                break
    if not query:
        return {
            "status": "BLOCKED",
            "error_type": "MissingQuery",
            "error": "DeepXiv metadata 检索需要 query 或可回退的 seed_items 标题。",
            "record_count": 0,
            "metadata_paths": {},
        }

    base_url, endpoint_family = _build_base_url(config)
    source_filter = _normalize_text(config.get("deepxiv_source_filter"))
    output_dir = _resolve_output_dir(config, "sandbox/online_retrieval_debug/outputs/deepxiv/metadata")
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "deepxiv_raw_response.json"
    normalized_path = output_dir / "deepxiv_metadata_records.json"

    try:
        data, request_url = _request_json(config, _build_search_params(config, query))
        items = _extract_items(data)
        normalized_records = [
            _normalize_record(item, endpoint_family=endpoint_family, source_filter=source_filter)
            for item in items
            if _normalize_text(item.get("title") or item.get("paper_title") or item.get("name"))
        ]
        raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        normalized_path.write_text(json.dumps(normalized_records, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "status": "PASS",
            "query": query,
            "record_count": len(normalized_records),
            "source_runs": [
                {
                    "source": "deepxiv",
                    "status": "PASS",
                    "endpoint_family": endpoint_family,
                    "request_url": request_url,
                    "record_count": len(normalized_records),
                }
            ],
            "metadata_paths": {
                "json": str(normalized_path),
                "raw_response": str(raw_path),
                "base_url": base_url,
            },
            "blocked_count": 0,
            "error_type": "",
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001
        raw_path.write_text(
            json.dumps({"status": "BLOCKED", "error": str(exc), "query": query}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "status": "BLOCKED",
            "query": query,
            "record_count": 0,
            "source_runs": [{"source": "deepxiv", "status": "BLOCKED", "endpoint_family": endpoint_family}],
            "metadata_paths": {"raw_response": str(raw_path)},
            "blocked_count": 1,
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }


def _guess_pdf_url(record_payload: dict[str, Any]) -> str:
    pdf_url = _normalize_text(record_payload.get("pdf_url") or record_payload.get("detail_url") or record_payload.get("landing_url"))
    if pdf_url:
        return pdf_url

    raw = dict(record_payload.get("raw") or {})
    endpoint_family = _normalize_text(raw.get("deepxiv_endpoint_family") or _DEFAULT_ENDPOINT_FAMILY).lower() or _DEFAULT_ENDPOINT_FAMILY
    source_id = _normalize_text(record_payload.get("source_id"))
    if endpoint_family == "arxiv" and source_id:
        return f"https://arxiv.org/pdf/{source_id}.pdf"
    return ""


def download_single(config: dict[str, Any], record_payload: dict[str, Any]) -> dict[str, Any]:
    record = dict(record_payload)
    pdf_url = _guess_pdf_url(record)
    if not pdf_url:
        return {
            "status": "BLOCKED",
            "record": record,
            "result": {
                "status": "BLOCKED",
                "error_type": "MissingPdfUrl",
                "error": "DeepXiv 记录缺少可用 pdf_url，无法执行 A045 物化。",
            },
            "output_path": "",
        }

    output_dir = _resolve_output_dir(config, "sandbox/online_retrieval_debug/outputs/deepxiv/download")
    download_dir = output_dir / "downloads"
    output_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    token = _resolve_token(config)
    timeout = max(5, _coerce_int(config.get("deepxiv_download_timeout_seconds"), 60))

    request = urllib.request.Request(
        pdf_url,
        headers=_build_headers(token, accept="application/pdf, application/octet-stream, */*"),
        method="GET",
    )
    output_path = output_dir / "deepxiv_single_download_result.json"

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = _normalize_text(response.headers.get("Content-Type"))
            final_url = _normalize_text(response.geturl() or pdf_url)
            body = response.read()
        if not body:
            raise RuntimeError("DeepXiv 下载返回空文件。")
        if "html" in content_type.lower() and not final_url.lower().endswith(".pdf"):
            raise RuntimeError(f"DeepXiv 下载返回 HTML 页面而非 PDF: {final_url}")

        file_name = f"{_safe_name(record.get('title') or record.get('source_id') or 'deepxiv')}.pdf"
        saved_path = download_dir / file_name
        saved_path.write_bytes(body)
        result = {
            "status": "PASS",
            "saved_path": str(saved_path),
            "download_url": pdf_url,
            "final_url": final_url,
            "content_type": content_type,
            "size_bytes": len(body),
        }
        payload = {
            "status": "PASS",
            "record": record,
            "result": result,
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output_path"] = str(output_path)
        return payload
    except Exception as exc:  # noqa: BLE001
        payload = {
            "status": "BLOCKED",
            "record": record,
            "result": {
                "status": "BLOCKED",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
                "download_url": pdf_url,
            },
            "output_path": str(output_path),
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload