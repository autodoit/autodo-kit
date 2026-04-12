"""孤儿附件隔离原子工具。"""

from __future__ import annotations

import filecmp
import hashlib
import shutil
import sqlite3
from pathlib import Path
from typing import Any


def _files_have_same_content(left: Path, right: Path) -> bool:
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        return filecmp.cmp(str(left), str(right), shallow=False)
    except OSError:
        return False


def _resolve_conflict_safe_target_path(source: Path, target_path: Path) -> Path:
    if not target_path.exists():
        return target_path
    if _files_have_same_content(source, target_path):
        return target_path

    digest = hashlib.md5(str(source.resolve()).encode("utf-8")).hexdigest()[:12]
    candidate = target_path.with_name(f"{target_path.stem}__{digest}{target_path.suffix}")
    counter = 2
    while candidate.exists() and not _files_have_same_content(source, candidate):
        candidate = target_path.with_name(f"{target_path.stem}__{digest}_{counter}{target_path.suffix}")
        counter += 1
    return candidate


def _prune_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for child in sorted(root.rglob("*"), reverse=True):
        if child.is_dir():
            try:
                child.rmdir()
            except OSError:
                continue


def _load_matched_paths_from_content_db(content_db: Path) -> set[str]:
    rows: set[str] = set()
    with sqlite3.connect(str(content_db), timeout=60) as conn:
        for (storage_path,) in conn.execute(
            "SELECT storage_path FROM attachments WHERE COALESCE(storage_path, '') <> ''"
        ).fetchall():
            rows.add(str(Path(str(storage_path)).expanduser().resolve()))
    return rows


def isolate_unmatched_attachments(payload: dict[str, Any]) -> dict[str, Any]:
    """隔离未被主库引用的孤儿附件。

    Args:
        payload: 输入参数字典。
            - workspace_attachments_dir: 待扫描附件目录（必填）。
            - unmatched_attachments_dir: 孤儿隔离目录（可选，默认同级 unmatched_attachments）。
            - content_db: content.db 路径（可选，优先用于读取已匹配 storage_path）。
            - matched_storage_paths: 已匹配路径列表（可选，会与 content_db 结果合并）。
            - dry_run: 仅统计不移动，默认 False。
            - prune_empty_dirs: 是否清理空目录，默认 True。

    Returns:
        dict[str, Any]: 隔离执行摘要。

    Raises:
        ValueError: 当 workspace_attachments_dir 缺失时抛出。

    Examples:
        >>> isolate_unmatched_attachments({
        ...     "workspace_attachments_dir": "workspace/references/attachments",
        ...     "content_db": "workspace/database/content/content.db",
        ...     "dry_run": True,
        ... })["status"]
        'PASS'
    """

    attachments_raw = str(payload.get("workspace_attachments_dir") or "").strip()
    if not attachments_raw:
        raise ValueError("workspace_attachments_dir 不能为空")

    workspace_attachments_dir = Path(attachments_raw).expanduser().resolve()
    default_unmatched_dir = workspace_attachments_dir.parent / "unmatched_attachments"
    unmatched_attachments_dir = Path(
        str(payload.get("unmatched_attachments_dir") or default_unmatched_dir)
    ).expanduser().resolve()

    dry_run = bool(payload.get("dry_run", True))
    prune_empty_dirs = bool(payload.get("prune_empty_dirs", True))

    matched_paths: set[str] = {
        str(Path(str(item)).expanduser().resolve())
        for item in (payload.get("matched_storage_paths") or [])
        if str(item).strip()
    }
    content_db_raw = str(payload.get("content_db") or "").strip()
    if content_db_raw:
        matched_paths |= _load_matched_paths_from_content_db(Path(content_db_raw).expanduser().resolve())

    if not workspace_attachments_dir.exists():
        return {
            "status": "SKIPPED",
            "workspace_attachments_dir": str(workspace_attachments_dir),
            "unmatched_dir": str(unmatched_attachments_dir),
            "matched_count": len(matched_paths),
            "unmatched_count": 0,
            "dry_run": dry_run,
            "rows": [],
        }

    unmatched_attachments_dir.mkdir(parents=True, exist_ok=True)
    moved_rows: list[dict[str, str]] = []

    for source in sorted(workspace_attachments_dir.rglob("*")):
        if not source.is_file():
            continue
        resolved_source = str(source.resolve())
        if resolved_source in matched_paths:
            continue

        relative_path = source.relative_to(workspace_attachments_dir)
        target_path = _resolve_conflict_safe_target_path(source, unmatched_attachments_dir / relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if not dry_run:
            if target_path.exists() and _files_have_same_content(source, target_path):
                source.unlink()
            else:
                shutil.move(str(source), str(target_path))

        moved_rows.append(
            {
                "source_path": resolved_source,
                "isolated_path": str(target_path.resolve()),
                "relative_path": str(relative_path).replace("\\", "/"),
            }
        )

    if prune_empty_dirs and not dry_run:
        _prune_empty_dirs(workspace_attachments_dir)

    return {
        "status": "PASS",
        "workspace_attachments_dir": str(workspace_attachments_dir),
        "unmatched_dir": str(unmatched_attachments_dir),
        "matched_count": len(matched_paths),
        "unmatched_count": len(moved_rows),
        "dry_run": dry_run,
        "rows": moved_rows,
    }
