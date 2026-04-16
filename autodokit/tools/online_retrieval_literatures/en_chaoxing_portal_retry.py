"""通过学校数据库集合站对英文失败项做二次重试。"""

from __future__ import annotations

import importlib
import json
import random
import re
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from autodokit.tools.online_retrieval_literatures.school_foreign_database_portal import fetch_school_foreign_databases
from autodokit.tools.online_retrieval_literatures.en_open_access_single_fulltext_download import _to_record, download_single
from autodokit.tools.online_retrieval_literatures.progress_reporter import print_progress_line, write_progress_snapshot


DEFAULT_PORTAL_ORDER = ["sciencedirect", "springer", "wiley", "jstor", "nature"]
_PORTAL_BUILD = None
_PROFILE_INFER = None


def _resolve_portal_handlers() -> tuple[Any, Any]:
    global _PORTAL_BUILD, _PROFILE_INFER
    if _PORTAL_BUILD is None or _PROFILE_INFER is None:
        module = importlib.import_module("autodokit.tools.online_retrieval_literatures.portals.profile_router")
        _PORTAL_BUILD = getattr(module, "build_portal_candidates")
        _PROFILE_INFER = getattr(module, "infer_record_profile")
    return _PORTAL_BUILD, _PROFILE_INFER


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _download_single_isolated(config: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """在线程隔离环境中执行单篇下载，避免事件循环上下文冲突。

    Args:
        config: 单篇下载配置。
        record: 记录字典。

    Returns:
        dict[str, Any]: 下载结果。
    """

    def _run_once(run_config: dict[str, Any]) -> dict[str, Any]:
        record_obj = _to_record(record)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(download_single, run_config, record_obj)
            return dict(future.result())

    def _run_via_subprocess(run_config: dict[str, Any]) -> dict[str, Any]:
        output_dir = Path(str(run_config.get("output_dir") or "")).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        record_json_text = json.dumps(record, ensure_ascii=False)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as record_file:
            record_file.write(record_json_text)
            record_path = Path(record_file.name)

        cmd = [
            sys.executable,
            "-m",
            "autodokit.tools.online_retrieval_literatures.en_open_access_single_fulltext_download",
            "--record-path",
            str(record_path),
            "--output-dir",
            str(output_dir),
            "--download-request-timeout",
            str(int(run_config.get("download_request_timeout") or 12)),
            "--per-record-max-attempts",
            str(int(run_config.get("per_record_max_attempts") or 6)),
            "--min-request-delay-seconds",
            str(float(run_config.get("min_request_delay_seconds") or 0.35)),
            "--max-request-delay-seconds",
            str(float(run_config.get("max_request_delay_seconds") or 1.6)),
            "--browser-profile-dir",
            str(run_config.get("browser_profile_dir") or ""),
            "--browser-cdp-port",
            str(int(run_config.get("browser_cdp_port") or 9332)),
            "--manual-wait-timeout-seconds",
            str(int(run_config.get("manual_wait_timeout_seconds") or 900)),
        ]
        if bool(run_config.get("enable_barrier_analysis", False)):
            cmd.append("--enable-barrier-analysis")
        if bool(run_config.get("allow_manual_intervention", False)):
            cmd.append("--allow-manual-intervention")
        if bool(run_config.get("keep_browser_open", False)):
            cmd.append("--keep-browser-open")
        bailian_key_file = _normalize_text(run_config.get("bailian_api_key_file"))
        if bailian_key_file:
            cmd.extend(["--bailian-api-key-file", bailian_key_file])

        completed = subprocess.run(cmd, check=False)
        output_path = output_dir / "single_download_result.json"
        payload: dict[str, Any]
        if output_path.exists():
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        else:
            payload = {
                "status": "BLOCKED",
                "record": record,
                "result": {
                    "status": "BLOCKED",
                    "error_type": "SubprocessResultMissing",
                    "error": "single_download_result.json 未生成",
                },
                "output_path": "",
            }
        payload["subprocess_returncode"] = int(completed.returncode)
        payload["subprocess_stdio_mode"] = "inherit"
        record_path.unlink(missing_ok=True)
        return payload

    try:
        return _run_once(dict(config))
    except Exception as exc:  # noqa: BLE001
        error_text = _normalize_text(exc)
        if "Playwright Sync API inside the asyncio loop" not in error_text:
            raise

        subprocess_result = _run_via_subprocess(dict(config))
        subprocess_result["async_conflict_fallback"] = True
        subprocess_result["async_conflict_mode"] = "subprocess"
        subprocess_result["async_conflict_error"] = error_text
        return subprocess_result

    except BaseException as exc:  # noqa: BLE001
        error_text = _normalize_text(exc)
        fallback_config = dict(config)
        fallback_config["allow_manual_intervention"] = False
        fallback_config["keep_browser_open"] = False
        fallback = _run_once(fallback_config)
        fallback["async_conflict_fallback"] = True
        fallback["async_conflict_mode"] = "thread_force_off"
        fallback["async_conflict_error"] = error_text
        fallback["manual_intervention_forced_off"] = True
        fallback["fallback_error"] = str(exc)
        return fallback


def _normalize_text(value: Any) -> str:
    return normalize_text(value)


def _extract_domain(url: Any) -> str:
    parsed = urllib.parse.urlparse(_normalize_text(url))
    return _normalize_text(parsed.netloc).lower()


def _looks_like_http_blocked_message(message: Any) -> bool:
    text = _normalize_text(message)
    return any(token in text for token in ["401", "403", "429", "Forbidden", "Too Many Requests", "HTTP Error"])


def _collect_blocked_domains_from_single_result(single_result: dict[str, Any]) -> set[str]:
    blocked: set[str] = set()
    result = dict(single_result.get("result") or single_result)
    barrier_type = _normalize_text(result.get("barrier_type")).lower()
    evidence = _normalize_text(result.get("evidence")).lower()
    attempts = list(result.get("attempts") or [])

    for attempt in attempts:
        attempt_dict = dict(attempt or {})
        url = _normalize_text(attempt_dict.get("url"))
        domain = _extract_domain(url)
        if not domain:
            continue
        if barrier_type == "http_blocked" or "401_403_429" in evidence or _looks_like_http_blocked_message(attempt_dict.get("message")):
            blocked.add(domain)
    return blocked


def _sample_delay(min_seconds: float, max_seconds: float) -> float:
    lower = max(float(min_seconds), 0.0)
    upper = max(float(max_seconds), lower)
    if upper == lower:
        return lower
    return random.uniform(lower, upper)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _portal_candidates(database: dict[str, Any], record: dict[str, Any]) -> list[str]:
    base_url = _normalize_text((database.get("resolved_links") or [database.get("open_url") or ""])[0])
    if not base_url:
        return []
    profile = str(database.get("profile") or "generic")
    build_portal_candidates, _ = _resolve_portal_handlers()
    return build_portal_candidates(profile, base_url, record)


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


def _normalize_portal_order(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        candidates = [item.strip().lower() for item in raw_value.split(",") if item.strip()]
    elif isinstance(raw_value, list):
        candidates = [str(item).strip().lower() for item in raw_value if str(item).strip()]
    else:
        candidates = []

    if not candidates:
        candidates = list(DEFAULT_PORTAL_ORDER)

    normalized: list[str] = []
    seen: set[str] = set()
    for profile in candidates:
        if profile in seen:
            continue
        if profile not in DEFAULT_PORTAL_ORDER:
            continue
        seen.add(profile)
        normalized.append(profile)

    if not normalized:
        return list(DEFAULT_PORTAL_ORDER)
    return normalized


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
    portal_order = _normalize_portal_order(config.get("portal_order"))
    max_db_per_record = int(config.get("max_databases_per_record") or 2)
    enable_blocked_domain_short_circuit = bool(config.get("enable_blocked_domain_short_circuit", True))
    blocked_domain_threshold = max(int(config.get("blocked_domain_threshold") or 2), 1)

    blocked_domain_hits: dict[str, int] = {}
    for domain, count in dict(config.get("blocked_domain_hits_seed") or {}).items():
        normalized_domain = _normalize_text(domain).lower()
        if normalized_domain:
            blocked_domain_hits[normalized_domain] = max(int(count or 0), 0)
    for domain in list(config.get("blocked_domains_seed") or []):
        normalized_domain = _normalize_text(domain).lower()
        if normalized_domain:
            blocked_domain_hits[normalized_domain] = max(blocked_domain_hits.get(normalized_domain, 0), blocked_domain_threshold)

    short_circuit_skip_count = 0

    step_metrics: dict[str, dict[str, int]] = {
        profile: {
            "records_entered": 0,
            "records_hit": 0,
            "db_attempts": 0,
            "db_with_candidates": 0,
            "pass_attempts": 0,
        }
        for profile in portal_order
    }

    activity_log_path = output_dir / "retry_activity.jsonl"
    progress_snapshot_path = output_dir / "retry_progress.json"
    results: list[dict[str, Any]] = []
    total_records = len(failed_records)
    pass_count = 0
    blocked_count = 0
    for index, record in enumerate(failed_records, start=1):
        _, infer_record_profile = _resolve_portal_handlers()
        record_profile = infer_record_profile(record)
        attempt_rows: list[dict[str, Any]] = []
        final_result: dict[str, Any] | None = None

        for step_index, profile in enumerate(portal_order, start=1):
            step_metrics[profile]["records_entered"] += 1
            matching_databases = [db for db in selected_databases if str(db.get("profile") or "") == profile]
            if not matching_databases:
                continue

            for db_index, database in enumerate(matching_databases[:max_db_per_record], start=1):
                step_metrics[profile]["db_attempts"] += 1
                portal_candidates = _portal_candidates(database, record)
                blocked_domains = {
                    domain for domain, count in blocked_domain_hits.items() if count >= blocked_domain_threshold
                } if enable_blocked_domain_short_circuit else set()
                filtered_candidates = [
                    url for url in portal_candidates if _extract_domain(url) not in blocked_domains
                ]
                attempt_payload = {
                    "database_id": database.get("database_id"),
                    "database_name": database.get("name"),
                    "profile": database.get("profile"),
                    "step_profile": profile,
                    "step_index": step_index,
                    "portal_candidates": filtered_candidates,
                }
                if blocked_domains:
                    attempt_payload["blocked_domains"] = sorted(blocked_domains)
                    attempt_payload["short_circuit_filtered_count"] = max(len(portal_candidates) - len(filtered_candidates), 0)
                _append_jsonl(activity_log_path, {"event": "portal_attempt_start", "index": index, **attempt_payload, "title": record.get("title")})
                if not filtered_candidates:
                    if portal_candidates and blocked_domains:
                        attempt_payload["status"] = "DOMAIN_SHORT_CIRCUIT"
                        short_circuit_skip_count += 1
                    else:
                        attempt_payload["status"] = "NO_PORTAL_CANDIDATES"
                    attempt_rows.append(attempt_payload)
                    _append_jsonl(activity_log_path, {"event": "portal_attempt_end", "index": index, **attempt_payload})
                    continue

                step_metrics[profile]["db_with_candidates"] += 1
                augmented_record = dict(record)
                raw = dict(augmented_record.get("raw") or {})
                original_candidates = [str(item) for item in list(raw.get("download_candidates") or []) if str(item).strip()]
                raw["download_candidates"] = filtered_candidates + original_candidates
                augmented_record["raw"] = raw
                if filtered_candidates and not str(augmented_record.get("pdf_url") or ""):
                    augmented_record["pdf_url"] = filtered_candidates[0]
                single_config = dict(config)
                single_config["output_dir"] = str(output_dir / f"item_{index:04d}" / f"s{step_index:02d}_db{db_index:02d}_{database.get('database_id')}")
                attempt_payload["allow_manual_intervention"] = bool(single_config.get("allow_manual_intervention", False))
                attempt_payload["keep_browser_open"] = bool(single_config.get("keep_browser_open", False))
                try:
                    single_result = _download_single_isolated(single_config, augmented_record)
                except Exception as exc:  # noqa: BLE001
                    single_result = {
                        "status": "BLOCKED",
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                        "error_traceback": traceback.format_exc(),
                        "record": augmented_record,
                        "result": {
                            "status": "BLOCKED",
                            "error_type": exc.__class__.__name__,
                            "error": str(exc),
                            "error_traceback": traceback.format_exc(),
                        },
                        "output_path": "",
                    }
                attempt_payload["status"] = str((single_result.get("result") or {}).get("status") or single_result.get("status") or "BLOCKED")
                attempt_payload["output_path"] = str(single_result.get("output_path") or "")
                if single_result.get("error"):
                    attempt_payload["error"] = str(single_result.get("error"))
                error_traceback = _normalize_text(single_result.get("error_traceback") or (single_result.get("result") or {}).get("error_traceback"))
                if error_traceback:
                    attempt_payload["error_traceback"] = error_traceback

                for blocked_domain in _collect_blocked_domains_from_single_result(single_result):
                    blocked_domain_hits[blocked_domain] = blocked_domain_hits.get(blocked_domain, 0) + 1

                attempt_rows.append(attempt_payload)
                _append_jsonl(activity_log_path, {"event": "portal_attempt_end", "index": index, **attempt_payload})
                if attempt_payload["status"] == "PASS":
                    step_metrics[profile]["pass_attempts"] += 1
                    step_metrics[profile]["records_hit"] += 1
                    final_result = single_result
                    break

                time.sleep(round(_sample_delay(float(config.get("min_portal_retry_delay_seconds") or 2.2), float(config.get("max_portal_retry_delay_seconds") or 6.8)), 3))

            if final_result is not None:
                break

        results.append(
            {
                "index": index,
                "record": record,
                "status": str((final_result or {}).get("status") or ((final_result or {}).get("result") or {}).get("status") or (attempt_rows[-1].get("status") if attempt_rows else "NO_PORTAL_HIT")),
                "matched_profile": record_profile,
                "portal_order_used": portal_order,
                "attempts": attempt_rows,
                "final_result": final_result or {},
            }
        )

        record_status = str(results[-1].get("status") or "NO_PORTAL_HIT")
        if record_status == "PASS":
            pass_count += 1
        else:
            blocked_count += 1

        current_title = _normalize_text(record.get("title") or record.get("source_id") or f"record-{index}")
        print_progress_line(
            prefix="A040-chaoxing-retry",
            total=total_records,
            completed=index,
            current_label=current_title,
            current_status=record_status,
            counters={
                "pass": pass_count,
                "blocked": blocked_count,
            },
        )
        write_progress_snapshot(
            progress_snapshot_path,
            {
                "stage": "retry_failed_records",
                "total": total_records,
                "completed": index,
                "remaining": max(total_records - index, 0),
                "current": {
                    "index": index,
                    "title": current_title,
                    "status": record_status,
                },
                "processed": [
                    {
                        "index": int(item.get("index") or 0),
                        "cite_key": _normalize_text((item.get("record") or {}).get("bibtex_key") or (item.get("record") or {}).get("source_id") or ""),
                        "status": _normalize_text(item.get("status") or ""),
                    }
                    for item in results
                ],
                "remaining_records": [
                    {
                        "index": index + offset,
                        "cite_key": _normalize_text(item.get("bibtex_key") or item.get("source_id") or ""),
                        "title": _normalize_text(item.get("title") or ""),
                    }
                    for offset, item in enumerate(failed_records[index:], start=1)
                ],
                "counters": {
                    "pass": pass_count,
                    "blocked": blocked_count,
                    "blocked_domains": len([d for d, c in blocked_domain_hits.items() if c >= blocked_domain_threshold]),
                    "short_circuit_skips": short_circuit_skip_count,
                },
            },
        )

        time.sleep(round(_sample_delay(float(config.get("min_inter_record_delay_seconds") or 2.7), float(config.get("max_inter_record_delay_seconds") or 7.9)), 3))

    step_hit_stats: list[dict[str, Any]] = []
    for step_index, profile in enumerate(portal_order, start=1):
        metric = step_metrics.get(profile) or {}
        entered = int(metric.get("records_entered") or 0)
        hits = int(metric.get("records_hit") or 0)
        step_hit_stats.append(
            {
                "step_index": step_index,
                "profile": profile,
                "records_entered": entered,
                "records_hit": hits,
                "hit_rate": round((hits / entered), 4) if entered > 0 else 0.0,
                "db_attempts": int(metric.get("db_attempts") or 0),
                "db_with_candidates": int(metric.get("db_with_candidates") or 0),
                "pass_attempts": int(metric.get("pass_attempts") or 0),
            }
        )

    summary = {
        "status": "PASS",
        "failed_records": len(failed_records),
        "selected_databases": len(selected_databases),
        "portal_order": portal_order,
        "step_hit_stats": step_hit_stats,
        "pass_count": sum(1 for item in results if str((item.get("final_result") or {}).get("status") or ((item.get("final_result") or {}).get("result") or {}).get("status") or item.get("status") or "") == "PASS"),
        "no_strategy_count": sum(1 for item in results if str(item.get("status") or "") in {"NO_PORTAL_STRATEGY", "NO_PORTAL_HIT"}),
        "results": results,
        "catalog_result": catalog_result,
        "activity_log_path": str(activity_log_path),
        "progress_snapshot_path": str(progress_snapshot_path),
        "blocked_domain_threshold": blocked_domain_threshold,
        "enable_blocked_domain_short_circuit": enable_blocked_domain_short_circuit,
        "blocked_domain_hits": blocked_domain_hits,
        "blocked_domains": sorted([domain for domain, count in blocked_domain_hits.items() if count >= blocked_domain_threshold]),
        "short_circuit_skip_count": short_circuit_skip_count,
    }
    summary_path = output_dir / "retry_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary
