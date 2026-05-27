"""AOK 本地 Git 快照与极简任务账本工具。"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from ...time_utils import now_iso


DEFAULT_TASK_LEDGER_DIR_NAME = "tasks"
DEFAULT_TASK_LEDGER_DB_NAME = "tasks.db"
DEFAULT_GIT_SNAPSHOT_LOG_DIR_NAME = "git_snapshots"
DEFAULT_GITIGNORE_LOG_DB_ENTRY = "database/logs/log.db"
TASK_RUN_TABLE_NAME = "任务运行"
GIT_SNAPSHOT_TABLE_NAME = "版本快照"
ROLLBACK_RECORD_TABLE_NAME = "回滚记录"
AFFAIR_REQUEST_TABLE_NAME = "事务请求"


def _utc_now_iso() -> str:
    return now_iso()


def _resolve_workspace_root(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser().resolve()


def _resolve_ledger_db_path(workspace_root: str | Path, ledger_db_path: str | Path | None = None) -> Path:
    if ledger_db_path is not None:
        return Path(ledger_db_path).expanduser().resolve()
    root = _resolve_workspace_root(workspace_root)
    return root / "database" / DEFAULT_TASK_LEDGER_DIR_NAME / DEFAULT_TASK_LEDGER_DB_NAME


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    return connection


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _ensure_gitignore_entry(workspace_root: Path, entry: str = DEFAULT_GITIGNORE_LOG_DB_ENTRY) -> Path:
    gitignore_path = workspace_root / ".gitignore"
    normalized_entry = entry.strip().replace("\\", "/")
    if gitignore_path.exists():
        existing_lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    else:
        existing_lines = []
    normalized_lines = [line.strip().replace("\\", "/") for line in existing_lines]
    if normalized_entry not in normalized_lines:
        updated_lines = [*existing_lines]
        if updated_lines and updated_lines[-1].strip() != "":
            updated_lines.append("")
        updated_lines.append(normalized_entry)
        gitignore_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    return gitignore_path


def create_task_ledger_readonly_views(
    workspace_root: str | Path,
    *,
    ledger_db_path: str | Path | None = None,
) -> dict[str, Any]:
    db_path = _resolve_ledger_db_path(workspace_root, ledger_db_path)
    statements = [
        f'''
        CREATE VIEW IF NOT EXISTS "任务运行总览" AS
        SELECT uid_任务 AS 任务UID, uid_工作流 AS 工作流UID, 节点编码, 闸门编码, 动作决策, 运行状态,
               工作区根路径, 开始时间, 结束时间, 操作人, 备注
        FROM {_quote_identifier(TASK_RUN_TABLE_NAME)}
        ORDER BY 结束时间 DESC, uid_任务 DESC
        ''',
        f'''
        CREATE VIEW IF NOT EXISTS "任务快照总览" AS
        SELECT gs.uid_任务 AS 任务UID, gs.uid_快照 AS 快照UID, gs.提交哈希, gs.父提交哈希,
               gs.提交信息, gs.标签名, gs.变更文件数, gs.是否包含附件 AS 含附件变更, gs.创建时间
        FROM {_quote_identifier(GIT_SNAPSHOT_TABLE_NAME)} gs
        ORDER BY gs.创建时间 DESC, gs.uid_快照 DESC
        ''',
        f'''
        CREATE VIEW IF NOT EXISTS "待人工处理任务清单" AS
        SELECT uid_任务 AS 任务UID, uid_工作流 AS 工作流UID, 节点编码, 动作决策 AS 建议动作,
               运行状态, 结束时间 AS 最近结束时间, 备注 AS 异常说明
        FROM {_quote_identifier(TASK_RUN_TABLE_NAME)}
        WHERE lower(运行状态) IN ('failed', 'blocked', 'human_gate', 'fail')
           OR lower(动作决策) IN ('pause_current', 'stop_workflow')
        ORDER BY 结束时间 DESC, uid_任务 DESC
         ''',
         f'''
         CREATE VIEW IF NOT EXISTS "待处理事务请求清单" AS
         SELECT uid_请求 AS 请求UID, 请求类型, 目标节点, 请求状态, 来源节点,
             来源任务UID, 请求原因码, 优先级, 创建时间
         FROM {_quote_identifier(AFFAIR_REQUEST_TABLE_NAME)}
         WHERE lower(请求状态) IN ('pending', '待分发', 'dispatched', '已分发', 'running', '运行中')
         ORDER BY 创建时间 DESC, uid_请求 DESC
         ''',
    ]
    with _connect(db_path) as connection:
        with connection:
            for statement in statements:
                connection.execute(statement)
    return {
        "status": "PASS",
        "ledger_db_path": str(db_path),
        "created_views": ["任务运行总览", "任务快照总览", "待人工处理任务清单", "待处理事务请求清单"],
    }


def ledger_init(workspace_root: str | Path, ledger_db_path: str | Path | None = None) -> dict[str, Any]:
    root = _resolve_workspace_root(workspace_root)
    db_path = _resolve_ledger_db_path(root, ledger_db_path)
    with _connect(db_path) as connection:
        connection.executescript(
            '''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS "任务运行" (
                uid_任务 TEXT PRIMARY KEY,
                uid_工作流 TEXT NOT NULL,
                节点编码 TEXT NOT NULL,
                闸门编码 TEXT NOT NULL,
                动作决策 TEXT NOT NULL,
                运行状态 TEXT NOT NULL,
                工作区根路径 TEXT NOT NULL,
                输入摘要 TEXT NOT NULL DEFAULT '{}',
                输出摘要 TEXT NOT NULL DEFAULT '{}',
                开始时间 TEXT NOT NULL,
                结束时间 TEXT NOT NULL,
                操作人 TEXT NOT NULL DEFAULT '',
                备注 TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS "版本快照" (
                uid_快照 TEXT PRIMARY KEY,
                uid_任务 TEXT NOT NULL,
                提交哈希 TEXT NOT NULL UNIQUE,
                父提交哈希 TEXT NOT NULL DEFAULT '',
                提交信息 TEXT NOT NULL,
                标签名 TEXT NOT NULL DEFAULT '',
                变更文件数 INTEGER NOT NULL DEFAULT 0,
                是否包含附件 INTEGER NOT NULL DEFAULT 0,
                创建时间 TEXT NOT NULL,
                FOREIGN KEY (uid_任务) REFERENCES "任务运行"(uid_任务)
            );
            CREATE TABLE IF NOT EXISTS "回滚记录" (
                uid_回滚 TEXT PRIMARY KEY,
                uid_来源任务 TEXT NOT NULL,
                uid_目标任务 TEXT NOT NULL,
                目标提交哈希 TEXT NOT NULL,
                保护提交哈希 TEXT NOT NULL DEFAULT '',
                回滚模式 TEXT NOT NULL,
                状态 TEXT NOT NULL,
                创建时间 TEXT NOT NULL,
                完成时间 TEXT NOT NULL DEFAULT '',
                备注 TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS "事务请求" (
                uid_请求 TEXT PRIMARY KEY,
                请求类型 TEXT NOT NULL,
                目标节点 TEXT NOT NULL,
                请求状态 TEXT NOT NULL,
                来源节点 TEXT NOT NULL DEFAULT '',
                来源任务UID TEXT NOT NULL DEFAULT '',
                来源文献UID TEXT NOT NULL DEFAULT '',
                来源cite_key TEXT NOT NULL DEFAULT '',
                请求原因码 TEXT NOT NULL DEFAULT '',
                请求原因 TEXT NOT NULL DEFAULT '',
                请求负载路径 TEXT NOT NULL DEFAULT '',
                结果摘要路径 TEXT NOT NULL DEFAULT '',
                uid_目标任务 TEXT NOT NULL DEFAULT '',
                优先级 TEXT NOT NULL DEFAULT '中',
                幂等键 TEXT NOT NULL DEFAULT '',
                决策状态 TEXT NOT NULL DEFAULT '正常',
                uid_决策 TEXT NOT NULL DEFAULT '',
                属性向量JSON TEXT NOT NULL DEFAULT '{}',
                创建时间 TEXT NOT NULL,
                分发时间 TEXT NOT NULL DEFAULT '',
                完成时间 TEXT NOT NULL DEFAULT '',
                创建器类型 TEXT NOT NULL DEFAULT '',
                创建器标识 TEXT NOT NULL DEFAULT ''
            );
            '''
        )
    view_bootstrap = create_task_ledger_readonly_views(workspace_root=root, ledger_db_path=db_path)
    return {
        "status": "PASS",
        "workspace_root": str(root),
        "ledger_db_path": str(db_path),
        "created_views": view_bootstrap.get("created_views", []),
    }


def ledger_record_task_run(
    workspace_root: str | Path,
    *,
    task_uid: str,
    workflow_uid: str,
    node_code: str,
    gate_code: str,
    decision: str,
    status: str,
    input_summary_json: str | dict[str, Any] | None = None,
    output_summary_json: str | dict[str, Any] | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    operator_name: str = "",
    note: str = "",
    ledger_db_path: str | Path | None = None,
) -> dict[str, Any]:
    db_path = _resolve_ledger_db_path(workspace_root, ledger_db_path)
    started = started_at or _utc_now_iso()
    ended = ended_at or started
    input_payload = json.dumps(input_summary_json or {}, ensure_ascii=False) if not isinstance(input_summary_json, str) else input_summary_json
    output_payload = json.dumps(output_summary_json or {}, ensure_ascii=False) if not isinstance(output_summary_json, str) else output_summary_json
    row = {
        "uid_任务": str(task_uid).strip(),
        "uid_工作流": str(workflow_uid).strip(),
        "节点编码": str(node_code).strip(),
        "闸门编码": str(gate_code).strip(),
        "动作决策": str(decision).strip(),
        "运行状态": str(status).strip(),
        "工作区根路径": str(_resolve_workspace_root(workspace_root)),
        "输入摘要": input_payload,
        "输出摘要": output_payload,
        "开始时间": started,
        "结束时间": ended,
        "操作人": str(operator_name).strip(),
        "备注": str(note).strip(),
    }
    with _connect(db_path) as connection:
        cursor = connection.execute(
            '''
            UPDATE "任务运行"
            SET
                uid_工作流 = ?,
                节点编码 = ?,
                闸门编码 = ?,
                动作决策 = ?,
                运行状态 = ?,
                工作区根路径 = ?,
                输入摘要 = ?,
                输出摘要 = ?,
                开始时间 = ?,
                结束时间 = ?,
                操作人 = ?,
                备注 = ?
            WHERE uid_任务 = ?
            ''',
            (
                row["uid_工作流"],
                row["节点编码"],
                row["闸门编码"],
                row["动作决策"],
                row["运行状态"],
                row["工作区根路径"],
                row["输入摘要"],
                row["输出摘要"],
                row["开始时间"],
                row["结束时间"],
                row["操作人"],
                row["备注"],
                row["uid_任务"],
            ),
        )
        if int(cursor.rowcount or 0) == 0:
            connection.execute(
                '''
                INSERT INTO "任务运行" (
                    uid_任务, uid_工作流, 节点编码, 闸门编码, 动作决策, 运行状态,
                    工作区根路径, 输入摘要, 输出摘要, 开始时间, 结束时间, 操作人, 备注
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                tuple(row.values()),
            )
    return {
        "task_uid": row["uid_任务"],
        "uid_任务": row["uid_任务"],
        "workflow_uid": row["uid_工作流"],
        "uid_工作流": row["uid_工作流"],
        "node_code": row["节点编码"],
        "gate_code": row["闸门编码"],
        "decision": row["动作决策"],
        "status": row["运行状态"],
        "input_summary_json": input_payload,
        "output_summary_json": output_payload,
    }


def ledger_record_git_snapshot(
    workspace_root: str | Path,
    *,
    snapshot_uid: str,
    task_uid: str,
    commit_hash: str,
    commit_message: str,
    parent_commit_hash: str = "",
    tag_name: str = "",
    changed_files_count: int = 0,
    includes_attachments: bool = False,
    created_at: str | None = None,
    ledger_db_path: str | Path | None = None,
) -> dict[str, Any]:
    db_path = _resolve_ledger_db_path(workspace_root, ledger_db_path)
    row = {
        "uid_快照": str(snapshot_uid).strip(),
        "uid_任务": str(task_uid).strip(),
        "提交哈希": str(commit_hash).strip(),
        "父提交哈希": str(parent_commit_hash).strip(),
        "提交信息": str(commit_message).strip(),
        "标签名": str(tag_name).strip(),
        "变更文件数": int(changed_files_count),
        "是否包含附件": 1 if includes_attachments else 0,
        "创建时间": created_at or _utc_now_iso(),
    }
    with _connect(db_path) as connection:
        connection.execute(
            '''
            INSERT INTO "版本快照" (
                uid_快照, uid_任务, 提交哈希, 父提交哈希, 提交信息, 标签名, 变更文件数, 是否包含附件, 创建时间
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid_快照) DO UPDATE SET
                uid_任务=excluded.uid_任务,
                提交哈希=excluded.提交哈希,
                父提交哈希=excluded.父提交哈希,
                提交信息=excluded.提交信息,
                标签名=excluded.标签名,
                变更文件数=excluded.变更文件数,
                是否包含附件=excluded.是否包含附件,
                创建时间=excluded.创建时间
            ''',
            tuple(row.values()),
        )
    return {
        "snapshot_uid": row["uid_快照"],
        "uid_快照": row["uid_快照"],
        "task_uid": row["uid_任务"],
        "uid_任务": row["uid_任务"],
        "commit_hash": row["提交哈希"],
        "commit_message": row["提交信息"],
        "tag_name": row["标签名"],
    }


def ledger_record_rollback(
    workspace_root: str | Path,
    *,
    rollback_uid: str,
    source_task_uid: str,
    target_task_uid: str,
    target_commit_hash: str,
    mode: str,
    status: str,
    safeguard_commit_hash: str = "",
    created_at: str | None = None,
    completed_at: str = "",
    note: str = "",
    ledger_db_path: str | Path | None = None,
) -> dict[str, Any]:
    db_path = _resolve_ledger_db_path(workspace_root, ledger_db_path)
    row = {
        "uid_回滚": str(rollback_uid).strip(),
        "uid_来源任务": str(source_task_uid).strip(),
        "uid_目标任务": str(target_task_uid).strip(),
        "目标提交哈希": str(target_commit_hash).strip(),
        "保护提交哈希": str(safeguard_commit_hash).strip(),
        "回滚模式": str(mode).strip(),
        "状态": str(status).strip(),
        "创建时间": created_at or _utc_now_iso(),
        "完成时间": completed_at,
        "备注": str(note).strip(),
    }
    with _connect(db_path) as connection:
        connection.execute(
            '''
            INSERT INTO "回滚记录" (
                uid_回滚, uid_来源任务, uid_目标任务, 目标提交哈希, 保护提交哈希, 回滚模式, 状态, 创建时间, 完成时间, 备注
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid_回滚) DO UPDATE SET
                uid_来源任务=excluded.uid_来源任务,
                uid_目标任务=excluded.uid_目标任务,
                目标提交哈希=excluded.目标提交哈希,
                保护提交哈希=excluded.保护提交哈希,
                回滚模式=excluded.回滚模式,
                状态=excluded.状态,
                创建时间=excluded.创建时间,
                完成时间=excluded.完成时间,
                备注=excluded.备注
            ''',
            tuple(row.values()),
        )
    return {
        "rollback_uid": row["uid_回滚"],
        "uid_回滚": row["uid_回滚"],
        "source_task_uid": row["uid_来源任务"],
        "target_task_uid": row["uid_目标任务"],
        "target_commit_hash": row["目标提交哈希"],
        "mode": row["回滚模式"],
        "status": row["状态"],
    }


def ledger_record_affair_request(
    workspace_root: str | Path,
    *,
    request_uid: str,
    request_type: str,
    target_node: str,
    request_status: str,
    source_node: str = "",
    source_task_uid: str = "",
    source_literature_uid: str = "",
    source_cite_key: str = "",
    reason_code: str = "",
    reason_text: str = "",
    payload_path: str = "",
    result_summary_path: str = "",
    target_task_uid: str = "",
    priority: str = "中",
    idempotency_key: str = "",
    decision_status: str = "正常",
    decision_uid: str = "",
    attribute_vector_json: str | dict[str, Any] | None = None,
    created_at: str | None = None,
    dispatched_at: str = "",
    completed_at: str = "",
    creator_type: str = "",
    creator_id: str = "",
    ledger_db_path: str | Path | None = None,
) -> dict[str, Any]:
    db_path = _resolve_ledger_db_path(workspace_root, ledger_db_path)
    attribute_payload = (
        attribute_vector_json
        if isinstance(attribute_vector_json, str)
        else json.dumps(attribute_vector_json or {}, ensure_ascii=False)
    )
    row = {
        "uid_请求": str(request_uid).strip(),
        "请求类型": str(request_type).strip(),
        "目标节点": str(target_node).strip(),
        "请求状态": str(request_status).strip(),
        "来源节点": str(source_node).strip(),
        "来源任务UID": str(source_task_uid).strip(),
        "来源文献UID": str(source_literature_uid).strip(),
        "来源cite_key": str(source_cite_key).strip(),
        "请求原因码": str(reason_code).strip(),
        "请求原因": str(reason_text).strip(),
        "请求负载路径": str(payload_path).strip(),
        "结果摘要路径": str(result_summary_path).strip(),
        "uid_目标任务": str(target_task_uid).strip(),
        "优先级": str(priority).strip() or "中",
        "幂等键": str(idempotency_key).strip(),
        "决策状态": str(decision_status).strip() or "正常",
        "uid_决策": str(decision_uid).strip(),
        "属性向量JSON": attribute_payload,
        "创建时间": created_at or _utc_now_iso(),
        "分发时间": str(dispatched_at).strip(),
        "完成时间": str(completed_at).strip(),
        "创建器类型": str(creator_type).strip(),
        "创建器标识": str(creator_id).strip(),
    }
    with _connect(db_path) as connection:
        connection.execute(
            '''
            INSERT INTO "事务请求" (
                uid_请求, 请求类型, 目标节点, 请求状态, 来源节点, 来源任务UID, 来源文献UID,
                来源cite_key, 请求原因码, 请求原因, 请求负载路径, 结果摘要路径, uid_目标任务,
                优先级, 幂等键, 决策状态, uid_决策, 属性向量JSON, 创建时间, 分发时间,
                完成时间, 创建器类型, 创建器标识
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid_请求) DO UPDATE SET
                请求类型=excluded.请求类型,
                目标节点=excluded.目标节点,
                请求状态=excluded.请求状态,
                来源节点=excluded.来源节点,
                来源任务UID=excluded.来源任务UID,
                来源文献UID=excluded.来源文献UID,
                来源cite_key=excluded.来源cite_key,
                请求原因码=excluded.请求原因码,
                请求原因=excluded.请求原因,
                请求负载路径=excluded.请求负载路径,
                结果摘要路径=excluded.结果摘要路径,
                uid_目标任务=excluded.uid_目标任务,
                优先级=excluded.优先级,
                幂等键=excluded.幂等键,
                决策状态=excluded.决策状态,
                uid_决策=excluded.uid_决策,
                属性向量JSON=excluded.属性向量JSON,
                创建时间=excluded.创建时间,
                分发时间=excluded.分发时间,
                完成时间=excluded.完成时间,
                创建器类型=excluded.创建器类型,
                创建器标识=excluded.创建器标识
            ''',
            tuple(row.values()),
        )
    return {
        "request_uid": row["uid_请求"],
        "uid_请求": row["uid_请求"],
        "request_type": row["请求类型"],
        "target_node": row["目标节点"],
        "request_status": row["请求状态"],
        "payload_path": row["请求负载路径"],
        "result_summary_path": row["结果摘要路径"],
        "idempotency_key": row["幂等键"],
    }


def ledger_get_snapshot_by_task_uid(
    workspace_root: str | Path,
    *,
    task_uid: str,
    ledger_db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    db_path = _resolve_ledger_db_path(workspace_root, ledger_db_path)
    with _connect(db_path) as connection:
        task_row = connection.execute('SELECT * FROM "任务运行" WHERE uid_任务 = ?', (str(task_uid).strip(),)).fetchone()
        snapshot_row = connection.execute(
            'SELECT * FROM "版本快照" WHERE uid_任务 = ? ORDER BY 创建时间 DESC, uid_快照 DESC LIMIT 1',
            (str(task_uid).strip(),),
        ).fetchone()
    if snapshot_row is None:
        return None
    return {
        "task_run": dict(task_row) if task_row is not None else None,
        "git_snapshot": {
            **dict(snapshot_row),
            "commit_hash": snapshot_row["提交哈希"],
            "task_uid": snapshot_row["uid_任务"],
            "snapshot_uid": snapshot_row["uid_快照"],
        },
    }


def ledger_get_snapshot_by_uid_任务(
    workspace_root: str | Path,
    *,
    uid_任务: str,
    ledger_db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    return ledger_get_snapshot_by_task_uid(workspace_root, task_uid=uid_任务, ledger_db_path=ledger_db_path)


def _run_git(workspace_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=workspace_root,
        text=True,
        capture_output=True,
        check=check,
    )


def git_workspace_init(workspace_root: str | Path, *, branch: str = "main") -> dict[str, Any]:
    root = _resolve_workspace_root(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        _run_git(root, "init", "-b", branch)
    _run_git(root, "config", "user.name", "AOK Local")
    _run_git(root, "config", "user.email", "aok-local@localhost")
    gitignore_path = _ensure_gitignore_entry(root)
    return {"status": "PASS", "workspace_root": str(root), "gitignore_path": str(gitignore_path)}


def git_create_snapshot_for_task(
    workspace_root: str | Path,
    *,
    task_uid: str,
    workflow_uid: str,
    node_code: str,
    gate_code: str,
    commit_message: str | None = None,
    tag_name: str | None = None,
    includes_attachments: bool = False,
    ledger_db_path: str | Path | None = None,
) -> dict[str, Any]:
    root = _resolve_workspace_root(workspace_root)
    git_workspace_init(root)
    ledger_init(root, ledger_db_path=ledger_db_path)
    _run_git(root, "add", "-A")
    status_output = _run_git(root, "status", "--porcelain", check=False).stdout.strip()
    message = commit_message or f"AOK {workflow_uid} {node_code} {gate_code} {task_uid} PASS"
    if status_output:
        _run_git(root, "commit", "-m", message)
    commit_hash = _run_git(root, "rev-parse", "HEAD").stdout.strip()
    parent_commit_hash = _run_git(root, "rev-parse", "HEAD^", check=False).stdout.strip()
    resolved_tag_name = tag_name or f"aok/task/{task_uid}"
    existing_tags = _run_git(root, "tag", "-l", resolved_tag_name, check=False).stdout.strip().splitlines()
    if resolved_tag_name not in existing_tags:
        _run_git(root, "tag", resolved_tag_name)

    ledger_record_task_run(
        root,
        task_uid=task_uid,
        workflow_uid=workflow_uid,
        node_code=node_code,
        gate_code=gate_code,
        decision="pass_next",
        status="pass",
        ledger_db_path=ledger_db_path,
    )
    snapshot_uid = f"snapshot-{task_uid}"
    snapshot_row = ledger_record_git_snapshot(
        root,
        snapshot_uid=snapshot_uid,
        task_uid=task_uid,
        commit_hash=commit_hash,
        parent_commit_hash=parent_commit_hash,
        commit_message=message,
        tag_name=resolved_tag_name,
        changed_files_count=len([line for line in status_output.splitlines() if line.strip()]),
        includes_attachments=includes_attachments,
        ledger_db_path=ledger_db_path,
    )

    summary_dir = root / "logs" / DEFAULT_GIT_SNAPSHOT_LOG_DIR_NAME
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / f"{task_uid}.json"
    summary_payload = {
        "task_uid": task_uid,
        "workflow_uid": workflow_uid,
        "node_code": node_code,
        "gate_code": gate_code,
        "commit_hash": commit_hash,
        "tag_name": resolved_tag_name,
    }
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "PASS",
        "task_uid": task_uid,
        "git_snapshot": snapshot_row,
        "summary_path": str(summary_path),
        "commit_hash": commit_hash,
    }


def git_rollback_by_task_uid(
    workspace_root: str | Path,
    *,
    source_task_uid: str,
    target_task_uid: str,
    mode: str = "preview",
    ledger_db_path: str | Path | None = None,
) -> dict[str, Any]:
    root = _resolve_workspace_root(workspace_root)
    snapshot = ledger_get_snapshot_by_task_uid(root, task_uid=target_task_uid, ledger_db_path=ledger_db_path)
    if snapshot is None:
        raise KeyError(f"未找到目标快照: {target_task_uid}")
    target_commit_hash = str(snapshot["git_snapshot"]["commit_hash"])
    rollback_uid = f"rollback-{source_task_uid}-to-{target_task_uid}"
    rollback_row = ledger_record_rollback(
        root,
        rollback_uid=rollback_uid,
        source_task_uid=source_task_uid,
        target_task_uid=target_task_uid,
        target_commit_hash=target_commit_hash,
        mode=mode,
        status="planned" if mode == "preview" else "done",
        ledger_db_path=ledger_db_path,
    )
    return {
        "status": "PASS",
        "source_task_uid": source_task_uid,
        "target_task_uid": target_task_uid,
        "target_commit_hash": target_commit_hash,
        "rollback": rollback_row,
    }
