"""Storage backend factory and helpers.

提供简单的接口，在 `csv` 与 `sqlite` 之间切换，便于事务逐步迁移。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from . import bibliodb_sqlite
from .contentdb_sqlite import DEFAULT_CONTENT_DB_NAME, resolve_content_db_path
from . import knowledgedb_sqlite


DEFAULT_REFERENCES_DB_NAME = DEFAULT_CONTENT_DB_NAME
DEFAULT_KNOWLEDGE_DB_NAME = DEFAULT_CONTENT_DB_NAME


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if pd.isna(value):
        return None
    return value


def _drop_sqlite_object(conn: sqlite3.Connection, object_name: str) -> None:
    object_row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ?",
        (object_name,),
    ).fetchone()
    if object_row is None:
        return
    object_type = str(object_row[0]).strip().lower()
    if object_type == "view":
        conn.execute(f"DROP VIEW IF EXISTS {_quote_identifier(object_name)}")
        return
    if object_type == "table":
        conn.execute(f"DROP TABLE IF EXISTS {_quote_identifier(object_name)}")


def _drop_all_sqlite_views(conn: sqlite3.Connection) -> None:
    for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'").fetchall():
        view_name = str(row[0] or "").strip()
        if view_name:
            conn.execute(f"DROP VIEW IF EXISTS {_quote_identifier(view_name)}")


def persist_literature_table(
    table: pd.DataFrame,
    output_dir: Path,
    filename: str,
    *,
    backend: str = "csv",
    db_path: Optional[Path] = None,
) -> list[Path]:
    """把文献主表写入后端（csv 或 sqlite）。

    返回写出的路径列表（csv 或 sqlite 文件路径）。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    file_path = output_dir / filename

    if backend == "csv":
        table.to_csv(file_path, index=True, index_label="id", encoding="utf-8-sig")
        written.append(file_path)
        return written

    if backend == "sqlite":
        # 如果未传 db_path，使用默认位置
        if db_path is None:
            db_path = resolve_content_db_path(output_dir.parent / DEFAULT_CONTENT_DB_NAME)
        else:
            db_path = resolve_content_db_path(db_path)
        # 先把表写为临时 CSV（pandas.to_sql 直接写入也可，但保持流程清晰）
        tmp_csv = output_dir / (filename + ".tmp.csv")
        table.to_csv(tmp_csv, index=True, index_label="id", encoding="utf-8-sig")
        # 导入到 sqlite（replace 模式）
        bibliodb_sqlite.import_from_csv(items_csv=tmp_csv, attachments_csv=None, db_path=db_path, if_exists="replace")
        written.append(db_path)
        # 保留审计 CSV 也写出
        file_path.unlink(missing_ok=True)
        tmp_csv.rename(file_path)
        written.append(file_path)
        return written

    raise ValueError(f"unsupported backend: {backend}")


