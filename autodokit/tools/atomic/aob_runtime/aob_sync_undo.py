"""AOB 同步撤销账本。

本模块提供幂等撤销能力：每次同步运行生成一个 SQLite 撤销账本，
记录每个目标文件的增删改操作与原始内容快照。同步完成后可通过
专用撤销脚本或 API 按 session_id 回滚。

撤销操作满足幂等要求：
- 已回滚的记录不会重复处理
- 撤销过程中每条记录独立标记
- 不依赖 LLM，纯确定性操作
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


撤销会话表名 = "sync_undo_sessions"
撤销变更表名 = "sync_undo_file_changes"
撤销数据库文件名 = "sync_undo.sqlite3"


def _sha256_bytes(data: bytes) -> str:
    """计算字节数据的 SHA256。"""

    return hashlib.sha256(data).hexdigest()


def _sha256_file(file_path: Path) -> str:
    """计算文件的 SHA256。"""

    if not file_path.exists() or not file_path.is_file():
        return ""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _确保撤销表(conn: sqlite3.Connection) -> None:
    """确保撤销相关表存在。"""

    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS {撤销会话表名} (
            session_id TEXT PRIMARY KEY,
            started_at REAL NOT NULL,
            completed_at REAL,
            sync_type TEXT NOT NULL DEFAULT 'update_user_content',
            dry_run INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            metadata_json TEXT
        );

        CREATE TABLE IF NOT EXISTS {撤销变更表名} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES {撤销会话表名}(session_id),
            change_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            target_label TEXT NOT NULL DEFAULT '',
            backup_content BLOB,
            post_content_hash TEXT NOT NULL DEFAULT '',
            rolled_back INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_undo_session_change
            ON {撤销变更表名}(session_id, rolled_back);
        """
    )


