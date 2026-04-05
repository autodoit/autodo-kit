"""事务：聚合任务文档产物生成汇总。

本事务把【通用文档管理工作流】中的 `aggregate_task.py` 工程化为 AOK affair。

输入（config.json，核心字段）：
- root_dir: 扫描根目录（必填）
- task_name: 任务名称（必填）
- output_dir: 输出目录（必填）
- uid_mode: UID 模式（可选，默认 timestamp-us-rand）
- uid_random_length: 随机后缀长度（可选，默认 2）
- dry_run: 是否不写文件（可选，默认 false）

输出：
- 汇总文件路径列表（找不到源文件则返回空列表）。

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
from autodokit.tools.task_docs import UidSpec, aggregate_task_documents


@dataclass
class AggregateConfig:
    """聚合任务文档配置。

    Attributes:
        root_dir: 扫描根目录。
        task_name: 任务名称。
        output_dir: 输出目录。
        uid_mode: UID 生成模式。
        uid_random_length: 随机后缀长度。
        dry_run: 是否干运行（不写文件）。
    """

    root_dir: str
    task_name: str
    output_dir: str
    uid_mode: str = "timestamp-us-rand"
    uid_random_length: int = 2
    dry_run: bool = False


def _parse_config(data: Dict[str, Any]) -> AggregateConfig:
    """解析并校验聚合配置。

    Args:
        data: 配置字典。

    Returns:
        AggregateConfig: 结构化配置。

    Raises:
        ValueError: 配置缺失或类型不正确。
    """

    root_dir = str(data.get("root_dir") or "").strip()
    if not root_dir:
        raise ValueError("root_dir 不能为空")

    task_name = str(data.get("task_name") or "").strip()
    if not task_name:
        raise ValueError("task_name 不能为空")

    output_dir = str(data.get("output_dir") or "").strip()
    if not output_dir:
        raise ValueError("output_dir 不能为空")

    uid_mode = str(data.get("uid_mode") or "timestamp-us-rand").strip() or "timestamp-us-rand"
    uid_random_length = int(data.get("uid_random_length") or 2)

    dry_run = bool(data.get("dry_run") or False)

    return AggregateConfig(
        root_dir=root_dir,
        task_name=task_name,
        output_dir=output_dir,
        uid_mode=uid_mode,
        uid_random_length=uid_random_length,
        dry_run=dry_run,
    )


def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """AOK 事务入口：聚合任务文档。

    Args:
        config_path: 调度器传入的临时配置文件路径。
        workspace_root: 工作区根目录（由调度器传入；本事务不强依赖）。

    Returns:
        写出的文件 Path 列表；找不到源文件则为空列表。

    Raises:
        ValueError: 配置非法。
    """

    data = load_json_or_py(Path(config_path))
    cfg = _parse_config(data)

    uid_spec = UidSpec(mode=cfg.uid_mode, random_length=cfg.uid_random_length)
    out_path = aggregate_task_documents(
        root_dir=Path(cfg.root_dir),
        task_name=cfg.task_name,
        output_dir=Path(cfg.output_dir),
        uid_spec=uid_spec,
        dry_run=cfg.dry_run,
    )

    return [out_path] if out_path is not None else []

