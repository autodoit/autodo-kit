"""AOK 公共工具网关。

本模块提供公共工具 manifest 的读取与筛选能力，用于：

1. 统一登记 AOK 对外暴露工具；
2. 为 CLI / Agent / UI 提供只读工具目录；
3. 按 `public-read` / `public-safe` / `internal` 做分级过滤。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autodokit.tools.public import (
    get_public_capability,
    invoke_capability,
    list_public_capabilities,
)


@dataclass(frozen=True)
class 公共工具条目:
    """公共工具条目。

    Args:
        tool_id: 工具唯一标识。
        kind: 工具类型，通常为 `python-symbol` 或 `script-entrypoint`。
        exposure: 暴露等级，支持 `public-read`、`public-safe`、`internal`。
        module: Python 模块路径或脚本逻辑模块。
        symbol: Python 符号名；脚本型工具可为空。
        entrypoint: 脚本入口相对路径；函数型工具可为空。
        summary: 简要说明。
        side_effect: 副作用说明。
        audit_mode: 审计模式说明。
    """

    tool_id: str
    kind: str
    exposure: str
    module: str
    symbol: str | None
    entrypoint: str | None
    summary: str
    side_effect: str
    audit_mode: str


def _默认清单路径() -> Path:
    """返回默认 manifest 路径。

    Returns:
        Path: 默认 manifest 文件路径。
    """

    return Path(__file__).resolve().parent / "public_tools_manifest.json"


def 读取公共工具清单(manifest_path: str | Path | None = None) -> dict[str, Any]:
    """读取公共工具 manifest。

    Args:
        manifest_path: manifest 路径；为空时使用内置默认路径。

    Returns:
        dict[str, Any]: manifest 原始字典。

    Raises:
        FileNotFoundError: manifest 不存在时抛出。
        ValueError: manifest 结构不合法时抛出。
    """

    path = Path(manifest_path).expanduser().resolve() if manifest_path else _默认清单路径()
    if not path.exists():
        raise FileNotFoundError(f"未找到公共工具 manifest：{path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("公共工具 manifest 顶层必须是对象")
    tools = payload.get("tools", [])
    if not isinstance(tools, list):
        raise ValueError("公共工具 manifest 的 tools 字段必须是数组")
    return payload


def 列出公共工具(
    *,
    exposure: str | None = None,
    kind: str | None = None,
    manifest_path: str | Path | None = None,
) -> list[公共工具条目]:
    """按条件列出公共工具。

    Args:
        exposure: 暴露等级过滤。
        kind: 工具类型过滤。
        manifest_path: manifest 路径；为空时使用默认路径。

    Returns:
        list[公共工具条目]: 过滤后的工具条目列表。
    """

    payload = 读取公共工具清单(manifest_path)
    result: list[公共工具条目] = []
    for item in payload.get("tools", []):
        if not isinstance(item, dict):
            continue
        current_exposure = str(item.get("exposure", "")).strip()
        current_kind = str(item.get("kind", "")).strip()
        if exposure and current_exposure != exposure:
            continue
        if kind and current_kind != kind:
            continue
        result.append(
            公共工具条目(
                tool_id=str(item.get("tool_id", "")).strip(),
                kind=current_kind,
                exposure=current_exposure,
                module=str(item.get("module", "")).strip(),
                symbol=str(item.get("symbol", "")).strip() or None,
                entrypoint=str(item.get("entrypoint", "")).strip() or None,
                summary=str(item.get("summary", "")).strip(),
                side_effect=str(item.get("side_effect", "")).strip(),
                audit_mode=str(item.get("audit_mode", "")).strip(),
            )
        )
    return result


def 获取公共工具(tool_id: str, *, manifest_path: str | Path | None = None) -> 公共工具条目 | None:
    """按 `tool_id` 获取单个公共工具条目。

    Args:
        tool_id: 工具唯一标识。
        manifest_path: manifest 路径；为空时使用默认路径。

    Returns:
        公共工具条目 | None: 找到则返回条目，否则返回 `None`。
    """

    target = str(tool_id).strip()
    if not target:
        return None
    for item in 列出公共工具(manifest_path=manifest_path):
        if item.tool_id == target:
            return item
    return None


__all__ = [
    "公共工具条目",
    "读取公共工具清单",
    "列出公共工具",
    "获取公共工具",
    "调用公共工具",
    "列出公共能力",
    "获取公共能力",
]


def 调用公共工具(
    tool_id: str,
    *,
    payload: Any | None = None,
    caller_context: dict[str, Any] | None = None,
    allow_internal: bool = False,
) -> dict[str, Any]:
    """调用公共工具（兼容包装）。

    Args:
        tool_id: 工具或能力标识。
        payload: 调用参数。
        caller_context: 调用方上下文。
        allow_internal: 是否允许调用 internal 能力。

    Returns:
        dict[str, Any]: 标准调用结果。
    """

    return invoke_capability(
        tool_id,
        payload=payload,
        caller_context=caller_context,
        allow_internal=allow_internal,
    )


def 列出公共能力(*, exposure: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    """列出公共能力（兼容包装）。"""

    return list_public_capabilities(exposure=exposure, kind=kind)


def 获取公共能力(tool_id: str) -> dict[str, Any] | None:
    """读取单个公共能力（兼容包装）。"""

    return get_public_capability(tool_id)