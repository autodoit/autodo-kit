# -*- coding: utf-8 -*-
"""AOB 同步原子工具（update-user-content）。

基于 logical key + SQLite 注册表决策，执行多引擎办公区同步。
注意：本工具不包含前置备份，备份是独立的原子工具。
如需"先备份再同步"，请使用 aob_flow_pipeline.flow_backup_then_update。
"""

from __future__ import annotations

from .aob_common import *

import json
import tempfile
from pathlib import Path
from typing import Any

# update 在 backup_before_sync=True 时需调用备份
try:
    from .aob_backup import 备份用户级内容
except Exception:
    备份用户级内容 = None

# update 在发布阶段需调用发布模块
try:
    from .aob_publish import 发布到单个目标并同步删除
except Exception:
    发布到单个目标并同步删除 = None


def 收集用户级内容同步侧(
    paths: 路径配置,
    *,
    targets: list[发布目标],
) -> tuple[
    dict[str, dict[str, dict[str, Any]]],
    dict[str, float],
    list[dict[str, Any]],
    list[str],
    list[str],
    str,
]:
    """收集用于同步决策的 libs/target side AOL 与元数据。"""

    side_entries: dict[str, dict[str, dict[str, Any]]] = {"libs": {}}
    side_observe_times: dict[str, float] = {"libs": 0.0}
    source_summaries: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    title_fallback = f"{paths.repo_root.name} canonical AOL"

    canonical_path = 解析AOL规范文件路径(paths)
    side_observe_times["libs"] = 获取路径最近修改时间(canonical_path)
    libs_summary: dict[str, Any] = {
        "side_id": "libs",
        "source": str(canonical_path),
        "source_label": "libs",
        "layout": "canonical_aol",
        "engine_vendor": "aol",
        "ide_vendor": "aol",
        "scope": "global",
        "contract_level": "canonical",
        "contract_note": "libs canonical AOL 是内部语义真源，不依赖外部供应商目录契约。",
        "observe_at_epoch": side_observe_times["libs"],
        "logical_entry_count": 0,
        "status": "missing",
    }
    if canonical_path.exists() and canonical_path.is_file():
        try:
            libs_aol = 读取canonical_AOL(paths)
            libs_payload = AOL对象转payload(libs_aol)
            side_entries["libs"] = AOL扁平化逻辑条目(libs_payload)
            title_fallback = str(libs_payload.get("title") or title_fallback)
            libs_summary["logical_entry_count"] = len(side_entries["libs"])
            libs_summary["status"] = "loaded"
        except Exception as exc:  # noqa: BLE001
            libs_summary["status"] = "error"
            libs_summary["error"] = str(exc)
            errors.append(f"libs canonical 读取失败：{exc}")
    source_summaries.append(libs_summary)

    for target in targets:
        side_id = f"target:{target.target_label}"
        source = 发布目标转聚合来源(target)
        contract_level, contract_note = 解析供应商载体契约级别(
            layout=source.layout,
            engine_vendor=source.engine_vendor,
            ide_vendor=source.ide_vendor,
            scope=source.scope,
        )
        observe_at = 获取路径最近修改时间(source.source_path)
        side_observe_times[side_id] = observe_at
        side_entries.setdefault(side_id, {})
        source_summary: dict[str, Any] = {
            "side_id": side_id,
            "source": str(source.source_path),
            "source_label": source.source_label,
            "target_label": target.target_label,
            "layout": source.layout,
            "engine_vendor": source.engine_vendor,
            "ide_vendor": source.ide_vendor,
            "scope": source.scope,
            "contract_level": contract_level,
            "contract_note": contract_note,
            "observe_at_epoch": observe_at,
            "logical_entry_count": 0,
            "status": "missing",
        }
        if not source.source_path.exists():
            source_summaries.append(source_summary)
            continue

        if not 是否包含可聚合内容(source.source_path, layout=source.layout, scope=source.scope):
            source_summary["status"] = "empty_or_unsupported"
            source_summaries.append(source_summary)
            continue

        aol, part, part_warnings = 来源构建AOL(paths, source=source)
        warnings.extend(part_warnings)
        if part.get("aol_counts"):
            source_summary["aol_counts"] = dict(part.get("aol_counts") or {})

        part_errors = [str(item) for item in list(part.get("errors") or []) if str(item).strip()]
        if part_errors:
            source_summary["status"] = "error"
            source_summary["error"] = "; ".join(part_errors)
            errors.extend([f"{target.target_label} 反编译失败：{item}" for item in part_errors])
            source_summaries.append(source_summary)
            continue

        if aol is None:
            source_summary["status"] = "empty"
            source_summaries.append(source_summary)
            continue

        payload = AOL对象转payload(aol)
        entries = AOL扁平化逻辑条目(payload)
        side_entries[side_id] = entries
        source_summary["logical_entry_count"] = len(entries)
        source_summary["status"] = "loaded"
        source_summaries.append(source_summary)

    return side_entries, side_observe_times, source_summaries, warnings, errors, title_fallback

