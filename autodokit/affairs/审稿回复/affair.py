"""审稿回复事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from autodokit.tools import load_json_or_py


class RevisionResponseEngine:
    """审稿回复引擎。"""

    def run(self, comments: list[str], manuscript_title: str) -> dict[str, Any]:
        """生成审稿意见逐条回复草稿。"""

        if not manuscript_title.strip():
            raise ValueError("manuscript_title 不能为空")

        normalized = [comment.strip() for comment in comments if comment.strip()] or ["请补充对主要结论的解释与边界条件说明。"]
        items = []
        for index, comment in enumerate(normalized, start=1):
            items.append(
                {
                    "comment_id": index,
                    "comment": comment,
                    "action": "补充分析并在修订稿中标注改动位置。",
                    "response": f"感谢审稿人意见。针对“{comment}”，我们已在修订稿中完成对应修改并补充说明。",
                }
            )

        return {"manuscript_title": manuscript_title, "item_count": len(items), "items": items}


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    cfg = load_json_or_py(config_path)
    result = RevisionResponseEngine().run(
        comments=list(cfg.get("comments") or []),
        manuscript_title=str(cfg.get("manuscript_title") or ""),
    )
    output_dir = Path(str(cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError("output_dir 必须为绝对路径")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "revision_response_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
