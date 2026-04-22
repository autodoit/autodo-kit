"""54yyyu MCP 写入示例。"""

from __future__ import annotations

from typing import Any

from mcp_http_client import build_default_client


def add_by_doi(doi: str, tags: list[str] | None = None) -> dict[str, Any]:
    """按 DOI 写入 Zotero。

    Args:
        doi: DOI 字符串。
        tags: 可选标签。

    Returns:
        dict[str, Any]: 统一结果字典。

    Examples:
        >>> add_by_doi("10.1038/nature14539", ["A040/seed"])
    """

    client = build_default_client()
    return client.call_tool(
        "zotero_add_by_doi",
        {
            "doi": doi,
            "tags": tags or [],
        },
    )


def update_item_title(item_key: str, title: str) -> dict[str, Any]:
    """更新 Zotero 条目标题。

    Args:
        item_key: 条目 key。
        title: 新标题。

    Returns:
        dict[str, Any]: 统一结果字典。
    """

    client = build_default_client()
    return client.call_tool(
        "zotero_update_item",
        {
            "item_key": item_key,
            "title": title,
        },
    )


if __name__ == "__main__":
    print(add_by_doi("10.1038/nature14539", ["aok/demo"]))
    print(update_item_title("DUMMYKEY", "AOK update demo"))
