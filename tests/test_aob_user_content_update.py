"""AOB 用户级内容同步测试。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from autodokit.tools.atomic.aob_runtime.library_tool import AOL扁平化逻辑条目
from autodokit.tools.atomic.aob_runtime.library_tool import 备份用户级内容
from autodokit.tools.atomic.aob_runtime.library_tool import 计算一键更新决策
from autodokit.tools.atomic.aob_runtime.library_tool import 发布目标
from autodokit.tools.atomic.aob_runtime.library_tool import 解析发布目标
from autodokit.tools.atomic.aob_runtime.library_tool import 准备用户级内容同步沙盒
from autodokit.tools.atomic.aob_runtime.library_tool import 更新用户级内容
from autodokit.tools.atomic.aob_runtime.library_tool import 路径配置


def _build_paths(repo_root: Path) -> 路径配置:
    db_root = repo_root / "database"
    libs_root = repo_root / "libs"
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


def _write_canonical(paths: 路径配置, *, prompt_content: str | None = None) -> None:
    canonical_dir = paths.libs_root / "aol"
    canonical_dir.mkdir(parents=True, exist_ok=True)

    extra_assets: list[dict[str, str]] = []
    if prompt_content is not None:
        extra_assets.append({"path": "prompts/tool.prompt.md", "content": prompt_content})

    payload = {
        "schema": "aol_canonical_json_v1",
        "aol": {
            "version": "1",
            "title": "test canonical",
            "instructions": ["canonical instruction"],
            "agents": [
                {
                    "id": "demo",
                    "description": "demo agent",
                    "prompt": "demo prompt",
                    "kind": "subagent",
                }
            ],
            "skills": [],
            "rules": [],
            "commands": [],
            "hooks": [],
            "mcp_servers": {},
            "settings": {},
            "policies": {},
            "engine_native": {},
            "extra_assets": extra_assets,
        },
    }
    (canonical_dir / "canonical.aol.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_canonical(paths: 路径配置) -> dict:
    canonical_path = paths.libs_root / "aol" / "canonical.aol.json"
    return json.loads(canonical_path.read_text(encoding="utf-8"))


def _prepare_fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    appdata_root = home_dir / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata_root))
    return home_dir


def _write_workspace_profiles(paths: 路径配置) -> None:
    payload = {
        "schema_version": 1,
        "profiles": [
            {
                "profile_id": "vscode_copilot_win11",
                "ide_vendor": "vscode",
                "engine_vendor": "copilot",
                "workspace_dir_name": ".github",
                "install_scope": "workspace",
                "project_config_paths": [],
                "instruction_paths": [".github/copilot-instructions.md", ".github/rules/*.md"],
            },
            {
                "profile_id": "claude_native_win11",
                "ide_vendor": "claude",
                "engine_vendor": "claude",
                "workspace_dir_name": ".claude",
                "install_scope": "workspace",
                "project_config_paths": [],
                "instruction_paths": ["CLAUDE.md", ".claude/rules/*.md"],
            },
        ],
    }
    paths.profile_db_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_update_user_content_should_aggregate_then_publish_to_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同步应在显式参与方之间比较后，把最新内容发布到其他目标。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    home_dir = _prepare_fake_home(tmp_path, monkeypatch)

    source_root = home_dir / ".claude"
    (source_root / "agents").mkdir(parents=True, exist_ok=True)
    (source_root / "agents" / "demo.agent.md").write_text("demo agent\n", encoding="utf-8")

    target_root = tmp_path / ".copilot"
    stats = 更新用户级内容(
        paths,
        target_paths=[str(source_root), str(target_root)],
        home_dir=str(home_dir),
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
        sync_items_after=False,
    )

    assert stats["aggregate"]["canonical_aol"]["status"] in {"unchanged", "updated", "added"}
    assert stats["publish"]["target_count"] == 2
    canonical = _read_canonical(paths)
    assert len(canonical["aol"].get("agents") or []) >= 1
    assert (target_root / "agents" / "demo.agent.md").exists()


def test_update_user_content_should_publish_prompt_assets_from_aggregate_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同步应在显式 prompt 参与方之间传播最新 prompt 资产。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    home_dir = _prepare_fake_home(tmp_path, monkeypatch)

    prompt_source = home_dir / "AppData" / "Roaming" / "Code" / "User" / "prompts"
    prompt_source.mkdir(parents=True, exist_ok=True)
    (prompt_source / "tool.prompt.md").write_text("prompt body\n", encoding="utf-8")
    (prompt_source / "common.instructions.md").write_text("instruction body\n", encoding="utf-8")

    prompt_target = tmp_path / "Cursor" / "User" / "prompts"

    更新用户级内容(
        paths,
        target_paths=[str(prompt_source), str(prompt_target)],
        home_dir=str(home_dir),
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
        sync_items_after=False,
    )

    canonical = _read_canonical(paths)
    extra_assets = canonical["aol"].get("extra_assets") or []
    extra_paths = {item.get("path") for item in extra_assets if isinstance(item, dict)}
    assert "prompts/tool.prompt.md" in extra_paths
    assert "instructions/common.instructions.md" in extra_paths
    assert (prompt_target / "tool.prompt.md").exists()
    assert (prompt_target / "common.instructions.md").exists()


def test_update_user_content_should_not_write_files_in_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dry-run 下应只预演备份、聚合、发布，不写入 canonical 与目标。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    home_dir = _prepare_fake_home(tmp_path, monkeypatch)

    source_root = home_dir / ".claude"
    (source_root / "agents").mkdir(parents=True, exist_ok=True)
    (source_root / "agents" / "demo.agent.md").write_text("demo agent\n", encoding="utf-8")

    target_root = tmp_path / ".copilot"

    stats = 更新用户级内容(
        paths,
        target_paths=[str(target_root)],
        home_dir=str(home_dir),
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=True,
        sync_items_after=False,
    )

    assert stats["aggregate"]["canonical_aol"]["status"].startswith("dry_run_")
    assert stats["publish"]["target_count"] == 1
    assert not (paths.libs_root / "aol" / "canonical.aol.json").exists()
    assert not target_root.exists()


def test_simulate_only_should_default_sandbox_to_downloads_timestamp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """simulate_only 且未指定 sandbox_dir 时，应默认落到 Downloads 时间戳目录。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    home_dir = _prepare_fake_home(tmp_path, monkeypatch)

    source_root = home_dir / ".claude"
    (source_root / "agents").mkdir(parents=True, exist_ok=True)
    (source_root / "agents" / "demo.agent.md").write_text("demo agent\n", encoding="utf-8")

    target_root = tmp_path / ".copilot"

    stats = 更新用户级内容(
        paths,
        target_paths=[str(source_root), str(target_root)],
        home_dir=str(home_dir),
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
        sync_items_after=False,
        simulate_only=True,
        sandbox_dir="",
    )

    sandbox_root = Path(stats["sandbox"]["sandbox_root"])
    assert sandbox_root.parent == home_dir / "Downloads"
    assert re.fullmatch(r"aob-sync-sandbox-\d{14}(?:-\d+)?", sandbox_root.name)