def 准备用户级内容同步沙盒(
    paths: 路径配置,
    *,
    targets: list[发布目标],
    home_dir: str = "",
    sandbox_dir: str,
) -> tuple[路径配置, list[发布目标], dict[str, Any]]:
    """把当前 libs canonical 与目标目录复制到独立沙盒。"""

    sandbox_root = 解析唯一沙盒根目录(home_dir=home_dir, sandbox_dir=sandbox_dir)
    sandbox_paths = 构建沙盒路径配置(sandbox_root=sandbox_root)
    复制用户级内容沙盒仓库基线(paths, sandbox_paths=sandbox_paths)

    sandbox_targets: list[发布目标] = []
    sandbox_target_summaries: list[dict[str, Any]] = []
    path_mappings: list[dict[str, str]] = []
    for target in targets:
        if target.scope == "project":
            # project 范围：复制整个项目根，并在沙盒里复刻项目根 -> carrier 根的层级。
            container_root = target.target_path.parent
            mirror_rel = 计算沙盒镜像相对路径(real_path=container_root, home_dir=home_dir)
            sandbox_container_root = (sandbox_root / mirror_rel).resolve()
            if container_root.exists():
                复制到沙盒镜像(source=container_root, destination=sandbox_container_root)
            sandbox_target_path = sandbox_container_root / target.target_path.name
        else:
            container_root = target.target_path
            mirror_rel = 计算沙盒镜像相对路径(real_path=target.target_path, home_dir=home_dir)
            sandbox_target_path = (sandbox_root / mirror_rel).resolve()
            if target.target_path.exists():
                复制到沙盒镜像(source=target.target_path, destination=sandbox_target_path)

        sandbox_targets.append(
            发布目标(
                target_path=sandbox_target_path,
                target_label=target.target_label,
                layout=target.layout,
                engine_vendor=target.engine_vendor,
                ide_vendor=target.ide_vendor,
                scope=target.scope,
            )
        )
        sandbox_target_summaries.append(
            {
                "target_label": target.target_label,
                "layout": target.layout,
                "scope": target.scope,
                "original_path": str(target.target_path),
                "container_root": str(container_root),
                "sandbox_path": str(sandbox_target_path),
                "exists_in_source": bool(target.target_path.exists()),
            }
        )
        path_mappings.append(
            {
                "role": "target",
                "label": target.target_label,
                "scope": target.scope,
                "real_path": str(target.target_path),
                "sandbox_path": str(sandbox_target_path),
            }
        )

    # 落盘 path_mapping.json
    mapping_payload = {
        "sandbox_root": str(sandbox_root),
        "home_dir": str(用户主目录(home_dir)),
        "layout_mode": "mirror_real_paths",
        "mappings": path_mappings,
    }
    mapping_path = sandbox_root / "path_mapping.json"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps(mapping_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return sandbox_paths, sandbox_targets, {
        "enabled": True,
        "sandbox_root": str(sandbox_root),
        "layout_mode": "mirror_real_paths",
        "targets": sandbox_target_summaries,
        "path_mappings": path_mappings,
        "path_mapping_file": str(mapping_path),
    }

def 更新用户级内容(
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
    sync_items_after: bool,
    backup_before_sync: bool = True,
    backup_dir: str = "",
    simulate_only: bool = False,
    sandbox_dir: str = "",
    enable_undo_journal: bool = True,
    undo_journal_dir: str = "",
    cleanup_unknown: bool = False,
    resolved_targets_override: list[发布目标] | None = None,
) -> dict[str, Any]:
    """执行用户级内容同步（基于 logical key + SQLite 元数据决策）。

    Args:
        cleanup_unknown: 是否清理目标目录中不在编译输出中的未跟踪文件。
            建议首次同步或沙盒模拟时启用。
    """

    if not AOL运行时可用():
        raise ValueError("aoc runtime 不可用，无法执行 update-user-content")

    if resolved_targets_override is not None:
        resolved_targets = list(resolved_targets_override)
    else:
        resolved_targets = 解析发布目标(
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
            targets=resolved_targets,
            home_dir=home_dir,
            sandbox_dir=sandbox_dir,
        )
        sandbox_journal_dir = str(sandbox_paths.repo_root / "datastore" / "sync_undo")
        sandbox_result = 更新用户级内容(
            sandbox_paths,
            target_paths=[],
            home_dir="",
            engine_vendors=[],
            ide_vendors=[],
            include_missing=True,
            scopes=scopes,
            project_dirs=project_dirs,
            dry_run=dry_run,
            sync_items_after=sync_items_after,
            backup_before_sync=False,
            backup_dir="",
            simulate_only=False,
            sandbox_dir="",
            enable_undo_journal=enable_undo_journal,
            undo_journal_dir=sandbox_journal_dir,
            cleanup_unknown=True,
            resolved_targets_override=sandbox_targets,
        )
        sandbox_result["sandbox"] = sandbox_summary
        sandbox_result["simulate_only"] = True
        sandbox_result["source_repo_root"] = str(paths.repo_root)
        return sandbox_result

    summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "source_count": 0,
        "target_count": 0,
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "targets": [],
        "errors": [],
        "touched_paths": [],
        "update_warnings": [],
        "aggregate_warnings": [],
        "publish_warnings": [],
        "sync_mode": "logical_key_registry_compare_then_publish",
        "decision_summary": {"added": 0, "updated": 0, "deleted": 0},
        "registry_summary": {"registry_hit_count": 0, "fallback_count": 0, "active_side_count": 0, "logical_key_count": 0},
        "sync_registry": {"enabled": False, "dry_run": dry_run},
        "undo_journal": {"enabled": False, "dry_run": dry_run},
        "sandbox": {"enabled": False},
        "simulate_only": False,
    }

    if backup_before_sync:
        backup_summary = 备份用户级内容(
            paths,
            target_paths=[str(item.target_path) for item in resolved_targets],
            home_dir=home_dir,
            engine_vendors=engine_vendors,
            ide_vendors=ide_vendors,
            include_missing=include_missing,
            backup_dir=backup_dir,
            scopes=scopes,
            project_dirs=project_dirs,
            dry_run=dry_run,
            resolved_targets_override=resolved_targets,
        )
        summary["backup"] = backup_summary
        summary["update_warnings"].extend(list(backup_summary.get("warnings") or []))
        summary["errors"].extend(list(backup_summary.get("errors") or []))
        summary["touched_paths"].extend(list(backup_summary.get("touched_paths") or []))
        if backup_summary.get("status") != "ok":
            raise ValueError(f"备份失败，已停止同步：{backup_summary}")
    else:
        summary["backup"] = {
            "enabled": False,
            "status": "skipped",
            "reason": "显式关闭备份",
            "dry_run": dry_run,
            "warnings": [],
            "errors": [],
            "touched_paths": [],
        }

    previous_registry, previous_target_files = 读取用户内容同步数据库基线(paths)
    side_entries, side_observe_times, source_summaries, aggregate_warnings, sync_errors, title_fallback = 收集用户级内容同步侧(
        paths,
        targets=resolved_targets,
    )
    # 去污染：过滤 canonical AOL 中旧同步 bug 产生的 vendor 后缀条目
    side_entries, decontam_stats = 过滤旧同步污染条目(side_entries)
    if decontam_stats.get("removed", 0) > 0:
        per_side = decontam_stats.get("per_side", {})
        side_detail = ", ".join(f"{k}={v}" for k, v in sorted(per_side.items()))
        aggregate_warnings.append(
            f"已过滤 {decontam_stats['removed']} 个旧同步 vendor 后缀污染条目（{side_detail}）"
        )
    side_priority = ["libs", *[f"target:{item.target_label}" for item in resolved_targets]]
    final_entries, registry_rows, registry_summary = 计算一键更新决策(
        side_entries=side_entries,
        side_observe_times=side_observe_times,
        previous_registry=previous_registry,
        side_priority=side_priority,
    )
    decision_summary = 计算canonical变更摘要(
        libs_entries=side_entries.get("libs", {}),
        final_entries=final_entries,
    )
    final_payload = 逻辑条目转AOL_payload(final_entries, title_fallback=title_fallback)
    merged_aol = payload转AOL对象(final_payload)
    canonical_write = {
        "path": str(解析AOL规范文件路径(paths)),
        "status": "blocked",
        "written": False,
        "dry_run": dry_run,
    }
    if not sync_errors:
        canonical_write = 写入canonical_AOL(paths, aol=merged_aol, dry_run=dry_run)

    aggregate_summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "source_count": len(source_summaries),
        "added": int(decision_summary.get("added") or 0),
        "updated": int(decision_summary.get("updated") or 0),
        "deleted": int(decision_summary.get("deleted") or 0),
        "sources": source_summaries,
        "errors": list(sync_errors),
        "touched_paths": [str(canonical_write.get("path") or "")] if canonical_write.get("path") else [],
        "aggregate_warnings": list(aggregate_warnings),
        "canonical_aol": canonical_write,
        "decision_summary": decision_summary,
        "registry_summary": registry_summary,
    }

    if sync_items_after and not dry_run and sum(int(value) for value in decision_summary.values()) > 0 and not sync_errors:
        aggregate_summary["items_sync"] = 同步_items(paths, dry_run=False)
    elif sync_items_after:
        aggregate_summary["items_sync"] = {
            "enabled": False,
            "reason": "dry_run 模式、无 canonical 变更或同步侧异常，跳过 items sync",
            "dry_run": dry_run,
        }
    else:
        aggregate_summary["items_sync"] = {
            "enabled": False,
            "reason": "显式关闭 items sync",
            "dry_run": dry_run,
        }

    if dry_run:
        aggregate_summary["aol_intermediate"] = 构建AOL摘要(
            merged_aol,
            source="in_memory_sync_dry_run",
            canonical_path=Path(str(canonical_write.get("path") or "")) if canonical_write.get("path") else None,
            warnings=list(aggregate_warnings),
        )
    elif sync_errors:
        aggregate_summary["aol_intermediate"] = {
            "enabled": False,
            "status": "blocked",
            "reason": "同步侧存在反编译错误，已阻止 canonical 写入与发布",
            "warnings": list(sync_errors),
        }
    else:
        aggregate_summary["aol_intermediate"] = 构建libs_aol中转摘要(paths)

    summary["aggregate"] = aggregate_summary
    summary["source_count"] = int(aggregate_summary.get("source_count") or 0)
    summary["canonical_aol"] = aggregate_summary.get("canonical_aol")
    summary["items_sync"] = aggregate_summary.get("items_sync")
    summary["aol_intermediate"] = aggregate_summary.get("aol_intermediate")
    summary["aggregate_warnings"] = list(aggregate_summary.get("aggregate_warnings") or [])
    summary["update_warnings"].extend(summary["aggregate_warnings"])
    summary["errors"].extend(list(aggregate_summary.get("errors") or []))
    summary["touched_paths"].extend(list(aggregate_summary.get("touched_paths") or []))
    summary["decision_summary"] = dict(decision_summary)
    summary["registry_summary"] = dict(registry_summary)

    publish_summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "target_count": len(resolved_targets),
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "targets": [],
        "errors": [],
        "touched_paths": [],
        "aol_intermediate": aggregate_summary.get("aol_intermediate"),
        "publish_warnings": [],
    }

    undo_journal: Any = None
    if enable_undo_journal and not sync_errors and 创建撤销账本 is not None:
        undo_journal = 创建撤销账本(
            repo_root=paths.repo_root,
            journal_root=Path(str(undo_journal_dir).strip()).expanduser() if str(undo_journal_dir).strip() else None,
            dry_run=dry_run,
            summary_meta={
                "repo_root": str(paths.repo_root),
                "target_labels": [item.target_label for item in resolved_targets],
                "decision_summary": dict(decision_summary),
            },
        )

    managed_target_files: dict[tuple[str, str], set[str]] = {}
    if sync_errors:
        publish_summary["errors"].append("同步侧存在反编译错误，已跳过正式发布")
    else:
        publish_aol = merged_aol if dry_run else 读取canonical_AOL(paths)
        for target in resolved_targets:
            part, managed_files = 发布到单个目标并同步删除(
                aol=publish_aol,
                target=target,
                dry_run=dry_run,
                warnings=publish_summary["publish_warnings"],
                previous_managed_files=previous_target_files.get((target.target_label, target.layout), set()),
                journal=undo_journal,
                cleanup_unknown=cleanup_unknown,
            )
            managed_target_files[(target.target_label, target.layout)] = managed_files
            合并发布统计(publish_summary, part)

    if undo_journal is not None:
        summary["undo_journal"] = undo_journal.结果摘要()
    else:
        summary["undo_journal"] = {
            "enabled": False,
            "reason": "显式关闭撤销账本或同步侧存在错误",
            "dry_run": dry_run,
        }

    summary["sync_registry"] = 写入用户内容同步数据库(
        paths,
        registry_rows=registry_rows,
        target_files=managed_target_files,
        dry_run=dry_run,
    )

    summary["publish"] = publish_summary
    summary["target_count"] = publish_summary["target_count"]
    summary["targets"] = list(publish_summary["targets"])
    summary["added"] = publish_summary["added"]
    summary["updated"] = publish_summary["updated"]
    summary["deleted"] = publish_summary["deleted"]
    summary["skipped_same"] = publish_summary["skipped_same"]
    summary["skipped_target_newer"] = publish_summary["skipped_target_newer"]
    summary["publish_warnings"] = list(publish_summary["publish_warnings"])
    summary["errors"].extend(list(publish_summary.get("errors") or []))
    summary["touched_paths"].extend(list(publish_summary.get("touched_paths") or []))

    return summary

