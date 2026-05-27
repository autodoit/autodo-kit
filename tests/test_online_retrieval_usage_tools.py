from __future__ import annotations

from pathlib import Path

from autodokit.tools import get_tool
from autodokit.tools.online_retrieval_literatures.online_retrieval_usage_tools import manage_online_retrieval_daily_usage


def test_manage_online_retrieval_daily_usage_record_and_get(tmp_path: Path) -> None:
    counter_path = tmp_path / "usage_counter.json"

    first = manage_online_retrieval_daily_usage(
        {
            "action": "record",
            "provider": "deepxiv",
            "count": 2,
            "event_kind": "api_request",
            "endpoint_family": "arxiv",
            "date": "2026-05-21",
            "counter_path": str(counter_path),
            "daily_limit": 10000,
        }
    )

    second = manage_online_retrieval_daily_usage(
        {
            "action": "record",
            "provider": "deepxiv",
            "count": 3,
            "event_kind": "api_request",
            "endpoint_family": "arxiv",
            "date": "2026-05-21",
            "counter_path": str(counter_path),
            "daily_limit": 10000,
        }
    )

    current = manage_online_retrieval_daily_usage(
        {
            "action": "get",
            "provider": "deepxiv",
            "date": "2026-05-21",
            "counter_path": str(counter_path),
        }
    )

    assert first["count"] == 2
    assert second["count"] == 5
    assert current["remaining"] == 9995
    assert current["by_event"]["api_request"] == 5
    assert current["by_endpoint"]["arxiv"] == 5


def test_manage_online_retrieval_daily_usage_list_and_reset(tmp_path: Path) -> None:
    counter_path = tmp_path / "usage_counter.json"

    manage_online_retrieval_daily_usage(
        {
            "action": "record",
            "provider": "deepxiv",
            "count": 4,
            "date": "2026-05-20",
            "counter_path": str(counter_path),
        }
    )
    manage_online_retrieval_daily_usage(
        {
            "action": "record",
            "provider": "deepxiv",
            "count": 6,
            "date": "2026-05-21",
            "counter_path": str(counter_path),
        }
    )

    listed = manage_online_retrieval_daily_usage(
        {
            "action": "list",
            "provider": "deepxiv",
            "limit": 2,
            "counter_path": str(counter_path),
        }
    )
    reset = manage_online_retrieval_daily_usage(
        {
            "action": "reset",
            "provider": "deepxiv",
            "date": "2026-05-21",
            "counter_path": str(counter_path),
        }
    )

    assert [item["date"] for item in listed["days"]] == ["2026-05-21", "2026-05-20"]
    assert reset["count"] == 0
    assert reset["remaining"] == 10000


def test_manage_online_retrieval_daily_usage_is_public_tool() -> None:
    fn = get_tool("manage_online_retrieval_daily_usage")
    assert callable(fn)