def test_sync_decision_should_choose_newer_side_without_vendor_suffix_duplicates() -> None:
    """logical key 决策应选出较新的 side，并保持单一语义身份。"""

    libs_payload = {
        "version": "1",
        "title": "test canonical",
        "instructions": [],
        "agents": [{"id": "demo", "description": "old", "prompt": "old prompt", "kind": "subagent"}],
        "skills": [],
        "rules": [],
        "commands": [],
        "hooks": [],
        "mcp_servers": {},
        "settings": {},
        "policies": {},
        "engine_native": {},
        "extra_assets": [],
    }
    newer_payload = {
        **libs_payload,
        "agents": [{"id": "demo", "description": "new", "prompt": "new prompt", "kind": "subagent"}],
    }

    final_entries, _registry_rows, registry_summary = 计算一键更新决策(
        side_entries={
            "libs": AOL扁平化逻辑条目(libs_payload),
            "target:qwen": AOL扁平化逻辑条目(newer_payload),
        },
        side_observe_times={"libs": 1_700_000_000.0, "target:qwen": 1_700_000_600.0},
        previous_registry={},
        side_priority=["libs", "target:qwen"],
    )

    assert registry_summary["fallback_count"] >= 1
    assert final_entries["agents::demo"]["identity"] == "demo"
    assert final_entries["agents::demo"]["value"]["description"] == "new"
    assert all("-qwen" not in key and "-claude" not in key for key in final_entries)


