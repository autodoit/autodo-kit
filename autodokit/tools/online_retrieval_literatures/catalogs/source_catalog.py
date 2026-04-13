"""来源别名与来源族定义。"""

from __future__ import annotations

SOURCE_ALIASES = {
    "school_database_portal": "school_foreign_database_portal",
    "chaoxing_portal": "school_foreign_database_portal",
    "open_platform": "en_open_access",
}

SOURCE_FAMILY = {
    "zh_cnki": "content_portal",
    "spis": "content_portal",
    "en_open_access": "open_platform",
    "school_foreign_database_portal": "navigation_portal",
    "all": "router_debug",
}


def canonical_source(source: str) -> str:
    name = (source or "").strip()
    if not name:
        return ""
    return SOURCE_ALIASES.get(name, name)


def source_family(source: str) -> str:
    return SOURCE_FAMILY.get(canonical_source(source), "unknown")
