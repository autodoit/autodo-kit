"""事务请求登记与执行工具。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
from uuid import uuid4

from autodokit.path_compat import resolve_portable_path
from autodokit.tools.config_contract_utils import export_to_chinese_contract, normalize_to_legacy_contract
from autodokit.tools.atomic.task_aok.git_snapshot_ledger import (
    AFFAIR_REQUEST_TABLE_NAME,
    ledger_init,
    ledger_record_affair_request,
)
from autodokit.tools.time_utils import now_iso


SUPPORTED_TARGET_NODES = {"A020", "A040", "A050", "A060", "A070"}
DEFAULT_REQUEST_TYPE_BY_NODE = {
    "A020": "import_preprocess",
    "A040": "retrieval",
    "A050": "download_fulltext",
    "A060": "preprocess_priority",
    "A070": "unified_preprocess",
}
PENDING_REQUEST_STATUSES = {"pending", "待分发", "dispatched", "已分发"}
RUNNING_REQUEST_STATUSES = {"running", "运行中"}
COMPLETED_REQUEST_STATUSES = {"completed", "已完成", "succeeded", "成功"}
FAILED_REQUEST_STATUSES = {"failed", "失败"}


def _stringify(value: Any) -> str:
    return str(value or "").strip()


def _normalize_enum_value(key: str, value: Any, default: str = "") -> str:
    normalized = normalize_to_legacy_contract({key: value})
    if isinstance(normalized, dict):
        text = _stringify(normalized.get(key))
        if text:
            return text
    return _stringify(default)


def _resolve_workspace_root(workspace_root: str | Path) -> Path:
    return resolve_portable_path(workspace_root, base=Path.cwd())


def _resolve_tasks_db_path(workspace_root: Path, tasks_db_path: str | Path | None = None) -> Path:
    if tasks_db_path is None:
        return workspace_root / "database" / "tasks" / "tasks.db"
    return resolve_portable_path(tasks_db_path, base=workspace_root)


def _resolve_registry_path(workspace_root: Path, registry_path: str | Path | None = None) -> Path:
    if registry_path is None:
        return workspace_root / "config" / "affair_entry_registry.json"
    return resolve_portable_path(registry_path, base=workspace_root)


def _read_json_file(path: str | Path) -> Any:
    resolved = Path(path).expanduser().resolve()
    return normalize_to_legacy_contract(json.loads(resolved.read_text(encoding="utf-8-sig")))


def _connect_tasks_db(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    return connection


def _normalize_node_code(target_node: str) -> str:
    normalized = _stringify(target_node).upper()
    if normalized not in SUPPORTED_TARGET_NODES:
        raise ValueError(f"暂不支持的事务请求目标节点: {target_node}")
    return normalized


def _build_request_uid(target_node: str) -> str:
    return f"req-{_normalize_node_code(target_node).lower()}-{uuid4().hex[:12]}"


def _build_idempotency_key(payload: Dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _row_to_request_dict(row: sqlite3.Row | None) -> Dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    return {
        "request_uid": item.get("uid_请求", ""),
        "uid_请求": item.get("uid_请求", ""),
        "request_type": item.get("请求类型", ""),
        "target_node": item.get("目标节点", ""),
        "request_status": item.get("请求状态", ""),
        "source_node": item.get("来源节点", ""),
        "source_task_uid": item.get("来源任务UID", ""),
        "source_literature_uid": item.get("来源文献UID", ""),
        "source_cite_key": item.get("来源cite_key", ""),
        "reason_code": item.get("请求原因码", ""),
        "reason_text": item.get("请求原因", ""),
        "payload_path": item.get("请求负载路径", ""),
        "result_summary_path": item.get("结果摘要路径", ""),
        "target_task_uid": item.get("uid_目标任务", ""),
        "priority": item.get("优先级", ""),
        "idempotency_key": item.get("幂等键", ""),
        "decision_status": item.get("决策状态", ""),
        "decision_uid": item.get("uid_决策", ""),
        "attribute_vector_json": item.get("属性向量JSON", "{}"),
        "created_at": item.get("创建时间", ""),
        "dispatched_at": item.get("分发时间", ""),
        "completed_at": item.get("完成时间", ""),
        "creator_type": item.get("创建器类型", ""),
        "creator_id": item.get("创建器标识", ""),
    }


def _load_request_row_by_uid(tasks_db_path: Path, request_uid: str) -> Dict[str, Any] | None:
    with _connect_tasks_db(tasks_db_path) as connection:
        row = connection.execute(
            f'SELECT * FROM "{AFFAIR_REQUEST_TABLE_NAME}" WHERE uid_请求 = ?',
            (_stringify(request_uid),),
        ).fetchone()
    return _row_to_request_dict(row)


def _load_request_row_by_idempotency_key(tasks_db_path: Path, idempotency_key: str) -> Dict[str, Any] | None:
    normalized = _stringify(idempotency_key)
    if not normalized:
        return None
    with _connect_tasks_db(tasks_db_path) as connection:
        row = connection.execute(
            f'SELECT * FROM "{AFFAIR_REQUEST_TABLE_NAME}" WHERE 幂等键 = ? ORDER BY 创建时间 DESC, uid_请求 DESC LIMIT 1',
            (normalized,),
        ).fetchone()
    return _row_to_request_dict(row)


def _iter_pending_request_rows(
    tasks_db_path: Path,
    *,
    target_nodes: Sequence[str] | None = None,
    limit: int | None = None,
) -> List[Dict[str, Any]]:
    normalized_nodes = [_normalize_node_code(item) for item in list(target_nodes or []) if _stringify(item)]
    status_values = sorted(PENDING_REQUEST_STATUSES | RUNNING_REQUEST_STATUSES)
    status_placeholders = ", ".join("?" for _ in status_values)
    params: List[Any] = list(status_values)
    sql = (
        f'SELECT * FROM "{AFFAIR_REQUEST_TABLE_NAME}" '
        f'WHERE lower(请求状态) IN ({status_placeholders})'
    )
    if normalized_nodes:
        node_placeholders = ", ".join("?" for _ in normalized_nodes)
        sql += f" AND 目标节点 IN ({node_placeholders})"
        params.extend(normalized_nodes)
    sql += " ORDER BY 创建时间 ASC, uid_请求 ASC"
    if isinstance(limit, int) and limit > 0:
        sql += f" LIMIT {int(limit)}"
    with _connect_tasks_db(tasks_db_path) as connection:
        rows = connection.execute(sql, tuple(params)).fetchall()
    return [_row_to_request_dict(row) for row in rows if row is not None]


def _build_standard_a040_payload_from_feedback_request(
    feedback_request: Dict[str, Any],
    *,
    request_uid: str,
    source_node: str,
) -> Dict[str, Any]:
    mapping_result = dict(feedback_request.get("mapping_result") or {})
    reference_lines = list(feedback_request.get("reference_lines") or [])
    preferred_sources = list(feedback_request.get("preferred_sources") or [])
    seed_items = list(feedback_request.get("seed_items") or [])
    reason_text = _stringify(feedback_request.get("retrieval_reason")) or "阅读回流触发 A040 补检"
    reason_code = "reading_feedback"
    if _stringify(mapping_result.get("parse_failure_reason")):
        reason_code = "parse_failed"
    elif not _stringify(mapping_result.get("matched_uid_literature")):
        reason_code = "no_match"
    elif bool(feedback_request.get("need_fulltext", False)):
        reason_code = "missing_fulltext"

    return {
        "request_uid": request_uid,
        "request_type": DEFAULT_REQUEST_TYPE_BY_NODE["A040"],
        "target_node": "A040",
        "caller": {
            "source_node": _stringify(source_node),
            "source_stage": _stringify(feedback_request.get("source_stage")),
            "source_task_uid": _stringify(feedback_request.get("source_task_uid")),
            "source_uid_literature": _stringify(feedback_request.get("source_uid_literature")),
            "source_cite_key": _stringify(feedback_request.get("source_cite_key")),
            "source_note_path": _stringify(feedback_request.get("source_note_path")),
            "trigger_mode": "auto",
        },
        "business_payload": {
            "query": "",
            "keyword_list": [],
            "reference_lines": reference_lines,
            "seed_items": seed_items,
            "preferred_sources": preferred_sources,
            "need_fulltext": bool(feedback_request.get("need_fulltext", False)),
            "need_metadata_completion": bool(feedback_request.get("need_metadata_completion", False)),
            "mapping_result": mapping_result,
            "raw_feedback_request": dict(feedback_request),
        },
        "reason": {
            "code": reason_code,
            "message": reason_text,
        },
        "routing_contract": {
            "write_back_to": {
                "tasks_db": True,
                "log_db": True,
                "content_db": True,
            },
            "callback": {
                "source_node": _stringify(source_node),
                "source_task_uid": _stringify(feedback_request.get("source_task_uid")),
                "resume_policy": "manual_or_scheduler",
            },
            "next_suggested_node": "A050" if bool(feedback_request.get("need_fulltext", False)) else "A040",
        },
    }


def _deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(dict(merged.get(key) or {}), value)
        else:
            merged[key] = value
    return merged


def _merge_seed_items(base_items: Iterable[Any], extra_items: Iterable[Any]) -> List[Any]:
    results: List[Any] = []
    seen: set[str] = set()
    for item in [*list(base_items or []), *list(extra_items or [])]:
        if isinstance(item, dict):
            identity = "|".join(
                [
                    _stringify(item.get("uid_literature")),
                    _stringify(item.get("cite_key")),
                    _stringify(item.get("title")),
                    _stringify(item.get("detail_url")),
                ]
            ).lower()
        else:
            identity = _stringify(item).lower()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        results.append(item)
    return results


def _apply_a040_request_business_payload(runtime_cfg: Dict[str, Any], business_payload: Dict[str, Any]) -> Dict[str, Any]:
    updated = dict(runtime_cfg)
    raw_feedback_request = business_payload.get("raw_feedback_request")
    if isinstance(raw_feedback_request, dict):
        updated["retrieval_feedback_requests"] = [raw_feedback_request]

    preferred_sources = [
        _stringify(item)
        for item in list(business_payload.get("preferred_sources") or [])
        if _stringify(item)
    ]
    if preferred_sources:
        updated["online_sources"] = preferred_sources

    seed_items = _merge_seed_items(updated.get("seed_items") or [], business_payload.get("seed_items") or [])
    if seed_items:
        updated["seed_items"] = seed_items

    reference_lines = [
        _stringify(item)
        for item in list(business_payload.get("reference_lines") or [])
        if _stringify(item)
    ]
    if not _stringify(updated.get("query")) and reference_lines:
        updated["query"] = reference_lines[0][:300]
    if not list(updated.get("keyword_list") or []) and reference_lines:
        updated["keyword_list"] = [reference_lines[0][:120]]

    if raw_feedback_request or preferred_sources or seed_items:
        updated["enable_online_retrieval"] = True
        updated["online_trigger_policy"] = _normalize_enum_value(
            "online_trigger_policy",
            business_payload.get("online_trigger_policy")
            or updated.get("online_trigger_policy")
            or "仅缺口触发",
            default="gap_only",
        )
    return updated


def _apply_a045_request_business_payload(runtime_cfg: Dict[str, Any], business_payload: Dict[str, Any]) -> Dict[str, Any]:
    updated = dict(runtime_cfg)
    preferred_sources = [
        _stringify(item)
        for item in list(business_payload.get("preferred_sources") or [])
        if _stringify(item)
    ]
    if preferred_sources:
        updated["online_sources"] = preferred_sources
    seed_items = _merge_seed_items(updated.get("seed_items") or [], business_payload.get("seed_items") or [])
    if seed_items:
        updated["seed_items"] = seed_items
    if seed_items or _stringify(updated.get("query")) or list(updated.get("keyword_list") or []):
        updated["enable_online_retrieval"] = True
    if not _stringify(updated.get("online_trigger_policy")):
        updated["online_trigger_policy"] = _normalize_enum_value("online_trigger_policy", "仅人工种子触发", default="manual_seed_only")
    if not _stringify(updated.get("online_acquisition_mode")):
        updated["online_acquisition_mode"] = _normalize_enum_value("online_acquisition_mode", "下载PDF", default="download_pdf")
    return updated


def _apply_a020_request_business_payload(runtime_cfg: Dict[str, Any], business_payload: Dict[str, Any]) -> Dict[str, Any]:
    updated = dict(runtime_cfg)
    updated["node_code"] = "A020"
    return updated


def _apply_a050_request_business_payload(runtime_cfg: Dict[str, Any], business_payload: Dict[str, Any]) -> Dict[str, Any]:
    updated = dict(runtime_cfg)
    profile = _normalize_enum_value("profile", business_payload.get("profile") or updated.get("profile") or "混合", default="mixed").lower()
    updated["profile"] = profile or "mixed"
    updated["node_code"] = "A060"
    updated["execution_mode"] = _normalize_enum_value("execution_mode", "仅生成优先级", default="priority_only")
    return updated


def _apply_a055_request_business_payload(runtime_cfg: Dict[str, Any], business_payload: Dict[str, Any]) -> Dict[str, Any]:
    updated = dict(runtime_cfg)
    profile = _normalize_enum_value("profile", business_payload.get("profile") or updated.get("profile") or "混合", default="mixed").lower()
    updated["profile"] = profile or "mixed"
    updated["node_code"] = "A070"
    updated["execution_mode"] = _normalize_enum_value("execution_mode", "执行完整预处理", default="full_preprocess")
    return updated


def register_affair_request(
    *,
    workspace_root: str | Path,
    target_node: str,
    payload: Dict[str, Any],
    priority: str = "中",
    creator_type: str = "tool",
    creator_id: str = "affair_request_bus",
    attribute_vector: Dict[str, Any] | None = None,
    tasks_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    workspace = _resolve_workspace_root(workspace_root)
    normalized_target_node = _normalize_node_code(target_node)
    resolved_tasks_db = _resolve_tasks_db_path(workspace, tasks_db_path)
    ledger_init(workspace_root=workspace, ledger_db_path=resolved_tasks_db)

    resolved_payload = dict(payload or {})
    request_uid = _stringify(resolved_payload.get("request_uid")) or _build_request_uid(normalized_target_node)
    resolved_payload.setdefault("request_uid", request_uid)
    resolved_payload.setdefault("target_node", normalized_target_node)
    resolved_payload.setdefault("request_type", DEFAULT_REQUEST_TYPE_BY_NODE[normalized_target_node])

    idempotency_key = _build_idempotency_key(resolved_payload)
    existing = _load_request_row_by_idempotency_key(resolved_tasks_db, idempotency_key)
    if existing and _stringify(existing.get("request_status")).lower() not in FAILED_REQUEST_STATUSES:
        payload_path = Path(_stringify(existing.get("payload_path")))
        request_dir = payload_path.parent if _stringify(existing.get("payload_path")) else workspace / "tasks" / "requests" / _stringify(existing.get("request_uid"))
        return {
            **existing,
            "request_dir": str(request_dir),
            "request_readable_path": str(request_dir / "request_readable.md"),
            "deduplicated": True,
        }

    request_dir = workspace / "tasks" / "requests" / request_uid
    request_dir.mkdir(parents=True, exist_ok=True)

    payload_path = request_dir / "payload.json"
    readable_path = request_dir / "request_readable.md"
    dispatch_path = request_dir / "dispatch_result.json"

    payload_path.write_text(json.dumps(resolved_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    readable_path.write_text(
        "\n".join(
            [
                f"# 事务请求-{request_uid}",
                "",
                f"- 目标节点: {normalized_target_node}",
                f"- 请求类型: {_stringify(resolved_payload.get('request_type'))}",
                f"- 来源节点: {_stringify((resolved_payload.get('caller') or {}).get('source_node'))}",
                f"- 来源任务UID: {_stringify((resolved_payload.get('caller') or {}).get('source_task_uid'))}",
                f"- 请求原因码: {_stringify((resolved_payload.get('reason') or {}).get('code'))}",
                f"- 请求原因: {_stringify((resolved_payload.get('reason') or {}).get('message'))}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    caller = dict(resolved_payload.get("caller") or {})
    reason = dict(resolved_payload.get("reason") or {})
    record = ledger_record_affair_request(
        workspace_root=workspace,
        request_uid=request_uid,
        request_type=_stringify(resolved_payload.get("request_type")) or DEFAULT_REQUEST_TYPE_BY_NODE[normalized_target_node],
        target_node=normalized_target_node,
        request_status="待分发",
        source_node=_stringify(caller.get("source_node")),
        source_task_uid=_stringify(caller.get("source_task_uid")),
        source_literature_uid=_stringify(caller.get("source_uid_literature")),
        source_cite_key=_stringify(caller.get("source_cite_key")),
        reason_code=_stringify(reason.get("code")),
        reason_text=_stringify(reason.get("message")),
        payload_path=str(payload_path),
        result_summary_path=str(dispatch_path),
        priority=_stringify(priority) or "中",
        idempotency_key=idempotency_key,
        decision_status="正常",
        attribute_vector_json=attribute_vector or {},
        creator_type=_stringify(creator_type),
        creator_id=_stringify(creator_id),
        ledger_db_path=resolved_tasks_db,
    )

    dispatch_path.write_text(
        json.dumps(
            {
                "status": "REGISTERED",
                "request_uid": request_uid,
                "target_node": normalized_target_node,
                "payload_path": str(payload_path),
                "tasks_db_path": str(resolved_tasks_db),
                "idempotency_key": idempotency_key,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        **record,
        "request_dir": str(request_dir),
        "request_readable_path": str(readable_path),
        "deduplicated": False,
    }


def register_a040_retrieval_request(
    *,
    workspace_root: str | Path,
    payload: Dict[str, Any] | None = None,
    feedback_request: Dict[str, Any] | None = None,
    source_node: str = "A150",
    priority: str = "中",
    creator_type: str = "tool",
    creator_id: str = "affair_request_bus",
    attribute_vector: Dict[str, Any] | None = None,
    tasks_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    request_uid = _build_request_uid("A040")
    resolved_payload = dict(payload or {})
    if not resolved_payload:
        if not isinstance(feedback_request, dict):
            raise ValueError("payload 与 feedback_request 至少需要提供一个")
        resolved_payload = _build_standard_a040_payload_from_feedback_request(
            feedback_request,
            request_uid=request_uid,
            source_node=source_node,
        )
    else:
        resolved_payload.setdefault("request_uid", request_uid)
        resolved_payload.setdefault("request_type", DEFAULT_REQUEST_TYPE_BY_NODE["A040"])
        resolved_payload.setdefault("target_node", "A040")

    return register_affair_request(
        workspace_root=workspace_root,
        target_node="A040",
        payload=resolved_payload,
        priority=priority,
        creator_type=creator_type,
        creator_id=creator_id,
        attribute_vector=attribute_vector,
        tasks_db_path=tasks_db_path,
    )


def register_a040_requests_from_feedback(
    *,
    workspace_root: str | Path,
    feedback_requests: List[Dict[str, Any]],
    source_node: str = "A150",
    priority: str = "中",
    creator_type: str = "tool",
    creator_id: str = "affair_request_bus",
    attribute_vector: Dict[str, Any] | None = None,
    tasks_db_path: str | Path | None = None,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for item in list(feedback_requests or []):
        if not isinstance(item, dict):
            continue
        results.append(
            register_a040_retrieval_request(
                workspace_root=workspace_root,
                feedback_request=item,
                source_node=source_node,
                priority=priority,
                creator_type=creator_type,
                creator_id=creator_id,
                attribute_vector=attribute_vector,
                tasks_db_path=tasks_db_path,
            )
        )
    return results


def register_a020_import_request(
    *,
    workspace_root: str | Path,
    payload: Dict[str, Any],
    priority: str = "中",
    creator_type: str = "tool",
    creator_id: str = "affair_request_bus",
    attribute_vector: Dict[str, Any] | None = None,
    tasks_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    resolved_payload = dict(payload or {})
    resolved_payload.setdefault("request_type", DEFAULT_REQUEST_TYPE_BY_NODE["A020"])
    resolved_payload.setdefault("target_node", "A020")
    resolved_payload.setdefault("request_uid", _build_request_uid("A020"))
    return register_affair_request(
        workspace_root=workspace_root,
        target_node="A020",
        payload=resolved_payload,
        priority=priority,
        creator_type=creator_type,
        creator_id=creator_id,
        attribute_vector=attribute_vector,
        tasks_db_path=tasks_db_path,
    )


def register_a045_download_request(
    *,
    workspace_root: str | Path,
    payload: Dict[str, Any],
    priority: str = "中",
    creator_type: str = "tool",
    creator_id: str = "affair_request_bus",
    attribute_vector: Dict[str, Any] | None = None,
    tasks_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    resolved_payload = dict(payload or {})
    resolved_payload.setdefault("request_type", DEFAULT_REQUEST_TYPE_BY_NODE["A050"])
    resolved_payload.setdefault("target_node", "A050")
    resolved_payload.setdefault("request_uid", _build_request_uid("A050"))
    return register_affair_request(
        workspace_root=workspace_root,
        target_node="A050",
        payload=resolved_payload,
        priority=priority,
        creator_type=creator_type,
        creator_id=creator_id,
        attribute_vector=attribute_vector,
        tasks_db_path=tasks_db_path,
    )


def register_a050_preprocess_request(
    *,
    workspace_root: str | Path,
    payload: Dict[str, Any],
    priority: str = "中",
    creator_type: str = "tool",
    creator_id: str = "affair_request_bus",
    attribute_vector: Dict[str, Any] | None = None,
    tasks_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    resolved_payload = dict(payload or {})
    resolved_payload.setdefault("request_type", DEFAULT_REQUEST_TYPE_BY_NODE["A060"])
    resolved_payload.setdefault("target_node", "A060")
    resolved_payload.setdefault("request_uid", _build_request_uid("A060"))
    return register_affair_request(
        workspace_root=workspace_root,
        target_node="A060",
        payload=resolved_payload,
        priority=priority,
        creator_type=creator_type,
        creator_id=creator_id,
        attribute_vector=attribute_vector,
        tasks_db_path=tasks_db_path,
    )


def register_a055_preprocess_request(
    *,
    workspace_root: str | Path,
    payload: Dict[str, Any],
    priority: str = "中",
    creator_type: str = "tool",
    creator_id: str = "affair_request_bus",
    attribute_vector: Dict[str, Any] | None = None,
    tasks_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    resolved_payload = dict(payload or {})
    resolved_payload.setdefault("request_type", DEFAULT_REQUEST_TYPE_BY_NODE["A070"])
    resolved_payload.setdefault("target_node", "A070")
    resolved_payload.setdefault("request_uid", _build_request_uid("A070"))
    return register_affair_request(
        workspace_root=workspace_root,
        target_node="A070",
        payload=resolved_payload,
        priority=priority,
        creator_type=creator_type,
        creator_id=creator_id,
        attribute_vector=attribute_vector,
        tasks_db_path=tasks_db_path,
    )


def load_affair_request_payload(
    *,
    workspace_root: str | Path,
    request_uid: str,
    tasks_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    workspace = _resolve_workspace_root(workspace_root)
    resolved_tasks_db = _resolve_tasks_db_path(workspace, tasks_db_path)
    row = _load_request_row_by_uid(resolved_tasks_db, request_uid)
    if row is None:
        raise KeyError(f"未找到事务请求: {request_uid}")
    payload_path = resolve_portable_path(_stringify(row.get("payload_path")), base=workspace)
    payload = _read_json_file(payload_path)
    return {
        "request_row": row,
        "payload": payload,
        "payload_path": str(payload_path),
        "tasks_db_path": str(resolved_tasks_db),
    }


def build_affair_request_runtime_config(
    *,
    workspace_root: str | Path,
    request_uid: str | None = None,
    payload: Dict[str, Any] | None = None,
    registry_path: str | Path | None = None,
    tasks_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    workspace = _resolve_workspace_root(workspace_root)
    request_row: Dict[str, Any] | None = None
    resolved_payload = dict(payload or {})
    if request_uid is not None:
        bundle = load_affair_request_payload(
            workspace_root=workspace,
            request_uid=request_uid,
            tasks_db_path=tasks_db_path,
        )
        request_row = dict(bundle.get("request_row") or {})
        resolved_payload = dict(bundle.get("payload") or {})
    if not resolved_payload:
        raise ValueError("payload 与 request_uid 至少需要提供一个")

    normalized_target_node = _normalize_node_code(resolved_payload.get("target_node") or "")
    resolved_registry_path = _resolve_registry_path(workspace, registry_path)
    registry_payload = _read_json_file(resolved_registry_path)

    from autodokit.tools.affair_entry_registry_tools import resolve_mainline_affair_entry

    entry = resolve_mainline_affair_entry(normalized_target_node, registry_payload)
    template_config_path = resolve_portable_path(str(entry.get("config_path") or ""), base=workspace)
    template_cfg = _read_json_file(template_config_path)
    if not isinstance(template_cfg, dict):
        raise ValueError(f"事务模板配置不是字典: {template_config_path}")

    runtime_cfg = dict(template_cfg)
    business_payload = dict(resolved_payload.get("business_payload") or {})
    runtime_cfg = _deep_merge_dict(runtime_cfg, business_payload)
    runtime_cfg["workspace_root"] = str(workspace)
    runtime_cfg["request_uid"] = _stringify(resolved_payload.get("request_uid") or (request_row or {}).get("request_uid"))
    runtime_cfg["request_type"] = _stringify(resolved_payload.get("request_type")) or DEFAULT_REQUEST_TYPE_BY_NODE[normalized_target_node]
    runtime_cfg["target_node"] = normalized_target_node
    runtime_cfg["caller"] = dict(resolved_payload.get("caller") or {})
    runtime_cfg["reason"] = dict(resolved_payload.get("reason") or {})
    runtime_cfg["routing_contract"] = dict(resolved_payload.get("routing_contract") or {})

    metadata = runtime_cfg.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    runtime_cfg["metadata"] = _deep_merge_dict(
        metadata,
        {
            "affair_request": {
                "request_uid": runtime_cfg["request_uid"],
                "request_type": runtime_cfg["request_type"],
                "target_node": normalized_target_node,
                "source_node": _stringify((runtime_cfg.get("caller") or {}).get("source_node")),
            }
        },
    )

    if normalized_target_node == "A020":
        runtime_cfg = _apply_a020_request_business_payload(runtime_cfg, business_payload)
    elif normalized_target_node == "A040":
        runtime_cfg = _apply_a040_request_business_payload(runtime_cfg, business_payload)
    elif normalized_target_node == "A050":
        runtime_cfg = _apply_a045_request_business_payload(runtime_cfg, business_payload)
    elif normalized_target_node == "A060":
        runtime_cfg = _apply_a050_request_business_payload(runtime_cfg, business_payload)
    elif normalized_target_node == "A070":
        runtime_cfg = _apply_a055_request_business_payload(runtime_cfg, business_payload)

    return {
        "request_row": request_row,
        "payload": resolved_payload,
        "runtime_config": runtime_cfg,
        "template_config_path": str(template_config_path),
        "entry_record": entry,
        "registry_path": str(resolved_registry_path),
    }


def _derive_target_task_uid(workspace_root: Path, output_paths: Sequence[Path]) -> str:
    tasks_root = (workspace_root / "tasks").resolve()
    for path in list(output_paths or []):
        resolved = Path(path).resolve()
        candidates = [resolved]
        if resolved.is_file():
            candidates.append(resolved.parent)
        for candidate in candidates:
            try:
                relative = candidate.relative_to(tasks_root)
            except ValueError:
                continue
            parts = list(relative.parts)
            if parts:
                return parts[0]
    return ""


def _write_dispatch_result(path: Path, payload: Dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _update_request_record(
    *,
    workspace_root: Path,
    tasks_db_path: Path,
    request_row: Dict[str, Any],
    request_status: str,
    result_summary_path: str,
    target_task_uid: str = "",
    dispatched_at: str = "",
    completed_at: str = "",
) -> Dict[str, Any]:
    return ledger_record_affair_request(
        workspace_root=workspace_root,
        request_uid=_stringify(request_row.get("request_uid")),
        request_type=_stringify(request_row.get("request_type")),
        target_node=_stringify(request_row.get("target_node")),
        request_status=request_status,
        source_node=_stringify(request_row.get("source_node")),
        source_task_uid=_stringify(request_row.get("source_task_uid")),
        source_literature_uid=_stringify(request_row.get("source_literature_uid")),
        source_cite_key=_stringify(request_row.get("source_cite_key")),
        reason_code=_stringify(request_row.get("reason_code")),
        reason_text=_stringify(request_row.get("reason_text")),
        payload_path=_stringify(request_row.get("payload_path")),
        result_summary_path=result_summary_path,
        target_task_uid=target_task_uid or _stringify(request_row.get("target_task_uid")),
        priority=_stringify(request_row.get("priority")) or "中",
        idempotency_key=_stringify(request_row.get("idempotency_key")),
        decision_status=_stringify(request_row.get("decision_status")) or "正常",
        decision_uid=_stringify(request_row.get("decision_uid")),
        attribute_vector_json=_stringify(request_row.get("attribute_vector_json")) or "{}",
        created_at=_stringify(request_row.get("created_at")) or now_iso(),
        dispatched_at=dispatched_at or _stringify(request_row.get("dispatched_at")),
        completed_at=completed_at or _stringify(request_row.get("completed_at")),
        creator_type=_stringify(request_row.get("creator_type")),
        creator_id=_stringify(request_row.get("creator_id")),
        ledger_db_path=tasks_db_path,
    )


def dispatch_affair_request(
    *,
    workspace_root: str | Path,
    request_uid: str,
    registry_path: str | Path | None = None,
    tasks_db_path: str | Path | None = None,
    force: bool = False,
    raise_on_error: bool = True,
) -> Dict[str, Any]:
    workspace = _resolve_workspace_root(workspace_root)
    resolved_tasks_db = _resolve_tasks_db_path(workspace, tasks_db_path)
    bundle = build_affair_request_runtime_config(
        workspace_root=workspace,
        request_uid=request_uid,
        registry_path=registry_path,
        tasks_db_path=resolved_tasks_db,
    )
    request_row = dict(bundle.get("request_row") or {})
    runtime_cfg = dict(bundle.get("runtime_config") or {})
    entry = dict(bundle.get("entry_record") or {})
    payload = dict(bundle.get("payload") or {})

    payload_path = resolve_portable_path(_stringify(request_row.get("payload_path")), base=workspace)
    request_dir = payload_path.parent
    runtime_config_path = request_dir / "runtime_config.json"
    dispatch_result_path = resolve_portable_path(_stringify(request_row.get("result_summary_path")), base=request_dir)
    current_status = _stringify(request_row.get("request_status")).lower()
    if not force and current_status in COMPLETED_REQUEST_STATUSES:
        if dispatch_result_path.exists():
            return dict(_read_json_file(dispatch_result_path) or {})
        return {
            "status": "SUCCEEDED",
            "request_uid": _stringify(request_row.get("request_uid")),
            "target_node": _stringify(request_row.get("target_node")),
            "target_task_uid": _stringify(request_row.get("target_task_uid")),
            "skipped_reason": "request_already_completed",
        }
    runtime_config_path.write_text(
        json.dumps(export_to_chinese_contract(runtime_cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    dispatch_started_at = now_iso()
    _update_request_record(
        workspace_root=workspace,
        tasks_db_path=resolved_tasks_db,
        request_row=request_row,
        request_status="运行中",
        result_summary_path=str(dispatch_result_path),
        dispatched_at=dispatch_started_at,
    )

    result_payload: Dict[str, Any] = {
        "status": "RUNNING",
        "request_uid": _stringify(request_row.get("request_uid")),
        "target_node": _stringify(request_row.get("target_node")),
        "affair_uid": _stringify(entry.get("affair_uid")),
        "template_config_path": _stringify(bundle.get("template_config_path")),
        "runtime_config_path": str(runtime_config_path),
        "dispatched_at": dispatch_started_at,
        "output_paths": [],
        "target_task_uid": "",
    }
    _write_dispatch_result(dispatch_result_path, result_payload)

    try:
        from autodokit.api import run_affair

        outputs = run_affair(
            _stringify(entry.get("affair_uid")),
            config=runtime_cfg,
            workspace_root=workspace,
        )
        normalized_outputs = [Path(path).resolve() for path in list(outputs or [])]
        target_task_uid = _derive_target_task_uid(workspace, normalized_outputs)
        completed_at = now_iso()
        result_payload = {
            **result_payload,
            "status": "SUCCEEDED",
            "completed_at": completed_at,
            "payload": payload,
            "output_paths": [str(path) for path in normalized_outputs],
            "target_task_uid": target_task_uid,
        }
        _write_dispatch_result(dispatch_result_path, result_payload)
        _update_request_record(
            workspace_root=workspace,
            tasks_db_path=resolved_tasks_db,
            request_row={**request_row, "target_task_uid": target_task_uid, "dispatched_at": dispatch_started_at},
            request_status="已完成",
            result_summary_path=str(dispatch_result_path),
            target_task_uid=target_task_uid,
            dispatched_at=dispatch_started_at,
            completed_at=completed_at,
        )
        return result_payload
    except Exception as exc:
        completed_at = now_iso()
        result_payload = {
            **result_payload,
            "status": "FAILED",
            "completed_at": completed_at,
            "error": str(exc),
            "payload": payload,
        }
        _write_dispatch_result(dispatch_result_path, result_payload)
        _update_request_record(
            workspace_root=workspace,
            tasks_db_path=resolved_tasks_db,
            request_row={**request_row, "dispatched_at": dispatch_started_at},
            request_status="失败",
            result_summary_path=str(dispatch_result_path),
            dispatched_at=dispatch_started_at,
            completed_at=completed_at,
        )
        if raise_on_error:
            raise
        return result_payload


def dispatch_pending_affair_requests(
    *,
    workspace_root: str | Path,
    target_nodes: Sequence[str] | None = None,
    limit: int | None = None,
    registry_path: str | Path | None = None,
    tasks_db_path: str | Path | None = None,
    raise_on_error: bool = False,
) -> List[Dict[str, Any]]:
    workspace = _resolve_workspace_root(workspace_root)
    resolved_tasks_db = _resolve_tasks_db_path(workspace, tasks_db_path)
    rows = _iter_pending_request_rows(
        resolved_tasks_db,
        target_nodes=target_nodes,
        limit=limit,
    )
    results: List[Dict[str, Any]] = []
    for row in rows:
        request_uid = _stringify(row.get("request_uid"))
        if not request_uid:
            continue
        results.append(
            dispatch_affair_request(
                workspace_root=workspace,
                request_uid=request_uid,
                registry_path=registry_path,
                tasks_db_path=resolved_tasks_db,
                raise_on_error=raise_on_error,
            )
        )
    return results


__all__ = [
    "build_affair_request_runtime_config",
    "dispatch_affair_request",
    "dispatch_pending_affair_requests",
    "load_affair_request_payload",
    "register_affair_request",
    "register_a020_import_request",
    "register_a040_retrieval_request",
    "register_a040_requests_from_feedback",
    "register_a045_download_request",
    "register_a050_preprocess_request",
    "register_a055_preprocess_request",
]