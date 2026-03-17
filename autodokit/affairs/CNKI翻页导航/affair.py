"""CNKI 翻页导航事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import build_cnki_result, load_json_or_py, write_affair_json_result


def execute(config_path: Path) -> list[Path]:
    raw_cfg = load_json_or_py(config_path)
    payload = {"action": str(raw_cfg.get("action") or "next"), "current_page": int(raw_cfg.get("current_page") or 1), "target_page": raw_cfg.get("target_page"), "sort_by": str(raw_cfg.get("sort_by") or "relevance")}
    result = build_cnki_result(mode="cnki-navigate-pages", access_type=str(raw_cfg.get("access_type") or "closed"), next_node="CNKI结果解析", payload=payload, metadata=dict(raw_cfg.get("metadata") or {}))
    return write_affair_json_result(raw_cfg, config_path, "cnki_navigate_pages_result.json", result)
