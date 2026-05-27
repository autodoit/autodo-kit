"""AOB 统一业务事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import (
    aob_aggregate_user_content,
    aob_backup_user_content,
    aob_check_opencode_deploy_regression,
    aob_convert_workspace,
    aob_deploy_workflow,
    aob_import_external_templates,
    aob_publish_user_content,
    aob_update_user_content,
    aob_sync_items,
    aob_validate_content,
    load_json_or_py,
    write_affair_json_result,
)


def execute(config_path: Path) -> list[Path]:
    """执行 AOB 统一业务事务。

    Args:
        config_path: 事务配置文件绝对路径。

    Returns:
        list[Path]: 结果文件路径列表。

    Raises:
        ValueError: 当 mode 缺失或业务参数不合法时抛出。
    """

    raw_cfg = load_json_or_py(config_path)
    mode = str(raw_cfg.get("mode") or "").strip()
    if not mode:
        raise ValueError("mode 不能为空")

    mode_handlers: dict[str, tuple[callable, list[str]]] = {
        "validate_content": (
            lambda: aob_validate_content(
                input_path=str(raw_cfg.get("input_path") or "libs").strip() or "libs",
                repo_root=str(raw_cfg.get("repo_root") or "").strip(),
            ),
            ["input_path", "repo_root"],
        ),
        "sync_items": (
            lambda: aob_sync_items(
                strategy=str(raw_cfg.get("strategy") or "mtime_size_then_hash").strip() or "mtime_size_then_hash",
                dry_run=bool(raw_cfg.get("dry_run", True)),
                repo_root=str(raw_cfg.get("repo_root") or "").strip(),
            ),
            ["strategy", "dry_run", "repo_root"],
        ),
        "aggregate_user_content": (
            lambda: aob_aggregate_user_content(
                source_paths=[str(item).strip() for item in list(raw_cfg.get("source_paths") or []) if str(item).strip()],
                scopes=[str(item).strip() for item in list(raw_cfg.get("scopes") or []) if str(item).strip()],
                project_dirs=[str(item).strip() for item in list(raw_cfg.get("project_dirs") or []) if str(item).strip()],
                home_dir=str(raw_cfg.get("home_dir") or "").strip(),
                dry_run=bool(raw_cfg.get("dry_run", True)),
                skip_items_sync=bool(raw_cfg.get("skip_items_sync", False)),
                repo_root=str(raw_cfg.get("repo_root") or "").strip(),
            ),
            ["source_paths", "scopes", "project_dirs", "home_dir", "dry_run", "skip_items_sync", "repo_root"],
        ),
        "publish_user_content": (
            lambda: aob_publish_user_content(
                target_paths=[str(item).strip() for item in list(raw_cfg.get("target_paths") or []) if str(item).strip()],
                scopes=[str(item).strip() for item in list(raw_cfg.get("scopes") or []) if str(item).strip()],
                project_dirs=[str(item).strip() for item in list(raw_cfg.get("project_dirs") or []) if str(item).strip()],
                home_dir=str(raw_cfg.get("home_dir") or "").strip(),
                engine_vendors=[str(item).strip() for item in list(raw_cfg.get("engine_vendors") or []) if str(item).strip()],
                ide_vendors=[str(item).strip() for item in list(raw_cfg.get("ide_vendors") or []) if str(item).strip()],
                include_missing=bool(raw_cfg.get("include_missing", False)),
                dry_run=bool(raw_cfg.get("dry_run", True)),
                repo_root=str(raw_cfg.get("repo_root") or "").strip(),
            ),
            ["target_paths", "scopes", "project_dirs", "home_dir", "engine_vendors", "ide_vendors", "include_missing", "dry_run", "repo_root"],
        ),
        "backup_user_content": (
            lambda: aob_backup_user_content(
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
            ),
            ["target_paths", "scopes", "project_dirs", "home_dir", "engine_vendors", "ide_vendors", "include_missing", "backup_dir", "dry_run", "repo_root"],
        ),
        "update_user_content": (
            lambda: aob_update_user_content(
                target_paths=[str(item).strip() for item in list(raw_cfg.get("target_paths") or []) if str(item).strip()],
                scopes=[str(item).strip() for item in list(raw_cfg.get("scopes") or []) if str(item).strip()],
                project_dirs=[str(item).strip() for item in list(raw_cfg.get("project_dirs") or []) if str(item).strip()],
                home_dir=str(raw_cfg.get("home_dir") or "").strip(),
                engine_vendors=[str(item).strip() for item in list(raw_cfg.get("engine_vendors") or []) if str(item).strip()],
                ide_vendors=[str(item).strip() for item in list(raw_cfg.get("ide_vendors") or []) if str(item).strip()],
                include_missing=bool(raw_cfg.get("include_missing", False)),
                backup_dir=str(raw_cfg.get("backup_dir") or "").strip(),
                dry_run=bool(raw_cfg.get("dry_run", True)),
                skip_backup=bool(raw_cfg.get("skip_backup", False)),
                skip_items_sync=bool(raw_cfg.get("skip_items_sync", False)),
                simulate_only=bool(raw_cfg.get("simulate_only", False)),
                sandbox_dir=str(raw_cfg.get("sandbox_dir") or "").strip(),
                repo_root=str(raw_cfg.get("repo_root") or "").strip(),
            ),
            [
                "target_paths",
                "scopes",
                "project_dirs",
                "home_dir",
                "engine_vendors",
                "ide_vendors",
                "include_missing",
                "backup_dir",
                "dry_run",
                "skip_backup",
                "skip_items_sync",
                "simulate_only",
                "sandbox_dir",
                "repo_root",
            ],
        ),
        "import_external_templates": (
            lambda: aob_import_external_templates(
                source_paths=[str(item).strip() for item in list(raw_cfg.get("source_paths") or []) if str(item).strip()],
                target_library_dir_name=str(raw_cfg.get("target_library_dir_name") or "").strip(),
                tags=str(raw_cfg.get("tags") or "").strip(),
                import_mode=str(raw_cfg.get("import_mode") or "add").strip() or "add",
                overwrite_existing=bool(raw_cfg.get("overwrite_existing", False)),
                dry_run=bool(raw_cfg.get("dry_run", True)),
                repo_root=str(raw_cfg.get("repo_root") or "").strip(),
            ),
            [
                "source_paths",
                "target_library_dir_name",
                "tags",
                "import_mode",
                "overwrite_existing",
                "dry_run",
                "repo_root",
            ],
        ),
        "convert_workspace": (
            lambda: aob_convert_workspace(
                project_dir=str(raw_cfg.get("project_dir") or "").strip(),
                source_engine=str(raw_cfg.get("source_engine") or "").strip(),
                target_engine=str(raw_cfg.get("target_engine") or "").strip(),
                source_ide=str(raw_cfg.get("source_ide") or "").strip(),
                target_ide=str(raw_cfg.get("target_ide") or "").strip(),
                source_os=str(raw_cfg.get("source_os") or "").strip(),
                target_os=str(raw_cfg.get("target_os") or "").strip(),
                title=str(raw_cfg.get("title") or "").strip(),
                dry_run=bool(raw_cfg.get("dry_run", False)),
                canonical_dump_path=str(raw_cfg.get("canonical_dump_path") or "").strip(),
                validation_report_path=str(raw_cfg.get("validation_report_path") or "").strip(),
                report_output_dir=str(raw_cfg.get("output_dir") or "").strip(),
                allow_downgrade=bool(raw_cfg.get("allow_downgrade", True)),
                target_capability_mode=str(raw_cfg.get("target_capability_mode") or "balanced").strip() or "balanced",
                repo_root=str(raw_cfg.get("repo_root") or "").strip(),
            ),
            [
                "project_dir",
                "source_engine",
                "target_engine",
                "source_ide",
                "target_ide",
                "source_os",
                "target_os",
                "title",
                "dry_run",
                "canonical_dump_path",
                "validation_report_path",
                "allow_downgrade",
                "target_capability_mode",
                "repo_root",
            ],
        ),
        "deploy_workflow": (
            lambda: aob_deploy_workflow(
                workflow_id=str(raw_cfg.get("workflow") or "academic").strip() or "academic",
                engine_ids=[str(item).strip() for item in list(raw_cfg.get("engine_ids") or ["opencode"]) if str(item).strip()],
                target_dir=str(raw_cfg.get("target_dir") or "").strip(),
                repo_root=str(raw_cfg.get("repo_root") or "").strip(),
                project_name=str(raw_cfg.get("project_name") or "").strip(),
                tags=str(raw_cfg.get("tags") or "").strip(),
                on_conflict=str(raw_cfg.get("on_conflict") or "skip").strip() or "skip",
                skip_health_check=bool(raw_cfg.get("skip_health_check", False)),
                extras=str(raw_cfg.get("extras") or "none").strip() or "none",
                git_init_mode=str(raw_cfg.get("git_init_mode") or "auto").strip() or "auto",
                dry_run=bool(raw_cfg.get("dry_run", True)),
            ),
            [
                "workflow",
                "engine_ids",
                "target_dir",
                "repo_root",
                "project_name",
                "tags",
                "on_conflict",
                "skip_health_check",
                "extras",
                "git_init_mode",
                "dry_run",
            ],
        ),
        "check_opencode_deploy_regression": (
            lambda: aob_check_opencode_deploy_regression(
                target_root=str(raw_cfg.get("target_root") or "").strip(),
                repo_root=str(raw_cfg.get("repo_root") or "").strip(),
                agents_dir=str(raw_cfg.get("agents_dir") or ".opencode/agents").strip() or ".opencode/agents",
                opencode_json=str(raw_cfg.get("opencode_json") or "opencode.json").strip() or "opencode.json",
                project_name=str(raw_cfg.get("project_name") or "").strip(),
                tags=str(raw_cfg.get("tags") or "学术研究,文档管理").strip() or "学术研究,文档管理",
            ),
            ["target_root", "repo_root", "agents_dir", "opencode_json", "project_name", "tags"],
        ),
    }

    if mode not in mode_handlers:
        raise ValueError(
            "不支持的 mode。可选值：validate_content, sync_items, aggregate_user_content, publish_user_content, backup_user_content, update_user_content, import_external_templates, "
            "convert_workspace, deploy_workflow, check_opencode_deploy_regression"
        )

    if mode == "import_external_templates":
        if not [str(item).strip() for item in list(raw_cfg.get("source_paths") or []) if str(item).strip()]:
            raise ValueError("source_paths 不能为空")
        if not str(raw_cfg.get("target_library_dir_name") or "").strip():
            raise ValueError("target_library_dir_name 不能为空")
        if not str(raw_cfg.get("tags") or "").strip():
            raise ValueError("tags 不能为空")
    if mode == "convert_workspace":
        if not str(raw_cfg.get("project_dir") or "").strip():
            raise ValueError("project_dir 不能为空")
        if not str(raw_cfg.get("source_engine") or "").strip():
            raise ValueError("source_engine 不能为空")
        if not str(raw_cfg.get("target_engine") or "").strip():
            raise ValueError("target_engine 不能为空")
    if mode == "deploy_workflow" and not str(raw_cfg.get("target_dir") or "").strip():
        raise ValueError("target_dir 不能为空")
    if mode == "check_opencode_deploy_regression" and not str(raw_cfg.get("target_root") or "").strip():
        raise ValueError("target_root 不能为空")

    runner, captured_fields = mode_handlers[mode]
    execution_result = runner()
    if isinstance(execution_result, dict):
        result = dict(execution_result)
        result.setdefault("mode", mode)
        result["status"] = str(result.get("status") or "FAIL")
        result["code"] = int(result.get("code", 1))
    else:
        code = int(execution_result)
        result = {"status": "PASS" if code == 0 else "FAIL", "code": code, "mode": mode}
    for field in captured_fields:
        result.setdefault(field, raw_cfg.get(field))
    return write_affair_json_result(raw_cfg, config_path, "aob_business_result.json", result)