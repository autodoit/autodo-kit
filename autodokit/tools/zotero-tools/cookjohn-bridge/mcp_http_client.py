"""cookjohn Zotero MCP 的最小 HTTP 客户端。

该模块提供最基础的 MCP 请求封装，供 AOK 上层工具调用。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CookjohnMcpConfig:
    """cookjohn MCP 连接配置。

    Args:
        endpoint: MCP HTTP 端点。
        timeout_seconds: 请求超时时间（秒）。
        headers: 额外请求头。

    Returns:
        CookjohnMcpConfig: 配置对象。

    Raises:
        ValueError: 当 endpoint 为空时抛出。

    Examples:
        >>> cfg = CookjohnMcpConfig(endpoint="http://127.0.0.1:23120/mcp")
    """

    endpoint: str
    timeout_seconds: int = 30
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.endpoint.strip():
            raise ValueError("endpoint 不能为空")


class CookjohnMcpHttpClient:
    """基于 HTTP 的 MCP 调用客户端。

    Args:
        config: 连接配置。

    Returns:
        CookjohnMcpHttpClient: 客户端实例。

    Examples:
        >>> client = CookjohnMcpHttpClient(CookjohnMcpConfig("http://127.0.0.1:23120/mcp"))
    """

    def __init__(self, config: CookjohnMcpConfig) -> None:
        self._config = config

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用 MCP 工具。

        Args:
            tool_name: 工具名。
            arguments: 工具参数。

        Returns:
            dict[str, Any]: 统一结果，包含 `ok`、`data`、`error` 字段。

        Raises:
            ValueError: 当 tool_name 为空时抛出。

        Examples:
            >>> client.call_tool("search_library", {"q": "machine learning"})
        """

        if not tool_name.strip():
            raise ValueError("tool_name 不能为空")

        payload = {
            "jsonrpc": "2.0",
            "id": "aok-cookjohn-1",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req_headers = {"Content-Type": "application/json"}
        if self._config.headers:
            req_headers.update(self._config.headers)

        req = urllib.request.Request(
            self._config.endpoint,
            data=body,
            headers=req_headers,
            method="POST",
        )
        try:
            response = urllib.request.urlopen(req, timeout=self._config.timeout_seconds)
            raw_text = response.read().decode("utf-8", errors="replace")
            data = json.loads(raw_text) if raw_text else {}
            return {"ok": True, "data": data, "error": ""}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "data": {}, "error": f"HTTPError {exc.code}: {detail}"}
        except urllib.error.URLError as exc:
            return {"ok": False, "data": {}, "error": f"URLError: {exc.reason}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "data": {}, "error": f"UnexpectedError: {exc}"}


def build_default_client() -> CookjohnMcpHttpClient:
    """构建默认客户端。

    Returns:
        CookjohnMcpHttpClient: 默认端点客户端。

    Examples:
        >>> client = build_default_client()
    """

    return CookjohnMcpHttpClient(CookjohnMcpConfig(endpoint="http://127.0.0.1:23120/mcp"))
