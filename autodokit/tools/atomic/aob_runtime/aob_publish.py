# -*- coding: utf-8 -*-
"""AOB 发布原子工具（publish-user-content）。

将 canonical AOL 编译后发布到各引擎办公区（Copilot/Claude/OpenCode 等）。
"""

from __future__ import annotations

from .aob_common import *

import shutil
import tempfile
from pathlib import Path
from typing import Any


def 发布到单个目标并同步删除(
    *,
    aol: Any,
    target: 发布目标,
    dry_run: bool,
    warnings: list[str],
    previous_managed_files: set[str],
    journal: Any = None,
    cleanup_unknown: bool = False,
) -> tuple[dict[str, Any], set[str]]:
    """发布到单个目标并同步删除过期托管文件。"""

    stats = 构建发布统计(target)
    target_engine = 归一化引擎供应商(engine_vendor=target.engine_vendor, ide_vendor=target.ide_vendor)
    if str(target.engine_vendor or "").strip().lower() not in 默认AOC支持引擎:
        warnings.append(
            f"目标 {target.target_label} 的 engine_vendor={target.engine_vendor} 不在 AOC 支持列表，已映射为 {target_engine}"
        )
    stats["aoc_target_engine"] = target_engine

    temp_dir = tempfile.TemporaryDirectory(prefix=f"aob-update-{target.target_label}-")
    managed_files: set[str] = set()
    try:
        compile_workspace_root = Path(temp_dir.name) / "workspace"
        compile_workspace_root.mkdir(parents=True, exist_ok=True)
        编译_aol到引擎办公区(
            aol=aol,
            target_workspace_dir=compile_workspace_root,
            target_engine=target_engine,
        )

        if target.layout == "prompt_root":
            发布编译结果到提示词目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
                journal=journal,
            )
            managed_files = 收集提示词目标托管文件(compile_workspace_root)
        else:
            发布编译结果到结构化目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
                journal=journal,
            )
            managed_files = 收集结构化目标托管文件(compile_workspace_root, target=target)
    finally:
        temp_dir.cleanup()

    stale_files = {item for item in previous_managed_files if item and item not in managed_files}
    stats["stale_managed_file_count"] = len(stale_files)
    删除目标过期托管文件(target=target, stale_files=stale_files, dry_run=dry_run, stats=stats, journal=journal)
    if cleanup_unknown and target.layout != "prompt_root":
        清理目标未跟踪文件(target=target, managed_files=managed_files, dry_run=dry_run, stats=stats, journal=journal)
    stats["managed_file_count"] = len(managed_files)
    return stats, managed_files

def 复制聚合文件(*, source_file: Path, target_file: Path, dry_run: bool, stats: dict[str, Any], journal: Any = None) -> None:
    """按“较新优先”策略复制单个聚合文件。

    Args:
        source_file: 来源文件。
        target_file: 目标文件。
        dry_run: 是否预演。
        stats: 发布统计累加器。
        journal: 可选撤销账本；存在时在覆盖/新增前后登记撤销操作。
    """

    is_overwrite = False
    if target_file.exists():
        if target_file.is_dir():
            stats["errors"].append(f"目标路径为目录，无法覆盖文件：{target_file}")
            return
        if 文件内容一致(source_file, target_file):
            stats["skipped_same"] += 1
            return
        if source_file.stat().st_mtime <= target_file.stat().st_mtime:
            stats["skipped_target_newer"] += 1
            return
        stats["updated"] += 1
        is_overwrite = True
    else:
        stats["added"] += 1

    stats["touched_paths"].append(str(target_file))
    if dry_run:
        return

    if journal is not None:
        if is_overwrite:
            journal.记录将覆盖(target_file)
        else:
            journal.记录将创建(target_file)

    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target_file)

    if journal is not None:
        journal.标记同步后哈希(target_file)

def 复制聚合条目(*, source_path: Path, target_path: Path, dry_run: bool, stats: dict[str, Any], journal: Any = None) -> None:
    """复制单个聚合条目，支持文件或目录。"""

    if source_path.is_dir():
        for child in sorted(source_path.rglob("*")):
            if not child.is_file():
                continue
            relative = child.relative_to(source_path)
            复制聚合文件(
                source_file=child,
                target_file=target_path / relative,
                dry_run=dry_run,
                stats=stats,
                journal=journal,
            )
        return

    复制聚合文件(source_file=source_path, target_file=target_path, dry_run=dry_run, stats=stats, journal=journal)