def 执行更新用户级内容(argv: list[str], paths: 路径配置) -> int:
    """执行用户级内容一键更新子命令。"""

    parser = argparse.ArgumentParser(description="按范围与 logical key + SQLite 元数据基线同步当前设备或项目的 AI 内容")
    parser.add_argument("--target-path", action="append", default=[], help="可选：显式指定同步参与目标路径，可重复传入")
    parser.add_argument("--scope", action="append", default=[], help="可选：自动发现范围，可重复传入 global/system/user/project")
    parser.add_argument("--project-dir", action="append", default=[], help="可选：项目级自动发现根目录，可重复传入")
    parser.add_argument("--home-dir", default="", help="可选：覆盖自动发现使用的用户主目录")
    parser.add_argument("--engine", action="append", default=[], help="可选：按 engine_vendor 过滤自动发现的同步参与方，可重复传入")
    parser.add_argument("--ide", action="append", default=[], help="可选：按 ide_vendor 过滤自动发现的同步参与方，可重复传入")
    parser.add_argument("--include-missing", action="store_true", help="自动发现时包含当前尚不存在的候选目标目录")
    parser.add_argument("--backup-dir", default="", help="可选：备份根目录，默认使用 autodo-lib/datastore")
    parser.add_argument("--dry-run", action="store_true", help="仅输出变更预览，不写入磁盘")
    parser.add_argument("--skip-backup", action="store_true", help="更新开始前跳过自动备份")
    parser.add_argument("--skip-items-sync", action="store_true", help="更新完成后跳过 items sync")
    parser.add_argument("--simulate-only", action="store_true", help="仅在沙盒副本中执行同步，不修改真实目录")
    parser.add_argument("--sandbox-dir", default="", help="可选：沙盒根目录；不传则默认使用 Downloads 下的时间戳目录")
    parser.add_argument("--skip-undo-journal", action="store_true", help="本次同步不记录可撤销的增删改账本")
    parser.add_argument("--undo-journal-dir", default="", help="可选：撤销账本根目录；不传则默认使用 autodo-lib/datastore/sync_undo")
    args = parser.parse_args(argv)

    stats = 更新用户级内容(
        paths,
        target_paths=[str(item).strip() for item in list(args.target_path or []) if str(item).strip()],
        home_dir=str(args.home_dir or "").strip(),
        engine_vendors=[str(item).strip() for item in list(args.engine or []) if str(item).strip()],
        ide_vendors=[str(item).strip() for item in list(args.ide or []) if str(item).strip()],
        include_missing=bool(args.include_missing),
        scopes=[str(item).strip() for item in list(args.scope or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(args.project_dir or []) if str(item).strip()],
        dry_run=bool(args.dry_run),
        sync_items_after=not bool(args.skip_items_sync),
        backup_before_sync=not bool(args.skip_backup),
        backup_dir=str(args.backup_dir or "").strip(),
        simulate_only=bool(args.simulate_only),
        sandbox_dir=str(args.sandbox_dir or "").strip(),
        enable_undo_journal=not bool(args.skip_undo_journal),
        undo_journal_dir=str(args.undo_journal_dir or "").strip(),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0
