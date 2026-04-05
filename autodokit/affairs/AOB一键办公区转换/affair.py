"""AOB 一键办公区转换事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import (
    load_json_or_py,
    run_aob_workspace_convert,
    write_affair_json_result,
)


def execute(config_path: Path) -> list[Path]:
    """执行 AOB 一键办公区转换事务。

    Args:
        config_path: 事务配置文件绝对路径。

    Returns:
        list[Path]: 结果文件路径列表。

    Raises:
        ValueError: 参数缺失或参数类型不合法时抛出。

    Examples:
        >>> isinstance(config_path, Path)
        True
    """

    raw_cfg = load_json_or_py(config_path)
    project_dir = str(raw_cfg.get("project_dir") or "").strip()
    source_engine = str(raw_cfg.get("source_engine") or "").strip()
    target_engine = str(raw_cfg.get("target_engine") or "").strip()
    if not project_dir:
        raise ValueError("project_dir 不能为空")
    if not source_engine:
        raise ValueError("source_engine 不能为空")
    if not target_engine:
        raise ValueError("target_engine 不能为空")

    code = run_aob_workspace_convert(
        project_dir=project_dir,
        source_engine=source_engine,
        target_engine=target_engine,
        title=str(raw_cfg.get("title") or "").strip(),
        dry_run=bool(raw_cfg.get("dry_run", False)),
        repo_root=str(raw_cfg.get("repo_root") or "").strip(),
    )

    result = {
        "status": "PASS" if code == 0 else "FAIL",
        "code": int(code),
        "project_dir": project_dir,
        "source_engine": source_engine,
        "target_engine": target_engine,
    }
    return write_affair_json_result(raw_cfg, config_path, "aob_workspace_convert_result.json", result)
