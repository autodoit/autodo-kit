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


def build_standard_affair_receipt(
    *,
    result_code: str,
    message: str,
    output_payload: dict[str, Any] | None = None,
    executor_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造标准事务回执结构。

    Args:
        result_code: 回执结果码，建议为 PASS/BLOCKED/FAIL。
        message: 面向编排层的人类可读摘要。
        output_payload: 事务输出载荷。
        executor_meta: 执行器元数据。

    Returns:
        标准回执字典。
    """

    normalized_code = str(result_code or "PASS").strip().upper() or "PASS"
    normalized_message = str(message or "事务执行完成").strip() or "事务执行完成"
    return {
        "result_code": normalized_code,
        "message": normalized_message,
        "output_payload": dict(output_payload or {}),
        "executor_meta": dict(executor_meta or {}),
    }


def write_affair_receipt_result(
    raw_cfg: dict[str, Any],
    config_path: Path,
    file_name: str,
    *,
    result_code: str,
    message: str,
    output_payload: dict[str, Any] | None = None,
    executor_meta: dict[str, Any] | None = None,
) -> list[Path]:
    """写出标准回执 JSON。

    Args:
        raw_cfg: 事务配置字典。
        config_path: 事务配置文件路径。
        file_name: 输出文件名。
        result_code: 回执结果码。
        message: 回执消息。
        output_payload: 输出载荷。
        executor_meta: 执行器元数据。

    Returns:
        输出文件路径列表。
    """

    receipt = build_standard_affair_receipt(
        result_code=result_code,
        message=message,
        output_payload=output_payload,
        executor_meta=executor_meta,
    )
    return write_affair_json_result(raw_cfg=raw_cfg, config_path=config_path, file_name=file_name, result=receipt)
