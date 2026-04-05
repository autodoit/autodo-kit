"""CNKI 全文下载规划事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import build_cnki_result, load_json_or_py, write_affair_json_result


def execute(config_path: Path) -> list[Path]:
    raw_cfg = load_json_or_py(config_path)
    payload = {"detail_url": str(raw_cfg.get("detail_url") or ""), "file_format": str(raw_cfg.get("file_format") or "pdf")}
    result = build_cnki_result(mode="cnki-download", access_type=str(raw_cfg.get("access_type") or "closed"), next_node="PDF文件转结构化数据文件", payload=payload, metadata=dict(raw_cfg.get("metadata") or {}))
    return write_affair_json_result(raw_cfg, config_path, "cnki_download_result.json", result)
