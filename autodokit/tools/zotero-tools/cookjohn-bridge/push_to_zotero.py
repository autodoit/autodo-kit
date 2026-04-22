"""cookjohn MCP 推送示例。

用于示范标签与元数据回写，后续可并入 AOK 事务调用层。
"""

from __future__ import annotations

from typing import Any

from mcp_http_client import build_default_client


def write_tags(item_key: str, tags: list[str], action: str = "add") -> dict[str, Any]:
    """写入或修改条目标签。

    Args:
        item_key: Zotero 条目 key。
        tags: 标签列表。
        action: `add/remove/set`。

    Returns:
        dict[str, Any]: 统一结果字典。

    Raises:
        ValueError: 当 action 非法时抛出。

    Examples:
        >>> write_tags("ABCD1234", ["A040/候选"], "add")
    """

    if action not in {"add", "remove", "set"}:
        raise ValueError("action 必须为 add/remove/set")

    client = build_default_client()
    return client.call_tool(
        "write_tag",
        {
            "action": action,
            "itemKey": item_key,
            "tags": tags,
        },
    )


def write_metadata(item_key: str, fields: dict[str, Any]) -> dict[str, Any]:
    """更新条目元数据。

    Args:
        item_key: Zotero 条目 key。
        fields: 字段字典，如 `{"title": "new title"}`。

    Returns:
        dict[str, Any]: 统一结果字典。

    Examples:
        >>> write_metadata("ABCD1234", {"title": "new title"})
    """

    client = build_default_client()
    return client.call_tool(
        "write_metadata",
        {
            "itemKey": item_key,
            "fields": fields,
        },
    )


if __name__ == "__main__":
    print(write_tags("DUMMYKEY", ["aok/test"], "add"))
    print(write_metadata("DUMMYKEY", {"title": "AOK metadata update demo"}))
