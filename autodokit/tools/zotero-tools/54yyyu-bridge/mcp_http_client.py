"""54yyyu Zotero MCP 的最小 HTTP 客户端。

该模块封装 `tools/list` 与 `tools/call`，便于接入 AOK facade。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Y54McpConfig:
    """54yyyu MCP 连接配置。

    Args:
        endpoint: MCP 服务 HTTP 端点。
        timeout_seconds: 超时秒数。
        headers: 额外请求头。

    Returns:
        Y54McpConfig: 配置对象。

    Raises:
        ValueError: endpoint 为空时抛出。

    Examples:
        >>> Y54McpConfig(endpoint="http://127.0.0.1:8000/mcp")
    """

    endpoint: str
    timeout_seconds: int = 30
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.endpoint.strip():
            raise ValueError("endpoint 不能为空")


class Y54McpHttpClient:
    """54yyyu MCP HTTP 客户端。

    Args:
        config: 连接配置。

    Returns:
        Y54McpHttpClient: 客户端实例。
    """

    def __init__(self, config: Y54McpConfig) -> None:
        self._config = config

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 MCP JSON-RPC POST 请求。

        Args:
            payload: 请求体。

        Returns:
            dict[str, Any]: 统一返回结构。
        """

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

    def list_tools(self) -> dict[str, Any]:
        """列出 MCP 工具。

        Returns:
            dict[str, Any]: 工具列表响应。

        Examples:
            >>> client.list_tools()
        """

        return self._post(
            {
                "jsonrpc": "2.0",
                "id": "aok-y54-list",
                "method": "tools/list",
                "params": {},
            }
        )

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用 MCP 工具。

        Args:
            tool_name: 工具名。
            arguments: 参数字典。

        Returns:
            dict[str, Any]: 调用响应。

        Raises:
            ValueError: tool_name 为空时抛出。

        Examples:
            >>> client.call_tool("zotero_search_items", {"query": "causal"})
        """

        if not tool_name.strip():
            raise ValueError("tool_name 不能为空")

        return self._post(
            {
                "jsonrpc": "2.0",
                "id": "aok-y54-call",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments or {},
                },
            }
        )


def build_default_client() -> Y54McpHttpClient:
    """构建默认客户端。

    Returns:
        Y54McpHttpClient: 默认客户端。
    """

    return Y54McpHttpClient(Y54McpConfig(endpoint="http://127.0.0.1:8000/mcp"))
