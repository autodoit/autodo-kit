"""论文自审事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def review_paper(manuscript_title: str, sections: dict[str, str], figures: list[str] | None = None) -> dict[str, Any]:
    """从结构和证据角度做内部自审。"""

    issues: list[dict[str, str]] = []
    for required_name in ("introduction", "method", "results", "conclusion"):
        if not str(sections.get(required_name) or "").strip():
            issues.append({"level": "high", "section": required_name, "message": "缺少核心章节内容"})
    if not figures:
        issues.append({"level": "medium", "section": "figures", "message": "未提供图表说明"})
    return {
        "status": "PASS" if not any(item["level"] == "high" for item in issues) else "BLOCKED",
        "mode": "paper-self-review",
        "result": {
            "manuscript_title": manuscript_title,
            "issue_count": len(issues),
            "issues": issues,
            "score": max(0, 100 - 15 * len(issues)),
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = review_paper(
        manuscript_title=str(raw_cfg.get("manuscript_title") or ""),
        sections=dict(raw_cfg.get("sections") or {}),
        figures=list(raw_cfg.get("figures") or []),
    )
    return write_affair_json_result(raw_cfg, config_path, "paper_self_review_result.json", result)
