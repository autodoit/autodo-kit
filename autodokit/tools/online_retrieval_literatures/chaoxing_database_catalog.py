"""兼容层：学校数据库集合站目录抓取与筛选工具。

Deprecated:
- 新代码请使用 school_foreign_database_portal.py 内的 fetch_school_databases。
- 本文件仅用于兼容历史导入路径，后续可在完成全量迁移后删除。
"""

from __future__ import annotations

from typing import Any

from .school_foreign_database_portal import DEFAULT_CHINESE_PORTAL_URL, DEFAULT_FOREIGN_PORTAL_URL, DEFAULT_PORTAL_URL, DEFAULT_SUBJECT_CATEGORIES, build_default_portal_url, fetch_school_databases, resolve_redirect_url, select_databases


def fetch_catalog(config: dict[str, Any]) -> dict[str, Any]:
    return fetch_school_databases(config)
