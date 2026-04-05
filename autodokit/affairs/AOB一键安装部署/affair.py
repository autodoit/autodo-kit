"""AOB 一键安装部署事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import (
    load_json_or_py,
    run_aob_workflow_deploy,
    write_affair_json_result,
)


def execute(config_path: Path) -> list[Path]:
    """执行 AOB 一键安装部署事务。

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
    workflow_id = str(raw_cfg.get("workflow") or "academic").strip()
    engine_ids = [str(item).strip() for item in list(raw_cfg.get("engine_ids") or ["opencode"]) if str(item).strip()]
    target_dir = str(raw_cfg.get("target_dir") or "").strip()
    if not target_dir:
        raise ValueError("target_dir 不能为空")

    code = run_aob_workflow_deploy(
        workflow_id=workflow_id,
        engine_ids=engine_ids,
        target_dir=target_dir,
        repo_root=str(raw_cfg.get("repo_root") or "").strip(),
        project_name=str(raw_cfg.get("project_name") or "").strip(),
        tags=str(raw_cfg.get("tags") or "").strip(),
        on_conflict=str(raw_cfg.get("on_conflict") or "skip").strip(),
        skip_health_check=bool(raw_cfg.get("skip_health_check", False)),
        extras=str(raw_cfg.get("extras") or "none").strip(),
        git_init_mode=str(raw_cfg.get("git_init_mode") or "auto").strip(),
        dry_run=bool(raw_cfg.get("dry_run", True)),
    )

    result = {
        "status": "PASS" if code == 0 else "FAIL",
        "code": int(code),
        "workflow": workflow_id,
        "engine_ids": engine_ids,
        "target_dir": target_dir,
    }
    return write_affair_json_result(raw_cfg, config_path, "aob_one_click_deploy_result.json", result)
