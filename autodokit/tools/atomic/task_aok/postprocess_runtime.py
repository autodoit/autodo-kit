"""AOK 统一事务节点后处理运行时。

该模块负责在事务执行结束后，统一执行任务落账、日志留痕、
gate 摘要登记与可选 Git snapshot。
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Iterable

from autodokit.tools.atomic.log_aok.logdb import (
    append_aok_log_event,
    bootstrap_aok_logdb,
    record_aok_gate_review,
    resolve_aok_log_db_path,
)
from autodokit.tools.atomic.task_aok.git_snapshot_ledger import (
    git_create_snapshot_for_task,
    ledger_init,
    ledger_record_task_run,
)
from autodokit.tools.time_utils import now_compact, now_iso

_RESULT_PASS = {"pass", "ok", "success", "completed", "done"}
_RESULT_FAIL = {"fail", "error", "failed", "exception"}
_RESULT_BLOCKED = {"blocked", "pause", "paused", "stop", "stopped"}
_RESULT_HUMAN_GATE = {"human_gate", "human", "wait_human", "manual"}

_TRUE_VALUES = {"1", "true", "yes", "y", "on", "是"}
_FALSE_VALUES = {"0", "false", "no", "n", "off", "否"}
_DEFAULT_VALUES = {"", "default", "默认", "none", "null"}


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_tristate(value: Any) -> str:
    text = _to_text(value).lower()
    if text in _TRUE_VALUES:
        return "true"
    if text in _FALSE_VALUES:
        return "false"
    if text in _DEFAULT_VALUES:
        return "default"
    return "default"


def _resolve_policy(local_value: Any, global_value: Any, *, fallback: str) -> str:
    local_state = _parse_tristate(local_value)
    if local_state != "default":
        return local_state
    global_state = _parse_tristate(global_value)
    if global_state != "default":
        return global_state
    return fallback


def _extract_commit_value(cfg: dict[str, Any], key: str) -> Any:
    if key in cfg:
        return cfg.get(key)
    nested = cfg.get("git_commit")
    if isinstance(nested, dict) and key in nested:
        return nested.get(key)
    return None


def _resolve_workspace_root(config_path: Path, local_cfg: dict[str, Any], workspace_root: str | Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).expanduser().resolve()
    workspace_value = _to_text(local_cfg.get("workspace_root") or local_cfg.get("project_root"))
    if workspace_value:
        return Path(workspace_value).expanduser().resolve()
    if len(config_path.parents) >= 3 and config_path.parent.name == "affairs_config":
        return config_path.parents[2].resolve()
    return config_path.parent.resolve()


def _normalize_artifact_paths(result: Any) -> list[Path]:
    """归一化事务产物路径。

    Args:
        result: 事务返回值。

    Returns:
        解析出的产物路径列表。
    """

    if isinstance(result, Path):
        return [result]
    if isinstance(result, str) and result.strip():
        return [Path(result.strip())]
    if isinstance(result, dict):
        candidate_keys = [
            "artifact_paths",
            "artifacts",
            "outputs",
            "output_paths",
            "paths",
            "result_paths",
        ]
        collected: list[Path] = []
        for key in candidate_keys:
            raw = result.get(key)
            if isinstance(raw, (str, Path)):
                text = _to_text(raw)
                if text:
                    collected.append(Path(text))
            elif isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
                for item in raw:
                    text = _to_text(item)
                    if text:
                        collected.append(Path(text))
        return collected
    if not isinstance(result, Iterable) or isinstance(result, (str, bytes)):
        return []
    normalized: list[Path] = []
    for item in result:
        if isinstance(item, Path):
            normalized.append(item)
        elif isinstance(item, str) and item.strip():
            normalized.append(Path(item.strip()))
    return normalized


def _resolve_node_code(node_code: str | None, config_path: Path, local_cfg: dict[str, Any]) -> str:
    value = _to_text(node_code) or _to_text(local_cfg.get("node_code"))
    if value:
        return value
    stem = config_path.stem
    return stem if stem else "UNKNOWN"


def _resolve_task_uid(local_cfg: dict[str, Any], result: Any, node_code: str) -> str:
    if isinstance(result, dict):
        result_task_uid = _to_text(result.get("task_uid"))
        if result_task_uid:
            return result_task_uid
    cfg_task_uid = _to_text(local_cfg.get("task_uid"))
    if cfg_task_uid:
        return cfg_task_uid
    return f"{now_compact()}-{node_code}"


def _resolve_gate_review_path(result: Any, artifact_paths: list[Path], local_cfg: dict[str, Any]) -> str:
    if isinstance(result, dict):
        for key in ("gate_review_path", "gate_path", "review_path"):
            text = _to_text(result.get(key))
            if text:
                return text
    for candidate in artifact_paths:
        name = candidate.name.lower()
        if "gate" in name and "review" in name and candidate.suffix.lower() == ".json":
            return str(candidate)
    local_text = _to_text(local_cfg.get("gate_review_path"))
    if local_text:
        return local_text
    return ""


def _normalize_result_code(result: Any, execute_error: BaseException | None) -> tuple[str, str]:
    if execute_error is not None:
        return "FAIL", "fail"
    if isinstance(result, dict):
        raw_code = _to_text(result.get("result_code")).upper()
        if raw_code in {"PASS", "FAIL", "BLOCKED", "HUMAN_GATE", "RETRYABLE_ERROR"}:
            status = _to_text(result.get("status")).lower() or raw_code.lower()
            return raw_code, status
        raw_status = _to_text(result.get("status")).lower()
        if raw_status in _RESULT_PASS:
            return "PASS", raw_status
        if raw_status in _RESULT_FAIL:
            return "FAIL", raw_status
        if raw_status in _RESULT_BLOCKED:
            return "BLOCKED", raw_status
        if raw_status in _RESULT_HUMAN_GATE:
            return "HUMAN_GATE", raw_status
    return "PASS", "pass"


def _resolve_decision(result_code: str, result: Any) -> str:
    if isinstance(result, dict):
        suggestion = _to_text(result.get("decision_suggestion") or result.get("decision")).strip()
        if suggestion:
            return suggestion
    if result_code == "PASS":
        return "pass_next"
    if result_code == "HUMAN_GATE":
        return "pause_current"
    if result_code == "BLOCKED":
        return "stop_workflow"
    return "retry_current"


def _resolve_git_policy(local_cfg: dict[str, Any], global_cfg: dict[str, Any]) -> tuple[str, str]:
    local_auto = _extract_commit_value(local_cfg, "is_auto_git_commit")
    global_auto = _extract_commit_value(global_cfg, "is_auto_git_commit")
    resolved_auto = _resolve_policy(local_auto, global_auto, fallback="false")

    local_ask = _extract_commit_value(local_cfg, "自动提交前是否询问人类")
    global_ask = _extract_commit_value(global_cfg, "自动提交前是否询问人类")
    resolved_ask = _resolve_policy(local_ask, global_ask, fallback="false")
    return resolved_auto, resolved_ask


def _confirm_from_human(node_code: str, task_uid: str) -> bool:
    if not sys.stdin or not sys.stdin.isatty():
        return False
    prompt = f"[{node_code}] 检测到自动提交策略且要求人工确认，是否提交 {task_uid}? [y/N]: "
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return _to_text(answer).lower() in _TRUE_VALUES


def _load_gate_payload(gate_review_path: str) -> dict[str, Any]:
    if not gate_review_path:
        return {}
    path = Path(gate_review_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_receipt(
    *,
    node_code: str,
    workspace_root: Path,
    task_uid: str,
    result_code: str,
    status: str,
    decision_suggestion: str,
    artifact_paths: list[Path],
    gate_review_path: str,
    started_at: str,
    ended_at: str,
    execute_result: Any,
    execute_error: BaseException | None,
) -> dict[str, Any]:
    return {
        "result_code": result_code,
        "status": status,
        "task_uid": task_uid,
        "node_code": node_code,
        "workspace_root": str(workspace_root),
        "artifact_paths": [str(path) for path in artifact_paths],
        "gate_review_path": gate_review_path,
        "decision_suggestion": decision_suggestion,
        "started_at": started_at,
        "ended_at": ended_at,
        "error_type": execute_error.__class__.__name__ if execute_error else "",
        "error_message": _to_text(execute_error) if execute_error else "",
        "payload": execute_result if isinstance(execute_result, dict) else {},
    }


def _run_task_and_log_records(
    *,
    receipt: dict[str, Any],
    config_path: Path,
    local_cfg: dict[str, Any],
    global_cfg: dict[str, Any],
    gate_payload: dict[str, Any],
) -> dict[str, Any]:
    workspace_root = Path(receipt["workspace_root"]).resolve()
    task_uid = _to_text(receipt.get("task_uid"))
    node_code = _to_text(receipt.get("node_code"))
    workflow_uid = _to_text(global_cfg.get("workflow_name") or global_cfg.get("task") or "academic-workflow")

    path_cfg = global_cfg.get("paths") if isinstance(global_cfg.get("paths"), dict) else {}
    tasks_db_path = _to_text(path_cfg.get("tasks_db_path")) or None
    log_db_path = _to_text(path_cfg.get("log_db_path")) or None

    ledger_init(workspace_root=workspace_root, ledger_db_path=tasks_db_path)
    bootstrap_aok_logdb(project_root=workspace_root, log_db_path=log_db_path)

    append_aok_log_event(
        event_type="node_postprocess_start",
        project_root=workspace_root,
        log_db_path=log_db_path,
        level="info",
        handler_kind="aok_postprocess",
        handler_name="postprocess_runtime",
        affair_code=node_code,
        reasoning_summary=f"{node_code} 后处理开始",
        payload={
            "task_uid": task_uid,
            "config_path": str(config_path),
            "result_code": receipt.get("result_code"),
            "started_at": receipt.get("started_at"),
        },
    )

    ledger_row = ledger_record_task_run(
        workspace_root=workspace_root,
        task_uid=task_uid,
        workflow_uid=workflow_uid,
        node_code=node_code,
        gate_code="POST_RUN",
        decision=_to_text(receipt.get("decision_suggestion")) or "pass_next",
        status=_to_text(receipt.get("status")) or "pass",
        input_summary_json={"config_path": str(config_path), "node_code": node_code},
        output_summary_json={
            "result_code": receipt.get("result_code"),
            "artifact_count": len(receipt.get("artifact_paths") or []),
            "gate_review_path": receipt.get("gate_review_path"),
        },
        started_at=_to_text(receipt.get("started_at")) or now_iso(),
        ended_at=_to_text(receipt.get("ended_at")) or now_iso(),
        operator_name="aok_postprocess",
        note=_to_text(receipt.get("error_message")),
        ledger_db_path=tasks_db_path,
    )

    if gate_payload:
        gate_code = _to_text(gate_payload.get("gate_uid") or gate_payload.get("gate_code") or f"G-{node_code}")
        record_aok_gate_review(
            gate_code=gate_code,
            project_root=workspace_root,
            log_db_path=log_db_path,
            affair_code=node_code,
            reviewer_agent="aok_postprocess",
            review_summary=_to_text(gate_payload.get("summary")) or _to_text(gate_payload.get("conclusion")),
            decision_candidates=[_to_text(gate_payload.get("recommendation"))],
            payload=gate_payload,
        )

    append_aok_log_event(
        event_type="node_postprocess_end",
        project_root=workspace_root,
        log_db_path=log_db_path,
        level="info" if _to_text(receipt.get("result_code")) == "PASS" else "warning",
        handler_kind="aok_postprocess",
        handler_name="postprocess_runtime",
        affair_code=node_code,
        artifact_paths=receipt.get("artifact_paths") or [],
        gate_review_path=_to_text(receipt.get("gate_review_path")) or None,
        reasoning_summary=f"{node_code} 后处理完成",
        payload={
            "task_uid": task_uid,
            "result_code": receipt.get("result_code"),
            "decision": receipt.get("decision_suggestion"),
            "ended_at": receipt.get("ended_at"),
            "log_db_path": str(resolve_aok_log_db_path(workspace_root, config_path=workspace_root / "config" / "config.json")),
        },
        gate_review=gate_payload if gate_payload else None,
    )

    return {
        "ledger_record": ledger_row,
        "tasks_db_path": tasks_db_path,
        "log_db_path": log_db_path,
        "resolved_workspace_root": str(workspace_root),
    }


def normalize_affair_receipt(
    *,
    config_path: str | Path,
    node_code: str | None,
    execute_result: Any,
    execute_error: BaseException | None,
    workspace_root: str | Path | None,
    started_at: str | None,
    ended_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """规范化事务执行回执。

    Args:
        config_path: 事务配置路径。
        node_code: 节点代号。
        execute_result: 事务返回值。
        execute_error: 事务异常对象。
        workspace_root: 可选工作区根目录。
        started_at: 开始时间。
        ended_at: 结束时间。

    Returns:
        tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
            依次为标准回执、局部配置、全局配置。
    """

    resolved_config_path = Path(config_path).expanduser().resolve()
    local_cfg = _read_json_file(resolved_config_path)
    resolved_workspace_root = _resolve_workspace_root(resolved_config_path, local_cfg, workspace_root)
    global_cfg = _read_json_file(resolved_workspace_root / "config" / "config.json")

    resolved_node_code = _resolve_node_code(node_code=node_code, config_path=resolved_config_path, local_cfg=local_cfg)
    artifact_paths = _normalize_artifact_paths(execute_result)
    gate_review_path = _resolve_gate_review_path(execute_result, artifact_paths, local_cfg)
    result_code, normalized_status = _normalize_result_code(execute_result, execute_error)
    task_uid = _resolve_task_uid(local_cfg, execute_result, resolved_node_code)
    decision = _resolve_decision(result_code, execute_result)

    receipt = _build_receipt(
        node_code=resolved_node_code,
        workspace_root=resolved_workspace_root,
        task_uid=task_uid,
        result_code=result_code,
        status=normalized_status,
        decision_suggestion=decision,
        artifact_paths=artifact_paths,
        gate_review_path=gate_review_path,
        started_at=_to_text(started_at) or now_iso(),
        ended_at=_to_text(ended_at) or now_iso(),
        execute_result=execute_result,
        execute_error=execute_error,
    )
    return receipt, local_cfg, global_cfg


def run_unified_postprocess(
    *,
    config_path: str | Path,
    node_code: str | None,
    execute_result: Any,
    execute_error: BaseException | None = None,
    workspace_root: str | Path | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> dict[str, Any]:
    """执行统一事务后处理并返回标准回执。

    Args:
        config_path: 事务配置路径。
        node_code: 节点代号。
        execute_result: 事务返回值。
        execute_error: 可选异常对象。
        workspace_root: 可选工作区根目录。
        started_at: 可选开始时间。
        ended_at: 可选结束时间。

    Returns:
        dict[str, Any]: 包含标准回执与后处理元信息。
    """

    receipt, local_cfg, global_cfg = normalize_affair_receipt(
        config_path=config_path,
        node_code=node_code,
        execute_result=execute_result,
        execute_error=execute_error,
        workspace_root=workspace_root,
        started_at=started_at,
        ended_at=ended_at,
    )

    resolved_config_path = Path(config_path).expanduser().resolve()
    gate_payload = _load_gate_payload(_to_text(receipt.get("gate_review_path")))
    post_meta = _run_task_and_log_records(
        receipt=receipt,
        config_path=resolved_config_path,
        local_cfg=local_cfg,
        global_cfg=global_cfg,
        gate_payload=gate_payload,
    )

    resolved_auto, resolved_ask = _resolve_git_policy(local_cfg, global_cfg)
    git_snapshot: dict[str, Any] | None = None
    if resolved_auto == "true" and _to_text(receipt.get("result_code")) == "PASS":
        allow_commit = True
        if resolved_ask == "true":
            allow_commit = _confirm_from_human(_to_text(receipt.get("node_code")), _to_text(receipt.get("task_uid")))
        if allow_commit:
            workflow_uid = _to_text(global_cfg.get("workflow_name") or global_cfg.get("task") or "academic-workflow")
            message = f"{_to_text(receipt.get('node_code'))}-{_to_text(receipt.get('task_uid'))}"
            git_snapshot = git_create_snapshot_for_task(
                workspace_root=receipt["workspace_root"],
                task_uid=_to_text(receipt.get("task_uid")),
                workflow_uid=workflow_uid,
                node_code=_to_text(receipt.get("node_code")),
                gate_code="POST_RUN",
                commit_message=message,
                tag_name=f"aok/task/{_to_text(receipt.get('task_uid'))}",
                includes_attachments=True,
                ledger_db_path=post_meta.get("tasks_db_path") or None,
            )

    return {
        **receipt,
        "postprocess": {
            "mode": "unified",
            "config_path": str(resolved_config_path),
            **post_meta,
            "git_snapshot": git_snapshot or {},
        },
    }
