"""AOB 用户级内容聚合事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import (
    aob_aggregate_user_content,
    load_json_or_py,
    write_affair_json_result,
)


def execute(config_path: Path) -> list[Path]:
    """执行 AOB 用户级内容聚合事务。

    Args:
        config_path: 事务配置文件绝对路径。

    Returns:
        list[Path]: 结果文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    execution_result = aob_aggregate_user_content(
        source_paths=[str(item).strip() for item in list(raw_cfg.get("source_paths") or []) if str(item).strip()],
        scopes=[str(item).strip() for item in list(raw_cfg.get("scopes") or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(raw_cfg.get("project_dirs") or []) if str(item).strip()],
        home_dir=str(raw_cfg.get("home_dir") or "").strip(),
        dry_run=bool(raw_cfg.get("dry_run", True)),
        skip_items_sync=bool(raw_cfg.get("skip_items_sync", False)),
        repo_root=str(raw_cfg.get("repo_root") or "").strip(),
    )
    if isinstance(execution_result, dict):
        result = dict(execution_result)
        result.setdefault("mode", "aggregate_user_content")
        result["status"] = str(result.get("status") or "FAIL")
        result["code"] = int(result.get("code", 1))
    else:
        code = int(execution_result)
        result = {
            "status": "PASS" if code == 0 else "FAIL",
            "code": code,
            "mode": "aggregate_user_content",
        }
    for field in ["source_paths", "scopes", "project_dirs", "home_dir", "dry_run", "skip_items_sync", "repo_root"]:
        result.setdefault(field, raw_cfg.get(field))
    return write_affair_json_result(
        raw_cfg,
        config_path,
        "aob_aggregate_user_content_result.json",
        result,
    )