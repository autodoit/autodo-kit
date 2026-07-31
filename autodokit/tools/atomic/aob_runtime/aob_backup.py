# -*- coding: utf-8 -*-
"""AOB 备份原子工具（backup-user-content）。

将 libs 与各引擎办公区目录打包快照到备份目录，做风险操作前的安全网。
"""

from __future__ import annotations

from .aob_common import *

import json
import shutil
import time
from pathlib import Path
from typing import Any


def 备份用户级内容(
    paths: 路径配置,
    *,
    target_paths: list[str],
    home_dir: str,
    engine_vendors: list[str],
    ide_vendors: list[str],
    include_missing: bool,
    backup_dir: str,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    resolved_targets_override: list[发布目标] | None = None,
) -> dict[str, Any]:
    """备份 libs 与用户级目标 AI 内容。"""

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

    backup_root = (
        Path(str(backup_dir).strip()).expanduser().resolve()
        if str(backup_dir).strip()
        else 默认用户内容备份根目录(paths)
    )
    snapshot_dir = 构造备份快照目录(backup_root=backup_root)

    summary: dict[str, Any] = {
        "enabled": True,
        "status": "ok",
        "dry_run": dry_run,
        "backup_root": str(backup_root),
        "snapshot_dir": str(snapshot_dir),
        "target_count": len(targets),
        "sources": [],
        "skipped_missing": 0,
        "errors": [],
        "warnings": [],
        "touched_paths": [],
        "file_count": 0,
    }

    source_specs: list[tuple[str, Path, Path, str, str]] = []
    source_specs.append(("libs", paths.libs_root, snapshot_dir / "libs", "libs", "global"))
    for target in targets:
        backup_source_path = target.target_path.parent if target.scope == "project" else target.target_path
        source_specs.append(
            (
                f"target:{target.target_label}",
                backup_source_path,
                snapshot_dir / "targets" / f"{target.target_label}__{target.layout}",
                target.layout,
                target.scope,
            )
        )

    manifest_sources: list[dict[str, Any]] = []
    for source_id, source_path, destination_path, layout, scope in source_specs:
        if not source_path.exists():
            summary["skipped_missing"] += 1
            summary["warnings"].append(f"来源不存在，跳过备份：{source_path}")
            manifest_sources.append(
                {
                    "source_id": source_id,
                    "layout": layout,
                    "scope": scope,
                    "source_path": str(source_path),
                    "destination_path": str(destination_path),
                    "status": "missing",
                    "file_count": 0,
                }
            )
            continue

        file_count = 统计文件数量(source_path)
        manifest_sources.append(
            {
                "source_id": source_id,
                "layout": layout,
                "scope": scope,
                "source_path": str(source_path),
                "destination_path": str(destination_path),
                "status": "copied" if not dry_run else "dry_run_preview",
                "file_count": file_count,
            }
        )
        summary["file_count"] += file_count
        summary["touched_paths"].append(str(destination_path))

        if dry_run:
            continue

        try:
            if destination_path.exists():
                if destination_path.is_file():
                    destination_path.unlink()
                else:
                    shutil.rmtree(destination_path)
            复制到备份快照(source=source_path, destination=destination_path)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"备份失败：{source_path} -> {destination_path} ({exc})")

    summary["sources"] = manifest_sources
    if summary["errors"]:
        summary["status"] = "error"

    manifest_payload = {
        "schema": "aob_user_content_backup_manifest_v1",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "backup_root": str(backup_root),
        "snapshot_dir": str(snapshot_dir),
        "dry_run": dry_run,
        "source_count": len(source_specs),
        "file_count": summary["file_count"],
        "sources": manifest_sources,
        "warnings": list(summary["warnings"]),
        "errors": list(summary["errors"]),
    }
    summary["manifest"] = manifest_payload

    if not dry_run:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = snapshot_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["manifest_path"] = str(manifest_path)
        summary["touched_paths"].append(str(manifest_path))
    else:
        summary["manifest_path"] = str(snapshot_dir / "manifest.json")

    return summary

def 执行备份用户级内容(argv: list[str], paths: 路径配置) -> int:
    """执行用户级内容备份子命令。"""

    parser = argparse.ArgumentParser(description="按范围备份当前设备或项目的 AI 内容（libs + 参与目标）")
    parser.add_argument("--target-path", action="append", default=[], help="可选：显式指定备份目标路径，可重复传入")
    parser.add_argument("--scope", action="append", default=[], help="可选：自动发现范围，可重复传入 global/system/user/project")
    parser.add_argument("--project-dir", action="append", default=[], help="可选：项目级自动发现根目录，可重复传入")
    parser.add_argument("--home-dir", default="", help="可选：覆盖自动发现使用的用户主目录")
    parser.add_argument("--engine", action="append", default=[], help="可选：按 engine_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--ide", action="append", default=[], help="可选：按 ide_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--include-missing", action="store_true", help="自动发现时包含当前尚不存在的候选目标目录")
    parser.add_argument("--backup-dir", default="", help="可选：备份根目录，默认使用 autodo-lib/datastore")
    parser.add_argument("--dry-run", action="store_true", help="仅输出备份计划，不写入磁盘")
    args = parser.parse_args(argv)

    stats = 备份用户级内容(
        paths,
        target_paths=[str(item).strip() for item in list(args.target_path or []) if str(item).strip()],
        home_dir=str(args.home_dir or "").strip(),
        engine_vendors=[str(item).strip() for item in list(args.engine or []) if str(item).strip()],
        ide_vendors=[str(item).strip() for item in list(args.ide or []) if str(item).strip()],
        include_missing=bool(args.include_missing),
        backup_dir=str(args.backup_dir or "").strip(),
        scopes=[str(item).strip() for item in list(args.scope or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(args.project_dir or []) if str(item).strip()],
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0
