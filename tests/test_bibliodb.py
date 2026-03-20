"""bibliodb 工具模块测试。"""

from __future__ import annotations

from autodokit.tools.bibliodb import (
    clean_title_text,
    create_placeholder,
    find_match,
    generate_uid,
    init_empty_table,
    insert_placeholder_from_reference,
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


def test_placeholder_and_match_and_pdf_status() -> None:
    """占位插入、匹配与原文状态更新应可用。"""

    table = init_empty_table()
    table, inserted, action = create_placeholder(
        table=table,
        first_author="Alice",
        year=2024,
        title="On systemic-risk: a survey",
        clean_title="on_systemic_risk_a_survey",
    )
    assert action == "inserted"
    assert inserted["is_placeholder"] == 1
    assert not str(inserted["uid"]).startswith("ph-")

    matches = find_match(table, first_author="Alice", year=2024, title="On systemic risk a survey")
    assert matches
    uid = matches[0]["uid"]

    table, updated = update_pdf_status(table=table, uid=uid, has_pdf=1, pdf_path="D:/pdfs/a.pdf")
    assert int(updated["是否有原文"]) == 1
    assert str(updated["pdf_path"]) == "D:/pdfs/a.pdf"


def test_parse_reference_text_should_extract_author_year_and_title() -> None:
    """`parse_reference_text` 应能解析常见格式参考文献信息。"""

    parsed = parse_reference_text("[12] Smith, J. 2020. Systemic-risk contagion in banking networks.")
    assert parsed.first_author.lower().startswith("smith")
    assert parsed.year_int == 2020
    assert "contagion" in parsed.title.lower()
    assert parsed.clean_title == "systemic_risk_contagion_in_banking_networks"


def test_insert_placeholder_from_reference_should_skip_when_exists() -> None:
    """`insert_placeholder_from_reference` 在命中已有记录时不应重复插入。"""

    table = init_empty_table()
    table, _, _ = create_placeholder(
        table=table,
        first_author="Smith",
        year=2020,
        title="Systemic risk contagion in banking networks",
        clean_title="systemic_risk_contagion_in_banking_networks",
    )

    new_table, record, action = insert_placeholder_from_reference(
        table=table,
        reference_text="Smith, J. (2020). Systemic risk contagion in banking networks.",
    )
    assert action == "exists"
    assert len(new_table) == len(table)
    assert record["matched"]["uid"]


def test_insert_placeholder_from_reference_should_insert_when_missing() -> None:
    """`insert_placeholder_from_reference` 在未命中时应插入占位记录。"""

    table = init_empty_table()
    new_table, record, action = insert_placeholder_from_reference(
        table=table,
        reference_text="Minsky, H. 1986. Stabilizing an Unstable Economy.",
    )
    assert action in {"inserted", "updated"}
    assert len(new_table) == 1
    assert record["is_placeholder"] == 1
    assert int(record["是否有原文"]) == 0
