"""CNKI 事务共用的轻量结果构造工具。"""

from __future__ import annotations

from typing import Any


def build_cnki_result(
    *,
    mode: str,
    access_type: str,
    payload: dict[str, Any],
    next_node: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 CNKI 事务统一结果。

    Args:
        mode: 技能模式名。
        access_type: 访问类型。
        payload: 业务结果负载。
        next_node: 推荐后续节点。
        metadata: 附加元数据。

    Returns:
        统一结构结果。
    """

    manual_approved = bool((metadata or {}).get("manual_approved", False))
    permission_status = "approved" if access_type == "open" or manual_approved else "manual_required"
    result_code = "PASS" if permission_status == "approved" else "BLOCKED"
    return {
        "mode": mode,
        "governance_result": {
            "bundle": {
                "result_code": result_code,
                "permission_status": permission_status,
                "access_type": access_type,
            }
        },
        "next_node": next_node,
        "payload": payload,
        "metadata": dict(metadata or {}),
    }