def load_reference_tables(
    *,
    db_path: Optional[Path] = None,
    references_root: Optional[Path] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    """优先从 SQLite 主库读取文献主表与附件表。"""
    if db_path is None:
        if references_root is None:
            raise ValueError("db_path 与 references_root 至少提供一个")
        db_path = resolve_content_db_path(references_root / DEFAULT_REFERENCES_DB_NAME)
    else:
        db_path = Path(db_path).resolve()

    bibliodb_sqlite.init_db(db_path)
    literatures = bibliodb_sqlite.load_literatures_df(db_path)
    attachments = bibliodb_sqlite.load_attachments_df(db_path)
    return literatures, attachments, db_path


def persist_reference_tables(
    *,
    literatures_df: pd.DataFrame,
    attachments_df: pd.DataFrame,
    tags_df: Optional[pd.DataFrame] = None,
    db_path: Optional[Path] = None,
    references_root: Optional[Path] = None,
) -> Path:
    """把文献主表与附件表写回 SQLite 主库。

    对 content.db 这类带运行态外键关系的主库，只替换文献域表，
    避免整表 replace 时误删阅读状态、解析资产等运行态数据。
    """
    if db_path is None:
        if references_root is None:
            raise ValueError("db_path 与 references_root 至少提供一个")
        db_path = resolve_content_db_path(references_root / DEFAULT_REFERENCES_DB_NAME)
    else:
        db_path = Path(db_path).resolve()

    bibliodb_sqlite.replace_reference_tables_only(
        db_path,
        literatures_df=literatures_df,
        attachments_df=attachments_df,
        tags_df=tags_df,
    )
    return db_path


def load_knowledge_tables(
    *,
    db_path: Optional[Path] = None,
    knowledge_root: Optional[Path] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    """优先从 SQLite 主库读取知识索引表与附件表。"""
    if db_path is None:
        if knowledge_root is None:
            raise ValueError("db_path 与 knowledge_root 至少提供一个")
        db_path = resolve_content_db_path(knowledge_root / DEFAULT_KNOWLEDGE_DB_NAME)
    else:
        db_path = Path(db_path).resolve()

    knowledgedb_sqlite.init_db(db_path)
    index_df = knowledgedb_sqlite.load_index_df(db_path)
    attachments_df = knowledgedb_sqlite.load_attachments_df(db_path)
    return index_df, attachments_df, db_path


def persist_knowledge_tables(
    *,
    index_df: pd.DataFrame,
    attachments_df: pd.DataFrame,
    db_path: Optional[Path] = None,
    knowledge_root: Optional[Path] = None,
) -> Path:
    """把知识索引表与附件表写回 SQLite 主库。"""
    if db_path is None:
        if knowledge_root is None:
            raise ValueError("db_path 与 knowledge_root 至少提供一个")
        db_path = resolve_content_db_path(knowledge_root / DEFAULT_KNOWLEDGE_DB_NAME)
    else:
        db_path = Path(db_path).resolve()

    knowledgedb_sqlite.save_tables(
        db_path,
        index_df=index_df,
        attachments_df=attachments_df,
        if_exists="replace",
    )
    return db_path


def load_reference_main_table(input_path: Path) -> pd.DataFrame:
    """按路径读取文献主表，支持 SQLite 主库或旧 CSV。"""
    if input_path.suffix.lower() == ".db":
        return bibliodb_sqlite.load_literatures_df(input_path)
    if input_path.exists():
        return pd.read_csv(input_path, dtype=str, keep_default_na=False)
    return pd.DataFrame()


def persist_reference_main_table(table: pd.DataFrame, output_path: Path) -> Path:
    """按路径写回文献主表，支持 SQLite 主库或旧 CSV。"""
    if output_path.suffix.lower() == ".db":
        resolved_output_path = Path(output_path).resolve()
        existing_attachments = bibliodb_sqlite.load_attachments_df(resolved_output_path) if resolved_output_path.exists() else pd.DataFrame()
        bibliodb_sqlite.save_tables(resolved_output_path, literatures_df=table, attachments_df=existing_attachments, if_exists="replace")
        return resolve_content_db_path(resolved_output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_path, index=False, encoding="utf-8-sig")
    return output_path


def _serialize_json_value(value: Any) -> str:
    """把嵌套值编码成可写入 SQLite 的 JSON 字符串。"""

    return json.dumps(value, ensure_ascii=False, default=str)


def persist_review_candidate_views(
    db_path: Path,
    *,
    view_tables: dict[str, pd.DataFrame],
    gate_review: dict[str, Any] | None = None,
    if_exists: str = "replace",
    scope_key: str = "",
    run_uid: str = "",
    drop_legacy_tables: bool = True,
) -> Path:
    """把 A050 视图与 gate 审查结果写入 content.db。"""

    if db_path.suffix.lower() != ".db":
        raise ValueError(f"review views 只能写入 sqlite 数据库: {db_path}")

    db_path = Path(db_path).resolve()
    bibliodb_sqlite.init_db(db_path)
    for table_name, table_df in (view_tables or {}).items():
        if not isinstance(table_df, pd.DataFrame):
            continue
        unique_columns = ["uid_literature"] if "uid_literature" in table_df.columns else None
        if table_name == "review_reading_batches" and {"batch_id", "uid_literature"}.issubset(set(table_df.columns)):
            unique_columns = ["batch_id", "uid_literature"]
        bibliodb_sqlite.save_dataframe_table(
            db_path,
            table_name,
            table_df,
            if_exists=if_exists,
            unique_columns=unique_columns,
        )

    if drop_legacy_tables:
        with sqlite3.connect(str(db_path)) as conn:
            _drop_all_sqlite_views(conn)
            conn.commit()

    if gate_review is not None:
        gate_df = pd.DataFrame(
            [
                {
                    "gate_uid": str(gate_review.get("gate_uid") or ""),
                    "node_uid": str(gate_review.get("node_uid") or ""),
                    "node_name": str(gate_review.get("node_name") or ""),
                    "summary": str(gate_review.get("summary") or ""),
                    "recommendation": str(gate_review.get("recommendation") or ""),
                    "score": gate_review.get("score"),
                    "issues_json": _serialize_json_value(gate_review.get("issues") or []),
                    "checks_json": _serialize_json_value(gate_review.get("checks") or []),
                    "artifacts_json": _serialize_json_value(gate_review.get("artifacts") or []),
                    "metadata_json": _serialize_json_value(gate_review.get("metadata") or {}),
                    "created_at": str(gate_review.get("created_at") or ""),
                }
            ]
        )
        bibliodb_sqlite.save_dataframe_table(
            db_path,
            "review_gate_reviews",
            gate_df,
            if_exists=if_exists,
            unique_columns=["gate_uid"] if str(gate_df.iloc[0].get("gate_uid") or "") else None,
        )

    return db_path


def load_knowledge_index_table(input_path: Path) -> pd.DataFrame:
    """按路径读取知识索引主表，支持 SQLite 主库或旧 CSV。"""
    if input_path.suffix.lower() == ".db":
        return knowledgedb_sqlite.load_index_df(input_path)
    if input_path.exists():
        return pd.read_csv(input_path, dtype=str, keep_default_na=False)
    return pd.DataFrame()
