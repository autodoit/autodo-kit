"""54yyyu MCP 服务探活脚本。"""

from __future__ import annotations

from typing import Any

from mcp_http_client import build_default_client


def probe_service() -> dict[str, Any]:
    """探测服务可用性与工具列表。

    Returns:
        dict[str, Any]: 探测结果。

    Examples:
        >>> probe_service()
    """

    client = build_default_client()
    result = client.list_tools()
    if not result.get("ok"):
        return {
            "ok": False,
            "stage": "tools/list",
            "error": result.get("error", "unknown error"),
        }

    tools = (
        result.get("data", {})
        .get("result", {})
        .get("tools", [])
    )
    return {
        "ok": True,
        "stage": "done",
        "tool_count": len(tools),
        "error": "",
    }


if __name__ == "__main__":
    print(probe_service())
