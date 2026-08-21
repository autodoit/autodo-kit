from pathlib import Path

from autodokit.tools.chat_session_index_tools import ChatSessionStore, parse_markdown_conversation


def test_markdown_import_and_pair_lookup(tmp_path: Path) -> None:
    source = tmp_path / "conversation.md"
    source.write_text("# 记录\n\n## 用户\n\n第一个问题\n\n## 助手\n\n第一个回答\n\n## 用户\n\n未回答的问题\n", encoding="utf-8")
    store = ChatSessionStore(tmp_path / "chat_repo")
    result = store.import_markdown(source, tags=["测试", "索引"])
    assert len(result["pair_ids"]) == 1
    pair = store.get_pair_info(result["pair_ids"][0])
    assert pair and "第一个回答" in pair["content"]
    assert store.search_by_tag("测试")[0]["session_id"] == result["session_id"]
    assert parse_markdown_conversation(source.read_text(encoding="utf-8"))[-1]["role"] == "user"


def test_single_parent_inherit_chain(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path / "chat_repo")
    parent = store.import_messages(
        [{"role": "user", "content": "父问题"}, {"role": "assistant", "content": "父回答"}],
        source_name="parent.md",
    )
    child = store.import_messages(
        [{"role": "user", "content": "子问题"}, {"role": "assistant", "content": "子回答"}],
        source_name="child.md",
        parent_session_id=parent["session_id"],
        fork_at_pair_id=parent["pair_ids"][0],
    )
    chain = store.get_session_inherit_chain(child["session_id"])
    assert [item["session_id"] for item in chain] == [parent["session_id"], child["session_id"]]
    assert chain[0]["inherited_pair_ids"] == parent["pair_ids"]
