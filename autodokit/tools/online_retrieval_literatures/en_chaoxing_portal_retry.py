"""通过学校数据库集合站对英文失败项做二次重试。"""

from __future__ import annotations

import json
import random
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .school_foreign_database_portal import fetch_school_foreign_databases
from .en_open_access_single_fulltext_download import _to_record, download_single


USER_AGENT = "AcademicResearchAutoWorkflow-ChaoxingRetry/0.1"


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _sample_delay(min_seconds: float, max_seconds: float) -> float:
    lower = max(float(min_seconds), 0.0)
    upper = max(float(max_seconds), lower)
    if upper == lower:
        return lower
    return random.uniform(lower, upper)


def _request_text(url: str, *, timeout: int = 30, referer: str = "") -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _extract_hrefs(html_text: str, base_url: str, patterns: list[str]) -> list[str]:
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html_text, flags=re.I)
    results: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        absolute = urllib.parse.urljoin(base_url, href)
        lowered = absolute.lower()
        if any(re.search(pattern, lowered) for pattern in patterns):
            if absolute not in seen:
                seen.add(absolute)
                results.append(absolute)
    return results


def _infer_record_profile(record: dict[str, Any]) -> str:
    doi = _normalize_text(record.get("doi"))
    merged = " ".join(
        [
            doi,
            _normalize_text(record.get("landing_url")),
            _normalize_text(record.get("pdf_url")),
            " ".join(str(item) for item in list((record.get("raw") or {}).get("download_candidates") or [])),
        ]
    ).lower()
    if doi.startswith("10.1007/") or "springer" in merged:
        return "springer"
    if doi.startswith("10.1016/") or any(token in merged for token in ["sciencedirect", "elsevier", "linkinghub"]):
        return "sciencedirect"
    if any(token in merged for token in ["onlinelibrary.wiley", "wiley"]):
        return "wiley"
    if "jstor" in merged:
        return "jstor"
    if "nature.com" in merged:
        return "nature"
    return "generic"


def _springer_candidates(base_url: str, record: dict[str, Any]) -> list[str]:
    doi = _normalize_text(record.get("doi"))
    title = _normalize_text(record.get("title"))
    candidates: list[str] = []
    if doi:
        candidates.extend(
            [
                f"{base_url.rstrip('/')}/content/pdf/{urllib.parse.quote(doi, safe='')}.pdf",
                f"{base_url.rstrip('/')}/article/{doi}",
                f"{base_url.rstrip('/')}/chapter/{doi}",
            ]
        )
    if title:
        search_url = f"{base_url.rstrip('/')}/search?query={urllib.parse.quote(title)}"
        candidates.append(search_url)
        try:
            html_text = _request_text(search_url, referer=base_url)
            candidates.extend(
                _extract_hrefs(
                    html_text,
                    base_url,
                    [r"/article/", r"/chapter/", r"/content/pdf/", r"/referenceworkentry/"],
                )[:4]
            )
        except Exception:
            pass
    return candidates


def _sciencedirect_candidates(base_url: str, record: dict[str, Any]) -> list[str]:
    doi = _normalize_text(record.get("doi"))
    title = _normalize_text(record.get("title"))
    candidates: list[str] = []
    if doi:
        candidates.append(f"https://doi.org/{doi}")
    if title:
        search_url = f"{base_url.rstrip('/')}/search?qs={urllib.parse.quote(title)}"
        candidates.append(search_url)
        try:
            html_text = _request_text(search_url, referer=base_url)
            candidates.extend(
                _extract_hrefs(
                    html_text,
                    base_url,
                    [r"/science/article/", r"/science/article/pii/", r"/science/article/abs/pii/"],
                )[:4]
            )
        except Exception:
            pass
    return candidates


