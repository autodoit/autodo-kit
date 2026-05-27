# -*- coding: utf-8 -*-
"""AOK SQLite 日志数据库工具。"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence
from uuid import uuid4

from ...time_utils import now_iso


DEFAULT_AOK_LOG_DB_FILENAME = "aok_log.db"
LOG_EVENT_TABLE_NAME = "运行事件"
LOG_ARTIFACT_TABLE_NAME = "运行产物"
GATE_REVIEW_TABLE_NAME = "闸门审查"
DEFAULT_AOK_LOG_EVENT_COLUMNS: List[str] = [
    "uid_事件",
    "事件类型",
    "级别",
    "处理器类型",
    "处理器名称",
    "模型名称",
    "技能列表",
    "智能体列表",
    "读取文件列表",
    "脚本路径",
    "第三方工具",
    "推理摘要",
    "对话摘录",
    "载荷",
    "创建时间",
]

DEFAULT_AOK_REQUIRED_TABLE_COLUMNS: Dict[str, List[str]] = {
    LOG_EVENT_TABLE_NAME: DEFAULT_AOK_LOG_EVENT_COLUMNS,
    LOG_ARTIFACT_TABLE_NAME: [
        "uid_产物",
        "事务编码",
        "产物类型",
        "文件路径",
        "文件角色",
        "uid_产出事件",
        "创建时间",
    ],
    GATE_REVIEW_TABLE_NAME: [
        "uid_审查",
        "闸门编码",
        "事务编码",
        "审阅智能体",
        "审查摘要",
        "候选动作列表",
        "载荷",
        "创建时间",
    ],
}


def _stringify(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _resolve_path_from_base(base: Path, raw_path: str | Path) -> Path:
    raw = Path(raw_path)
    return raw.resolve() if raw.is_absolute() else (base / raw).resolve()


def _load_global_config_payload(config_path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_workspace_logs_dir(
    workspace_root: str | Path,
    *,
    config_path: str | Path | None = None,
) -> Path:
    resolved_workspace_root = Path(workspace_root).resolve()
    resolved_config_path: Path | None = None
    if config_path is not None:
        candidate = Path(config_path)
        if candidate.exists() and candidate.is_file():
            resolved_config_path = candidate
    else:
        candidate = resolved_workspace_root / "config" / "config.json"
        if candidate.exists() and candidate.is_file():
            resolved_config_path = candidate

    if resolved_config_path is not None:
        payload = _load_global_config_payload(resolved_config_path)
        paths = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
        raw_logs_dir = _stringify(paths.get("logs_dir"))
        if raw_logs_dir:
            return _resolve_path_from_base(resolved_workspace_root, raw_logs_dir)
    return (resolved_workspace_root / "logs").resolve()


def resolve_aok_log_db_path(
    workspace_root: str | Path,
    *,
    config_path: str | Path | None = None,
) -> Path:
    resolved_workspace_root = Path(workspace_root).resolve()
    resolved_config_path: Path | None = None
    if config_path is not None:
        candidate = Path(config_path)
        if candidate.exists() and candidate.is_file():
            resolved_config_path = candidate
    else:
        candidate = resolved_workspace_root / "config" / "config.json"
        if candidate.exists() and candidate.is_file():
            resolved_config_path = candidate

    if resolved_config_path is not None:
        payload = _load_global_config_payload(resolved_config_path)
        paths = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
        raw_log_db_path = _stringify(paths.get("log_db_path"))
        if raw_log_db_path:
            return _resolve_path_from_base(resolved_workspace_root, raw_log_db_path)
    return (resolved_workspace_root / "database" / "logs" / DEFAULT_AOK_LOG_DB_FILENAME).resolve()


def _resolve_logdb_root(
    project_root: str | Path = ".",
    *,
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
) -> tuple[Path, Path, Path]:
    root = Path(project_root).resolve()
    if log_db_path is not None:
        resolved_db_path = _resolve_path_from_base(root, log_db_path)
        resolved_logdb_root = resolved_db_path.parent
    else:
        if logs_db_root is not None:
            resolved_logdb_root = _resolve_path_from_base(root, logs_db_root)
        else:
            resolved_logdb_root = root / "database" / "logs"
        resolved_db_path = resolved_logdb_root / DEFAULT_AOK_LOG_DB_FILENAME
    return root, resolved_logdb_root, resolved_db_path


def _connect_sqlite(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> List[str]:
    statements = [
        f'''
        CREATE TABLE IF NOT EXISTS "{LOG_EVENT_TABLE_NAME}" (
            uid_事件 TEXT PRIMARY KEY,
            事件类型 TEXT NOT NULL,
            级别 TEXT,
            处理器类型 TEXT,
            处理器名称 TEXT,
            模型名称 TEXT,
            技能列表 TEXT,
            智能体列表 TEXT,
            读取文件列表 TEXT,
            脚本路径 TEXT,
            第三方工具 TEXT,
            推理摘要 TEXT,
            对话摘录 TEXT,
            载荷 TEXT,
            创建时间 TEXT NOT NULL
        )
        ''',
        f'''
        CREATE TABLE IF NOT EXISTS "{LOG_ARTIFACT_TABLE_NAME}" (
            uid_产物 TEXT PRIMARY KEY,
            事务编码 TEXT,
            产物类型 TEXT,
            文件路径 TEXT NOT NULL,
            文件角色 TEXT,
            uid_产出事件 TEXT,
            创建时间 TEXT NOT NULL,
            FOREIGN KEY(uid_产出事件) REFERENCES "{LOG_EVENT_TABLE_NAME}"(uid_事件)
        )
        ''',
        f'''
        CREATE TABLE IF NOT EXISTS "{GATE_REVIEW_TABLE_NAME}" (
            uid_审查 TEXT PRIMARY KEY,
            闸门编码 TEXT NOT NULL,
            事务编码 TEXT,
            审阅智能体 TEXT,
            审查摘要 TEXT,
            候选动作列表 TEXT,
            载荷 TEXT,
            创建时间 TEXT NOT NULL
        )
        ''',
    ]
    with connection:
        for statement in statements:
            connection.execute(statement)
    return [LOG_EVENT_TABLE_NAME, LOG_ARTIFACT_TABLE_NAME, GATE_REVIEW_TABLE_NAME]


def create_aok_log_readonly_views(
    project_root: str | Path = ".",
    *,
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    _, _, db_path = _resolve_logdb_root(project_root, logs_db_root=logs_db_root, log_db_path=log_db_path)
    statements = [
        f'''
        CREATE VIEW IF NOT EXISTS "运行事件总览" AS
        SELECT uid_事件 AS 事件UID, 事件类型, 级别, 处理器类型, 处理器名称, 模型名称, 推理摘要, 创建时间
        FROM "{LOG_EVENT_TABLE_NAME}"
        ORDER BY 创建时间 DESC, uid_事件 DESC
        ''',
        f'''
        CREATE VIEW IF NOT EXISTS "闸门审计总览" AS
        SELECT uid_审查 AS 审计UID, 闸门编码, 事务编码, 审阅智能体, 审查摘要, 候选动作列表, 创建时间
        FROM "{GATE_REVIEW_TABLE_NAME}"
        ORDER BY 创建时间 DESC, uid_审查 DESC
        ''',
        f'''
        CREATE VIEW IF NOT EXISTS "异常事件总览" AS
        SELECT uid_事件 AS 事件UID, 事件类型, 级别, 载荷, 创建时间
        FROM "{LOG_EVENT_TABLE_NAME}"
        WHERE lower(COALESCE(级别, '')) IN ('error', 'blocked', 'warning', 'critical')
        ORDER BY 创建时间 DESC, uid_事件 DESC
        ''',
    ]
    with _connect_sqlite(db_path) as connection:
        _ensure_schema(connection)
        with connection:
            for statement in statements:
                connection.execute(statement)
    return {
        "status": "PASS",
        "db_path": str(db_path),
        "created_views": ["运行事件总览", "闸门审计总览", "异常事件总览"],
    }


def init_empty_log_events_table() -> List[Dict[str, str]]:
    return []


def bootstrap_aok_logdb(
    project_root: str | Path = ".",
    *,
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    root, resolved_logdb_root, db_path = _resolve_logdb_root(project_root, logs_db_root=logs_db_root, log_db_path=log_db_path)
    errors: List[str] = []
    if resolved_logdb_root.exists() and not resolved_logdb_root.is_dir():
        errors.append(f"日志目录路径不是目录: {resolved_logdb_root}")
    if db_path.exists() and db_path.is_dir():
        errors.append(f"日志数据库文件路径当前是目录: {db_path}")
    if errors:
        return {
            "status": "BLOCKED",
            "reason": "invalid_logdb_path_shape",
            "project_root": str(root),
            "logdb_root": str(resolved_logdb_root),
            "db_path": str(db_path),
            "errors": errors,
            "warnings": [],
            "error_count": len(errors),
            "warning_count": 0,
            "created_tables": [],
            "created_views": [],
            "created_files": [],
        }

    with _connect_sqlite(db_path) as connection:
        created_tables = _ensure_schema(connection)
    view_result = create_aok_log_readonly_views(project_root=root, log_db_path=db_path)
    return {
        "status": "PASS",
        "project_root": str(root),
        "logdb_root": str(resolved_logdb_root),
        "db_path": str(db_path),
        "created_files": [str(db_path)],
        "created_tables": created_tables,
        "created_views": view_result["created_views"],
        "errors": [],
        "warnings": [],
        "error_count": 0,
        "warning_count": 0,
    }


def validate_aok_logdb(
    project_root: str | Path = ".",
    *,
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    _, _, db_path = _resolve_logdb_root(project_root, logs_db_root=logs_db_root, log_db_path=log_db_path)
    errors: List[str] = []
    warnings: List[str] = []
    if not db_path.exists() or not db_path.is_file():
        errors.append(f"日志数据库不存在: {db_path}")
        return {
            "status": "BLOCKED",
            "db_path": str(db_path),
            "errors": errors,
            "warnings": warnings,
            "error_count": len(errors),
            "warning_count": len(warnings),
        }
    with _connect_sqlite(db_path) as connection:
        for table_name, required_columns in DEFAULT_AOK_REQUIRED_TABLE_COLUMNS.items():
            rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            actual_columns = {str(row[1]) for row in rows if len(row) > 1}
            missing = [name for name in required_columns if name not in actual_columns]
            if missing:
                errors.append(f"{table_name} 缺少列: {', '.join(missing)}")
    return {
        "status": "PASS" if not errors else "BLOCKED",
        "db_path": str(db_path),
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


def _unavailable_row(reason: str, **payload: Any) -> Dict[str, Any]:
    row = {"status": "SKIPPED", "reason": reason}
    row.update(payload)
    return row


def append_aok_log_event(
    project_root: str | Path = ".",
    *,
    workspace_root: str | Path | None = None,
    event_type: str,
    handler_kind: str = "",
    handler_name: str = "",
    model_name: str = "",
    skill_names: Sequence[str] | None = None,
    agent_names: Sequence[str] | None = None,
    read_files: Sequence[str] | None = None,
    script_path: str = "",
    third_party_tool: str = "",
    reasoning_summary: str = "",
    conversation_excerpt: str = "",
    payload: Dict[str, Any] | None = None,
    log_db_path: str | Path | None = None,
    gate_review: Dict[str, Any] | None = None,
    gate_review_path: str | Path | None = None,
    level: str | None = None,
    enabled: bool | None = None,
    **extra_kwargs: Any,
) -> Dict[str, Any]:
    if enabled is False:
        return _unavailable_row(
            "disabled",
            event_type=event_type,
            handler_name=handler_name,
            payload=payload or {},
        )

    payload_data = json.loads(
        json.dumps(
            {
                **(payload or {}),
                **({"_extra_kwargs": extra_kwargs} if extra_kwargs else {}),
            },
            ensure_ascii=False,
            default=str,
        )
    )

    root = Path(workspace_root or project_root).resolve()
    db_path = Path(log_db_path).resolve() if log_db_path is not None else resolve_aok_log_db_path(root)
    if db_path.exists() and db_path.is_dir():
        return _unavailable_row("logdb_unavailable", event_type=event_type, handler_name=handler_name)
    bootstrap = bootstrap_aok_logdb(project_root=root, log_db_path=db_path)
    if bootstrap["status"] != "PASS":
        return _unavailable_row("logdb_unavailable", event_type=event_type, handler_name=handler_name)

    record = {
        "uid_事件": f"event-{uuid4().hex[:12]}",
        "事件类型": _stringify(event_type),
        "级别": _stringify(level or "info") or "info",
        "处理器类型": _stringify(handler_kind),
        "处理器名称": _stringify(handler_name),
        "模型名称": _stringify(model_name),
        "技能列表": json.dumps(list(skill_names or []), ensure_ascii=False),
        "智能体列表": json.dumps(list(agent_names or []), ensure_ascii=False),
        "读取文件列表": json.dumps(list(read_files or []), ensure_ascii=False),
        "脚本路径": _stringify(script_path),
        "第三方工具": _stringify(third_party_tool),
        "推理摘要": _stringify(reasoning_summary),
        "对话摘录": _stringify(conversation_excerpt),
        "载荷": json.dumps(payload_data, ensure_ascii=False),
        "创建时间": now_iso(),
    }
    with _connect_sqlite(db_path) as connection, connection:
        connection.execute(
            f'''
            INSERT OR REPLACE INTO "{LOG_EVENT_TABLE_NAME}" (
                uid_事件, 事件类型, 级别, 处理器类型, 处理器名称, 模型名称,
                技能列表, 智能体列表, 读取文件列表, 脚本路径,
                第三方工具, 推理摘要, 对话摘录, 载荷, 创建时间
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            tuple(record.values()),
        )

    result = {
        "status": "PASS",
        "event_uid": record["uid_事件"],
        "uid_事件": record["uid_事件"],
        "event_type": record["事件类型"],
        "handler_kind": record["处理器类型"],
        "handler_name": record["处理器名称"],
        "model_name": record["模型名称"],
        "skill_names": list(skill_names or []),
        "agent_names": list(agent_names or []),
        "read_files": list(read_files or []),
        "script_path": record["脚本路径"],
        "third_party_tool": record["第三方工具"],
        "reasoning_summary": record["推理摘要"],
        "conversation_excerpt": record["对话摘录"],
        "payload": payload_data,
        "created_at": record["创建时间"],
    }
    if gate_review is not None or gate_review_path is not None:
        logs_dir = resolve_workspace_logs_dir(root)
        exports_dir = logs_dir / "exports"
        reviews_dir = logs_dir / "reviews"
        exports_dir.mkdir(parents=True, exist_ok=True)
        reviews_dir.mkdir(parents=True, exist_ok=True)
        event_export_path = exports_dir / f'{record["uid_事件"]}.json'
        event_export_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["event_export_path"] = str(event_export_path)
        if gate_review is not None:
            gate_code = _stringify(gate_review.get("gate_code") or gate_review.get("gate_uid")) or "gate_review"
            gate_export_path = reviews_dir / f"{gate_code}.json"
            gate_export_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
            result["gate_export_path"] = str(gate_export_path)
        elif gate_review_path:
            source = Path(gate_review_path).resolve()
            if source.exists() and source.is_file():
                gate_export_path = reviews_dir / source.name
                if source != gate_export_path:
                    shutil.copy2(source, gate_export_path)
                result["gate_export_path"] = str(gate_export_path)
    return result


def list_aok_log_events(
    project_root: str | Path = ".",
    *,
    handler_kind: str | None = None,
    event_type: str | None = None,
    log_db_path: str | Path | None = None,
) -> List[Dict[str, Any]]:
    _, _, db_path = _resolve_logdb_root(project_root, log_db_path=log_db_path)
    if not db_path.exists() or not db_path.is_file():
        return []
    with _connect_sqlite(db_path) as connection:
        rows = connection.execute(f'SELECT * FROM "{LOG_EVENT_TABLE_NAME}" ORDER BY 创建时间').fetchall()
    items: List[Dict[str, Any]] = []
    for row in rows:
        payload = json.loads(str(row["载荷"] or "{}"))
        item = {
            "event_uid": str(row["uid_事件"]),
            "uid_事件": str(row["uid_事件"]),
            "event_type": str(row["事件类型"]),
            "handler_kind": str(row["处理器类型"] or ""),
            "handler_name": str(row["处理器名称"] or ""),
            "model_name": str(row["模型名称"] or ""),
            "payload": payload,
            "created_at": str(row["创建时间"]),
        }
        if handler_kind and item["handler_kind"] != handler_kind:
            continue
        if event_type and item["event_type"] != event_type:
            continue
        items.append(item)
    return items


def record_aok_log_artifact(
    project_root: str | Path = ".",
    *,
    affair_code: str,
    artifact_type: str,
    file_path: str,
    file_role: str,
    produced_by_event_uid: str = "",
    log_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    _, _, db_path = _resolve_logdb_root(project_root, log_db_path=log_db_path)
    bootstrap_aok_logdb(project_root=project_root, log_db_path=db_path)
    row = {
        "uid_产物": f"artifact-{uuid4().hex[:12]}",
        "事务编码": affair_code,
        "产物类型": artifact_type,
        "文件路径": file_path,
        "文件角色": file_role,
        "uid_产出事件": produced_by_event_uid,
        "创建时间": now_iso(),
    }
    with _connect_sqlite(db_path) as connection, connection:
        connection.execute(
            f'INSERT OR REPLACE INTO "{LOG_ARTIFACT_TABLE_NAME}" (uid_产物, 事务编码, 产物类型, 文件路径, 文件角色, uid_产出事件, 创建时间) VALUES (?, ?, ?, ?, ?, ?, ?)',
            tuple(row.values()),
        )
    return {
        "status": "PASS",
        "artifact_uid": row["uid_产物"],
        "uid_产物": row["uid_产物"],
        "affair_code": affair_code,
        "artifact_type": artifact_type,
        "file_path": file_path,
        "file_role": file_role,
        "produced_by_event_uid": produced_by_event_uid,
    }


def record_aok_gate_review(
    project_root: str | Path = ".",
    *,
    gate_code: str,
    affair_code: str,
    reviewer_agent: str,
    review_summary: str,
    decision_candidates: Sequence[str] | None = None,
    payload: Dict[str, Any] | None = None,
    log_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    _, _, db_path = _resolve_logdb_root(project_root, log_db_path=log_db_path)
    bootstrap_aok_logdb(project_root=project_root, log_db_path=db_path)
    row = {
        "uid_审查": f"review-{uuid4().hex[:12]}",
        "闸门编码": gate_code,
        "事务编码": affair_code,
        "审阅智能体": reviewer_agent,
        "审查摘要": review_summary,
        "候选动作列表": json.dumps(list(decision_candidates or []), ensure_ascii=False),
        "载荷": json.dumps(payload or {}, ensure_ascii=False),
        "创建时间": now_iso(),
    }
    with _connect_sqlite(db_path) as connection, connection:
        connection.execute(
            f'INSERT OR REPLACE INTO "{GATE_REVIEW_TABLE_NAME}" (uid_审查, 闸门编码, 事务编码, 审阅智能体, 审查摘要, 候选动作列表, 载荷, 创建时间) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            tuple(row.values()),
        )
    return {
        "status": "PASS",
        "review_uid": row["uid_审查"],
        "uid_审查": row["uid_审查"],
        "gate_code": gate_code,
        "affair_code": affair_code,
        "reviewer_agent": reviewer_agent,
        "review_summary": review_summary,
        "decision_candidates": list(decision_candidates or []),
    }


def record_aok_human_decision(
    project_root: str | Path = ".",
    *,
    gate_code: str,
    affair_code: str,
    decision: str,
    rationale: str,
    operator_name: str,
    log_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    return {
        "status": "PASS",
        "gate_code": gate_code,
        "affair_code": affair_code,
        "decision": decision,
        "rationale": rationale,
        "operator_name": operator_name,
        "created_at": now_iso(),
        "log_db_path": str(Path(log_db_path).resolve()) if log_db_path is not None else str(resolve_aok_log_db_path(project_root)),
    }


def repair_aok_logdb(
    project_root: str | Path = ".",
    *,
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
) -> Dict[str, Any]:
    root, _, db_path = _resolve_logdb_root(project_root, logs_db_root=logs_db_root, log_db_path=log_db_path)
    actions: List[str] = []
    quarantined_paths: List[str] = []
    if db_path.exists() and db_path.is_dir():
        quarantine_target = db_path.parent / f"{db_path.name}.quarantine-{uuid4().hex[:8]}"
        shutil.move(str(db_path), str(quarantine_target))
        actions.append(f"quarantine_directory:{db_path}")
        quarantined_paths.append(str(quarantine_target))
    bootstrap = bootstrap_aok_logdb(project_root=root, log_db_path=db_path)
    actions.append(f"bootstrap_schema:{bootstrap['status']}")
    return {
        "status": bootstrap["status"],
        "db_path": str(db_path),
        "actions": actions,
        "quarantined_paths": quarantined_paths,
    }
