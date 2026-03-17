"""事务：创建任务 latest 文档。

本事务把【通用文档管理工作流】中的 `create_latest.py` 工程化为 AOK affair。

输入（config.json，核心字段）：
- task_name: 任务名称（必填）
- doc_types: 文档类型列表，例如 ["需求","设计","过程"]（必填）
- output_dir: 输出目录（必填）
- uid_mode: UID 模式（可选，默认 timestamp-us-rand）
- uid_random_length: 随机后缀长度（可选，默认 2）
- overwrite: 是否覆盖已存在文件（可选，默认 false）

输出：
- 写出的 Markdown 文件路径列表。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from autodokit.tools import load_json_or_py
from autodokit.tools.task_docs import UidSpec, create_latest_files


@dataclass
class CreateLatestConfig:
    """创建 latest 文档的事务配置。

    Attributes:
        task_name: 任务名称。
        doc_types: 需要创建的文档类型列表（需求/设计/过程）。
        output_dir: 输出目录（绝对或相对路径，调度器通常会先解析为绝对路径）。
        uid_mode: UID 生成模式。
        uid_random_length: UID 随机后缀长度（仅 *-rand 生效）。
        overwrite: 是否覆盖已存在文件。
        extra_tags: 额外 tags（可选）。
    """

    task_name: str
    doc_types: List[str]
    output_dir: str
    uid_mode: str = "timestamp-us-rand"
    uid_random_length: int = 2
    overwrite: bool = False
    extra_tags: Optional[List[str]] = None


def _parse_config(data: Dict[str, Any]) -> CreateLatestConfig:
    """解析并校验事务配置。

    Args:
        data: 配置字典。

    Returns:
        CreateLatestConfig: 结构化配置。

    Raises:
        ValueError: 配置缺失或类型不正确。
    """

    task_name = str(data.get("task_name") or "").strip()
    if not task_name:
        raise ValueError("task_name 不能为空")

    doc_types_raw = data.get("doc_types")
    if not isinstance(doc_types_raw, list) or not doc_types_raw:
        raise ValueError("doc_types 必须是非空列表")
    doc_types = [str(x).strip() for x in doc_types_raw if str(x).strip()]
    if not doc_types:
        raise ValueError("doc_types 不能为空")

    output_dir = str(data.get("output_dir") or "").strip()
    if not output_dir:
        raise ValueError("output_dir 不能为空")

    uid_mode = str(data.get("uid_mode") or "timestamp-us-rand").strip() or "timestamp-us-rand"
    uid_random_length = int(data.get("uid_random_length") or 2)

    overwrite = bool(data.get("overwrite") or False)

    extra_tags_raw = data.get("extra_tags")
    extra_tags: Optional[List[str]] = None
    if isinstance(extra_tags_raw, list):
        extra_tags = [str(x).strip() for x in extra_tags_raw if str(x).strip()]

    return CreateLatestConfig(
        task_name=task_name,
        doc_types=doc_types,
        output_dir=output_dir,
        uid_mode=uid_mode,
        uid_random_length=uid_random_length,
        overwrite=overwrite,
        extra_tags=extra_tags,
    )


def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """AOK 事务入口：创建任务 latest 文档。

    Args:
        config_path: 调度器传入的临时配置文件路径。
        workspace_root: 工作区根目录（由调度器传入；本事务不强依赖）。

    Returns:
        写出的文件 Path 列表。

    Raises:
        ValueError: 配置非法。
        FileExistsError: overwrite=false 且目标文件已存在。
    """

    data = load_json_or_py(Path(config_path))
    cfg = _parse_config(data)

    uid_spec = UidSpec(mode=cfg.uid_mode, random_length=cfg.uid_random_length)
    output_dir = Path(cfg.output_dir)

    return create_latest_files(
        task_name=cfg.task_name,
        doc_types=cfg.doc_types,
        output_dir=output_dir,
        uid_spec=uid_spec,
        overwrite=cfg.overwrite,
        extra_tags=cfg.extra_tags,
    )

