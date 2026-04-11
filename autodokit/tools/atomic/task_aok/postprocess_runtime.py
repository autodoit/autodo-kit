"""AOK 统一事务节点后处理运行时工具。

本模块为 `autodokit.api.run_affair(...)` 提供轻量统一后处理能力：
1. 规范化事务执行结果为统一回执；
2. 对齐任务实例目录锚点；
3. 统一写入任务 ledger 与日志事件。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .git_snapshot_ledger import ledger_init, ledger_record_task_run
from .task_instance_dir import create_task_instance_dir
from ..log_aok.logdb import append_aok_log_event


def _now_iso() -> str:
    """返回当前时间字符串。

    Returns:
        str: ISO 时间字符串，秒级精度。
    """

    return datetime.now().isoformat(timespec="seconds")


def _extract_paths_from_result(execute_result: Any) -> list[Path]:
    """从事务返回值提取产物路径。

    Args:
        execute_result: 事务原始返回值，可能是 list[Path]、tuple、dict 或其他类型。

    Returns:
        list[Path]: 可解析出的路径列表。
    """

    if execute_result is None:
        return []
    if isinstance(execute_result, (str, Path)):
        return [Path(execute_result)]
    if isinstance(execute_result, dict):
        items = execute_result.get("artifact_paths") or execute_result.get("outputs") or []
        if isinstance(items, (str, Path)):
            return [Path(items)]
        if isinstance(items, list):
            return [Path(item) for item in items if item]
        return []
    if isinstance(execute_result, (list, tuple)):
        return [Path(item) for item in execute_result if item]
    return []


def _guess_task_uid_from_paths(paths: list[Path]) -> str:
    """尝试从产物路径推断 task_uid。

    Args:
        paths: 产物路径列表。

    Returns:
        str: 推断得到的 task_uid，若无法推断则返回空字符串。
    """

    for raw_path in paths:
        path = Path(raw_path)
        parts = [segment for segment in path.parts]
        for index, segment in enumerate(parts):
            if segment == "tasks" and index + 1 < len(parts):
                return str(parts[index + 1])
    return ""


def _resolve_task_anchor(
    workspace_root: Path,
    node_code: str,
    task_uid: str,
) -> tuple[str, Path]:
    """解析或创建任务目录锚点。

    Args:
        workspace_root: 工作区根路径。
        node_code: 节点代号。
        task_uid: 任务唯一标识，可为空。

    Returns:
        tuple[str, Path]: 规范化 task_uid 与任务目录路径。
    """

    if task_uid:
        task_instance_dir = workspace_root / "tasks" / task_uid
        if not task_instance_dir.exists():
            created_dir = create_task_instance_dir(
                workspace_root=workspace_root,
                node_code=node_code,
                task_uid=task_uid,
                manifest_extra={"created_by": "postprocess_runtime"},
            )
            return task_uid, created_dir
        return task_uid, task_instance_dir

    created_dir = create_task_instance_dir(
        workspace_root=workspace_root,
        node_code=node_code,
        task_uid=None,
        manifest_extra={"created_by": "postprocess_runtime"},
    )
    return created_dir.name, created_dir


def normalize_affair_receipt(
    *,
    affair_uid: str,
    node_code: str,
    workspace_root: Path,
    config_path: Path,
    execute_result: Any = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    """规范化事务执行结果。

    Args:
        affair_uid: 事务唯一标识。
        node_code: 节点代号。
        workspace_root: 工作区根路径。
        config_path: 配置文件路径。
        execute_result: 事务返回值。
        started_at: 事务开始时间。
        ended_at: 事务结束时间。
        error: 事务异常对象。

    Returns:
        dict[str, Any]: 统一回执结构。

    Examples:
        >>> payload = normalize_affair_receipt(
        ...     affair_uid="A020",
        ...     node_code="A020",
        ...     workspace_root=Path("."),
        ...     config_path=Path("cfg.json"),
        ... )
        >>> payload["node_code"]
        'A020'
    """

    artifact_paths = [path.resolve() for path in _extract_paths_from_result(execute_result)]

    task_uid = ""
    if isinstance(execute_result, dict):
        task_uid = str(
            execute_result.get("task_uid")
            or execute_result.get("aok_task_uid")
            or execute_result.get("task_instance_uid")
            or ""
        ).strip()
    if not task_uid:
        task_uid = _guess_task_uid_from_paths(artifact_paths)

    result_code = "PASS"
    status = "pass"
    error_message = ""
    if error is not None:
        result_code = "RETRYABLE_ERROR"
        status = "failed"
        error_message = str(error)

    resolved_started_at = started_at or _now_iso()
    resolved_ended_at = ended_at or _now_iso()

    normalized_task_uid, task_instance_dir = _resolve_task_anchor(
        workspace_root=workspace_root,
        node_code=node_code,
        task_uid=task_uid,
    )

    return {
        "result_code": result_code,
        "status": status,
        "decision_suggestion": "pass_next" if result_code == "PASS" else "retry_current",
        "task_uid": normalized_task_uid,
        "node_code": node_code,
        "affair_uid": affair_uid,
        "workspace_root": str(workspace_root),
        "config_path": str(config_path),
        "task_instance_dir": str(task_instance_dir.resolve()),
        "artifact_paths": [str(path) for path in artifact_paths],
        "gate_review_path": "",
        "started_at": resolved_started_at,
        "ended_at": resolved_ended_at,
        "error_type": type(error).__name__ if error is not None else "",
        "error_message": error_message,
        "payload": execute_result if isinstance(execute_result, dict) else {},
    }


def postprocess_affair_execution(
    *,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """执行统一后处理落账。

    Args:
        receipt: 统一回执。

    Returns:
        dict[str, Any]: 后处理结果摘要。

    Raises:
        ValueError: 当回执关键字段缺失时抛出。
    """

    workspace_root_raw = str(receipt.get("workspace_root") or "").strip()
    task_uid = str(receipt.get("task_uid") or "").strip()
    node_code = str(receipt.get("node_code") or "").strip()
    if not workspace_root_raw or not task_uid or not node_code:
        raise ValueError("receipt 缺少 workspace_root/task_uid/node_code")

    workspace_root = Path(workspace_root_raw).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    ledger_boot = ledger_init(workspace_root=workspace_root)

    input_summary = {
        "affair_uid": str(receipt.get("affair_uid") or ""),
        "config_path": str(receipt.get("config_path") or ""),
    }
    output_summary = {
        "result_code": str(receipt.get("result_code") or ""),
        "artifact_paths": receipt.get("artifact_paths") or [],
        "error_type": str(receipt.get("error_type") or ""),
        "error_message": str(receipt.get("error_message") or ""),
    }

    task_row = ledger_record_task_run(
        workspace_root=workspace_root,
        task_uid=task_uid,
        workflow_uid=str(receipt.get("affair_uid") or node_code),
        node_code=node_code,
        gate_code="",
        decision=str(receipt.get("decision_suggestion") or ""),
        status=str(receipt.get("status") or ""),
        input_summary_json=input_summary,
        output_summary_json=output_summary,
        started_at=str(receipt.get("started_at") or _now_iso()),
        ended_at=str(receipt.get("ended_at") or _now_iso()),
        operator_name="run_affair",
        note=str(receipt.get("error_message") or ""),
    )

    start_event = append_aok_log_event(
        event_type="affair_run_started",
        project_root=workspace_root,
        affair_code=node_code,
        level="info",
        reasoning_summary=f"{node_code} started",
        payload={
            "task_uid": task_uid,
            "started_at": str(receipt.get("started_at") or ""),
            "config_path": str(receipt.get("config_path") or ""),
        },
    )

    finish_level = "info" if str(receipt.get("result_code") or "") == "PASS" else "error"
    finish_event = append_aok_log_event(
        event_type="affair_run_finished",
        project_root=workspace_root,
        affair_code=node_code,
        level=finish_level,
        reasoning_summary=f"{node_code} finished with {receipt.get('result_code')}",
        payload={
            "task_uid": task_uid,
            "result_code": str(receipt.get("result_code") or ""),
            "decision_suggestion": str(receipt.get("decision_suggestion") or ""),
            "started_at": str(receipt.get("started_at") or ""),
            "ended_at": str(receipt.get("ended_at") or ""),
            "error_message": str(receipt.get("error_message") or ""),
            "artifact_paths": receipt.get("artifact_paths") or [],
        },
        artifact_paths=[Path(path) for path in (receipt.get("artifact_paths") or [])],
    )

    return {
        "status": "PASS",
        "ledger_boot": ledger_boot,
        "task_row": task_row,
        "start_event": start_event,
        "finish_event": finish_event,
        "task_uid": task_uid,
    }
