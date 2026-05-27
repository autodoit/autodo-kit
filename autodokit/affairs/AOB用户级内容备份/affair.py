"""AOB 用户级内容备份事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import (
    aob_backup_user_content,
    load_json_or_py,
    write_affair_json_result,
)


def execute(config_path: Path) -> list[Path]:
    """执行 AOB 用户级内容备份事务。

    Args:
        config_path: 事务配置文件绝对路径。

    Returns:
        list[Path]: 结果文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    execution_result = aob_backup_user_content(
        target_paths=[str(item).strip() for item in list(raw_cfg.get("target_paths") or []) if str(item).strip()],
        scopes=[str(item).strip() for item in list(raw_cfg.get("scopes") or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(raw_cfg.get("project_dirs") or []) if str(item).strip()],
        home_dir=str(raw_cfg.get("home_dir") or "").strip(),
        engine_vendors=[str(item).strip() for item in list(raw_cfg.get("engine_vendors") or []) if str(item).strip()],
        ide_vendors=[str(item).strip() for item in list(raw_cfg.get("ide_vendors") or []) if str(item).strip()],
        include_missing=bool(raw_cfg.get("include_missing", False)),
        backup_dir=str(raw_cfg.get("backup_dir") or "").strip(),
        dry_run=bool(raw_cfg.get("dry_run", True)),
        repo_root=str(raw_cfg.get("repo_root") or "").strip(),
    )
    if isinstance(execution_result, dict):
        result = dict(execution_result)
        result.setdefault("mode", "backup_user_content")
        result["status"] = str(result.get("status") or "FAIL")
        result["code"] = int(result.get("code", 1))
    else:
        code = int(execution_result)
        result = {
            "status": "PASS" if code == 0 else "FAIL",
            "code": code,
            "mode": "backup_user_content",
        }
    for field in [
        "target_paths",
        "scopes",
        "project_dirs",
        "home_dir",
        "engine_vendors",
        "ide_vendors",
        "include_missing",
        "backup_dir",
        "dry_run",
        "repo_root",
    ]:
        result.setdefault(field, raw_cfg.get(field))
    return write_affair_json_result(
        raw_cfg,
        config_path,
        "aob_backup_user_content_result.json",
        result,
    )