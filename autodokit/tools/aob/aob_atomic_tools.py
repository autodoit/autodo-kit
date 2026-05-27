"""AOB 原子工具入口。

本模块面向 AOK 事务编排，提供职责单一的 AOB 原子动作封装，
避免事务层直接消费基于 argv 的通用 CLI 入口。

公开导出优先通过 ``autodokit.tools.aob`` 访问。
"""

from __future__ import annotations

from autodokit.tools.aob.aob_workspace_pipeline import execute_workspace_conversion_pipeline
from autodokit.tools.aob.aob_tools import (
    run_aob_aoc,
    run_aob_aggregate_user_content,
    run_aob_backup_user_content,
    run_aob_external_templates_import,
    run_aob_items_sync,
    run_aob_publish_user_content,
    run_aob_update_user_content,
    run_aob_regression_opencode_deploy_check,
    run_aob_workflow_deploy,
)


def aob_validate_content(*, input_path: str = "libs", repo_root: str = "") -> int:
    """执行 AOB 内容编译校验。

    Args:
        input_path: AOL 输入路径，通常为 ``libs`` 或单个 AOL 文件。
        repo_root: AOB 仓库根目录。

    Returns:
        int: 退出码。
    """

    args: list[str] = ["validate", "--input", str(input_path).strip() or "libs"]
    if str(repo_root).strip():
        args.extend(["--repo-root", str(repo_root).strip()])
    return run_aob_aoc(args)


def aob_sync_items(*, strategy: str = "mtime_size_then_hash", dry_run: bool = True, repo_root: str = "") -> int:
    """执行 AOB 内容库条目同步。

    Args:
        strategy: items 同步策略。
        dry_run: 是否试运行。
        repo_root: AOB 仓库根目录。

    Returns:
        int: 退出码。
    """

    return run_aob_items_sync(strategy=strategy, dry_run=dry_run, repo_root=repo_root)


def aob_import_external_templates(
    *,
    source_paths: list[str],
    target_library_dir_name: str,
    tags: str,
    import_mode: str = "add",
    overwrite_existing: bool = False,
    dry_run: bool = True,
    repo_root: str = "",
) -> int:
    """执行 AOB 外部模板导入。

    Args:
        source_paths: 来源路径列表。
        target_library_dir_name: 目标模板目录名。
        tags: 标签文本。
        import_mode: 标签写入模式。
        overwrite_existing: 是否覆盖同名文件。
        dry_run: 是否试运行。
        repo_root: AOB 仓库根目录。

    Returns:
        int: 退出码。
    """

    return run_aob_external_templates_import(
        source_paths=source_paths,
        target_library_dir_name=target_library_dir_name,
        tags=tags,
        import_mode=import_mode,
        overwrite_existing=overwrite_existing,
        dry_run=dry_run,
        repo_root=repo_root,
    )


def aob_aggregate_user_content(
    *,
    source_paths: list[str] | None = None,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    home_dir: str = "",
    dry_run: bool = True,
    skip_items_sync: bool = False,
    repo_root: str = "",
) -> int:
    """执行用户级 AI 内容聚合。

    Args:
        source_paths: 可选来源路径列表；为空时自动发现。
        home_dir: 可选用户主目录覆盖值。
        dry_run: 是否试运行。
        skip_items_sync: 是否跳过 items sync。
        repo_root: AOB 仓库根目录。

    Returns:
        int: 退出码。
    """

    return run_aob_aggregate_user_content(
        source_paths=source_paths,
        scopes=scopes,
        project_dirs=project_dirs,
        home_dir=home_dir,
        dry_run=dry_run,
        skip_items_sync=skip_items_sync,
        repo_root=repo_root,
    )


def aob_publish_user_content(
    *,
    target_paths: list[str] | None = None,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    home_dir: str = "",
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    include_missing: bool = False,
    dry_run: bool = True,
    repo_root: str = "",
) -> int:
    """执行用户级 AI 内容发布。"""

    return run_aob_publish_user_content(
        target_paths=target_paths,
        scopes=scopes,
        project_dirs=project_dirs,
        home_dir=home_dir,
        engine_vendors=engine_vendors,
        ide_vendors=ide_vendors,
        include_missing=include_missing,
        dry_run=dry_run,
        repo_root=repo_root,
    )


def aob_backup_user_content(
    *,
    target_paths: list[str] | None = None,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    home_dir: str = "",
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    include_missing: bool = False,
    backup_dir: str = "",
    dry_run: bool = True,
    repo_root: str = "",
) -> int:
    """执行用户级 AI 内容备份。"""

    return run_aob_backup_user_content(
        target_paths=target_paths,
        scopes=scopes,
        project_dirs=project_dirs,
        home_dir=home_dir,
        engine_vendors=engine_vendors,
        ide_vendors=ide_vendors,
        include_missing=include_missing,
        backup_dir=backup_dir,
        dry_run=dry_run,
        repo_root=repo_root,
    )


