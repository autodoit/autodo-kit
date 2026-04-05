"""公开数据获取事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from autodokit.tools import load_json_or_py, write_affair_json_result


def plan_api_data_fetch(
    query: str,
    object_type: str = "dataset",
    source_type: str = "online",
    region_type: str = "global",
    access_type: str = "open",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """规划公开数据获取动作。

    Args:
        query: 数据需求描述。
        object_type: 对象类型。
        source_type: 来源类型。
        region_type: 区域类型。
        access_type: 访问类型。
        metadata: 附加元数据。

    Returns:
        结构化规划结果。
    """

    final_metadata = dict(metadata or {})
    request_uid = str(final_metadata.get("request_uid") or f"request-{uuid4().hex}")
    permission_status = "approved" if access_type == "open" else "manual_required"
    result_code = "PASS" if permission_status == "approved" else "BLOCKED"
    return {
        "status": "PASS" if result_code == "PASS" else "BLOCKED",
        "mode": "api-data-fetch",
        "result": {
            "request_uid": request_uid,
            "query": query,
            "object_type": object_type,
            "source_type": source_type,
            "region_type": region_type,
            "access_type": access_type,
            "permission_status": permission_status,
            "result_code": result_code,
            "plan": [
                {"step": 1, "action": "样本试拉", "goal": "确认字段和权限"},
                {"step": 2, "action": "批量拉取", "goal": "保存主数据文件"},
                {"step": 3, "action": "异常恢复", "goal": "断点续拉和失败记录"}
            ],
            "metadata": final_metadata,
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = plan_api_data_fetch(
        query=str(raw_cfg.get("query") or ""),
        object_type=str(raw_cfg.get("object_type") or "dataset"),
        source_type=str(raw_cfg.get("source_type") or "online"),
        region_type=str(raw_cfg.get("region_type") or "global"),
        access_type=str(raw_cfg.get("access_type") or "open"),
        metadata=dict(raw_cfg.get("metadata") or {}),
    )
    return write_affair_json_result(raw_cfg, config_path, "api_data_fetch_result.json", result)
