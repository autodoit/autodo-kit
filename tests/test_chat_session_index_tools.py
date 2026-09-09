from pathlib import Path

from autodokit.tools.chat_session_index_tools import ChatSessionStore, parse_markdown_conversation
from autodokit.tools.chat_session_index_tools_v2 import ChatSessionStoreV2


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


def test_v2_rebuild_indexes_is_idempotent_with_existing_backup(tmp_path: Path) -> None:
    store = ChatSessionStoreV2(tmp_path / "chat_repo")
    store.import_messages(
        [
            {"role": "user", "content": "第一问题"},
            {"role": "assistant", "content": "第一回答"},
        ],
        source_name="demo.md",
        tags=["测试"],
    )

    first = store.rebuild_indexes()
    second = store.rebuild_indexes()

    assert first["sessions"] == 1
    assert second["sessions"] == 1
    assert second["pairs"] == 1


def test_v2_focus_update_detects_delta_and_skips_clean_match(tmp_path: Path) -> None:
    store = ChatSessionStoreV2(tmp_path / "chat_repo")
    initial = [
        {"role": "user", "content": "第一问题"},
        {"role": "assistant", "content": "第一回答"},
        {"role": "user", "content": "第二问题"},
        {"role": "assistant", "content": "第二回答"},
    ]
    created = store.import_messages(initial, source_name="demo.md", title="demo", tags=["测试"])

    clean_result = store.reconcile_source_messages(initial, session_id=created["session_id"], mode="focus")
    assert clean_result["status"] == "skipped"
    assert clean_result["changes"]["added"] == 0

    updated = [
        {"role": "user", "content": "第一问题"},
        {"role": "assistant", "content": "第一回答"},
        {"role": "user", "content": "第二问题"},
        {"role": "assistant", "content": "第二回答-修正"},
        {"role": "user", "content": "第三问题"},
        {"role": "assistant", "content": "第三回答"},
    ]
    focus_result = store.reconcile_source_messages(updated, session_id=created["session_id"], mode="focus")
    assert focus_result["status"] == "updated"
    assert focus_result["changes"]["modified"] >= 1
    assert focus_result["changes"]["added"] >= 1


def test_v2_append_mode_keeps_existing_session_and_adds_pairs(tmp_path: Path) -> None:
    store = ChatSessionStoreV2(tmp_path / "chat_repo")
    created = store.import_messages(
        [
            {"role": "user", "content": "原始问题"},
            {"role": "assistant", "content": "原始回答"},
        ],
        source_name="demo.md",
        title="demo",
        tags=["测试"],
    )

    appended = store.reconcile_source_messages(
        [
            {"role": "user", "content": "原始问题"},
            {"role": "assistant", "content": "原始回答"},
            {"role": "user", "content": "追加问题"},
            {"role": "assistant", "content": "追加回答"},
        ],
        session_id=created["session_id"],
        mode="append",
    )

    assert appended["status"] == "updated"
    assert appended["changes"]["added"] == 1
    assert appended["session_id"] == created["session_id"]


def test_v2_find_existing_session_matches_source_name(tmp_path: Path) -> None:
    store = ChatSessionStoreV2(tmp_path / "chat_repo")
    created = store.import_messages(
        [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "回答"},
        ],
        source_name="demo.md",
        title="demo",
        tags=["测试"],
    )

    assert store.find_existing_session(source_name="demo.md") == created["session_id"]
    assert store.find_existing_session(title="demo") == created["session_id"]
    assert store.find_existing_session(source_name="other.md") is None


def test_v2_dry_run_does_not_write_archive(tmp_path: Path) -> None:
    store = ChatSessionStoreV2(tmp_path / "chat_repo")
    created = store.import_messages(
        [
            {"role": "user", "content": "问题一"},
            {"role": "assistant", "content": "回答一"},
        ],
        source_name="demo.md",
        title="demo",
        tags=["测试"],
    )

    preview = store.reconcile_source_messages(
        [
            {"role": "user", "content": "问题一"},
            {"role": "assistant", "content": "回答一"},
            {"role": "user", "content": "问题二"},
            {"role": "assistant", "content": "回答二"},
        ],
        session_id=created["session_id"],
        mode="focus",
        dry_run=True,
    )

    assert preview["status"] == "updated"
    assert preview["dry_run"] is True
    # 预览后归档未变：仍只有 1 对
    sessions = store.search_by_tag("测试")
    assert len(sessions) == 1
    assert sessions[0]["total_qa_pairs"] == 1


def test_v2_auto_mode_resolves_to_focus_or_create(tmp_path: Path) -> None:
    store = ChatSessionStoreV2(tmp_path / "chat_repo")
    store.import_messages(
        [
            {"role": "user", "content": "问题一"},
            {"role": "assistant", "content": "回答一"},
        ],
        source_name="demo.md",
        title="demo",
        tags=["测试"],
    )

    # 同源再次导入 → 命中已有会话
    matched = store.find_existing_session(source_name="demo.md")
    assert matched is not None
    result = store.reconcile_source_messages(
        [
            {"role": "user", "content": "问题一"},
            {"role": "assistant", "content": "回答一"},
            {"role": "user", "content": "问题二"},
            {"role": "assistant", "content": "回答二"},
        ],
        session_id=matched,
        mode="focus",
    )
    assert result["status"] == "updated"
    assert result["changes"]["added"] == 1

    # 全新来源 → 无匹配
    assert store.find_existing_session(source_name="brand_new.md") is None
