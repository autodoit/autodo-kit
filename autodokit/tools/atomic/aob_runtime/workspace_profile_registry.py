"""AOB 办公区目标配置注册表。

用于在现有 AOC/AOB 引擎维模型之上，补充 IDE 与操作系统维度，
避免继续在转换与部署逻辑中硬编码办公区目录名。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


数据库相对路径 = Path("database") / "workspace_target_profiles.json"


默认工作区目标配置数据库: dict[str, Any] = {
    "schema_version": 1,
    "profiles": [
        {
            "profile_id": "opencode_native_linux",
            "ide_vendor": "opencode",
            "ide_product": "opencode",
            "engine_vendor": "opencode",
            "engine_product": "opencode",
            "os_family": "linux",
            "os_version_family": "linux_latest",
            "workspace_dir_name": ".opencode",
            "install_scope": "workspace",
            "runtime_mode": "native",
            "status": "supported",
            "default_for_engine": True,
            "project_config_paths": ["opencode.json"],
            "workspace_config_paths": [".opencode/autodo.engine.config.json"],
            "instruction_paths": [".opencode/rules/*.md"],
        },
        {
            "profile_id": "claude_native_linux",
            "ide_vendor": "claude",
            "ide_product": "claude_code",
            "engine_vendor": "claude",
            "engine_product": "claude_code",
            "os_family": "linux",
            "os_version_family": "linux_latest",
            "workspace_dir_name": ".claude",
            "install_scope": "workspace",
            "runtime_mode": "native",
            "status": "supported",
            "default_for_engine": True,
            "workspace_config_paths": [".claude/settings.json", ".claude/autodo.engine.config.json"],
            "instruction_paths": ["CLAUDE.md", ".claude/rules/*.md"],
        },
        {
            "profile_id": "vscode_copilot_linux",
            "ide_vendor": "vscode",
            "ide_product": "vscode",
            "engine_vendor": "copilot",
            "engine_product": "copilot_chat",
            "os_family": "linux",
            "os_version_family": "linux_latest",
            "workspace_dir_name": ".github",
            "install_scope": "workspace",
            "runtime_mode": "extension",
            "status": "supported",
            "default_for_engine": True,
            "workspace_config_paths": [".github/autodo.engine.config.json"],
            "instruction_paths": [".github/copilot-instructions.md", ".github/rules/*.md"],
        },
        {
            "profile_id": "gemini_native_linux",
            "ide_vendor": "gemini",
            "ide_product": "gemini_cli",
            "engine_vendor": "gemini",
            "engine_product": "gemini",
            "os_family": "linux",
            "os_version_family": "linux_latest",
            "workspace_dir_name": ".gemini",
            "install_scope": "workspace",
            "runtime_mode": "native",
            "status": "supported",
            "default_for_engine": True,
            "workspace_config_paths": [".gemini/settings.json", ".gemini/autodo.engine.config.json"],
            "instruction_paths": ["GEMINI.md", ".gemini/rules/*.md"],
        },
        {
            "profile_id": "codex_native_linux",
            "ide_vendor": "codex",
            "ide_product": "codex_cli",
            "engine_vendor": "codex",
            "engine_product": "codex",
            "os_family": "linux",
            "os_version_family": "linux_latest",
            "workspace_dir_name": ".codex",
            "install_scope": "workspace",
            "runtime_mode": "native",
            "status": "supported",
            "default_for_engine": True,
            "workspace_config_paths": [".codex/config.json", ".codex/autodo.engine.config.json"],
            "instruction_paths": ["AGENTS.md", ".codex/rules/*.md"],
        },
    ],
}


def 解析_aob仓库根目录(传入路径: str = "") -> Path:
    """解析 AOB 仓库根目录。"""

    if str(传入路径).strip():
        return Path(str(传入路径).strip()).expanduser().resolve()

    env_root = str(os.environ.get("AOB_REPO_ROOT", "")).strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    kit_root = Path(__file__).resolve().parents[4]
    sibling_aob = kit_root.parent / "autodo-lib"
    if sibling_aob.exists():
        return sibling_aob.resolve()
    return kit_root.resolve()


def 当前操作系统族() -> str:
    """返回当前运行宿主对应的标准 OS 族。"""

    if sys.platform.startswith("win"):
        return "win11"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def 规范化操作系统族(raw: str) -> str:
    """规范化输入的 OS 标识。"""

    text = str(raw or "").strip().lower()
    mapping = {
        "windows": "win11",
        "win": "win11",
        "win11": "win11",
        "mac": "macos",
        "macos": "macos",
        "darwin": "macos",
        "linux": "linux",
        "ubuntu": "linux",
    }
    return mapping.get(text, text)


def 读取工作区目标配置数据库(*, repo_root: Path) -> dict[str, Any]:
    """读取工作区目标配置数据库。"""

    db_path = repo_root / 数据库相对路径
    if not db_path.exists():
        return json.loads(json.dumps(默认工作区目标配置数据库, ensure_ascii=False))

    payload = json.loads(db_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"工作区目标配置数据库格式错误：{db_path}")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError(f"工作区目标配置数据库缺少 profiles：{db_path}")
    return payload


def 解析工作区目标配置(
    *,
    engine_vendor: str,
    ide_vendor: str = "",
    os_family: str = "",
    repo_root: str = "",
) -> dict[str, Any]:
    """根据引擎、IDE 与 OS 解析目标 profile。"""

    normalized_engine = str(engine_vendor or "").strip().lower()
    normalized_ide = str(ide_vendor or "").strip().lower()
    normalized_os = 规范化操作系统族(os_family) or 当前操作系统族()
    root = 解析_aob仓库根目录(repo_root)
    payload = 读取工作区目标配置数据库(repo_root=root)

    candidates: list[tuple[int, dict[str, Any]]] = []
    for profile in list(payload.get("profiles") or []):
        if not isinstance(profile, dict):
            continue
        if str(profile.get("engine_vendor") or "").strip().lower() != normalized_engine:
            continue

        profile_ide = str(profile.get("ide_vendor") or "").strip().lower()
        profile_os = 规范化操作系统族(str(profile.get("os_family") or ""))
        score = 0

        if normalized_ide:
            if profile_ide != normalized_ide:
                continue
            score += 10
        elif bool(profile.get("default_for_engine", False)):
            score += 5

        if profile_os == normalized_os:
            score += 4
        elif profile_os in {"", "any"}:
            score += 1
        else:
            continue

        if bool(profile.get("default_for_engine", False)):
            score += 1
        candidates.append((score, profile))

    if not candidates:
        raise ValueError(
            f"未找到匹配的工作区 profile：engine={normalized_engine}, ide={normalized_ide or '<default>'}, os={normalized_os}"
        )

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = dict(candidates[0][1])
    selected.setdefault("resolved_engine_vendor", normalized_engine)
    selected.setdefault("resolved_ide_vendor", normalized_ide or str(selected.get("ide_vendor") or "").strip().lower())
    selected.setdefault("resolved_os_family", normalized_os)
    return selected