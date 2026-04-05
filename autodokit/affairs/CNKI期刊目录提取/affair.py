"""CNKI 期刊目录提取事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import build_cnki_result, load_json_or_py, write_affair_json_result


def execute(config_path: Path) -> list[Path]:
    raw_cfg = load_json_or_py(config_path)
    payload = {"journal_name": str(raw_cfg.get("journal_name") or ""), "year": str(raw_cfg.get("year") or ""), "issue": str(raw_cfg.get("issue") or ""), "download_original": bool(raw_cfg.get("download_original") or False)}
    result = build_cnki_result(mode="cnki-journal-toc", access_type=str(raw_cfg.get("access_type") or "closed"), next_node="CNKI单篇详情提取", payload=payload, metadata=dict(raw_cfg.get("metadata") or {}))
    return write_affair_json_result(raw_cfg, config_path, "cnki_journal_toc_result.json", result)