def _wiley_candidates(base_url: str, record: dict[str, Any]) -> list[str]:
    doi = _normalize_text(record.get("doi"))
    title = _normalize_text(record.get("title"))
    candidates: list[str] = []
    if doi:
        candidates.extend(
            [
                f"{base_url.rstrip('/')}/doi/{doi}",
                f"{base_url.rstrip('/')}/doi/pdfdirect/{doi}",
            ]
        )
    if title:
        search_url = f"{base_url.rstrip('/')}/action/doSearch?AllField={urllib.parse.quote(title)}"
        candidates.append(search_url)
        try:
            html_text = _request_text(search_url, referer=base_url)
            candidates.extend(
                _extract_hrefs(
                    html_text,
                    base_url,
                    [r"/doi/abs/", r"/doi/full/", r"/doi/pdf", r"/doi/pdfdirect/"],
                )[:4]
            )
        except Exception:
            pass
    return candidates


def _jstor_candidates(base_url: str, record: dict[str, Any]) -> list[str]:
    title = _normalize_text(record.get("title"))
    candidates: list[str] = []
    if title:
        search_url = f"{base_url.rstrip('/')}/action/doBasicSearch?Query={urllib.parse.quote(title)}&so=rel"
        candidates.append(search_url)
        try:
            html_text = _request_text(search_url, referer=base_url)
            stable_links = _extract_hrefs(html_text, base_url, [r"/stable/"])
            candidates.extend(stable_links[:3])
            for stable_link in stable_links[:2]:
                stable_id = stable_link.rstrip("/").split("/stable/")[-1]
                if stable_id:
                    candidates.append(f"{base_url.rstrip('/')}/stable/pdf/{stable_id}.pdf")
        except Exception:
            pass
    return candidates


def _nature_candidates(base_url: str, record: dict[str, Any]) -> list[str]:
    title = _normalize_text(record.get("title"))
    candidates: list[str] = []
    if title:
        search_url = f"{base_url.rstrip('/')}/search?q={urllib.parse.quote(title)}"
        candidates.append(search_url)
        try:
            html_text = _request_text(search_url, referer=base_url)
            candidates.extend(_extract_hrefs(html_text, base_url, [r"/articles/"])[:4])
        except Exception:
            pass
    return candidates


def _portal_candidates(database: dict[str, Any], record: dict[str, Any]) -> list[str]:
    base_url = _normalize_text((database.get("resolved_links") or [database.get("open_url") or ""])[0])
    if not base_url:
        return []
    profile = str(database.get("profile") or "generic")
    if profile == "springer":
        return _springer_candidates(base_url, record)
    if profile == "sciencedirect":
        return _sciencedirect_candidates(base_url, record)
    if profile == "wiley":
        return _wiley_candidates(base_url, record)
    if profile == "jstor":
        return _jstor_candidates(base_url, record)
    if profile == "nature":
        return _nature_candidates(base_url, record)
    return []


