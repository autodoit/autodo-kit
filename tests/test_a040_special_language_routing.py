"""A040 特殊渠道语种分流规则测试。"""

from __future__ import annotations

from autodokit.affairs.检索治理.affair import _a040_sc_is_foreign_literature


class _FakeRow(dict):
    def keys(self):
        return super().keys()


def _row(**kwargs: object) -> _FakeRow:
    base = {
        "title": "",
        "literature_language": "",
        "language": "",
        "source_lang": "",
    }
    base.update(kwargs)
    return _FakeRow(base)


def test_foreign_language_from_canonical_column_should_pass() -> None:
    row = _row(literature_language="fr", title="中文标题也应走外文分流")
    assert _a040_sc_is_foreign_literature(row) is True


def test_chinese_from_canonical_column_should_block() -> None:
    row = _row(literature_language="zh-cn", language="en", source_lang="en")
    assert _a040_sc_is_foreign_literature(row) is False


def test_fallback_to_language_field_should_pass_for_non_chinese() -> None:
    row = _row(language="de")
    assert _a040_sc_is_foreign_literature(row) is True


def test_fallback_to_title_heuristic_should_block_chinese_title() -> None:
    row = _row(title="科研协作网络演化与学科系统性变迁")
    assert _a040_sc_is_foreign_literature(row) is False


def test_fallback_to_title_heuristic_should_pass_non_chinese_title() -> None:
    row = _row(title="Collaboration network shocks and systemic scholarly change")
    assert _a040_sc_is_foreign_literature(row) is True
