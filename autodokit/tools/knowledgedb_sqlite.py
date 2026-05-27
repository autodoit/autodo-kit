"""SQLite-backed 知识库索引适配器。

提供：把知识索引 CSV 导入到统一内容主库 `content.db`，并提供简单查询与导出接口。
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Optional

import pandas as pd

from .contentdb_sqlite import (
    AUTO_KNOWLEDGE_EVIDENCE_SOURCE_FIELDS,
    AUTO_KNOWLEDGE_LINK_SOURCE_FIELDS,
    KNOWLEDGE_EVIDENCE_TABLE_NAME,
    KNOWLEDGE_ATTACHMENT_TABLE_NAME,
    KNOWLEDGE_INDEX_TABLE_NAME,
    KNOWLEDGE_LINK_TABLE_NAME,
    LITERATURE_TABLE_NAME,
    _build_knowledge_relation_frames,
    _load_knowledge_relation_source_frames,
    _upsert_table_rows,
    connect_sqlite,
    init_content_db,
    resolve_content_physical_column,
    sync_knowledge_relationships,
)


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


def _collect_existing_ids(conn: sqlite3.Connection, table_name: str, logical_column: str) -> set[str]:
    if _sqlite_object_type(conn, table_name) != "table":
        return set()
    physical_column = resolve_content_physical_column(table_name, logical_column)
    return {
        str(row[0]).strip()
        for row in conn.execute(f'SELECT "{physical_column}" FROM "{table_name}"').fetchall()
        if row and str(row[0] or "").strip()
    }


def _load_manual_relation_snapshot(
    conn: sqlite3.Connection,
    table_name: str,
    *,
    auto_source_fields: tuple[str, ...],
) -> pd.DataFrame:
    if _sqlite_object_type(conn, table_name) != "table":
        return pd.DataFrame()
    source_field_column = resolve_content_physical_column(table_name, "source_field")
    placeholders = ", ".join(["?"] * len(auto_source_fields))
    return pd.read_sql_query(
        f'SELECT * FROM "{table_name}" WHERE COALESCE("{source_field_column}", \'\') NOT IN ({placeholders})',
        conn,
        params=tuple(auto_source_fields),
    )


def init_db(db_path: Path) -> None:
    init_content_db(db_path)
    with _connect(db_path) as conn:
        _create_index_if_table(conn, KNOWLEDGE_INDEX_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_know_uid ON \"{KNOWLEDGE_INDEX_TABLE_NAME}\"(uid_knowledge)")
        _create_index_if_table(conn, KNOWLEDGE_ATTACHMENT_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_katt_uid ON \"{KNOWLEDGE_ATTACHMENT_TABLE_NAME}\"(uid_knowledge)")
        conn.commit()


def import_from_csv(index_csv: Path, attachments_csv: Optional[Path], db_path: Path, if_exists: str = "replace") -> None:
    index_df = pd.read_csv(index_csv, encoding="utf-8-sig") if index_csv and index_csv.exists() else None
    attachments_df = pd.read_csv(attachments_csv, encoding="utf-8-sig") if attachments_csv and attachments_csv.exists() else None
    save_tables(db_path, index_df=index_df, attachments_df=attachments_df, if_exists=if_exists)


def query_index(db_path: Path, sql: str = f"SELECT * FROM \"{KNOWLEDGE_INDEX_TABLE_NAME}\" LIMIT 1000") -> pd.DataFrame:
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
    affected_knowledge_uids: set[str] = set()
    manual_link_snapshot = pd.DataFrame()
    manual_evidence_snapshot = pd.DataFrame()
    if if_exists == "replace":
        with _connect(db_path) as snapshot_conn:
            affected_knowledge_uids = _collect_existing_ids(snapshot_conn, KNOWLEDGE_INDEX_TABLE_NAME, "uid_knowledge")
            manual_link_snapshot = _load_manual_relation_snapshot(
                snapshot_conn,
                KNOWLEDGE_LINK_TABLE_NAME,
                auto_source_fields=AUTO_KNOWLEDGE_LINK_SOURCE_FIELDS,
            )
            manual_evidence_snapshot = _load_manual_relation_snapshot(
                snapshot_conn,
                KNOWLEDGE_EVIDENCE_TABLE_NAME,
                auto_source_fields=AUTO_KNOWLEDGE_EVIDENCE_SOURCE_FIELDS,
            )
        with _connect(db_path) as reset_conn:
            _drop_sqlite_object_if_exists(reset_conn, KNOWLEDGE_EVIDENCE_TABLE_NAME)
            _drop_sqlite_object_if_exists(reset_conn, KNOWLEDGE_LINK_TABLE_NAME)
            _drop_sqlite_object_if_exists(reset_conn, KNOWLEDGE_ATTACHMENT_TABLE_NAME)
            _drop_sqlite_object_if_exists(reset_conn, "knowledge_note_evidence_view")
            _drop_sqlite_object_if_exists(reset_conn, "literature_standard_notes_view")
            _drop_sqlite_object_if_exists(reset_conn, "知识笔记")
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
    with _connect(db_path) as conn:
        affected_knowledge_uids.update(_collect_existing_ids(conn, KNOWLEDGE_INDEX_TABLE_NAME, "uid_knowledge"))

    sync_knowledge_relationships(
        db_path,
        replace_knowledge_scope=sorted(affected_knowledge_uids),
    )

    if affected_knowledge_uids:
        with sqlite3.connect(str(db_path), timeout=60) as raw_conn:
            auto_link_df, auto_evidence_df = _build_knowledge_relation_frames(*_load_knowledge_relation_source_frames(raw_conn))
            if not auto_link_df.empty:
                auto_link_df = auto_link_df.loc[
                    auto_link_df["uid_knowledge"].astype(str).isin(affected_knowledge_uids)
                ].reset_index(drop=True)
            if not auto_evidence_df.empty:
                auto_evidence_df = auto_evidence_df.loc[
                    auto_evidence_df["uid_knowledge"].astype(str).isin(affected_knowledge_uids)
                ].reset_index(drop=True)
            _upsert_table_rows(
                raw_conn,
                KNOWLEDGE_LINK_TABLE_NAME,
                auto_link_df,
                key_columns=["uid_knowledge", "uid_literature", "relation_type"],
            )
            _upsert_table_rows(
                raw_conn,
                KNOWLEDGE_EVIDENCE_TABLE_NAME,
                auto_evidence_df,
                key_columns=["uid_knowledge", "evidence_type", "target_uid", "evidence_role"],
            )
            raw_conn.commit()

    if manual_link_snapshot.empty and manual_evidence_snapshot.empty:
        return

    with _connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        current_knowledge_uids = _collect_existing_ids(conn, KNOWLEDGE_INDEX_TABLE_NAME, "uid_knowledge")
        current_literature_uids = _collect_existing_ids(conn, LITERATURE_TABLE_NAME, "uid_literature")

        try:
            if not manual_link_snapshot.empty:
                uid_knowledge_column = resolve_content_physical_column(KNOWLEDGE_LINK_TABLE_NAME, "uid_knowledge")
                uid_literature_column = resolve_content_physical_column(KNOWLEDGE_LINK_TABLE_NAME, "uid_literature")
                internal_id_column = resolve_content_physical_column(KNOWLEDGE_LINK_TABLE_NAME, "id")
                filtered_link_snapshot = manual_link_snapshot.loc[
                    manual_link_snapshot[uid_knowledge_column].astype(str).isin(current_knowledge_uids)
                    & manual_link_snapshot[uid_literature_column].astype(str).isin(current_literature_uids)
                ].reset_index(drop=True)
                if internal_id_column in filtered_link_snapshot.columns:
                    filtered_link_snapshot = filtered_link_snapshot.drop(columns=[internal_id_column])
                _upsert_table_rows(
                    conn,
                    KNOWLEDGE_LINK_TABLE_NAME,
                    filtered_link_snapshot,
                    key_columns=["uid_knowledge", "uid_literature", "relation_type"],
                )

            if not manual_evidence_snapshot.empty:
                uid_knowledge_column = resolve_content_physical_column(KNOWLEDGE_EVIDENCE_TABLE_NAME, "uid_knowledge")
                internal_id_column = resolve_content_physical_column(KNOWLEDGE_EVIDENCE_TABLE_NAME, "id")
                filtered_evidence_snapshot = manual_evidence_snapshot.loc[
                    manual_evidence_snapshot[uid_knowledge_column].astype(str).isin(current_knowledge_uids)
                ].reset_index(drop=True)
                if internal_id_column in filtered_evidence_snapshot.columns:
                    filtered_evidence_snapshot = filtered_evidence_snapshot.drop(columns=[internal_id_column])
                _upsert_table_rows(
                    conn,
                    KNOWLEDGE_EVIDENCE_TABLE_NAME,
                    filtered_evidence_snapshot,
                    key_columns=["uid_knowledge", "evidence_type", "target_uid", "evidence_role"],
                )
            conn.commit()
        finally:
            conn.execute("PRAGMA foreign_keys=ON")


def export_csv(db_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        df_idx = pd.read_sql_query(f"SELECT * FROM \"{KNOWLEDGE_INDEX_TABLE_NAME}\"", conn)
        df_att = pd.read_sql_query(f"SELECT * FROM \"{KNOWLEDGE_ATTACHMENT_TABLE_NAME}\"", conn)
        df_idx.to_csv(out_dir / "knowledge_index.csv", index=False, encoding="utf-8-sig")
        df_att.to_csv(out_dir / "knowledge_attachments.csv", index=False, encoding="utf-8-sig")
    finally:
        conn.close()
