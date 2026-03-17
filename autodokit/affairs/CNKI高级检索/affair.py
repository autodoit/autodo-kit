"""CNKI 高级检索事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import build_cnki_result, load_json_or_py, write_affair_json_result


def build_advanced_plan(raw_cfg: dict[str, Any]) -> dict[str, Any]:
    """构造 CNKI 高级检索计划。"""

    payload = {
        "query": str(raw_cfg.get("query") or ""),
        "author": str(raw_cfg.get("author") or ""),
        "journal": str(raw_cfg.get("journal") or ""),
        "start_year": str(raw_cfg.get("start_year") or ""),
        "end_year": str(raw_cfg.get("end_year") or ""),
        "source_types": list(raw_cfg.get("source_types") or []),
        "field_type": str(raw_cfg.get("field_type") or "SU"),
    }
    return build_cnki_result(mode="cnki-advanced-search", access_type=str(raw_cfg.get("access_type") or "closed"), next_node="CNKI结果解析", payload=payload, metadata=dict(raw_cfg.get("metadata") or {}))


def execute(config_path: Path) -> list[Path]:
    raw_cfg = load_json_or_py(config_path)
    return write_affair_json_result(raw_cfg, config_path, "cnki_advanced_search_result.json", build_advanced_plan(raw_cfg))
