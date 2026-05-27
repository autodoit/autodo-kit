"""AOB 用户级内容聚合测试。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from autodokit.tools.atomic.aob_runtime.library_tool import 聚合用户级内容
from autodokit.tools.atomic.aob_runtime.library_tool import 路径配置


def _build_paths(repo_root: Path) -> 路径配置:
    libs_root = repo_root / "libs"
    db_root = repo_root / "database"
    libs_root.mkdir(parents=True, exist_ok=True)
    db_root.mkdir(parents=True, exist_ok=True)
    return 路径配置(
        repo_root=repo_root,
        libs_root=libs_root,
        db_root=db_root,
        items_csv=db_root / "items.csv",
        relation_csv=db_root / "item_scenario_relation.csv",
        manifest_json=db_root / "items_manifest.json",
        profile_db_json=db_root / "workspace_target_profiles.json",
        registry_sqlite=db_root / "items_registry.sqlite3",
    )


def _read_canonical(paths: 路径配置) -> dict:
    canonical_path = paths.libs_root / "aol" / "canonical.aol.json"
    return json.loads(canonical_path.read_text(encoding="utf-8"))


def test_aggregate_user_content_should_generate_canonical_aol_snapshot(tmp_path: Path) -> None:
    """结构化来源应被统一转换并写入 canonical AOL。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)

    source_root = tmp_path / ".claude"
    (source_root / "agents").mkdir(parents=True, exist_ok=True)
    (source_root / "skills" / "demo-skill").mkdir(parents=True, exist_ok=True)
    (source_root / "agents" / "demo.agent.md").write_text("demo agent\n", encoding="utf-8")
    (source_root / "skills" / "demo-skill" / "SKILL.md").write_text("demo skill\n", encoding="utf-8")

    stats = 聚合用户级内容(
        paths,
        source_paths=[str(source_root)],
        home_dir="",
        dry_run=False,
        sync_items_after=False,
    )

    assert stats["canonical_aol"]["status"] in {"added", "updated", "unchanged"}
    assert stats["aol_intermediate"]["status"] == "ok"

    canonical = _read_canonical(paths)
    assert canonical["schema"] == "aol_canonical_json_v1"
    assert len(canonical["aol"]["agents"]) >= 1
    assert len(canonical["aol"]["skills"]) >= 1


def test_aggregate_user_content_should_collect_prompt_root_into_extra_assets(tmp_path: Path) -> None:
    """prompts 根目录来源应进入 canonical AOL 的 extra_assets。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)

    prompt_root = tmp_path / "Code" / "User" / "prompts"
    prompt_root.mkdir(parents=True, exist_ok=True)
    (prompt_root / "tool.prompt.md").write_text("prompt body\n", encoding="utf-8")
    (prompt_root / "common.instructions.md").write_text("instruction body\n", encoding="utf-8")

    聚合用户级内容(
        paths,
        source_paths=[str(prompt_root)],
        home_dir="",
        dry_run=False,
        sync_items_after=False,
    )

    canonical = _read_canonical(paths)
    extra_paths = {item["path"] for item in canonical["aol"].get("extra_assets", [])}
    assert "prompts/tool.prompt.md" in extra_paths
    assert "instructions/common.instructions.md" in extra_paths


def test_aggregate_user_content_should_not_write_canonical_file_in_dry_run(tmp_path: Path) -> None:
    """dry-run 只返回中转摘要，不应写入 canonical AOL 文件。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)

    source_root = tmp_path / ".copilot"
    (source_root / "agents").mkdir(parents=True, exist_ok=True)
    (source_root / "agents" / "demo.agent.md").write_text("demo\n", encoding="utf-8")

    stats = 聚合用户级内容(
        paths,
        source_paths=[str(source_root)],
        home_dir="",
        dry_run=True,
        sync_items_after=False,
    )

    assert stats["aol_intermediate"]["source"] == "in_memory_dry_run"
    assert not (paths.libs_root / "aol" / "canonical.aol.json").exists()


def test_aggregate_user_content_simulate_only_should_default_sandbox_to_downloads_timestamp_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """simulate_only 且未指定 sandbox_dir 时，应默认落到 Downloads 时间戳目录。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)

    home_dir = tmp_path / "home"
    monkeypatch.setenv("USERPROFILE", str(home_dir))

    source_root = home_dir / ".claude"
    (source_root / "agents").mkdir(parents=True, exist_ok=True)
    (source_root / "agents" / "demo.agent.md").write_text("demo agent\n", encoding="utf-8")

    stats = 聚合用户级内容(
        paths,
        source_paths=[str(source_root)],
        home_dir=str(home_dir),
        dry_run=False,
        sync_items_after=False,
        simulate_only=True,
        sandbox_dir="",
    )

    sandbox_root = Path(stats["sandbox"]["sandbox_root"])
    assert sandbox_root.parent == home_dir / "Downloads"
    assert re.fullmatch(r"aob-sync-sandbox-\d{14}(?:-\d+)?", sandbox_root.name)

    assert not (paths.libs_root / "aol" / "canonical.aol.json").exists()
    assert (sandbox_root / "libs" / "aol" / "canonical.aol.json").exists()