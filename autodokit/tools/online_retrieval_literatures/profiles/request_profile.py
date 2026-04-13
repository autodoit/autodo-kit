"""请求画像解析。"""

from __future__ import annotations

from typing import Any


def infer_request_profile(payload: dict[str, Any]) -> str:
    """推导请求画像。

    Returns:
        zh / en / mixed
    """
    explicit = str(payload.get("request_profile") or "").strip().lower()
    if explicit in {"zh", "cn", "chinese"}:
        return "zh"
    if explicit in {"en", "english"}:
        return "en"
    if explicit in {"mixed", "all", "both"}:
        return "mixed"

    source = str(payload.get("source") or "").strip().lower()
    if source == "zh_cnki":
        return "zh"
    if source in {"en_open_access", "open_platform"}:
        return "en"
    if source == "spis":
        return "mixed"
    if source in {"school_foreign_database_portal", "school_database_portal", "chaoxing_portal"}:
        return "en"
    return "mixed"
