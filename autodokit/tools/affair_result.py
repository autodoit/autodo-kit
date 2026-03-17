"""事务结果写出辅助工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ensure_absolute_output_dir(raw_cfg: dict[str, Any], config_path: Path) -> Path:
    """解析并校验事务输出目录。

    Args:
        raw_cfg: 事务配置字典。
        config_path: 事务配置文件路径。

    Returns:
        绝对输出目录路径。

    Raises:
        ValueError: 输出目录不是绝对路径时抛出。
    """

    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={str(raw_cfg.get('output_dir') or '')!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def write_affair_json_result(
    raw_cfg: dict[str, Any],
    config_path: Path,
    file_name: str,
    result: Any,
) -> list[Path]:
    """把事务结果写成 JSON 文件。

    Args:
        raw_cfg: 事务配置字典。
        config_path: 事务配置路径。
        file_name: 输出文件名。
        result: 待写出的结果对象。

    Returns:
        输出文件路径列表。
    """

    output_dir = ensure_absolute_output_dir(raw_cfg=raw_cfg, config_path=config_path)
    out_path = output_dir / file_name
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
