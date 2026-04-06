"""Obsidian 笔记时区与主链入口注册表工具测试。"""

from __future__ import annotations

import json
from pathlib import Path

from autodokit.tools import (
    batch_rewrite_obsidian_note_timestamps,
    knowledge_note_register,
    resolve_mainline_affair_entry,
    write_mainline_affair_entry_registry,
)
from autodokit.tools.task_docs import build_front_matter


def test_batch_rewrite_obsidian_note_timestamps_should_convert_utc_to_beijing(tmp_path: Path) -> None:
    """UTC frontmatter 应可批量改写为北京时间。"""

    note_path = tmp_path / "utc_note.md"
    note_path.write_text(
        "\n".join(
            [
                "---",
                'title: "示例笔记"',
                'created: "2026-04-05T01:59:16+00:00"',
                'updated: "2026-04-05T02:10:00+00:00"',
                "---",
                "",
                "# 示例笔记",
            ]
        ),
        encoding="utf-8",
    )

    result = batch_rewrite_obsidian_note_timestamps(note_paths=[note_path])
    assert result["processed_count"] == 1
    assert result["changed_count"] == 1
    rewritten = note_path.read_text(encoding="utf-8")
    assert 'created: "2026-04-05T09:59:16+08:00"' in rewritten
    assert 'updated: "2026-04-05T10:10:00+08:00"' in rewritten


def test_knowledge_note_register_should_default_to_beijing_time(tmp_path: Path) -> None:
    """知识笔记注册默认应写入北京时间。"""

    note_path = tmp_path / "knowledge_note.md"
    knowledge_note_register(
        note_path=note_path,
        title="北京时间测试",
        uid_knowledge="kn-beijing-001",
        evidence_uids=["lit-001"],
    )
    text = note_path.read_text(encoding="utf-8")
    assert "+08:00" in text


def test_write_mainline_affair_entry_registry_should_include_a065_and_a130(tmp_path: Path) -> None:
    """主链入口注册表应写出已实现节点与设计占位节点。"""

    output_path = tmp_path / "affair_entry_registry.json"
    write_mainline_affair_entry_registry(
        output_path,
        workspace_root=tmp_path,
        node_inputs={"A065": str(tmp_path / "A065.json")},
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    a065 = resolve_mainline_affair_entry("A065", payload)
    a130 = resolve_mainline_affair_entry("A130", payload)
    assert a065["module"] == "autodokit.affairs.综述参考文献预处理与笔记骨架.affair"
    assert a065["config_path"].endswith("A065.json")
    assert a130["implemented"] is False


def test_build_front_matter_should_use_beijing_time() -> None:
    """任务文档 frontmatter 的 created 应默认使用北京时间。"""

    front_matter = build_front_matter(title="任务文档", doc_type="设计", uid="uid-001")
    assert "+08:00" in front_matter
    assert "Z" not in front_matter