"""在线检索结果契约。"""

from __future__ import annotations

from typing import Any


def finalize_result(
    result: dict[str, Any],
    *,
    source: str,
    mode: str,
    action: str,
    request_profile: str,
) -> dict[str, Any]:
    """补全统一返回字段。

    Args:
        result: 原始结果。
        source: 来源。
        mode: 模式。
        action: 动作。
        request_profile: 请求画像。

    Returns:
        dict[str, Any]: 补全后的结果。
    """
    merged = dict(result)
    merged["source"] = merged.get("source") or source
    merged["mode"] = merged.get("mode") or mode
    merged["action"] = merged.get("action") or action
    merged["request_profile"] = merged.get("request_profile") or request_profile
    merged["status"] = str(merged.get("status") or "BLOCKED")
    return merged
