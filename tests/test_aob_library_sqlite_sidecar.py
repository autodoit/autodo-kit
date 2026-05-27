"""AOB library SQLite sidecar 测试。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from autodokit.tools.atomic.aob_runtime.library_tool import 同步_registry_sqlite
from autodokit.tools.atomic.aob_runtime.library_tool import 路径配置


def test_registry_sqlite_should_materialize_items_and_profiles(tmp_path: Path) -> None:
    """应把 items 与 workspace profiles 写入 SQLite sidecar。"""

    repo_root = tmp_path / "repo"
    libs_root = repo_root / "libs"
    db_root = repo_root / "database"
    libs_root.mkdir(parents=True, exist_ok=True)
    db_root.mkdir(parents=True, exist_ok=True)

    profile_db = db_root / "workspace_target_profiles.json"
    profile_db.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [
                    {
                        "profile_id": "cursor_claude_win11",
                        "ide_vendor": "cursor",
                        "ide_product": "cursor",
                        "engine_vendor": "claude",
                        "engine_product": "claude_code",
                        "os_family": "win11",
                        "os_version_family": "win11_latest",
                        "workspace_dir_name": ".cursor",
                        "install_scope": "workspace",
                        "runtime_mode": "embedded",
                        "status": "experimental",
                        "default_for_engine": False,
                        "project_config_paths": [],
                        "workspace_config_paths": [".cursor/settings.json"],
                        "instruction_paths": ["CLAUDE.md"],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    paths = 路径配置(
        repo_root=repo_root,
        libs_root=libs_root,
        db_root=db_root,
        items_csv=db_root / "items.csv",
        relation_csv=db_root / "item_scenario_relation.csv",
        manifest_json=db_root / "items_manifest.json",
        profile_db_json=profile_db,
        registry_sqlite=db_root / "items_registry.sqlite3",
    )
    rows = {
        "libs/prompts/demo.prompt.md": {
            "uid": "demo12345678",
            "name": "demo",
            "content_type": "prompts",
            "scenario_tags": ["文档管理", "软件开发"],
            "relative_path": "libs/prompts/demo.prompt.md",
            "item_type": "md",
            "file_count": 0,
        }
    }

    stats = 同步_registry_sqlite(paths, rows, dry_run=False)

    assert stats["items"] == 1
    assert stats["profiles"] == 1
    assert paths.registry_sqlite.exists()

    with sqlite3.connect(str(paths.registry_sqlite)) as conn:
        item_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        tag_count = conn.execute("SELECT COUNT(*) FROM item_tags").fetchone()[0]
        profile_count = conn.execute("SELECT COUNT(*) FROM workspace_profiles").fetchone()[0]
        profile_path_count = conn.execute("SELECT COUNT(*) FROM workspace_profile_paths").fetchone()[0]

    assert item_count == 1
    assert tag_count == 2
    assert profile_count == 1
    assert profile_path_count == 2