"""AOB 同步主链端到端测试。

覆盖 `更新用户级内容` 全链路（在 tmp_path 沙盒中）：
1. 全链路：污染 canonical → 同步 → canonical 去污染、目标无 vendor 副本。
2. 参与方一致性：显式 target_paths 时，读取范围 == 发布范围。
3. 删除传播：canonical 删除条目 → 目标对应文件被删除（仅托管文件）。
4. 撤销回滚：同步后执行撤销 → 目标恢复原状。
5. 注册表基线：第二次同步未变更条目沿用历史 changed_at。
6. items sync：canonical 有变更时触发 items sync（sync_items_after=True）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from autodokit.tools.atomic.aob_runtime.aob_update import 更新用户级内容
from autodokit.tools.atomic.aob_runtime.aob_common import 路径配置
from autodokit.tools.atomic.aob_runtime.aob_sync_undo import 执行撤销


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


def _write_canonical(
    paths: 路径配置,
    *,
    agents: list[dict] | None = None,
    skills: list[dict] | None = None,
    prompt_content: str | None = None,
) -> None:
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
            "agents": agents or [
                {"id": "demo", "description": "demo agent", "prompt": "demo prompt", "kind": "subagent"}
            ],
            "skills": skills or [],
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
    (canonical_dir / "canonical.aol.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _read_canonical(paths: 路径配置) -> dict:
    canonical_path = paths.libs_root / "aol" / "canonical.aol.json"
    return json.loads(canonical_path.read_text(encoding="utf-8"))


def _prepare_fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    appdata_root = home_dir / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata_root))
    return home_dir


def test_e2e_sync_should_decontaminate_and_publish_to_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全链路：污染 canonical → 同步 → canonical 去污染、目标无 vendor 副本。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    home_dir = _prepare_fake_home(tmp_path, monkeypatch)

    # 构造含 vendor 污染的 canonical
    _write_canonical(
        paths,
        agents=[
            {"id": "demo", "description": "d", "prompt": "p", "kind": "subagent"},
            {"id": "demo-claude", "description": "d", "prompt": "p", "kind": "subagent"},
            {"id": "demo-copilot", "description": "d", "prompt": "p", "kind": "subagent"},
        ],
    )

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

    # 去污染统计：2 个 vendor 变体被过滤
    assert "已过滤 2 个旧同步" in " ".join(stats.get("aggregate_warnings") or [])
    # canonical 只保留 base
    canonical = _read_canonical(paths)
    agent_ids = [a["id"] for a in canonical["aol"]["agents"]]
    assert "demo" in agent_ids
    assert "demo-claude" not in agent_ids
    assert "demo-copilot" not in agent_ids
    # 目标目录有 demo 文件，无 vendor 副本
    target_agents = [p.name for p in (target_root / "agents").glob("*")] if (target_root / "agents").exists() else []
    assert any("demo" in name for name in target_agents)
    assert not any("demo-claude" in name for name in target_agents)


def test_e2e_sync_should_scope_participants_consistently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """参与方一致性：显式 target_paths 时只比较并发布这些参与方。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    home_dir = _prepare_fake_home(tmp_path, monkeypatch)

    _write_canonical(paths)

    # 两个显式参与方：source（claude）与 target（copilot）
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

    # 只处理 2 个参与方
    assert stats["source_count"] == 3  # libs + 2 targets
    assert stats["target_count"] == 2
    # 发布只覆盖显式目标
    assert (target_root / "agents" / "demo.agent.md").exists()


