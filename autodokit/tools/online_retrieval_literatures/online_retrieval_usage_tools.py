"""在线检索每日用量统计工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autodokit.tools.time_utils import now_dt, now_iso


DEFAULT_ONLINE_RETRIEVAL_DAILY_LIMIT = 10000


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _resolve_counter_path(payload: dict[str, Any]) -> Path:
    raw = _normalize_text(payload.get("counter_path") or payload.get("usage_counter_path") or payload.get("deepxiv_usage_counter_file"))
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".autodokit" / "online_retrieval" / "daily_usage" / "usage_counter.json").resolve()


def _resolve_action(payload: dict[str, Any]) -> str:
    action = _normalize_text(payload.get("action") or "record").lower()
    return action or "record"


def _resolve_provider(payload: dict[str, Any]) -> str:
    provider = _normalize_text(payload.get("provider") or payload.get("source") or "deepxiv").lower()
    return provider or "deepxiv"


def _resolve_day_key(payload: dict[str, Any]) -> str:
    raw = _normalize_text(payload.get("date") or payload.get("day"))
    if raw:
        return raw
    timezone_name = _normalize_text(payload.get("timezone_name") or payload.get("timezone") or "Asia/Shanghai")
    return now_dt(timezone_name).strftime("%Y-%m-%d")


def _load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "providers": {}, "updated_at": ""}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("version", 1)
    payload.setdefault("providers", {})
    payload.setdefault("updated_at", "")
    return payload


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ensure_provider_bucket(ledger: dict[str, Any], provider: str, default_daily_limit: int) -> dict[str, Any]:
    providers = ledger.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        ledger["providers"] = providers
    bucket = providers.setdefault(provider, {})
    if not isinstance(bucket, dict):
        bucket = {}
        providers[provider] = bucket
    bucket.setdefault("default_daily_limit", default_daily_limit)
    bucket.setdefault("days", {})
    return bucket


def _ensure_day_bucket(provider_bucket: dict[str, Any], day_key: str, daily_limit: int) -> dict[str, Any]:
    days = provider_bucket.setdefault("days", {})
    if not isinstance(days, dict):
        days = {}
        provider_bucket["days"] = days
    bucket = days.setdefault(day_key, {})
    if not isinstance(bucket, dict):
        bucket = {}
        days[day_key] = bucket
    bucket.setdefault("count", 0)
    bucket.setdefault("daily_limit", daily_limit)
    bucket.setdefault("by_event", {})
    bucket.setdefault("by_endpoint", {})
    bucket.setdefault("updated_at", "")
    return bucket


def _build_snapshot(*, provider: str, day_key: str, day_bucket: dict[str, Any], counter_path: Path) -> dict[str, Any]:
    count = _coerce_int(day_bucket.get("count"), 0)
    daily_limit = _coerce_int(day_bucket.get("daily_limit"), DEFAULT_ONLINE_RETRIEVAL_DAILY_LIMIT)
    remaining = max(0, daily_limit - count)
    return {
        "status": "PASS",
        "provider": provider,
        "date": day_key,
        "count": count,
        "daily_limit": daily_limit,
        "remaining": remaining,
        "usage_ratio": 0.0 if daily_limit <= 0 else round(count / daily_limit, 6),
        "by_event": dict(day_bucket.get("by_event") or {}),
        "by_endpoint": dict(day_bucket.get("by_endpoint") or {}),
        "updated_at": str(day_bucket.get("updated_at") or ""),
        "counter_path": str(counter_path),
    }


def manage_online_retrieval_daily_usage(payload: dict[str, Any]) -> dict[str, Any]:
    """记录或读取在线检索每日用量。

    Args:
        payload: 管理参数。常用字段包括 `action`、`provider`、`count`、
            `event_kind`、`endpoint_family`、`counter_path`、`daily_limit`。

    Returns:
        dict[str, Any]: 当前 provider 当日统计快照，或最近若干日摘要。
    """

    action = _resolve_action(payload)
    provider = _resolve_provider(payload)
    day_key = _resolve_day_key(payload)
    counter_path = _resolve_counter_path(payload)
    timestamp = now_iso(_normalize_text(payload.get("timezone_name") or payload.get("timezone") or "Asia/Shanghai"), timespec="seconds")
    daily_limit = _coerce_int(payload.get("daily_limit"), DEFAULT_ONLINE_RETRIEVAL_DAILY_LIMIT)
    ledger = _load_ledger(counter_path)
    provider_bucket = _ensure_provider_bucket(ledger, provider, daily_limit)
    day_bucket = _ensure_day_bucket(provider_bucket, day_key, daily_limit)

    if action == "record":
        increment = max(0, _coerce_int(payload.get("count"), 1))
        event_kind = _normalize_text(payload.get("event_kind") or payload.get("kind") or "api_request")
        endpoint_family = _normalize_text(payload.get("endpoint_family") or payload.get("channel"))
        day_bucket["count"] = _coerce_int(day_bucket.get("count"), 0) + increment
        day_bucket["daily_limit"] = daily_limit
        if event_kind:
            by_event = dict(day_bucket.get("by_event") or {})
            by_event[event_kind] = _coerce_int(by_event.get(event_kind), 0) + increment
            day_bucket["by_event"] = by_event
        if endpoint_family:
            by_endpoint = dict(day_bucket.get("by_endpoint") or {})
            by_endpoint[endpoint_family] = _coerce_int(by_endpoint.get(endpoint_family), 0) + increment
            day_bucket["by_endpoint"] = by_endpoint
        day_bucket["updated_at"] = timestamp
        provider_bucket["default_daily_limit"] = daily_limit
        ledger["updated_at"] = timestamp
        _write_ledger(counter_path, ledger)
        return _build_snapshot(provider=provider, day_key=day_key, day_bucket=day_bucket, counter_path=counter_path)

    if action == "get":
        return _build_snapshot(provider=provider, day_key=day_key, day_bucket=day_bucket, counter_path=counter_path)

    if action == "reset":
        day_bucket["count"] = 0
        day_bucket["by_event"] = {}
        day_bucket["by_endpoint"] = {}
        day_bucket["daily_limit"] = daily_limit
        day_bucket["updated_at"] = timestamp
        ledger["updated_at"] = timestamp
        _write_ledger(counter_path, ledger)
        return _build_snapshot(provider=provider, day_key=day_key, day_bucket=day_bucket, counter_path=counter_path)

    if action == "list":
        days = dict(provider_bucket.get("days") or {})
        limit = max(1, _coerce_int(payload.get("limit"), 7))
        ordered_keys = sorted(days.keys(), reverse=True)[:limit]
        return {
            "status": "PASS",
            "provider": provider,
            "counter_path": str(counter_path),
            "days": [
                _build_snapshot(provider=provider, day_key=item, day_bucket=dict(days.get(item) or {}), counter_path=counter_path)
                for item in ordered_keys
            ],
        }

    raise ValueError(f"不支持的 action: {action}")


__all__ = [
    "DEFAULT_ONLINE_RETRIEVAL_DAILY_LIMIT",
    "manage_online_retrieval_daily_usage",
]