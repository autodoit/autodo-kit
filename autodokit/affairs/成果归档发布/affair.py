"""成果归档发布事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


def archive_publication(
    manuscript_title: str,
    publication_status: str,
    archive_files: list[str],
    release_note: str,
) -> dict[str, Any]:
    """归档终稿并生成发布摘要。

    Args:
        manuscript_title: 稿件标题。
        publication_status: 发表状态。
        archive_files: 归档文件列表。
        release_note: 发布说明。

    Returns:
        事务标准结果。

    Examples:
        >>> archive_publication("标题", "accepted", [], "")["status"]
        'PASS'
    """

    return {
        "status": "PASS",
        "mode": "publication-archive-release",
        "result": {
            "manuscript_title": manuscript_title,
            "publication_status": publication_status,
            "archive_files": archive_files,
            "archive_count": len(archive_files),
            "release_note": release_note,
            "closed": publication_status.strip().lower() in {"accepted", "published"},
        },
    }


@affair_auto_git_commit("A160")
def execute(config_path: Path) -> list[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置文件路径。

    Returns:
        事务产物路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    result = archive_publication(
        manuscript_title=str(raw_cfg.get("manuscript_title") or ""),
        publication_status=str(raw_cfg.get("publication_status") or ""),
        archive_files=list(raw_cfg.get("archive_files") or []),
        release_note=str(raw_cfg.get("release_note") or ""),
    )
    return write_affair_json_result(raw_cfg, config_path, "publication_archive_release_result.json", result)