def 是否提示词发布文件(file_path: Path, *, content_type: str) -> bool:
    """判断文件是否适合发布到 prompts 根目录。"""

    if not file_path.is_file():
        return False
    lowered = file_path.name.lower()
    if content_type == "prompts":
        return lowered.endswith(".prompt.md")
    if content_type == "instructions":
        return lowered.endswith(".instructions.md")
    return False

def 发布编译结果到结构化目录(*, compile_workspace_root: Path, target: 发布目标, dry_run: bool, stats: dict[str, Any], journal: Any = None) -> None:
    """把 AOC 编译结果发布到结构化目标目录。"""

    for source_file in sorted(path for path in compile_workspace_root.rglob("*") if path.is_file()):
        relative = source_file.relative_to(compile_workspace_root)
        复制聚合文件(
            source_file=source_file,
            target_file=target.target_path / relative,
            dry_run=dry_run,
            stats=stats,
            journal=journal,
        )

    for root_name in ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "opencode.json"]:
        source_file = compile_workspace_root.parent / root_name
        if not source_file.exists() or not source_file.is_file():
            continue
        if target.scope == "project":
            target_file = target.target_path.parent / root_name
        else:
            target_file = target.target_path / root_name
        复制聚合文件(
            source_file=source_file,
            target_file=target_file,
            dry_run=dry_run,
            stats=stats,
            journal=journal,
        )

def 发布编译结果到提示词目录(*, compile_workspace_root: Path, target: 发布目标, dry_run: bool, stats: dict[str, Any], journal: Any = None) -> None:
    """把 AOC 编译结果中的 prompts/instructions 投影到 prompts 根目录。"""

    for content_type in ["prompts", "instructions"]:
        source_root = compile_workspace_root / content_type
        if not source_root.exists() or not source_root.is_dir():
            continue
        for source_file in sorted(path for path in source_root.rglob("*") if path.is_file()):
            if not 是否提示词发布文件(source_file, content_type=content_type):
                continue
            relative = source_file.relative_to(source_root)
            复制聚合文件(
                source_file=source_file,
                target_file=target.target_path / relative,
                dry_run=dry_run,
                stats=stats,
                journal=journal,
            )

def 发布到单个目标(*, aol: Any, target: 发布目标, dry_run: bool, warnings: list[str]) -> dict[str, Any]:
    """把 AOL 编译后发布到单个目标目录。"""

    stats = 构建发布统计(target)
    contract_level, contract_note = 解析供应商载体契约级别(
        layout=target.layout,
        engine_vendor=target.engine_vendor,
        ide_vendor=target.ide_vendor,
        scope=target.scope,
    )
    stats["contract_level"] = contract_level
    stats["contract_note"] = contract_note
    if contract_level == "heuristic":
        warnings.append(
            f"目标 {target.target_label} 使用经验性载体契约（layout={target.layout}, engine={target.engine_vendor}, ide={target.ide_vendor}）：{contract_note}"
        )
    target_engine = 归一化引擎供应商(engine_vendor=target.engine_vendor, ide_vendor=target.ide_vendor)
    if str(target.engine_vendor or "").strip().lower() not in 默认AOC支持引擎:
        warnings.append(
            f"目标 {target.target_label} 的 engine_vendor={target.engine_vendor} 不在 AOC 支持列表，已映射为 {target_engine}"
        )
    stats["aoc_target_engine"] = target_engine

    temp_dir = tempfile.TemporaryDirectory(prefix=f"aob-publish-{target.target_label}-")
    try:
        compile_workspace_root = Path(temp_dir.name) / "workspace"
        compile_workspace_root.mkdir(parents=True, exist_ok=True)
        编译_aol到引擎办公区(
            aol=aol,
            target_workspace_dir=compile_workspace_root,
            target_engine=target_engine,
        )

        if target.layout == "prompt_root":
            发布编译结果到提示词目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
            )
        else:
            发布编译结果到结构化目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
            )
    finally:
        temp_dir.cleanup()

    return stats

