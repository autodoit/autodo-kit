"""Zotero 标签批量提取工具。

通过 cookjohn MCP (端口 23120) 从 Zotero 提取所有条目的标签，
去重统计后输出结构化结果或 JSONL 文件。

用法::

    from autodokit.tools.zotero_tools.cookjohn_bridge.extract_tags import extract_all_tags

    result = extract_all_tags()
    if result["ok"]:
        print(f"共发现 {len(result['data']['tags'])} 个标签")
"""

from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .mcp_http_client import CookjohnMcpConfig, CookjohnMcpHttpClient

_DEFAULT_ENDPOINT = "http://127.0.0.1:23120/mcp"
_CONCURRENCY = 20
_PAGE_LIMIT = 500


def _build_client(endpoint: str | None = None) -> CookjohnMcpHttpClient:
    """构造默认 MCP 客户端。"""
    return CookjohnMcpHttpClient(
        CookjohnMcpConfig(endpoint=endpoint or _DEFAULT_ENDPOINT)
    )


def _call_mcp_direct(endpoint: str, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
    """直接调用 MCP 工具并解析返回内容。

    Args:
        endpoint: MCP HTTP 端点。
        tool_name: 工具名。
        arguments: 工具参数。

    Returns:
        解析后的 data 内容，若失败返回 None。
    """
    client = _build_client(endpoint)
    result = client.call_tool(tool_name, arguments)
    if not result["ok"]:
        return None
    resp = result.get("data", {})
    if "result" in resp and "content" in resp["result"]:
        text = resp["result"]["content"][0].get("text", "")
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return resp


def get_all_item_keys(endpoint: str | None = None) -> list[str]:
    """分页获取 Zotero 库中所有条目的 key。

    Args:
        endpoint: MCP 端点，默认 http://127.0.0.1:23120/mcp。

    Returns:
        list[str]: 条目 key 列表。

    Examples:
        >>> keys = get_all_item_keys()
        >>> len(keys) > 0
        True
    """
    endpoint = endpoint or _DEFAULT_ENDPOINT
    all_keys: list[str] = []
    offset = 0
    total: int | None = None

    while True:
        resp = _call_mcp_direct(endpoint, "search_library", {
            "q": "", "limit": _PAGE_LIMIT, "offset": offset, "mode": "minimal"
        })
        if isinstance(resp, dict):
            pagination = resp.get("pagination", {})
            results = resp.get("results", [])
            if total is None:
                total = pagination.get("total", 0)
            keys = [r["key"] for r in results if "key" in r]
            all_keys.extend(keys)
            has_more = pagination.get("hasMore", False)
            if not has_more or not results:
                break
            offset += _PAGE_LIMIT
        else:
            break
    return all_keys


def _get_single_item_tags(endpoint: str, item_key: str) -> tuple[str, list[Any]]:
    """获取单个条目的标签。"""
    try:
        resp = _call_mcp_direct(endpoint, "get_item_details", {"itemKey": item_key})
        if isinstance(resp, dict):
            # cookjohn 返回格式一: tags 在顶层
            tags = resp.get("tags")
            if tags is not None:
                return item_key, tags if isinstance(tags, list) else []
            # cookjohn 返回格式二: tags 在 data 内
            data = resp.get("data")
            if isinstance(data, dict):
                tags = data.get("tags")
                if isinstance(tags, list):
                    return item_key, tags
        return item_key, []
    except Exception:  # noqa: BLE001
        return item_key, []


def extract_all_tags(
    endpoint: str | None = None,
    concurrency: int = _CONCURRENCY,
    progress_callback: Any = None,
) -> dict[str, Any]:
    """从 Zotero 提取所有标签，去重统计。

    Args:
        endpoint: MCP 端点，默认 http://127.0.0.1:23120/mcp。
        concurrency: 并发提取的线程数，默认 20。
        progress_callback: 可选进度回调函数，签名
            ``(done: int, total: int, tags_found: int) -> None``。

    Returns:
        dict[str, Any]: 统一结果字典，包含 ``ok``、``data``、``error`` 字段。
        ``data`` 结构::

            {
                "tags": [{"tag": str, "count": int, "type": str}, ...],
                "total_items": int,
                "total_tags": int,
                "auto_tag_count": int,
                "manual_tag_count": int,
                "elapsed_seconds": float
            }

    Examples:
        >>> result = extract_all_tags()
        >>> result["ok"]
        True
        >>> len(result["data"]["tags"]) > 0
        True
    """
    import time

    endpoint = endpoint or _DEFAULT_ENDPOINT
    t0 = time.time()

    # Step 1: 获取所有条目 key
    all_keys = get_all_item_keys(endpoint)
    if not all_keys:
        return {"ok": False, "data": {}, "error": "未获取到任何条目 key"}

    total_items = len(all_keys)

    # Step 2: 多线程批量获取标签
    all_tags: Counter[str] = Counter()
    done_count = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_map = {executor.submit(_get_single_item_tags, endpoint, key): key for key in all_keys}
        for future in as_completed(future_map):
            _item_key, tags = future.result()
            for tag in tags:
                if isinstance(tag, str):
                    all_tags[tag] += 1
                elif isinstance(tag, dict) and "tag" in tag:
                    all_tags[tag["tag"]] += 1
            done_count += 1
            if progress_callback is not None:
                progress_callback(done_count, total_items, len(all_tags))

    elapsed = time.time() - t0
    sorted_tags = all_tags.most_common()

    # 分类统计
    auto_count = sum(1 for t, _ in sorted_tags if t.startswith("/") or t.startswith("#"))
    manual_count = len(sorted_tags) - auto_count

    # 组装结构化结果
    tag_records: list[dict[str, Any]] = []
    for tag, count in sorted_tags:
        tag_type = "auto" if (tag.startswith("/") or tag.startswith("#")) else "manual"
        tag_records.append({"tag": tag, "count": count, "type": tag_type})

    return {
        "ok": True,
        "data": {
            "tags": tag_records,
            "total_items": total_items,
            "total_tags": len(sorted_tags),
            "auto_tag_count": auto_count,
            "manual_tag_count": manual_count,
            "elapsed_seconds": round(elapsed, 1),
        },
        "error": "",
    }


def save_tags_to_jsonl(
    output_path: str | Path,
    endpoint: str | None = None,
    concurrency: int = _CONCURRENCY,
) -> dict[str, Any]:
    """从 Zotero 提取标签并保存为 JSONL 文件。

    Args:
        output_path: 输出 JSONL 文件路径。
        endpoint: MCP 端点，默认 http://127.0.0.1:23120/mcp。
        concurrency: 并发提取线程数，默认 20。

    Returns:
        dict[str, Any]: 统一结果字典。成功时 ``data`` 包含 ``output_path`` 等字段。

    Examples:
        >>> result = save_tags_to_jsonl("/tmp/zotero_tags.jsonl")
        >>> result["ok"]
        True
    """
    extract_result = extract_all_tags(
        endpoint=endpoint, concurrency=concurrency
    )
    if not extract_result["ok"]:
        return extract_result

    data = extract_result["data"]
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as f:
        for record in data["tags"]:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "data": {
            "output_path": str(output.resolve()),
            "total_tags": data["total_tags"],
            "total_items": data["total_items"],
            "auto_tag_count": data["auto_tag_count"],
            "manual_tag_count": data["manual_tag_count"],
            "elapsed_seconds": data["elapsed_seconds"],
        },
        "error": "",
    }


if __name__ == "__main__":
    import sys

    output = sys.argv[1] if len(sys.argv) > 1 else "zotero_tags.jsonl"
    result = save_tags_to_jsonl(output)

    if result["ok"]:
        d = result["data"]
        print(f"✅ 标签提取完成！")
        print(f"   输出路径: {d['output_path']}")
        print(f"   条目总数: {d['total_items']}")
        print(f"   标签总数: {d['total_tags']} (自动 {d['auto_tag_count']}, 手动 {d['manual_tag_count']})")
        print(f"   耗时: {d['elapsed_seconds']}s")
    else:
        print(f"❌ 失败: {result['error']}")
        sys.exit(1)
