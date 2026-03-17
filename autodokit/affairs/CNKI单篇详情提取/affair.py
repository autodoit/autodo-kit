"""CNKI 单篇详情提取事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import build_cnki_result, load_json_or_py, write_affair_json_result


def execute(config_path: Path) -> list[Path]:
    raw_cfg = load_json_or_py(config_path)
    payload = {"detail_url": str(raw_cfg.get("detail_url") or ""), "title_hint": str(raw_cfg.get("title_hint") or ""), "export_id": str(raw_cfg.get("export_id") or "")}
    result = build_cnki_result(mode="cnki-paper-detail", access_type=str(raw_cfg.get("access_type") or "closed"), next_node="CNKI全文下载规划", payload=payload, metadata=dict(raw_cfg.get("metadata") or {}))
    return write_affair_json_result(raw_cfg, config_path, "cnki_paper_detail_result.json", result)
