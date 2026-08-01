# -*- coding: utf-8 -*-
"""AOB 流程编排层。

提供原子功能的流程式组合入口。每个流程按"步骤函数"串联，每步独立可重试，
返回包含每步 stats、耗时、状态的结构化结果。

流程入口：
- flow_backup_then_aggregate: 备份 → 聚合
- flow_backup_then_publish: 备份 → 发布
- flow_backup_then_update: 备份 → 同步
- flow_aggregate_then_publish: 聚合 → 发布
- flow_full_sync: 备份 → 聚合 → 发布 → 中文索引生成

用法：
    from .aob_flow_pipeline import flow_full_sync
    result = flow_full_sync(paths, target_paths=[...])
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from .aob_common import 路径配置, 默认路径


# ---------------------------------------------------------------------------
# 步骤结果工具
# ---------------------------------------------------------------------------

def _步骤结果(步骤名: str, status: str, result: dict[str, Any],
              elapsed: float, 跳过原因: str = "") -> dict[str, Any]:
    """构建单步骤的结果摘要。"""
    return {
        "step": 步骤名,
        "status": status,  # "ok" | "skipped" | "error" | "dry_run"
        "skipped_reason": 跳过原因,
        "elapsed_seconds": round(elapsed, 3),
        "result": result,
    }


def _流程结果(步骤列表: list[dict[str, Any]], *, dry_run: bool,
              simulate_only: bool, repo_root: str) -> dict[str, Any]:
    """构建流程整体结果。"""
    has_error = any(s["status"] == "error" for s in 步骤列表)
    return {
        "status": "error" if has_error else "ok",
        "dry_run": dry_run,
        "simulate_only": simulate_only,
        "repo_root": repo_root,
        "steps": 步骤列表,
        "touched_paths": _收集触碰路径(步骤列表),
    }


def _收集触碰路径(步骤列表: list[dict[str, Any]]) -> list[str]:
    """收集所有步骤中的触碰路径。"""
    paths: list[str] = []
    for s in 步骤列表:
        r = s.get("result", {})
        if isinstance(r, dict):
            for tp in r.get("touched_paths") or []:
                if tp not in paths:
                    paths.append(tp)
    return paths


def _打印流程摘要(步骤列表: list[dict[str, Any]]) -> None:
    """打印流程执行摘要到 stdout。"""
    print("\n流程执行摘要:")
    for s in 步骤列表:
        status_icon = {"ok": "✅", "skipped": "⏭️", "error": "❌", "dry_run": "📋"}.get(s["status"], "❓")
        print(f"  {status_icon} {s['step']}: {s['status']} ({s['elapsed_seconds']}s)")
        if s.get("skipped_reason"):
            print(f"       原因: {s['skipped_reason']}")


# ---------------------------------------------------------------------------
# 流程函数
# ---------------------------------------------------------------------------

def flow_backup_then_aggregate(
    paths: 路径配置 | None = None,
    *,
    target_paths: list[str] | None = None,
    home_dir: str = "",
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    include_missing: bool = False,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    backup_dir: str = "",
    source_paths: list[str] | None = None,
    dry_run: bool = False,
    sync_items_after: bool = True,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    verbose: bool = True,
) -> dict[str, Any]:
    """步骤：备份 → 聚合。

    适用于修改了用户级内容后，希望先备份再聚合到 canonical AOL 的场景。
    """
    if paths is None:
        paths = 默认路径()
    steps: list[dict[str, Any]] = []

    # Step 1: 备份（沙盒模拟时跳过——备份模块不支持 simulate_only）
    if simulate_only:
        steps.append(_步骤结果("backup", "skipped", {}, 0.0,
                               跳过原因="沙盒模拟模式下跳过备份（数据已在 update 沙盒中）"))
    else:
        t0 = time.monotonic()
        try:
            from .aob_backup import 备份用户级内容 as _备份
            backup_result = _备份(
                paths, target_paths=target_paths or [], home_dir=home_dir,
                engine_vendors=engine_vendors or [], ide_vendors=ide_vendors or [],
                include_missing=include_missing, backup_dir=backup_dir,
                scopes=scopes, project_dirs=project_dirs, dry_run=dry_run,
            )
            steps.append(_步骤结果("backup", "ok" if backup_result.get("status") != "error" else "error",
                                   backup_result, time.monotonic() - t0))
        except Exception as e:
            steps.append(_步骤结果("backup", "error", {"error": str(e)}, time.monotonic() - t0))
            return _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))

    # Step 2: 聚合
    t0 = time.monotonic()
    try:
        from .aob_aggregate import 聚合用户级内容 as _聚合
        agg_result = _聚合(
            paths, source_paths=source_paths or [], home_dir=home_dir,
            scopes=scopes, project_dirs=project_dirs, dry_run=dry_run,
            sync_items_after=sync_items_after, simulate_only=simulate_only,
            sandbox_dir=sandbox_dir,
        )
        steps.append(_步骤结果("aggregate", "ok", agg_result, time.monotonic() - t0))
    except Exception as e:
        steps.append(_步骤结果("aggregate", "error", {"error": str(e)}, time.monotonic() - t0))

    result = _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))
    if verbose:
        _打印流程摘要(steps)
    return result


def flow_backup_then_publish(
    paths: 路径配置 | None = None,
    *,
    target_paths: list[str] | None = None,
    home_dir: str = "",
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    include_missing: bool = False,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    backup_dir: str = "",
    dry_run: bool = False,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    verbose: bool = True,
) -> dict[str, Any]:
    """步骤：备份 → 发布。

    适用于在 canonical AOL 已更新后，希望先备份再发布到各引擎的场景。
    """
    if paths is None:
        paths = 默认路径()
    steps: list[dict[str, Any]] = []

    # Step 1: 备份（沙盒模拟时跳过——备份模块不支持 simulate_only）
    if simulate_only:
        steps.append(_步骤结果("backup", "skipped", {}, 0.0,
                               跳过原因="沙盒模拟模式下跳过备份（数据已在 update 沙盒中）"))
    else:
        t0 = time.monotonic()
        try:
            from .aob_backup import 备份用户级内容 as _备份
            backup_result = _备份(
                paths, target_paths=target_paths or [], home_dir=home_dir,
                engine_vendors=engine_vendors or [], ide_vendors=ide_vendors or [],
                include_missing=include_missing, backup_dir=backup_dir,
                scopes=scopes, project_dirs=project_dirs, dry_run=dry_run,
            )
            steps.append(_步骤结果("backup", "ok" if backup_result.get("status") != "error" else "error",
                                   backup_result, time.monotonic() - t0))
        except Exception as e:
            steps.append(_步骤结果("backup", "error", {"error": str(e)}, time.monotonic() - t0))
            return _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))

    # Step 2: 发布
    t0 = time.monotonic()
    try:
        from .aob_publish import 发布用户级内容 as _发布
        pub_result = _发布(
            paths, target_paths=target_paths or [], home_dir=home_dir,
            engine_vendors=engine_vendors or [], ide_vendors=ide_vendors or [],
            include_missing=include_missing, scopes=scopes,
            project_dirs=project_dirs, dry_run=dry_run,
            simulate_only=simulate_only, sandbox_dir=sandbox_dir,
        )
        steps.append(_步骤结果("publish", "ok", pub_result, time.monotonic() - t0))
    except Exception as e:
        steps.append(_步骤结果("publish", "error", {"error": str(e)}, time.monotonic() - t0))

    result = _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))
    if verbose:
        _打印流程摘要(steps)
    return result


def flow_backup_then_update(
    paths: 路径配置 | None = None,
    *,
    target_paths: list[str] | None = None,
    home_dir: str = "",
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    include_missing: bool = False,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    backup_dir: str = "",
    dry_run: bool = False,
    sync_items_after: bool = True,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    enable_undo_journal: bool = True,
    undo_journal_dir: str = "",
    cleanup_unknown: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """步骤：备份 → 同步。

    替代原有 update-user-content 内置的"先备份"逻辑。
    备份和同步各自独立，任何一步失败都不影响后续。
    若需跳过备份，请直接调用 update-user-content --skip-backup。
    """
    if paths is None:
        paths = 默认路径()
    steps: list[dict[str, Any]] = []

    # Step 1: 备份（沙盒模拟时跳过——备份模块不支持 simulate_only）
    if simulate_only:
        steps.append(_步骤结果("backup", "skipped", {}, 0.0,
                               跳过原因="沙盒模拟模式下跳过备份（数据已在 update 沙盒中）"))
    else:
        t0 = time.monotonic()
        try:
            from .aob_backup import 备份用户级内容 as _备份
            backup_result = _备份(
                paths, target_paths=target_paths or [], home_dir=home_dir,
                engine_vendors=engine_vendors or [], ide_vendors=ide_vendors or [],
                include_missing=include_missing, backup_dir=backup_dir,
                scopes=scopes, project_dirs=project_dirs, dry_run=dry_run,
            )
            steps.append(_步骤结果("backup", "ok" if backup_result.get("status") != "error" else "error",
                                   backup_result, time.monotonic() - t0))
        except Exception as e:
            steps.append(_步骤结果("backup", "error", {"error": str(e)}, time.monotonic() - t0))
            return _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))

    # Step 2: 同步（调用 update 但 skip_backup=True，因为已经备份过了）
    t0 = time.monotonic()
    try:
        from .aob_update import 更新用户级内容 as _更新
        update_result = _更新(
            paths, target_paths=target_paths or [], home_dir=home_dir,
            engine_vendors=engine_vendors or [], ide_vendors=ide_vendors or [],
            include_missing=include_missing, scopes=scopes,
            project_dirs=project_dirs, dry_run=dry_run,
            sync_items_after=sync_items_after,
            backup_before_sync=False,  # 已经备份过了
            backup_dir=backup_dir,
            simulate_only=simulate_only, sandbox_dir=sandbox_dir,
            enable_undo_journal=enable_undo_journal,
            undo_journal_dir=undo_journal_dir,
            cleanup_unknown=cleanup_unknown,
        )
        steps.append(_步骤结果("update", "ok", update_result, time.monotonic() - t0))
    except Exception as e:
        steps.append(_步骤结果("update", "error", {"error": str(e)}, time.monotonic() - t0))

    result = _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))
    if verbose:
        _打印流程摘要(steps)
    return result


def flow_aggregate_then_publish(
    paths: 路径配置 | None = None,
    *,
    target_paths: list[str] | None = None,
    source_paths: list[str] | None = None,
    home_dir: str = "",
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    include_missing: bool = False,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool = False,
    sync_items_after: bool = True,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    verbose: bool = True,
) -> dict[str, Any]:
    """步骤：聚合 → 发布。

    适用于从用户级内容直接同步到各引擎的"一键刷新"场景。
    """
    if paths is None:
        paths = 默认路径()
    steps: list[dict[str, Any]] = []

    # Step 1: 聚合
    t0 = time.monotonic()
    try:
        from .aob_aggregate import 聚合用户级内容 as _聚合
        agg_result = _聚合(
            paths, source_paths=source_paths or [], home_dir=home_dir,
            scopes=scopes, project_dirs=project_dirs, dry_run=dry_run,
            sync_items_after=sync_items_after, simulate_only=simulate_only,
            sandbox_dir=sandbox_dir,
        )
        steps.append(_步骤结果("aggregate", "ok", agg_result, time.monotonic() - t0))
    except Exception as e:
        steps.append(_步骤结果("aggregate", "error", {"error": str(e)}, time.monotonic() - t0))
        return _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))

    # Step 2: 发布
    t0 = time.monotonic()
    try:
        from .aob_publish import 发布用户级内容 as _发布
        pub_result = _发布(
            paths, target_paths=target_paths or [], home_dir=home_dir,
            engine_vendors=engine_vendors or [], ide_vendors=ide_vendors or [],
            include_missing=include_missing, scopes=scopes,
            project_dirs=project_dirs, dry_run=dry_run,
            simulate_only=simulate_only, sandbox_dir=sandbox_dir,
        )
        steps.append(_步骤结果("publish", "ok", pub_result, time.monotonic() - t0))
    except Exception as e:
        steps.append(_步骤结果("publish", "error", {"error": str(e)}, time.monotonic() - t0))

    result = _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))
    if verbose:
        _打印流程摘要(steps)
    return result


def flow_full_sync(
    paths: 路径配置 | None = None,
    *,
    target_paths: list[str] | None = None,
    source_paths: list[str] | None = None,
    home_dir: str = "",
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    include_missing: bool = False,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    backup_dir: str = "",
    dry_run: bool = False,
    sync_items_after: bool = True,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    enable_undo_journal: bool = True,
    undo_journal_dir: str = "",
    generate_zh_index: bool = True,
    verbose: bool = True,
) -> dict[str, Any]:
    """完整同步流程：备份 → 聚合 → 发布 → 中文索引生成。

    这是面向日常维护的"一键全流程"入口。
    每步结果独立记录，任何一步失败可通过 steps[i].status 定位。
    """
    if paths is None:
        paths = 默认路径()
    steps: list[dict[str, Any]] = []

    # Step 1: 备份（沙盒模拟时跳过——备份模块不支持 simulate_only）
    if simulate_only:
        steps.append(_步骤结果("backup", "skipped", {}, 0.0,
                               跳过原因="沙盒模拟模式下跳过备份（数据已在 update 沙盒中）"))
    else:
        t0 = time.monotonic()
        try:
            from .aob_backup import 备份用户级内容 as _备份
            backup_result = _备份(
                paths, target_paths=target_paths or [], home_dir=home_dir,
                engine_vendors=engine_vendors or [], ide_vendors=ide_vendors or [],
                include_missing=include_missing, backup_dir=backup_dir,
                scopes=scopes, project_dirs=project_dirs, dry_run=dry_run,
            )
            steps.append(_步骤结果("backup", "ok" if backup_result.get("status") != "error" else "error",
                                   backup_result, time.monotonic() - t0))
        except Exception as e:
            steps.append(_步骤结果("backup", "error", {"error": str(e)}, time.monotonic() - t0))
            return _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))

    # Step 2: 聚合
    t0 = time.monotonic()
    try:
        from .aob_aggregate import 聚合用户级内容 as _聚合
        agg_result = _聚合(
            paths, source_paths=source_paths or [], home_dir=home_dir,
            scopes=scopes, project_dirs=project_dirs, dry_run=dry_run,
            sync_items_after=sync_items_after, simulate_only=simulate_only,
            sandbox_dir=sandbox_dir,
        )
        steps.append(_步骤结果("aggregate", "ok", agg_result, time.monotonic() - t0))
    except Exception as e:
        steps.append(_步骤结果("aggregate", "error", {"error": str(e)}, time.monotonic() - t0))
        return _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))

    # Step 3: 发布
    t0 = time.monotonic()
    try:
        from .aob_publish import 发布用户级内容 as _发布
        pub_result = _发布(
            paths, target_paths=target_paths or [], home_dir=home_dir,
            engine_vendors=engine_vendors or [], ide_vendors=ide_vendors or [],
            include_missing=include_missing, scopes=scopes,
            project_dirs=project_dirs, dry_run=dry_run,
            simulate_only=simulate_only, sandbox_dir=sandbox_dir,
        )
        steps.append(_步骤结果("publish", "ok", pub_result, time.monotonic() - t0))
    except Exception as e:
        steps.append(_步骤结果("publish", "error", {"error": str(e)}, time.monotonic() - t0))
        return _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))

    # Step 4: 中文索引生成（可选）
    if generate_zh_index:
        t0 = time.monotonic()
        try:
            from .aob_zh_index import 生成中文索引 as _索引
            索引结果 = _索引(dry_run=dry_run)
            steps.append(_步骤结果("generate-zh-index", "ok", 索引结果, time.monotonic() - t0))
        except Exception as e:
            steps.append(_步骤结果("generate-zh-index",
                                   "skipped" if dry_run else "error",
                                   {"error": str(e)}, time.monotonic() - t0,
                                   跳过原因=f"索引生成失败: {e}" if dry_run else ""))

    result = _流程结果(steps, dry_run=dry_run, simulate_only=simulate_only, repo_root=str(paths.repo_root))
    if verbose:
        _打印流程摘要(steps)
    return result


# ---------------------------------------------------------------------------
# CLI 入口（供 library_tool 路由调用）
# ---------------------------------------------------------------------------

def _execute_flow_backup_aggregate(argv: list[str], paths: 路径配置) -> int:
    """CLI: flow-backup-aggregate"""
    import argparse
    p = argparse.ArgumentParser(description="备份 → 聚合")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--simulate-only", action="store_true")
    p.add_argument("--sandbox-dir", default="")
    p.add_argument("--home-dir", default="")
    p.add_argument("--backup-dir", default="")
    p.add_argument("--source-path", action="append", default=[])
    p.add_argument("--target-path", action="append", default=[])
    p.add_argument("--scope", action="append", default=[])
    p.add_argument("--project-dir", action="append", default=[])
    p.add_argument("--engine", action="append", default=[])
    p.add_argument("--ide", action="append", default=[])
    p.add_argument("--include-missing", action="store_true")
    p.add_argument("--skip-items-sync", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    result = flow_backup_then_aggregate(
        paths, dry_run=args.dry_run, simulate_only=args.simulate_only,
        sandbox_dir=args.sandbox_dir, home_dir=args.home_dir, backup_dir=args.backup_dir,
        source_paths=args.source_path, target_paths=args.target_path,
        scopes=args.scope, project_dirs=args.project_dir,
        engine_vendors=args.engine, ide_vendors=args.ide,
        include_missing=args.include_missing,
        sync_items_after=not args.skip_items_sync,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "error" else 0


def _execute_flow_backup_publish(argv: list[str], paths: 路径配置) -> int:
    """CLI: flow-backup-publish"""
    import argparse
    p = argparse.ArgumentParser(description="备份 → 发布")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--simulate-only", action="store_true")
    p.add_argument("--sandbox-dir", default="")
    p.add_argument("--home-dir", default="")
    p.add_argument("--backup-dir", default="")
    p.add_argument("--target-path", action="append", default=[])
    p.add_argument("--engine", action="append", default=[])
    p.add_argument("--ide", action="append", default=[])
    p.add_argument("--scope", action="append", default=[])
    p.add_argument("--project-dir", action="append", default=[])
    p.add_argument("--include-missing", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    result = flow_backup_then_publish(
        paths, dry_run=args.dry_run, simulate_only=args.simulate_only,
        sandbox_dir=args.sandbox_dir, home_dir=args.home_dir, backup_dir=args.backup_dir,
        target_paths=args.target_path, engine_vendors=args.engine,
        ide_vendors=args.ide, scopes=args.scope, project_dirs=args.project_dir,
        include_missing=args.include_missing,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "error" else 0


def _execute_flow_backup_update(argv: list[str], paths: 路径配置) -> int:
    """CLI: flow-backup-update"""
    import argparse
    p = argparse.ArgumentParser(description="备份 → 同步")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--simulate-only", action="store_true")
    p.add_argument("--sandbox-dir", default="")
    p.add_argument("--home-dir", default="")
    p.add_argument("--backup-dir", default="")
    p.add_argument("--target-path", action="append", default=[])
    p.add_argument("--engine", action="append", default=[])
    p.add_argument("--ide", action="append", default=[])
    p.add_argument("--scope", action="append", default=[])
    p.add_argument("--project-dir", action="append", default=[])
    p.add_argument("--include-missing", action="store_true")
    p.add_argument("--skip-items-sync", action="store_true")
    p.add_argument("--skip-undo-journal", action="store_true")
    p.add_argument("--undo-journal-dir", default="")
    p.add_argument("--cleanup-unknown", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    result = flow_backup_then_update(
        paths, dry_run=args.dry_run, simulate_only=args.simulate_only,
        sandbox_dir=args.sandbox_dir, home_dir=args.home_dir, backup_dir=args.backup_dir,
        target_paths=args.target_path, engine_vendors=args.engine,
        ide_vendors=args.ide, scopes=args.scope, project_dirs=args.project_dir,
        include_missing=args.include_missing,
        sync_items_after=not args.skip_items_sync,
        enable_undo_journal=not args.skip_undo_journal,
        undo_journal_dir=args.undo_journal_dir,
        cleanup_unknown=args.cleanup_unknown,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "error" else 0


def _execute_flow_aggregate_publish(argv: list[str], paths: 路径配置) -> int:
    """CLI: flow-aggregate-publish"""
    import argparse
    p = argparse.ArgumentParser(description="聚合 → 发布")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--simulate-only", action="store_true")
    p.add_argument("--sandbox-dir", default="")
    p.add_argument("--home-dir", default="")
    p.add_argument("--source-path", action="append", default=[])
    p.add_argument("--target-path", action="append", default=[])
    p.add_argument("--engine", action="append", default=[])
    p.add_argument("--ide", action="append", default=[])
    p.add_argument("--scope", action="append", default=[])
    p.add_argument("--project-dir", action="append", default=[])
    p.add_argument("--include-missing", action="store_true")
    p.add_argument("--skip-items-sync", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    result = flow_aggregate_then_publish(
        paths, dry_run=args.dry_run, simulate_only=args.simulate_only,
        sandbox_dir=args.sandbox_dir, home_dir=args.home_dir,
        source_paths=args.source_path, target_paths=args.target_path,
        engine_vendors=args.engine, ide_vendors=args.ide,
        scopes=args.scope, project_dirs=args.project_dir,
        include_missing=args.include_missing,
        sync_items_after=not args.skip_items_sync,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "error" else 0


def _execute_flow_full_sync(argv: list[str], paths: 路径配置) -> int:
    """CLI: flow-full-sync"""
    import argparse
    p = argparse.ArgumentParser(description="备份 → 聚合 → 发布 → 中文索引（一键全流程）")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--simulate-only", action="store_true")
    p.add_argument("--sandbox-dir", default="")
    p.add_argument("--home-dir", default="")
    p.add_argument("--backup-dir", default="")
    p.add_argument("--source-path", action="append", default=[])
    p.add_argument("--target-path", action="append", default=[])
    p.add_argument("--engine", action="append", default=[])
    p.add_argument("--ide", action="append", default=[])
    p.add_argument("--scope", action="append", default=[])
    p.add_argument("--project-dir", action="append", default=[])
    p.add_argument("--include-missing", action="store_true")
    p.add_argument("--skip-items-sync", action="store_true")
    p.add_argument("--skip-undo-journal", action="store_true")
    p.add_argument("--undo-journal-dir", default="")
    p.add_argument("--cleanup-unknown", action="store_true")
    p.add_argument("--skip-zh-index", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    result = flow_full_sync(
        paths, dry_run=args.dry_run, simulate_only=args.simulate_only,
        sandbox_dir=args.sandbox_dir, home_dir=args.home_dir, backup_dir=args.backup_dir,
        source_paths=args.source_path, target_paths=args.target_path,
        engine_vendors=args.engine, ide_vendors=args.ide,
        scopes=args.scope, project_dirs=args.project_dir,
        include_missing=args.include_missing,
        sync_items_after=not args.skip_items_sync,
        enable_undo_journal=not args.skip_undo_journal,
        undo_journal_dir=args.undo_journal_dir,
        generate_zh_index=not args.skip_zh_index,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "error" else 0
