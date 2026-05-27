"""AOK SQLite 决策数据库工具。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from ...time_utils import now_iso


DEFAULT_DECISION_DB_FILENAME = "decision.db"
DECISION_TABLE_NAME = "决策记录"


def _stringify(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _resolve_path_from_base(base: Path, raw_path: str | Path) -> Path:
    raw = Path(raw_path)
    return raw.resolve() if raw.is_absolute() else (base / raw).resolve()


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect_sqlite(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def resolve_decision_db_path(
    workspace_root: str | Path,
    *,
    decision_db_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> Path:
    if not _stringify(workspace_root):
        raise ValueError("workspace_root 不能为空")
    root = Path(workspace_root).expanduser().resolve()
    if decision_db_path is not None:
        return _resolve_path_from_base(root, decision_db_path)
    if config_path is not None:
        candidate = Path(config_path).expanduser().resolve()
        if candidate.exists() and candidate.is_file():
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
                paths = payload.get("paths") if isinstance(payload, dict) and isinstance(payload.get("paths"), dict) else {}
                raw_path = _stringify(paths.get("decision_db_path"))
                if raw_path:
                    return _resolve_path_from_base(root, raw_path)
            except Exception:
                pass
    return root / "database" / "decision" / DEFAULT_DECISION_DB_FILENAME


def _ensure_schema(connection: sqlite3.Connection) -> None:
    table = _quote_identifier(DECISION_TABLE_NAME)
    with connection:
        connection.execute(
            f'''
            CREATE TABLE IF NOT EXISTS {table} (
                uid_决策 TEXT PRIMARY KEY,
                uid_任务 TEXT NOT NULL DEFAULT '',
                uid_节点 TEXT NOT NULL DEFAULT '',
                闸门编码 TEXT NOT NULL DEFAULT '',
                事务编码 TEXT NOT NULL DEFAULT '',
                决策类型 TEXT NOT NULL,
                选定动作 TEXT NOT NULL,
                决策前任务状态 TEXT NOT NULL DEFAULT '',
                决策后任务状态 TEXT NOT NULL DEFAULT '',
                uid_下一节点 TEXT NOT NULL DEFAULT '',
                原因编码 TEXT NOT NULL DEFAULT '',
                原因说明 TEXT NOT NULL DEFAULT '',
                决策执行方 TEXT NOT NULL DEFAULT '',
                决策参与成员清单 TEXT NOT NULL DEFAULT '[]',
                决策模式 TEXT NOT NULL DEFAULT '',
                是否覆盖建议 INTEGER NOT NULL DEFAULT 0,
                覆盖说明 TEXT NOT NULL DEFAULT '',
                拆分子项清单 TEXT NOT NULL DEFAULT '[]',
                证据清单 TEXT NOT NULL DEFAULT '{{}}',
                决策详情 TEXT NOT NULL DEFAULT '{{}}',
                创建时间 TEXT NOT NULL
            )
            '''
        )


def create_decision_readonly_views(
    workspace_root: str | Path,
    *,
    decision_db_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    db_path = resolve_decision_db_path(workspace_root, decision_db_path=decision_db_path, config_path=config_path)
    table = _quote_identifier(DECISION_TABLE_NAME)
    statements = [
        f'''
        CREATE VIEW IF NOT EXISTS "决策记录总览" AS
        SELECT uid_决策 AS 决策UID, uid_任务 AS 任务UID, uid_节点 AS 节点UID, 闸门编码, 事务编码,
               决策类型, 选定动作, 原因编码, 原因说明, 决策执行方, 决策模式, 创建时间
        FROM {table}
        ORDER BY 创建时间 DESC, uid_决策 DESC
        ''',
        f'''
        CREATE VIEW IF NOT EXISTS "人工决策总览" AS
        SELECT uid_决策 AS 决策UID, uid_任务 AS 任务UID, uid_节点 AS 节点UID, 闸门编码, 事务编码,
               选定动作 AS 人工决策, 原因说明 AS 决策理由, 决策执行方 AS 操作人, 创建时间 AS 决策时间
        FROM {table}
        WHERE 决策类型 IN ('human', '人工决策') OR 决策模式 IN ('human', '人工')
        ORDER BY 创建时间 DESC, uid_决策 DESC
        ''',
        f'''
        CREATE VIEW IF NOT EXISTS "待人工裁决清单" AS
        SELECT uid_决策 AS 决策UID, uid_任务 AS 任务UID, uid_节点 AS 节点UID, 闸门编码, 事务编码, 原因说明, 创建时间
        FROM {table}
        WHERE 选定动作 IN ('pause_current', 'stop_workflow', 'human_gate')
           OR 决策后任务状态 IN ('human_gate', 'blocked')
        ORDER BY 创建时间 DESC, uid_决策 DESC
        ''',
    ]
    with _connect_sqlite(db_path) as connection:
        _ensure_schema(connection)
        with connection:
            for statement in statements:
                connection.execute(statement)
    return {
        "status": "PASS",
        "decision_db_path": str(db_path),
        "created_views": ["决策记录总览", "人工决策总览", "待人工裁决清单"],
    }


def bootstrap_decision_db(
    workspace_root: str | Path,
    *,
    decision_db_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    db_path = resolve_decision_db_path(workspace_root, decision_db_path=decision_db_path, config_path=config_path)
    with _connect_sqlite(db_path) as connection:
        _ensure_schema(connection)
    views = create_decision_readonly_views(workspace_root, decision_db_path=db_path, config_path=config_path)
    return {
        "status": "PASS",
        "decision_db_path": str(db_path),
        "created_tables": [DECISION_TABLE_NAME],
        "created_views": views["created_views"],
    }


def record_decision(
    *,
    workspace_root: str | Path,
    decision_type: str,
    selected_action: str,
    decision_db_path: str | Path | None = None,
    config_path: str | Path | None = None,
    task_uid: str = "",
    node_uid: str = "",
    gate_code: str = "",
    affair_code: str = "",
    task_status_before: str = "",
    task_status_after: str = "",
    next_node_uid: str = "",
    reason_code: str = "",
    reason_text: str = "",
    decision_actor: str = "",
    decision_members: list[str] | None = None,
    decision_mode: str = "",
    is_override_recommendation: bool = False,
    override_explanation: str = "",
    split_children: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
    decision_detail: dict[str, Any] | None = None,
    uid_任务: str = "",
    uid_节点: str = "",
    uid_下一节点: str = "",
) -> dict[str, Any]:
    if not _stringify(decision_type) or not _stringify(selected_action):
        raise ValueError("decision_type 与 selected_action 不能为空")
    db_path = resolve_decision_db_path(workspace_root, decision_db_path=decision_db_path, config_path=config_path)
    bootstrap_decision_db(workspace_root, decision_db_path=db_path, config_path=config_path)
    row = {
        "uid_决策": f"decision-{uuid4().hex[:12]}",
        "uid_任务": _stringify(uid_任务 or task_uid),
        "uid_节点": _stringify(uid_节点 or node_uid),
        "闸门编码": _stringify(gate_code),
        "事务编码": _stringify(affair_code),
        "决策类型": _stringify(decision_type),
        "选定动作": _stringify(selected_action),
        "决策前任务状态": _stringify(task_status_before),
        "决策后任务状态": _stringify(task_status_after),
        "uid_下一节点": _stringify(uid_下一节点 or next_node_uid),
        "原因编码": _stringify(reason_code),
        "原因说明": _stringify(reason_text),
        "决策执行方": _stringify(decision_actor),
        "决策参与成员清单": json.dumps(list(decision_members or []), ensure_ascii=False),
        "决策模式": _stringify(decision_mode),
        "是否覆盖建议": 1 if is_override_recommendation else 0,
        "覆盖说明": _stringify(override_explanation),
        "拆分子项清单": json.dumps(list(split_children or []), ensure_ascii=False),
        "证据清单": json.dumps(evidence or {}, ensure_ascii=False),
        "决策详情": json.dumps(decision_detail or {}, ensure_ascii=False),
        "创建时间": now_iso(),
    }
    with _connect_sqlite(db_path) as connection, connection:
        connection.execute(
            f'''
            INSERT OR REPLACE INTO "{DECISION_TABLE_NAME}" (
                uid_决策, uid_任务, uid_节点, 闸门编码, 事务编码, 决策类型, 选定动作,
                决策前任务状态, 决策后任务状态, uid_下一节点, 原因编码, 原因说明,
                决策执行方, 决策参与成员清单, 决策模式, 是否覆盖建议, 覆盖说明,
                拆分子项清单, 证据清单, 决策详情, 创建时间
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            tuple(row.values()),
        )
    return {
        "uid_决策": row["uid_决策"],
        "decision_uid": row["uid_决策"],
        "uid_任务": row["uid_任务"],
        "task_uid": row["uid_任务"],
        "uid_节点": row["uid_节点"],
        "node_uid": row["uid_节点"],
        "uid_下一节点": row["uid_下一节点"],
        "next_node_uid": row["uid_下一节点"],
        "decision_type": row["决策类型"],
        "selected_action": row["选定动作"],
        "reason_code": row["原因编码"],
        "reason_text": row["原因说明"],
        "decision_actor": row["决策执行方"],
        "decision_mode": row["决策模式"],
        "created_at": row["创建时间"],
    }


def record_human_decision(
    *,
    workspace_root: str | Path,
    selected_action: str,
    rationale: str,
    operator_name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    return record_decision(
        workspace_root=workspace_root,
        decision_type="human",
        selected_action=selected_action,
        reason_text=rationale,
        decision_actor=operator_name,
        decision_mode="人工",
        **kwargs,
    )
