"""论文整编写作事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def build_full_paper(section_materials: dict[str, str], evidence_points: list[str], journal_style: str) -> dict[str, Any]:
    """整编章节材料为连贯稿件。"""

    ordered_sections = [
        ("title", section_materials.get("title", "未命名稿件")),
        ("abstract", section_materials.get("abstract", "待补充摘要。")),
        ("introduction", section_materials.get("introduction", "待补充引言。")),
        ("method", section_materials.get("method", "待补充研究设计。")),
        ("results", section_materials.get("results", "待补充结果分析。")),
        ("conclusion", section_materials.get("conclusion", "待补充结论。")),
    ]
    body = "\n\n".join(f"[{name}]\n{content}" for name, content in ordered_sections)
    return {
        "status": "PASS",
        "mode": "ml-paper-writing",
        "result": {
            "journal_style": journal_style,
            "evidence_points": evidence_points,
            "draft": body,
            "section_count": len(ordered_sections),
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = build_full_paper(
        section_materials=dict(raw_cfg.get("section_materials") or {}),
        evidence_points=list(raw_cfg.get("evidence_points") or []),
        journal_style=str(raw_cfg.get("journal_style") or "general"),
    )
    return write_affair_json_result(raw_cfg, config_path, "ml_paper_writing_result.json", result)