def test_prepare_sync_sandbox_should_copy_libs_and_targets_without_touching_original_targets(
    tmp_path: Path,
) -> None:
    """沙盒准备阶段应复制 libs canonical 和目标目录，但不改原文件。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    _write_canonical(paths)

    target_root = tmp_path / ".claude"
    (target_root / "agents").mkdir(parents=True, exist_ok=True)
    (target_root / "agents" / "demo.md").write_text("old target\n", encoding="utf-8")

    sandbox_root = tmp_path / "sandbox-sync"
    sandbox_paths, sandbox_targets, sandbox_summary = 准备用户级内容同步沙盒(
        paths,
        targets=[
            发布目标(
                target_path=target_root,
                target_label="claude",
                layout="structured_root",
                engine_vendor="claude",
                ide_vendor="claude",
                scope="user",
            )
        ],
        sandbox_dir=str(sandbox_root),
    )

    assert sandbox_summary["enabled"] is True
    assert Path(str(sandbox_summary["sandbox_root"])) == sandbox_root
    assert sandbox_paths.libs_root == sandbox_root / "libs"
    assert len(sandbox_targets) == 1
    assert (sandbox_root / "targets" / "claude__structured_root" / "agents").exists()
    assert (sandbox_root / "libs" / "aol" / "canonical.aol.json").exists()
    assert (target_root / "agents" / "demo.md").read_text(encoding="utf-8") == "old target\n"


def test_resolve_publish_targets_should_expand_project_profiles(
    tmp_path: Path,
) -> None:
    """project 范围应按 workspace profile 展开为多个目标实例。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    _write_workspace_profiles(paths)

    project_root = tmp_path / "demo-project"
    (project_root / ".github").mkdir(parents=True, exist_ok=True)
    (project_root / ".github" / "copilot-instructions.md").write_text("repo instruction\n", encoding="utf-8")
    (project_root / ".claude" / "rules").mkdir(parents=True, exist_ok=True)
    (project_root / ".claude" / "rules" / "policy.md").write_text("repo rule\n", encoding="utf-8")

    targets = 解析发布目标(
        [],
        paths=paths,
        home_dir="",
        engine_vendors=[],
        ide_vendors=[],
        scopes=["project"],
        project_dirs=[str(project_root)],
        include_missing=False,
    )

    assert len(targets) == 2
    assert {item.scope for item in targets} == {"project"}
    assert {(item.engine_vendor, item.ide_vendor) for item in targets} == {("copilot", "vscode"), ("claude", "claude")}
    assert {item.target_path for item in targets} == {project_root / ".github", project_root / ".claude"}


def test_prepare_sync_sandbox_should_copy_project_root_and_point_to_carrier(
    tmp_path: Path,
) -> None:
    """project 范围沙盒应复制整个项目根，但 sandbox target 指向 carrier 根。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    _write_canonical(paths)

    project_root = tmp_path / "demo-project"
    (project_root / ".claude" / "rules").mkdir(parents=True, exist_ok=True)
    (project_root / "CLAUDE.md").write_text("# project claude\n", encoding="utf-8")
    (project_root / ".claude" / "rules" / "policy.md").write_text("# policy\n", encoding="utf-8")

    sandbox_root = tmp_path / "sandbox-project-sync"
    sandbox_paths, sandbox_targets, sandbox_summary = 准备用户级内容同步沙盒(
        paths,
        targets=[
            发布目标(
                target_path=project_root / ".claude",
                target_label="claude-project",
                layout="structured_root",
                engine_vendor="claude",
                ide_vendor="claude",
                scope="project",
            )
        ],
        sandbox_dir=str(sandbox_root),
    )

    assert sandbox_summary["enabled"] is True
    assert Path(str(sandbox_summary["sandbox_root"])) == sandbox_root
    assert sandbox_paths.libs_root == sandbox_root / "libs"
    assert len(sandbox_targets) == 1
    assert sandbox_targets[0].target_path == sandbox_root / "targets" / "claude-project__structured_root" / ".claude"
    assert (sandbox_root / "targets" / "claude-project__structured_root" / "CLAUDE.md").exists()
    assert (sandbox_root / "targets" / "claude-project__structured_root" / ".claude" / "rules" / "policy.md").exists()
    assert sandbox_summary["targets"][0]["container_root"] == str(project_root)


def test_backup_user_content_should_record_project_scope_sources(
    tmp_path: Path,
) -> None:
    """project 范围备份应在 manifest 中保留 project scope。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    _write_workspace_profiles(paths)

    project_root = tmp_path / "demo-project"
    (project_root / ".github").mkdir(parents=True, exist_ok=True)
    (project_root / ".github" / "copilot-instructions.md").write_text("repo instruction\n", encoding="utf-8")

    stats = 备份用户级内容(
        paths,
        target_paths=[],
        home_dir="",
        engine_vendors=["copilot"],
        ide_vendors=["vscode"],
        include_missing=False,
        backup_dir="",
        scopes=["project"],
        project_dirs=[str(project_root)],
        dry_run=True,
    )

    project_sources = [item for item in stats["sources"] if str(item.get("source_id") or "").startswith("target:")]
    assert len(project_sources) == 1
    assert project_sources[0]["scope"] == "project"
    assert Path(project_sources[0]["source_path"]) == project_root
