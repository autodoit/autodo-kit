"""cookjohn MCP 拉取示例。

用于示范如何从 Zotero 拉取条目与注释，后续可并入 AOK facade。
"""

from __future__ import annotations

from typing import Any

from mcp_http_client import build_default_client


def pull_items(query: str, limit: int = 20) -> dict[str, Any]:
    """拉取 Zotero 条目。

    Args:
        query: 搜索关键词。
        limit: 最大返回数量。

    Returns:
        dict[str, Any]: 统一结果字典。

    Examples:
        >>> pull_items("difference in differences", 10)
    """

    client = build_default_client()
    return client.call_tool("search_library", {"q": query, "limit": limit})


def pull_annotations(query: str, limit: int = 20) -> dict[str, Any]:
    """拉取 Zotero 批注。

    Args:
        query: 批注关键词。
        limit: 最大返回数量。

    Returns:
        dict[str, Any]: 统一结果字典。

    Examples:
        >>> pull_annotations("identification", 10)
    """

    client = build_default_client()
    return client.call_tool("search_annotations", {"q": query, "limit": limit})


if __name__ == "__main__":
    print(pull_items("machine learning", 5))
    print(pull_annotations("causal", 5))