@dataclass
class 撤销账本:
    """同步撤销账本。

    在一次同步过程中记录每个文件的增删改操作及原始内容快照，
    同步完成后可通过 session_id 进行幂等回滚。

    Attributes:
        session_id: 本次会话唯一 ID。
        db_path: SQLite 数据库路径。
        dry_run: 是否为预演模式。
        repo_root: 仓库根目录。
    """

    session_id: str
    db_path: Path
    dry_run: bool
    repo_root: Path
    _conn: sqlite3.Connection | None = field(default=None, repr=False)
    _change_count: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        """初始化数据库连接并创建会话记录。"""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        _确保撤销表(self._conn)
        now_ts = float(time.time())
        self._conn.execute(
            f"""
            INSERT OR REPLACE INTO {撤销会话表名}
            (session_id, started_at, sync_type, dry_run, status, metadata_json)
            VALUES (?, ?, 'update_user_content', ?, 'pending', ?)
            """,
            (
                self.session_id,
                now_ts,
                1 if self.dry_run else 0,
                json.dumps({"repo_root": str(self.repo_root)}, ensure_ascii=False),
            ),
        )
        self._conn.commit()

    def _ensure_conn(self) -> sqlite3.Connection:
        """确保数据库连接可用。"""

        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            _确保撤销表(self._conn)
        return self._conn

    def _记录变更(self, change_type: str, file_path: Path, backup_content: bytes | None = None) -> None:
        """内部：记录一条文件变更。"""

        conn = self._ensure_conn()
        now_ts = float(time.time())
        post_hash = _sha256_file(file_path) if file_path.exists() and file_path.is_file() else ""
        target_label = self._推断目标标签(file_path)
        conn.execute(
            f"""
            INSERT INTO {撤销变更表名}
            (session_id, change_type, file_path, target_label, backup_content, post_content_hash, rolled_back, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                self.session_id,
                change_type,
                str(file_path),
                target_label,
                backup_content,
                post_hash,
                now_ts,
            ),
        )
        self._change_count += 1

    def _推断目标标签(self, file_path: Path) -> str:
        """从文件路径推断目标标签（如 copilot/claude 等）。"""

        resolved = file_path.resolve()
        parts = resolved.parts
        for part in parts:
            name = part.lower().lstrip(".")
            if name in {"copilot", "claude", "codex", "gemini", "opencode", "cursor", "lingma", "qoder", "qwen"}:
                return name
        if len(parts) >= 2:
            return parts[-2].lstrip(".")
        return ""

    def 记录将删除(self, file_path: Path) -> None:
        """记录即将删除的文件（保存原始内容用于恢复）。

        Args:
            file_path: 将被删除的文件路径。
        """

        backup = None
        if file_path.exists() and file_path.is_file():
            try:
                backup = file_path.read_bytes()
            except OSError:
                pass
        self._记录变更("deleted", file_path, backup_content=backup)

    def 记录将覆盖(self, file_path: Path) -> None:
        """记录即将被覆盖的文件（保存原始内容用于恢复）。

        Args:
            file_path: 将被覆盖的文件路径。
        """

        backup = None
        if file_path.exists() and file_path.is_file():
            try:
                backup = file_path.read_bytes()
            except OSError:
                pass
        self._记录变更("modified", file_path, backup_content=backup)

    def 记录将创建(self, file_path: Path) -> None:
        """记录即将新创建的文件。

        Args:
            file_path: 将被创建的文件路径。
        """

        self._记录变更("added", file_path, backup_content=None)

    def 标记同步后哈希(self, file_path: Path) -> None:
        """标记同步后的文件哈希（用于撤销时验证文件是否被外部修改）。

        Args:
            file_path: 已同步的文件路径。
        """

        if not file_path.exists() or not file_path.is_file():
            return
        post_hash = _sha256_file(file_path)
        conn = self._ensure_conn()
        conn.execute(
            f"""
            UPDATE {撤销变更表名}
            SET post_content_hash=?
            WHERE id = (
                SELECT id FROM {撤销变更表名}
                WHERE session_id=? AND file_path=? AND rolled_back=0
                ORDER BY id DESC LIMIT 1
            )
            """,
            (post_hash, self.session_id, str(file_path)),
        )

    def 完成(self, status: str = "completed") -> None:
        """标记会话完成。

        Args:
            status: 完成状态（completed/failed）。
        """

        conn = self._ensure_conn()
        now_ts = float(time.time())
        conn.execute(
            f"UPDATE {撤销会话表名} SET completed_at=?, status=? WHERE session_id=?",
            (now_ts, status, self.session_id),
        )
        conn.commit()

    def 结果摘要(self) -> dict[str, Any]:
        """生成撤销账本的结果摘要。

        Returns:
            dict[str, Any]: 结果摘要。
        """

        conn = self._ensure_conn()
        total = conn.execute(
            f"SELECT COUNT(*) FROM {撤销变更表名} WHERE session_id=?",
            (self.session_id,),
        ).fetchone()[0]
        by_type: dict[str, int] = {}
        for change_type, count in conn.execute(
            f"SELECT change_type, COUNT(*) FROM {撤销变更表名} WHERE session_id=? GROUP BY change_type",
            (self.session_id,),
        ):
            by_type[str(change_type)] = int(count)

        return {
            "enabled": True,
            "session_id": self.session_id,
            "db_path": str(self.db_path),
            "dry_run": self.dry_run,
            "repo_root": str(self.repo_root),
            "total_changes": int(total),
            "by_type": by_type,
        }

    def 关闭(self) -> None:
        """关闭数据库连接。"""

        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


def 创建撤销账本(
    *,
    repo_root: Path,
    journal_root: Path | None = None,
    dry_run: bool = True,
    summary_meta: dict[str, Any] | None = None,
) -> 撤销账本:
    """创建一个新的撤销账本实例。

    Args:
        repo_root: 仓库根目录。
        journal_root: 撤销账本存放根目录；不传则默认 ``<repo_root>/datastore/sync_undo``。
        dry_run: 是否为预演模式。
        summary_meta: 附加元数据。

    Returns:
        撤销账本: 已初始化的撤销账本实例。
    """

    if journal_root is None:
        journal_root = repo_root / "datastore" / "sync_undo"
    journal_root.mkdir(parents=True, exist_ok=True)

    db_path = journal_root / 撤销数据库文件名
    session_id = f"sync-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

    journal = 撤销账本(
        session_id=session_id,
        db_path=db_path,
        dry_run=dry_run,
        repo_root=repo_root,
    )
    return journal


def 执行撤销(
    db_path: Path,
    *,
    session_id: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """执行指定会话的同步撤销（幂等）。

    撤销逻辑：
    - added 文件 -> 删除（仅当内容 hash 匹配时）
    - modified 文件 -> 用 backup_content 恢复
    - deleted 文件 -> 用 backup_content 重建

    Args:
        db_path: 撤销数据库路径。
        session_id: 要撤销的会话 ID。
        dry_run: 是否仅预览不执行。

    Returns:
        dict[str, Any]: 撤销结果摘要。
    """

    if not db_path.exists():
        return {"status": "FAIL", "error": f"撤销数据库不存在：{db_path}"}

    with sqlite3.connect(str(db_path)) as conn:
        session_row = conn.execute(
            f"SELECT session_id, status, dry_run, sync_type FROM {撤销会话表名} WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if session_row is None:
            return {"status": "FAIL", "error": f"会话不存在：{session_id}"}

        session_status = str(session_row[1])
        if session_status == "rolled_back":
            return {
                "status": "PASS",
                "message": f"会话 {session_id} 已经撤销过，幂等跳过",
                "idempotent": True,
                "session_id": session_id,
            }

        changes = conn.execute(
            f"""SELECT id, change_type, file_path, target_label, backup_content, post_content_hash, rolled_back
            FROM {撤销变更表名}
            WHERE session_id=? AND rolled_back=0
            ORDER BY id DESC""",
            (session_id,),
        ).fetchall()

        result: dict[str, Any] = {
            "session_id": session_id,
            "dry_run": dry_run,
            "total_pending": len(changes),
            "restored": 0,
            "deleted": 0,
            "skipped": 0,
            "errors": [],
            "changes": [],
        }

        for row in changes:
            row_id, change_type, file_path, target_label, backup_content, post_hash, _ = row
            file_obj = Path(file_path)
            record: dict[str, Any] = {
                "id": row_id,
                "change_type": change_type,
                "file_path": file_path,
                "target_label": target_label,
                "action": "",
            }

            if change_type == "added":
                if file_obj.exists() and file_obj.is_file():
                    current_hash = _sha256_file(file_obj)
                    if post_hash and current_hash != post_hash:
                        record["action"] = "skipped_hash_mismatch"
                        result["skipped"] += 1
                        result["errors"].append(f"文件内容已被外部修改，跳过删除：{file_path}")
                    else:
                        if not dry_run:
                            file_obj.unlink()
                        record["action"] = "deleted" if not dry_run else "would_delete"
                        result["deleted"] += 1
                else:
                    record["action"] = "skipped_not_found"
                    result["skipped"] += 1

            elif change_type == "modified":
                if backup_content is not None:
                    if not dry_run:
                        file_obj.parent.mkdir(parents=True, exist_ok=True)
                        file_obj.write_bytes(backup_content)
                    record["action"] = "restored" if not dry_run else "would_restore"
                    result["restored"] += 1
                else:
                    record["action"] = "skipped_no_backup"
                    result["errors"].append(f"缺少备份内容，无法恢复：{file_path}")
                    result["skipped"] += 1

            elif change_type == "deleted":
                if backup_content is not None:
                    if not dry_run:
                        file_obj.parent.mkdir(parents=True, exist_ok=True)
                        file_obj.write_bytes(backup_content)
                    record["action"] = "restored" if not dry_run else "would_restore"
                    result["restored"] += 1
                else:
                    record["action"] = "skipped_no_backup"
                    result["errors"].append(f"缺少备份内容，无法重建：{file_path}")
                    result["skipped"] += 1

            result["changes"].append(record)
            if not dry_run:
                conn.execute(
                    f"UPDATE {撤销变更表名} SET rolled_back=1 WHERE id=?",
                    (row_id,),
                )

        if not dry_run:
            now_ts = float(time.time())
            conn.execute(
                f"UPDATE {撤销会话表名} SET completed_at=?, status='rolled_back' WHERE session_id=?",
                (now_ts, session_id),
            )
            conn.commit()
            result["status"] = "PASS"
        else:
            result["status"] = "DRY_RUN"

    return result


def 列出撤销会话(db_path: Path) -> list[dict[str, Any]]:
    """列出所有撤销会话。

    Args:
        db_path: 撤销数据库路径。

    Returns:
        list[dict[str, Any]]: 会话列表。
    """

    if not db_path.exists():
        return []

    sessions: list[dict[str, Any]] = []
    with sqlite3.connect(str(db_path)) as conn:
        for row in conn.execute(
            f"SELECT session_id, started_at, completed_at, sync_type, dry_run, status FROM {撤销会话表名} ORDER BY started_at DESC"
        ):
            sessions.append(
                {
                    "session_id": str(row[0]),
                    "started_at": float(row[1]),
                    "completed_at": float(row[2]) if row[2] else None,
                    "sync_type": str(row[3]),
                    "dry_run": bool(row[4]),
                    "status": str(row[5]),
                }
            )
    return sessions
