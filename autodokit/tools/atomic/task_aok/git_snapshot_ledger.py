"""AOK 本地 Git 快照与极简任务账本工具。

本模块只提供最小闭环能力：
1. 初始化独立 SQLite 任务账本；
2. 记录节点运行、Git 快照与回滚记录；
3. 对 workspace 执行本地 Git 初始化、提交、打 tag 与回滚查询。
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_TASK_LEDGER_DIR_NAME = "tasks"
DEFAULT_TASK_LEDGER_DB_NAME = "tasks.db"
DEFAULT_GIT_SNAPSHOT_LOG_DIR_NAME = "git_snapshots"
DEFAULT_GITIGNORE_LOG_DB_ENTRY = "database/logs/aok_log.db"


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


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


def ledger_init(workspace_root: str | Path, ledger_db_path: str | Path | None = None) -> dict[str, Any]:
    """初始化极简任务账本。

    Args:
        workspace_root: workspace 根目录。
        ledger_db_path: 可选自定义账本路径。

    Returns:
        初始化结果摘要。

    Examples:
        >>> result = ledger_init('.tmp')
        >>> result['status']
        'PASS'
    """

    root = _resolve_workspace_root(workspace_root)
    db_path = _resolve_ledger_db_path(root, ledger_db_path)
    with _connect(db_path) as connection:
        connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS task_runs (
                task_uid TEXT PRIMARY KEY,
                workflow_uid TEXT NOT NULL,
                node_code TEXT NOT NULL,
                gate_code TEXT NOT NULL,
                decision TEXT NOT NULL,
                status TEXT NOT NULL,
                workspace_root TEXT NOT NULL,
                input_summary_json TEXT NOT NULL DEFAULT '{}',
                output_summary_json TEXT NOT NULL DEFAULT '{}',
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                operator_name TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS git_snapshots (
                snapshot_uid TEXT PRIMARY KEY,
                task_uid TEXT NOT NULL,
                commit_hash TEXT NOT NULL UNIQUE,
                parent_commit_hash TEXT NOT NULL DEFAULT '',
                commit_message TEXT NOT NULL,
                tag_name TEXT NOT NULL DEFAULT '',
                changed_files_count INTEGER NOT NULL DEFAULT 0,
                includes_attachments INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (task_uid) REFERENCES task_runs(task_uid)
            );
            CREATE TABLE IF NOT EXISTS rollback_records (
                rollback_uid TEXT PRIMARY KEY,
                source_task_uid TEXT NOT NULL,
                target_task_uid TEXT NOT NULL,
                target_commit_hash TEXT NOT NULL,
                safeguard_commit_hash TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT ''
            );
            """
        )
    return {"status": "PASS", "workspace_root": str(root), "ledger_db_path": str(db_path)}


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
    """登记一次节点运行结果。"""

    db_path = _resolve_ledger_db_path(workspace_root, ledger_db_path)
    started = started_at or _utc_now_iso()
    ended = ended_at or started
    input_payload = json.dumps(input_summary_json or {}, ensure_ascii=False) if not isinstance(input_summary_json, str) else input_summary_json
    output_payload = json.dumps(output_summary_json or {}, ensure_ascii=False) if not isinstance(output_summary_json, str) else output_summary_json
    row = {
        "task_uid": str(task_uid).strip(),
        "workflow_uid": str(workflow_uid).strip(),
        "node_code": str(node_code).strip(),
        "gate_code": str(gate_code).strip(),
        "decision": str(decision).strip(),
        "status": str(status).strip(),
        "workspace_root": str(_resolve_workspace_root(workspace_root)),
        "input_summary_json": input_payload,
        "output_summary_json": output_payload,
        "started_at": started,
        "ended_at": ended,
        "operator_name": str(operator_name).strip(),
        "note": str(note).strip(),
    }
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO task_runs (
                task_uid, workflow_uid, node_code, gate_code, decision, status,
                workspace_root, input_summary_json, output_summary_json,
                started_at, ended_at, operator_name, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_uid) DO UPDATE SET
                workflow_uid=excluded.workflow_uid,
                node_code=excluded.node_code,
                gate_code=excluded.gate_code,
                decision=excluded.decision,
                status=excluded.status,
                workspace_root=excluded.workspace_root,
                input_summary_json=excluded.input_summary_json,
                output_summary_json=excluded.output_summary_json,
                started_at=excluded.started_at,
                ended_at=excluded.ended_at,
                operator_name=excluded.operator_name,
                note=excluded.note
            """,
            tuple(row.values()),
        )
    return row


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
    """登记 Git 快照。"""

    db_path = _resolve_ledger_db_path(workspace_root, ledger_db_path)
    row = {
        "snapshot_uid": str(snapshot_uid).strip(),
        "task_uid": str(task_uid).strip(),
        "commit_hash": str(commit_hash).strip(),
        "parent_commit_hash": str(parent_commit_hash).strip(),
        "commit_message": str(commit_message).strip(),
        "tag_name": str(tag_name).strip(),
        "changed_files_count": int(changed_files_count),
        "includes_attachments": 1 if includes_attachments else 0,
        "created_at": created_at or _utc_now_iso(),
    }
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO git_snapshots (
                snapshot_uid, task_uid, commit_hash, parent_commit_hash,
                commit_message, tag_name, changed_files_count, includes_attachments, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_uid) DO UPDATE SET
                task_uid=excluded.task_uid,
                commit_hash=excluded.commit_hash,
                parent_commit_hash=excluded.parent_commit_hash,
                commit_message=excluded.commit_message,
                tag_name=excluded.tag_name,
                changed_files_count=excluded.changed_files_count,
                includes_attachments=excluded.includes_attachments,
                created_at=excluded.created_at
            """,
            tuple(row.values()),
        )
    return row


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
    """登记回滚记录。"""

    db_path = _resolve_ledger_db_path(workspace_root, ledger_db_path)
    row = {
        "rollback_uid": str(rollback_uid).strip(),
        "source_task_uid": str(source_task_uid).strip(),
        "target_task_uid": str(target_task_uid).strip(),
        "target_commit_hash": str(target_commit_hash).strip(),
        "safeguard_commit_hash": str(safeguard_commit_hash).strip(),
        "mode": str(mode).strip(),
        "status": str(status).strip(),
        "created_at": created_at or _utc_now_iso(),
        "completed_at": completed_at,
        "note": str(note).strip(),
    }
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO rollback_records (
                rollback_uid, source_task_uid, target_task_uid, target_commit_hash,
                safeguard_commit_hash, mode, status, created_at, completed_at, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rollback_uid) DO UPDATE SET
                source_task_uid=excluded.source_task_uid,
                target_task_uid=excluded.target_task_uid,
                target_commit_hash=excluded.target_commit_hash,
                safeguard_commit_hash=excluded.safeguard_commit_hash,
                mode=excluded.mode,
                status=excluded.status,
                created_at=excluded.created_at,
                completed_at=excluded.completed_at,
                note=excluded.note
            """,
            tuple(row.values()),
        )
    return row


def ledger_get_snapshot_by_task_uid(
    workspace_root: str | Path,
    *,
    task_uid: str,
    ledger_db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """按 task_uid 查询快照记录。"""

    db_path = _resolve_ledger_db_path(workspace_root, ledger_db_path)
    with _connect(db_path) as connection:
        task_row = connection.execute(
            "SELECT * FROM task_runs WHERE task_uid = ?",
            (str(task_uid).strip(),),
        ).fetchone()
        snapshot_row = connection.execute(
            "SELECT * FROM git_snapshots WHERE task_uid = ? ORDER BY created_at DESC, snapshot_uid DESC LIMIT 1",
            (str(task_uid).strip(),),
        ).fetchone()
    if snapshot_row is None:
        return None
    return {
        "task_run": dict(task_row) if task_row is not None else None,
        "git_snapshot": dict(snapshot_row),
    }


def _run_git(workspace_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "autodokit")
    env.setdefault("GIT_AUTHOR_EMAIL", "autodokit@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "autodokit")
    env.setdefault("GIT_COMMITTER_EMAIL", "autodokit@example.com")
    return subprocess.run(
        ["git", *args],
        cwd=str(workspace_root),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def git_workspace_init(workspace_root: str | Path, *, branch: str = "main") -> dict[str, Any]:
    """初始化 workspace 的本地 Git 仓库。"""

    root = _resolve_workspace_root(workspace_root)
    git_dir = root / ".git"
    gitignore_path = _ensure_gitignore_entry(root)
    if git_dir.exists():
        return {
            "status": "PASS",
            "workspace_root": str(root),
            "git_dir": str(git_dir),
            "gitignore_path": str(gitignore_path),
            "created": False,
        }
    result = _run_git(root, ["init", "-b", branch])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git init 失败").strip())
    return {
        "status": "PASS",
        "workspace_root": str(root),
        "git_dir": str(git_dir),
        "gitignore_path": str(gitignore_path),
        "created": True,
    }


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
    """为任务创建本地 Git 快照并写入账本。"""

    root = _resolve_workspace_root(workspace_root)
    ledger_init(root, ledger_db_path=ledger_db_path)
    git_workspace_init(root)
    message = commit_message or f"AOK {workflow_uid} {node_code} {gate_code} {task_uid} PASS"
    add_result = _run_git(root, ["add", "-A"])
    if add_result.returncode != 0:
        raise RuntimeError((add_result.stderr or add_result.stdout or "git add 失败").strip())
    status_result = _run_git(root, ["status", "--porcelain"])
    changed_lines = [line for line in status_result.stdout.splitlines() if line.strip()]
    if not changed_lines:
        ledger_record_task_run(
            root,
            task_uid=task_uid,
            workflow_uid=workflow_uid,
            node_code=node_code,
            gate_code=gate_code,
            decision="pass_next",
            status="pass_no_changes",
            ledger_db_path=ledger_db_path,
        )
        return {
            "status": "PASS",
            "git_snapshot": None,
            "summary_path": "",
            "commit_hash": "",
            "created": False,
            "reason": "no_changes",
        }
    commit_result = _run_git(root, ["commit", "-m", message])
    if commit_result.returncode != 0:
        raise RuntimeError((commit_result.stderr or commit_result.stdout or "git commit 失败").strip())
    rev_result = _run_git(root, ["rev-parse", "HEAD"])
    if rev_result.returncode != 0:
        raise RuntimeError((rev_result.stderr or rev_result.stdout or "git rev-parse 失败").strip())
    commit_hash = rev_result.stdout.strip()
    parent_result = _run_git(root, ["rev-parse", "HEAD^"])
    parent_commit_hash = parent_result.stdout.strip() if parent_result.returncode == 0 else ""
    files_result = _run_git(root, ["diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"])
    changed_files_count = len([line for line in files_result.stdout.splitlines() if line.strip()])
    resolved_tag_name = tag_name or f"aok/task/{task_uid}"
    tag_result = _run_git(root, ["tag", "-f", resolved_tag_name, commit_hash])
    if tag_result.returncode != 0:
        raise RuntimeError((tag_result.stderr or tag_result.stdout or "git tag 失败").strip())
    snapshot_uid = f"snapshot-{task_uid}"
    snapshot_row = ledger_record_git_snapshot(
        root,
        snapshot_uid=snapshot_uid,
        task_uid=task_uid,
        commit_hash=commit_hash,
        parent_commit_hash=parent_commit_hash,
        commit_message=message,
        tag_name=resolved_tag_name,
        changed_files_count=changed_files_count,
        includes_attachments=includes_attachments,
        ledger_db_path=ledger_db_path,
    )
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
    summary_dir = root / "logs" / DEFAULT_GIT_SNAPSHOT_LOG_DIR_NAME
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / f"{task_uid}.json"
    summary_payload = {
        "workspace_root": str(root),
        "task_uid": task_uid,
        "workflow_uid": workflow_uid,
        "node_code": node_code,
        "gate_code": gate_code,
        "commit_hash": commit_hash,
        "tag_name": resolved_tag_name,
        "changed_files_count": changed_files_count,
        "includes_attachments": includes_attachments,
        "created_at": _utc_now_iso(),
    }
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "PASS", "git_snapshot": snapshot_row, "summary_path": str(summary_path), "commit_hash": commit_hash}


def git_rollback_by_task_uid(
    workspace_root: str | Path,
    *,
    source_task_uid: str,
    target_task_uid: str,
    mode: str = "preview",
    ledger_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """根据 task_uid 查询回滚目标。"""

    root = _resolve_workspace_root(workspace_root)
    snapshot = ledger_get_snapshot_by_task_uid(root, task_uid=target_task_uid, ledger_db_path=ledger_db_path)
    if snapshot is None:
        raise KeyError(f"未找到目标快照: {target_task_uid}")
    commit_hash = snapshot["git_snapshot"]["commit_hash"]
    rollback_uid = f"rollback-{source_task_uid}-to-{target_task_uid}"
    ledger_record_rollback(
        root,
        rollback_uid=rollback_uid,
        source_task_uid=source_task_uid,
        target_task_uid=target_task_uid,
        target_commit_hash=commit_hash,
        mode=mode,
        status="planned" if mode == "preview" else "done",
        ledger_db_path=ledger_db_path,
    )
    return {"status": "PASS", "mode": mode, "target_task_uid": target_task_uid, "target_commit_hash": commit_hash}
