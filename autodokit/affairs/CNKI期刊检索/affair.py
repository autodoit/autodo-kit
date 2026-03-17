"""CNKI 期刊检索事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import build_cnki_result, load_json_or_py, write_affair_json_result


def execute(config_path: Path) -> list[Path]:
    raw_cfg = load_json_or_py(config_path)
    result = build_cnki_result(mode="cnki-journal-search", access_type=str(raw_cfg.get("access_type") or "closed"), next_node="CNKI期刊指标提取", payload={"journal_query": str(raw_cfg.get("journal_query") or "")}, metadata=dict(raw_cfg.get("metadata") or {}))
    return write_affair_json_result(raw_cfg, config_path, "cnki_journal_search_result.json", result)
