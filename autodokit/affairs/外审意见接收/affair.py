"""外审意见接收事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def triage_review(decision: str, review_comments: list[dict[str, Any]], editor_notes: str) -> dict[str, Any]:
    """解析外审决定并给出分流建议。

    Args:
        decision: 编辑决定。
        review_comments: 审稿意见列表。
        editor_notes: 编辑附注。

    Returns:
        事务标准结果。

    Examples:
        >>> triage_review("minor_revision", [], "")["result"]["route"]
        'review-response'
    """

    normalized = decision.strip().lower()
    if normalized in {"accept", "accepted", "publish"}:
        route = "publication-archive-release"
    elif normalized in {"reject_transfer", "transfer"}:
        route = "journal-submission"
    else:
        route = "review-response"

    return {
        "status": "PASS",
        "mode": "external-review-intake",
        "result": {
            "decision": decision,
            "editor_notes": editor_notes,
            "review_comment_count": len(review_comments),
            "review_comments": review_comments,
            "route": route,
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置文件路径。

    Returns:
        事务产物路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    result = triage_review(
        decision=str(raw_cfg.get("decision") or ""),
        review_comments=list(raw_cfg.get("review_comments") or []),
        editor_notes=str(raw_cfg.get("editor_notes") or ""),
    )
    return write_affair_json_result(raw_cfg, config_path, "external_review_intake_result.json", result)
