"""导航门户执行器（编排辅助）。"""

from __future__ import annotations

from typing import Any

from autodokit.tools.online_retrieval_literatures.en_chaoxing_portal_retry import retry_failed_records as retry_en_failed_records_via_chaoxing
from autodokit.tools.online_retrieval_literatures.school_foreign_database_portal import fetch_school_foreign_databases


def execute_navigation_catalog(payload: dict[str, Any]) -> dict[str, Any]:
    return fetch_school_foreign_databases(payload)


def execute_navigation_retry(payload: dict[str, Any]) -> dict[str, Any]:
    return retry_en_failed_records_via_chaoxing(payload)
