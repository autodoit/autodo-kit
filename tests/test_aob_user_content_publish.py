"""AOB 用户级内容发布测试。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from autodokit.tools.atomic.aob_runtime.library_tool import 发布用户级内容
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


def _write_canonical(paths: 路径配置, *, extra_assets: list[dict] | None = None) -> None:
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
            "extra_assets": list(extra_assets or []),
        },
    }
    (canonical_dir / "canonical.aol.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_publish_user_content_should_emit_structured_target_from_canonical_aol(tmp_path: Path) -> None:
    """结构化目标应通过 AOC 编译产物落盘，而不是直接复制 libs。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    _write_canonical(paths)

    target_root = tmp_path / ".claude"
    stats = 发布用户级内容(
        paths,
        target_paths=[str(target_root)],
        home_dir="",
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
    )

    assert stats["aol_intermediate"]["status"] == "ok"
    assert stats["aol_intermediate"]["source"] == "canonical_file"
    assert (target_root / "agents" / "demo.md").exists()
    assert (target_root / "CLAUDE.md").exists()


def test_publish_user_content_should_project_prompt_files_from_compiled_assets(tmp_path: Path) -> None:
    """prompts 根目录只接收 canonical AOL 编译后的 prompt/instructions 文件。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    _write_canonical(
        paths,
        extra_assets=[
            {"path": "prompts/tool.prompt.md", "content": "prompt"},
            {"path": "instructions/common.instructions.md", "content": "instruction"},
            {"path": "settings/internal.json", "content": "{\"x\":1}"},
        ],
    )

    prompt_root = tmp_path / "Code" / "User" / "prompts"
    stats = 发布用户级内容(
        paths,
        target_paths=[str(prompt_root)],
        home_dir="",
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
    )

    assert stats["target_count"] == 1
    assert (prompt_root / "tool.prompt.md").exists()
    assert (prompt_root / "common.instructions.md").exists()
    assert not (prompt_root / "internal.json").exists()


def test_publish_user_content_should_filter_auto_discovered_targets_by_engine(tmp_path: Path) -> None:
    """自动发现目标时，应支持按 engine_vendor 过滤。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    _write_canonical(paths)

    home_dir = tmp_path / "home"
    (home_dir / ".claude").mkdir(parents=True, exist_ok=True)
    (home_dir / ".copilot").mkdir(parents=True, exist_ok=True)

    stats = 发布用户级内容(
        paths,
        target_paths=[],
        home_dir=str(home_dir),
        engine_vendors=["claude"],
        ide_vendors=[],
        include_missing=False,
        dry_run=True,
    )

    assert stats["target_count"] == 1
    assert stats["targets"][0]["target_label"] == "claude"


def test_publish_user_content_should_fail_when_canonical_missing(tmp_path: Path) -> None:
    """未生成 canonical AOL 时，发布应失败并提示先聚合。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    target_root = tmp_path / ".claude"

    with pytest.raises(ValueError):
        发布用户级内容(
            paths,
            target_paths=[str(target_root)],
            home_dir="",
            engine_vendors=[],
            ide_vendors=[],
            include_missing=False,
            dry_run=False,
        )


def test_publish_user_content_simulate_only_should_default_sandbox_to_downloads_timestamp_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """simulate_only 且未指定 sandbox_dir 时，应默认落到 Downloads 时间戳目录。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    _write_canonical(paths)

    home_dir = tmp_path / "home"
    monkeypatch.setenv("USERPROFILE", str(home_dir))

    target_root = home_dir / ".claude"
    target_root.mkdir(parents=True, exist_ok=True)
    (target_root / "keep.txt").write_text("keep\n", encoding="utf-8")

    stats = 发布用户级内容(
        paths,
        target_paths=[str(target_root)],
        home_dir=str(home_dir),
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
        simulate_only=True,
        sandbox_dir="",
    )

    sandbox_root = Path(stats["sandbox"]["sandbox_root"])
    assert sandbox_root.parent == home_dir / "Downloads"
    assert re.fullmatch(r"aob-sync-sandbox-\d{14}(?:-\d+)?", sandbox_root.name)

    assert (target_root / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    assert not (target_root / "agents" / "demo.md").exists()

    sandbox_target = Path(stats["sandbox"]["targets"][0]["sandbox_path"])
    assert (sandbox_target / "agents" / "demo.md").exists()