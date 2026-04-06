"""knowledgedb 工具模块测试。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools.knowledgedb import (
    generate_knowledge_uid,
    init_empty_knowledge_attachments_table,
    init_empty_knowledge_index_table,
    knowledge_attach_file,
    knowledge_base_generate,
    knowledge_bind_literature_standard_note,
    knowledge_index_sync_from_note,
    knowledge_note_register,
    knowledge_note_validate_obsidian,
    knowledge_find_by_literature,
    knowledge_get,
    knowledge_sync_note,
    knowledge_upsert,
)


def test_generate_knowledge_uid_should_be_stable() -> None:
    """`generate_knowledge_uid` 对同一输入应生成稳定结果。"""

    uid1 = generate_knowledge_uid("notes/a.md", "A Note")
    uid2 = generate_knowledge_uid("notes/a.md", "A Note")
    assert uid1 == uid2
    assert uid1.startswith("kn-")


def test_knowledge_upsert_should_insert_index_record() -> None:
    """`knowledge_upsert` 应插入规范化知识索引记录。"""

    table = init_empty_knowledge_index_table()
    table, record, action = knowledge_upsert(
        table,
        {
            "note_path": "knowledge/notes/a.md",
            "title": "系统性风险知识卡片",
            "note_type": "knowledge_note",
            "tags": ["risk", "banking"],
        },
    )
    assert action == "inserted"
    assert record["uid_knowledge"].startswith("kn-")
    assert record["tags"] == "risk|banking"
    assert len(table) == 1


def test_knowledge_sync_note_should_parse_frontmatter() -> None:
    """`knowledge_sync_note` 应从 Markdown frontmatter 同步索引。"""

    note_dir = Path(".")
    temp_note = Path(note_dir / "tmp_sync_note.md").resolve()
    temp_note.write_text(
        "\n".join(
            [
                "---",
                "uid_knowledge: kn-custom-001",
                "title: 文献标准笔记",
                "note_type: literature_standard_note",
                "status: active",
                "tags:",
                '  - "note/literature"',
                '  - "topic/systemic-risk"',
                "aliases: [系统性风险文献笔记]",
                "uid_literature: lit-001",
                "cite_key: smith-2024-a-paper",
                "evidence_uids: [ev-1, ev-2]",
                "---",
                "",
                "# 文献标准笔记",
            ]
        ),
        encoding="utf-8",
    )
    try:
        table = init_empty_knowledge_index_table()
        table, record, action = knowledge_sync_note(table, temp_note, workspace_root=temp_note.parent)
        assert action == "inserted"
        assert record["uid_knowledge"] == "kn-custom-001"
        assert record["note_path"] == temp_note.name
        assert record["tags"] == "note/literature|topic/systemic-risk"
        assert record["uid_literature"] == "lit-001"
    finally:
        temp_note.unlink(missing_ok=True)


def test_knowledge_attach_file_and_get_should_return_attachments() -> None:
    """知识附件绑定后应能通过 `knowledge_get` 读回。"""

    index_table = init_empty_knowledge_index_table()
    attachments_table = init_empty_knowledge_attachments_table()
    index_table, record, _ = knowledge_upsert(
        index_table,
        {
            "uid_knowledge": "kn-001",
            "note_path": "knowledge/notes/a.md",
            "title": "知识卡片 A",
        },
    )

    index_table, attachments_table, relation = knowledge_attach_file(
        index_table,
        attachments_table,
        uid_knowledge=record["uid_knowledge"],
        attachment_name="assets/chart.png",
        attachment_type="image",
        storage_path="knowledge/attachments/chart.png",
    )
    assert relation["attachment_name"] == "chart.png"

    fetched = knowledge_get(index_table, attachments_table, uid_knowledge=record["uid_knowledge"])
    assert fetched["uid_knowledge"] == "kn-001"
    assert len(fetched["attachments"]) == 1
    assert fetched["attachments"][0]["attachment_type"] == "image"


def test_knowledge_find_by_literature_should_filter_bound_notes() -> None:
    """按文献 UID 和笔记类型应能筛出绑定知识笔记。"""

    index_table = init_empty_knowledge_index_table()
    index_table, _, _ = knowledge_upsert(
        index_table,
        {
            "uid_knowledge": "kn-001",
            "note_path": "knowledge/notes/a.md",
            "title": "标准笔记",
            "note_type": "literature_standard_note",
            "uid_literature": "lit-001",
            "cite_key": "smith-2024-a-paper",
        },
    )
    index_table, _, _ = knowledge_upsert(
        index_table,
        {
            "uid_knowledge": "kn-002",
            "note_path": "knowledge/notes/b.md",
            "title": "普通知识卡片",
            "note_type": "knowledge_note",
            "uid_literature": "lit-002",
        },
    )

    matches = knowledge_find_by_literature(
        index_table,
        uid_literature="lit-001",
        note_type="literature_standard_note",
    )
    assert len(matches) == 1
    assert matches[0]["uid_knowledge"] == "kn-001"


def test_knowledge_note_register_validate_and_bind_should_work() -> None:
    """知识笔记注册、校验和文献标准笔记绑定应可联动。"""

    temp_note = Path("tmp_register_note.md").resolve()
    try:
        created = knowledge_note_register(
            note_path=temp_note,
            title="机制知识卡片",
            uid_knowledge="kn-reg-001",
            note_type="knowledge_note",
            evidence_uids=["lit-001"],
            tags=["aok/knowledge"],
        )
        assert created["uid_knowledge"] == "kn-reg-001"

        validation = knowledge_note_validate_obsidian(temp_note)
        assert validation["valid"] is True

        bound = knowledge_bind_literature_standard_note(
            note_path=temp_note,
            uid_literature="lit-001",
            cite_key="smith-2024-a-paper",
        )
        assert bound["note_type"] == "literature_standard_note"
        assert bound["uid_literature"] == "lit-001"
    finally:
        temp_note.unlink(missing_ok=True)


def test_knowledge_base_generate_and_index_sync_should_work() -> None:
    """Bases 视图生成与索引同步兼容接口应可用。"""

    temp_dir = Path("tmp_knowledge_views").resolve()
    temp_note = Path("tmp_index_sync.md").resolve()
    try:
        generated = knowledge_base_generate(temp_dir)
        assert len(generated) == 2
        assert generated[0].exists()
        assert generated[1].exists()

        knowledge_note_register(
            note_path=temp_note,
            title="同步测试笔记",
            uid_knowledge="kn-sync-001",
            evidence_uids=["lit-002"],
        )
        index_table = init_empty_knowledge_index_table()
        index_table, row = knowledge_index_sync_from_note(index_table, temp_note, workspace_root=temp_note.parent)
        assert len(index_table) == 1
        assert row["uid_knowledge"] == "kn-sync-001"
    finally:
        if temp_note.exists():
            temp_note.unlink(missing_ok=True)
        if temp_dir.exists():
            for child in temp_dir.iterdir():
                child.unlink(missing_ok=True)
            temp_dir.rmdir()