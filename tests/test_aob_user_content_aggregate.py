"""AOB 用户级内容聚合测试。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools.atomic.aob_runtime.library_tool import 聚合用户级内容
from autodokit.tools.atomic.aob_runtime.library_tool import 路径配置


def test_aggregate_user_content_should_copy_newer_sources_and_skip_older_targets(tmp_path: Path) -> None:
    """同名条目冲突时，应优先保留较新的来源内容。"""

    repo_root = tmp_path / "repo"
    libs_root = repo_root / "libs"
    db_root = repo_root / "database"
    (libs_root / "agents").mkdir(parents=True, exist_ok=True)
    db_root.mkdir(parents=True, exist_ok=True)

    target_agent = libs_root / "agents" / "demo.agent.md"
    target_agent.write_text("old target\n", encoding="utf-8")

    source_root = tmp_path / ".copilot"
    (source_root / "agents").mkdir(parents=True, exist_ok=True)
    source_agent = source_root / "agents" / "demo.agent.md"
    source_agent.write_text("new source\n", encoding="utf-8")

    target_time = 1_700_000_000
    source_time = target_time + 10
    target_agent.touch()
    source_agent.touch()
    target_agent.chmod(0o666)
    source_agent.chmod(0o666)
    import os
    os.utime(target_agent, (target_time, target_time))
    os.utime(source_agent, (source_time, source_time))

    paths = 路径配置(
        repo_root=repo_root,
        libs_root=libs_root,
        db_root=db_root,
        items_csv=db_root / "items.csv",
        relation_csv=db_root / "item_scenario_relation.csv",
        manifest_json=db_root / "items_manifest.json",
        profile_db_json=db_root / "workspace_target_profiles.json",
        registry_sqlite=db_root / "items_registry.sqlite3",
    )

    stats = 聚合用户级内容(
        paths,
        source_paths=[str(source_root)],
        home_dir="",
        dry_run=False,
        sync_items_after=False,
    )

    assert stats["updated"] == 1
    assert stats["added"] == 0
    assert target_agent.read_text(encoding="utf-8") == "new source\n"


def test_aggregate_user_content_should_support_prompt_suffix_routing(tmp_path: Path) -> None:
    """VS Code prompts 目录中的文件应按后缀路由到目标内容目录。"""

    repo_root = tmp_path / "repo"
    libs_root = repo_root / "libs"
    db_root = repo_root / "database"
    libs_root.mkdir(parents=True, exist_ok=True)
    db_root.mkdir(parents=True, exist_ok=True)

    prompt_root = tmp_path / "prompts"
    prompt_root.mkdir(parents=True, exist_ok=True)
    (prompt_root / "common.instructions.md").write_text("instruction body\n", encoding="utf-8")
    (prompt_root / "tool.prompt.md").write_text("prompt body\n", encoding="utf-8")

    paths = 路径配置(
        repo_root=repo_root,
        libs_root=libs_root,
        db_root=db_root,
        items_csv=db_root / "items.csv",
        relation_csv=db_root / "item_scenario_relation.csv",
        manifest_json=db_root / "items_manifest.json",
        profile_db_json=db_root / "workspace_target_profiles.json",
        registry_sqlite=db_root / "items_registry.sqlite3",
    )

    stats = 聚合用户级内容(
        paths,
        source_paths=[str(prompt_root)],
        home_dir="",
        dry_run=False,
        sync_items_after=False,
    )

    assert stats["added"] == 2
    assert (libs_root / "instructions" / "common.instructions.md").exists()
    assert (libs_root / "prompts" / "tool.prompt.md").exists()


def test_aggregate_user_content_should_skip_non_skill_entries_under_skills_root(tmp_path: Path) -> None:
    """skills 根目录下的非技能目录和散落文件不应被聚合为技能。"""

    repo_root = tmp_path / "repo"
    libs_root = repo_root / "libs"
    db_root = repo_root / "database"
    libs_root.mkdir(parents=True, exist_ok=True)
    db_root.mkdir(parents=True, exist_ok=True)

    source_root = tmp_path / ".copilot"
    skills_root = source_root / "skills"
    valid_skill = skills_root / "valid-skill"
    invalid_dir = skills_root / "logs"
    loose_file = skills_root / "rename_skills_and_sync_refs.py"

    valid_skill.mkdir(parents=True, exist_ok=True)
    invalid_dir.mkdir(parents=True, exist_ok=True)
    (valid_skill / "SKILL.md").write_text("# valid\n", encoding="utf-8")
    (invalid_dir / "runtime.log").write_text("noise\n", encoding="utf-8")
    loose_file.write_text("print('noise')\n", encoding="utf-8")

    paths = 路径配置(
        repo_root=repo_root,
        libs_root=libs_root,
        db_root=db_root,
        items_csv=db_root / "items.csv",
        relation_csv=db_root / "item_scenario_relation.csv",
        manifest_json=db_root / "items_manifest.json",
        profile_db_json=db_root / "workspace_target_profiles.json",
        registry_sqlite=db_root / "items_registry.sqlite3",
    )

    stats = 聚合用户级内容(
        paths,
        source_paths=[str(source_root)],
        home_dir="",
        dry_run=False,
        sync_items_after=False,
    )

    assert stats["added"] == 1
    assert (libs_root / "skills" / "valid-skill" / "SKILL.md").exists()
    assert not (libs_root / "skills" / "logs").exists()
    assert not (libs_root / "skills" / "rename_skills_and_sync_refs.py").exists()