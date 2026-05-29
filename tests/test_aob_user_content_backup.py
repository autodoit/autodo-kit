"""AOB 用户级内容备份测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodokit.tools.atomic.aob_runtime.library_tool import 发布用户级内容
from autodokit.tools.atomic.aob_runtime.library_tool import 备份用户级内容
from autodokit.tools.atomic.aob_runtime.library_tool import 默认路径
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


def _write_canonical(paths: 路径配置) -> None:
    canonical_dir = paths.libs_root / "aol"
    canonical_dir.mkdir(parents=True, exist_ok=True)
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
            "extra_assets": [
                {"path": "prompts/tool.prompt.md", "content": "prompt body"},
            ],
        },
    }
    (canonical_dir / "canonical.aol.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_backup_user_content_should_copy_libs_and_targets(tmp_path: Path) -> None:
    """独立备份命令应复制 libs 与目标目录。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    _write_canonical(paths)

    target_root = tmp_path / ".claude"
    发布用户级内容(
        paths,
        target_paths=[str(target_root)],
        home_dir="",
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
    )

    backup_root = tmp_path / "custom_backup"
    stats = 备份用户级内容(
        paths,
        target_paths=[str(target_root)],
        home_dir="",
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        backup_dir=str(backup_root),
        dry_run=False,
    )

    assert stats["status"] == "ok"
    snapshot_dir = Path(stats["snapshot_dir"])
    assert snapshot_dir.exists()
    assert (snapshot_dir / "libs" / "aol" / "canonical.aol.json").exists()
    assert (snapshot_dir / "targets" / "claude__structured_root" / "agents" / "demo.md").exists()
    assert Path(stats["manifest_path"]).exists()


def test_backup_user_content_should_not_write_any_file_in_dry_run(tmp_path: Path) -> None:
    """dry-run 只预览，不落盘。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    _write_canonical(paths)

    target_root = tmp_path / ".claude"
    stats = 备份用户级内容(
        paths,
        target_paths=[str(target_root)],
        home_dir="",
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        backup_dir="",
        dry_run=True,
    )

    assert stats["status"] == "ok"
    assert not Path(stats["snapshot_dir"]).exists()


def test_backup_user_content_should_default_to_autodo_lib_datastore(tmp_path: Path) -> None:
    """默认备份根目录应指向兄弟仓库 autodo-lib/datastore。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)

    stats = 备份用户级内容(
        paths,
        target_paths=[],
        home_dir="",
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        backup_dir="",
        dry_run=True,
    )

    assert Path(stats["backup_root"]) == (tmp_path / "autodo-lib" / "datastore")


def test_default_paths_should_resolve_sibling_autodo_lib_when_repo_root_points_to_autodo_kit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式传入 autodo-kit 时，也应回到兄弟仓库 autodo-lib 读取 libs。"""

    kit_root = tmp_path / "autodo-kit"
    lib_root = tmp_path / "autodo-lib"
    (kit_root / "autodokit").mkdir(parents=True, exist_ok=True)
    (lib_root / "libs").mkdir(parents=True, exist_ok=True)
    (lib_root / "database").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AOB_REPO_ROOT", str(kit_root))

    paths = 默认路径()

    assert paths.repo_root == lib_root.resolve()
    assert paths.libs_root == (lib_root / "libs").resolve()
    assert paths.db_root == (lib_root / "database").resolve()


def test_update_user_content_should_backup_before_sync_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update 默认应先备份再同步。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    _write_canonical(paths)

    home_dir = tmp_path / "home"
    monkeypatch.setenv("APPDATA", str(home_dir / "AppData" / "Roaming"))
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
        dry_run=False,
        sync_items_after=False,
    )

    assert stats["backup"]["enabled"] is True
    snapshot_dir = Path(str(stats["backup"]["snapshot_dir"]))
    assert snapshot_dir.exists()
    assert (snapshot_dir / "libs" / "aol" / "canonical.aol.json").exists()
    assert (target_root / "agents" / "demo.agent.md").exists()
