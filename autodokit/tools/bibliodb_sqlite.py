"""SQLite-backed 文献数据库简单适配器。

用途：在不破坏现有 `autodokit.tools.bibliodb` 接口的前提下，提供一个轻量的
SQLite 存储层与 CSV 互导能力，方便把文献库持久化到 `database/references.db`。

注意：该模块提供最小化、工程可用的导入/查询接口，面向运行时与分析双重场景。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from autodokit.tools.time_utils import now_iso

from .contentdb_sqlite import (
    ATTACHMENT_LINK_TABLE_NAME,
    ATTACHMENT_TABLE_NAME,
    KNOWLEDGE_LINK_TABLE_NAME,
    PDF_STRUCTURED_VARIANT_PATH_COLUMNS,
    READING_STATE_TABLE_NAME,
    backfill_content_relationships,
    connect_sqlite,
    get_pdf_structured_variant_column,
    init_content_db,
)


LITERATURE_TABLE_NAME = "literatures"
LITERATURE_ATTACHMENT_TABLE_NAME = "literature_attachments"
LITERATURE_TAG_TABLE_NAME = "literature_tags"
LITERATURE_CHUNK_SET_TABLE_NAME = "literature_chunk_sets"
LITERATURE_CHUNK_TABLE_NAME = "literature_chunks"
LEGACY_READING_QUEUE_TABLE_NAME = "reading_queue"
READING_QUEUE_TABLE_NAME = "literature_reading_queue"
PARSE_ASSET_TABLE_NAME = "literature_parse_assets"
WORKSPACE_NODE_STATE_TABLE_NAME = "workspace_node_state"
LITERATURE_REVIEW_STATE_TABLE_NAME = "literature_review_state"
A05_CURRENT_STATE_COLUMNS: Dict[str, str] = {
    "a05_scope_key": "TEXT",
    "a05_is_review_candidate": "INTEGER",
    "a05_in_read_pool": "INTEGER",
    "a05_current_score": "REAL",
    "a05_current_rank": "INTEGER",
    "a05_current_status": "TEXT",
    "a05_last_run_uid": "TEXT",
    "a05_updated_at": "TEXT",
}
STRUCTURED_STATE_COLUMNS: Dict[str, str] = {
    "structured_status": "TEXT",
    "structured_abs_path": "TEXT",
    "structured_backend": "TEXT",
    "structured_task_type": "TEXT",
    "structured_updated_at": "TEXT",
    "structured_schema_version": "TEXT",
    "structured_text_length": "INTEGER",
    "structured_reference_count": "INTEGER",
}
STRUCTURED_STATE_COLUMNS.update(PDF_STRUCTURED_VARIANT_PATH_COLUMNS)
PLACEHOLDER_STATE_COLUMNS: Dict[str, str] = {
    "placeholder_reason": "TEXT",
    "placeholder_status": "TEXT",
    "placeholder_run_uid": "TEXT",
}
READING_QUEUE_COLUMNS: Dict[str, str] = {
    "uid_literature": "TEXT",
    "cite_key": "TEXT",
    "stage": "TEXT",
    "source_affair": "TEXT",
    "queue_status": "TEXT",
    "decision": "TEXT",
    "priority": "REAL",
    "bucket": "TEXT",
    "preferred_next_stage": "TEXT",
    "recommended_reason": "TEXT",
    "theme_relation": "TEXT",
    "evidence_note_path": "TEXT",
    "source_round": "TEXT",
    "run_uid": "TEXT",
    "scope_key": "TEXT",
    "is_current": "INTEGER",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}
READING_STATE_COLUMNS: Dict[str, str] = {
    "uid_literature": "TEXT PRIMARY KEY",
    "cite_key": "TEXT",
    "source_stage": "TEXT",
    "source_uid_literature": "TEXT",
    "source_cite_key": "TEXT",
    "recommended_reason": "TEXT",
    "theme_relation": "TEXT",
    "source_origin": "TEXT",
    "reading_objective": "TEXT",
    "manual_guidance": "TEXT",
    "pending_preprocess": "INTEGER",
    "preprocessed": "INTEGER",
    "preprocess_status": "TEXT",
    "preprocess_note_path": "TEXT",
    "standard_note_path": "TEXT",
    "pending_rough_read": "INTEGER",
    "in_rough_read": "INTEGER",
    "rough_read_done": "INTEGER",
    "rough_read_note_path": "TEXT",
    "rough_read_decision": "TEXT",
    "rough_read_reason": "TEXT",
    "analysis_light_synced": "INTEGER",
    "analysis_batch_synced": "INTEGER",
    "pending_deep_read": "INTEGER",
    "in_deep_read": "INTEGER",
    "deep_read_done": "INTEGER",
    "deep_read_count": "INTEGER",
    "deep_read_note_path": "TEXT",
    "deep_read_decision": "TEXT",
    "deep_read_reason": "TEXT",
    "analysis_formal_synced": "INTEGER",
    "innovation_synced": "INTEGER",
    "last_batch_id": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}
WORKSPACE_NODE_STATE_COLUMNS: Dict[str, str] = {
    "node_code": "TEXT PRIMARY KEY",
    "node_name": "TEXT",
    "pending_run": "INTEGER",
    "in_progress": "INTEGER",
    "completed": "INTEGER",
    "gate_status": "TEXT",
    "last_task_uid": "TEXT",
    "current_task_uid": "TEXT",
    "last_run_at": "TEXT",
    "completed_at": "TEXT",
    "summary": "TEXT",
    "next_node_code": "TEXT",
    "failure_reason": "TEXT",
    "retry_count": "INTEGER",
    "updated_at": "TEXT",
}
REVIEW_STATE_COLUMNS: Dict[str, str] = {
    "uid_literature": "TEXT PRIMARY KEY",
    "cite_key": "TEXT",
    "pending_review_candidate": "INTEGER",
    "review_candidate_ready": "INTEGER",
    "pending_review_parse": "INTEGER",
    "review_parse_ready": "INTEGER",
    "pending_reference_preprocess": "INTEGER",
    "reference_preprocessed": "INTEGER",
    "pending_review_read": "INTEGER",
    "in_review_read": "INTEGER",
    "review_read_done": "INTEGER",
    "review_read_count": "INTEGER",
    "source_stage": "TEXT",
    "source_origin": "TEXT",
    "recommended_reason": "TEXT",
    "reading_objective": "TEXT",
    "manual_guidance": "TEXT",
    "parse_asset_uid": "TEXT",
    "structured_abs_path": "TEXT",
    "note_uid": "TEXT",
    "updated_at": "TEXT",
}
PARSE_ASSET_COLUMNS: Dict[str, str] = {
    "asset_uid": "TEXT",
    "uid_literature": "TEXT",
    "cite_key": "TEXT",
    "uid_attachment": "TEXT",
    "parse_level": "TEXT",
    "backend": "TEXT",
    "model_name": "TEXT",
    "asset_dir": "TEXT",
    "normalized_structured_path": "TEXT",
    "reconstructed_markdown_path": "TEXT",
    "linear_index_path": "TEXT",
    "elements_path": "TEXT",
    "chunks_jsonl_path": "TEXT",
    "parse_record_path": "TEXT",
    "quality_report_path": "TEXT",
    "parse_status": "TEXT",
    "last_run_uid": "TEXT",
    "is_current": "INTEGER",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}


def _quote_identifier(identifier: str) -> str:
    """对 SQLite 标识符做最小转义。"""

    return '"' + str(identifier).replace('"', '""') + '"'


def _connect(db_path: Path) -> sqlite3.Connection:
    return connect_sqlite(db_path)


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: Dict[str, str]) -> None:
    existing_columns = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    }
    for column_name, column_type in columns.items():
        if column_name in existing_columns:
            continue
        conn.execute(
            f"ALTER TABLE {_quote_identifier(table_name)} ADD COLUMN {_quote_identifier(column_name)} {column_type}"
        )


def _sqlite_object_type(conn: sqlite3.Connection, object_name: str) -> str:
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ? LIMIT 1",
        (object_name,),
    ).fetchone()
    return str(row[0]).strip().lower() if row and row[0] else ""


def _create_index_if_table(conn: sqlite3.Connection, table_name: str, index_sql: str) -> None:
    if _sqlite_object_type(conn, table_name) == "table":
        conn.execute(index_sql)


def _delete_all_if_table(conn: sqlite3.Connection, table_name: str) -> None:
    if _sqlite_object_type(conn, table_name) == "table":
        try:
            conn.execute(f"DELETE FROM {_quote_identifier(table_name)}")
        except sqlite3.OperationalError as exc:
            # 兼容历史库里视图/外键混用导致的 mismatch，避免中断主写入流程。
            if "foreign key mismatch" not in str(exc).lower():
                raise


def _resolve_writable_table_name(conn: sqlite3.Connection, logical_name: str) -> str:
    """解析逻辑对象对应的可写表名。

    当逻辑对象是视图且定义为 `SELECT * FROM <base_table>` 时，
    返回底层可写表名；否则返回空字符串。
    """

    object_type = _sqlite_object_type(conn, logical_name)
    if object_type == "table":
        return logical_name
    if object_type != "view":
        return ""

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = ? LIMIT 1",
        (logical_name,),
    ).fetchone()
    view_sql = str(row[0] or "") if row else ""
    match = re.search(r"SELECT\s+\*\s+FROM\s+\"?([A-Za-z0-9_]+)\"?", view_sql, flags=re.IGNORECASE)
    if match is None:
        return ""
    base_table = str(match.group(1) or "").strip()
    if not base_table:
        return ""
    return base_table if _sqlite_object_type(conn, base_table) == "table" else ""


def init_db(db_path: Path) -> None:
    """创建数据库与必要的表（若已存在则保留）。"""
    init_content_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.cursor()
        literature_target = _resolve_writable_table_name(conn, LITERATURE_TABLE_NAME)
        if literature_target:
            _ensure_columns(conn, literature_target, A05_CURRENT_STATE_COLUMNS)
            _ensure_columns(conn, literature_target, STRUCTURED_STATE_COLUMNS)
            _ensure_columns(conn, literature_target, PLACEHOLDER_STATE_COLUMNS)
        conn.execute(f"CREATE TABLE IF NOT EXISTS {READING_QUEUE_TABLE_NAME} (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        _ensure_columns(conn, READING_QUEUE_TABLE_NAME, READING_QUEUE_COLUMNS)
        conn.execute(f"CREATE TABLE IF NOT EXISTS {READING_STATE_TABLE_NAME} (uid_literature TEXT PRIMARY KEY)")
        _ensure_columns(conn, READING_STATE_TABLE_NAME, {key: value for key, value in READING_STATE_COLUMNS.items() if key != "uid_literature"})
        conn.execute(f"CREATE TABLE IF NOT EXISTS {WORKSPACE_NODE_STATE_TABLE_NAME} (node_code TEXT PRIMARY KEY)")
        _ensure_columns(conn, WORKSPACE_NODE_STATE_TABLE_NAME, {key: value for key, value in WORKSPACE_NODE_STATE_COLUMNS.items() if key != "node_code"})
        conn.execute(f"CREATE TABLE IF NOT EXISTS {LITERATURE_REVIEW_STATE_TABLE_NAME} (uid_literature TEXT PRIMARY KEY)")
        _ensure_columns(conn, LITERATURE_REVIEW_STATE_TABLE_NAME, {key: value for key, value in REVIEW_STATE_COLUMNS.items() if key != "uid_literature"})
        conn.execute(f"CREATE TABLE IF NOT EXISTS {PARSE_ASSET_TABLE_NAME} (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        _ensure_columns(conn, PARSE_ASSET_TABLE_NAME, PARSE_ASSET_COLUMNS)

        # 从旧 reading_queue 迁移一次到新 literature_reading_queue。
        if (
            _sqlite_object_type(conn, LEGACY_READING_QUEUE_TABLE_NAME) == "table"
            and LEGACY_READING_QUEUE_TABLE_NAME != READING_QUEUE_TABLE_NAME
        ):
            legacy_count = conn.execute(
                f"SELECT COUNT(1) FROM {_quote_identifier(LEGACY_READING_QUEUE_TABLE_NAME)}"
            ).fetchone()
            current_count = conn.execute(
                f"SELECT COUNT(1) FROM {_quote_identifier(READING_QUEUE_TABLE_NAME)}"
            ).fetchone()
            if int((legacy_count or [0])[0] or 0) > 0 and int((current_count or [0])[0] or 0) == 0:
                try:
                    legacy_df = pd.read_sql_query(
                        f"SELECT * FROM {_quote_identifier(LEGACY_READING_QUEUE_TABLE_NAME)}",
                        conn,
                    )
                    if not legacy_df.empty:
                        for column in READING_QUEUE_COLUMNS:
                            if column not in legacy_df.columns:
                                legacy_df[column] = None
                        migrated = legacy_df[list(READING_QUEUE_COLUMNS.keys())].copy()
                        migrated.to_sql(READING_QUEUE_TABLE_NAME, conn, if_exists="append", index=False)
                except Exception:
                    pass
        literature_columns = {
            row[1]
            for row in cur.execute("PRAGMA table_info(literatures)").fetchall()
        }
        if "uid_literature" in literature_columns:
            _create_index_if_table(conn, "literatures", "CREATE INDEX IF NOT EXISTS idx_lit_uid ON literatures(uid_literature)")
        if "cite_key" in literature_columns:
            _create_index_if_table(conn, "literatures", "CREATE INDEX IF NOT EXISTS idx_lit_cite ON literatures(cite_key)")
        attachment_columns = {
            row[1]
            for row in cur.execute("PRAGMA table_info(literature_attachments)").fetchall()
        }
        if "uid_literature" in attachment_columns:
            _create_index_if_table(conn, "literature_attachments", "CREATE INDEX IF NOT EXISTS idx_att_lit ON literature_attachments(uid_literature)")
        tag_columns = {
            row[1]
            for row in cur.execute("PRAGMA table_info(literature_tags)").fetchall()
        }
        if "uid_literature" in tag_columns:
            _create_index_if_table(conn, "literature_tags", "CREATE INDEX IF NOT EXISTS idx_tag_lit ON literature_tags(uid_literature)")
        if "tag" in tag_columns:
            _create_index_if_table(conn, "literature_tags", "CREATE INDEX IF NOT EXISTS idx_tag_name ON literature_tags(tag)")
        _create_index_if_table(conn, LITERATURE_CHUNK_SET_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_chunk_set_uid ON {LITERATURE_CHUNK_SET_TABLE_NAME}(chunks_uid)")
        _create_index_if_table(conn, LITERATURE_CHUNK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_chunk_uid ON {LITERATURE_CHUNK_TABLE_NAME}(chunk_id)")
        _create_index_if_table(conn, LITERATURE_CHUNK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_chunk_set_ref ON {LITERATURE_CHUNK_TABLE_NAME}(chunks_uid)")
        _create_index_if_table(conn, LITERATURE_CHUNK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_chunk_lit_uid ON {LITERATURE_CHUNK_TABLE_NAME}(uid_literature)")
        _create_index_if_table(conn, READING_QUEUE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_reading_queue_stage_status ON {READING_QUEUE_TABLE_NAME}(stage, queue_status)")
        _create_index_if_table(conn, READING_QUEUE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_reading_queue_item ON {READING_QUEUE_TABLE_NAME}(stage, uid_literature, cite_key)")
        _create_index_if_table(conn, READING_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_reading_state_preprocess ON {READING_STATE_TABLE_NAME}(pending_preprocess, preprocessed)")
        _create_index_if_table(conn, READING_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_reading_state_rough ON {READING_STATE_TABLE_NAME}(pending_rough_read, rough_read_done)")
        _create_index_if_table(conn, READING_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_reading_state_deep ON {READING_STATE_TABLE_NAME}(pending_deep_read, deep_read_done)")
        _create_index_if_table(conn, READING_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_reading_state_cite ON {READING_STATE_TABLE_NAME}(cite_key)")
        _create_index_if_table(conn, WORKSPACE_NODE_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_workspace_node_gate ON {WORKSPACE_NODE_STATE_TABLE_NAME}(gate_status, in_progress, pending_run)")
        _create_index_if_table(conn, LITERATURE_REVIEW_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_review_state_parse ON {LITERATURE_REVIEW_STATE_TABLE_NAME}(pending_review_parse, review_parse_ready)")
        _create_index_if_table(conn, LITERATURE_REVIEW_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_review_state_ref ON {LITERATURE_REVIEW_STATE_TABLE_NAME}(pending_reference_preprocess, reference_preprocessed)")
        _create_index_if_table(conn, LITERATURE_REVIEW_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_review_state_read ON {LITERATURE_REVIEW_STATE_TABLE_NAME}(pending_review_read, review_read_done)")
        _create_index_if_table(conn, LITERATURE_REVIEW_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_review_state_cite ON {LITERATURE_REVIEW_STATE_TABLE_NAME}(cite_key)")
        _create_index_if_table(conn, PARSE_ASSET_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_parse_asset_lit_level ON {PARSE_ASSET_TABLE_NAME}(uid_literature, parse_level)")
        _create_index_if_table(conn, PARSE_ASSET_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_parse_asset_current ON {PARSE_ASSET_TABLE_NAME}(parse_level, is_current)")
        conn.commit()


def _utc_now_iso() -> str:
    return now_iso()


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _normalize_queue_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    working = frame.copy() if frame is not None else pd.DataFrame()
    for column in READING_QUEUE_COLUMNS:
        if column not in working.columns:
            working[column] = None
    if "is_current" in working.columns:
        working["is_current"] = working["is_current"].fillna(1).astype(int)
    if "priority" in working.columns:
        working["priority"] = pd.to_numeric(working["priority"], errors="coerce")
    return working


def _queue_identity_key(row: pd.Series) -> tuple[str, str, str]:
    return (
        _stringify(row.get("stage")),
        _stringify(row.get("uid_literature")),
        _stringify(row.get("cite_key")),
    )


def _normalize_reading_state_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    working = frame.copy() if frame is not None else pd.DataFrame()
    for column in READING_STATE_COLUMNS:
        if column not in working.columns:
            working[column] = None
    integer_columns = [
        "pending_preprocess",
        "preprocessed",
        "pending_rough_read",
        "in_rough_read",
        "rough_read_done",
        "analysis_light_synced",
        "analysis_batch_synced",
        "pending_deep_read",
        "in_deep_read",
        "deep_read_done",
        "deep_read_count",
        "analysis_formal_synced",
        "innovation_synced",
    ]
    for column in integer_columns:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce").fillna(0).astype(int)
    return working


def _normalize_review_state_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    working = frame.copy() if frame is not None else pd.DataFrame()
    for column in REVIEW_STATE_COLUMNS:
        if column not in working.columns:
            working[column] = None
    integer_columns = [
        "pending_review_candidate",
        "review_candidate_ready",
        "pending_review_parse",
        "review_parse_ready",
        "pending_reference_preprocess",
        "reference_preprocessed",
        "pending_review_read",
        "in_review_read",
        "review_read_done",
        "review_read_count",
    ]
    for column in integer_columns:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce").fillna(0).astype(int)
    return working


def load_reading_state_df(
    db_path: Path,
    *,
    flag_filters: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """读取文献阅读状态表，并按标志列过滤。"""

    init_db(db_path)
    conn = _connect(db_path)
    try:
        state_df = pd.read_sql_query(f"SELECT * FROM {READING_STATE_TABLE_NAME}", conn)
    finally:
        conn.close()

    state_df = _normalize_reading_state_frame(state_df)
    for column, expected in (flag_filters or {}).items():
        if column not in state_df.columns:
            continue
        if isinstance(expected, bool):
            state_df = state_df[state_df[column].fillna(0).astype(int) == int(expected)]
        else:
            state_df = state_df[state_df[column].astype(str) == str(expected)]
    if state_df.empty:
        return _normalize_reading_state_frame(state_df)
    sort_columns = [column for column in ["pending_preprocess", "pending_rough_read", "pending_deep_read", "deep_read_count", "updated_at"] if column in state_df.columns]
    if sort_columns:
        ascending = [False, False, False, True, False][: len(sort_columns)]
        state_df = state_df.sort_values(by=sort_columns, ascending=ascending, na_position="last").reset_index(drop=True)
    return state_df


def upsert_reading_state_rows(db_path: Path, rows: Sequence[dict[str, Any]] | pd.DataFrame) -> None:
    """按 uid_literature 回写文献阅读状态表。"""

    init_db(db_path)
    incoming_df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows or []))
    if incoming_df.empty:
        return
    incoming_df = _normalize_reading_state_frame(incoming_df)
    now_iso = _utc_now_iso()
    for index, row in incoming_df.iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        if not uid_literature:
            continue
        incoming_df.at[index, "uid_literature"] = uid_literature
        incoming_df.at[index, "created_at"] = _stringify(row.get("created_at")) or now_iso
        incoming_df.at[index, "updated_at"] = _stringify(row.get("updated_at")) or now_iso

    incoming_df = incoming_df[incoming_df["uid_literature"].astype(str).ne("")].reset_index(drop=True)
    if incoming_df.empty:
        return

    writable_columns = list(READING_STATE_COLUMNS.keys())
    update_columns = [column for column in writable_columns if column != "uid_literature"]
    placeholders = ", ".join(["?"] * len(writable_columns))
    update_sql = ", ".join([f"{_quote_identifier(column)} = excluded.{_quote_identifier(column)}" for column in update_columns])

    with _connect(db_path) as conn:
        for _, row in incoming_df.iterrows():
            row_dict = row.to_dict()
            values = [None if pd.isna(row_dict.get(column)) else row_dict.get(column) for column in writable_columns]
            conn.execute(
                f"""
                INSERT INTO {READING_STATE_TABLE_NAME} ({', '.join(_quote_identifier(column) for column in writable_columns)})
                VALUES ({placeholders})
                ON CONFLICT(uid_literature) DO UPDATE SET
                    {update_sql}
                """,
                values,
            )
        conn.commit()


def load_review_state_df(
    db_path: Path,
    *,
    flag_filters: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """读取综述阅读状态表，并按标志列过滤。"""

    init_db(db_path)
    conn = _connect(db_path)
    try:
        state_df = pd.read_sql_query(f"SELECT * FROM {LITERATURE_REVIEW_STATE_TABLE_NAME}", conn)
    finally:
        conn.close()

    state_df = _normalize_review_state_frame(state_df)
    for column, expected in (flag_filters or {}).items():
        if column not in state_df.columns:
            continue
        if isinstance(expected, bool):
            state_df = state_df[state_df[column].fillna(0).astype(int) == int(expected)]
        else:
            state_df = state_df[state_df[column].astype(str) == str(expected)]
    return state_df.reset_index(drop=True)


def upsert_review_state_rows(db_path: Path, rows: Sequence[dict[str, Any]] | pd.DataFrame) -> None:
    """按 uid_literature 回写综述阅读状态表。"""

    init_db(db_path)
    incoming_df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows or []))
    if incoming_df.empty:
        return

    incoming_df = _normalize_review_state_frame(incoming_df)
    now_iso = _utc_now_iso()
    for index, row in incoming_df.iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        if not uid_literature:
            continue
        incoming_df.at[index, "uid_literature"] = uid_literature
        incoming_df.at[index, "updated_at"] = _stringify(row.get("updated_at")) or now_iso

    incoming_df = incoming_df[incoming_df["uid_literature"].astype(str).ne("")].reset_index(drop=True)
    if incoming_df.empty:
        return

    writable_columns = list(REVIEW_STATE_COLUMNS.keys())
    update_columns = [column for column in writable_columns if column != "uid_literature"]
    placeholders = ", ".join(["?"] * len(writable_columns))
    update_sql = ", ".join([f"{_quote_identifier(column)} = excluded.{_quote_identifier(column)}" for column in update_columns])

    with _connect(db_path) as conn:
        for _, row in incoming_df.iterrows():
            row_dict = row.to_dict()
            values = [None if pd.isna(row_dict.get(column)) else row_dict.get(column) for column in writable_columns]
            conn.execute(
                f"""
                INSERT INTO {LITERATURE_REVIEW_STATE_TABLE_NAME} ({', '.join(_quote_identifier(column) for column in writable_columns)})
                VALUES ({placeholders})
                ON CONFLICT(uid_literature) DO UPDATE SET
                    {update_sql}
                """,
                values,
            )
        conn.commit()


def load_workspace_node_state_df(db_path: Path) -> pd.DataFrame:
    """读取工作区节点状态表。"""

    init_db(db_path)
    conn = _connect(db_path)
    try:
        frame = pd.read_sql_query(f"SELECT * FROM {WORKSPACE_NODE_STATE_TABLE_NAME}", conn)
    finally:
        conn.close()
    return frame.reset_index(drop=True)


def upsert_workspace_node_state_rows(db_path: Path, rows: Sequence[dict[str, Any]] | pd.DataFrame) -> None:
    """按 node_code 回写工作区节点状态表。"""

    init_db(db_path)
    incoming_df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows or []))
    if incoming_df.empty:
        return

    for column in WORKSPACE_NODE_STATE_COLUMNS:
        if column not in incoming_df.columns:
            incoming_df[column] = None

    now_iso = _utc_now_iso()
    incoming_df["node_code"] = incoming_df["node_code"].astype(str).str.strip()
    incoming_df = incoming_df[incoming_df["node_code"].ne("")].reset_index(drop=True)
    if incoming_df.empty:
        return
    incoming_df["updated_at"] = incoming_df["updated_at"].fillna("").astype(str)
    incoming_df.loc[incoming_df["updated_at"].eq(""), "updated_at"] = now_iso

    writable_columns = list(WORKSPACE_NODE_STATE_COLUMNS.keys())
    update_columns = [column for column in writable_columns if column != "node_code"]
    placeholders = ", ".join(["?"] * len(writable_columns))
    update_sql = ", ".join([f"{_quote_identifier(column)} = excluded.{_quote_identifier(column)}" for column in update_columns])

    with _connect(db_path) as conn:
        for _, row in incoming_df.iterrows():
            row_dict = row.to_dict()
            values = [None if pd.isna(row_dict.get(column)) else row_dict.get(column) for column in writable_columns]
            conn.execute(
                f"""
                INSERT INTO {WORKSPACE_NODE_STATE_TABLE_NAME} ({', '.join(_quote_identifier(column) for column in writable_columns)})
                VALUES ({placeholders})
                ON CONFLICT(node_code) DO UPDATE SET
                    {update_sql}
                """,
                values,
            )
        conn.commit()


def load_reading_queue_df(
    db_path: Path,
    *,
    stage: str = "",
    only_current: bool = False,
    queue_statuses: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """读取阅读队列表，并按阶段/状态做过滤。"""

    init_db(db_path)
    conn = _connect(db_path)
    try:
        query = f"SELECT * FROM {READING_QUEUE_TABLE_NAME}"
        queue_df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    if queue_df.empty:
        return _normalize_queue_frame(queue_df)

    queue_df = _normalize_queue_frame(queue_df)
    if stage:
        queue_df = queue_df[queue_df["stage"].astype(str) == str(stage)]
    if only_current and "is_current" in queue_df.columns:
        queue_df = queue_df[queue_df["is_current"].fillna(0).astype(int) == 1]
    if queue_statuses:
        allowed = {str(item) for item in queue_statuses if _stringify(item)}
        queue_df = queue_df[queue_df["queue_status"].astype(str).isin(allowed)]
    if queue_df.empty:
        return _normalize_queue_frame(queue_df)
    sort_columns = [column for column in ["priority", "updated_at", "id"] if column in queue_df.columns]
    if sort_columns:
        queue_df = queue_df.sort_values(
            by=sort_columns,
            ascending=[False] * len(sort_columns),
            na_position="last",
        ).reset_index(drop=True)
    else:
        queue_df = queue_df.reset_index(drop=True)
    return queue_df


def upsert_reading_queue_rows(db_path: Path, rows: Sequence[dict[str, Any]] | pd.DataFrame) -> None:
    """按 stage + uid_literature + cite_key 回写阅读队列。"""

    init_db(db_path)
    incoming_df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows or []))
    if incoming_df.empty:
        return
    incoming_df = _normalize_queue_frame(incoming_df)
    now_iso = _utc_now_iso()

    for index, row in incoming_df.iterrows():
        incoming_df.at[index, "updated_at"] = _stringify(row.get("updated_at")) or now_iso
        incoming_df.at[index, "created_at"] = _stringify(row.get("created_at")) or now_iso
        incoming_df.at[index, "is_current"] = 1

    existing_df = load_reading_queue_df(db_path)
    existing_df = _normalize_queue_frame(existing_df)
    if not existing_df.empty:
        existing_df = existing_df.drop(columns=[column for column in ["id"] if column in existing_df.columns])

    if existing_df.empty:
        merged_df = incoming_df.copy()
    else:
        existing_map = {_queue_identity_key(row): idx for idx, row in existing_df.iterrows()}
        merged_df = existing_df.copy()
        for _, row in incoming_df.iterrows():
            row_key = _queue_identity_key(row)
            match_index = existing_map.get(row_key)
            if match_index is None:
                merged_df = pd.concat([merged_df, pd.DataFrame([row.to_dict()])], ignore_index=True)
                continue
            created_at = _stringify(merged_df.at[match_index, "created_at"]) or _stringify(row.get("created_at")) or now_iso
            for column in merged_df.columns:
                if column in row.index:
                    merged_df.at[match_index, column] = row.get(column)
            merged_df.at[match_index, "created_at"] = created_at
            merged_df.at[match_index, "updated_at"] = _stringify(row.get("updated_at")) or now_iso
            merged_df.at[match_index, "is_current"] = 1

    merged_df = _normalize_queue_frame(merged_df)
    merged_df = merged_df.drop_duplicates(subset=["stage", "uid_literature", "cite_key"], keep="last")
    save_dataframe_table(
        db_path,
        READING_QUEUE_TABLE_NAME,
        merged_df,
        if_exists="replace",
        unique_columns=["stage", "uid_literature", "cite_key"],
    )


def replace_tags_for_namespace(
    db_path: Path,
    *,
    namespace: str,
    tag_rows: Sequence[dict[str, Any]] | pd.DataFrame,
    source_type: str = "",
) -> None:
    """替换指定命名空间下的 literature_tags 记录。"""

    init_db(db_path)
    normalized_namespace = str(namespace or "").strip("/")
    if not normalized_namespace:
        raise ValueError("namespace 不能为空")

    incoming_df = tag_rows.copy() if isinstance(tag_rows, pd.DataFrame) else pd.DataFrame(list(tag_rows or []))
    if incoming_df.empty:
        return

    with _connect(db_path) as conn:
        existing_df = pd.read_sql_query(f"SELECT * FROM {LITERATURE_TAG_TABLE_NAME}", conn)

    if existing_df.empty:
        existing_df = pd.DataFrame(columns=["uid_literature", "cite_key", "tag", "tag_norm", "source_type", "created_at", "updated_at"])

    for column in ["uid_literature", "cite_key", "tag", "tag_norm", "source_type", "created_at", "updated_at"]:
        if column not in existing_df.columns:
            existing_df[column] = ""

    identities: set[tuple[str, str]] = set()
    normalized_rows: list[dict[str, Any]] = []
    now_iso = _utc_now_iso()
    for _, row in incoming_df.iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        raw_tag = _stringify(row.get("tag"))
        if not raw_tag or (not uid_literature and not cite_key):
            continue
        full_tag = raw_tag if raw_tag.startswith(normalized_namespace + "/") or raw_tag == normalized_namespace else f"{normalized_namespace}/{raw_tag.strip('/')}"
        identities.add((uid_literature, cite_key))
        normalized_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "tag": full_tag,
                "tag_norm": full_tag.lower(),
                "source_type": _stringify(row.get("source_type")) or source_type,
                "created_at": _stringify(row.get("created_at")) or now_iso,
                "updated_at": _stringify(row.get("updated_at")) or now_iso,
            }
        )

    if not normalized_rows:
        return

    def _should_drop(existing_row: pd.Series) -> bool:
        identity = (_stringify(existing_row.get("uid_literature")), _stringify(existing_row.get("cite_key")))
        tag_text = _stringify(existing_row.get("tag"))
        return identity in identities and (tag_text == normalized_namespace or tag_text.startswith(normalized_namespace + "/"))

    filtered_df = existing_df[~existing_df.apply(_should_drop, axis=1)].copy()
    merged_df = pd.concat([filtered_df, pd.DataFrame(normalized_rows)], ignore_index=True)
    merged_df = merged_df.drop_duplicates(subset=["uid_literature", "cite_key", "tag"], keep="last")
    save_tables(
        db_path,
        tags_df=merged_df,
        if_exists="replace",
    )


def import_from_csv(
    items_csv: Path,
    attachments_csv: Optional[Path],
    db_path: Path,
    if_exists: str = "replace",
    tags_csv: Optional[Path] = None,
) -> None:
    """将 CSV 导入到 SQLite。若 `if_exists==replace` 会覆盖已有表。

    Args:
        items_csv: 文献主表 CSV（`literatures.csv`）。
        attachments_csv: 附件表 CSV（`literature_attachments.csv`），可为 None。
        db_path: 目标 sqlite 文件路径。
        if_exists: pandas.to_sql 的行为（replace/append/skip）。
    """
    literatures_df = pd.read_csv(items_csv, encoding="utf-8-sig") if items_csv and items_csv.exists() else None
    attachments_df = pd.read_csv(attachments_csv, encoding="utf-8-sig") if attachments_csv and attachments_csv.exists() else None
    tags_df = pd.read_csv(tags_csv, encoding="utf-8-sig") if tags_csv and tags_csv.exists() else None
    save_tables(
        db_path,
        literatures_df=literatures_df,
        attachments_df=attachments_df,
        tags_df=tags_df,
        if_exists=if_exists,
    )


def query_literatures(db_path: Path, sql: str = "SELECT * FROM literatures LIMIT 1000") -> pd.DataFrame:
    conn = _connect(db_path)
    try:
        return pd.read_sql_query(sql, conn)
    finally:
        conn.close()


def load_literatures_df(db_path: Path) -> pd.DataFrame:
    """读取文献主表为 DataFrame。"""
    init_db(db_path)
    return query_literatures(db_path, sql=f"SELECT * FROM {LITERATURE_TABLE_NAME}")


def load_attachments_df(db_path: Path) -> pd.DataFrame:
    """读取文献附件表为 DataFrame。"""
    init_db(db_path)
    conn = _connect(db_path)
    try:
        link_count = conn.execute(f"SELECT COUNT(1) FROM {ATTACHMENT_LINK_TABLE_NAME}").fetchone()
        if int((link_count or [0])[0] or 0) > 0:
            return pd.read_sql_query(
                f"""
                SELECT
                    COALESCE(lnk.legacy_uid_attachment, lnk.uid_attachment_link, att.uid_attachment) AS uid_attachment,
                    lnk.uid_literature,
                    att.attachment_name,
                    COALESCE(NULLIF(lnk.link_role, ''), att.attachment_type) AS attachment_type,
                    att.file_ext,
                    att.storage_path,
                    att.source_path,
                    att.checksum,
                    COALESCE(lnk.is_primary, 0) AS is_primary,
                    att.status,
                    COALESCE(lnk.created_at, att.created_at) AS created_at,
                    COALESCE(lnk.updated_at, att.updated_at) AS updated_at
                FROM {ATTACHMENT_LINK_TABLE_NAME} AS lnk
                LEFT JOIN {ATTACHMENT_TABLE_NAME} AS att
                    ON att.uid_attachment = lnk.uid_attachment
                ORDER BY lnk.uid_literature, COALESCE(lnk.is_primary, 0) DESC, att.attachment_name
                """,
                conn,
            )
        return pd.read_sql_query(f"SELECT * FROM {LITERATURE_ATTACHMENT_TABLE_NAME}", conn)
    finally:
        conn.close()


def load_tags_df(db_path: Path) -> pd.DataFrame:
    """读取文献标签关系表为 DataFrame。"""
    init_db(db_path)
    conn = _connect(db_path)
    try:
        return pd.read_sql_query(f"SELECT * FROM {LITERATURE_TAG_TABLE_NAME}", conn)
    finally:
        conn.close()


def load_chunk_sets_df(db_path: Path) -> pd.DataFrame:
    """读取 chunk 批次索引表。"""

    init_db(db_path)
    conn = _connect(db_path)
    try:
        return pd.read_sql_query(f"SELECT * FROM {LITERATURE_CHUNK_SET_TABLE_NAME}", conn)
    finally:
        conn.close()


def load_chunks_df(db_path: Path) -> pd.DataFrame:
    """读取 chunk 明细索引表。"""

    init_db(db_path)
    conn = _connect(db_path)
    try:
        return pd.read_sql_query(f"SELECT * FROM {LITERATURE_CHUNK_TABLE_NAME}", conn)
    finally:
        conn.close()


def load_parse_assets_df(
    db_path: Path,
    *,
    parse_level: str = "",
    only_current: bool = False,
    parse_statuses: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """读取 parse asset 当前态表。"""

    init_db(db_path)
    conn = _connect(db_path)
    try:
        asset_df = pd.read_sql_query(f"SELECT * FROM {PARSE_ASSET_TABLE_NAME}", conn)
    finally:
        conn.close()

    if asset_df.empty:
        return pd.DataFrame(columns=[*PARSE_ASSET_COLUMNS.keys()])

    if parse_level:
        asset_df = asset_df[asset_df["parse_level"].astype(str) == str(parse_level)]
    if only_current:
        asset_df = asset_df[asset_df["is_current"].fillna(0).astype(int) == 1]
    if parse_statuses:
        allowed = {str(item) for item in parse_statuses if _stringify(item)}
        asset_df = asset_df[asset_df["parse_status"].astype(str).isin(allowed)]

    if asset_df.empty:
        return asset_df.reset_index(drop=True)
    return asset_df.reset_index(drop=True)


def upsert_parse_asset_rows(db_path: Path, rows: Sequence[dict[str, Any]] | pd.DataFrame) -> None:
    """回写 parse asset 表，并同步文献主表 structured 当前态。"""

    incoming_df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows or []))
    if incoming_df.empty:
        return

    init_db(db_path)
    with _connect(db_path) as conn:
        for _, row in incoming_df.fillna("").iterrows():
            uid_literature = _stringify(row.get("uid_literature"))
            cite_key = _stringify(row.get("cite_key"))
            structured_path = _stringify(
                row.get("normalized_structured_path")
                or row.get("structured_abs_path")
            )
            parse_level = _stringify(row.get("parse_level") or row.get("task_type"))
            backend = _stringify(row.get("backend") or row.get("structured_backend"))
            parse_status = _stringify(row.get("parse_status")) or "ready"
            updated_at = _stringify(row.get("structured_updated_at") or row.get("updated_at")) or _utc_now_iso()
            created_at = _stringify(row.get("created_at")) or updated_at
            asset_uid = _stringify(row.get("asset_uid")) or hashlib.md5(
                f"{uid_literature}|{cite_key}|{parse_level}|{structured_path}".encode("utf-8")
            ).hexdigest()

            if not uid_literature and not cite_key:
                continue

            conn.execute(
                f"""
                INSERT INTO {PARSE_ASSET_TABLE_NAME}
                    (asset_uid, uid_literature, cite_key, uid_attachment, parse_level, backend, model_name,
                     asset_dir, normalized_structured_path, reconstructed_markdown_path, linear_index_path,
                     elements_path, chunks_jsonl_path, parse_record_path, quality_report_path, parse_status,
                     last_run_uid, is_current, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_uid)
                DO UPDATE SET
                    uid_literature=excluded.uid_literature,
                    cite_key=excluded.cite_key,
                    uid_attachment=excluded.uid_attachment,
                    parse_level=excluded.parse_level,
                    backend=excluded.backend,
                    model_name=excluded.model_name,
                    asset_dir=excluded.asset_dir,
                    normalized_structured_path=excluded.normalized_structured_path,
                    reconstructed_markdown_path=excluded.reconstructed_markdown_path,
                    linear_index_path=excluded.linear_index_path,
                    elements_path=excluded.elements_path,
                    chunks_jsonl_path=excluded.chunks_jsonl_path,
                    parse_record_path=excluded.parse_record_path,
                    quality_report_path=excluded.quality_report_path,
                    parse_status=excluded.parse_status,
                    last_run_uid=excluded.last_run_uid,
                    is_current=excluded.is_current,
                    updated_at=excluded.updated_at
                """,
                (
                    asset_uid,
                    uid_literature,
                    cite_key,
                    _stringify(row.get("uid_attachment")),
                    parse_level,
                    backend,
                    _stringify(row.get("model_name") or row.get("llm_model")),
                    _stringify(row.get("asset_dir")) or (str(Path(structured_path).parent) if structured_path else ""),
                    structured_path,
                    _stringify(row.get("reconstructed_markdown_path")),
                    _stringify(row.get("linear_index_path")),
                    _stringify(row.get("elements_path")),
                    _stringify(row.get("chunks_jsonl_path")),
                    _stringify(row.get("parse_record_path")),
                    _stringify(row.get("quality_report_path")),
                    parse_status,
                    _stringify(row.get("last_run_uid") or row.get("run_uid")),
                    int(row.get("is_current") or 1),
                    created_at,
                    updated_at,
                ),
            )

            assignments = [
                "structured_status = ?",
                "structured_abs_path = ?",
                "structured_backend = ?",
                "structured_task_type = ?",
                "structured_updated_at = ?",
            ]
            params: list[object] = [
                parse_status,
                structured_path,
                backend,
                parse_level,
                updated_at,
            ]
            variant_column = get_pdf_structured_variant_column(backend, parse_level)
            if variant_column and structured_path:
                assignments.append(f"{variant_column} = ?")
                params.append(structured_path)

            where_sql = "uid_literature = ?"
            identity = uid_literature
            if not uid_literature:
                where_sql = "cite_key = ?"
                identity = cite_key
            params.append(identity)

            conn.execute(
                f"""
                UPDATE {LITERATURE_TABLE_NAME}
                SET
                    {",\n                    ".join(assignments)}
                WHERE {where_sql}
                """,
                tuple(params),
            )
        conn.commit()


def save_structured_state(
    db_path: Path,
    *,
    uid_literature: str,
    structured_status: str,
    structured_abs_path: str,
    structured_backend: str,
    structured_task_type: str,
    structured_updated_at: str,
    structured_schema_version: str,
    structured_text_length: int,
    structured_reference_count: int,
) -> None:
    """按文献 UID 回写结构化状态字段。"""

    init_db(db_path)
    upsert_parse_asset_rows(
        db_path,
        [
            {
                "uid_literature": uid_literature,
                "parse_level": structured_task_type,
                "backend": structured_backend,
                "parse_status": structured_status,
                "normalized_structured_path": structured_abs_path,
                "is_current": 1,
                "updated_at": structured_updated_at,
            }
        ],
    )
    variant_column = get_pdf_structured_variant_column(structured_backend, structured_task_type)
    with _connect(db_path) as conn:
        assignments = [
            "structured_status = ?",
            "structured_abs_path = ?",
            "structured_backend = ?",
            "structured_task_type = ?",
            "structured_updated_at = ?",
            "structured_schema_version = ?",
            "structured_text_length = ?",
            "structured_reference_count = ?",
        ]
        params: list[object] = [
            structured_status,
            structured_abs_path,
            structured_backend,
            structured_task_type,
            structured_updated_at,
            structured_schema_version,
            int(structured_text_length or 0),
            int(structured_reference_count or 0),
        ]
        if variant_column:
            assignments.append(f"{variant_column} = ?")
            params.append(structured_abs_path)
        params.append(uid_literature)
        cursor = conn.execute(
            f"""
            UPDATE {LITERATURE_TABLE_NAME}
            SET
                {",\n                ".join(assignments)}
            WHERE uid_literature = ?
            """,
            tuple(params),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"uid_literature={uid_literature} not found")
        conn.commit()


def get_structured_state(db_path: Path, uid_literature: str) -> dict:
    """读取单篇文献的结构化状态。"""

    init_db(db_path)
    conn = _connect(db_path)
    try:
        df = pd.read_sql_query(
            f"SELECT uid_literature, structured_status, structured_abs_path, structured_backend, structured_task_type, structured_updated_at, structured_schema_version, structured_text_length, structured_reference_count, structured_path_local_pipeline_v2_reference_context, structured_path_local_pipeline_v2_full_fine_grained, structured_path_babeldoc_reference_context, structured_path_babeldoc_full_fine_grained FROM {LITERATURE_TABLE_NAME} WHERE uid_literature = ?",
            conn,
            params=(uid_literature,),
        )
        if df.empty:
            raise KeyError(f"uid={uid_literature} not found")
        return df.iloc[0].to_dict()
    finally:
        conn.close()


def replace_chunk_set_records(
    db_path: Path,
    *,
    chunk_set_row: dict,
    chunk_rows: List[dict],
) -> None:
    """按 chunks_uid 替换 chunk 批次与明细索引。"""

    init_db(db_path)
    chunks_uid = str(chunk_set_row.get("chunks_uid") or "").strip()
    if not chunks_uid:
        raise ValueError("chunk_set_row.chunks_uid 不能为空")

    with _connect(db_path) as conn:
        conn.execute(
            f"DELETE FROM {LITERATURE_CHUNK_TABLE_NAME} WHERE chunks_uid = ?",
            (chunks_uid,),
        )
        conn.execute(
            f"DELETE FROM {LITERATURE_CHUNK_SET_TABLE_NAME} WHERE chunks_uid = ?",
            (chunks_uid,),
        )
        pd.DataFrame([chunk_set_row]).where(pd.notnull(pd.DataFrame([chunk_set_row])), None).to_sql(
            LITERATURE_CHUNK_SET_TABLE_NAME,
            conn,
            if_exists="append",
            index=False,
        )
        if chunk_rows:
            working = pd.DataFrame(chunk_rows).where(pd.notnull(pd.DataFrame(chunk_rows)), None)
            working.to_sql(LITERATURE_CHUNK_TABLE_NAME, conn, if_exists="append", index=False)
        conn.commit()


def save_dataframe_table(
    db_path: Path,
    table_name: str,
    table_df: pd.DataFrame,
    *,
    if_exists: str = "replace",
    unique_columns: Optional[List[str]] = None,
) -> None:
    """把任意 DataFrame 直接写入 SQLite 的指定表。"""

    init_db(db_path)
    if table_df is None or table_df.shape[1] == 0:
        return
    working = table_df.where(pd.notnull(table_df), None) if table_df is not None else pd.DataFrame()
    with _connect(db_path) as conn:
        working.to_sql(table_name, conn, if_exists=if_exists, index=False)
        if unique_columns:
            index_name = f"idx_{table_name}_{'_'.join(unique_columns)}"
            columns_sql = ", ".join(_quote_identifier(column) for column in unique_columns)
            conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {_quote_identifier(index_name)} ON {_quote_identifier(table_name)} ({columns_sql})"
            )
        conn.commit()


def _stable_attachment_uid(uid_literature: str, storage_path: str) -> str:
    raw = f"{uid_literature}|{storage_path}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()


_LITERATURE_ATTACHMENT_COLUMNS: List[str] = [
    "uid_attachment",
    "uid_literature",
    "attachment_name",
    "attachment_type",
    "file_ext",
    "storage_path",
    "source_path",
    "checksum",
    "is_primary",
    "status",
    "created_at",
    "updated_at",
]


_LITERATURE_TAG_COLUMNS: List[str] = [
    "uid_literature",
    "cite_key",
    "tag",
    "tag_norm",
    "source_type",
    "created_at",
    "updated_at",
]


def _empty_attachments_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_LITERATURE_ATTACHMENT_COLUMNS)


def _empty_tags_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_LITERATURE_TAG_COLUMNS)


def _ensure_reference_columns(frame: pd.DataFrame | None, columns: Sequence[str]) -> pd.DataFrame:
    working = frame.copy() if frame is not None else pd.DataFrame()
    for column in columns:
        if column not in working.columns:
            working[column] = None
    return working


def _normalize_literatures_df(frame: pd.DataFrame | None) -> pd.DataFrame:
    working = frame.copy() if frame is not None else pd.DataFrame()
    if working.empty:
        return working
    if "id" not in working.columns and str(working.index.name or "") == "id":
        working = working.reset_index()
    if "id" in working.columns:
        working["id"] = pd.to_numeric(working["id"], errors="coerce")
    return working


def _normalize_attachments_df(frame: pd.DataFrame | None) -> pd.DataFrame:
    working = _ensure_reference_columns(frame, _LITERATURE_ATTACHMENT_COLUMNS)
    if working.empty:
        return _empty_attachments_df()
    working["is_primary"] = pd.to_numeric(working["is_primary"], errors="coerce").fillna(0).astype(int)
    return working


def _stable_attachment_entity_uid(checksum: str, storage_path: str, source_path: str, attachment_name: str) -> str:
    token = _stringify(checksum) or _stringify(storage_path) or _stringify(source_path) or _stringify(attachment_name)
    normalized = token.lower()
    return f"att-{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def _stable_attachment_link_uid(uid_literature: str, uid_attachment: str, legacy_uid_attachment: str) -> str:
    token = _stringify(legacy_uid_attachment) or f"{_stringify(uid_literature)}|{_stringify(uid_attachment)}"
    normalized = token.lower()
    return f"attlnk-{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def _build_normalized_attachment_frames(flat_attachments_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    attachment_columns = [
        "uid_attachment",
        "attachment_name",
        "attachment_type",
        "file_ext",
        "storage_path",
        "source_path",
        "checksum",
        "status",
        "created_at",
        "updated_at",
    ]
    link_columns = [
        "uid_attachment_link",
        "uid_literature",
        "uid_attachment",
        "link_role",
        "is_primary",
        "source_type",
        "legacy_uid_attachment",
        "created_at",
        "updated_at",
    ]
    if flat_attachments_df is None or flat_attachments_df.empty:
        return pd.DataFrame(columns=attachment_columns), pd.DataFrame(columns=link_columns)

    attachment_rows_by_uid: dict[str, dict[str, Any]] = {}
    link_rows: list[dict[str, Any]] = []
    now = _utc_now_iso()
    for _, row in flat_attachments_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        if not uid_literature:
            continue
        checksum = _stringify(row.get("checksum"))
        storage_path = _stringify(row.get("storage_path"))
        source_path = _stringify(row.get("source_path"))
        attachment_name = _stringify(row.get("attachment_name"))
        if not any([checksum, storage_path, source_path, attachment_name]):
            continue

        uid_attachment = _stable_attachment_entity_uid(checksum, storage_path, source_path, attachment_name)
        legacy_uid_attachment = _stringify(row.get("uid_attachment"))
        existing_attachment = attachment_rows_by_uid.get(uid_attachment, {})
        attachment_rows_by_uid[uid_attachment] = {
            "uid_attachment": uid_attachment,
            "attachment_name": attachment_name or _stringify(existing_attachment.get("attachment_name")),
            "attachment_type": _stringify(row.get("attachment_type")) or _stringify(existing_attachment.get("attachment_type")),
            "file_ext": _stringify(row.get("file_ext")) or _stringify(existing_attachment.get("file_ext")),
            "storage_path": storage_path or _stringify(existing_attachment.get("storage_path")),
            "source_path": source_path or _stringify(existing_attachment.get("source_path")),
            "checksum": checksum or _stringify(existing_attachment.get("checksum")),
            "status": _stringify(row.get("status")) or _stringify(existing_attachment.get("status")) or "available",
            "created_at": _stringify(existing_attachment.get("created_at")) or _stringify(row.get("created_at")) or now,
            "updated_at": _stringify(row.get("updated_at")) or _stringify(existing_attachment.get("updated_at")) or now,
        }
        link_rows.append(
            {
                "uid_attachment_link": _stable_attachment_link_uid(uid_literature, uid_attachment, legacy_uid_attachment),
                "uid_literature": uid_literature,
                "uid_attachment": uid_attachment,
                "link_role": _stringify(row.get("attachment_type")) or "attached",
                "is_primary": int(pd.to_numeric(row.get("is_primary"), errors="coerce") or 0),
                "source_type": "bibliodb_flat_attachments",
                "legacy_uid_attachment": legacy_uid_attachment,
                "created_at": _stringify(row.get("created_at")) or now,
                "updated_at": _stringify(row.get("updated_at")) or now,
            }
        )

    attachments_df = pd.DataFrame(list(attachment_rows_by_uid.values()), columns=attachment_columns)
    links_df = pd.DataFrame(link_rows, columns=link_columns)
    if not links_df.empty:
        links_df = links_df.sort_values(
            by=["uid_literature", "uid_attachment", "is_primary", "updated_at"],
            ascending=[True, True, False, False],
            na_position="last",
        ).drop_duplicates(subset=["uid_literature", "uid_attachment"], keep="first").reset_index(drop=True)
    return attachments_df, links_df


def _write_normalized_attachment_tables(
    conn: sqlite3.Connection,
    flat_attachments_df: pd.DataFrame,
    *,
    if_exists: str,
) -> None:
    attachments_df, links_df = _build_normalized_attachment_frames(flat_attachments_df)
    _ensure_columns(conn, ATTACHMENT_TABLE_NAME, {column: "TEXT" for column in attachments_df.columns})
    _ensure_columns(conn, ATTACHMENT_LINK_TABLE_NAME, {column: "TEXT" for column in links_df.columns})

    if if_exists == "replace":
        _delete_all_if_table(conn, ATTACHMENT_LINK_TABLE_NAME)
        _delete_all_if_table(conn, ATTACHMENT_TABLE_NAME)

    if not attachments_df.empty:
        attachments_df.where(pd.notnull(attachments_df), None).to_sql(
            ATTACHMENT_TABLE_NAME,
            conn,
            if_exists="append",
            index=False,
        )
    if not links_df.empty:
        links_df.where(pd.notnull(links_df), None).to_sql(
            ATTACHMENT_LINK_TABLE_NAME,
            conn,
            if_exists="append",
            index=False,
        )


def _normalize_tags_df(frame: pd.DataFrame | None) -> pd.DataFrame:
    working = _ensure_reference_columns(frame, _LITERATURE_TAG_COLUMNS)
    if working.empty:
        return _empty_tags_df()
    return working


def _is_empty_scalar(value: Any) -> bool:
    return _stringify(value) == ""


def _find_unique_uid(frame: pd.DataFrame, mask: pd.Series) -> str:
    rows = frame[mask]
    if rows.empty:
        return ""
    uid_values = rows.get("uid_literature", pd.Series(dtype=str)).astype(str).dropna().unique().tolist()
    if len(uid_values) != 1:
        return ""
    return _stringify(uid_values[0])


def _find_matching_literature_uid(current_df: pd.DataFrame, incoming_row: pd.Series) -> str:
    if current_df.empty:
        return ""

    incoming_uid = _stringify(incoming_row.get("uid_literature"))
    if incoming_uid:
        matched = _find_unique_uid(
            current_df,
            current_df.get("uid_literature", pd.Series(dtype=str)).astype(str) == incoming_uid,
        )
        if matched:
            return matched

    incoming_cite_key = _stringify(incoming_row.get("cite_key"))
    if incoming_cite_key:
        matched = _find_unique_uid(
            current_df,
            current_df.get("cite_key", pd.Series(dtype=str)).astype(str) == incoming_cite_key,
        )
        if matched:
            return matched

    title_norm = _stringify(incoming_row.get("title_norm"))
    first_author = _stringify(incoming_row.get("first_author"))
    year = _stringify(incoming_row.get("year"))
    if title_norm and first_author and year:
        matched = _find_unique_uid(
            current_df,
            (
                current_df.get("title_norm", pd.Series(dtype=str)).astype(str) == title_norm
            )
            & (
                current_df.get("first_author", pd.Series(dtype=str)).astype(str) == first_author
            )
            & (
                current_df.get("year", pd.Series(dtype=str)).astype(str) == year
            ),
        )
        if matched:
            return matched

    clean_title = _stringify(incoming_row.get("clean_title"))
    if clean_title and year:
        matched = _find_unique_uid(
            current_df,
            (
                current_df.get("clean_title", pd.Series(dtype=str)).astype(str) == clean_title
            )
            & (
                current_df.get("year", pd.Series(dtype=str)).astype(str) == year
            ),
        )
        if matched:
            return matched

    return ""


def _merge_literature_row(existing_row: Dict[str, Any], incoming_row: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing_row)
    prefer_longer_columns = {"abstract", "keywords", "authors"}
    prefer_existing_columns = {
        "id",
        "uid_literature",
        "cite_key",
        "title",
        "title_norm",
        "clean_title",
        "first_author",
        "year",
        "has_fulltext",
        "primary_attachment_name",
        "pdf_path",
        "created_at",
    }

    for column, incoming_value in incoming_row.items():
        existing_value = merged.get(column)
        incoming_text = _stringify(incoming_value)
        existing_text = _stringify(existing_value)
        if column in prefer_existing_columns:
            if not existing_text and incoming_text:
                merged[column] = incoming_value
            continue
        if column in prefer_longer_columns:
            if len(incoming_text) > len(existing_text):
                merged[column] = incoming_value
            continue
        if not existing_text and incoming_text:
            merged[column] = incoming_value
    return merged


def _attachment_identity(row: pd.Series | Dict[str, Any]) -> str:
    attachment_name = _stringify(row.get("attachment_name"))
    if attachment_name:
        return attachment_name.lower()
    storage_name = Path(_stringify(row.get("storage_path")) or _stringify(row.get("source_path"))).name
    return storage_name.lower()


def _attachment_timestamp(row: pd.Series | Dict[str, Any]) -> float:
    for key in ["storage_path", "source_path"]:
        raw_path = _stringify(row.get(key))
        if not raw_path:
            continue
        path = Path(raw_path)
        if path.exists() and path.is_file():
            try:
                return float(path.stat().st_mtime)
            except OSError:
                continue
    return 0.0


def _attachment_sort_key(row: pd.Series | Dict[str, Any]) -> tuple[int, int, float, int, str]:
    attachment_type = _stringify(row.get("attachment_type")).lower()
    storage_path = _stringify(row.get("storage_path"))
    source_path = _stringify(row.get("source_path"))
    exists_flag = int(any(Path(path_text).exists() for path_text in [storage_path, source_path] if path_text))
    fulltext_flag = int(attachment_type in {"fulltext", "pdf"} or _stringify(row.get("file_ext")).lower() == "pdf")
    primary_flag = int(pd.to_numeric(row.get("is_primary"), errors="coerce") if hasattr(pd, "to_numeric") else row.get("is_primary") or 0)
    return (
        fulltext_flag,
        primary_flag,
        exists_flag,
        _attachment_timestamp(row),
        _attachment_identity(row),
    )


def _build_attachment_uid_from_row(uid_literature: str, row: Dict[str, Any]) -> str:
    token = _stringify(row.get("storage_path")) or _stringify(row.get("source_path")) or _stringify(row.get("attachment_name"))
    return _stable_attachment_uid(uid_literature, token)


def _merge_attachment_rows(rows: List[Dict[str, Any]], uid_literature: str) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        key = _attachment_identity(row)
        if not key:
            continue
        normalized = dict(row)
        normalized["uid_literature"] = uid_literature
        grouped.setdefault(key, []).append(normalized)

    merged_rows: List[Dict[str, Any]] = []
    now_iso = _utc_now_iso()
    for same_name_rows in grouped.values():
        chosen = max(same_name_rows, key=_attachment_sort_key)
        chosen["uid_literature"] = uid_literature
        chosen["uid_attachment"] = _build_attachment_uid_from_row(uid_literature, chosen)
        chosen["created_at"] = _stringify(chosen.get("created_at")) or now_iso
        chosen["updated_at"] = now_iso
        chosen["status"] = _stringify(chosen.get("status")) or "available"
        merged_rows.append(chosen)

    if not merged_rows:
        return []

    primary_index = max(range(len(merged_rows)), key=lambda idx: _attachment_sort_key(merged_rows[idx]))
    for idx, row in enumerate(merged_rows):
        row["is_primary"] = 1 if idx == primary_index else 0
        row["file_ext"] = _stringify(row.get("file_ext")) or Path(_stringify(row.get("attachment_name"))).suffix.lower().lstrip(".")
    merged_rows.sort(key=lambda item: (_attachment_sort_key(item), _attachment_identity(item)), reverse=True)
    return merged_rows


def _refresh_literatures_from_attachments(literatures_df: pd.DataFrame, attachments_df: pd.DataFrame) -> pd.DataFrame:
    working = literatures_df.copy()
    attachment_working = _normalize_attachments_df(attachments_df)
    if working.empty:
        return working
    if attachment_working.empty:
        if "has_fulltext" in working.columns:
            working["has_fulltext"] = 0
        if "primary_attachment_name" in working.columns:
            working["primary_attachment_name"] = ""
        if "pdf_path" in working.columns:
            working["pdf_path"] = ""
        return working

    indexed_rows: Dict[str, Dict[str, Any]] = {}
    for _, row in attachment_working.iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        if not uid_literature:
            continue
        best_row = indexed_rows.get(uid_literature)
        if best_row is None or _attachment_sort_key(row) > _attachment_sort_key(best_row):
            indexed_rows[uid_literature] = row.to_dict()

    for index, row in working.iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        selected_attachment = indexed_rows.get(uid_literature)
        if selected_attachment is None:
            working.at[index, "has_fulltext"] = 0
            working.at[index, "primary_attachment_name"] = ""
            working.at[index, "pdf_path"] = ""
            continue
        working.at[index, "has_fulltext"] = 1
        working.at[index, "primary_attachment_name"] = _stringify(selected_attachment.get("attachment_name"))
        working.at[index, "pdf_path"] = _stringify(selected_attachment.get("storage_path")) or _stringify(selected_attachment.get("source_path"))
    return working


def merge_reference_records(
    *,
    existing_literatures_df: pd.DataFrame | None,
    existing_attachments_df: pd.DataFrame | None,
    existing_tags_df: pd.DataFrame | None,
    incoming_literatures_df: pd.DataFrame | None,
    incoming_attachments_df: pd.DataFrame | None,
    incoming_tags_df: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """把现有文献表与新导入文献表做增量归并。"""

    existing_literatures = _normalize_literatures_df(existing_literatures_df)
    incoming_literatures = _normalize_literatures_df(incoming_literatures_df)
    existing_attachments = _normalize_attachments_df(existing_attachments_df)
    incoming_attachments = _normalize_attachments_df(incoming_attachments_df)
    existing_tags = _normalize_tags_df(existing_tags_df)
    incoming_tags = _normalize_tags_df(incoming_tags_df)
    now_iso_text = now_iso()

    if incoming_literatures.empty:
        return existing_literatures, existing_attachments, existing_tags, {
            "incoming_count": 0,
            "matched_existing_count": 0,
            "inserted_count": 0,
            "final_literature_count": int(len(existing_literatures)),
            "uid_mapping": {},
        }

    current_df = existing_literatures.copy()
    next_id = int(pd.to_numeric(current_df.get("id", pd.Series(dtype=float)), errors="coerce").max()) if not current_df.empty and "id" in current_df.columns else 0
    if pd.isna(next_id):
        next_id = 0

    uid_mapping: Dict[str, str] = {}
    matched_existing_count = 0
    inserted_count = 0

    for _, incoming_row in incoming_literatures.iterrows():
        incoming_dict = incoming_row.to_dict()
        incoming_uid = _stringify(incoming_dict.get("uid_literature"))
        if not incoming_uid:
            continue
        matched_uid = _find_matching_literature_uid(current_df, incoming_row)
        if matched_uid:
            mask = current_df.get("uid_literature", pd.Series(dtype=str)).astype(str) == matched_uid
            if not mask.any():
                continue
            existing_index = current_df[mask].index[0]
            merged_row = _merge_literature_row(current_df.loc[existing_index].to_dict(), incoming_dict)
            merged_row["uid_literature"] = matched_uid
            merged_row["created_at"] = _stringify(merged_row.get("created_at")) or _stringify(incoming_dict.get("created_at")) or now_iso_text
            merged_row["updated_at"] = now_iso_text
            merged_row["imported_at"] = now_iso_text
            current_df.loc[existing_index, list(merged_row.keys())] = list(merged_row.values())
            uid_mapping[incoming_uid] = matched_uid
            matched_existing_count += 1
            continue

        next_id += 1
        new_row = incoming_dict
        new_row["id"] = next_id
        new_row["created_at"] = _stringify(new_row.get("created_at")) or now_iso_text
        new_row["updated_at"] = _stringify(new_row.get("updated_at")) or now_iso_text
        new_row["imported_at"] = _stringify(new_row.get("imported_at")) or now_iso_text
        current_df = pd.concat([current_df, pd.DataFrame([new_row])], ignore_index=True)
        uid_mapping[incoming_uid] = incoming_uid
        inserted_count += 1

    merged_attachment_rows: List[Dict[str, Any]] = []
    attachment_uid_order = current_df.get("uid_literature", pd.Series(dtype=str)).astype(str).tolist() if not current_df.empty else []
    existing_attachment_records = existing_attachments.to_dict(orient="records") if not existing_attachments.empty else []
    incoming_attachment_records = incoming_attachments.to_dict(orient="records") if not incoming_attachments.empty else []

    for uid_literature in attachment_uid_order:
        combined_rows: List[Dict[str, Any]] = []
        combined_rows.extend([
            row for row in existing_attachment_records if _stringify(row.get("uid_literature")) == uid_literature
        ])
        combined_rows.extend([
            {**row, "uid_literature": uid_mapping.get(_stringify(row.get("uid_literature")), uid_literature)}
            for row in incoming_attachment_records
            if uid_mapping.get(_stringify(row.get("uid_literature")), _stringify(row.get("uid_literature"))) == uid_literature
        ])
        merged_attachment_rows.extend(_merge_attachment_rows(combined_rows, uid_literature))

    merged_attachments_df = _normalize_attachments_df(pd.DataFrame(merged_attachment_rows))
    current_df = _refresh_literatures_from_attachments(current_df, merged_attachments_df)

    tag_rows: List[Dict[str, Any]] = []
    if not existing_tags.empty:
        tag_rows.extend(existing_tags.to_dict(orient="records"))
    if not incoming_tags.empty:
        cite_lookup = {
            _stringify(row.get("uid_literature")): _stringify(row.get("cite_key"))
            for row in current_df.to_dict(orient="records")
        }
        for row in incoming_tags.to_dict(orient="records"):
            incoming_uid = _stringify(row.get("uid_literature"))
            target_uid = uid_mapping.get(incoming_uid, incoming_uid)
            if not target_uid:
                continue
            normalized = dict(row)
            normalized["uid_literature"] = target_uid
            normalized["cite_key"] = cite_lookup.get(target_uid, _stringify(row.get("cite_key")))
            tag_rows.append(normalized)
    merged_tags_df = _normalize_tags_df(pd.DataFrame(tag_rows)).drop_duplicates(subset=["uid_literature", "tag"], keep="last")

    if "id" in current_df.columns:
        current_df["id"] = pd.to_numeric(current_df["id"], errors="coerce").fillna(0).astype(int)
        current_df = current_df.sort_values(by=["id", "uid_literature"], ascending=[True, True]).reset_index(drop=True)

    return current_df, merged_attachments_df, merged_tags_df, {
        "incoming_count": int(len(incoming_literatures)),
        "matched_existing_count": int(matched_existing_count),
        "inserted_count": int(inserted_count),
        "final_literature_count": int(len(current_df)),
        "uid_mapping": uid_mapping,
    }


def replace_reference_tables_only(
    db_path: Path,
    *,
    literatures_df: Optional[pd.DataFrame] = None,
    attachments_df: Optional[pd.DataFrame] = None,
    tags_df: Optional[pd.DataFrame] = None,
) -> None:
    """仅替换文献域三张表，保留阅读状态与解析资产等运行态表。"""

    init_db(db_path)
    conn = _connect(db_path)
    try:
        literature_target = _resolve_writable_table_name(conn, LITERATURE_TABLE_NAME)
        attachment_target = _resolve_writable_table_name(conn, LITERATURE_ATTACHMENT_TABLE_NAME)
        tag_target = _resolve_writable_table_name(conn, LITERATURE_TAG_TABLE_NAME)

        if literatures_df is not None and literature_target:
            working_literatures = _normalize_literatures_df(literatures_df)
            _ensure_columns(conn, literature_target, {column: "TEXT" for column in working_literatures.columns})
            if not working_literatures.empty:
                literatures_columns = [column for column in working_literatures.columns if column]
                update_columns = [column for column in literatures_columns if column != "id"]
                placeholders = ", ".join(["?"] * len(literatures_columns))
                update_sql = ", ".join(
                    [f"{_quote_identifier(column)} = excluded.{_quote_identifier(column)}" for column in update_columns]
                )
                sql = (
                    f"INSERT INTO {_quote_identifier(literature_target)} "
                    f"({', '.join(_quote_identifier(column) for column in literatures_columns)}) "
                    f"VALUES ({placeholders}) "
                    f"ON CONFLICT(id) DO UPDATE SET {update_sql}"
                )
                for row in working_literatures.where(pd.notnull(working_literatures), None).to_dict(orient="records"):
                    values = [row.get(column) for column in literatures_columns]
                    conn.execute(sql, values)

        if attachments_df is not None and attachment_target:
            working_attachments = _normalize_attachments_df(attachments_df)
            _ensure_columns(conn, attachment_target, {column: "TEXT" for column in working_attachments.columns})
            _delete_all_if_table(conn, attachment_target)
            if not working_attachments.empty:
                working_attachments.where(pd.notnull(working_attachments), None).to_sql(attachment_target, conn, if_exists="append", index=False)
            _write_normalized_attachment_tables(conn, working_attachments, if_exists="replace")

        if tags_df is not None and tag_target:
            working_tags = _normalize_tags_df(tags_df)
            _ensure_columns(conn, tag_target, {column: "TEXT" for column in working_tags.columns})
            _delete_all_if_table(conn, tag_target)
            if not working_tags.empty:
                working_tags.where(pd.notnull(working_tags), None).to_sql(tag_target, conn, if_exists="append", index=False)

        conn.commit()
    finally:
        conn.close()
    init_db(db_path)
    backfill_content_relationships(db_path)


def build_attachments_df_from_literatures(literatures_df: pd.DataFrame) -> pd.DataFrame:
    """根据文献主表构建附件关系表。

    Args:
        literatures_df: 文献主表，要求至少包含 uid_literature、pdf_path 等字段。

    Returns:
        可写入 literature_attachments 的 DataFrame。
    """
    if literatures_df is None or literatures_df.empty:
        return _empty_attachments_df()

    rows: List[dict] = []
    for _, row in literatures_df.iterrows():
        storage_path = str(row.get("pdf_path", "") or "").strip()
        uid_literature = str(row.get("uid_literature", "") or "").strip()
        if not storage_path or not uid_literature:
            continue
        attachment_name = str(row.get("primary_attachment_name", "") or Path(storage_path).name)
        suffix = Path(storage_path).suffix.lower()
        rows.append(
            {
                "uid_attachment": _stable_attachment_uid(uid_literature, storage_path),
                "uid_literature": uid_literature,
                "attachment_name": attachment_name,
                "attachment_type": "fulltext",
                "file_ext": suffix.lstrip("."),
                "storage_path": storage_path,
                "source_path": storage_path,
                "checksum": "",
                "is_primary": int(bool(storage_path)),
                "status": "available",
                "created_at": str(row.get("created_at", "") or ""),
                "updated_at": str(row.get("updated_at", "") or ""),
            }
        )
    if not rows:
        return _empty_attachments_df()
    return pd.DataFrame(rows).drop_duplicates(subset=["uid_attachment"])


def build_tags_df_from_inverted_index(
    literatures_df: pd.DataFrame,
    tag_inverted_index: Dict[str, List[int]],
    *,
    normalize_text_fn=None,
) -> pd.DataFrame:
    """根据标签倒排索引构建文献标签关系表。

    Args:
        literatures_df: 文献主表，索引需与倒排索引中的 rid 对齐。
        tag_inverted_index: 标签到文献 rid 列表的倒排索引。
        normalize_text_fn: 可选标签归一化函数。

    Returns:
        可写入 literature_tags 的 DataFrame。
    """
    if literatures_df is None or literatures_df.empty or not tag_inverted_index:
        return pd.DataFrame(
            columns=[
                "uid_literature",
                "cite_key",
                "tag",
                "tag_norm",
                "source_type",
                "created_at",
                "updated_at",
            ]
        )

    indexed = literatures_df.copy()
    if "id" in indexed.columns:
        indexed = indexed.set_index("id", drop=False)

    rows: List[dict] = []
    for tag, rid_list in tag_inverted_index.items():
        for rid in rid_list:
            if rid not in indexed.index:
                continue
            record = indexed.loc[rid]
            rows.append(
                {
                    "uid_literature": str(record.get("uid_literature", "") or ""),
                    "cite_key": str(record.get("cite_key", "") or ""),
                    "tag": str(tag),
                    "tag_norm": normalize_text_fn(str(tag)) if normalize_text_fn else str(tag).strip().lower(),
                    "source_type": "a02_tag_match",
                    "created_at": str(record.get("created_at", "") or ""),
                    "updated_at": str(record.get("updated_at", "") or ""),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "uid_literature",
                "cite_key",
                "tag",
                "tag_norm",
                "source_type",
                "created_at",
                "updated_at",
            ]
        )
    return pd.DataFrame(rows).drop_duplicates(subset=["uid_literature", "tag"])


def _default_normalize_text(value: str) -> str:
    """执行最小化文本归一化，供标签回填使用。"""
    return " ".join(str(value or "").lower().split())


def rebuild_reference_relation_tables(
    db_path: Path,
    *,
    tag_list: Optional[List[str]] = None,
    tag_match_fields: Optional[List[str]] = None,
    normalize_text_fn=None,
    if_exists: str = "replace",
) -> Dict[str, int]:
    """基于文献主表重建附件关系表与标签关系表。

    Args:
        db_path: references.db 路径。
        tag_list: 可选标签列表；为空时仅重建附件关系表。
        tag_match_fields: 标签匹配字段列表。
        normalize_text_fn: 文本归一化函数。
        if_exists: 写回 SQLite 时的覆盖策略。

    Returns:
        重建后的表计数字典。
    """
    from autodokit.tools.literature_tag_tools import build_literature_tag_inverted_index

    init_db(db_path)
    literatures_df = load_literatures_df(db_path)
    attachments_df = build_attachments_df_from_literatures(literatures_df)

    tags_df = build_tags_df_from_inverted_index(pd.DataFrame(), {})
    if tag_list:
        indexed_df = literatures_df.copy()
        if "id" in indexed_df.columns:
            indexed_df = indexed_df.set_index("id", drop=False)
        tag_inv = build_literature_tag_inverted_index(
            indexed_df,
            tag_list,
            tag_match_fields or ["title", "abstract", "keywords"],
            normalize_text_fn=normalize_text_fn or _default_normalize_text,
        )
        tags_df = build_tags_df_from_inverted_index(
            indexed_df,
            tag_inv,
            normalize_text_fn=normalize_text_fn or _default_normalize_text,
        )

    save_tables(
        db_path,
        attachments_df=attachments_df,
        tags_df=tags_df,
        if_exists=if_exists,
    )
    return {
        "literatures": int(len(literatures_df)),
        "literature_attachments": int(len(attachments_df)),
        "literature_tags": int(len(tags_df)),
    }


def rebuild_reference_relation_tables_from_config(
    db_path: Path,
    config_path: Path,
    *,
    if_exists: str = "replace",
) -> Dict[str, int]:
    """从 JSON 配置读取标签参数并重建关系表。"""
    raw = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    return rebuild_reference_relation_tables(
        db_path,
        tag_list=raw.get("tag_list") or [],
        tag_match_fields=raw.get("tag_match_fields") or ["title", "abstract", "keywords"],
        if_exists=if_exists,
    )


def save_tables(
    db_path: Path,
    *,
    literatures_df: Optional[pd.DataFrame] = None,
    attachments_df: Optional[pd.DataFrame] = None,
    tags_df: Optional[pd.DataFrame] = None,
    if_exists: str = "replace",
) -> None:
    """把 DataFrame 形式的文献表整体写回 SQLite。"""
    init_db(db_path)
    conn = _connect(db_path)
    try:
        literature_target = _resolve_writable_table_name(conn, LITERATURE_TABLE_NAME)
        attachment_target = _resolve_writable_table_name(conn, LITERATURE_ATTACHMENT_TABLE_NAME)
        tag_target = _resolve_writable_table_name(conn, LITERATURE_TAG_TABLE_NAME)

        if literatures_df is not None and literatures_df.shape[1] > 0 and literature_target:
            _ensure_columns(conn, literature_target, {column: "TEXT" for column in literatures_df.columns})
            working = literatures_df.where(pd.notnull(literatures_df), None)
            if if_exists == "replace":
                _delete_all_if_table(conn, KNOWLEDGE_LINK_TABLE_NAME)
                _delete_all_if_table(conn, LITERATURE_CHUNK_TABLE_NAME)
                _delete_all_if_table(conn, LITERATURE_CHUNK_SET_TABLE_NAME)
                _delete_all_if_table(conn, PARSE_ASSET_TABLE_NAME)
                _delete_all_if_table(conn, READING_QUEUE_TABLE_NAME)
                _delete_all_if_table(conn, READING_STATE_TABLE_NAME)
                _delete_all_if_table(conn, ATTACHMENT_LINK_TABLE_NAME)
                _delete_all_if_table(conn, ATTACHMENT_TABLE_NAME)
                _delete_all_if_table(conn, attachment_target)
                _delete_all_if_table(conn, tag_target)
                _delete_all_if_table(conn, literature_target)
                working.to_sql(literature_target, conn, if_exists="append", index=False)
            else:
                working.to_sql(literature_target, conn, if_exists=if_exists, index=False)
        if attachments_df is not None and attachment_target:
            _ensure_columns(conn, attachment_target, {column: "TEXT" for column in attachments_df.columns})
            working = attachments_df.where(pd.notnull(attachments_df), None) if not attachments_df.empty else pd.DataFrame(columns=[
                "uid_attachment", "uid_literature", "attachment_name", "attachment_type", "file_ext", "storage_path", "source_path", "checksum", "is_primary", "status", "created_at", "updated_at"
            ])
            if if_exists == "replace":
                _delete_all_if_table(conn, attachment_target)
                if not working.empty:
                    working.to_sql(attachment_target, conn, if_exists="append", index=False)
            else:
                if not working.empty:
                    working.to_sql(attachment_target, conn, if_exists=if_exists, index=False)
            _write_normalized_attachment_tables(conn, _normalize_attachments_df(attachments_df), if_exists=if_exists)
        if tags_df is not None and tag_target:
            _ensure_columns(conn, tag_target, {column: "TEXT" for column in tags_df.columns})
            working = tags_df.where(pd.notnull(tags_df), None) if not tags_df.empty else pd.DataFrame(columns=[
                "uid_literature", "cite_key", "tag", "tag_norm", "source_type", "created_at", "updated_at"
            ])
            if if_exists == "replace":
                _delete_all_if_table(conn, tag_target)
                if not working.empty:
                    working.to_sql(tag_target, conn, if_exists="append", index=False)
            else:
                if not working.empty:
                    working.to_sql(tag_target, conn, if_exists=if_exists, index=False)
        conn.commit()
    finally:
        conn.close()
    init_db(db_path)
    backfill_content_relationships(db_path)


def get_literature_by_uid(db_path: Path, uid: str) -> dict:
    conn = _connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM literatures WHERE uid_literature = ?", conn, params=(uid,))
        if df.empty:
            raise KeyError(f"uid={uid} not found")
        record = df.iloc[0].to_dict()
        link_count = conn.execute(f"SELECT COUNT(1) FROM {ATTACHMENT_LINK_TABLE_NAME}").fetchone()
        if int((link_count or [0])[0] or 0) > 0:
            att = pd.read_sql_query(
                f"""
                SELECT
                    COALESCE(lnk.legacy_uid_attachment, lnk.uid_attachment_link, att.uid_attachment) AS uid_attachment,
                    lnk.uid_literature,
                    att.attachment_name,
                    COALESCE(NULLIF(lnk.link_role, ''), att.attachment_type) AS attachment_type,
                    att.file_ext,
                    att.storage_path,
                    att.source_path,
                    att.checksum,
                    COALESCE(lnk.is_primary, 0) AS is_primary,
                    att.status,
                    COALESCE(lnk.created_at, att.created_at) AS created_at,
                    COALESCE(lnk.updated_at, att.updated_at) AS updated_at
                FROM {ATTACHMENT_LINK_TABLE_NAME} AS lnk
                LEFT JOIN {ATTACHMENT_TABLE_NAME} AS att
                    ON att.uid_attachment = lnk.uid_attachment
                WHERE lnk.uid_literature = ?
                ORDER BY COALESCE(lnk.is_primary, 0) DESC, att.attachment_name
                """,
                conn,
                params=(uid,),
            )
        else:
            att = pd.read_sql_query("SELECT * FROM literature_attachments WHERE uid_literature = ?", conn, params=(uid,))
        record["attachments"] = [dict(row) for _, row in att.iterrows()]
        tags = pd.read_sql_query(f"SELECT * FROM {LITERATURE_TAG_TABLE_NAME} WHERE uid_literature = ?", conn, params=(uid,))
        record["tags"] = [dict(row) for _, row in tags.iterrows()]
        return record
    finally:
        conn.close()


def export_csv(db_path: Path, out_dir: Path) -> None:
    """把 sqlite 表导出为 CSV（供分析或兼容使用）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        df_items = pd.read_sql_query("SELECT * FROM literatures", conn)
        link_count = conn.execute(f"SELECT COUNT(1) FROM {ATTACHMENT_LINK_TABLE_NAME}").fetchone()
        if int((link_count or [0])[0] or 0) > 0:
            df_att = pd.read_sql_query(
                f"""
                SELECT
                    COALESCE(lnk.legacy_uid_attachment, lnk.uid_attachment_link, att.uid_attachment) AS uid_attachment,
                    lnk.uid_literature,
                    att.attachment_name,
                    COALESCE(NULLIF(lnk.link_role, ''), att.attachment_type) AS attachment_type,
                    att.file_ext,
                    att.storage_path,
                    att.source_path,
                    att.checksum,
                    COALESCE(lnk.is_primary, 0) AS is_primary,
                    att.status,
                    COALESCE(lnk.created_at, att.created_at) AS created_at,
                    COALESCE(lnk.updated_at, att.updated_at) AS updated_at
                FROM {ATTACHMENT_LINK_TABLE_NAME} AS lnk
                LEFT JOIN {ATTACHMENT_TABLE_NAME} AS att
                    ON att.uid_attachment = lnk.uid_attachment
                ORDER BY lnk.uid_literature, COALESCE(lnk.is_primary, 0) DESC, att.attachment_name
                """,
                conn,
            )
        else:
            df_att = pd.read_sql_query("SELECT * FROM literature_attachments", conn)
        df_tags = pd.read_sql_query(f"SELECT * FROM {LITERATURE_TAG_TABLE_NAME}", conn)
        df_items.to_csv(out_dir / "literatures.csv", index=False, encoding="utf-8-sig")
        df_att.to_csv(out_dir / "literature_attachments.csv", index=False, encoding="utf-8-sig")
        df_tags.to_csv(out_dir / "literature_tags.csv", index=False, encoding="utf-8-sig")
    finally:
        conn.close()
