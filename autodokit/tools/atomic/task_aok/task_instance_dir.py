"""AOK 任务实例目录辅助工具。"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from autodokit.path_compat import resolve_portable_path


def create_task_instance_dir(
    workspace_root: Path,
    node_code: str,
    *,
    task_uid: str | None = None,
    manifest_extra: Mapping[str, Any] | None = None,
) -> Path:
    """创建任务实例目录并写入最小 manifest。"""

    tasks_root = workspace_root / "tasks"
    tasks_root.mkdir(parents=True, exist_ok=True)
    resolved_task_uid = task_uid or f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{node_code}"
    task_instance_dir = tasks_root / resolved_task_uid
    task_instance_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "task_uid": resolved_task_uid,
        "node_code": node_code,
        "workspace_root": str(workspace_root),
        "task_instance_dir": str(task_instance_dir),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if manifest_extra:
        manifest.update(dict(manifest_extra))
    (task_instance_dir / "task_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return task_instance_dir


def resolve_legacy_output_dir(
    raw_cfg: Mapping[str, Any],
    config_path: Path,
    *,
    default_path: Path | None = None,
) -> Path:
    """解析旧输出目录，用于兼容镜像。"""

    raw_value = raw_cfg.get("legacy_output_dir") or raw_cfg.get("output_dir")
    legacy_output_dir = resolve_portable_path(
        raw_value or default_path or config_path.parent,
        base=config_path.parent,
    )
    if not legacy_output_dir.is_absolute():
        raise ValueError(f"legacy_output_dir/output_dir 必须为绝对路径: {legacy_output_dir}")
    legacy_output_dir.mkdir(parents=True, exist_ok=True)
    return legacy_output_dir


def mirror_artifacts_to_legacy(
    artifact_paths: Iterable[Path],
    legacy_output_dir: Path,
    task_instance_dir: Path,
) -> list[Path]:
    """将任务目录中的文件镜像回旧输出目录。"""

    if legacy_output_dir.resolve() == task_instance_dir.resolve():
        return []
    legacy_output_dir.mkdir(parents=True, exist_ok=True)
    mirrored: list[Path] = []
    for artifact_path in artifact_paths:
        path = Path(artifact_path)
        if not path.exists() or not path.is_file():
            continue
        target_path = legacy_output_dir / path.name
        shutil.copy2(path, target_path)
        mirrored.append(target_path)
    return mirrored