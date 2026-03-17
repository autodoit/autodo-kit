"""单轮调度派发事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_dispatch_map, load_json_or_py, write_affair_json_result


def run_scheduler_affair(
    task_uid: str,
    goal: str,
    payload: dict[str, Any],
    project_root: str | Path = ".",
    current_transaction_uid: str | None = None,
) -> dict[str, Any]:
    """执行简化版单轮调度。"""

    root = Path(project_root).resolve()
    dispatch_map = load_dispatch_map(root)
    dispatch_key = str(payload.get("dispatch_key") or ("dataset_search" if payload.get("object_type") == "dataset" else "literature_search"))
    target = dispatch_map.get(dispatch_key) or {"kind": "placeholder", "target": dispatch_key}
    selected_transaction_uid = str(target.get("target") or dispatch_key)
    return {
        "status": "PASS" if selected_transaction_uid else "BLOCKED",
        "mode": "scheduler-dispatch",
        "project_root": str(root),
        "selected_transaction_uid": selected_transaction_uid,
        "event": {
            "task_uid": task_uid,
            "goal": goal,
            "current_transaction_uid": current_transaction_uid or "",
            "dispatch_key": dispatch_key,
            "target": selected_transaction_uid,
            "payload": payload,
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = run_scheduler_affair(
        task_uid=str(raw_cfg.get("task_uid") or ""),
        goal=str(raw_cfg.get("goal") or ""),
        payload=dict(raw_cfg.get("payload") or {}),
        project_root=str(raw_cfg.get("project_root") or "."),
        current_transaction_uid=raw_cfg.get("current_transaction_uid"),
    )
    return write_affair_json_result(raw_cfg, config_path, "scheduler_dispatch_result.json", result)
