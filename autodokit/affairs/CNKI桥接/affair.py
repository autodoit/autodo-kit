"""CNKI 桥接事务执行入口。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from autodokit.tools import load_json_or_py

from .engine import CnkiWorkflowPlanner


def execute(config_path: Path) -> list[Path]:
    """执行 CNKI 规划事务并输出结构化结果。

    Args:
        config_path: 事务配置文件绝对路径。

    Returns:
        输出文件路径列表。

    Raises:
        ValueError: `output_dir` 不是绝对路径。

    Examples:
        >>> execute(Path("/home/ethan/work/tmp/cnki_task.json"))
    """

    raw_cfg = load_json_or_py(config_path)
    planner = CnkiWorkflowPlanner()
    mode = str(raw_cfg.get("mode") or "cnki-search")

    builders: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "cnki-search": lambda cfg: planner.build_search_plan(
            query=str(cfg.get("query") or ""),
            page=int(cfg.get("page") or 1),
            sort_by=str(cfg.get("sort_by") or "relevance"),
            access_type=str(cfg.get("access_type") or "closed"),
            metadata=dict(cfg.get("metadata") or {}),
        ),
        "cnki-advanced-search": lambda cfg: planner.build_advanced_search_plan(
            query=str(cfg.get("query") or ""),
            author=str(cfg.get("author") or ""),
            journal=str(cfg.get("journal") or ""),
            start_year=str(cfg.get("start_year") or ""),
            end_year=str(cfg.get("end_year") or ""),
            source_types=list(cfg.get("source_types") or []),
            field_type=str(cfg.get("field_type") or "SU"),
            access_type=str(cfg.get("access_type") or "closed"),
            metadata=dict(cfg.get("metadata") or {}),
        ),
        "cnki-parse-results": lambda cfg: planner.build_parse_results_plan(
            page_url=str(cfg.get("page_url") or ""),
            current_page=int(cfg.get("current_page") or 1),
            access_type=str(cfg.get("access_type") or "closed"),
            metadata=dict(cfg.get("metadata") or {}),
        ),
        "cnki-navigate-pages": lambda cfg: planner.build_navigate_pages_plan(
            action=str(cfg.get("action") or "next"),
            current_page=int(cfg.get("current_page") or 1),
            target_page=int(cfg.get("target_page")) if cfg.get("target_page") is not None else None,
            sort_by=str(cfg.get("sort_by") or "relevance"),
            access_type=str(cfg.get("access_type") or "closed"),
            metadata=dict(cfg.get("metadata") or {}),
        ),
        "cnki-paper-detail": lambda cfg: planner.build_paper_detail_plan(
            detail_url=str(cfg.get("detail_url") or ""),
            title_hint=str(cfg.get("title_hint") or ""),
            export_id=str(cfg.get("export_id") or ""),
            access_type=str(cfg.get("access_type") or "closed"),
            metadata=dict(cfg.get("metadata") or {}),
        ),
        "cnki-journal-search": lambda cfg: planner.build_journal_search_plan(
            journal_query=str(cfg.get("journal_query") or ""),
            access_type=str(cfg.get("access_type") or "closed"),
            metadata=dict(cfg.get("metadata") or {}),
        ),
        "cnki-journal-index": lambda cfg: planner.build_journal_index_plan(
            journal_name=str(cfg.get("journal_name") or ""),
            detail_url=str(cfg.get("detail_url") or ""),
            access_type=str(cfg.get("access_type") or "closed"),
            metadata=dict(cfg.get("metadata") or {}),
        ),
        "cnki-journal-toc": lambda cfg: planner.build_journal_toc_plan(
            journal_name=str(cfg.get("journal_name") or ""),
            year=str(cfg.get("year") or ""),
            issue=str(cfg.get("issue") or ""),
            download_original=bool(cfg.get("download_original", False)),
            access_type=str(cfg.get("access_type") or "closed"),
            metadata=dict(cfg.get("metadata") or {}),
        ),
        "cnki-download": lambda cfg: planner.build_download_plan(
            detail_url=str(cfg.get("detail_url") or ""),
            preferred_format=str(cfg.get("preferred_format") or "auto"),
            access_type=str(cfg.get("access_type") or "closed"),
            metadata=dict(cfg.get("metadata") or {}),
        ),
        "cnki-export": lambda cfg: planner.build_export_plan(
            mode=str(cfg.get("export_mode") or cfg.get("mode_value") or "ris"),
            detail_url=str(cfg.get("detail_url") or ""),
            export_id=str(cfg.get("export_id") or ""),
            batch_items=list(cfg.get("batch_items") or []),
            access_type=str(cfg.get("access_type") or "closed"),
            metadata=dict(cfg.get("metadata") or {}),
        ),
    }

    builder = builders.get(mode)
    if builder is None:
        result = {
            "status": "BLOCKED",
            "mode": mode,
            "error": f"不支持的 CNKI 模式: {mode}",
        }
    else:
        result = {
            "status": "PASS",
            "mode": mode,
            "result": builder(raw_cfg),
        }

    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={str(raw_cfg.get('output_dir') or '')!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / "cnki_bridge_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
