"""审稿意见拆解事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def break_down_review_comments(comments: list[str], manuscript_title: str) -> dict[str, Any]:
    """拆解审稿意见并生成处理路径。"""

    items: list[dict[str, Any]] = []
    for index, comment in enumerate([item.strip() for item in comments if item.strip()], start=1):
        if "稳健" in comment or "机制" in comment:
            route = "补分析"
        elif "贡献" in comment or "写作" in comment:
            route = "补写作"
        else:
            route = "解释说明"
        items.append({"comment_id": index, "comment": comment, "route": route})
    return {
        "status": "PASS",
        "mode": "review-response",
        "result": {
            "manuscript_title": manuscript_title,
            "item_count": len(items),
            "items": items,
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = break_down_review_comments(
        comments=list(raw_cfg.get("comments") or []),
        manuscript_title=str(raw_cfg.get("manuscript_title") or ""),
    )
    return write_affair_json_result(raw_cfg, config_path, "review_response_result.json", result)
