"""CNKI 结果解析事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import build_cnki_result, load_json_or_py, write_affair_json_result


def execute(config_path: Path) -> list[Path]:
    raw_cfg = load_json_or_py(config_path)
    result = build_cnki_result(mode="cnki-parse-results", access_type=str(raw_cfg.get("access_type") or "closed"), next_node="CNKI翻页导航", payload={"page_url": str(raw_cfg.get("page_url") or ""), "current_page": int(raw_cfg.get("current_page") or 1)}, metadata=dict(raw_cfg.get("metadata") or {}))
    return write_affair_json_result(raw_cfg, config_path, "cnki_parse_results_result.json", result)
