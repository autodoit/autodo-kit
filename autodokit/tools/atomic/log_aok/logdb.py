"""AOK SQLite 日志数据库工具。"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Dict, List, Sequence, Tuple
from uuid import uuid4


DEFAULT_AOK_LOG_DB_FILENAME = "aok_log.db"
DEFAULT_AOK_LOG_EVENT_COLUMNS: List[str] = [
    "event_uid",
    "event_type",
    "level",
    "handler_kind",
    "handler_name",
    "model_name",
    "skill_names_json",
    "agent_names_json",
    "read_files_json",
    "script_path",
    "third_party_tool",
    "reasoning_summary",
    "conversation_excerpt",
    "payload_json",
    "created_at",
]

DEFAULT_AOK_REQUIRED_TABLE_COLUMNS: Dict[str, List[str]] = {
    "log_events": DEFAULT_AOK_LOG_EVENT_COLUMNS,
    "log_artifacts": [
        "artifact_uid",
        "affair_code",
        "artifact_type",
        "file_path",
        "file_role",
        "produced_by_event_uid",
        "created_at",
    ],
    "gate_reviews": [
        "review_uid",
        "gate_code",
        "affair_code",
        "reviewer_agent",
        "review_summary",
        "decision_candidates_json",
        "payload_json",
        "created_at",
    ],
    "human_decisions": [
        "decision_uid",
        "gate_code",
        "affair_code",
        "decision",
        "rationale",
        "operator_name",
        "payload_json",
        "created_at",
    ],
}


def _resolve_path_from_base(base: Path, raw_path: str | Path) -> Path:
    """基于 base 解析路径。"""

    raw = Path(raw_path)
    return raw.resolve() if raw.is_absolute() else (base / raw).resolve()


def _load_global_config_payload(config_path: Path) -> Dict[str, Any]:
    """读取全局配置 JSON 负载。"""

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_aok_log_db_path(
    workspace_root: str | Path,
    *,
    config_path: str | Path | None = None,
) -> Path:
    """解析 AOK 日志数据库文件路径。

    Args:
        workspace_root: 工作区根目录。
        config_path: 可选全局配置文件路径。

    Returns:
        绝对日志数据库文件路径。
    """

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
        path_cfg = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
        raw_log_db_path = _stringify(path_cfg.get("log_db_path"))
        if raw_log_db_path:
            return _resolve_path_from_base(resolved_workspace_root, raw_log_db_path)

    return (resolved_workspace_root / "database" / "logs" / DEFAULT_AOK_LOG_DB_FILENAME).resolve()


def _resolve_logdb_root(
    project_root: str | Path = ".",
    *,
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
) -> Tuple[Path, Path, Path]:
    """解析日志数据库路径。

    Args:
        project_root: 项目根目录。
        logs_db_root: 自定义日志数据库目录。
        log_db_path: 自定义日志数据库文件路径。

    Returns:
        `(项目根目录, 日志目录, 日志数据库文件路径)`。

    Raises:
        OSError: 路径解析失败时抛出底层异常。

    Examples:
        >>> _, root, db = _resolve_logdb_root('.')
        >>> root.name == 'logs'
        True
        >>> db.name
        'aok_log.db'
    """

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


def _validate_logdb_path_shapes(logdb_root: Path, db_path: Path) -> List[str]:
    """校验日志目录与数据库文件路径形态。"""

    errors: List[str] = []
    if logdb_root.exists() and not logdb_root.is_dir():
        errors.append(f"日志目录路径不是目录: {logdb_root}")
    if db_path.exists() and db_path.is_dir():
        errors.append(f"日志数据库文件路径当前是目录: {db_path}")
    return errors


def _build_logdb_blocked_result(
    *,
    reason: str,
    logdb_root: Path,
    db_path: Path,
    errors: Sequence[str] | None = None,
    warnings: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """构造日志系统 BLOCKED 结果。"""

    normalized_errors = list(errors or [])
    normalized_warnings = list(warnings or [])
    return {
        "status": "BLOCKED",
        "reason": reason,
        "logdb_root": str(logdb_root),
        "db_path": str(db_path),
        "created_files": [],
        "created_tables": [],
        "errors": normalized_errors,
        "warnings": normalized_warnings,
        "error_count": len(normalized_errors),
        "warning_count": len(normalized_warnings),
    }


def _utc_now_iso() -> str:
    """返回 UTC ISO 时间。"""

    return datetime.now(tz=UTC).isoformat()


def _stringify(value: Any) -> str:
    """安全转换为字符串。"""

    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(values: Sequence[str] | str | None) -> List[str]:
    """把字符串序列归一化为去重列表。"""

    if values is None:
        return []
    if isinstance(values, str):
        raw = values.replace(",", "|").replace("；", "|").replace(";", "|").split("|")
    else:
        raw = list(values)

    result: List[str] = []
    seen: set[str] = set()
    for item in raw:
        normalized = _stringify(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _safe_json_dumps(value: Any) -> str:
    """安全序列化 JSON。"""

    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return "{}"


def _connect_sqlite(db_path: Path) -> sqlite3.Connection:
    """建立 SQLite 连接。"""

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> List[str]:
    """创建日志数据库 schema。"""

    statements = [
        """
        CREATE TABLE IF NOT EXISTS log_events (
            event_uid TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            level TEXT,
            handler_kind TEXT,
            handler_name TEXT,
            model_name TEXT,
            skill_names_json TEXT,
            agent_names_json TEXT,
            read_files_json TEXT,
            script_path TEXT,
            third_party_tool TEXT,
            reasoning_summary TEXT,
            conversation_excerpt TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS log_artifacts (
            artifact_uid TEXT PRIMARY KEY,
            affair_code TEXT,
            artifact_type TEXT,
            file_path TEXT NOT NULL,
            file_role TEXT,
            produced_by_event_uid TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(produced_by_event_uid) REFERENCES log_events(event_uid)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS gate_reviews (
            review_uid TEXT PRIMARY KEY,
            gate_code TEXT NOT NULL,
            affair_code TEXT,
            reviewer_agent TEXT,
            review_summary TEXT,
            decision_candidates_json TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS human_decisions (
            decision_uid TEXT PRIMARY KEY,
            gate_code TEXT NOT NULL,
            affair_code TEXT,
            decision TEXT NOT NULL,
            rationale TEXT,
            operator_name TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_log_events_event_type ON log_events(event_type)",
        "CREATE INDEX IF NOT EXISTS idx_log_events_created_at ON log_events(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_gate_reviews_gate_code ON gate_reviews(gate_code)",
        "CREATE INDEX IF NOT EXISTS idx_human_decisions_gate_code ON human_decisions(gate_code)",
    ]
    created_tables = list(DEFAULT_AOK_REQUIRED_TABLE_COLUMNS.keys())
    with connection:
        for statement in statements:
            connection.execute(statement)
    return created_tables


def init_empty_log_events_table() -> List[Dict[str, str]]:
    """返回日志事件逻辑字段定义。"""

    return [
        {"column_name": column_name, "table_name": "log_events"}
        for column_name in DEFAULT_AOK_LOG_EVENT_COLUMNS
    ]


def bootstrap_aok_logdb(
    project_root: str | Path = ".",
    *,
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
    enabled: bool = True,
) -> Dict[str, Any]:
    """初始化 AOK SQLite 日志数据库。

    Args:
        project_root: 项目根目录。
        logs_db_root: 自定义日志数据库目录。
        log_db_path: 自定义日志数据库文件路径。
        enabled: 是否启用日志系统。

    Returns:
        初始化结果字典。

    Raises:
        OSError: 建库失败时抛出底层异常。

    Examples:
        >>> result = bootstrap_aok_logdb('.')
        >>> 'db_path' in result
        True
    """

    _, logdb_root, resolved_db_path = _resolve_logdb_root(
        project_root=project_root,
        logs_db_root=logs_db_root,
        log_db_path=log_db_path,
    )
    if not enabled:
        return {
            "status": "SKIPPED",
            "reason": "logging_disabled",
            "logdb_root": str(logdb_root),
            "db_path": str(resolved_db_path),
            "created_files": [],
            "created_tables": [],
        }

    shape_errors = _validate_logdb_path_shapes(logdb_root, resolved_db_path)
    if shape_errors:
        return _build_logdb_blocked_result(
            reason="invalid_logdb_path_shape",
            logdb_root=logdb_root,
            db_path=resolved_db_path,
            errors=shape_errors,
        )

    try:
        logdb_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return _build_logdb_blocked_result(
            reason="logdb_root_create_failed",
            logdb_root=logdb_root,
            db_path=resolved_db_path,
            errors=[f"创建日志目录失败: {exc}"],
        )

    existed_before = resolved_db_path.exists()
    try:
        with _connect_sqlite(resolved_db_path) as connection:
            created_tables = _ensure_schema(connection)
    except Exception as exc:
        return _build_logdb_blocked_result(
            reason="sqlite_bootstrap_failed",
            logdb_root=logdb_root,
            db_path=resolved_db_path,
            errors=[f"初始化日志数据库失败: {exc}"],
        )

    return {
        "status": "PASS",
        "logdb_root": str(logdb_root),
        "db_path": str(resolved_db_path),
        "created_files": [] if existed_before else [str(resolved_db_path)],
        "created_tables": created_tables,
    }


def validate_aok_logdb(
    project_root: str | Path = ".",
    *,
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
    enabled: bool = True,
) -> Dict[str, Any]:
    """校验 AOK SQLite 日志数据库结构。"""

    _, logdb_root, resolved_db_path = _resolve_logdb_root(
        project_root=project_root,
        logs_db_root=logs_db_root,
        log_db_path=log_db_path,
    )
    errors: List[str] = []
    warnings: List[str] = []

    if not enabled:
        return {
            "status": "SKIPPED",
            "reason": "logging_disabled",
            "logdb_root": str(logdb_root),
            "db_path": str(resolved_db_path),
            "errors": [],
            "warnings": [],
            "error_count": 0,
            "warning_count": 0,
        }

    shape_errors = _validate_logdb_path_shapes(logdb_root, resolved_db_path)
    errors.extend(shape_errors)

    if not logdb_root.exists():
        errors.append(f"日志数据库目录不存在: {logdb_root}")
    if not resolved_db_path.exists():
        errors.append(f"日志数据库文件不存在: {resolved_db_path}")

    if resolved_db_path.exists() and resolved_db_path.is_file() and not shape_errors:
        try:
            connection_cm = _connect_sqlite(resolved_db_path)
        except Exception as exc:
            errors.append(f"无法连接日志数据库: {exc}")
            connection_cm = None
        if connection_cm is None:
            return {
                "status": "BLOCKED",
                "logdb_root": str(logdb_root),
                "db_path": str(resolved_db_path),
                "errors": errors,
                "warnings": warnings,
                "error_count": len(errors),
                "warning_count": len(warnings),
            }

        with connection_cm as connection:
            for table_name, required_columns in DEFAULT_AOK_REQUIRED_TABLE_COLUMNS.items():
                table_exists = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                    (table_name,),
                ).fetchone()
                if table_exists is None:
                    errors.append(f"缺少数据表: {table_name}")
                    continue
                columns = {
                    row[1]
                    for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
                }
                missing_columns = [column for column in required_columns if column not in columns]
                if missing_columns:
                    errors.append(f"数据表 {table_name} 缺少字段: {','.join(missing_columns)}")

            if not errors:
                event_count = connection.execute("SELECT COUNT(*) FROM log_events").fetchone()[0]
                if event_count == 0:
                    warnings.append("日志事件表当前为空")

    return {
        "status": "PASS" if not errors else "BLOCKED",
        "logdb_root": str(logdb_root),
        "db_path": str(resolved_db_path),
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


def append_aok_log_event(
    *,
    event_type: str,
    project_root: str | Path = ".",
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
    enabled: bool = True,
    level: str = "info",
    handler_kind: str = "llm_native",
    handler_name: str = "",
    model_name: str = "",
    skill_names: Sequence[str] | str | None = None,
    agent_names: Sequence[str] | str | None = None,
    read_files: Sequence[str] | str | None = None,
    script_path: str = "",
    third_party_tool: str = "",
    reasoning_summary: str = "",
    conversation_excerpt: str = "",
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """追加一条常规日志事件。"""

    normalized_event_type = _stringify(event_type)
    if not normalized_event_type:
        raise ValueError("event_type 不能为空")

    boot = bootstrap_aok_logdb(
        project_root=project_root,
        logs_db_root=logs_db_root,
        log_db_path=log_db_path,
        enabled=enabled,
    )
    if boot["status"] == "SKIPPED":
        return {"status": "SKIPPED", "reason": "logging_disabled"}
    if boot["status"] != "PASS":
        return {
            "status": "SKIPPED",
            "reason": "logdb_unavailable",
            "error": _stringify((boot.get("errors") or [boot.get("reason")])[0]),
        }

    event_uid = f"log-{uuid4().hex[:12]}"
    created_at = _utc_now_iso()
    record: Dict[str, Any] = {
        "event_uid": event_uid,
        "event_type": normalized_event_type,
        "level": _stringify(level) or "info",
        "handler_kind": _stringify(handler_kind) or "llm_native",
        "handler_name": _stringify(handler_name),
        "model_name": _stringify(model_name),
        "skill_names_json": _safe_json_dumps(_normalize_string_list(skill_names)),
        "agent_names_json": _safe_json_dumps(_normalize_string_list(agent_names)),
        "read_files_json": _safe_json_dumps(_normalize_string_list(read_files)),
        "script_path": _stringify(script_path),
        "third_party_tool": _stringify(third_party_tool),
        "reasoning_summary": _stringify(reasoning_summary),
        "conversation_excerpt": _stringify(conversation_excerpt),
        "payload_json": _safe_json_dumps(payload or {}),
        "created_at": created_at,
    }

    try:
        with _connect_sqlite(Path(boot["db_path"])) as connection:
            connection.execute(
                """
                INSERT INTO log_events (
                    event_uid, event_type, level, handler_kind, handler_name,
                    model_name, skill_names_json, agent_names_json, read_files_json,
                    script_path, third_party_tool, reasoning_summary,
                    conversation_excerpt, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["event_uid"],
                    record["event_type"],
                    record["level"],
                    record["handler_kind"],
                    record["handler_name"],
                    record["model_name"],
                    record["skill_names_json"],
                    record["agent_names_json"],
                    record["read_files_json"],
                    record["script_path"],
                    record["third_party_tool"],
                    record["reasoning_summary"],
                    record["conversation_excerpt"],
                    record["payload_json"],
                    record["created_at"],
                ),
            )
    except Exception as exc:
        return {
            "status": "SKIPPED",
            "reason": "logdb_write_failed",
            "error": _stringify(exc),
            "event_uid": record["event_uid"],
        }
    return record


def list_aok_log_events(
    project_root: str | Path = ".",
    *,
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
    enabled: bool = True,
    event_type: str | None = None,
    handler_kind: str | None = None,
    level: str | None = None,
    limit: int | None = None,
) -> List[Dict[str, Any]]:
    """查询运行事件记录。"""

    _, _, resolved_db_path = _resolve_logdb_root(
        project_root=project_root,
        logs_db_root=logs_db_root,
        log_db_path=log_db_path,
    )
    if not enabled or not resolved_db_path.exists() or not resolved_db_path.is_file():
        return []

    conditions: List[str] = []
    parameters: List[Any] = []
    if event_type:
        conditions.append("event_type = ?")
        parameters.append(_stringify(event_type))
    if handler_kind:
        conditions.append("handler_kind = ?")
        parameters.append(_stringify(handler_kind))
    if level:
        conditions.append("level = ?")
        parameters.append(_stringify(level))

    query = "SELECT * FROM log_events"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at ASC"
    if limit is not None and limit >= 0:
        query += " LIMIT ?"
        parameters.append(limit)

    try:
        with _connect_sqlite(resolved_db_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
    except Exception:
        return []
    return [dict(row) for row in rows]


def record_aok_log_artifact(
    *,
    file_path: str,
    project_root: str | Path = ".",
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
    enabled: bool = True,
    affair_code: str = "",
    artifact_type: str = "",
    file_role: str = "",
    produced_by_event_uid: str = "",
) -> Dict[str, Any]:
    """登记关键文件产物。"""

    normalized_file_path = _stringify(file_path)
    if not normalized_file_path:
        raise ValueError("file_path 不能为空")

    boot = bootstrap_aok_logdb(
        project_root=project_root,
        logs_db_root=logs_db_root,
        log_db_path=log_db_path,
        enabled=enabled,
    )
    if boot["status"] == "SKIPPED":
        return {"status": "SKIPPED", "reason": "logging_disabled"}
    if boot["status"] != "PASS":
        return {
            "status": "SKIPPED",
            "reason": "logdb_unavailable",
            "error": _stringify((boot.get("errors") or [boot.get("reason")])[0]),
        }

    record = {
        "artifact_uid": f"artifact-{uuid4().hex[:12]}",
        "affair_code": _stringify(affair_code),
        "artifact_type": _stringify(artifact_type),
        "file_path": normalized_file_path,
        "file_role": _stringify(file_role),
        "produced_by_event_uid": _stringify(produced_by_event_uid),
        "created_at": _utc_now_iso(),
    }
    try:
        with _connect_sqlite(Path(boot["db_path"])) as connection:
            connection.execute(
                """
                INSERT INTO log_artifacts (
                    artifact_uid, affair_code, artifact_type,
                    file_path, file_role, produced_by_event_uid, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["artifact_uid"],
                    record["affair_code"],
                    record["artifact_type"],
                    record["file_path"],
                    record["file_role"],
                    record["produced_by_event_uid"],
                    record["created_at"],
                ),
            )
    except Exception as exc:
        return {
            "status": "SKIPPED",
            "reason": "logdb_write_failed",
            "error": _stringify(exc),
            "artifact_uid": record["artifact_uid"],
        }
    return record


def record_aok_gate_review(
    *,
    gate_code: str,
    project_root: str | Path = ".",
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
    enabled: bool = True,
    affair_code: str = "",
    reviewer_agent: str = "",
    review_summary: str = "",
    decision_candidates: Sequence[str] | str | None = None,
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """登记 gate 审计结果。"""

    normalized_gate_code = _stringify(gate_code)
    if not normalized_gate_code:
        raise ValueError("gate_code 不能为空")

    boot = bootstrap_aok_logdb(
        project_root=project_root,
        logs_db_root=logs_db_root,
        log_db_path=log_db_path,
        enabled=enabled,
    )
    if boot["status"] == "SKIPPED":
        return {"status": "SKIPPED", "reason": "logging_disabled"}
    if boot["status"] != "PASS":
        return {
            "status": "SKIPPED",
            "reason": "logdb_unavailable",
            "error": _stringify((boot.get("errors") or [boot.get("reason")])[0]),
        }

    record = {
        "review_uid": f"review-{uuid4().hex[:12]}",
        "gate_code": normalized_gate_code,
        "affair_code": _stringify(affair_code),
        "reviewer_agent": _stringify(reviewer_agent),
        "review_summary": _stringify(review_summary),
        "decision_candidates_json": _safe_json_dumps(_normalize_string_list(decision_candidates)),
        "payload_json": _safe_json_dumps(payload or {}),
        "created_at": _utc_now_iso(),
    }
    try:
        with _connect_sqlite(Path(boot["db_path"])) as connection:
            connection.execute(
                """
                INSERT INTO gate_reviews (
                    review_uid, gate_code, affair_code,
                    reviewer_agent, review_summary, decision_candidates_json,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["review_uid"],
                    record["gate_code"],
                    record["affair_code"],
                    record["reviewer_agent"],
                    record["review_summary"],
                    record["decision_candidates_json"],
                    record["payload_json"],
                    record["created_at"],
                ),
            )
    except Exception as exc:
        return {
            "status": "SKIPPED",
            "reason": "logdb_write_failed",
            "error": _stringify(exc),
            "review_uid": record["review_uid"],
        }
    return record


def record_aok_human_decision(
    *,
    gate_code: str,
    decision: str,
    project_root: str | Path = ".",
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
    enabled: bool = True,
    affair_code: str = "",
    rationale: str = "",
    operator_name: str = "",
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """登记人工最终决策。"""

    normalized_gate_code = _stringify(gate_code)
    normalized_decision = _stringify(decision)
    if not normalized_gate_code:
        raise ValueError("gate_code 不能为空")
    if not normalized_decision:
        raise ValueError("decision 不能为空")

    boot = bootstrap_aok_logdb(
        project_root=project_root,
        logs_db_root=logs_db_root,
        log_db_path=log_db_path,
        enabled=enabled,
    )
    if boot["status"] == "SKIPPED":
        return {"status": "SKIPPED", "reason": "logging_disabled"}
    if boot["status"] != "PASS":
        return {
            "status": "SKIPPED",
            "reason": "logdb_unavailable",
            "error": _stringify((boot.get("errors") or [boot.get("reason")])[0]),
        }

    record = {
        "decision_uid": f"decision-{uuid4().hex[:12]}",
        "gate_code": normalized_gate_code,
        "affair_code": _stringify(affair_code),
        "decision": normalized_decision,
        "rationale": _stringify(rationale),
        "operator_name": _stringify(operator_name),
        "payload_json": _safe_json_dumps(payload or {}),
        "created_at": _utc_now_iso(),
    }
    try:
        with _connect_sqlite(Path(boot["db_path"])) as connection:
            connection.execute(
                """
                INSERT INTO human_decisions (
                    decision_uid, gate_code, affair_code,
                    decision, rationale, operator_name, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["decision_uid"],
                    record["gate_code"],
                    record["affair_code"],
                    record["decision"],
                    record["rationale"],
                    record["operator_name"],
                    record["payload_json"],
                    record["created_at"],
                ),
            )
    except Exception as exc:
        return {
            "status": "SKIPPED",
            "reason": "logdb_write_failed",
            "error": _stringify(exc),
            "decision_uid": record["decision_uid"],
        }
    return record


def repair_aok_logdb(
    project_root: str | Path = ".",
    *,
    logs_db_root: str | Path | None = None,
    log_db_path: str | Path | None = None,
    enabled: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """修复 AOK 日志数据库路径异常并重建 schema。"""

    _, logdb_root, resolved_db_path = _resolve_logdb_root(
        project_root=project_root,
        logs_db_root=logs_db_root,
        log_db_path=log_db_path,
    )
    if not enabled:
        return {
            "status": "SKIPPED",
            "reason": "logging_disabled",
            "logdb_root": str(logdb_root),
            "db_path": str(resolved_db_path),
            "actions": [],
            "quarantined_paths": [],
            "dry_run": bool(dry_run),
        }

    actions: List[str] = []
    quarantined_paths: List[str] = []

    if logdb_root.exists() and not logdb_root.is_dir():
        return _build_logdb_blocked_result(
            reason="invalid_logdb_root_shape",
            logdb_root=logdb_root,
            db_path=resolved_db_path,
            errors=[f"日志目录路径不是目录: {logdb_root}"],
        )

    if resolved_db_path.exists() and resolved_db_path.is_dir():
        quarantine_path = resolved_db_path.parent / (
            f"{resolved_db_path.name}.dir_quarantine_{datetime.now(tz=UTC).strftime('%Y%m%d%H%M%S')}"
        )
        actions.append(f"quarantine_directory:{resolved_db_path}->{quarantine_path}")
        quarantined_paths.append(str(quarantine_path))
        if not dry_run:
            shutil.move(str(resolved_db_path), str(quarantine_path))

    if not dry_run:
        bootstrap = bootstrap_aok_logdb(
            project_root=project_root,
            logs_db_root=logs_db_root,
            log_db_path=log_db_path,
            enabled=enabled,
        )
        if bootstrap.get("status") != "PASS":
            return {
                "status": "BLOCKED",
                "reason": "repair_bootstrap_failed",
                "logdb_root": str(logdb_root),
                "db_path": str(resolved_db_path),
                "actions": actions,
                "quarantined_paths": quarantined_paths,
                "dry_run": False,
                "bootstrap_result": bootstrap,
                "errors": list(bootstrap.get("errors") or []),
                "warnings": list(bootstrap.get("warnings") or []),
                "error_count": len(list(bootstrap.get("errors") or [])),
                "warning_count": len(list(bootstrap.get("warnings") or [])),
            }
        actions.append("bootstrap_schema:PASS")

    return {
        "status": "PASS",
        "logdb_root": str(logdb_root),
        "db_path": str(resolved_db_path),
        "actions": actions,
        "quarantined_paths": quarantined_paths,
        "dry_run": bool(dry_run),
    }
