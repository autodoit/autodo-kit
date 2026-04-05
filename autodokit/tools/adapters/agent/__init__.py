"""Agent 适配层辅助函数。"""

from __future__ import annotations

from typing import Any

from autodokit.tools import get_tool


def agent_invoke(tool_name: str, payload: dict[str, Any] | None = None, *, agent_id: str = "agent", scope: str = "user") -> dict[str, Any]:
    """供 Agent 按工具名调用函数。

    Args:
        tool_name: 工具函数名。
        payload: 调用参数，支持 `args` 与 `kwargs` 两个键。
        agent_id: 智能体标识。
        scope: 工具范围，支持 `user`、`developer`、`all`。

    Returns:
        dict[str, Any]: 调用结果。
    """

    context = {"caller_source": "agent", "caller_id": agent_id}
    data = dict(payload or {})
    args = data.get("args", [])
    kwargs = data.get("kwargs", {})
    if not isinstance(args, list):
        raise ValueError("payload.args 必须是列表")
    if not isinstance(kwargs, dict):
        raise ValueError("payload.kwargs 必须是字典")

    fn = get_tool(tool_name, scope=scope)
    result = fn(*args, **kwargs)
    return {"status": "success", "tool_name": tool_name, "caller": context, "data": result}


__all__ = ["agent_invoke"]
