"""54yyyu MCP 拉取示例。"""

from __future__ import annotations

from typing import Any

from mcp_http_client import build_default_client


def pull_items(query: str, limit: int = 10) -> dict[str, Any]:
    """拉取 Zotero 条目（54yyyu 工具）。

    Args:
        query: 查询字符串。
        limit: 返回上限。

    Returns:
        dict[str, Any]: 统一结果字典。

    Examples:
        >>> pull_items("machine learning", 10)
    """

    client = build_default_client()
    return client.call_tool(
        "zotero_search_items",
        {
            "query": query,
            "limit": limit,
        },
    )


def pull_notes(query: str, limit: int = 20) -> dict[str, Any]:
    """搜索 Zotero 笔记与注释。

    Args:
        query: 搜索关键词。
        limit: 返回上限。

    Returns:
        dict[str, Any]: 统一结果字典。
    """

    client = build_default_client()
    return client.call_tool(
        "zotero_search_notes",
        {
            "query": query,
            "limit": limit,
        },
    )


if __name__ == "__main__":
    print(pull_items("causal inference", 5))
    print(pull_notes("identification", 5))
