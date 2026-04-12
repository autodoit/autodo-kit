"""作者清洗与关系回填原子工具。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from autodokit.tools.contentdb_sqlite import backfill_content_relationships


def _query_scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


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

    backfill_content_relationships(db_path)

    with sqlite3.connect(str(db_path), timeout=60) as conn:
        total_authors = _query_scalar(conn, "SELECT COUNT(1) FROM authors")
        total_author_links = _query_scalar(conn, "SELECT COUNT(1) FROM literature_authors")

        type_rows = conn.execute(
            """
            SELECT COALESCE(author_type, '') AS author_type, COUNT(1) AS row_count
            FROM authors
            GROUP BY COALESCE(author_type, '')
            ORDER BY row_count DESC, author_type ASC
            """
        ).fetchall()
        quality_rows = conn.execute(
            """
            SELECT COALESCE(quality_flag, '') AS quality_flag, COUNT(1) AS row_count
            FROM authors
            GROUP BY COALESCE(quality_flag, '')
            ORDER BY row_count DESC, quality_flag ASC
            """
        ).fetchall()
        anomaly_rows = conn.execute(
            """
            SELECT
                uid_author,
                canonical_name,
                display_name,
                author_type,
                quality_flag
            FROM authors
            WHERE COALESCE(quality_flag, '') <> ''
            ORDER BY uid_author ASC
            LIMIT ?
            """,
            (sample_limit,),
        ).fetchall()

    return {
        "status": "PASS",
        "content_db": str(db_path),
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
