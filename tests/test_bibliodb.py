"""bibliodb 工具模块测试。"""

from __future__ import annotations

from autodokit.tools.bibliodb import (
    clean_title_text,
    create_placeholder,
    find_match,
    generate_uid,
    init_empty_table,
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

    matches = find_match(table, first_author="Alice", year=2024, title="On systemic risk a survey")
    assert matches
    uid = matches[0]["uid"]

    table, updated = update_pdf_status(table=table, uid=uid, has_pdf=1, pdf_path="D:/pdfs/a.pdf")
    assert int(updated["是否有原文"]) == 1
    assert str(updated["pdf_path"]) == "D:/pdfs/a.pdf"