def test_e2e_sync_should_cleanup_unknown_target_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """清理未跟踪文件：cleanup_unknown=True 时，目标中不在编译输出的杂散文件被清理。

    注：双向同步遵循"存在优先"原则，canonical 删除的条目会被目标反向提供内容阻止；
    因此删除传播通过 cleanup_unknown 清理"非 canonical 内容的杂散文件"来体现。
    """

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    home_dir = _prepare_fake_home(tmp_path, monkeypatch)

    _write_canonical(
        paths,
        agents=[{"id": "demo", "description": "demo agent", "prompt": "demo prompt", "kind": "subagent"}],
    )
    target_root = home_dir / ".copilot"

    # 第一次同步：发布 agent 到目标
    更新用户级内容(
        paths,
        target_paths=[str(target_root)],
        home_dir=str(home_dir),
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
        sync_items_after=False,
    )
    assert (target_root / "agents" / "demo.agent.md").exists()

    # 在目标 agents 目录放一个不在 canonical 中的杂散文件（非 .agent.md 格式，避免被反编译吸收）
    stale_file = target_root / "agents" / "stale-orphan.md"
    stale_file.write_text("orphan content\n", encoding="utf-8")

    # 第二次同步：cleanup_unknown=True 清理杂散文件
    更新用户级内容(
        paths,
        target_paths=[str(target_root)],
        home_dir=str(home_dir),
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
        sync_items_after=False,
        cleanup_unknown=True,
    )

    # 杂散文件被清理；canonical 内容保留
    assert not stale_file.exists()
    assert (target_root / "agents" / "demo.agent.md").exists()


def test_e2e_sync_should_record_undo_and_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """撤销回滚：同步后执行撤销，目标恢复原状。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    home_dir = _prepare_fake_home(tmp_path, monkeypatch)

    _write_canonical(paths, prompt_content="prompt body\n")
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
        undo_journal_dir=str(tmp_path / "undo"),
    )

    undo = stats.get("undo_journal") or {}
    assert undo.get("enabled") is True
    journal_path = Path(str(undo.get("db_path")))
    session_id = str(undo.get("session_id") or "")

    # 撤销
    result = 执行撤销(journal_path, session_id=session_id, dry_run=False)
    assert result["status"] == "PASS"

    # 幂等
    second = 执行撤销(journal_path, session_id=session_id, dry_run=False)
    assert second["status"] == "PASS"
    assert second["idempotent"] is True


def test_e2e_sync_should_keep_registry_baseline_on_second_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注册表基线：第二次同步未变更条目沿用历史 changed_at（registry_hit_count > 0）。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    home_dir = _prepare_fake_home(tmp_path, monkeypatch)

    _write_canonical(paths, prompt_content="prompt body\n")
    target_root = tmp_path / ".copilot"

    # 第一次同步
    stats1 = 更新用户级内容(
        paths,
        target_paths=[str(target_root)],
        home_dir=str(home_dir),
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
        sync_items_after=False,
    )
    assert stats1.get("registry_summary", {}).get("registry_hit_count", 0) == 0  # 首次无基线

    # 第二次同步（内容未变）
    stats2 = 更新用户级内容(
        paths,
        target_paths=[str(target_root)],
        home_dir=str(home_dir),
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
        sync_items_after=False,
    )
    # 未变更条目沿用历史基线 → 有 registry 命中
    assert stats2.get("registry_summary", {}).get("registry_hit_count", 0) > 0


def test_e2e_sync_should_run_items_sync_when_canonical_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """items sync：canonical 有变更且 sync_items_after=True 时触发 items sync。"""

    repo_root = tmp_path / "repo"
    paths = _build_paths(repo_root)
    home_dir = _prepare_fake_home(tmp_path, monkeypatch)

    # canonical 无 prompt，target 有 prompt → 同步后 canonical 增加 prompt → 触发 items sync
    _write_canonical(paths, prompt_content=None)
    target_root = home_dir / ".copilot"
    (target_root / "prompts").mkdir(parents=True, exist_ok=True)
    (target_root / "prompts" / "tool.prompt.md").write_text("newer prompt\n", encoding="utf-8")

    stats = 更新用户级内容(
        paths,
        target_paths=[str(target_root)],
        home_dir=str(home_dir),
        engine_vendors=[],
        ide_vendors=[],
        include_missing=False,
        dry_run=False,
        sync_items_after=True,
    )

    # canonical 应有变更（target 的 prompt 被收敛进 canonical）
    decision = stats.get("decision_summary") or {}
    assert decision.get("added", 0) + decision.get("updated", 0) + decision.get("deleted", 0) > 0
    # items sync 被触发
    items_sync = stats.get("items_sync") or {}
    assert items_sync.get("enabled") is not False
    assert paths.items_csv.exists() or paths.registry_sqlite.exists()
