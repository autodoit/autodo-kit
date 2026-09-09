"""AOB 去污染逻辑专项测试。

覆盖 `是否旧同步污染key` 与 `过滤旧同步污染条目` 的核心行为：
1. vendor 后缀（-claude/-codex/...）识别为污染。
2. 合法名称（含数字但不以 -数字 结尾）不误杀。
3. 数字后缀重复（-2/-3）的过滤规则。
4. 多 side 混合污染的过滤统计。
5. 空输入与无污染场景。

注：当前实现中 `all_entries` 使用 `content` 字段做内容比较，但扁平化条目的
实际字段是 `value_hash`，导致内容比较恒等（""==""），数字后缀且 base 存在时
一律过滤。这是"宽松过滤"行为，测试按实际行为断言，并在阶段 3 收紧。
"""

from __future__ import annotations

from autodokit.tools.atomic.aob_runtime.aob_common import (
    AOL扁平化逻辑条目,
    过滤旧同步污染条目,
    是否旧同步污染key,
)


def _make_payload(agents: list[dict], skills: list[dict] | None = None) -> dict:
    """构造最小 AOL payload。"""

    return {
        "version": "1",
        "title": "test",
        "instructions": [],
        "agents": agents,
        "skills": skills or [],
        "rules": [],
        "commands": [],
        "hooks": [],
        "mcp_servers": {},
        "settings": {},
        "policies": {},
        "engine_native": {},
        "extra_assets": [],
    }


def _agent(agent_id: str, description: str = "d", prompt: str = "p") -> dict:
    """构造最小 agent 条目。"""

    return {"id": agent_id, "description": description, "prompt": prompt, "kind": "subagent"}


def test_vendor_suffix_should_be_marked_polluted() -> None:
    """vendor 后缀（-claude/-codex/...）应识别为污染。"""

    payload = _make_payload([_agent("demo"), _agent("demo-claude")])
    entries = AOL扁平化逻辑条目(payload)
    known = set(entries)

    assert 是否旧同步污染key("agents::demo", all_known_keys=known) is False
    assert 是否旧同步污染key("agents::demo-claude", all_known_keys=known) is True

    # 全部 vendor 后缀均应识别
    for suffix in ["claude", "codex", "copilot", "cursor", "gemini", "lingma", "qoder", "qwen", "opencode"]:
        assert 是否旧同步污染key(f"agents::demo-{suffix}", all_known_keys=known) is True


def test_legitimate_names_should_not_be_marked_polluted() -> None:
    """合法名称（含数字但不以 -数字 结尾）不应误杀。"""

    assert 是否旧同步污染key("skills::a010-v5", all_known_keys=set()) is False
    assert 是否旧同步污染key("agents::my_agent_v6", all_known_keys=set()) is False
    assert 是否旧同步污染key("agents::ar-a010-import-preprocess-v6", all_known_keys=set()) is False
    assert 是否旧同步污染key("agents::demo", all_known_keys=set()) is False
    assert 是否旧同步污染key("skills::__root", all_known_keys=set()) is False


def test_numeric_suffix_with_existing_base_should_be_polluted() -> None:
    """数字后缀（-2/-3）且 base key 存在时应识别为污染。"""

    payload = _make_payload([_agent("demo"), _agent("demo-2")])
    entries = AOL扁平化逻辑条目(payload)
    known = set(entries)

    assert 是否旧同步污染key("agents::demo-2", all_known_keys=known) is True


def test_numeric_suffix_without_base_should_not_be_polluted() -> None:
    """数字后缀但 base key 不存在时不应识别为污染。"""

    payload = _make_payload([_agent("demo-2")])
    entries = AOL扁平化逻辑条目(payload)
    known = set(entries)

    assert 是否旧同步污染key("agents::demo-2", all_known_keys=known) is False


def test_numeric_suffix_with_different_content_should_be_kept() -> None:
    """内容不同时，数字后缀且 base 存在应保留（不视为污染）。

    阶段 3 修复：`all_entries` 内容比较改用 `value_hash` 字段（原实现用不存在的
    `content` 字段导致恒等比较）。现在只有当数字后缀条目与 base 内容相同时才
    过滤；内容不同视为独立条目保留。
    """

    payload = _make_payload(
        [
            _agent("demo", description="base", prompt="base prompt"),
            _agent("demo-2", description="DIFFERENT", prompt="DIFFERENT prompt"),
        ]
    )
    entries = AOL扁平化逻辑条目(payload)
    known = set(entries)

    # 内容不同 → 保留
    assert 是否旧同步污染key("agents::demo-2", all_known_keys=known, all_entries=entries) is False


