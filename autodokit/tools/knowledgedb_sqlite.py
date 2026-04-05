"""SQLite-backed 知识库索引适配器。

提供：把知识索引 CSV 导入到统一内容主库 `content.db`，并提供简单查询与导出接口。
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Optional

import pandas as pd

from .contentdb_sqlite import (
    KNOWLEDGE_EVIDENCE_TABLE_NAME,
    KNOWLEDGE_LINK_TABLE_NAME,
    backfill_content_relationships,
    connect_sqlite,
    init_content_db,
)


KNOWLEDGE_INDEX_TABLE_NAME = "knowledge_index"
KNOWLEDGE_ATTACHMENT_TABLE_NAME = "knowledge_attachments"


def _connect(db_path: Path) -> sqlite3.Connection:
    return connect_sqlite(db_path)


def _sqlite_object_type(conn: sqlite3.Connection, object_name: str) -> str:
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ? LIMIT 1",
        (object_name,),
    ).fetchone()
    return str(row[0]).strip().lower() if row and row[0] else ""


def _create_index_if_table(conn: sqlite3.Connection, table_name: str, index_sql: str) -> None:
    if _sqlite_object_type(conn, table_name) == "table":
        conn.execute(index_sql)


def _drop_sqlite_object_if_exists(conn: sqlite3.Connection, object_name: str) -> None:
    object_type = _sqlite_object_type(conn, object_name)
    if object_type == "view":
        conn.execute(f"DROP VIEW IF EXISTS {object_name}")
    elif object_type == "table":
        conn.execute(f"DROP TABLE IF EXISTS {object_name}")


def init_db(db_path: Path) -> None:
    init_content_db(db_path)
    with _connect(db_path) as conn:
        _create_index_if_table(conn, KNOWLEDGE_INDEX_TABLE_NAME, "CREATE INDEX IF NOT EXISTS idx_know_uid ON knowledge_index(uid_knowledge)")
        _create_index_if_table(conn, KNOWLEDGE_ATTACHMENT_TABLE_NAME, "CREATE INDEX IF NOT EXISTS idx_katt_uid ON knowledge_attachments(uid_knowledge)")
        conn.commit()


def import_from_csv(index_csv: Path, attachments_csv: Optional[Path], db_path: Path, if_exists: str = "replace") -> None:
    index_df = pd.read_csv(index_csv, encoding="utf-8-sig") if index_csv and index_csv.exists() else None
    attachments_df = pd.read_csv(attachments_csv, encoding="utf-8-sig") if attachments_csv and attachments_csv.exists() else None
    save_tables(db_path, index_df=index_df, attachments_df=attachments_df, if_exists=if_exists)


def query_index(db_path: Path, sql: str = "SELECT * FROM knowledge_index LIMIT 1000") -> pd.DataFrame:
    conn = _connect(db_path)
    try:
        return pd.read_sql_query(sql, conn)
    finally:
        conn.close()


def load_index_df(db_path: Path) -> pd.DataFrame:
    """读取知识索引表为 DataFrame。"""
    init_db(db_path)
    return query_index(db_path, sql=f"SELECT * FROM {KNOWLEDGE_INDEX_TABLE_NAME}")


def load_attachments_df(db_path: Path) -> pd.DataFrame:
    """读取知识附件表为 DataFrame。"""
    init_db(db_path)
    conn = _connect(db_path)
    try:
        return pd.read_sql_query(f"SELECT * FROM {KNOWLEDGE_ATTACHMENT_TABLE_NAME}", conn)
    finally:
        conn.close()


def save_tables(
    db_path: Path,
    *,
    index_df: Optional[pd.DataFrame] = None,
    attachments_df: Optional[pd.DataFrame] = None,
    if_exists: str = "replace",
) -> None:
    """把 DataFrame 形式的知识库表整体写回 SQLite。"""
    init_db(db_path)
    if if_exists == "replace":
        with _connect(db_path) as reset_conn:
            _drop_sqlite_object_if_exists(reset_conn, KNOWLEDGE_EVIDENCE_TABLE_NAME)
            _drop_sqlite_object_if_exists(reset_conn, KNOWLEDGE_LINK_TABLE_NAME)
            _drop_sqlite_object_if_exists(reset_conn, KNOWLEDGE_ATTACHMENT_TABLE_NAME)
            _drop_sqlite_object_if_exists(reset_conn, "knowledge_note_evidence_view")
            _drop_sqlite_object_if_exists(reset_conn, "literature_standard_notes_view")
            _drop_sqlite_object_if_exists(reset_conn, "knowledge_notes")
            _drop_sqlite_object_if_exists(reset_conn, KNOWLEDGE_INDEX_TABLE_NAME)
            reset_conn.commit()
        init_db(db_path)
    conn = _connect(db_path)
    try:
        index_object_type = _sqlite_object_type(conn, KNOWLEDGE_INDEX_TABLE_NAME)
        attachment_object_type = _sqlite_object_type(conn, KNOWLEDGE_ATTACHMENT_TABLE_NAME)

        if index_df is not None and index_object_type == "table":
            for column in index_df.columns:
                conn.execute(f"ALTER TABLE {KNOWLEDGE_INDEX_TABLE_NAME} ADD COLUMN \"{column}\" TEXT") if column not in {
                    row[1] for row in conn.execute(f"PRAGMA table_info({KNOWLEDGE_INDEX_TABLE_NAME})").fetchall()
                } else None
            working = index_df.where(pd.notnull(index_df), None)
            if if_exists == "replace":
                if not working.empty:
                    working.to_sql(KNOWLEDGE_INDEX_TABLE_NAME, conn, if_exists="append", index=False)
            else:
                working.to_sql(KNOWLEDGE_INDEX_TABLE_NAME, conn, if_exists=if_exists, index=False)
        if attachments_df is not None and attachment_object_type == "table":
            for column in attachments_df.columns:
                conn.execute(f"ALTER TABLE {KNOWLEDGE_ATTACHMENT_TABLE_NAME} ADD COLUMN \"{column}\" TEXT") if column not in {
                    row[1] for row in conn.execute(f"PRAGMA table_info({KNOWLEDGE_ATTACHMENT_TABLE_NAME})").fetchall()
                } else None
            working = attachments_df.where(pd.notnull(attachments_df), None)
            if if_exists == "replace":
                if not working.empty:
                    working.to_sql(KNOWLEDGE_ATTACHMENT_TABLE_NAME, conn, if_exists="append", index=False)
            else:
                working.to_sql(KNOWLEDGE_ATTACHMENT_TABLE_NAME, conn, if_exists=if_exists, index=False)
        conn.commit()
    finally:
        conn.close()
    init_db(db_path)
    backfill_content_relationships(db_path)


def export_csv(db_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        df_idx = pd.read_sql_query("SELECT * FROM knowledge_index", conn)
        df_att = pd.read_sql_query("SELECT * FROM knowledge_attachments", conn)
        df_idx.to_csv(out_dir / "knowledge_index.csv", index=False, encoding="utf-8-sig")
        df_att.to_csv(out_dir / "knowledge_attachments.csv", index=False, encoding="utf-8-sig")
    finally:
        conn.close()
