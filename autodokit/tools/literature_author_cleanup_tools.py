"""作者清洗与关系回填原子工具。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from autodokit.tools.author_name_llm_preprocess_tools import normalize_content_db_author_names_with_aliyun
from autodokit.tools.contentdb_sqlite import AUTHOR_LINK_TABLE_NAME, AUTHOR_TABLE_NAME, resolve_content_physical_column


def _query_scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _physical_column_if_exists(conn: sqlite3.Connection, table_name: str, logical_name: str) -> str:
    candidate = resolve_content_physical_column(table_name, logical_name)
    columns = {
        str(row[1]).strip()
        for row in conn.execute(f'PRAGMA table_info("{table_name}")')
        if str(row[1]).strip()
    }
    if candidate in columns:
        return candidate
    return ""


def refresh_author_entities(payload: dict[str, Any]) -> dict[str, Any]:
    """执行作者实体清洗回填，并返回质量摘要。

    Args:
        payload: 输入参数字典。
            - content_db: content.db 路径（必填）。
            - sample_limit: 异常样例上限，默认 20。

    Returns:
        dict[str, Any]: 运行摘要，包含 authors 与 literature_authors 的规模与质量分布。

    Raises:
        ValueError: 当 content_db 缺失时抛出。

    Examples:
        >>> refresh_author_entities({"content_db": "workspace/database/content/content.db"})["status"]
        'PASS'
    """

    db_raw = str(payload.get("content_db") or "").strip()
    if not db_raw:
        raise ValueError("content_db 不能为空")
    db_path = Path(db_raw).expanduser().resolve()
    sample_limit = int(payload.get("sample_limit") or 20)

    normalize_summary = normalize_content_db_author_names_with_aliyun(
        {
            "content_db": str(db_path),
            "api_key_file": payload.get("api_key_file"),
            "config_path": payload.get("config_path"),
            "model": payload.get("model"),
            "batch_size": payload.get("batch_size"),
            "allow_fallback_cleaning": payload.get("allow_fallback_cleaning", False),
            "sample_limit": sample_limit,
        }
    )

    with sqlite3.connect(str(db_path), timeout=60) as conn:
        total_authors = _query_scalar(conn, f'SELECT COUNT(1) FROM "{AUTHOR_TABLE_NAME}"')
        total_author_links = _query_scalar(conn, f'SELECT COUNT(1) FROM "{AUTHOR_LINK_TABLE_NAME}"')

        uid_author_col = _physical_column_if_exists(conn, AUTHOR_TABLE_NAME, "uid_author")
        canonical_name_col = _physical_column_if_exists(conn, AUTHOR_TABLE_NAME, "标准作者名")
        display_name_col = _physical_column_if_exists(conn, AUTHOR_TABLE_NAME, "display_name")
        author_type_col = _physical_column_if_exists(conn, AUTHOR_TABLE_NAME, "作者类型")
        quality_flag_col = _physical_column_if_exists(conn, AUTHOR_TABLE_NAME, "作者质量标记")

        type_expr = f'"{author_type_col}"' if author_type_col else "''"
        quality_expr = f'"{quality_flag_col}"' if quality_flag_col else "''"
        uid_expr = f'"{uid_author_col}"' if uid_author_col else "''"
        canonical_expr = f'"{canonical_name_col}"' if canonical_name_col else "''"
        display_expr = f'"{display_name_col}"' if display_name_col else "''"

        type_rows = conn.execute(
            f"""
            SELECT COALESCE(author_type, '') AS author_type, COUNT(1) AS row_count
            FROM (
                SELECT {type_expr} AS author_type
                FROM "{AUTHOR_TABLE_NAME}"
            )
            GROUP BY COALESCE(author_type, '')
            ORDER BY row_count DESC, author_type ASC
            """
        ).fetchall()
        quality_rows = conn.execute(
            f"""
            SELECT COALESCE(quality_flag, '') AS quality_flag, COUNT(1) AS row_count
            FROM (
                SELECT {quality_expr} AS quality_flag
                FROM "{AUTHOR_TABLE_NAME}"
            )
            GROUP BY COALESCE(quality_flag, '')
            ORDER BY row_count DESC, quality_flag ASC
            """
        ).fetchall()
        anomaly_rows = conn.execute(
            f"""
            SELECT
                uid_author,
                canonical_name,
                display_name,
                author_type,
                quality_flag
            FROM (
                SELECT
                    {uid_expr} AS uid_author,
                    {canonical_expr} AS canonical_name,
                    {display_expr} AS display_name,
                    {type_expr} AS author_type,
                    {quality_expr} AS quality_flag
                FROM "{AUTHOR_TABLE_NAME}"
            )
            WHERE COALESCE(quality_flag, '') <> ''
            ORDER BY uid_author ASC
            LIMIT ?
            """,
            (sample_limit,),
        ).fetchall()

    return {
        "status": "PASS",
        "content_db": str(db_path),
        "normalize_summary": normalize_summary,
        "authors_total": total_authors,
        "literature_author_links_total": total_author_links,
        "author_type_distribution": [
            {"author_type": str(row[0]), "count": int(row[1])}
            for row in type_rows
        ],
        "quality_flag_distribution": [
            {"quality_flag": str(row[0]), "count": int(row[1])}
            for row in quality_rows
        ],
        "quality_samples": [
            {
                "uid_author": str(row[0]),
                "canonical_name": str(row[1]),
                "display_name": str(row[2]),
                "author_type": str(row[3]),
                "quality_flag": str(row[4]),
            }
            for row in anomaly_rows
        ],
    }
