"""AOB 工作区 profile 注册表测试。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools.atomic.aob_runtime.workspace_profile_registry import 解析工作区目标配置


def test_profile_registry_should_resolve_cursor_claude_win11_from_repo_db() -> None:
    """应能从仓库数据库中解析 Cursor + Claude + Win11 profile。"""

    repo_root = Path(__file__).resolve().parents[2].parent / "autodo-lib"

    profile = 解析工作区目标配置(
        engine_vendor="claude",
        ide_vendor="cursor",
        os_family="win11",
        repo_root=str(repo_root),
    )

    assert profile["profile_id"] == "cursor_claude_win11"
    assert profile["workspace_dir_name"] == ".cursor"
    assert profile["engine_vendor"] == "claude"
    assert profile["ide_vendor"] == "cursor"


def test_profile_registry_should_resolve_default_vscode_copilot_profile() -> None:
    """未显式传 IDE 时，应回退到引擎默认 profile。"""

    repo_root = Path(__file__).resolve().parents[2].parent / "autodo-lib"

    profile = 解析工作区目标配置(
        engine_vendor="copilot",
        os_family="linux",
        repo_root=str(repo_root),
    )

    assert profile["profile_id"] == "vscode_copilot_linux"
    assert profile["workspace_dir_name"] == ".github"
    assert profile["ide_vendor"] == "vscode"