def 发布用户级内容(
    paths: 路径配置,
    *,
    target_paths: list[str],
    home_dir: str,
    engine_vendors: list[str],
    ide_vendors: list[str],
    include_missing: bool,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    resolved_targets_override: list[发布目标] | None = None,
) -> dict[str, Any]:
    """把集中在 libs 的内容发布到当前设备的用户级 AI 办公区。"""

    if not AOL运行时可用():
        raise ValueError("aoc runtime 不可用，无法执行 publish-user-content")

    if resolved_targets_override is not None:
        targets = list(resolved_targets_override)
    else:
        targets = 解析发布目标(
            target_paths,
            paths=paths,
            home_dir=home_dir,
            engine_vendors=engine_vendors,
            ide_vendors=ide_vendors,
            scopes=scopes,
            project_dirs=project_dirs,
            include_missing=include_missing,
        )

    if simulate_only:
        sandbox_paths, sandbox_targets, sandbox_summary = 准备用户级内容同步沙盒(
            paths,
            targets=targets,
            home_dir=home_dir,
            sandbox_dir=sandbox_dir,
        )
        sandbox_result = 发布用户级内容(
            sandbox_paths,
            target_paths=[],
            home_dir="",
            engine_vendors=[],
            ide_vendors=[],
            include_missing=True,
            dry_run=dry_run,
            simulate_only=False,
            sandbox_dir="",
            resolved_targets_override=sandbox_targets,
        )
        sandbox_result["sandbox"] = sandbox_summary
        sandbox_result["simulate_only"] = True
        sandbox_result["source_repo_root"] = str(paths.repo_root)
        return sandbox_result

    aol_intermediate = 构建libs_aol中转摘要(paths)
    if aol_intermediate.get("enabled") and aol_intermediate.get("status") != "ok":
        raise ValueError(f"AOL 中转构建失败：{aol_intermediate}")

    aol = 读取canonical_AOL(paths)

    summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "target_count": len(targets),
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "targets": [],
        "errors": [],
        "touched_paths": [],
        "aol_intermediate": aol_intermediate,
        "publish_warnings": [],
        "sandbox": {"enabled": False},
        "simulate_only": False,
    }

    for target in targets:
        part = 发布到单个目标(
            aol=aol,
            target=target,
            dry_run=dry_run,
            warnings=summary["publish_warnings"],
        )
        合并发布统计(summary, part)

    return summary

def 执行发布用户级内容(argv: list[str], paths: 路径配置) -> int:
    """执行用户级内容发布子命令。"""

    parser = argparse.ArgumentParser(description="按范围把 libs 中的 AI 内容发布到当前设备、项目或显式目标")
    parser.add_argument("--target-path", action="append", default=[], help="可选：显式指定发布目标路径，可重复传入")
    parser.add_argument("--scope", action="append", default=[], help="可选：自动发现范围，可重复传入 global/system/user/project")
    parser.add_argument("--project-dir", action="append", default=[], help="可选：项目级自动发现根目录，可重复传入")
    parser.add_argument("--home-dir", default="", help="可选：覆盖自动发现使用的用户主目录")
    parser.add_argument("--engine", action="append", default=[], help="可选：按 engine_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--ide", action="append", default=[], help="可选：按 ide_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--include-missing", action="store_true", help="自动发现时包含当前尚不存在的候选目标目录")
    parser.add_argument("--dry-run", action="store_true", help="仅输出变更预览，不写入磁盘")
    parser.add_argument("--simulate-only", action="store_true", help="仅在沙盒副本中执行发布，不修改真实目录")
    parser.add_argument("--sandbox-dir", default="", help="可选：沙盒根目录；不传则默认使用 Downloads 下的时间戳目录")
    args = parser.parse_args(argv)

    stats = 发布用户级内容(
        paths,
        target_paths=[str(item).strip() for item in list(args.target_path or []) if str(item).strip()],
        home_dir=str(args.home_dir or "").strip(),
        engine_vendors=[str(item).strip() for item in list(args.engine or []) if str(item).strip()],
        ide_vendors=[str(item).strip() for item in list(args.ide or []) if str(item).strip()],
        include_missing=bool(args.include_missing),
        scopes=[str(item).strip() for item in list(args.scope or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(args.project_dir or []) if str(item).strip()],
        dry_run=bool(args.dry_run),
        simulate_only=bool(args.simulate_only),
        sandbox_dir=str(args.sandbox_dir or "").strip(),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0