def test_numeric_suffix_with_same_content_should_be_polluted() -> None:
    """内容相同时，数字后缀且 base 存在应过滤（视为重复）。"""

    payload = _make_payload(
        [
            _agent("demo", description="same", prompt="same prompt"),
            _agent("demo-2", description="same", prompt="same prompt"),
        ]
    )
    entries = AOL扁平化逻辑条目(payload)
    known = set(entries)

    # 内容相同 → 过滤
    assert 是否旧同步污染key("agents::demo-2", all_known_keys=known, all_entries=entries) is True


def test_filter_should_remove_polluted_entries_across_sides() -> None:
    """多 side 混合污染应被过滤，并返回 per_side 统计。"""

    libs_payload = _make_payload(
        [_agent("demo"), _agent("demo-claude"), _agent("demo-copilot")]
    )
    target_payload = _make_payload([_agent("demo-2")])

    side_entries = {
        "libs": AOL扁平化逻辑条目(libs_payload),
        "target:copilot": AOL扁平化逻辑条目(target_payload),
    }

    cleaned, stats = 过滤旧同步污染条目(side_entries)

    # demo-claude、demo-copilot（vendor 后缀）+ demo-2（数字后缀，与 base demo 业务内容相同）
    assert stats["removed"] == 3
    assert stats["per_side"]["libs"] == 2
    assert stats["per_side"]["target:copilot"] == 1

    # 保留 base，过滤变体
    assert "agents::demo" in cleaned["libs"]
    assert "agents::demo-claude" not in cleaned["libs"]
    assert "agents::demo-copilot" not in cleaned["libs"]
    assert "agents::demo-2" not in cleaned["target:copilot"]


def test_filter_without_pollution_should_keep_all() -> None:
    """无污染时应保留全部条目，removed=0。"""

    payload = _make_payload([_agent("demo"), _agent("other")])
    side_entries = {"libs": AOL扁平化逻辑条目(payload)}

    cleaned, stats = 过滤旧同步污染条目(side_entries)

    assert stats["removed"] == 0
    assert set(cleaned["libs"]) == set(side_entries["libs"])


def test_filter_with_empty_input() -> None:
    """空输入应返回空结果与 removed=0。"""

    cleaned, stats = 过滤旧同步污染条目({})

    assert cleaned == {}
    assert stats["removed"] == 0
    assert stats["per_side"] == {}


def test_filter_should_promote_orphan_vendor_variant_to_base() -> None:
    """base 缺失的 vendor 变体应提升为 base（保留唯一内容），而非删除。"""

    # 只有 demo-claude，没有 demo（base 缺失）
    payload = _make_payload([_agent("demo-claude", description="only content", prompt="p")])
    side_entries = {"libs": AOL扁平化逻辑条目(payload)}

    cleaned, stats = 过滤旧同步污染条目(side_entries)

    assert stats["removed"] == 0
    assert stats["promoted"] == 1
    # 变体被提升为无后缀 base
    assert "agents::demo" in cleaned["libs"]
    assert "agents::demo-claude" not in cleaned["libs"]
    assert cleaned["libs"]["agents::demo"]["value"]["id"] == "demo"
    assert cleaned["libs"]["agents::demo"]["value"]["description"] == "only content"


def test_filter_should_not_promote_when_disabled() -> None:
    """promote_orphan_variants=False 时，base 缺失的 vendor 变体应被删除。"""

    payload = _make_payload([_agent("demo-claude")])
    side_entries = {"libs": AOL扁平化逻辑条目(payload)}

    cleaned, stats = 过滤旧同步污染条目(side_entries, promote_orphan_variants=False)

    assert stats["removed"] == 1
    assert stats["promoted"] == 0
    assert "agents::demo" not in cleaned["libs"]
    assert "agents::demo-claude" not in cleaned["libs"]


def test_filter_should_only_affect_agents_skills_rules_commands() -> None:
    """过滤应只作用于命名型域（agents/skills/rules/commands），不误伤其他域。"""

    payload = {
        "version": "1",
        "title": "test",
        "instructions": ["some instruction"],
        "agents": [_agent("demo"), _agent("demo-claude")],
        "skills": [],
        "rules": [],
        "commands": [],
        "hooks": [{"path": "hooks/check.md", "content": "x"}],
        "mcp_servers": {"server-a": {"command": "cmd"}},
        "settings": {"key": "value"},
        "policies": {},
        "engine_native": {"claude": {"extra": 1}},
        "extra_assets": [],
    }
    side_entries = {"libs": AOL扁平化逻辑条目(payload)}

    cleaned, stats = 过滤旧同步污染条目(side_entries)

    # 只过滤 agents::demo-claude（vendor 后缀）
    assert stats["removed"] == 1
    assert "agents::demo" in cleaned["libs"]
    assert "agents::demo-claude" not in cleaned["libs"]
    # 非命名型域不受影响
    assert "hooks::hooks/check.md" in cleaned["libs"]
    assert "mcp_servers::server-a" in cleaned["libs"]
    assert "settings::__root" in cleaned["libs"]
    assert "engine_native::claude" in cleaned["libs"]
