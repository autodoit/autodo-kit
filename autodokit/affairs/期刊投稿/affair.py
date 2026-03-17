"""期刊投稿事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def prepare_submission(
    manuscript_title: str,
    target_journal: str,
    package_files: list[str],
    version_tag: str,
) -> dict[str, Any]:
    """整理投稿包并登记投稿版本。

    Args:
        manuscript_title: 稿件标题。
        target_journal: 目标期刊。
        package_files: 投稿包文件路径列表。
        version_tag: 版本标签。

    Returns:
        事务标准结果。

    Examples:
        >>> prepare_submission("标题", "期刊", [], "v1")["mode"]
        'journal-submission'
    """

    return {
        "status": "PASS",
        "mode": "journal-submission",
        "result": {
            "manuscript_title": manuscript_title,
            "target_journal": target_journal,
            "version_tag": version_tag,
            "package_count": len(package_files),
            "package_files": package_files,
            "submission_manifest": {
                "ready": True,
                "next": "external-review-intake",
            },
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
    result = prepare_submission(
        manuscript_title=str(raw_cfg.get("manuscript_title") or ""),
        target_journal=str(raw_cfg.get("target_journal") or ""),
        package_files=list(raw_cfg.get("package_files") or []),
        version_tag=str(raw_cfg.get("version_tag") or "v1"),
    )
    return write_affair_json_result(raw_cfg, config_path, "journal_submission_result.json", result)
