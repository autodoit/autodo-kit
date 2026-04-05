"""AOB 工具执行能力统一入口。

本模块把 AOB 历史脚本能力统一收敛到 ``autodokit.tools``，
提供两类调用方式：

1. 透传 CLI 参数列表的执行函数；
2. 面向常用场景的一键调用函数。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from autodokit.tools.atomic.aob_runtime import (
    aoc_main,
    deploy_main,
    library_main,
    regression_opencode_deploy_check_main,
)


def _resolve_aob_repo_root(repo_root: str = "") -> Path:
    """解析 AOB 仓库根目录。

    Args:
        repo_root: 显式传入的仓库根目录。

    Returns:
        Path: 解析后的仓库根目录。
    """

    if str(repo_root).strip():
        return Path(repo_root).expanduser().resolve()

    env_root = str(os.environ.get("AOB_REPO_ROOT", "")).strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    kit_root = Path(__file__).resolve().parents[2]
    sibling_aob = kit_root.parent / "autodo-lib"
    if sibling_aob.exists():
        return sibling_aob.resolve()

    return kit_root.resolve()


def _with_argv(*, argv: list[str], program: str, runner: callable) -> int:
    """在受控参数上下文中执行入口函数。

    Args:
        argv: 传递给入口函数的参数列表（不含程序名）。
        program: 模拟的程序名。
        runner: 入口函数。

    Returns:
        int: 退出码。

    Raises:
        SystemExit: 当入口函数显式抛出 ``SystemExit`` 时，透传退出码。

    Examples:
        >>> callable(_with_argv)
        True
    """

    old_argv = list(sys.argv)
    sys.argv = [program, *list(argv)]
    try:
        result = runner()
        return int(result) if result is not None else 0
    except SystemExit as exc:  # pragma: no cover
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    finally:
        sys.argv = old_argv


def run_aob_aoc(argv: list[str] | None = None) -> int:
    """执行 AOC 工具。

    Args:
        argv: CLI 参数列表，不传时默认空列表。

    Returns:
        int: 退出码。
    """

    return _with_argv(argv=list(argv or []), program="aoc", runner=aoc_main)


def run_aob_deploy(argv: list[str] | None = None) -> int:
    """执行部署工具。

    Args:
        argv: CLI 参数列表，不传时默认空列表。

    Returns:
        int: 退出码。
    """

    return _with_argv(argv=list(argv or []), program="deploy", runner=deploy_main)


def run_aob_library(argv: list[str] | None = None) -> int:
    """执行本地库管理工具。

    Args:
        argv: CLI 参数列表，不传时默认空列表。

    Returns:
        int: 退出码。
    """

    return _with_argv(argv=list(argv or []), program="library", runner=library_main)


def run_aob_regression_opencode_deploy_check(argv: list[str] | None = None) -> int:
    """执行 OpenCode 部署回归检查。

    Args:
        argv: CLI 参数列表，不传时默认空列表。

    Returns:
        int: 退出码。
    """

    return _with_argv(
        argv=list(argv or []),
        program="regression_opencode_deploy_check",
        runner=regression_opencode_deploy_check_main,
    )


def run_aob_workflow_deploy(
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
    """执行一键工作流部署。

    Args:
        workflow_id: 工作流 ID。
        engine_ids: 目标引擎列表。
        target_dir: 目标项目目录。
        repo_root: AOB 仓库根目录。
        project_name: 可选项目名。
        tags: 可选标签文本（逗号分隔）。
        on_conflict: 冲突策略。
        skip_health_check: 是否跳过健康检查。
        extras: 扩展包策略。
        git_init_mode: Git 初始化策略。
        dry_run: 是否试运行。

    Returns:
        int: 退出码。

    Raises:
        ValueError: 参数不合法时抛出。
    """

    if not workflow_id.strip():
        raise ValueError("workflow_id 不能为空")
    if not engine_ids:
        raise ValueError("engine_ids 不能为空")
    if not str(target_dir).strip():
        raise ValueError("target_dir 不能为空")

    args: list[str] = [
        "workflow",
        "--workflow",
        workflow_id.strip(),
        "--engine",
        ",".join([str(item).strip() for item in engine_ids if str(item).strip()]),
        "--target",
        str(target_dir).strip(),
        "--on-conflict",
        str(on_conflict).strip() or "skip",
        "--extras",
        str(extras).strip() or "none",
        "--git-init",
        str(git_init_mode).strip() or "auto",
    ]

    if str(repo_root).strip():
        args.extend(["--repo-root", str(repo_root).strip()])
    if str(project_name).strip():
        args.extend(["--project-name", str(project_name).strip()])
    if str(tags).strip():
        args.extend(["--tags", str(tags).strip()])
    if skip_health_check:
        args.append("--skip-health-check")
    if dry_run:
        args.append("--dry-run")

    return run_aob_deploy(args)


def run_aob_items_sync(*, strategy: str = "mtime_size_then_hash", dry_run: bool = True, repo_root: str = "") -> int:
    """执行 `items sync`。

    Args:
        strategy: 同步策略。
        dry_run: 是否试运行。
        repo_root: AOB 仓库根目录。

    Returns:
        int: 退出码。
    """

    args: list[str] = ["items", "sync", "--strategy", str(strategy).strip() or "mtime_size_then_hash"]
    if str(repo_root).strip():
        args.extend(["--repo-root", str(repo_root).strip()])
    if dry_run:
        args.append("--dry-run")
    return run_aob_library(args)


def run_aob_external_templates_import(
    *,
    source_paths: list[str],
    target_library_dir_name: str,
    tags: str,
    import_mode: str = "add",
    overwrite_existing: bool = False,
    dry_run: bool = True,
    repo_root: str = "",
) -> int:
    """执行外部模板导入流程。

    Args:
        source_paths: 外部来源路径列表（文件或目录绝对路径）。
        target_library_dir_name: 目标模板目录名。
        tags: 标签文本（逗号分隔）。
        import_mode: 标签写入模式，支持 ``add``、``replace``。
        overwrite_existing: 复制冲突时是否覆盖。
        dry_run: 是否试运行。
        repo_root: AOB 仓库根目录。

    Returns:
        int: 退出码。

    Raises:
        ValueError: 参数不合法时抛出。
        FileNotFoundError: 来源路径不存在时抛出。
    """

    if not source_paths:
        raise ValueError("source_paths 不能为空")
    if not str(target_library_dir_name).strip():
        raise ValueError("target_library_dir_name 不能为空")
    if str(import_mode).strip() not in {"add", "replace"}:
        raise ValueError("import_mode 仅支持 add 或 replace")
    if not str(tags).strip():
        raise ValueError("tags 不能为空")

    repo_root_path = _resolve_aob_repo_root(repo_root)
    templates_root = repo_root_path / "libs" / "templates"
    destination_root = templates_root / str(target_library_dir_name).strip()

    source_path_objs: list[Path] = []
    for raw in source_paths:
        src = Path(str(raw).strip()).expanduser().resolve()
        if not src.exists():
            raise FileNotFoundError(f"来源路径不存在：{src}")
        source_path_objs.append(src)

    if not dry_run:
        destination_root.mkdir(parents=True, exist_ok=True)
        for source in source_path_objs:
            target_path = destination_root / source.name
            if source.is_dir():
                if target_path.exists() and not overwrite_existing:
                    raise ValueError(f"目标目录已存在且禁止覆盖：{target_path}")
                shutil.copytree(source, target_path, dirs_exist_ok=overwrite_existing)
                continue
            if target_path.exists() and not overwrite_existing:
                raise ValueError(f"目标文件已存在且禁止覆盖：{target_path}")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target_path)

    relative_path = destination_root.relative_to(repo_root_path).as_posix()
    sync_code = run_aob_items_sync(dry_run=dry_run, repo_root=str(repo_root_path))
    if sync_code != 0:
        return sync_code

    import_args: list[str] = [
        "items",
        "import",
        "--tags",
        str(tags).strip(),
        "--paths",
        relative_path,
        "--mode",
        str(import_mode).strip(),
    ]
    if dry_run:
        import_args.append("--dry-run")
    import_args.extend(["--repo-root", str(repo_root_path)])
    return run_aob_library(import_args)


def run_aob_workspace_convert(
    *,
    project_dir: str,
    source_engine: str,
    target_engine: str,
    title: str = "",
    dry_run: bool = False,
    repo_root: str = "",
) -> int:
    """执行办公区跨引擎转换。

    Args:
        project_dir: 模板项目目录。
        source_engine: 来源引擎。
        target_engine: 目标引擎。
        title: 可选标题。
        dry_run: 是否试运行。
        repo_root: AOB 仓库根目录。

    Returns:
        int: 退出码。
    """

    args: list[str] = [
        "workspace-convert",
        "--project-dir",
        str(project_dir).strip(),
        "--source-engine",
        str(source_engine).strip(),
        "--target-engine",
        str(target_engine).strip(),
    ]
    if str(repo_root).strip():
        args.extend(["--repo-root", str(repo_root).strip()])
    if str(title).strip():
        args.extend(["--title", str(title).strip()])
    if dry_run:
        args.append("--dry-run")
    return run_aob_deploy(args)
