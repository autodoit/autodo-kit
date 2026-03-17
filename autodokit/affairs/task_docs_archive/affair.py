"""事务：归档任务文档（移动到 archives 并更新 tags）。

输入（config，核心字段）：
- root_dir: 扫描根目录（必填）
- task_name: 任务名（必填）
- archive_dir: 归档目录（可选；默认 <root_dir>/archives）
- include_latest: 是否包含 latest（可选，默认 false）
- dry_run: 是否干运行（可选，默认 false）

输出：
- 移动后的文件路径列表。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from autodokit.tools import load_json_or_py
from autodokit.tools.task_docs import archive_task_files


@dataclass
class ArchiveConfig:
    """归档任务文档配置。

    Attributes:
        root_dir: 扫描根目录。
        task_name: 任务名。
        archive_dir: 归档目录。
        include_latest: 是否包含 latest。
        dry_run: 是否干运行。
    """

    root_dir: str
    task_name: str
    archive_dir: str = ""
    include_latest: bool = False
    dry_run: bool = False


def _parse_config(data: Dict[str, Any]) -> ArchiveConfig:
    """解析并校验归档配置。"""

    root_dir = str(data.get("root_dir") or "").strip()
    if not root_dir:
        raise ValueError("root_dir 不能为空")

    task_name = str(data.get("task_name") or "").strip()
    if not task_name:
        raise ValueError("task_name 不能为空")

    archive_dir = str(data.get("archive_dir") or "").strip()
    include_latest = bool(data.get("include_latest") or False)
    dry_run = bool(data.get("dry_run") or False)

    return ArchiveConfig(
        root_dir=root_dir,
        task_name=task_name,
        archive_dir=archive_dir,
        include_latest=include_latest,
        dry_run=dry_run,
    )


def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """AOK 事务入口：归档任务文档。"""

    data = load_json_or_py(Path(config_path))
    cfg = _parse_config(data)

    root_dir = Path(cfg.root_dir)
    archive_dir = Path(cfg.archive_dir) if cfg.archive_dir else (root_dir / "history")

    return archive_task_files(
        root_dir=root_dir,
        task_name=cfg.task_name,
        archive_dir=archive_dir,
        include_latest=cfg.include_latest,
        dry_run=cfg.dry_run,
    )

