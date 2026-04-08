"""AOK 本地 Git 快照与极简任务账本测试。"""

from __future__ import annotations

import json
from pathlib import Path

from autodokit.tools.atomic.task_aok.git_snapshot_ledger import (
    DEFAULT_GITIGNORE_LOG_DB_ENTRY,
    DEFAULT_GIT_SNAPSHOT_LOG_DIR_NAME,
    DEFAULT_TASK_LEDGER_DB_NAME,
    DEFAULT_TASK_LEDGER_DIR_NAME,
    git_create_snapshot_for_task,
    git_rollback_by_task_uid,
    git_workspace_init,
    ledger_get_snapshot_by_task_uid,
    ledger_init,
    ledger_record_git_snapshot,
    ledger_record_rollback,
    ledger_record_task_run,
)


def test_ledger_init_and_records_should_work(tmp_path: Path) -> None:
    """账本初始化与最小记录写入应可工作。"""

    result = ledger_init(tmp_path)
    assert result["status"] == "PASS"
    ledger_db = tmp_path / "database" / DEFAULT_TASK_LEDGER_DIR_NAME / DEFAULT_TASK_LEDGER_DB_NAME
    assert ledger_db.exists()

    task_row = ledger_record_task_run(
        tmp_path,
        task_uid="task-001",
        workflow_uid="wf-001",
        node_code="A05",
        gate_code="G05",
        decision="pass_next",
        status="pass",
        input_summary_json={"foo": "bar"},
        output_summary_json={"ok": True},
    )
    assert task_row["task_uid"] == "task-001"

    snapshot_row = ledger_record_git_snapshot(
        tmp_path,
        snapshot_uid="snapshot-task-001",
        task_uid="task-001",
        commit_hash="abc123",
        commit_message="AOK wf-001 A05 G05 task-001 PASS",
        tag_name="aok/task/task-001",
        changed_files_count=2,
        includes_attachments=True,
    )
    assert snapshot_row["commit_hash"] == "abc123"

    rollback_row = ledger_record_rollback(
        tmp_path,
        rollback_uid="rollback-001",
        source_task_uid="task-002",
        target_task_uid="task-001",
        target_commit_hash="abc123",
        mode="preview",
        status="planned",
    )
    assert rollback_row["mode"] == "preview"

    fetched = ledger_get_snapshot_by_task_uid(tmp_path, task_uid="task-001")
    assert fetched is not None
    assert fetched["git_snapshot"]["commit_hash"] == "abc123"


def test_git_workspace_init_and_snapshot_should_work(tmp_path: Path) -> None:
    """Git 初始化、快照与摘要导出应可工作。"""

    (tmp_path / "README.md").write_text("hello", encoding="utf-8")

    init_result = git_workspace_init(tmp_path)
    assert init_result["status"] == "PASS"
    assert (tmp_path / ".git").exists()
    gitignore_path = tmp_path / ".gitignore"
    assert gitignore_path.exists()
    assert DEFAULT_GITIGNORE_LOG_DB_ENTRY in gitignore_path.read_text(encoding="utf-8")

    snapshot_result = git_create_snapshot_for_task(
        tmp_path,
        task_uid="task-001",
        workflow_uid="wf-001",
        node_code="A05",
        gate_code="G05",
    )
    assert snapshot_result["status"] == "PASS"
    assert snapshot_result["commit_hash"]

    summary_path = Path(snapshot_result["summary_path"])
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["task_uid"] == "task-001"
    assert payload["gate_code"] == "G05"

    restored = git_rollback_by_task_uid(
        tmp_path,
        source_task_uid="task-002",
        target_task_uid="task-001",
        mode="preview",
    )
    assert restored["status"] == "PASS"
    assert restored["target_task_uid"] == "task-001"

    ledger_db = tmp_path / "database" / DEFAULT_TASK_LEDGER_DIR_NAME / DEFAULT_TASK_LEDGER_DB_NAME
    assert ledger_db.exists()
    assert (tmp_path / "logs" / DEFAULT_GIT_SNAPSHOT_LOG_DIR_NAME).is_dir()


def test_git_create_snapshot_for_task_should_be_idempotent_when_no_changes(tmp_path: Path) -> None:
    """无文件变化时再次 snapshot 不应报错。"""

    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    first = git_create_snapshot_for_task(
        tmp_path,
        task_uid="task-001",
        workflow_uid="wf-001",
        node_code="A05",
        gate_code="G05",
    )
    assert first["status"] == "PASS"
    second = git_create_snapshot_for_task(
        tmp_path,
        task_uid="task-001",
        workflow_uid="wf-001",
        node_code="A05",
        gate_code="G05",
    )
    assert second["status"] == "PASS"