def aob_update_user_content(
    *,
    target_paths: list[str] | None = None,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    home_dir: str = "",
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    include_missing: bool = False,
    backup_dir: str = "",
    dry_run: bool = True,
    skip_backup: bool = False,
    skip_items_sync: bool = False,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    repo_root: str = "",
) -> int:
    """执行用户级 AI 内容同步，默认按备份、聚合、发布顺序串联。"""

    return run_aob_update_user_content(
        target_paths=target_paths,
        scopes=scopes,
        project_dirs=project_dirs,
        home_dir=home_dir,
        engine_vendors=engine_vendors,
        ide_vendors=ide_vendors,
        include_missing=include_missing,
        backup_dir=backup_dir,
        dry_run=dry_run,
        skip_backup=skip_backup,
        skip_items_sync=skip_items_sync,
        simulate_only=simulate_only,
        sandbox_dir=sandbox_dir,
        repo_root=repo_root,
    )


def aob_convert_workspace(
    *,
    project_dir: str,
    source_engine: str,
    target_engine: str,
    source_ide: str = "",
    target_ide: str = "",
    source_os: str = "",
    target_os: str = "",
    title: str = "",
    dry_run: bool = False,
    canonical_dump_path: str = "",
    validation_report_path: str = "",
    report_output_dir: str = "",
    allow_downgrade: bool = True,
    target_capability_mode: str = "balanced",
    repo_root: str = "",
) -> dict[str, object]:
    """执行 AOB 办公区跨引擎转换。

    Args:
        project_dir: 项目目录。
        source_engine: 来源引擎。
        target_engine: 目标引擎。
        source_ide: 来源 IDE。
        target_ide: 目标 IDE。
        source_os: 来源操作系统。
        target_os: 目标操作系统。
        title: 转换标题。
        dry_run: 是否试运行。
        canonical_dump_path: canonical AOL dump 输出路径。
        validation_report_path: capability 校验报告输出路径。
        report_output_dir: 默认报告输出目录。
        allow_downgrade: 是否允许降级输出。
        target_capability_mode: 目标能力模式。
        repo_root: AOB 仓库根目录。

    Returns:
        dict[str, object]: 转换结果与报告路径。
    """

    result = execute_workspace_conversion_pipeline(
        project_dir=project_dir,
        source_engine=source_engine,
        target_engine=target_engine,
        source_ide=source_ide,
        target_ide=target_ide,
        source_os=source_os,
        target_os=target_os,
        title=title,
        dry_run=dry_run,
        canonical_dump_path=canonical_dump_path,
        validation_report_path=validation_report_path,
        report_output_dir=report_output_dir,
        allow_downgrade=allow_downgrade,
        target_capability_mode=target_capability_mode,
        repo_root=repo_root,
    )
    return result


def aob_deploy_workflow(
    *,
    workflow_id: str,
    engine_ids: list[str],
    target_dir: str,
    repo_root: str = "",
    project_name: str = "",
    tags: str = "",
    on_conflict: str = "skip",
    skip_health_check: bool = False,
    extras: str = "none",
    git_init_mode: str = "auto",
    dry_run: bool = True,
) -> int:
    """执行 AOB 工作流部署。

    Args:
        workflow_id: 工作流 ID。
        engine_ids: 目标引擎列表。
        target_dir: 目标目录。
        repo_root: AOB 仓库根目录。
        project_name: 项目名。
        tags: 标签文本。
        on_conflict: 冲突策略。
        skip_health_check: 是否跳过健康检查。
        extras: 扩展包模式。
        git_init_mode: Git 初始化模式。
        dry_run: 是否试运行。

    Returns:
        int: 退出码。
    """

    return run_aob_workflow_deploy(
        workflow_id=workflow_id,
        engine_ids=engine_ids,
        target_dir=target_dir,
        repo_root=repo_root,
        project_name=project_name,
        tags=tags,
        on_conflict=on_conflict,
        skip_health_check=skip_health_check,
        extras=extras,
        git_init_mode=git_init_mode,
        dry_run=dry_run,
    )


def aob_check_opencode_deploy_regression(
    *,
    target_root: str,
    repo_root: str = "",
    agents_dir: str = ".opencode/agents",
    opencode_json: str = "opencode.json",
    project_name: str = "",
    tags: str = "学术研究,文档管理",
) -> int:
    """执行 OpenCode 部署回归检查。

    Args:
        target_root: 目标根目录。
        repo_root: AOB 仓库根目录。
        agents_dir: agents 相对目录。
        opencode_json: 配置文件名。
        project_name: 项目名称。
        tags: 部署标签。

    Returns:
        int: 退出码。
    """

    args: list[str] = [
        "--target-root",
        str(target_root).strip(),
        "--agents-dir",
        str(agents_dir).strip() or ".opencode/agents",
        "--opencode-json",
        str(opencode_json).strip() or "opencode.json",
        "--tags",
        str(tags).strip() or "学术研究,文档管理",
    ]
    if str(repo_root).strip():
        args.extend(["--repo-root", str(repo_root).strip()])
    if str(project_name).strip():
        args.extend(["--project-name", str(project_name).strip()])
    return run_aob_regression_opencode_deploy_check(args)