def _load_failed_records(config: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(config.get("failed_records"), list):
        return [dict(item) for item in list(config.get("failed_records") or []) if isinstance(item, dict)]

    summary_path = Path(str(config.get("failed_summary_path") or "")).expanduser().resolve()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    results = list(payload.get("results") or [])
    failed: list[dict[str, Any]] = []
    for item in results:
        result = dict(item.get("result") or {})
        status = str(result.get("status") or item.get("status") or "")
        if status == "PASS":
            continue
        record = dict(item.get("record") or {})
        if record:
            failed.append(record)
    return failed


def _load_selected_databases(config: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(config.get("selected_databases"), list):
        return [dict(item) for item in list(config.get("selected_databases") or []) if isinstance(item, dict)]

    selected_path = str(config.get("selected_databases_path") or "").strip()
    if not selected_path:
        return []
    path = Path(selected_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("selected_databases_path 必须指向对象数组 JSON。")
    return [dict(item) for item in payload if isinstance(item, dict)]


def retry_failed_records(config: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(str(config.get("output_dir") or "sandbox/online_retrieval_debug/outputs/en_chaoxing_retry")).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_databases = _load_selected_databases(config)
    catalog_result: dict[str, Any]
    if selected_databases:
        catalog_result = {
            "status": "PASS",
            "selected": selected_databases,
            "selected_databases": len(selected_databases),
            "artifacts": {"selected_json": str(Path(str(config.get('selected_databases_path') or '')).expanduser().resolve()) if str(config.get('selected_databases_path') or '').strip() else ""},
        }
    else:
        catalog_config = dict(config)
        catalog_config["output_dir"] = str(output_dir / "chaoxing_catalog")
        catalog_result = fetch_school_foreign_databases(catalog_config)
        selected_databases = list(catalog_result.get("selected") or [])
    failed_records = _load_failed_records(config)

    activity_log_path = output_dir / "retry_activity.jsonl"
    results: list[dict[str, Any]] = []
    for index, record in enumerate(failed_records, start=1):
        record_profile = _infer_record_profile(record)
        matching_databases = [db for db in selected_databases if str(db.get("profile") or "") == record_profile]
        if not matching_databases:
            results.append(
                {
                    "index": index,
                    "record": record,
                    "status": "NO_PORTAL_STRATEGY",
                    "matched_profile": record_profile,
                    "attempts": [],
                }
            )
            _append_jsonl(activity_log_path, {"event": "record_skipped", "index": index, "title": record.get("title"), "matched_profile": record_profile})
            continue

        attempt_rows: list[dict[str, Any]] = []
        final_result: dict[str, Any] | None = None
        for db_index, database in enumerate(matching_databases[: int(config.get("max_databases_per_record") or 2)], start=1):
            portal_candidates = _portal_candidates(database, record)
            attempt_payload = {
                "database_id": database.get("database_id"),
                "database_name": database.get("name"),
                "profile": database.get("profile"),
                "portal_candidates": portal_candidates,
            }
            _append_jsonl(activity_log_path, {"event": "portal_attempt_start", "index": index, **attempt_payload, "title": record.get("title")})
            if not portal_candidates:
                attempt_payload["status"] = "NO_PORTAL_CANDIDATES"
                attempt_rows.append(attempt_payload)
                _append_jsonl(activity_log_path, {"event": "portal_attempt_end", "index": index, **attempt_payload})
                continue

            augmented_record = dict(record)
            raw = dict(augmented_record.get("raw") or {})
            original_candidates = [str(item) for item in list(raw.get("download_candidates") or []) if str(item).strip()]
            raw["download_candidates"] = portal_candidates + original_candidates
            augmented_record["raw"] = raw
            if portal_candidates and not str(augmented_record.get("pdf_url") or ""):
                augmented_record["pdf_url"] = portal_candidates[0]
            single_config = dict(config)
            single_config["output_dir"] = str(output_dir / f"item_{index:04d}" / f"db_{db_index:02d}_{database.get('database_id')}")
            single_result = download_single(single_config, _to_record(augmented_record))
            attempt_payload["status"] = str((single_result.get("result") or {}).get("status") or single_result.get("status") or "BLOCKED")
            attempt_payload["output_path"] = str(single_result.get("output_path") or "")
            attempt_rows.append(attempt_payload)
            _append_jsonl(activity_log_path, {"event": "portal_attempt_end", "index": index, **attempt_payload})
            if attempt_payload["status"] == "PASS":
                final_result = single_result
                break

            time.sleep(round(_sample_delay(float(config.get("min_portal_retry_delay_seconds") or 2.2), float(config.get("max_portal_retry_delay_seconds") or 6.8)), 3))

        results.append(
            {
                "index": index,
                "record": record,
                "status": str((final_result or {}).get("status") or ((final_result or {}).get("result") or {}).get("status") or (attempt_rows[-1].get("status") if attempt_rows else "NO_PORTAL_STRATEGY")),
                "matched_profile": record_profile,
                "attempts": attempt_rows,
                "final_result": final_result or {},
            }
        )

        time.sleep(round(_sample_delay(float(config.get("min_inter_record_delay_seconds") or 2.7), float(config.get("max_inter_record_delay_seconds") or 7.9)), 3))

    summary = {
        "status": "PASS",
        "failed_records": len(failed_records),
        "selected_databases": len(selected_databases),
        "pass_count": sum(1 for item in results if str((item.get("final_result") or {}).get("status") or ((item.get("final_result") or {}).get("result") or {}).get("status") or item.get("status") or "") == "PASS"),
        "no_strategy_count": sum(1 for item in results if str(item.get("status") or "") == "NO_PORTAL_STRATEGY"),
        "results": results,
        "catalog_result": catalog_result,
        "activity_log_path": str(activity_log_path),
    }
    summary_path = output_dir / "retry_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary
