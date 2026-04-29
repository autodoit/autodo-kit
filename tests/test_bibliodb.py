"""bibliodb 工具模块测试。"""

from __future__ import annotations

from autodokit.tools.bibliodb import (
    clean_title_text,
    generate_uid,
    init_empty_attachments_table,
    init_empty_literatures_table,
    insert_placeholder_from_reference,
    literature_attach_file,
    literature_bind_standard_note,
    literature_get,
    literature_match,
    literature_upsert,
    parse_reference_text,
    update_pdf_status,
)


def test_clean_title_text_should_normalize_spaces_and_symbols() -> None:
    """`clean_title_text` 应按规则处理空格、连字符和符号。"""

    result = clean_title_text("On systemic-risk: a survey")
    assert result == "on_systemic_risk_a_survey"


def test_generate_uid_should_be_stable() -> None:
    """`generate_uid` 对相同输入应生成稳定结果。"""

    uid1 = generate_uid("Alice", 2024, "on systemic risk")
    uid2 = generate_uid("Alice", 2024, "on systemic risk")
    assert uid1 == uid2
    assert uid1.startswith("lit-")


def test_literature_upsert_should_insert_record_with_003_fields() -> None:
    """`literature_upsert` 应按 003 契约插入文献记录。"""

    table = init_empty_literatures_table()
    table, record, action = literature_upsert(
        table,
        {
            "title": "On systemic-risk: a survey",
            "first_author": "Alice",
            "year": "2024",
            "entry_type": "article",
        },
    )
    assert action == "inserted"
    assert record["uid_literature"].startswith("lit-")
    assert record["cite_key"].startswith("alice-2024-")
    assert int(record["has_fulltext"]) == 0
    assert len(table) == 1


def test_placeholder_and_match_and_pdf_status_should_work() -> None:
    """占位插入、匹配与原文状态更新应可用。"""

    table = init_empty_literatures_table()
    table, inserted, action = insert_placeholder_from_reference(
        table=table,
        reference_text="Alice. 2024. On systemic-risk: a survey.",
    )
    assert action in {"inserted", "updated"}
    assert inserted["is_placeholder"] == 1

    matches = literature_match(table, first_author="Alice", year=2024, title="On systemic risk a survey")
    assert matches
    uid = matches[0]["uid_literature"]

    table, updated = update_pdf_status(table=table, uid=uid, has_pdf=1, pdf_path="/tmp/pdfs/a.pdf")
    assert int(updated["has_fulltext"]) == 1
    assert str(updated["primary_attachment_name"]) == "a.pdf"


def test_parse_reference_text_should_extract_author_year_and_title() -> None:
    """`parse_reference_text` 应能解析常见格式参考文献信息。"""

    parsed = parse_reference_text("[12] Smith, J. 2020. Systemic-risk contagion in banking networks.")
    assert parsed.first_author.lower().startswith("smith")
    assert parsed.year_int == 2020
    assert "contagion" in parsed.title.lower()
    assert parsed.clean_title == "systemic_risk_contagion_in_banking_networks"


def test_insert_placeholder_from_reference_should_skip_when_exists() -> None:
    """命中已有记录时不应重复插入。"""

    table = init_empty_literatures_table()
    table, _, _ = literature_upsert(
        table,
        {
            "title": "Systemic risk contagion in banking networks",
            "first_author": "Smith",
            "year": "2020",
            "entry_type": "article",
        },
    )

    new_table, record, action = insert_placeholder_from_reference(
        table=table,
        reference_text="Smith, J. (2020). Systemic risk contagion in banking networks.",
    )
    assert action == "exists"
    assert len(new_table) == len(table)
    assert record["matched"]["uid_literature"]


def test_literature_attach_file_should_sync_primary_attachment() -> None:
    """绑定原文附件时应联动主表原文字段。"""

    literatures = init_empty_literatures_table()
    attachments = init_empty_attachments_table()
    literatures, record, _ = literature_upsert(
        literatures,
        {
            "title": "A paper",
            "first_author": "Alice",
            "year": "2024",
            "entry_type": "article",
        },
    )

    literatures, attachments, relation = literature_attach_file(
        literatures,
        attachments,
        uid_literature=record["uid_literature"],
        attachment_name="/tmp/papers/a-paper.pdf",
        attachment_type="fulltext",
        is_primary=1,
    )
    assert relation["attachment_name"] == "a-paper.pdf"
    fetched = literature_get(literatures, attachments, uid_literature=record["uid_literature"])
    assert fetched["primary_attachment_name"] == "a-paper.pdf"
    assert int(fetched["has_fulltext"]) == 1
    assert len(fetched["attachments"]) == 1


def test_literature_bind_standard_note_should_write_binding() -> None:
    """绑定文献标准笔记时应写入唯一绑定字段。"""

    literatures = init_empty_literatures_table()
    literatures, record, _ = literature_upsert(
        literatures,
        {
            "title": "Bound paper",
            "first_author": "Bob",
            "year": "2023",
            "entry_type": "article",
        },
    )

    literatures, updated = literature_bind_standard_note(
        literatures,
        uid_literature=record["uid_literature"],
        standard_note_uid="kn-20260322-001",
    )
    assert updated["standard_note_uid"] == "kn-20260322-001"
