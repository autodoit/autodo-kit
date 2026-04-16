"""A040 普通流程 seed_items 语种分流测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from autodokit.affairs.检索治理.affair import _partition_seed_items_by_language


def _prepare_db(db_path: Path) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE literatures (
                uid_literature TEXT,
                cite_key TEXT,
                title TEXT,
                language TEXT,
                source_lang TEXT,
                "文献语种" TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO literatures(uid_literature, cite_key, title, language, source_lang, \"文献语种\") VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("uid-zh", "ck-zh", "中文标题A", "zh", "zh", "zh-cn"),
                ("uid-fr", "ck-fr", "Titre Francais", "fr", "fr", "fr"),
                ("uid-und", "ck-und", "Collaboration Network and Metrics", "", "", ""),
            ],
        )


def test_partition_seed_items_should_follow_canonical_language_first(tmp_path: Path) -> None:
    db_path = tmp_path / "content.db"
    _prepare_db(db_path)

    seeds = [
        {"cite_key": "ck-zh", "title": "中文标题A"},
        {"cite_key": "ck-fr", "title": "Titre Francais"},
        {"cite_key": "ck-und", "title": "Collaboration Network and Metrics"},
        {"title": "科研协作网络与学科演化"},
        {"title": "Collaboration networks and disciplinary evolution"},
    ]

    zh_items, foreign_items = _partition_seed_items_by_language(db_path, seeds)

    zh_keys = {str(item.get("cite_key") or "") for item in zh_items}
    foreign_keys = {str(item.get("cite_key") or "") for item in foreign_items}
    assert "ck-zh" in zh_keys
    assert "ck-fr" in foreign_keys
    assert "ck-und" in foreign_keys

    zh_titles = {str(item.get("title") or "") for item in zh_items}
    foreign_titles = {str(item.get("title") or "") for item in foreign_items}
    assert "银行系统性风险与房地产" in zh_titles
    assert "Systemic risk and real estate cycle" in foreign_titles
