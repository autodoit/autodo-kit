"""Obsidian 笔记时区与主链入口注册表工具测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodokit.tools import (
    batch_rewrite_obsidian_note_timestamps,
    knowledge_note_register,
    resolve_mainline_affair_entry,
    write_mainline_affair_entry_registry,
)
from autodokit.tools.task_docs import build_front_matter
from autodokit.api import import_affair_module


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


def test_write_mainline_affair_entry_registry_should_include_current_review_and_non_review_chain_entries(tmp_path: Path) -> None:
    """主链入口注册表应写出恢复后的 A110/A130/A140/A150 四节点入口。"""

    output_path = tmp_path / "affair_entry_registry.json"
    write_mainline_affair_entry_registry(output_path, workspace_root=tmp_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    a110 = resolve_mainline_affair_entry("A110", payload)
    a130 = resolve_mainline_affair_entry("A130", payload)
    a140 = resolve_mainline_affair_entry("A140", payload)
    a150 = resolve_mainline_affair_entry("A150", payload)
    a170 = resolve_mainline_affair_entry("A170", payload)
    a180 = resolve_mainline_affair_entry("A180", payload)
    a190 = resolve_mainline_affair_entry("A190", payload)
    assert a110["node_name"] == "综述文献候选视图构建"
    assert a110["affair_uid"] == "ar_A060_综述文献候选视图构建"
    assert a110["module"] == "autodokit.affairs.候选文献视图构建.affair"
    assert a110["config_path"].endswith("A110.json")
    assert a130["node_name"] == "综述文献研读"
    assert a130["affair_uid"] == "ar_A070_综述文献研读"
    assert a130["module"] == "autodokit.affairs.候选文献视图构建.affair"
    assert a130["config_path"].endswith("A130.json")
    assert a140["node_name"] == "普通文献候选视图构建"
    assert a140["affair_uid"] == "ar_A075_普通文献候选视图构建"
    assert a140["module"] == "autodokit.affairs.非综述候选种子生成.affair"
    assert a140["config_path"].endswith("A140.json")
    assert a150["node_name"] == "普通文献泛读"
    assert a150["affair_uid"] == "ar_A080_普通文献泛读"
    assert a150["module"] == "autodokit.affairs.非综述候选视图构建.affair"
    assert a150["config_path"].endswith("A150.json")
    assert a170["node_name"] == "文献批判性研读"
    assert a170["affair_uid"] == "ar_A100_文献批判性研读"
    assert a170["module"] == "autodokit.affairs.文献研读与正式知识回写.affair"
    assert a170["config_path"].endswith("A170.json")
    assert a180["node_name"] == "研究脉络梳理"
    assert a180["affair_uid"] == "ar_A110_研究脉络梳理"
    assert a180["implemented"] is True
    assert a180["module"] == "autodokit.affairs.文献矩阵.affair"
    assert a190["node_name"] == "创新点凝练"
    assert a190["affair_uid"] == "ar_A140_创新点凝练"
    with pytest.raises(KeyError):
        resolve_mainline_affair_entry("A120", payload)


def test_import_affair_module_should_resolve_new_merged_affair_uid() -> None:
    """恢复后的 A110/A130/A140/A150 affair_uid 应可直接解析到官方模块。"""

    a060_module = import_affair_module(affair_uid="ar_A060_综述文献候选视图构建")
    a070_module = import_affair_module(affair_uid="ar_A070_综述文献研读")
    a075_module = import_affair_module(affair_uid="ar_A075_普通文献候选视图构建")
    a080_module = import_affair_module(affair_uid="ar_A080_普通文献泛读")
    a100_module = import_affair_module(affair_uid="ar_A100_文献批判性研读")
    a110_module = import_affair_module(affair_uid="ar_A110_研究脉络梳理")
    a140_module = import_affair_module(affair_uid="ar_A140_创新点凝练")

    assert a060_module.__name__ == "autodokit.affairs.候选文献视图构建.affair"
    assert a070_module.__name__ == "autodokit.affairs.候选文献视图构建.affair"
    assert a075_module.__name__ == "autodokit.affairs.非综述候选种子生成.affair"
    assert a080_module.__name__ == "autodokit.affairs.非综述候选视图构建.affair"
    assert a100_module.__name__ == "autodokit.affairs.文献研读与正式知识回写.affair"
    assert a110_module.__name__ == "autodokit.affairs.文献矩阵.affair"
    assert a140_module.__name__ == "autodokit.affairs.创新点池构建.affair"


def test_build_front_matter_should_use_beijing_time() -> None:
    """任务文档 frontmatter 的 created 应默认使用北京时间。"""

    front_matter = build_front_matter(title="任务文档", doc_type="设计", uid="uid-001")
    assert "+08:00" in front_matter
    assert "Z" not in front_matter