"""AOB 同步撤销账本与恢复能力测试。

这些测试直接验证撤销账本与回滚逻辑，独立于 AOC 运行时，确保撤销：
1. 能精确恢复被新增 / 覆盖 / 删除的文件。
2. 幂等：重复撤销不会进一步破坏目录。
3. 不覆盖用户在同步之后做的新改动。
"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools.atomic.aob_runtime.aob_sync_undo import (
    创建撤销账本,
    执行撤销,
    列出撤销会话,
)


def _build_ledger(tmp_path: Path):
    journal_root = tmp_path / "journal"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    return 创建撤销账本(repo_root=repo_root, journal_root=journal_root, dry_run=False)


def test_undo_should_restore_create_overwrite_delete(tmp_path: Path) -> None:
    target = tmp_path / "targets"
    target.mkdir(parents=True, exist_ok=True)

    created_file = target / "created.md"
    overwritten_file = target / "overwritten.md"
    deleted_file = target / "deleted.md"

    # 模拟同步前的初始状态：overwritten 与 deleted 已存在。
    overwritten_file.write_text("OLD overwritten content", encoding="utf-8")
    deleted_file.write_text("OLD deleted content", encoding="utf-8")

    ledger = _build_ledger(tmp_path)

    # 模拟同步：新增 created。
    ledger.记录将创建(created_file)
    created_file.write_text("NEW created content", encoding="utf-8")
    ledger.标记同步后哈希(created_file)

    # 模拟同步：覆盖 overwritten。
    ledger.记录将覆盖(overwritten_file)
    overwritten_file.write_text("NEW overwritten content", encoding="utf-8")
    ledger.标记同步后哈希(overwritten_file)

    # 模拟同步：删除 deleted。
    ledger.记录将删除(deleted_file)
    deleted_file.unlink()

    assert created_file.exists()
    assert overwritten_file.read_text(encoding="utf-8") == "NEW overwritten content"
    assert not deleted_file.exists()

    # 撤销。
    ledger.关闭()
    result = 执行撤销(ledger.db_path, session_id=ledger.session_id, dry_run=False)

    assert result["status"] == "PASS"
    assert result["deleted"] == 1
    assert result["restored"] == 2
    assert not created_file.exists()
    assert overwritten_file.read_text(encoding="utf-8") == "OLD overwritten content"
    assert deleted_file.read_text(encoding="utf-8") == "OLD deleted content"


def test_undo_should_be_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "targets"
    target.mkdir(parents=True, exist_ok=True)
    created_file = target / "created.md"
    overwritten_file = target / "overwritten.md"
    overwritten_file.write_text("OLD", encoding="utf-8")

    ledger = _build_ledger(tmp_path)
    ledger.记录将创建(created_file)
    created_file.write_text("NEW", encoding="utf-8")
    ledger.标记同步后哈希(created_file)
    ledger.记录将覆盖(overwritten_file)
    overwritten_file.write_text("NEW2", encoding="utf-8")
    ledger.标记同步后哈希(overwritten_file)

    ledger.关闭()
    first = 执行撤销(ledger.db_path, session_id=ledger.session_id, dry_run=False)
    assert first["status"] == "PASS"
    assert not created_file.exists()
    assert overwritten_file.read_text(encoding="utf-8") == "OLD"

    # 第二次撤销应幂等：不再有破坏性动作。
    second = 执行撤销(ledger.db_path, session_id=ledger.session_id, dry_run=False)
    assert second["status"] == "PASS"
    assert second["idempotent"] is True
    assert not created_file.exists()
    assert overwritten_file.read_text(encoding="utf-8") == "OLD"


def test_undo_should_not_clobber_user_modifications(tmp_path: Path) -> None:
    target = tmp_path / "targets"
    target.mkdir(parents=True, exist_ok=True)
    created_file = target / "created.md"

    ledger = _build_ledger(tmp_path)
    ledger.记录将创建(created_file)
    created_file.write_text("SYNC content", encoding="utf-8")
    ledger.标记同步后哈希(created_file)

    # 用户在同步之后又改了这个文件。
    created_file.write_text("USER edited after sync", encoding="utf-8")

    ledger.关闭()
    result = 执行撤销(ledger.db_path, session_id=ledger.session_id, dry_run=False)
    assert result["status"] == "PASS"
    assert result["deleted"] == 0
    assert result["skipped"] == 1
    # 用户改动被保留。
    assert created_file.read_text(encoding="utf-8") == "USER edited after sync"


def test_undo_dry_run_should_not_touch_disk(tmp_path: Path) -> None:
    target = tmp_path / "targets"
    target.mkdir(parents=True, exist_ok=True)
    created_file = target / "created.md"

    ledger = _build_ledger(tmp_path)
    ledger.记录将创建(created_file)
    created_file.write_text("NEW", encoding="utf-8")
    ledger.标记同步后哈希(created_file)

    ledger.关闭()
    result = 执行撤销(ledger.db_path, session_id=ledger.session_id, dry_run=True)
    assert result["status"] == "DRY_RUN"
    assert result["deleted"] == 1
    # dry-run 不应真正删除文件。
    assert created_file.exists()


def test_list_sessions_should_return_created_ledger(tmp_path: Path) -> None:
    ledger = _build_ledger(tmp_path)
    ledger.记录将创建(tmp_path / "a.md")
    ledger.关闭()

    sessions = 列出撤销会话(ledger.db_path)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == ledger.session_id
    assert sessions[0]["status"] == "pending"
