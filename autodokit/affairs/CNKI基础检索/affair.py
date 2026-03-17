"""CNKI 基础检索事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import build_cnki_result, load_json_or_py, write_affair_json_result


def build_search_plan(query: str, page: int, sort_by: str, access_type: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
    """构造 CNKI 基础检索计划。"""

    return build_cnki_result(
        mode="cnki-search",
        access_type=access_type,
        next_node="CNKI结果解析",
        payload={"query": query, "page": page, "sort_by": sort_by},
        metadata=metadata,
    )


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = build_search_plan(
        query=str(raw_cfg.get("query") or ""),
        page=int(raw_cfg.get("page") or 1),
        sort_by=str(raw_cfg.get("sort_by") or "relevance"),
        access_type=str(raw_cfg.get("access_type") or "closed"),
        metadata=dict(raw_cfg.get("metadata") or {}),
    )
    return write_affair_json_result(raw_cfg, config_path, "cnki_search_result.json", result)
