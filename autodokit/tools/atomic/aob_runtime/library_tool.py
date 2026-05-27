#!/usr/bin/env python3
"""本地库管理统一入口。

本脚本仅保留一个文件作为“本地库管理”功能入口，提供以下子命令：
- items：条目清单管理（sync/get/delete/upsert）。
- tags：场景标签与关系表管理。
"""

from __future__ import annotations

import argparse
import csv
import filecmp
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .aoc_tool import (
        AOL定义,
        从libs构建_aol,
        从引擎办公区构建_aol,
        原位归一化libs_aol,
        校验_aol,
        读取_代理列表,
        读取_技能列表,
        读取_规则列表,
        读取_命令列表,
        读取_附加载体列表,
        读取_对象字段,
        读取_引擎原生配置,
        编译_aol到引擎办公区,
    )
except Exception:  # pragma: no cover
    try:
        from aoc import (
            AOL定义,
            从libs构建_aol,
            从引擎办公区构建_aol,
            原位归一化libs_aol,
            校验_aol,
            读取_代理列表,
            读取_技能列表,
            读取_规则列表,
            读取_命令列表,
            读取_附加载体列表,
            读取_对象字段,
            读取_引擎原生配置,
            编译_aol到引擎办公区,
        )
    except Exception:  # pragma: no cover
        AOL定义 = None
        从libs构建_aol = None
        从引擎办公区构建_aol = None
        原位归一化libs_aol = None
        校验_aol = None
        读取_代理列表 = None
        读取_技能列表 = None
        读取_规则列表 = None
        读取_命令列表 = None
        读取_附加载体列表 = None
        读取_对象字段 = None
        读取_引擎原生配置 = None
        编译_aol到引擎办公区 = None


默认场景标签顺序 = ["学术研究", "文档管理", "软件开发"]

默认忽略目录名 = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "node_modules",
}

默认忽略文件名 = {
    ".DS_Store",
    "Thumbs.db",
}

默认忽略文件后缀 = {
    ".pyc",
    ".pyo",
    ".tmp",
    ".swp",
    ".log",
}

默认聚合内容目录名 = {
    "agents",
    "skills",
    "rules",
    "prompts",
    "hooks",
    "settings",
    "instructions",
    "templates",
}

默认用户级聚合根目录 = [
    ".copilot",
    ".claude",
    ".codex",
    ".gemini",
    ".opencode",
    ".cursor",
    ".lingma",
    ".qoder",
    ".qwen",
]

默认提示词目录候选 = [
    ("Code", "User", "prompts"),
    ("Cursor", "User", "prompts"),
    ("Lingma", "User", "prompts"),
]

默认项目级载体目录名 = {
    ".github",
    ".claude",
    ".codex",
    ".cursor",
    ".gemini",
    ".opencode",
    ".qwen",
}

默认项目级载体文件名 = {
    "agents.md",
    "claude.md",
    "copilot-instructions.md",
    "gemini.md",
    "opencode.json",
    "qwen.md",
}

默认项目根线索名 = {
    ".git",
    "package.json",
    "pyproject.toml",
    "readme.md",
}

默认系统级路径片段 = (
    "/etc/",
    "/opt/",
    "/usr/",
    "/var/",
    "/program files/",
    "/program files (x86)/",
    "/programdata/",
    "/windows/",
    "/system32/",
)


def 规范路径(text: str) -> str:
    """把路径文本规范为统一的斜杠分隔形式。

    Args:
        text: 待规范的路径文本。

    Returns:
        str: 规范化后的路径文本。
    """

    return str(text or "").strip().replace("\\", "/")


def 规范标签(tags: list[str]) -> list[str]:
    """规范标签列表并去重。

    Args:
        tags: 原始标签列表。

    Returns:
        list[str]: 去重后的标签列表，保持原始顺序。
    """

    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        label = str(tag or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        normalized.append(label)
    return normalized


def 解析标签单元格(cell_text: str) -> list[str]:
    """把 CSV 的标签单元格解析为标签列表。

    Args:
        cell_text: 标签单元格文本。

    Returns:
        list[str]: 标签列表。
    """

    raw = str(cell_text or "").strip()
    if not raw:
        return []

    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return 规范标签([str(item) for item in parsed if str(item or "").strip()])
        except Exception:  # noqa: BLE001
            pass

    parts = re.split(r"[;,，；\n|]+", raw)
    return 规范标签([part.strip() for part in parts if part.strip()])


def 序列化标签单元格(tags: list[str]) -> str:
    """把标签列表序列化为 CSV 可写入文本。

    Args:
        tags: 标签列表。

    Returns:
        str: 逗号分隔标签文本。
    """

    return ",".join(规范标签([str(item) for item in list(tags or [])]))

默认用户级发布目标 = [
    {"folder_name": ".copilot", "target_label": "copilot", "layout": "structured_root", "engine_vendor": "copilot", "ide_vendor": "copilot", "scope": "user"},
    {"folder_name": ".claude", "target_label": "claude", "layout": "structured_root", "engine_vendor": "claude", "ide_vendor": "claude", "scope": "user"},
    {"folder_name": ".codex", "target_label": "codex", "layout": "structured_root", "engine_vendor": "codex", "ide_vendor": "codex", "scope": "user"},
    {"folder_name": ".gemini", "target_label": "gemini", "layout": "structured_root", "engine_vendor": "gemini", "ide_vendor": "gemini", "scope": "user"},
    {"folder_name": ".opencode", "target_label": "opencode", "layout": "structured_root", "engine_vendor": "opencode", "ide_vendor": "opencode", "scope": "user"},
    {"folder_name": ".cursor", "target_label": "cursor", "layout": "structured_root", "engine_vendor": "claude", "ide_vendor": "cursor", "scope": "user"},
    {"folder_name": ".lingma", "target_label": "lingma", "layout": "structured_root", "engine_vendor": "lingma", "ide_vendor": "lingma", "scope": "user"},
    {"folder_name": ".qoder", "target_label": "qoder", "layout": "structured_root", "engine_vendor": "qoder", "ide_vendor": "qoder", "scope": "user"},
    {"folder_name": ".qwen", "target_label": "qwen", "layout": "structured_root", "engine_vendor": "qwen", "ide_vendor": "qwen", "scope": "user"},
]

默认提示词发布目标候选 = [
    {"parts": ("Code", "User", "prompts"), "target_label": "code_user_prompts", "layout": "prompt_root", "engine_vendor": "copilot", "ide_vendor": "vscode", "scope": "user"},
    {"parts": ("Cursor", "User", "prompts"), "target_label": "cursor_user_prompts", "layout": "prompt_root", "engine_vendor": "claude", "ide_vendor": "cursor", "scope": "user"},
    {"parts": ("Lingma", "User", "prompts"), "target_label": "lingma_user_prompts", "layout": "prompt_root", "engine_vendor": "lingma", "ide_vendor": "lingma", "scope": "user"},
]

默认独立指令文件名 = {
    "agents.md",
    "claude.md",
    "copilot-instructions.md",
    "gemini.md",
}

默认独立设置文件名 = {
    ".mcp.json",
    "config.json",
    "copilot-instructions.json",
    "opencode.json",
    "settings.json",
}

默认AOL规范目录名 = "aol"
默认AOL规范文件名 = "canonical.aol.json"

用户内容同步注册表缺失哈希 = "__ABSENT__"
用户内容同步注册表表名 = "user_content_sync_registry"
用户内容同步目标文件表名 = "user_content_sync_target_files"

默认AOC支持引擎 = {"opencode", "claude", "copilot", "gemini", "codex"}

默认引擎供应商映射 = {
    "opencode": "opencode",
    "claude": "claude",
    "copilot": "copilot",
    "gemini": "gemini",
    "codex": "codex",
    "cursor": "claude",
    "vscode": "copilot",
    "lingma": "copilot",
    "qoder": "copilot",
    "qwen": "copilot",
}


def 解析供应商载体契约级别(
    *,
    layout: str,
    engine_vendor: str,
    ide_vendor: str,
    scope: str = "",
) -> tuple[str, str]:
    """返回当前载体的官方契约级别与说明。

    Args:
        layout: 当前载体布局类型。
        engine_vendor: 引擎供应商。
        ide_vendor: IDE 供应商。

    Returns:
        tuple[str, str]: `(contract_level, contract_note)`。
    """

    engine_key = str(engine_vendor or "").strip().lower()
    ide_key = str(ide_vendor or "").strip().lower()
    layout_key = str(layout or "").strip().lower()
    scope_key = str(scope or "").strip().lower()

    if scope_key == "global":
        return (
            "heuristic",
            "global 范围当前按 canonical 真源或显式共享目录接入，尚未声明统一的本地供应商载体契约。",
        )

    if scope_key == "project" and engine_key == "claude" and ide_key == "claude":
        return (
            "official_partial",
            "已核验 Claude Code 的项目级 CLAUDE.md、.claude/settings.json 与 .claude/rules/*.md；当前其余载体仍按现有 AOC 映射处理。",
        )
    if scope_key == "project" and engine_key == "qwen" and ide_key == "qwen":
        return (
            "official_partial",
            "已核验 Qwen Code 的项目级 QWEN.md、.qwen/settings.json 与 .qwen/skills；当前其余载体仍按现有 AOC 映射处理。",
        )
    if scope_key == "project" and engine_key == "copilot" and ide_key in {"copilot", "vscode"}:
        return (
            "official_partial",
            "已核验 GitHub Copilot 的仓库级 .github/copilot-instructions.md、.github/rules/*.md 与 AGENTS.md 支持口径。",
        )
    if scope_key == "project" and ide_key == "cursor":
        return (
            "official_partial",
            "已核验 Cursor 的项目级 .cursor/rules、.md/.mdc frontmatter 与 AGENTS.md 支持口径。",
        )
    if scope_key == "project" and engine_key == "gemini" and ide_key == "gemini":
        return (
            "official_partial",
            "已核验 Gemini CLI 的项目级 GEMINI.md 与 .gemini/rules/*.md 支持口径。",
        )
    if scope_key == "project" and engine_key == "opencode" and ide_key == "opencode":
        return (
            "official_partial",
            "已核验 OpenCode 的项目级 opencode.json 与 .opencode/rules/*.md 支持口径。",
        )

    if layout_key == "structured_root" and engine_key == "claude" and ide_key == "claude":
        return (
            "official_partial",
            "已核验 Claude Code 的 CLAUDE.md / .claude/CLAUDE.md / .claude/rules/*.md 与用户级、系统级路径；当前 structured_root 中其余载体仍按现有 AOC 映射处理。",
        )
    if layout_key == "structured_root" and engine_key == "qwen" and ide_key == "qwen":
        return (
            "official_partial",
            "已核验 Qwen Code 的 ~/.qwen、.qwen/settings.json、系统 settings.json、QWEN.md（或 context.fileName）与 .qwen/skills。",
        )
    if layout_key == "structured_root" and engine_key == "copilot" and ide_key in {"copilot", "vscode"}:
        return (
            "heuristic",
            "GitHub Copilot 本轮已核验的是仓库级 .github/copilot-instructions.md、.github/instructions/**/*.instructions.md 以及 AGENTS.md / CLAUDE.md / GEMINI.md 支持矩阵；当前用户级目录布局仍按兼容发现处理。",
        )
    if ide_key == "cursor":
        return (
            "heuristic",
            "Cursor 本轮已核验的是项目级 .cursor/rules、.md/.mdc frontmatter 与 AGENTS.md；当前用户级目录或 prompts 根目录暂无本轮官方路径依据。",
        )
    if layout_key == "prompt_root":
        return (
            "heuristic",
            "当前 prompts 根目录采用兼容发现口径；本轮已核验供应商文档未统一给出该用户级 prompts 根目录的稳定跨平台契约。",
        )
    return (
        "heuristic",
        "当前载体缺少本轮已核验的供应商官方路径或语法契约，仍按兼容发现处理。",
    )


@dataclass(frozen=True)
class 路径配置:
    """路径配置。

    Args:
        repo_root: 仓库根目录。
        libs_root: 内容库根目录。
        db_root: 数据库目录。
        items_csv: 条目清单文件。
        relation_csv: 二维关系表文件。
        manifest_json: 清单文件。
        profile_db_json: 工作区 profile 数据库。
        registry_sqlite: SQLite sidecar 索引文件。
    """

    repo_root: Path
    libs_root: Path
    db_root: Path
    items_csv: Path
    relation_csv: Path
    manifest_json: Path
    profile_db_json: Path
    registry_sqlite: Path


@dataclass(frozen=True)
class 聚合来源:
    """用户级内容聚合来源。

    Args:
        source_path: 来源根目录或文件。
        source_label: 稳定来源标签。
        layout: 来源布局类型。
        engine_vendor: 来源引擎供应商。
        ide_vendor: 来源 IDE 供应商。
        scope: 来源范围。
    """

    source_path: Path
    source_label: str
    layout: str
    engine_vendor: str
    ide_vendor: str
    scope: str


@dataclass(frozen=True)
class 发布目标:
    """用户级内容发布目标。"""

    target_path: Path
    target_label: str
    layout: str
    engine_vendor: str
    ide_vendor: str
    scope: str


def 仓库根目录() -> Path:
    """获取仓库根目录。

    Returns:
        Path: 仓库根目录。
    """

    def 规范AOB仓库根目录(root: Path) -> Path:
        """把传入根目录规范到 AOB 内容库仓库。

        当调用方把 `autodo-kit` 作为运行根目录传入时，AOB 用户级内容相关动作
        实际仍应以兄弟仓库 `autodo-lib` 作为内容库真源。

        Args:
            root: 候选仓库根目录。

        Returns:
            Path: 规范化后的仓库根目录。
        """

        resolved = root.expanduser().resolve()
        sibling_aob = resolved.parent / "autodo-lib"
        if resolved.name.lower() == "autodo-kit" and sibling_aob.exists():
            return sibling_aob.resolve()
        if resolved.name.lower() != "autodo-lib" and sibling_aob.exists() and (sibling_aob / "libs").exists():
            return sibling_aob.resolve()
        return resolved

    env_root = str(os.environ.get("AOB_REPO_ROOT", "")).strip()
    if env_root:
        return 规范AOB仓库根目录(Path(env_root))

    kit_root = Path(__file__).resolve().parents[4]
    sibling_aob = kit_root.parent / "autodo-lib"
    if sibling_aob.exists():
        return sibling_aob.resolve()
    return 规范AOB仓库根目录(kit_root)


def 默认路径() -> 路径配置:
    """构建默认路径配置。

    Returns:
        路径配置: 路径配置对象。
    """

    root = 仓库根目录()
    db_root = root / "database"
    return 路径配置(
        repo_root=root,
        libs_root=root / "libs",
        db_root=db_root,
        items_csv=db_root / "items.csv",
        relation_csv=db_root / "item_scenario_relation.csv",
        manifest_json=db_root / "items_manifest.json",
        profile_db_json=db_root / "workspace_target_profiles.json",
        registry_sqlite=db_root / "items_registry.sqlite3",
    )


def 用户主目录(home_dir: str = "") -> Path:
    """解析用户主目录。"""

    if str(home_dir).strip():
        return Path(str(home_dir).strip()).expanduser().resolve()
    env_home = str(os.environ.get("USERPROFILE") or os.environ.get("HOME") or "").strip()
    if env_home:
        return Path(env_home).expanduser().resolve()
    return Path.home().resolve()


def 默认沙盒目录(home_dir: str = "") -> Path:
    """构建默认沙盒目录。

    Args:
        home_dir: 可选用户主目录。

    Returns:
        Path: 位于 Downloads 下的时间戳沙盒目录。
    """

    home = 用户主目录(home_dir)
    downloads_root = home / "Downloads"
    timestamp = time.strftime("%Y%m%d%H%M%S")
    return downloads_root / f"aob-sync-sandbox-{timestamp}"


def 解析唯一沙盒根目录(*, home_dir: str = "", sandbox_dir: str) -> Path:
    """解析沙盒根目录，并在必要时追加序号避免覆盖。"""

    base_root = Path(str(sandbox_dir).strip()).expanduser() if str(sandbox_dir).strip() else 默认沙盒目录(home_dir)
    sandbox_root = base_root.resolve()
    if sandbox_root.exists():
        index = 2
        candidate = sandbox_root
        while candidate.exists() and any(candidate.iterdir()):
            candidate = Path(f"{str(sandbox_root)}-{index}")
            index += 1
        sandbox_root = candidate
    return sandbox_root


def 构建沙盒路径配置(*, sandbox_root: Path) -> 路径配置:
    """根据沙盒根目录构建路径配置。"""

    sandbox_libs_root = sandbox_root / "libs"
    sandbox_db_root = sandbox_root / "database"
    return 路径配置(
        repo_root=sandbox_root,
        libs_root=sandbox_libs_root,
        db_root=sandbox_db_root,
        items_csv=sandbox_db_root / "items.csv",
        relation_csv=sandbox_db_root / "item_scenario_relation.csv",
        manifest_json=sandbox_db_root / "items_manifest.json",
        profile_db_json=sandbox_db_root / "workspace_target_profiles.json",
        registry_sqlite=sandbox_db_root / "items_registry.sqlite3",
    )


def 复制用户级内容沙盒仓库基线(paths: 路径配置, *, sandbox_paths: 路径配置) -> None:
    """把 canonical 与 sidecar 基线复制到沙盒仓库。"""

    canonical_path = 解析AOL规范文件路径(paths)
    if canonical_path.exists() and canonical_path.is_file():
        复制到备份快照(source=canonical_path, destination=解析AOL规范文件路径(sandbox_paths))

    for source_file, destination_file in [
        (paths.items_csv, sandbox_paths.items_csv),
        (paths.relation_csv, sandbox_paths.relation_csv),
        (paths.manifest_json, sandbox_paths.manifest_json),
        (paths.profile_db_json, sandbox_paths.profile_db_json),
        (paths.registry_sqlite, sandbox_paths.registry_sqlite),
    ]:
        if source_file.exists() and source_file.is_file():
            复制到备份快照(source=source_file, destination=destination_file)


def 规范来源标签(text: str) -> str:
    """把来源标签规范化为稳定目录名片段。"""

    normalized = re.sub(r"[^0-9A-Za-z._-]+", "_", str(text or "").strip()).strip("_").lower()
    return normalized or "source"


def 规范发布过滤(filters: list[str] | None) -> set[str]:
    """规范化发布过滤列表。"""

    return {str(item).strip().lower() for item in list(filters or []) if str(item).strip()}


def 规范范围(scope: str) -> str:
    """把范围文本规范为统一枚举。"""

    raw = str(scope or "").strip().lower()
    if not raw:
        return ""

    aliases = {
        "workspace": "project",
        "repo": "project",
        "repository": "project",
        "machine": "system",
        "device": "system",
        "shared": "global",
        "cloud": "global",
        "account": "global",
    }
    normalized = aliases.get(raw, raw)
    if normalized in {"global", "system", "user", "project"}:
        return normalized
    return ""


def 规范范围过滤(filters: list[str] | None) -> set[str]:
    """规范化范围过滤列表。"""

    normalized = {规范范围(str(item)) for item in list(filters or []) if str(item).strip()}
    return {item for item in normalized if item}


def 默认自动发现范围(*, scopes: list[str] | None, project_dirs: list[str] | None) -> set[str]:
    """返回自动发现阶段实际启用的范围集合。"""

    normalized = 规范范围过滤(scopes)
    if normalized:
        return normalized
    if list(project_dirs or []):
        return {"project"}
    return {"user"}


def APPDATA根目录(home_dir: str = "") -> Path:
    """返回当前用户的 APPDATA 根目录。"""

    home = 用户主目录(home_dir)
    return Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming")).resolve()


def 路径在目录内(path: Path, root: Path) -> bool:
    """判断路径是否位于某个目录内部。"""

    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:  # noqa: BLE001
        return False


def 是否项目根目录(path: Path) -> bool:
    """判断目录是否具备项目根目录特征。"""

    if not path.exists() or not path.is_dir():
        return False

    for name in 默认项目根线索名:
        if (path / name).exists():
            return True
    for name in 默认项目级载体目录名:
        if (path / name).exists():
            return True
    for name in 默认项目级载体文件名:
        if (path / name).exists():
            return True
    return False


def 推断项目根目录候选(path: Path, *, home_dir: str = "") -> Path | None:
    """根据显式路径推断项目根目录。"""

    home = 用户主目录(home_dir)
    lowered_name = path.name.lower()

    if path.is_file() and lowered_name in 默认项目级载体文件名:
        return path.parent

    if not path.is_dir():
        return None

    if lowered_name in 默认项目级载体目录名:
        if path.parent == home:
            return None
        if 是否项目根目录(path.parent):
            return path.parent
        return None

    if 是否项目根目录(path):
        return path
    return None


def 提取路径模式锚点(pattern: str) -> str:
    """把 glob 路径模式截断为可检测的锚点路径。"""

    normalized = 规范路径(pattern).strip("/")
    wildcard_positions = [index for index in [normalized.find("*"), normalized.find("?"), normalized.find("[")] if index >= 0]
    if wildcard_positions:
        normalized = normalized[: min(wildcard_positions)]
    return normalized.rstrip("/")


def 构建范围标签(*, base_label: str, scope: str, path: Path) -> str:
    """构建带范围去重信息的稳定标签。"""

    normalized_base = 规范来源标签(base_label)
    scope_key = 规范范围(scope) or "user"
    if scope_key == "user":
        return normalized_base
    digest = hashlib.sha1(规范路径(str(path)).encode("utf-8")).hexdigest()[:8]
    return 规范来源标签(f"{normalized_base}_{scope_key}_{digest}")


def 推断项目级过滤(path: Path) -> tuple[list[str], list[str]]:
    """根据显式项目级路径推断供应商过滤。"""

    lowered_name = path.name.lower()
    if lowered_name in {".claude", "claude.md"}:
        return ["claude"], ["claude"]
    if lowered_name in {".qwen", "qwen.md"}:
        return ["qwen"], ["qwen"]
    if lowered_name in {".github", "agents.md", "copilot-instructions.md"}:
        return ["copilot"], ["vscode"]
    if lowered_name in {".cursor"}:
        return ["claude"], ["cursor"]
    if lowered_name in {".gemini", "gemini.md"}:
        return ["gemini"], ["gemini"]
    if lowered_name in {".opencode", "opencode.json"}:
        return ["opencode"], ["opencode"]
    if lowered_name in {".codex"}:
        return ["codex"], ["codex"]
    return [], []


def 推断路径范围(path: Path, *, home_dir: str = "", project_dirs: list[str] | None = None) -> str:
    """根据路径位置和上下文推断范围。"""

    for raw_project_dir in list(project_dirs or []):
        project_dir = Path(str(raw_project_dir).strip()).expanduser().resolve()
        if path == project_dir or 路径在目录内(path, project_dir):
            return "project"

    project_root = 推断项目根目录候选(path, home_dir=home_dir)
    if project_root is not None:
        return "project"

    home = 用户主目录(home_dir)
    appdata_root = APPDATA根目录(home_dir)
    if path == home or 路径在目录内(path, home) or path == appdata_root or 路径在目录内(path, appdata_root):
        return "user"

    normalized = f"/{规范路径(str(path)).lower().lstrip('/')}"
    if any(fragment in normalized for fragment in 默认系统级路径片段):
        return "system"
    return "global"


def 读取工作区目标profiles(paths: 路径配置) -> list[dict[str, Any]]:
    """读取 project 范围工作区 profile 真源。"""

    if not paths.profile_db_json.exists() or not paths.profile_db_json.is_file():
        return []

    payload = json.loads(paths.profile_db_json.read_text(encoding="utf-8"))
    profiles_raw = payload.get("profiles") if isinstance(payload, dict) else payload
    if not isinstance(profiles_raw, list):
        return []

    profiles: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]] = set()
    for item in profiles_raw:
        if not isinstance(item, dict):
            continue

        scope = 规范范围(str(item.get("install_scope") or ""))
        if scope != "project":
            continue

        engine_vendor = str(item.get("engine_vendor") or "").strip().lower()
        ide_vendor = str(item.get("ide_vendor") or "").strip().lower()
        workspace_dir_name = str(item.get("workspace_dir_name") or "").strip()
        project_config_paths = [str(value).strip() for value in list(item.get("project_config_paths") or []) if str(value).strip()]
        instruction_paths = [str(value).strip() for value in list(item.get("instruction_paths") or []) if str(value).strip()]
        dedupe_key = (
            engine_vendor,
            ide_vendor,
            workspace_dir_name,
            tuple(project_config_paths),
            tuple(instruction_paths),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        profiles.append(
            {
                "profile_id": str(item.get("profile_id") or "").strip(),
                "engine_vendor": engine_vendor,
                "ide_vendor": ide_vendor,
                "workspace_dir_name": workspace_dir_name,
                "project_config_paths": project_config_paths,
                "instruction_paths": instruction_paths,
                "scope": scope,
            }
        )
    return profiles


def 项目命中profile(project_dir: Path, profile: dict[str, Any]) -> bool:
    """判断项目目录是否命中某个 workspace profile。"""

    markers: list[str] = []
    workspace_dir_name = str(profile.get("workspace_dir_name") or "").strip()
    if workspace_dir_name:
        markers.append(workspace_dir_name)
    markers.extend([提取路径模式锚点(item) for item in list(profile.get("project_config_paths") or [])])
    markers.extend([提取路径模式锚点(item) for item in list(profile.get("instruction_paths") or [])])

    for marker in markers:
        normalized = str(marker or "").strip().strip("/")
        if not normalized:
            continue
        if (project_dir / normalized).exists():
            return True
    return False


def 发现项目级聚合来源(
    paths: 路径配置,
    *,
    project_dirs: list[str],
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
) -> list[聚合来源]:
    """基于 project_dirs 和 profile 真源发现项目级聚合来源。"""

    engine_filters = 规范发布过滤(engine_vendors)
    ide_filters = 规范发布过滤(ide_vendors)
    profiles = 读取工作区目标profiles(paths)
    candidates: list[聚合来源] = []

    for raw_project_dir in list(project_dirs or []):
        if not str(raw_project_dir).strip():
            continue
        project_dir = Path(str(raw_project_dir).strip()).expanduser().resolve()
        if not project_dir.exists() or not project_dir.is_dir():
            continue

        for profile in profiles:
            engine_vendor = str(profile.get("engine_vendor") or "").strip().lower()
            ide_vendor = str(profile.get("ide_vendor") or "").strip().lower()
            workspace_dir_name = str(profile.get("workspace_dir_name") or "").strip()
            if engine_filters and engine_vendor not in engine_filters:
                continue
            if ide_filters and ide_vendor not in ide_filters:
                continue
            if not 项目命中profile(project_dir, profile):
                continue

            carrier_root = project_dir / workspace_dir_name if workspace_dir_name else project_dir

            label = 构建范围标签(
                base_label=f"{project_dir.name}_{ide_vendor}_{engine_vendor}",
                scope="project",
                path=project_dir,
            )
            candidates.append(
                聚合来源(
                    source_path=carrier_root,
                    source_label=label,
                    layout="structured_root",
                    engine_vendor=engine_vendor,
                    ide_vendor=ide_vendor,
                    scope="project",
                )
            )

    deduped: list[聚合来源] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for candidate in candidates:
        dedupe_key = (
            规范路径(str(candidate.source_path)).lower(),
            candidate.engine_vendor.lower(),
            candidate.ide_vendor.lower(),
            candidate.scope.lower(),
        )
        if dedupe_key in seen_keys:
            continue
        if not 是否包含可聚合内容(candidate.source_path, layout=candidate.layout, scope=candidate.scope):
            continue
        seen_keys.add(dedupe_key)
        deduped.append(candidate)
    return deduped


def 发现项目级发布目标(
    paths: 路径配置,
    *,
    project_dirs: list[str],
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    include_missing: bool = False,
) -> list[发布目标]:
    """基于 project_dirs 和 profile 真源发现项目级发布目标。"""

    engine_filters = 规范发布过滤(engine_vendors)
    ide_filters = 规范发布过滤(ide_vendors)
    profiles = 读取工作区目标profiles(paths)
    candidates: list[发布目标] = []

    for raw_project_dir in list(project_dirs or []):
        if not str(raw_project_dir).strip():
            continue
        project_dir = Path(str(raw_project_dir).strip()).expanduser().resolve()
        if not include_missing and (not project_dir.exists() or not project_dir.is_dir()):
            continue

        for profile in profiles:
            engine_vendor = str(profile.get("engine_vendor") or "").strip().lower()
            ide_vendor = str(profile.get("ide_vendor") or "").strip().lower()
            workspace_dir_name = str(profile.get("workspace_dir_name") or "").strip()
            if engine_filters and engine_vendor not in engine_filters:
                continue
            if ide_filters and ide_vendor not in ide_filters:
                continue
            if not include_missing and not 项目命中profile(project_dir, profile):
                continue

            carrier_root = project_dir / workspace_dir_name if workspace_dir_name else project_dir

            label = 构建范围标签(
                base_label=f"{project_dir.name}_{ide_vendor}_{engine_vendor}",
                scope="project",
                path=project_dir,
            )
            candidates.append(
                发布目标(
                    target_path=carrier_root,
                    target_label=label,
                    layout="structured_root",
                    engine_vendor=engine_vendor,
                    ide_vendor=ide_vendor,
                    scope="project",
                )
            )

    deduped: list[发布目标] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for candidate in candidates:
        dedupe_key = (
            规范路径(str(candidate.target_path)).lower(),
            candidate.engine_vendor.lower(),
            candidate.ide_vendor.lower(),
            candidate.scope.lower(),
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        deduped.append(candidate)
    return deduped


def 解析AOL规范文件路径(paths: 路径配置) -> Path:
    """返回 canonical AOL 文件路径。"""

    return paths.libs_root / 默认AOL规范目录名 / 默认AOL规范文件名


def 归一化引擎供应商(*, engine_vendor: str, ide_vendor: str = "") -> str:
    """把来源或目标的 engine/ide 供应商归一化到 AOC 支持引擎。"""

    engine_key = str(engine_vendor or "").strip().lower()
    ide_key = str(ide_vendor or "").strip().lower()
    if engine_key in 默认AOC支持引擎:
        return engine_key
    mapped = 默认引擎供应商映射.get(engine_key)
    if mapped:
        return mapped
    mapped = 默认引擎供应商映射.get(ide_key)
    if mapped:
        return mapped
    return "copilot"


def 推断显式聚合来源(
    source_path: Path,
    *,
    home_dir: str = "",
    project_dirs: list[str] | None = None,
) -> 聚合来源:
    """根据显式来源路径推断聚合元数据。"""

    explicit_scope = 推断路径范围(source_path, home_dir=home_dir, project_dirs=project_dirs)

    if source_path.is_file():
        return 聚合来源(
            source_path=source_path,
            source_label=构建范围标签(
                base_label=source_path.stem or source_path.name,
                scope=explicit_scope,
                path=source_path,
            ),
            layout="single_file",
            engine_vendor="copilot",
            ide_vendor="copilot",
            scope=explicit_scope,
        )

    lowered_name = source_path.name.lower()
    if lowered_name == "prompts":
        vendor_name = source_path.parent.parent.name.lower() if len(source_path.parents) >= 2 else "prompts"
        if vendor_name == "code":
            return 聚合来源(
                source_path=source_path,
                source_label="code_user_prompts",
                layout="prompt_root",
                engine_vendor="copilot",
                ide_vendor="vscode",
                scope="user",
            )
        if vendor_name == "cursor":
            return 聚合来源(
                source_path=source_path,
                source_label="cursor_user_prompts",
                layout="prompt_root",
                engine_vendor="claude",
                ide_vendor="cursor",
                scope="user",
            )
        if vendor_name == "lingma":
            return 聚合来源(
                source_path=source_path,
                source_label="lingma_user_prompts",
                layout="prompt_root",
                engine_vendor="lingma",
                ide_vendor="lingma",
                scope="user",
            )
        label = 构建范围标签(
            base_label=f"{vendor_name}_user_prompts",
            scope=explicit_scope,
            path=source_path,
        )
        return 聚合来源(
            source_path=source_path,
            source_label=label,
            layout="prompt_root",
            engine_vendor=vendor_name,
            ide_vendor=vendor_name,
            scope=explicit_scope,
        )

    vendor = lowered_name.lstrip(".")
    if vendor == "cursor":
        project_root = 推断项目根目录候选(source_path, home_dir=home_dir)
        effective_path = project_root if project_root is not None else source_path
        scope = "project" if project_root is not None else "user"
        return 聚合来源(
            source_path=effective_path,
            source_label=构建范围标签(base_label=vendor, scope=scope, path=effective_path),
            layout="structured_root",
            engine_vendor="claude",
            ide_vendor="cursor",
            scope=scope,
        )
    project_root = 推断项目根目录候选(source_path, home_dir=home_dir)
    effective_path = project_root if project_root is not None else source_path
    scope = "project" if project_root is not None else (explicit_scope or "user")
    return 聚合来源(
        source_path=effective_path,
        source_label=构建范围标签(base_label=vendor or "source", scope=scope, path=effective_path),
        layout="structured_root",
        engine_vendor=vendor or "copilot",
        ide_vendor=vendor or "copilot",
        scope=scope,
    )


def 推断显式发布目标(
    target_path: Path,
    *,
    home_dir: str = "",
    project_dirs: list[str] | None = None,
) -> 发布目标:
    """根据显式目标路径推断发布元数据。"""

    explicit_scope = 推断路径范围(target_path, home_dir=home_dir, project_dirs=project_dirs)

    lowered_name = target_path.name.lower()
    if lowered_name == "prompts":
        vendor_name = target_path.parent.parent.name.lower() if len(target_path.parents) >= 2 else "prompts"
        if vendor_name == "code":
            return 发布目标(target_path=target_path, target_label="code_user_prompts", layout="prompt_root", engine_vendor="copilot", ide_vendor="vscode", scope="user")
        if vendor_name == "cursor":
            return 发布目标(target_path=target_path, target_label="cursor_user_prompts", layout="prompt_root", engine_vendor="claude", ide_vendor="cursor", scope="user")
        if vendor_name == "lingma":
            return 发布目标(target_path=target_path, target_label="lingma_user_prompts", layout="prompt_root", engine_vendor="lingma", ide_vendor="lingma", scope="user")
        label = 构建范围标签(base_label=f"{vendor_name}_user_prompts", scope=explicit_scope, path=target_path)
        return 发布目标(target_path=target_path, target_label=label, layout="prompt_root", engine_vendor=vendor_name, ide_vendor=vendor_name, scope=explicit_scope)

    label = 规范来源标签(lowered_name.lstrip("."))
    if label == "cursor":
        project_root = 推断项目根目录候选(target_path, home_dir=home_dir)
        effective_path = project_root if project_root is not None else target_path
        scope = "project" if project_root is not None else "user"
        return 发布目标(target_path=effective_path, target_label=构建范围标签(base_label=label, scope=scope, path=effective_path), layout="structured_root", engine_vendor="claude", ide_vendor="cursor", scope=scope)
    project_root = 推断项目根目录候选(target_path, home_dir=home_dir)
    effective_path = project_root if project_root is not None else target_path
    scope = "project" if project_root is not None else (explicit_scope or "user")
    return 发布目标(target_path=effective_path, target_label=构建范围标签(base_label=label, scope=scope, path=effective_path), layout="structured_root", engine_vendor=label, ide_vendor=label, scope=scope)


def 推断单文件内容类型(file_path: Path) -> str | None:
    """按文件名推断聚合目标内容类型。"""

    name = file_path.name.lower()
    if name.endswith(".agent.md"):
        return "agents"
    if name.endswith(".instructions.md"):
        return "instructions"
    if name.endswith(".prompt.md"):
        return "prompts"
    if name.endswith(".rule.md"):
        return "rules"
    if name in 默认独立指令文件名:
        return "instructions"
    if name in 默认独立设置文件名:
        return "settings"
    if file_path.suffix.lower() in {".json", ".jsonc", ".toml", ".yaml", ".yml"}:
        return "settings"
    if file_path.suffix.lower() == ".md":
        return "prompts"
    return None


def 是否包含可聚合内容(source_path: Path, *, layout: str, scope: str = "") -> bool:
    """判断来源路径是否包含可聚合内容。"""

    if layout == "single_file":
        return source_path.is_file() and 推断单文件内容类型(source_path) is not None
    if not source_path.exists() or not source_path.is_dir():
        return False
    if layout == "prompt_root":
        return any(
            path.is_file() and 推断单文件内容类型(path) is not None
            for path in source_path.rglob("*")
        )

    if 规范范围(scope) == "project" and source_path.name.lower() not in 默认项目级载体目录名:
        for child in source_path.iterdir():
            if child.is_dir() and child.name.lower() in 默认项目级载体目录名:
                return True
            if child.is_file() and child.name.lower() in 默认项目级载体文件名:
                return True
        return False

    for child in source_path.iterdir():
        if child.is_dir() and child.name.lower() in 默认聚合内容目录名:
            return True
        if child.is_file() and 推断单文件内容类型(child) is not None:
            return True
    return False


def 发现用户级聚合来源(*, home_dir: str = "") -> list[聚合来源]:
    """自动发现当前用户的 AI 内容来源目录。"""

    home = 用户主目录(home_dir)
    roaming_root = APPDATA根目录(home_dir)
    candidates: list[聚合来源] = []

    for folder_name in 默认用户级聚合根目录:
        source_path = home / folder_name
        vendor = folder_name.lstrip(".").lower()
        if vendor == "cursor":
            engine_vendor = "claude"
            ide_vendor = "cursor"
        else:
            engine_vendor = vendor
            ide_vendor = vendor
        candidates.append(
            聚合来源(
                source_path=source_path,
                source_label=规范来源标签(folder_name.lstrip(".")),
                layout="structured_root",
                engine_vendor=engine_vendor,
                ide_vendor=ide_vendor,
                scope="user",
            )
        )

    for parts in 默认提示词目录候选:
        source_path = roaming_root.joinpath(*parts)
        vendor = str(parts[0]).strip().lower()
        if vendor == "code":
            engine_vendor = "copilot"
            ide_vendor = "vscode"
        elif vendor == "cursor":
            engine_vendor = "claude"
            ide_vendor = "cursor"
        else:
            engine_vendor = vendor
            ide_vendor = vendor
        candidates.append(
            聚合来源(
                source_path=source_path,
                source_label=规范来源标签("_".join(parts)),
                layout="prompt_root",
                engine_vendor=engine_vendor,
                ide_vendor=ide_vendor,
                scope="user",
            )
        )

    deduped: list[聚合来源] = []
    seen_paths: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.source_path.resolve()
        except FileNotFoundError:
            resolved = candidate.source_path
        key = str(resolved).replace("\\", "/").lower()
        if key in seen_paths:
            continue
        if not 是否包含可聚合内容(candidate.source_path, layout=candidate.layout, scope=candidate.scope):
            continue
        seen_paths.add(key)
        deduped.append(candidate)
    return deduped


def 发现聚合来源(
    paths: 路径配置,
    *,
    home_dir: str = "",
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
) -> list[聚合来源]:
    """按范围自动发现聚合来源。"""

    scope_filters = 默认自动发现范围(scopes=scopes, project_dirs=project_dirs)
    candidates: list[聚合来源] = []
    if "user" in scope_filters:
        candidates.extend(发现用户级聚合来源(home_dir=home_dir))
    if "project" in scope_filters:
        candidates.extend(发现项目级聚合来源(paths, project_dirs=list(project_dirs or [])))

    deduped: list[聚合来源] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for candidate in candidates:
        dedupe_key = (
            规范路径(str(candidate.source_path)).lower(),
            candidate.engine_vendor.lower(),
            candidate.ide_vendor.lower(),
            candidate.scope.lower(),
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        deduped.append(candidate)
    return deduped


def 解析聚合来源(
    source_paths: list[str],
    *,
    paths: 路径配置,
    home_dir: str = "",
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
) -> list[聚合来源]:
    """解析显式来源，或回退到自动发现。"""

    if not source_paths:
        return 发现聚合来源(
            paths,
            home_dir=home_dir,
            scopes=scopes,
            project_dirs=project_dirs,
        )

    resolved_sources: list[聚合来源] = []
    for raw in source_paths:
        source_path = Path(str(raw).strip()).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"聚合来源不存在：{source_path}")

        project_root = 推断项目根目录候选(source_path, home_dir=home_dir)
        if project_root is not None:
            project_engines, project_ides = 推断项目级过滤(source_path)
            project_sources = 发现项目级聚合来源(
                paths,
                project_dirs=[str(project_root)],
                engine_vendors=project_engines,
                ide_vendors=project_ides,
            )
            if project_sources:
                resolved_sources.extend(project_sources)
                continue

        resolved_sources.append(
            推断显式聚合来源(
                source_path,
                home_dir=home_dir,
                project_dirs=project_dirs,
            )
        )
    return resolved_sources


def 发现用户级发布目标(
    *,
    home_dir: str = "",
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    include_missing: bool = False,
) -> list[发布目标]:
    """自动发现当前用户的发布目标目录。"""

    home = 用户主目录(home_dir)
    roaming_root = APPDATA根目录(home_dir)
    engine_filters = 规范发布过滤(engine_vendors)
    ide_filters = 规范发布过滤(ide_vendors)
    candidates: list[发布目标] = []

    for item in 默认用户级发布目标:
        target = 发布目标(
            target_path=home / str(item["folder_name"]),
            target_label=str(item["target_label"]),
            layout=str(item["layout"]),
            engine_vendor=str(item["engine_vendor"]),
            ide_vendor=str(item["ide_vendor"]),
                scope=str(item["scope"]),
        )
        candidates.append(target)

    for item in 默认提示词发布目标候选:
        target = 发布目标(
            target_path=roaming_root.joinpath(*tuple(item["parts"])),
            target_label=str(item["target_label"]),
            layout=str(item["layout"]),
            engine_vendor=str(item["engine_vendor"]),
            ide_vendor=str(item["ide_vendor"]),
                scope=str(item["scope"]),
        )
        candidates.append(target)

    deduped: list[发布目标] = []
    seen_paths: set[str] = set()
    for candidate in candidates:
        if engine_filters and candidate.engine_vendor.lower() not in engine_filters:
            continue
        if ide_filters and candidate.ide_vendor.lower() not in ide_filters:
            continue
        if not include_missing and not candidate.target_path.exists():
            continue
        key = str(candidate.target_path).replace("\\", "/").lower()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        deduped.append(candidate)
    return deduped


def 发现发布目标(
    paths: 路径配置,
    *,
    home_dir: str = "",
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    include_missing: bool = False,
) -> list[发布目标]:
    """按范围自动发现发布目标。"""

    scope_filters = 默认自动发现范围(scopes=scopes, project_dirs=project_dirs)
    candidates: list[发布目标] = []
    if "user" in scope_filters:
        candidates.extend(
            发现用户级发布目标(
                home_dir=home_dir,
                engine_vendors=engine_vendors,
                ide_vendors=ide_vendors,
                include_missing=include_missing,
            )
        )
    if "project" in scope_filters:
        candidates.extend(
            发现项目级发布目标(
                paths,
                project_dirs=list(project_dirs or []),
                engine_vendors=engine_vendors,
                ide_vendors=ide_vendors,
                include_missing=include_missing,
            )
        )

    deduped: list[发布目标] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for candidate in candidates:
        dedupe_key = (
            规范路径(str(candidate.target_path)).lower(),
            candidate.engine_vendor.lower(),
            candidate.ide_vendor.lower(),
            candidate.scope.lower(),
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        deduped.append(candidate)
    return deduped


def 解析发布目标(
    target_paths: list[str],
    *,
    paths: 路径配置,
    home_dir: str = "",
    engine_vendors: list[str] | None = None,
    ide_vendors: list[str] | None = None,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    include_missing: bool = False,
) -> list[发布目标]:
    """解析显式发布目标，或回退到自动发现。"""

    if not target_paths:
        return 发现发布目标(
            paths,
            home_dir=home_dir,
            engine_vendors=engine_vendors,
            ide_vendors=ide_vendors,
            scopes=scopes,
            project_dirs=project_dirs,
            include_missing=include_missing,
        )

    resolved_targets: list[发布目标] = []
    for raw in target_paths:
        target_path = Path(str(raw).strip()).expanduser().resolve()
        project_root = 推断项目根目录候选(target_path, home_dir=home_dir)
        if project_root is not None:
            auto_engine_filters, auto_ide_filters = 推断项目级过滤(target_path)
            merged_engine_filters = list(engine_vendors or []) + auto_engine_filters
            merged_ide_filters = list(ide_vendors or []) + auto_ide_filters
            project_targets = 发现项目级发布目标(
                paths,
                project_dirs=[str(project_root)],
                engine_vendors=merged_engine_filters,
                ide_vendors=merged_ide_filters,
                include_missing=include_missing,
            )
            if project_targets:
                resolved_targets.extend(project_targets)
                continue

        resolved_targets.append(
            推断显式发布目标(
                target_path,
                home_dir=home_dir,
                project_dirs=project_dirs,
            )
        )
    return resolved_targets


def 发布目标转聚合来源(target: 发布目标) -> 聚合来源:
    """把发布目标转换为可反编译的聚合来源。"""

    return 聚合来源(
        source_path=target.target_path,
        source_label=target.target_label,
        layout=target.layout,
        engine_vendor=target.engine_vendor,
        ide_vendor=target.ide_vendor,
        scope=target.scope,
    )


def 构建聚合统计(source: 聚合来源) -> dict[str, Any]:
    """初始化单来源聚合统计。"""

    return {
        "source": str(source.source_path),
        "source_label": source.source_label,
        "layout": source.layout,
        "engine_vendor": source.engine_vendor,
        "ide_vendor": source.ide_vendor,
        "scope": source.scope,
        "added": 0,
        "updated": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "errors": [],
        "touched_paths": [],
    }


def 构建发布统计(target: 发布目标) -> dict[str, Any]:
    """初始化单目标发布统计。"""

    return {
        "target": str(target.target_path),
        "target_label": target.target_label,
        "layout": target.layout,
        "engine_vendor": target.engine_vendor,
        "ide_vendor": target.ide_vendor,
        "scope": target.scope,
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "errors": [],
        "touched_paths": [],
    }


def 合并聚合统计(total: dict[str, Any], part: dict[str, Any]) -> None:
    """把单来源统计合并到总统计。"""

    for key in ["added", "updated", "skipped_same", "skipped_target_newer"]:
        total[key] = int(total.get(key, 0)) + int(part.get(key, 0))
    total.setdefault("sources", []).append(part)
    total.setdefault("errors", []).extend(list(part.get("errors") or []))
    total.setdefault("touched_paths", []).extend(list(part.get("touched_paths") or []))


def 合并发布统计(total: dict[str, Any], part: dict[str, Any]) -> None:
    """把单目标发布统计合并到总统计。"""

    for key in ["added", "updated", "deleted", "skipped_same", "skipped_target_newer"]:
        total[key] = int(total.get(key, 0)) + int(part.get(key, 0))
    total.setdefault("targets", []).append(part)
    total.setdefault("errors", []).extend(list(part.get("errors") or []))
    total.setdefault("touched_paths", []).extend(list(part.get("touched_paths") or []))


def AOL运行时可用() -> bool:
    """判断是否具备 AOL 读写与编译运行时。"""

    required = [
        AOL定义,
        从引擎办公区构建_aol,
        编译_aol到引擎办公区,
        读取_代理列表,
        读取_技能列表,
        读取_规则列表,
        读取_命令列表,
        读取_附加载体列表,
        读取_对象字段,
        读取_引擎原生配置,
    ]
    return all(item is not None for item in required)


def 代理对象转payload(agent: Any) -> dict[str, Any]:
    """把 AOL 代理对象转换为可序列化结构。"""

    return {
        "id": str(agent.agent_id),
        "description": str(agent.description),
        "prompt": str(agent.prompt),
        "kind": str(agent.kind),
        "model": agent.model,
        "color": agent.color,
        "toolsPolicy": {
            "mode": str(agent.tools_policy.mode),
            "tools": dict(agent.tools_policy.tools or {}),
            "bashRules": [dict(item) for item in list(agent.tools_policy.bash_rules or [])],
        },
        "engineOverrides": dict(agent.engine_overrides or {}),
    }


def 技能对象转payload(skill: Any) -> dict[str, Any]:
    """把 AOL 技能对象转换为可序列化结构。"""

    return {
        "name": str(skill.name),
        "description": str(skill.description),
        "body": str(skill.body),
        "metadata": dict(skill.metadata or {}),
    }


def 规则对象转payload(rule: Any) -> dict[str, Any]:
    """把 AOL 规则对象转换为可序列化结构。"""

    return {
        "id": str(rule.rule_id),
        "content": str(rule.content),
    }


def 命令对象转payload(command: Any) -> dict[str, Any]:
    """把 AOL 命令对象转换为可序列化结构。"""

    return {
        "id": str(command.command_id),
        "description": str(command.description),
        "argumentHint": str(command.argument_hint),
        "body": str(command.body),
    }


def 载体对象转payload(asset: Any) -> dict[str, Any]:
    """把 AOL 附加载体对象转换为可序列化结构。"""

    return {
        "path": str(asset.relative_path).replace("\\", "/"),
        "content": str(asset.content),
    }


def AOL对象转payload(aol: Any) -> dict[str, Any]:
    """把 AOL 对象转换为可序列化 payload。"""

    return {
        "version": str(aol.version),
        "title": str(aol.title),
        "instructions": [str(item) for item in list(aol.instructions or [])],
        "agents": [代理对象转payload(agent) for agent in list(aol.agents or [])],
        "skills": [技能对象转payload(skill) for skill in list(aol.skills or [])],
        "rules": [规则对象转payload(rule) for rule in list(aol.rules or [])],
        "commands": [命令对象转payload(command) for command in list(aol.commands or [])],
        "project_instruction": str(aol.project_instruction) if aol.project_instruction else None,
        "claude_md": str(aol.claude_md) if aol.claude_md else None,
        "hooks": [载体对象转payload(asset) for asset in list(aol.hooks or [])],
        "mcp_servers": dict(aol.mcp_servers or {}),
        "settings": dict(aol.settings or {}),
        "policies": dict(aol.policies or {}),
        "engine_native": dict(aol.engine_native or {}),
        "extra_assets": [载体对象转payload(asset) for asset in list(aol.extra_assets or [])],
    }


def payload转AOL对象(payload: dict[str, Any]) -> Any:
    """把 payload 转换为 AOL 对象。"""

    if not AOL运行时可用():
        raise ValueError("aoc runtime 不可用，无法解析 canonical AOL")

    instructions_raw = payload.get("instructions")
    if isinstance(instructions_raw, list):
        instructions = [str(item).strip() for item in instructions_raw if str(item).strip()]
    else:
        instructions = []

    project_instruction = payload.get("project_instruction")
    if project_instruction is None:
        project_instruction = payload.get("projectInstruction")
    project_instruction = str(project_instruction).strip() if isinstance(project_instruction, str) and str(project_instruction).strip() else None

    claude_md = payload.get("claude_md")
    if claude_md is None:
        claude_md = payload.get("claudeMd")
    claude_md = str(claude_md).strip() if isinstance(claude_md, str) and str(claude_md).strip() else None

    settings_payload = payload.get("settings")
    policies_payload = payload.get("policies")
    engine_native_payload = payload.get("engine_native")
    if engine_native_payload is None:
        engine_native_payload = payload.get("engineNative")

    return AOL定义(
        version=str(payload.get("version") or "1"),
        title=str(payload.get("title") or "AOL Library"),
        instructions=instructions,
        agents=读取_代理列表(payload.get("agents")),
        skills=读取_技能列表(payload.get("skills")),
        rules=读取_规则列表(payload.get("rules")),
        commands=读取_命令列表(payload.get("commands")),
        project_instruction=project_instruction,
        claude_md=claude_md,
        hooks=读取_附加载体列表(payload.get("hooks")),
        mcp_servers=读取_对象字段(payload.get("mcp_servers") or payload.get("mcpServers"), field_name="mcp_servers"),
        settings=读取_对象字段(settings_payload, field_name="settings"),
        policies=读取_对象字段(policies_payload, field_name="policies"),
        engine_native=读取_引擎原生配置(engine_native_payload),
        extra_assets=读取_附加载体列表(payload.get("extra_assets") or payload.get("extraAssets")),
    )


def 构建AOL摘要(aol: Any, *, source: str, canonical_path: Path | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    """构建 AOL 中转摘要。"""

    runtime_warnings = list(warnings or [])
    if 校验_aol is not None:
        runtime_warnings.extend(list(校验_aol(aol) or []))
    return {
        "enabled": True,
        "status": "ok",
        "source": source,
        "canonical_path": str(canonical_path) if canonical_path else "",
        "title": str(aol.title),
        "counts": {
            "agents": len(list(aol.agents or [])),
            "skills": len(list(aol.skills or [])),
            "rules": len(list(aol.rules or [])),
            "commands": len(list(aol.commands or [])),
            "hooks": len(list(aol.hooks or [])),
            "extra_assets": len(list(aol.extra_assets or [])),
        },
        "warnings": runtime_warnings,
    }


def 读取canonical_AOL(paths: 路径配置) -> Any:
    """从 libs canonical 文件读取 AOL。"""

    canonical_path = 解析AOL规范文件路径(paths)
    if not canonical_path.exists() or not canonical_path.is_file():
        raise FileNotFoundError(f"未找到 canonical AOL：{canonical_path}")

    payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"canonical AOL 格式错误：{canonical_path}")

    aol_payload = payload.get("aol") if isinstance(payload.get("aol"), dict) else payload
    return payload转AOL对象(aol_payload)


def 写入canonical_AOL(paths: 路径配置, *, aol: Any, dry_run: bool) -> dict[str, Any]:
    """写入 libs canonical AOL 文件。"""

    canonical_path = 解析AOL规范文件路径(paths)
    wrapped_payload = {
        "schema": "aol_canonical_json_v1",
        "aol": AOL对象转payload(aol),
    }
    rendered = json.dumps(wrapped_payload, ensure_ascii=False, indent=2) + "\n"

    status = "added"
    if canonical_path.exists():
        old_text = canonical_path.read_text(encoding="utf-8")
        if old_text == rendered:
            status = "unchanged"
        else:
            status = "updated"

    if not dry_run and status != "unchanged":
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.write_text(rendered, encoding="utf-8")

    return {
        "path": str(canonical_path),
        "status": status if not dry_run else f"dry_run_{status}",
        "written": bool((not dry_run) and status in {"added", "updated"}),
        "dry_run": dry_run,
    }


def 构建libs_aol中转摘要(paths: 路径配置) -> dict[str, Any]:
    """从 libs canonical 文件构建 AOL 中转摘要。"""

    if not AOL运行时可用():
        return {
            "enabled": False,
            "status": "unavailable",
            "reason": "aoc runtime 不可用，无法构建 AOL 中转摘要",
        }

    canonical_path = 解析AOL规范文件路径(paths)
    if not canonical_path.exists():
        return {
            "enabled": True,
            "status": "error",
            "reason": f"未找到 canonical AOL：{canonical_path}",
            "canonical_path": str(canonical_path),
            "warnings": ["请先执行 aggregate-user-content 生成 canonical AOL"],
        }

    try:
        aol = 读取canonical_AOL(paths)
        return 构建AOL摘要(aol, source="canonical_file", canonical_path=canonical_path)
    except Exception as exc:
        return {
            "enabled": True,
            "status": "error",
            "reason": f"读取 canonical AOL 失败：{exc}",
            "canonical_path": str(canonical_path),
            "warnings": ["canonical AOL 损坏或结构不合法"],
        }


def 计算稳定哈希(value: Any) -> str:
    """对任意可 JSON 序列化值计算稳定哈希。"""

    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def AOL扁平化逻辑条目(aol_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """把 AOL payload 扁平化为逻辑条目。"""

    entries: dict[str, dict[str, Any]] = {}

    def _append(section: str, identity: str, value: Any) -> None:
        logical_key = f"{section}::{identity}"
        entries[logical_key] = {
            "logical_key": logical_key,
            "section": section,
            "identity": identity,
            "value": value,
            "value_hash": 计算稳定哈希(value),
        }

    _append("version", "__root", str(aol_payload.get("version") or "1"))
    _append("title", "__root", str(aol_payload.get("title") or "AOL Library"))

    for item in list(aol_payload.get("instructions") or []):
        text = str(item).strip()
        if not text:
            continue
        _append("instructions", 计算稳定哈希(text), text)

    for section, key_name, identity_field in [
        ("agents", "id", "id"),
        ("skills", "name", "name"),
        ("rules", "id", "id"),
        ("commands", "id", "id"),
    ]:
        for raw in list(aol_payload.get(section) or []):
            if not isinstance(raw, dict):
                continue
            identity = str(raw.get(identity_field) or "").strip()
            if not identity:
                continue
            payload = dict(raw)
            payload[key_name] = identity
            _append(section, identity, payload)

    for root_field in ["project_instruction", "claude_md", "settings", "policies"]:
        value = aol_payload.get(root_field)
        if value in (None, "", {}, []):
            continue
        _append(root_field, "__root", value)

    for section in ["hooks", "extra_assets"]:
        for raw in list(aol_payload.get(section) or []):
            if not isinstance(raw, dict):
                continue
            relative_path = 规范路径(str(raw.get("path") or ""))
            if not relative_path:
                continue
            payload = {
                "path": relative_path,
                "content": str(raw.get("content") or ""),
            }
            _append(section, relative_path, payload)

    for server_name, server_payload in sorted(dict(aol_payload.get("mcp_servers") or {}).items()):
        name = str(server_name).strip()
        if not name:
            continue
        _append("mcp_servers", name, server_payload)

    for engine_name, engine_payload in sorted(dict(aol_payload.get("engine_native") or {}).items()):
        name = str(engine_name).strip()
        if not name:
            continue
        _append("engine_native", name, engine_payload)

    return entries


def 逻辑条目转AOL_payload(logical_entries: dict[str, dict[str, Any]], *, title_fallback: str) -> dict[str, Any]:
    """把逻辑条目回组装为 AOL payload。"""

    payload: dict[str, Any] = {
        "version": "1",
        "title": title_fallback,
        "instructions": [],
        "agents": [],
        "skills": [],
        "rules": [],
        "commands": [],
        "project_instruction": None,
        "claude_md": None,
        "hooks": [],
        "mcp_servers": {},
        "settings": {},
        "policies": {},
        "engine_native": {},
        "extra_assets": [],
    }

    instructions_seen: set[str] = set()

    for entry in [item for _, item in sorted(logical_entries.items()) if isinstance(item, dict)]:
        section = str(entry.get("section") or "").strip()
        identity = str(entry.get("identity") or "").strip()
        value = entry.get("value")

        if section == "version":
            payload["version"] = str(value or "1")
            continue
        if section == "title":
            payload["title"] = str(value or title_fallback)
            continue
        if section == "instructions":
            text = str(value or "").strip()
            if text and text not in instructions_seen:
                instructions_seen.add(text)
                payload["instructions"].append(text)
            continue
        if section in {"agents", "skills", "rules", "commands"}:
            if isinstance(value, dict):
                payload[section].append(dict(value))
            continue
        if section in {"project_instruction", "claude_md"}:
            text = str(value).strip() if isinstance(value, str) else ""
            payload[section] = text or None
            continue
        if section in {"hooks", "extra_assets"}:
            if isinstance(value, dict):
                rel = 规范路径(str(value.get("path") or identity))
                if not rel:
                    continue
                payload[section].append(
                    {
                        "path": rel,
                        "content": str(value.get("content") or ""),
                    }
                )
            continue
        if section == "mcp_servers":
            if identity:
                payload["mcp_servers"][identity] = value
            continue
        if section == "settings":
            payload["settings"] = dict(value) if isinstance(value, dict) else {}
            continue
        if section == "policies":
            payload["policies"] = dict(value) if isinstance(value, dict) else {}
            continue
        if section == "engine_native":
            if identity:
                payload["engine_native"][identity] = value

    return payload


def 获取路径最近修改时间(path: Path) -> float:
    """获取路径及其子文件最近修改时间。"""

    if not path.exists():
        return 0.0

    try:
        latest = float(path.stat().st_mtime)
    except OSError:
        return 0.0

    if path.is_file():
        return latest

    for child in path.rglob("*"):
        if not child.is_file():
            continue
        try:
            latest = max(latest, float(child.stat().st_mtime))
        except OSError:
            continue
    return latest


def 确保用户内容同步表(conn: sqlite3.Connection) -> None:
    """确保用户内容同步相关表存在。"""

    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS {用户内容同步注册表表名} (
            logical_key TEXT NOT NULL,
            side_id TEXT NOT NULL,
            exists_flag INTEGER NOT NULL,
            value_hash TEXT NOT NULL,
            changed_at_epoch REAL NOT NULL,
            updated_at_epoch REAL NOT NULL,
            PRIMARY KEY (logical_key, side_id)
        );

        CREATE TABLE IF NOT EXISTS {用户内容同步目标文件表名} (
            target_label TEXT NOT NULL,
            layout TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            updated_at_epoch REAL NOT NULL,
            PRIMARY KEY (target_label, layout, relative_path)
        );
        """
    )


def 读取用户内容同步数据库基线(paths: 路径配置) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str], set[str]]]:
    """读取用户内容同步数据库基线。"""

    registry_rows: dict[tuple[str, str], dict[str, Any]] = {}
    target_files: dict[tuple[str, str], set[str]] = {}
    if not paths.registry_sqlite.exists() or not paths.registry_sqlite.is_file():
        return registry_rows, target_files

    with sqlite3.connect(str(paths.registry_sqlite)) as conn:
        确保用户内容同步表(conn)
        for logical_key, side_id, exists_flag, value_hash, changed_at, updated_at in conn.execute(
            f"SELECT logical_key, side_id, exists_flag, value_hash, changed_at_epoch, updated_at_epoch FROM {用户内容同步注册表表名}"
        ):
            registry_rows[(str(logical_key), str(side_id))] = {
                "exists_flag": int(exists_flag),
                "value_hash": str(value_hash),
                "changed_at_epoch": float(changed_at),
                "updated_at_epoch": float(updated_at),
            }

        for target_label, layout, relative_path in conn.execute(
            f"SELECT target_label, layout, relative_path FROM {用户内容同步目标文件表名}"
        ):
            key = (str(target_label), str(layout))
            target_files.setdefault(key, set()).add(规范路径(str(relative_path)))

    return registry_rows, target_files


def 写入用户内容同步数据库(
    paths: 路径配置,
    *,
    registry_rows: list[tuple[str, str, int, str, float, float]],
    target_files: dict[tuple[str, str], set[str]],
    dry_run: bool,
) -> dict[str, Any]:
    """写入用户内容同步数据库。"""

    if dry_run:
        return {
            "enabled": True,
            "dry_run": True,
            "registry_rows": len(registry_rows),
            "target_records": sum(len(list(paths_set)) for paths_set in target_files.values()),
            "sqlite_path": str(paths.registry_sqlite),
        }

    paths.registry_sqlite.parent.mkdir(parents=True, exist_ok=True)
    now_ts = float(time.time())

    with sqlite3.connect(str(paths.registry_sqlite)) as conn:
        确保用户内容同步表(conn)
        conn.executemany(
            f"""
            INSERT INTO {用户内容同步注册表表名}
            (logical_key, side_id, exists_flag, value_hash, changed_at_epoch, updated_at_epoch)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(logical_key, side_id) DO UPDATE SET
                exists_flag=excluded.exists_flag,
                value_hash=excluded.value_hash,
                changed_at_epoch=excluded.changed_at_epoch,
                updated_at_epoch=excluded.updated_at_epoch
            """,
            registry_rows,
        )

        for (target_label, layout), managed_files in target_files.items():
            conn.execute(
                f"DELETE FROM {用户内容同步目标文件表名} WHERE target_label=? AND layout=?",
                (target_label, layout),
            )
            payload = [
                (target_label, layout, 规范路径(relative_path), now_ts)
                for relative_path in sorted({规范路径(item) for item in managed_files if 规范路径(item)})
            ]
            conn.executemany(
                f"""
                INSERT INTO {用户内容同步目标文件表名}(target_label, layout, relative_path, updated_at_epoch)
                VALUES(?, ?, ?, ?)
                """,
                payload,
            )
        conn.commit()

    return {
        "enabled": True,
        "dry_run": False,
        "registry_rows": len(registry_rows),
        "target_records": sum(len(list(paths_set)) for paths_set in target_files.values()),
        "sqlite_path": str(paths.registry_sqlite),
    }


def 计算一键更新决策(
    *,
    side_entries: dict[str, dict[str, dict[str, Any]]],
    side_observe_times: dict[str, float],
    previous_registry: dict[tuple[str, str], dict[str, Any]],
    side_priority: list[str],
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str, int, str, float, float]], dict[str, Any]]:
    """计算一键更新决策。"""

    ranked = {side_id: index for index, side_id in enumerate(side_priority)}
    decision_now = float(time.time())
    all_keys: set[str] = set()
    for entries in side_entries.values():
        all_keys.update(entries.keys())
    for logical_key, side_id in previous_registry.keys():
        if side_id in ranked:
            all_keys.add(logical_key)

    final_entries: dict[str, dict[str, Any]] = {}
    registry_rows: list[tuple[str, str, int, str, float, float]] = []
    registry_hit_count = 0
    fallback_count = 0

    for logical_key in sorted(all_keys):
        winner_side = ""
        winner_changed_at = -1.0
        winner_exists = False
        key_has_registry = False

        for side_id in side_priority:
            current_entry = side_entries.get(side_id, {}).get(logical_key)
            exists_flag = 1 if current_entry is not None else 0
            value_hash = (
                str(current_entry.get("value_hash") or "")
                if current_entry is not None
                else 用户内容同步注册表缺失哈希
            )
            observe_at = float(side_observe_times.get(side_id, 0.0) or 0.0)

            previous = previous_registry.get((logical_key, side_id))
            if previous is not None:
                key_has_registry = True
            if previous and int(previous.get("exists_flag", 0)) == exists_flag and str(previous.get("value_hash") or "") == value_hash:
                changed_at = float(previous.get("changed_at_epoch", 0.0) or 0.0)
                registry_hit_count += 1
            else:
                if observe_at > 0:
                    changed_at = float(observe_at)
                elif exists_flag == 0 and previous is None:
                    # 首轮同步中“天然缺席”的 side 不应压过真实存在内容。
                    changed_at = 0.0
                else:
                    # 对有历史基线的缺席或无观测新增，回退为当前决策时刻。
                    changed_at = decision_now

            updated_at = max(observe_at, decision_now)
            registry_rows.append((logical_key, side_id, exists_flag, value_hash, changed_at, updated_at))

            if changed_at > winner_changed_at:
                winner_side = side_id
                winner_changed_at = changed_at
                winner_exists = bool(exists_flag)
            elif changed_at == winner_changed_at and winner_side and ranked.get(side_id, 9999) < ranked.get(winner_side, 9999):
                winner_side = side_id
                winner_changed_at = changed_at
                winner_exists = bool(exists_flag)

        if not key_has_registry:
            fallback_count += 1

        if winner_side and winner_exists:
            winner_entry = side_entries.get(winner_side, {}).get(logical_key)
            if winner_entry is not None:
                final_entries[logical_key] = winner_entry

    return final_entries, registry_rows, {
        "registry_hit_count": registry_hit_count,
        "fallback_count": fallback_count,
        "active_side_count": len(side_priority),
        "logical_key_count": len(all_keys),
    }


def 计算canonical变更摘要(*, libs_entries: dict[str, dict[str, Any]], final_entries: dict[str, dict[str, Any]]) -> dict[str, int]:
    """计算 canonical 维度的新增/更新/删除统计。"""

    added = 0
    updated = 0
    deleted = 0

    for logical_key in sorted(set(libs_entries.keys()) | set(final_entries.keys())):
        old_entry = libs_entries.get(logical_key)
        new_entry = final_entries.get(logical_key)
        if old_entry is None and new_entry is not None:
            added += 1
            continue
        if old_entry is not None and new_entry is None:
            deleted += 1
            continue
        if old_entry is not None and new_entry is not None and str(old_entry.get("value_hash")) != str(new_entry.get("value_hash")):
            updated += 1

    return {
        "added": added,
        "updated": updated,
        "deleted": deleted,
    }


def 收集结构化目标托管文件(compile_workspace_root: Path, *, target: 发布目标) -> set[str]:
    """收集结构化目标托管文件集合。"""

    managed_files = {
        规范路径(str(path.relative_to(compile_workspace_root)))
        for path in sorted(compile_workspace_root.rglob("*"))
        if path.is_file()
    }
    for root_name in ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "opencode.json"]:
        source_file = compile_workspace_root.parent / root_name
        if source_file.exists() and source_file.is_file():
            if target.scope == "project":
                managed_files.add(规范路径(f"../{root_name}"))
            else:
                managed_files.add(规范路径(root_name))
    return {item for item in managed_files if item}


def 收集提示词目标托管文件(compile_workspace_root: Path) -> set[str]:
    """收集 prompts 根目录托管文件集合。"""

    managed_files: set[str] = set()
    for content_type in ["prompts", "instructions"]:
        source_root = compile_workspace_root / content_type
        if not source_root.exists() or not source_root.is_dir():
            continue
        for source_file in sorted(path for path in source_root.rglob("*") if path.is_file()):
            if not 是否提示词发布文件(source_file, content_type=content_type):
                continue
            managed_files.add(规范路径(str(source_file.relative_to(source_root))))
    return {item for item in managed_files if item}


def 清理空目录到根(*, start_dir: Path, root_dir: Path) -> None:
    """从 start_dir 向上清理空目录，直到 root_dir。"""

    current = start_dir
    while current != root_dir and current.is_dir():
        try:
            next(current.iterdir())
            break
        except StopIteration:
            current.rmdir()
            current = current.parent
        except OSError:
            break


def 删除目标过期托管文件(*, target: 发布目标, stale_files: set[str], dry_run: bool, stats: dict[str, Any]) -> None:
    """删除目标中过期托管文件。"""

    for relative_path in sorted({规范路径(item) for item in stale_files if 规范路径(item)}):
        target_file = (target.target_path / Path(relative_path)).resolve()
        if not target_file.exists() or not target_file.is_file():
            continue
        stats["deleted"] += 1
        stats["touched_paths"].append(str(target_file))
        if dry_run:
            continue
        target_file.unlink()
        if 路径在目录内(target_file.parent, target.target_path):
            清理空目录到根(start_dir=target_file.parent, root_dir=target.target_path)


def 发布到单个目标并同步删除(
    *,
    aol: Any,
    target: 发布目标,
    dry_run: bool,
    warnings: list[str],
    previous_managed_files: set[str],
) -> tuple[dict[str, Any], set[str]]:
    """发布到单个目标并同步删除过期托管文件。"""

    stats = 构建发布统计(target)
    target_engine = 归一化引擎供应商(engine_vendor=target.engine_vendor, ide_vendor=target.ide_vendor)
    if str(target.engine_vendor or "").strip().lower() not in 默认AOC支持引擎:
        warnings.append(
            f"目标 {target.target_label} 的 engine_vendor={target.engine_vendor} 不在 AOC 支持列表，已映射为 {target_engine}"
        )
    stats["aoc_target_engine"] = target_engine

    temp_dir = tempfile.TemporaryDirectory(prefix=f"aob-update-{target.target_label}-")
    managed_files: set[str] = set()
    try:
        compile_workspace_root = Path(temp_dir.name) / "workspace"
        compile_workspace_root.mkdir(parents=True, exist_ok=True)
        编译_aol到引擎办公区(
            aol=aol,
            target_workspace_dir=compile_workspace_root,
            target_engine=target_engine,
        )

        if target.layout == "prompt_root":
            发布编译结果到提示词目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
            )
            managed_files = 收集提示词目标托管文件(compile_workspace_root)
        else:
            发布编译结果到结构化目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
            )
            managed_files = 收集结构化目标托管文件(compile_workspace_root, target=target)
    finally:
        temp_dir.cleanup()

    stale_files = {item for item in previous_managed_files if item and item not in managed_files}
    stats["stale_managed_file_count"] = len(stale_files)
    删除目标过期托管文件(target=target, stale_files=stale_files, dry_run=dry_run, stats=stats)
    stats["managed_file_count"] = len(managed_files)
    return stats, managed_files


def 文件内容一致(source_file: Path, target_file: Path) -> bool:
    """判断两个文件内容是否一致。"""

    if not source_file.exists() or not target_file.exists() or not source_file.is_file() or not target_file.is_file():
        return False
    return filecmp.cmp(str(source_file), str(target_file), shallow=False)


def 复制聚合文件(*, source_file: Path, target_file: Path, dry_run: bool, stats: dict[str, Any]) -> None:
    """按“较新优先”策略复制单个聚合文件。"""

    if target_file.exists():
        if target_file.is_dir():
            stats["errors"].append(f"目标路径为目录，无法覆盖文件：{target_file}")
            return
        if 文件内容一致(source_file, target_file):
            stats["skipped_same"] += 1
            return
        if source_file.stat().st_mtime <= target_file.stat().st_mtime:
            stats["skipped_target_newer"] += 1
            return
        stats["updated"] += 1
    else:
        stats["added"] += 1

    stats["touched_paths"].append(str(target_file))
    if dry_run:
        return
    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target_file)


def 复制聚合条目(*, source_path: Path, target_path: Path, dry_run: bool, stats: dict[str, Any]) -> None:
    """复制单个聚合条目，支持文件或目录。"""

    if source_path.is_dir():
        for child in sorted(source_path.rglob("*")):
            if not child.is_file():
                continue
            relative = child.relative_to(source_path)
            复制聚合文件(
                source_file=child,
                target_file=target_path / relative,
                dry_run=dry_run,
                stats=stats,
            )
        return

    复制聚合文件(source_file=source_path, target_file=target_path, dry_run=dry_run, stats=stats)


def 是否提示词发布文件(file_path: Path, *, content_type: str) -> bool:
    """判断文件是否适合发布到 prompts 根目录。"""

    if not file_path.is_file():
        return False
    lowered = file_path.name.lower()
    if content_type == "prompts":
        return lowered.endswith(".prompt.md")
    if content_type == "instructions":
        return lowered.endswith(".instructions.md")
    return False


def 复制文件到临时办公区(*, source_file: Path, target_file: Path) -> None:
    """复制文件到临时办公区。"""

    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target_file)


def 准备来源办公区(source: 聚合来源) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    """将来源转换为可供 AOC ingest 的办公区结构。"""

    if source.layout == "structured_root":
        return source.source_path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"aob-aggregate-{source.source_label}-")
    workspace_root = Path(temp_dir.name) / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    if source.layout == "prompt_root":
        for child in sorted(source.source_path.rglob("*")):
            if not child.is_file():
                continue
            content_type = 推断单文件内容类型(child)
            if not content_type:
                continue
            relative = child.relative_to(source.source_path)
            if content_type == "instructions":
                复制文件到临时办公区(source_file=child, target_file=workspace_root / "instructions" / relative)
            elif content_type == "settings":
                复制文件到临时办公区(source_file=child, target_file=workspace_root / "settings" / relative)
            else:
                复制文件到临时办公区(source_file=child, target_file=workspace_root / "prompts" / relative)
        return workspace_root, temp_dir

    content_type = 推断单文件内容类型(source.source_path)
    if not content_type:
        return workspace_root, temp_dir
    if content_type == "instructions":
        复制文件到临时办公区(source_file=source.source_path, target_file=workspace_root / "instructions" / source.source_path.name)
    elif content_type == "settings":
        复制文件到临时办公区(source_file=source.source_path, target_file=workspace_root / "settings" / source.source_path.name)
    else:
        复制文件到临时办公区(source_file=source.source_path, target_file=workspace_root / "prompts" / source.source_path.name)
    return workspace_root, temp_dir


def 来源构建AOL(paths: 路径配置, *, source: 聚合来源) -> tuple[Any | None, dict[str, Any], list[str]]:
    """把单个来源转换为 AOL 对象。"""

    stats = 构建聚合统计(source)
    warnings: list[str] = []
    contract_level, contract_note = 解析供应商载体契约级别(
        layout=source.layout,
        engine_vendor=source.engine_vendor,
        ide_vendor=source.ide_vendor,
        scope=source.scope,
    )
    stats["contract_level"] = contract_level
    stats["contract_note"] = contract_note
    if contract_level == "heuristic":
        warnings.append(
            f"来源 {source.source_label} 使用经验性载体契约（layout={source.layout}, engine={source.engine_vendor}, ide={source.ide_vendor}）：{contract_note}"
        )
    if not AOL运行时可用():
        stats["errors"].append("aoc runtime 不可用，无法聚合来源")
        return None, stats, warnings

    source_engine = 归一化引擎供应商(engine_vendor=source.engine_vendor, ide_vendor=source.ide_vendor)
    if str(source.engine_vendor or "").strip().lower() not in 默认AOC支持引擎:
        warnings.append(
            f"来源 {source.source_label} 的 engine_vendor={source.engine_vendor} 不在 AOC 支持列表，已映射为 {source_engine}"
        )

    workspace_root, temp_dir = 准备来源办公区(source)
    try:
        aol, counts = 从引擎办公区构建_aol(
            source_workspace_dir=workspace_root,
            source_engine=source_engine,
            title=f"{source.source_label} canonical AOL",
        )
    except Exception as exc:  # noqa: BLE001
        stats["errors"].append(f"来源 AOL 转换失败：{exc}")
        return None, stats, warnings
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    stats["aol_source_engine"] = source_engine
    stats["aol_counts"] = {
        "agents": int(counts.get("agents", 0)),
        "skills": int(counts.get("skills", 0)),
        "rules": int(counts.get("rules", 0)),
        "commands": int(counts.get("commands", 0)),
        "assets": int(counts.get("assets", 0)),
        "hooks": int(counts.get("hooks", 0)),
        "configs": int(counts.get("configs", 0)),
    }
    stats["added"] = (
        stats["aol_counts"]["agents"]
        + stats["aol_counts"]["skills"]
        + stats["aol_counts"]["rules"]
        + stats["aol_counts"]["commands"]
        + stats["aol_counts"]["assets"]
    )
    return aol, stats, warnings


def 生成唯一名称(*, base: str, used: set[str]) -> str:
    """生成不冲突名称。"""

    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def 合并来源AOL(paths: 路径配置, *, aol_entries: list[tuple[聚合来源, Any]]) -> tuple[Any, list[str]]:
    """把多个来源 AOL 合并为一个 canonical AOL。"""

    warnings: list[str] = []
    if not aol_entries:
        merged_payload = {
            "version": "1",
            "title": f"{paths.repo_root.name} canonical AOL",
            "instructions": [],
            "agents": [],
            "skills": [],
            "rules": [],
            "commands": [],
            "project_instruction": None,
            "claude_md": None,
            "hooks": [],
            "mcp_servers": {},
            "settings": {},
            "policies": {},
            "engine_native": {},
            "extra_assets": [],
        }
        return payload转AOL对象(merged_payload), warnings

    merged_payload: dict[str, Any] = {
        "version": "1",
        "title": f"{paths.repo_root.name} canonical AOL",
        "instructions": [],
        "agents": [],
        "skills": [],
        "rules": [],
        "commands": [],
        "project_instruction": None,
        "claude_md": None,
        "hooks": [],
        "mcp_servers": {},
        "settings": {},
        "policies": {},
        "engine_native": {},
        "extra_assets": [],
    }

    instructions_seen: set[str] = set()
    project_instruction_parts: list[str] = []
    claude_md_parts: list[str] = []

    agent_signatures: dict[str, str] = {}
    skill_signatures: dict[str, str] = {}
    rule_signatures: dict[str, str] = {}
    command_signatures: dict[str, str] = {}
    hook_contents: dict[str, str] = {}
    extra_contents: dict[str, str] = {}

    used_agents: set[str] = set()
    used_skills: set[str] = set()
    used_rules: set[str] = set()
    used_commands: set[str] = set()

    for source, aol in aol_entries:
        for item in list(aol.instructions or []):
            text = str(item).strip()
            if not text or text in instructions_seen:
                continue
            instructions_seen.add(text)
            merged_payload["instructions"].append(text)

        if aol.project_instruction and str(aol.project_instruction).strip():
            text = str(aol.project_instruction).strip()
            if text not in project_instruction_parts:
                project_instruction_parts.append(text)

        if aol.claude_md and str(aol.claude_md).strip():
            text = str(aol.claude_md).strip()
            if text not in claude_md_parts:
                claude_md_parts.append(text)

        merged_payload["mcp_servers"].update(dict(aol.mcp_servers or {}))
        merged_payload["settings"].update(dict(aol.settings or {}))
        merged_payload["policies"].update(dict(aol.policies or {}))
        merged_payload["engine_native"].update(dict(aol.engine_native or {}))

        for agent in list(aol.agents or []):
            payload = 代理对象转payload(agent)
            base = str(payload["id"]).strip() or "agent"
            signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            existing_sig = agent_signatures.get(base)
            if existing_sig == signature:
                continue
            if existing_sig is None and base not in used_agents:
                final_id = 生成唯一名称(base=base, used=used_agents)
            else:
                final_id = 生成唯一名称(base=f"{base}-{source.source_label}", used=used_agents)
                warnings.append(f"代理 ID 冲突：{base} -> {final_id}")
            payload["id"] = final_id
            agent_signatures[final_id] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            merged_payload["agents"].append(payload)

        for skill in list(aol.skills or []):
            payload = 技能对象转payload(skill)
            base = str(payload["name"]).strip() or "skill"
            signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            existing_sig = skill_signatures.get(base)
            if existing_sig == signature:
                continue
            if existing_sig is None and base not in used_skills:
                final_name = 生成唯一名称(base=base, used=used_skills)
            else:
                final_name = 生成唯一名称(base=f"{base}-{source.source_label}", used=used_skills)
                warnings.append(f"技能名称冲突：{base} -> {final_name}")
            payload["name"] = final_name
            skill_signatures[final_name] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            merged_payload["skills"].append(payload)

        for rule in list(aol.rules or []):
            payload = 规则对象转payload(rule)
            base = str(payload["id"]).strip() or "rule"
            signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            existing_sig = rule_signatures.get(base)
            if existing_sig == signature:
                continue
            if existing_sig is None and base not in used_rules:
                final_id = 生成唯一名称(base=base, used=used_rules)
            else:
                final_id = 生成唯一名称(base=f"{base}-{source.source_label}", used=used_rules)
                warnings.append(f"规则 ID 冲突：{base} -> {final_id}")
            payload["id"] = final_id
            rule_signatures[final_id] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            merged_payload["rules"].append(payload)

        for command in list(aol.commands or []):
            payload = 命令对象转payload(command)
            base = str(payload["id"]).strip() or "command"
            signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            existing_sig = command_signatures.get(base)
            if existing_sig == signature:
                continue
            if existing_sig is None and base not in used_commands:
                final_id = 生成唯一名称(base=base, used=used_commands)
            else:
                final_id = 生成唯一名称(base=f"{base}-{source.source_label}", used=used_commands)
                warnings.append(f"命令 ID 冲突：{base} -> {final_id}")
            payload["id"] = final_id
            command_signatures[final_id] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            merged_payload["commands"].append(payload)

        for asset in list(aol.hooks or []):
            payload = 载体对象转payload(asset)
            rel = str(payload["path"]).strip().replace("\\", "/")
            if not rel:
                continue
            content = str(payload["content"])
            existing = hook_contents.get(rel)
            if existing == content:
                continue
            if existing is not None and existing != content:
                rel = f"sources/{source.source_label}/{rel}"
                warnings.append(f"hooks 载体冲突，已重命名为：{rel}")
            hook_contents[rel] = content
            merged_payload["hooks"].append({"path": rel, "content": content})

        for asset in list(aol.extra_assets or []):
            payload = 载体对象转payload(asset)
            rel = str(payload["path"]).strip().replace("\\", "/")
            if not rel:
                continue
            content = str(payload["content"])
            existing = extra_contents.get(rel)
            if existing == content:
                continue
            if existing is not None and existing != content:
                rel = f"sources/{source.source_label}/{rel}"
                warnings.append(f"extra_assets 载体冲突，已重命名为：{rel}")
            extra_contents[rel] = content
            merged_payload["extra_assets"].append({"path": rel, "content": content})

    if project_instruction_parts:
        merged_payload["project_instruction"] = "\n\n".join(project_instruction_parts)
    if claude_md_parts:
        merged_payload["claude_md"] = "\n\n".join(claude_md_parts)

    merged_aol = payload转AOL对象(merged_payload)
    return merged_aol, warnings


def 发布编译结果到结构化目录(*, compile_workspace_root: Path, target: 发布目标, dry_run: bool, stats: dict[str, Any]) -> None:
    """把 AOC 编译结果发布到结构化目标目录。"""

    for source_file in sorted(path for path in compile_workspace_root.rglob("*") if path.is_file()):
        relative = source_file.relative_to(compile_workspace_root)
        复制聚合文件(
            source_file=source_file,
            target_file=target.target_path / relative,
            dry_run=dry_run,
            stats=stats,
        )

    for root_name in ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "opencode.json"]:
        source_file = compile_workspace_root.parent / root_name
        if not source_file.exists() or not source_file.is_file():
            continue
        if target.scope == "project":
            target_file = target.target_path.parent / root_name
        else:
            target_file = target.target_path / root_name
        复制聚合文件(
            source_file=source_file,
            target_file=target_file,
            dry_run=dry_run,
            stats=stats,
        )


def 发布编译结果到提示词目录(*, compile_workspace_root: Path, target: 发布目标, dry_run: bool, stats: dict[str, Any]) -> None:
    """把 AOC 编译结果中的 prompts/instructions 投影到 prompts 根目录。"""

    for content_type in ["prompts", "instructions"]:
        source_root = compile_workspace_root / content_type
        if not source_root.exists() or not source_root.is_dir():
            continue
        for source_file in sorted(path for path in source_root.rglob("*") if path.is_file()):
            if not 是否提示词发布文件(source_file, content_type=content_type):
                continue
            relative = source_file.relative_to(source_root)
            复制聚合文件(
                source_file=source_file,
                target_file=target.target_path / relative,
                dry_run=dry_run,
                stats=stats,
            )


def 发布到单个目标(*, aol: Any, target: 发布目标, dry_run: bool, warnings: list[str]) -> dict[str, Any]:
    """把 AOL 编译后发布到单个目标目录。"""

    stats = 构建发布统计(target)
    contract_level, contract_note = 解析供应商载体契约级别(
        layout=target.layout,
        engine_vendor=target.engine_vendor,
        ide_vendor=target.ide_vendor,
        scope=target.scope,
    )
    stats["contract_level"] = contract_level
    stats["contract_note"] = contract_note
    if contract_level == "heuristic":
        warnings.append(
            f"目标 {target.target_label} 使用经验性载体契约（layout={target.layout}, engine={target.engine_vendor}, ide={target.ide_vendor}）：{contract_note}"
        )
    target_engine = 归一化引擎供应商(engine_vendor=target.engine_vendor, ide_vendor=target.ide_vendor)
    if str(target.engine_vendor or "").strip().lower() not in 默认AOC支持引擎:
        warnings.append(
            f"目标 {target.target_label} 的 engine_vendor={target.engine_vendor} 不在 AOC 支持列表，已映射为 {target_engine}"
        )
    stats["aoc_target_engine"] = target_engine

    temp_dir = tempfile.TemporaryDirectory(prefix=f"aob-publish-{target.target_label}-")
    try:
        compile_workspace_root = Path(temp_dir.name) / "workspace"
        compile_workspace_root.mkdir(parents=True, exist_ok=True)
        编译_aol到引擎办公区(
            aol=aol,
            target_workspace_dir=compile_workspace_root,
            target_engine=target_engine,
        )

        if target.layout == "prompt_root":
            发布编译结果到提示词目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
            )
        else:
            发布编译结果到结构化目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
            )
    finally:
        temp_dir.cleanup()

    return stats


def 发布用户级内容(
    paths: 路径配置,
    *,
    target_paths: list[str],
    home_dir: str,
    engine_vendors: list[str],
    ide_vendors: list[str],
    include_missing: bool,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    resolved_targets_override: list[发布目标] | None = None,
) -> dict[str, Any]:
    """把集中在 libs 的内容发布到当前设备的用户级 AI 办公区。"""

    if not AOL运行时可用():
        raise ValueError("aoc runtime 不可用，无法执行 publish-user-content")

    if resolved_targets_override is not None:
        targets = list(resolved_targets_override)
    else:
        targets = 解析发布目标(
            target_paths,
            paths=paths,
            home_dir=home_dir,
            engine_vendors=engine_vendors,
            ide_vendors=ide_vendors,
            scopes=scopes,
            project_dirs=project_dirs,
            include_missing=include_missing,
        )

    if simulate_only:
        sandbox_paths, sandbox_targets, sandbox_summary = 准备用户级内容同步沙盒(
            paths,
            targets=targets,
            home_dir=home_dir,
            sandbox_dir=sandbox_dir,
        )
        sandbox_result = 发布用户级内容(
            sandbox_paths,
            target_paths=[],
            home_dir="",
            engine_vendors=[],
            ide_vendors=[],
            include_missing=True,
            dry_run=dry_run,
            simulate_only=False,
            sandbox_dir="",
            resolved_targets_override=sandbox_targets,
        )
        sandbox_result["sandbox"] = sandbox_summary
        sandbox_result["simulate_only"] = True
        sandbox_result["source_repo_root"] = str(paths.repo_root)
        return sandbox_result

    aol_intermediate = 构建libs_aol中转摘要(paths)
    if aol_intermediate.get("enabled") and aol_intermediate.get("status") != "ok":
        raise ValueError(f"AOL 中转构建失败：{aol_intermediate}")

    aol = 读取canonical_AOL(paths)

    summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "target_count": len(targets),
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "targets": [],
        "errors": [],
        "touched_paths": [],
        "aol_intermediate": aol_intermediate,
        "publish_warnings": [],
        "sandbox": {"enabled": False},
        "simulate_only": False,
    }

    for target in targets:
        part = 发布到单个目标(
            aol=aol,
            target=target,
            dry_run=dry_run,
            warnings=summary["publish_warnings"],
        )
        合并发布统计(summary, part)

    return summary


def 默认用户内容备份根目录(paths: 路径配置) -> Path:
    """获取用户内容备份根目录。"""

    sibling_root = paths.repo_root.parent / "autodo-lib"
    return (sibling_root / "datastore").resolve()


def 构造备份快照目录(*, backup_root: Path, prefix: str = "aob-user-content-backup") -> Path:
    """构造不冲突的备份快照目录。"""

    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    base = backup_root / f"{prefix}-{stamp}"
    candidate = base
    index = 2
    while candidate.exists():
        candidate = backup_root / f"{prefix}-{stamp}-{index}"
        index += 1
    return candidate


def 统计文件数量(path: Path) -> int:
    """统计路径内文件数量。"""

    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def 复制到备份快照(*, source: Path, destination: Path) -> None:
    """复制来源到备份快照。"""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, destination)
        return
    shutil.copytree(source, destination)


def 备份用户级内容(
    paths: 路径配置,
    *,
    target_paths: list[str],
    home_dir: str,
    engine_vendors: list[str],
    ide_vendors: list[str],
    include_missing: bool,
    backup_dir: str,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    resolved_targets_override: list[发布目标] | None = None,
) -> dict[str, Any]:
    """备份 libs 与用户级目标 AI 内容。"""

    if resolved_targets_override is not None:
        targets = list(resolved_targets_override)
    else:
        targets = 解析发布目标(
            target_paths,
            paths=paths,
            home_dir=home_dir,
            engine_vendors=engine_vendors,
            ide_vendors=ide_vendors,
            scopes=scopes,
            project_dirs=project_dirs,
            include_missing=include_missing,
        )

    backup_root = (
        Path(str(backup_dir).strip()).expanduser().resolve()
        if str(backup_dir).strip()
        else 默认用户内容备份根目录(paths)
    )
    snapshot_dir = 构造备份快照目录(backup_root=backup_root)

    summary: dict[str, Any] = {
        "enabled": True,
        "status": "ok",
        "dry_run": dry_run,
        "backup_root": str(backup_root),
        "snapshot_dir": str(snapshot_dir),
        "target_count": len(targets),
        "sources": [],
        "skipped_missing": 0,
        "errors": [],
        "warnings": [],
        "touched_paths": [],
        "file_count": 0,
    }

    source_specs: list[tuple[str, Path, Path, str, str]] = []
    source_specs.append(("libs", paths.libs_root, snapshot_dir / "libs", "libs", "global"))
    for target in targets:
        backup_source_path = target.target_path.parent if target.scope == "project" else target.target_path
        source_specs.append(
            (
                f"target:{target.target_label}",
                backup_source_path,
                snapshot_dir / "targets" / f"{target.target_label}__{target.layout}",
                target.layout,
                target.scope,
            )
        )

    manifest_sources: list[dict[str, Any]] = []
    for source_id, source_path, destination_path, layout, scope in source_specs:
        if not source_path.exists():
            summary["skipped_missing"] += 1
            summary["warnings"].append(f"来源不存在，跳过备份：{source_path}")
            manifest_sources.append(
                {
                    "source_id": source_id,
                    "layout": layout,
                    "scope": scope,
                    "source_path": str(source_path),
                    "destination_path": str(destination_path),
                    "status": "missing",
                    "file_count": 0,
                }
            )
            continue

        file_count = 统计文件数量(source_path)
        manifest_sources.append(
            {
                "source_id": source_id,
                "layout": layout,
                "scope": scope,
                "source_path": str(source_path),
                "destination_path": str(destination_path),
                "status": "copied" if not dry_run else "dry_run_preview",
                "file_count": file_count,
            }
        )
        summary["file_count"] += file_count
        summary["touched_paths"].append(str(destination_path))

        if dry_run:
            continue

        try:
            if destination_path.exists():
                if destination_path.is_file():
                    destination_path.unlink()
                else:
                    shutil.rmtree(destination_path)
            复制到备份快照(source=source_path, destination=destination_path)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"备份失败：{source_path} -> {destination_path} ({exc})")

    summary["sources"] = manifest_sources
    if summary["errors"]:
        summary["status"] = "error"

    manifest_payload = {
        "schema": "aob_user_content_backup_manifest_v1",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "backup_root": str(backup_root),
        "snapshot_dir": str(snapshot_dir),
        "dry_run": dry_run,
        "source_count": len(source_specs),
        "file_count": summary["file_count"],
        "sources": manifest_sources,
        "warnings": list(summary["warnings"]),
        "errors": list(summary["errors"]),
    }
    summary["manifest"] = manifest_payload

    if not dry_run:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = snapshot_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["manifest_path"] = str(manifest_path)
        summary["touched_paths"].append(str(manifest_path))
    else:
        summary["manifest_path"] = str(snapshot_dir / "manifest.json")

    return summary


def 收集用户级内容同步侧(
    paths: 路径配置,
    *,
    targets: list[发布目标],
) -> tuple[
    dict[str, dict[str, dict[str, Any]]],
    dict[str, float],
    list[dict[str, Any]],
    list[str],
    list[str],
    str,
]:
    """收集用于同步决策的 libs/target side AOL 与元数据。"""

    side_entries: dict[str, dict[str, dict[str, Any]]] = {"libs": {}}
    side_observe_times: dict[str, float] = {"libs": 0.0}
    source_summaries: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    title_fallback = f"{paths.repo_root.name} canonical AOL"

    canonical_path = 解析AOL规范文件路径(paths)
    side_observe_times["libs"] = 获取路径最近修改时间(canonical_path)
    libs_summary: dict[str, Any] = {
        "side_id": "libs",
        "source": str(canonical_path),
        "source_label": "libs",
        "layout": "canonical_aol",
        "engine_vendor": "aol",
        "ide_vendor": "aol",
        "scope": "global",
        "contract_level": "canonical",
        "contract_note": "libs canonical AOL 是内部语义真源，不依赖外部供应商目录契约。",
        "observe_at_epoch": side_observe_times["libs"],
        "logical_entry_count": 0,
        "status": "missing",
    }
    if canonical_path.exists() and canonical_path.is_file():
        try:
            libs_aol = 读取canonical_AOL(paths)
            libs_payload = AOL对象转payload(libs_aol)
            side_entries["libs"] = AOL扁平化逻辑条目(libs_payload)
            title_fallback = str(libs_payload.get("title") or title_fallback)
            libs_summary["logical_entry_count"] = len(side_entries["libs"])
            libs_summary["status"] = "loaded"
        except Exception as exc:  # noqa: BLE001
            libs_summary["status"] = "error"
            libs_summary["error"] = str(exc)
            errors.append(f"libs canonical 读取失败：{exc}")
    source_summaries.append(libs_summary)

    for target in targets:
        side_id = f"target:{target.target_label}"
        source = 发布目标转聚合来源(target)
        contract_level, contract_note = 解析供应商载体契约级别(
            layout=source.layout,
            engine_vendor=source.engine_vendor,
            ide_vendor=source.ide_vendor,
            scope=source.scope,
        )
        observe_at = 获取路径最近修改时间(source.source_path)
        side_observe_times[side_id] = observe_at
        side_entries.setdefault(side_id, {})
        source_summary: dict[str, Any] = {
            "side_id": side_id,
            "source": str(source.source_path),
            "source_label": source.source_label,
            "target_label": target.target_label,
            "layout": source.layout,
            "engine_vendor": source.engine_vendor,
            "ide_vendor": source.ide_vendor,
            "scope": source.scope,
            "contract_level": contract_level,
            "contract_note": contract_note,
            "observe_at_epoch": observe_at,
            "logical_entry_count": 0,
            "status": "missing",
        }
        if not source.source_path.exists():
            source_summaries.append(source_summary)
            continue

        if not 是否包含可聚合内容(source.source_path, layout=source.layout, scope=source.scope):
            source_summary["status"] = "empty_or_unsupported"
            source_summaries.append(source_summary)
            continue

        aol, part, part_warnings = 来源构建AOL(paths, source=source)
        warnings.extend(part_warnings)
        if part.get("aol_counts"):
            source_summary["aol_counts"] = dict(part.get("aol_counts") or {})

        part_errors = [str(item) for item in list(part.get("errors") or []) if str(item).strip()]
        if part_errors:
            source_summary["status"] = "error"
            source_summary["error"] = "; ".join(part_errors)
            errors.extend([f"{target.target_label} 反编译失败：{item}" for item in part_errors])
            source_summaries.append(source_summary)
            continue

        if aol is None:
            source_summary["status"] = "empty"
            source_summaries.append(source_summary)
            continue

        payload = AOL对象转payload(aol)
        entries = AOL扁平化逻辑条目(payload)
        side_entries[side_id] = entries
        source_summary["logical_entry_count"] = len(entries)
        source_summary["status"] = "loaded"
        source_summaries.append(source_summary)

    return side_entries, side_observe_times, source_summaries, warnings, errors, title_fallback


def 准备用户级内容同步沙盒(
    paths: 路径配置,
    *,
    targets: list[发布目标],
    home_dir: str = "",
    sandbox_dir: str,
) -> tuple[路径配置, list[发布目标], dict[str, Any]]:
    """把当前 libs canonical 与目标目录复制到独立沙盒。"""

    sandbox_root = 解析唯一沙盒根目录(home_dir=home_dir, sandbox_dir=sandbox_dir)
    sandbox_paths = 构建沙盒路径配置(sandbox_root=sandbox_root)
    复制用户级内容沙盒仓库基线(paths, sandbox_paths=sandbox_paths)

    sandbox_targets: list[发布目标] = []
    sandbox_target_summaries: list[dict[str, Any]] = []
    for target in targets:
        sandbox_target_root = sandbox_root / "targets" / f"{target.target_label}__{target.layout}"
        if target.scope == "project":
            source_root = target.target_path.parent
            if source_root.exists():
                复制到备份快照(source=source_root, destination=sandbox_target_root)
            sandbox_target_path = sandbox_target_root / target.target_path.name
        else:
            sandbox_target_path = sandbox_target_root
            if target.target_path.exists():
                复制到备份快照(source=target.target_path, destination=sandbox_target_path)
        sandbox_targets.append(
            发布目标(
                target_path=sandbox_target_path,
                target_label=target.target_label,
                layout=target.layout,
                engine_vendor=target.engine_vendor,
                ide_vendor=target.ide_vendor,
                scope=target.scope,
            )
        )
        sandbox_target_summaries.append(
            {
                "target_label": target.target_label,
                "layout": target.layout,
                "scope": target.scope,
                "original_path": str(target.target_path),
                "container_root": str(target.target_path.parent if target.scope == "project" else target.target_path),
                "sandbox_path": str(sandbox_target_path),
                "exists_in_source": bool(target.target_path.exists()),
            }
        )

    return sandbox_paths, sandbox_targets, {
        "enabled": True,
        "sandbox_root": str(sandbox_root),
        "targets": sandbox_target_summaries,
    }


def 准备用户级内容聚合沙盒(
    paths: 路径配置,
    *,
    sources: list[聚合来源],
    home_dir: str = "",
    sandbox_dir: str,
) -> tuple[路径配置, list[聚合来源], dict[str, Any]]:
    """把当前 libs canonical 与聚合来源复制到独立沙盒。"""

    sandbox_root = 解析唯一沙盒根目录(home_dir=home_dir, sandbox_dir=sandbox_dir)
    sandbox_paths = 构建沙盒路径配置(sandbox_root=sandbox_root)
    复制用户级内容沙盒仓库基线(paths, sandbox_paths=sandbox_paths)

    sandbox_sources: list[聚合来源] = []
    sandbox_source_summaries: list[dict[str, Any]] = []
    for source in sources:
        sandbox_source_root = sandbox_root / "sources" / f"{source.source_label}__{source.layout}"
        if source.scope == "project":
            source_container_root = source.source_path.parent
            if source_container_root.exists():
                复制到备份快照(source=source_container_root, destination=sandbox_source_root)
            sandbox_source_path = sandbox_source_root / source.source_path.name
        elif source.source_path.is_file():
            sandbox_source_path = sandbox_source_root / source.source_path.name
            if source.source_path.exists():
                复制到备份快照(source=source.source_path, destination=sandbox_source_path)
        else:
            sandbox_source_path = sandbox_source_root
            if source.source_path.exists():
                复制到备份快照(source=source.source_path, destination=sandbox_source_path)

        sandbox_sources.append(
            聚合来源(
                source_path=sandbox_source_path,
                source_label=source.source_label,
                layout=source.layout,
                engine_vendor=source.engine_vendor,
                ide_vendor=source.ide_vendor,
                scope=source.scope,
            )
        )
        sandbox_source_summaries.append(
            {
                "source_label": source.source_label,
                "layout": source.layout,
                "scope": source.scope,
                "original_path": str(source.source_path),
                "container_root": str(source.source_path.parent if source.scope == "project" else source.source_path),
                "sandbox_path": str(sandbox_source_path),
                "exists_in_source": bool(source.source_path.exists()),
            }
        )

    return sandbox_paths, sandbox_sources, {
        "enabled": True,
        "sandbox_root": str(sandbox_root),
        "sources": sandbox_source_summaries,
    }


def 执行聚合用户级内容阶段(
    paths: 路径配置,
    *,
    source_paths: list[str],
    home_dir: str,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    sync_items_after: bool,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    resolved_sources_override: list[聚合来源] | None = None,
) -> tuple[dict[str, Any], Any]:
    """执行聚合阶段并返回聚合摘要与合并后的 AOL。"""

    if not AOL运行时可用():
        raise ValueError("aoc runtime 不可用，无法执行 aggregate-user-content")

    if resolved_sources_override is not None:
        sources = list(resolved_sources_override)
    else:
        sources = 解析聚合来源(
            source_paths,
            paths=paths,
            home_dir=home_dir,
            scopes=scopes,
            project_dirs=project_dirs,
        )

    if simulate_only:
        sandbox_paths, sandbox_sources, sandbox_summary = 准备用户级内容聚合沙盒(
            paths,
            sources=sources,
            home_dir=home_dir,
            sandbox_dir=sandbox_dir,
        )
        sandbox_result, merged_aol = 执行聚合用户级内容阶段(
            sandbox_paths,
            source_paths=[],
            home_dir="",
            scopes=scopes,
            project_dirs=project_dirs,
            dry_run=dry_run,
            sync_items_after=sync_items_after,
            simulate_only=False,
            sandbox_dir="",
            resolved_sources_override=sandbox_sources,
        )
        sandbox_result["sandbox"] = sandbox_summary
        sandbox_result["simulate_only"] = True
        sandbox_result["source_repo_root"] = str(paths.repo_root)
        return sandbox_result, merged_aol

    summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "source_count": len(sources),
        "added": 0,
        "updated": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "sources": [],
        "errors": [],
        "touched_paths": [],
        "aggregate_warnings": [],
        "sandbox": {"enabled": False},
        "simulate_only": False,
    }

    source_aol_entries: list[tuple[聚合来源, Any]] = []

    for source in sources:
        aol, part, warnings = 来源构建AOL(paths, source=source)
        合并聚合统计(summary, part)
        summary["aggregate_warnings"].extend(warnings)
        if aol is not None:
            source_aol_entries.append((source, aol))

    merged_aol, merge_warnings = 合并来源AOL(paths, aol_entries=source_aol_entries)
    summary["aggregate_warnings"].extend(merge_warnings)
    canonical_write = 写入canonical_AOL(paths, aol=merged_aol, dry_run=dry_run)
    summary["canonical_aol"] = canonical_write
    summary["added"] = 1 if canonical_write["status"].endswith("added") else 0
    summary["updated"] = 1 if canonical_write["status"].endswith("updated") else 0
    summary["skipped_same"] = 1 if canonical_write["status"].endswith("unchanged") else 0
    if canonical_write.get("path"):
        summary["touched_paths"].append(str(canonical_write["path"]))

    if sync_items_after and not dry_run and (summary["added"] or summary["updated"]):
        summary["items_sync"] = 同步_items(paths, dry_run=False)
    elif sync_items_after:
        summary["items_sync"] = {
            "enabled": False,
            "reason": "dry_run 模式或无新增变更，跳过 items sync",
            "dry_run": dry_run,
        }
    else:
        summary["items_sync"] = {
            "enabled": False,
            "reason": "显式关闭 items sync",
            "dry_run": dry_run,
        }

    if dry_run:
        summary["aol_intermediate"] = 构建AOL摘要(
            merged_aol,
            source="in_memory_dry_run",
            canonical_path=Path(str(canonical_write.get("path") or "")) if canonical_write.get("path") else None,
            warnings=list(summary["aggregate_warnings"]),
        )
    else:
        summary["aol_intermediate"] = 构建libs_aol中转摘要(paths)

    return summary, merged_aol


def 更新用户级内容(
    paths: 路径配置,
    *,
    target_paths: list[str],
    home_dir: str,
    engine_vendors: list[str],
    ide_vendors: list[str],
    include_missing: bool,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    sync_items_after: bool,
    backup_before_sync: bool = True,
    backup_dir: str = "",
    simulate_only: bool = False,
    sandbox_dir: str = "",
    resolved_targets_override: list[发布目标] | None = None,
) -> dict[str, Any]:
    """执行用户级内容同步（基于 logical key + SQLite 元数据决策）。"""

    if not AOL运行时可用():
        raise ValueError("aoc runtime 不可用，无法执行 update-user-content")

    if resolved_targets_override is not None:
        resolved_targets = list(resolved_targets_override)
    else:
        resolved_targets = 解析发布目标(
            target_paths,
            paths=paths,
            home_dir=home_dir,
            engine_vendors=engine_vendors,
            ide_vendors=ide_vendors,
            scopes=scopes,
            project_dirs=project_dirs,
            include_missing=include_missing,
        )

    if simulate_only:
        sandbox_paths, sandbox_targets, sandbox_summary = 准备用户级内容同步沙盒(
            paths,
            targets=resolved_targets,
            home_dir=home_dir,
            sandbox_dir=sandbox_dir,
        )
        sandbox_result = 更新用户级内容(
            sandbox_paths,
            target_paths=[],
            home_dir="",
            engine_vendors=[],
            ide_vendors=[],
            include_missing=True,
            scopes=scopes,
            project_dirs=project_dirs,
            dry_run=dry_run,
            sync_items_after=sync_items_after,
            backup_before_sync=False,
            backup_dir="",
            simulate_only=False,
            sandbox_dir="",
            resolved_targets_override=sandbox_targets,
        )
        sandbox_result["sandbox"] = sandbox_summary
        sandbox_result["simulate_only"] = True
        sandbox_result["source_repo_root"] = str(paths.repo_root)
        return sandbox_result

    summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "source_count": 0,
        "target_count": 0,
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "targets": [],
        "errors": [],
        "touched_paths": [],
        "update_warnings": [],
        "aggregate_warnings": [],
        "publish_warnings": [],
        "sync_mode": "logical_key_registry_compare_then_publish",
        "decision_summary": {"added": 0, "updated": 0, "deleted": 0},
        "registry_summary": {"registry_hit_count": 0, "fallback_count": 0, "active_side_count": 0, "logical_key_count": 0},
        "sync_registry": {"enabled": False, "dry_run": dry_run},
        "sandbox": {"enabled": False},
        "simulate_only": False,
    }

    if backup_before_sync:
        backup_summary = 备份用户级内容(
            paths,
            target_paths=[str(item.target_path) for item in resolved_targets],
            home_dir=home_dir,
            engine_vendors=engine_vendors,
            ide_vendors=ide_vendors,
            include_missing=include_missing,
            backup_dir=backup_dir,
            scopes=scopes,
            project_dirs=project_dirs,
            dry_run=dry_run,
            resolved_targets_override=resolved_targets,
        )
        summary["backup"] = backup_summary
        summary["update_warnings"].extend(list(backup_summary.get("warnings") or []))
        summary["errors"].extend(list(backup_summary.get("errors") or []))
        summary["touched_paths"].extend(list(backup_summary.get("touched_paths") or []))
        if backup_summary.get("status") != "ok":
            raise ValueError(f"备份失败，已停止同步：{backup_summary}")
    else:
        summary["backup"] = {
            "enabled": False,
            "status": "skipped",
            "reason": "显式关闭备份",
            "dry_run": dry_run,
            "warnings": [],
            "errors": [],
            "touched_paths": [],
        }

    previous_registry, previous_target_files = 读取用户内容同步数据库基线(paths)
    side_entries, side_observe_times, source_summaries, aggregate_warnings, sync_errors, title_fallback = 收集用户级内容同步侧(
        paths,
        targets=resolved_targets,
    )
    side_priority = ["libs", *[f"target:{item.target_label}" for item in resolved_targets]]
    final_entries, registry_rows, registry_summary = 计算一键更新决策(
        side_entries=side_entries,
        side_observe_times=side_observe_times,
        previous_registry=previous_registry,
        side_priority=side_priority,
    )
    decision_summary = 计算canonical变更摘要(
        libs_entries=side_entries.get("libs", {}),
        final_entries=final_entries,
    )
    final_payload = 逻辑条目转AOL_payload(final_entries, title_fallback=title_fallback)
    merged_aol = payload转AOL对象(final_payload)
    canonical_write = {
        "path": str(解析AOL规范文件路径(paths)),
        "status": "blocked",
        "written": False,
        "dry_run": dry_run,
    }
    if not sync_errors:
        canonical_write = 写入canonical_AOL(paths, aol=merged_aol, dry_run=dry_run)

    aggregate_summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "source_count": len(source_summaries),
        "added": int(decision_summary.get("added") or 0),
        "updated": int(decision_summary.get("updated") or 0),
        "deleted": int(decision_summary.get("deleted") or 0),
        "sources": source_summaries,
        "errors": list(sync_errors),
        "touched_paths": [str(canonical_write.get("path") or "")] if canonical_write.get("path") else [],
        "aggregate_warnings": list(aggregate_warnings),
        "canonical_aol": canonical_write,
        "decision_summary": decision_summary,
        "registry_summary": registry_summary,
    }

    if sync_items_after and not dry_run and sum(int(value) for value in decision_summary.values()) > 0 and not sync_errors:
        aggregate_summary["items_sync"] = 同步_items(paths, dry_run=False)
    elif sync_items_after:
        aggregate_summary["items_sync"] = {
            "enabled": False,
            "reason": "dry_run 模式、无 canonical 变更或同步侧异常，跳过 items sync",
            "dry_run": dry_run,
        }
    else:
        aggregate_summary["items_sync"] = {
            "enabled": False,
            "reason": "显式关闭 items sync",
            "dry_run": dry_run,
        }

    if dry_run:
        aggregate_summary["aol_intermediate"] = 构建AOL摘要(
            merged_aol,
            source="in_memory_sync_dry_run",
            canonical_path=Path(str(canonical_write.get("path") or "")) if canonical_write.get("path") else None,
            warnings=list(aggregate_warnings),
        )
    elif sync_errors:
        aggregate_summary["aol_intermediate"] = {
            "enabled": False,
            "status": "blocked",
            "reason": "同步侧存在反编译错误，已阻止 canonical 写入与发布",
            "warnings": list(sync_errors),
        }
    else:
        aggregate_summary["aol_intermediate"] = 构建libs_aol中转摘要(paths)

    summary["aggregate"] = aggregate_summary
    summary["source_count"] = int(aggregate_summary.get("source_count") or 0)
    summary["canonical_aol"] = aggregate_summary.get("canonical_aol")
    summary["items_sync"] = aggregate_summary.get("items_sync")
    summary["aol_intermediate"] = aggregate_summary.get("aol_intermediate")
    summary["aggregate_warnings"] = list(aggregate_summary.get("aggregate_warnings") or [])
    summary["update_warnings"].extend(summary["aggregate_warnings"])
    summary["errors"].extend(list(aggregate_summary.get("errors") or []))
    summary["touched_paths"].extend(list(aggregate_summary.get("touched_paths") or []))
    summary["decision_summary"] = dict(decision_summary)
    summary["registry_summary"] = dict(registry_summary)

    publish_summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "target_count": len(resolved_targets),
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "targets": [],
        "errors": [],
        "touched_paths": [],
        "aol_intermediate": aggregate_summary.get("aol_intermediate"),
        "publish_warnings": [],
    }

    managed_target_files: dict[tuple[str, str], set[str]] = {}
    if sync_errors:
        publish_summary["errors"].append("同步侧存在反编译错误，已跳过正式发布")
    else:
        publish_aol = merged_aol if dry_run else 读取canonical_AOL(paths)
        for target in resolved_targets:
            part, managed_files = 发布到单个目标并同步删除(
                aol=publish_aol,
                target=target,
                dry_run=dry_run,
                warnings=publish_summary["publish_warnings"],
                previous_managed_files=previous_target_files.get((target.target_label, target.layout), set()),
            )
            managed_target_files[(target.target_label, target.layout)] = managed_files
            合并发布统计(publish_summary, part)

    summary["sync_registry"] = 写入用户内容同步数据库(
        paths,
        registry_rows=registry_rows,
        target_files=managed_target_files,
        dry_run=dry_run,
    )

    summary["publish"] = publish_summary
    summary["target_count"] = publish_summary["target_count"]
    summary["targets"] = list(publish_summary["targets"])
    summary["added"] = publish_summary["added"]
    summary["updated"] = publish_summary["updated"]
    summary["deleted"] = publish_summary["deleted"]
    summary["skipped_same"] = publish_summary["skipped_same"]
    summary["skipped_target_newer"] = publish_summary["skipped_target_newer"]
    summary["publish_warnings"] = list(publish_summary["publish_warnings"])
    summary["errors"].extend(list(publish_summary.get("errors") or []))
    summary["touched_paths"].extend(list(publish_summary.get("touched_paths") or []))

    return summary


def 聚合用户级内容(
    paths: 路径配置,
    *,
    source_paths: list[str],
    home_dir: str,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    sync_items_after: bool,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    resolved_sources_override: list[聚合来源] | None = None,
) -> dict[str, Any]:
    """聚合当前设备用户级 AI 内容到 libs。"""

    summary, _merged_aol = 执行聚合用户级内容阶段(
        paths,
        source_paths=source_paths,
        home_dir=home_dir,
        scopes=scopes,
        project_dirs=project_dirs,
        dry_run=dry_run,
        sync_items_after=sync_items_after,
        simulate_only=simulate_only,
        sandbox_dir=sandbox_dir,
        resolved_sources_override=resolved_sources_override,
    )
    return summary


def 读取_items(paths: 路径配置) -> dict[str, dict[str, Any]]:
    """读取 `items.csv`。"""

    if not paths.items_csv.exists():
        return {}

    with paths.items_csv.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        rows: dict[str, dict[str, Any]] = {}
        for row in reader:
            relative_path = 规范路径(str(row.get("relative_path") or ""))
            if not relative_path:
                continue
            rows[relative_path] = {
                "uid": str(row.get("uid") or "").strip(),
                "name": str(row.get("name") or "").strip(),
                "content_type": str(row.get("content_type") or "").strip(),
                "scenario_tags": 解析标签单元格(str(row.get("scenario_tags") or "")),
                "relative_path": relative_path,
                "item_type": str(row.get("item_type") or "").strip(),
                "file_count": int(str(row.get("file_count") or "0") or "0"),
            }
        return rows


def 写入_items(paths: 路径配置, rows: dict[str, dict[str, Any]]) -> None:
    """写入 `items.csv`。

    Args:
        paths: 路径配置。
        rows: 条目映射，键为 relative_path。
    """

    paths.items_csv.parent.mkdir(parents=True, exist_ok=True)
    with paths.items_csv.open("w", encoding="utf-8", newline="") as file:
        fieldnames = ["uid", "name", "content_type", "scenario_tags", "relative_path", "item_type", "file_count"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for relative_path in sorted(rows.keys()):
            row = rows.get(relative_path) or {}
            writer.writerow(
                {
                    "uid": str(row.get("uid") or "").strip(),
                    "name": str(row.get("name") or "").strip(),
                    "content_type": str(row.get("content_type") or "").strip(),
                    "scenario_tags": 序列化标签单元格(list(row.get("scenario_tags") or [])),
                    "relative_path": 规范路径(str(row.get("relative_path") or relative_path)),
                    "item_type": str(row.get("item_type") or "").strip(),
                    "file_count": int(str(row.get("file_count") or "0") or "0"),
                }
            )


def 写入关系表(paths: 路径配置, items_rows: dict[str, dict[str, Any]]) -> None:
    """由 `items.csv` 数据写出二维关系表。

    Args:
        paths: 路径配置。
        items_rows: 条目映射。
    """

    tags: list[str] = list(默认场景标签顺序)
    seen = set(tags)
    for row in items_rows.values():
        for tag in list(row.get("scenario_tags") or []):
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)

    paths.relation_csv.parent.mkdir(parents=True, exist_ok=True)
    with paths.relation_csv.open("w", encoding="utf-8", newline="") as file:
        fieldnames = ["uid", "name", *tags]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for row in sorted(items_rows.values(), key=lambda r: str(r.get("name") or "")):
            name = str(row.get("name") or "").strip()
            uid = str(row.get("uid") or "").strip()
            row_tags = set(规范标签(list(row.get("scenario_tags") or [])))
            out = {"uid": uid, "name": name}
            for tag in tags:
                out[tag] = "1" if tag in row_tags else "0"
            writer.writerow(out)


def 读取关系表(paths: 路径配置) -> dict[str, list[str]]:
    """读取二维关系表并返回 UID -> 标签映射。

    Args:
        paths: 路径配置。

    Returns:
        dict[str, list[str]]: UID 到标签列表的映射。
    """

    if not paths.relation_csv.exists() or not paths.relation_csv.is_file():
        return {}

    with paths.relation_csv.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            return {}

        tag_columns = [
            str(name or "").strip()
            for name in reader.fieldnames
            if str(name or "").strip() and str(name or "").strip() not in {"uid", "name"}
        ]
        if not tag_columns:
            return {}

        mapping: dict[str, list[str]] = {}
        for row in reader:
            uid = str(row.get("uid") or "").strip()
            if not uid:
                continue

            tags: list[str] = []
            for column in tag_columns:
                cell = str(row.get(column) or "").strip().lower()
                if cell in {"1", "true", "yes", "y", "x"}:
                    tags.append(column)
            mapping[uid] = 规范标签(tags)

        return mapping


def 解析开头元数据块(text: str) -> tuple[str, list[str], str] | None:
    """解析文本开头的 YAML 元数据块。

    支持两种常见形式：
    1. 文件开头即 `---` 的 front-matter。
    2. 代码围栏后紧跟 `---` 的 AOL/AOC 模板头。

    Args:
        text: 原始文本。

    Returns:
        tuple[str, list[str], str] | None: `(前缀, 元数据行列表, 后缀)`；若未命中则返回 `None`。
    """

    lines = text.splitlines(keepends=True)
    if not lines:
        return None

    start_index: int | None = None
    if lines[0].strip() == "---":
        start_index = 0
    else:
        scan_limit = min(20, len(lines))
        for index in range(scan_limit):
            if lines[index].strip() != "---":
                continue
            prior = [line.strip() for line in lines[:index] if line.strip()]
            if prior and all(line.startswith("```") for line in prior):
                start_index = index
                break

    if start_index is None:
        return None

    end_index: int | None = None
    for index in range(start_index + 1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return None

    prefix = "".join(lines[:start_index])
    metadata_lines = [line.rstrip("\r\n") for line in lines[start_index + 1 : end_index]]
    suffix = "".join(lines[end_index + 1 :])
    return prefix, metadata_lines, suffix


def 更新元数据文本(*, text: str, uid: str, name: str) -> tuple[str, bool]:
    """更新单个文本中的元数据字段。

    规则：
    - 顶层 `id` 字段统一迁移为 `uid`。
    - 保证存在并更新顶层 `uid` 与 `name` 字段。

    Args:
        text: 原始文本。
        uid: 目标 UID。
        name: 目标名称。

    Returns:
        tuple[str, bool]: `(新文本, 是否发生变更)`。
    """

    parsed = 解析开头元数据块(text)
    if parsed is None:
        return text, False

    prefix, metadata_lines, suffix = parsed
    key_pattern = re.compile(r"^([A-Za-z0-9_-]+)\s*:")
    uid_line = f'uid: {json.dumps(uid, ensure_ascii=False)}'
    name_line = f'name: {json.dumps(name, ensure_ascii=False)}'

    updated_lines: list[str] = []
    has_uid = False
    has_name = False

    for line in metadata_lines:
        match = key_pattern.match(line)
        if not match:
            updated_lines.append(line)
            continue

        key = match.group(1)
        if key == "id":
            continue
        if key == "uid":
            if not has_uid:
                updated_lines.append(uid_line)
                has_uid = True
            continue
        if key == "name":
            if not has_name:
                updated_lines.append(name_line)
                has_name = True
            continue

        updated_lines.append(line)

    if not has_uid:
        updated_lines.append(uid_line)
    if not has_name:
        updated_lines.append(name_line)

    header = "\n".join(updated_lines)
    if header:
        header += "\n"
    new_text = f"{prefix}---\n{header}---\n{suffix}"
    return new_text, new_text != text


def 解析元数据目标文件(*, paths: 路径配置, row: dict[str, Any]) -> Path | None:
    """解析条目对应的元数据文件路径。

    Args:
        paths: 路径配置。
        row: 条目行数据。

    Returns:
        Path | None: 可写元数据文件路径；若无可维护元数据文件则返回 `None`。
    """

    relative = 规范路径(str(row.get("relative_path") or ""))
    if not relative:
        return None

    target = paths.repo_root / relative
    if target.is_file() and target.suffix.lower() == ".md":
        return target
    if target.is_dir():
        skill_file = target / "SKILL.md"
        if skill_file.exists() and skill_file.is_file():
            return skill_file
    return None


def 同步_items元数据(paths: 路径配置, rows: dict[str, dict[str, Any]], *, dry_run: bool) -> dict[str, int]:
    """按 `items` 结果同步条目元数据。

    Args:
        paths: 路径配置。
        rows: 条目映射。
        dry_run: 是否预演。

    Returns:
        dict[str, int]: 元数据同步统计。
    """

    scanned_count = 0
    changed_count = 0
    skipped_count = 0

    for row in rows.values():
        uid = str(row.get("uid") or "").strip()
        name = str(row.get("name") or "").strip()
        if not uid or not name:
            skipped_count += 1
            continue

        metadata_file = 解析元数据目标文件(paths=paths, row=row)
        if metadata_file is None:
            skipped_count += 1
            continue

        scanned_count += 1
        original = metadata_file.read_text(encoding="utf-8", errors="ignore")
        updated, changed = 更新元数据文本(text=original, uid=uid, name=name)
        if not changed:
            continue
        changed_count += 1
        if not dry_run:
            metadata_file.write_text(updated, encoding="utf-8")

    return {
        "target_files": scanned_count,
        "updated_files": changed_count,
        "skipped": skipped_count,
    }


def 读取工作区profile记录(paths: 路径配置) -> list[dict[str, Any]]:
    """读取工作区 profile 记录。"""

    if not paths.profile_db_json.exists():
        return []

    payload = json.loads(paths.profile_db_json.read_text(encoding="utf-8"))
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, list):
        return []
    return [item for item in profiles if isinstance(item, dict)]


def 同步_registry_sqlite(paths: 路径配置, rows: dict[str, dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    """同步 SQLite sidecar 索引。

    保持 CSV/JSON 作为人工维护真源；SQLite 仅作为运行时查询与多维关系索引。
    """

    profiles = 读取工作区profile记录(paths)
    tag_rows = sum(len(规范标签(list(row.get("scenario_tags") or []))) for row in rows.values())
    profile_path_rows = 0
    for profile in profiles:
        profile_path_rows += len(list(profile.get("project_config_paths") or []))
        profile_path_rows += len(list(profile.get("workspace_config_paths") or []))
        profile_path_rows += len(list(profile.get("instruction_paths") or []))

    if dry_run:
        return {
            "enabled": True,
            "dry_run": True,
            "sqlite_path": str(paths.registry_sqlite),
            "items": len(rows),
            "item_tags": tag_rows,
            "profiles": len(profiles),
            "profile_paths": profile_path_rows,
        }

    paths.registry_sqlite.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(paths.registry_sqlite)) as conn:
        conn.executescript(
            """
            DROP TABLE IF EXISTS items;
            DROP TABLE IF EXISTS item_tags;
            DROP TABLE IF EXISTS workspace_profiles;
            DROP TABLE IF EXISTS workspace_profile_paths;

            CREATE TABLE items (
                uid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                content_type TEXT NOT NULL,
                scenario_tags TEXT NOT NULL,
                relative_path TEXT NOT NULL UNIQUE,
                item_type TEXT NOT NULL,
                file_count INTEGER NOT NULL
            );

            CREATE TABLE item_tags (
                uid TEXT NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY (uid, tag)
            );

            CREATE TABLE workspace_profiles (
                profile_id TEXT PRIMARY KEY,
                ide_vendor TEXT NOT NULL,
                ide_product TEXT,
                engine_vendor TEXT NOT NULL,
                engine_product TEXT,
                os_family TEXT NOT NULL,
                os_version_family TEXT,
                workspace_dir_name TEXT NOT NULL,
                install_scope TEXT,
                runtime_mode TEXT,
                status TEXT,
                default_for_engine INTEGER NOT NULL,
                raw_json TEXT NOT NULL
            );

            CREATE TABLE workspace_profile_paths (
                profile_id TEXT NOT NULL,
                path_kind TEXT NOT NULL,
                path_value TEXT NOT NULL,
                PRIMARY KEY (profile_id, path_kind, path_value)
            );
            """
        )

        conn.executemany(
            """
            INSERT INTO items(uid, name, content_type, scenario_tags, relative_path, item_type, file_count)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(row.get("uid") or "").strip(),
                    str(row.get("name") or "").strip(),
                    str(row.get("content_type") or "").strip(),
                    序列化标签单元格(list(row.get("scenario_tags") or [])),
                    str(row.get("relative_path") or "").strip(),
                    str(row.get("item_type") or "").strip(),
                    int(row.get("file_count") or 0),
                )
                for row in rows.values()
            ],
        )

        item_tag_payload: list[tuple[str, str]] = []
        for row in rows.values():
            uid = str(row.get("uid") or "").strip()
            for tag in 规范标签(list(row.get("scenario_tags") or [])):
                item_tag_payload.append((uid, tag))
        conn.executemany("INSERT INTO item_tags(uid, tag) VALUES(?, ?)", item_tag_payload)

        conn.executemany(
            """
            INSERT INTO workspace_profiles(
                profile_id, ide_vendor, ide_product, engine_vendor, engine_product,
                os_family, os_version_family, workspace_dir_name, install_scope,
                runtime_mode, status, default_for_engine, raw_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(profile.get("profile_id") or "").strip(),
                    str(profile.get("ide_vendor") or "").strip(),
                    str(profile.get("ide_product") or "").strip(),
                    str(profile.get("engine_vendor") or "").strip(),
                    str(profile.get("engine_product") or "").strip(),
                    str(profile.get("os_family") or "").strip(),
                    str(profile.get("os_version_family") or "").strip(),
                    str(profile.get("workspace_dir_name") or "").strip(),
                    str(profile.get("install_scope") or "").strip(),
                    str(profile.get("runtime_mode") or "").strip(),
                    str(profile.get("status") or "").strip(),
                    1 if bool(profile.get("default_for_engine", False)) else 0,
                    json.dumps(profile, ensure_ascii=False),
                )
                for profile in profiles
            ],
        )

        profile_path_payload: list[tuple[str, str, str]] = []
        for profile in profiles:
            profile_id = str(profile.get("profile_id") or "").strip()
            for path_value in list(profile.get("project_config_paths") or []):
                profile_path_payload.append((profile_id, "project_config", str(path_value).strip()))
            for path_value in list(profile.get("workspace_config_paths") or []):
                profile_path_payload.append((profile_id, "workspace_config", str(path_value).strip()))
            for path_value in list(profile.get("instruction_paths") or []):
                profile_path_payload.append((profile_id, "instruction", str(path_value).strip()))
        conn.executemany(
            "INSERT INTO workspace_profile_paths(profile_id, path_kind, path_value) VALUES(?, ?, ?)",
            profile_path_payload,
        )
        conn.commit()

    return {
        "enabled": True,
        "dry_run": False,
        "sqlite_path": str(paths.registry_sqlite),
        "items": len(rows),
        "item_tags": len(item_tag_payload),
        "profiles": len(profiles),
        "profile_paths": len(profile_path_payload),
    }


def 扫描_libs(paths: 路径配置) -> dict[str, dict[str, Any]]:
    """扫描 `libs/` 生成条目映射。

    Args:
        paths: 路径配置。

    Returns:
        dict[str, dict[str, Any]]: 扫描结果。
    """

    result: dict[str, dict[str, Any]] = {}
    if not paths.libs_root.exists():
        return result

    for content_dir in sorted(path for path in paths.libs_root.iterdir() if path.is_dir()):
        if 是否应忽略路径(content_dir):
            continue
        content_type = content_dir.name
        for child in sorted(content_dir.iterdir()):
            if 是否应忽略路径(child):
                continue
            relative = 规范路径(str(child.relative_to(paths.repo_root)))
            name = child.name
            for suffix in [".agent.md", ".skill.md", ".hook.md", ".prompt.md", ".md"]:
                if name.lower().endswith(suffix):
                    name = name[: -len(suffix)]
                    break
            item_type = "文件夹" if child.is_dir() else (child.suffix.lower().lstrip(".") or "无后缀")
            file_count = (
                sum(1 for p in child.rglob("*") if p.is_file() and not 是否应忽略路径(p))
                if child.is_dir()
                else 0
            )
            result[relative] = {
                "name": name,
                "content_type": content_type,
                "relative_path": relative,
                "item_type": item_type,
                "file_count": file_count,
            }
    return result


def 是否应忽略路径(path: Path) -> bool:
    """判断扫描时是否应忽略该路径。

    Args:
        path: 待判断路径。

    Returns:
        bool: 为 `True` 表示应忽略。
    """

    for part in path.parts:
        if part in 默认忽略目录名:
            return True

    name = path.name
    if name in 默认忽略文件名:
        return True

    if path.is_file() and path.suffix.lower() in 默认忽略文件后缀:
        return True

    return False


def 生成_uid(existing: set[str]) -> str:
    """生成唯一 UID。

    Args:
        existing: 已存在 UID 集合。

    Returns:
        str: 新 UID。
    """

    for _ in range(10):
        candidate = uuid.uuid4().hex[:12]
        if candidate not in existing:
            return candidate
    return uuid.uuid4().hex


def 同步_items(paths: 路径配置, *, dry_run: bool) -> dict[str, Any]:
    """执行 `items sync`。

    Args:
        paths: 路径配置。
        dry_run: 是否预演。

    Returns:
        dict[str, Any]: 同步统计。
    """

    aol_stats = 同步_aol库(paths, dry_run=dry_run)
    existing = 读取_items(paths)
    scanned = 扫描_libs(paths)
    relation_map = 读取关系表(paths)

    existing_keys = set(existing.keys())
    scanned_keys = set(scanned.keys())
    added = sorted(scanned_keys - existing_keys)
    removed = sorted(existing_keys - scanned_keys)

    final_rows: dict[str, dict[str, Any]] = {}
    used_uids = {str(row.get("uid") or "").strip() for row in existing.values() if str(row.get("uid") or "").strip()}

    for relative in sorted(scanned.keys()):
        scan_row = scanned[relative]
        old_row = existing.get(relative, {})

        uid = str(old_row.get("uid") or "").strip()
        if not uid:
            uid = 生成_uid(used_uids)
        used_uids.add(uid)

        tags = 规范标签(list(old_row.get("scenario_tags") or []))
        if uid in relation_map:
            tags = relation_map[uid]

        final_rows[relative] = {
            "uid": uid,
            "name": scan_row["name"],
            "content_type": scan_row["content_type"],
            "scenario_tags": tags,
            "relative_path": relative,
            "item_type": scan_row["item_type"],
            "file_count": scan_row["file_count"],
        }

    manifest = {
        "schema_version": 2,
        "content_root": str(paths.libs_root),
        "items": {
            key: {
                "uid": row["uid"],
                "name": row["name"],
                "content_type": row["content_type"],
                "relative_path": row["relative_path"],
                "item_type": row["item_type"],
                "file_count": row["file_count"],
            }
            for key, row in sorted(final_rows.items())
        },
    }

    if not dry_run:
        metadata_stats = 同步_items元数据(paths, final_rows, dry_run=False)
        sqlite_stats = 同步_registry_sqlite(paths, final_rows, dry_run=False)
        写入_items(paths, final_rows)
        写入关系表(paths, final_rows)
        paths.manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        metadata_stats = 同步_items元数据(paths, final_rows, dry_run=True)
        sqlite_stats = 同步_registry_sqlite(paths, final_rows, dry_run=True)

    return {
        "added": len(added),
        "removed": len(removed),
        "items_total": len(final_rows),
        "items_csv": str(paths.items_csv),
        "relation_csv": str(paths.relation_csv),
        "manifest": str(paths.manifest_json),
        "dry_run": dry_run,
        "metadata_sync": metadata_stats,
        "sqlite_sync": sqlite_stats,
        "aol_sync": aol_stats,
    }


def 解析标签参数(tags_text: str) -> list[str]:
    """解析命令行标签参数。

    Args:
        tags_text: 逗号分隔标签文本，例如 ``写论文,管理文献数据``。

    Returns:
        list[str]: 规范化后的标签列表。

    Raises:
        ValueError: 当标签参数为空时抛出。

    Examples:
        >>> 解析标签参数("写论文,管理文献数据")
        ['写论文', '管理文献数据']
    """

    tags = 规范标签([part.strip() for part in str(tags_text).split(",") if part.strip()])
    if not tags:
        raise ValueError("--tags 不能为空，示例：写论文,管理文献数据")
    return tags


def 解析路径参数(paths_text: str) -> list[str]:
    """解析命令行路径参数。

    Args:
        paths_text: 逗号分隔路径文本，可为文件或目录。

    Returns:
        list[str]: 规范化后的相对路径列表（以 ``libs/`` 开头）。

    Examples:
        >>> 解析路径参数("libs/skills/arxiv,libs/agents")
        ['libs/skills/arxiv', 'libs/agents']
    """

    raw_parts = [part.strip() for part in str(paths_text or "").split(",") if part.strip()]
    parsed: list[str] = []
    for part in raw_parts:
        relative = 规范路径(part)
        if not relative.startswith("libs/"):
            relative = 规范路径(f"libs/{relative}")
        parsed.append(relative)
    return parsed


def 导入_items(
    paths: 路径配置,
    *,
    tags: list[str],
    only_new: bool,
    target_paths: list[str],
    mode: str,
    dry_run: bool,
) -> dict[str, Any]:
    """导入条目并批量写入场景标签。

    Args:
        paths: 路径配置。
        tags: 需要批量应用的标签列表。
        only_new: 是否仅处理新增条目。
        target_paths: 指定处理路径列表；为空时处理扫描结果全集。
        mode: 标签写入模式，``add`` 或 ``replace``。
        dry_run: 是否预演。

    Returns:
        dict[str, Any]: 导入统计信息。

    Raises:
        ValueError: 当模式不受支持时抛出。

    Examples:
        >>> isinstance(导入_items, object)
        True
    """

    if mode not in {"add", "replace"}:
        raise ValueError("--mode 仅支持 add 或 replace")

    existing_rows = 读取_items(paths)
    scanned_rows = 扫描_libs(paths)
    selected_keys = sorted(scanned_rows.keys())

    if target_paths:
        selected_keys = [
            key
            for key in selected_keys
            if any(key == target or key.startswith(f"{target}/") for target in target_paths)
        ]

    if only_new:
        existing_keys = set(existing_rows.keys())
        selected_keys = [key for key in selected_keys if key not in existing_keys]

    working_rows = dict(existing_rows)
    used_uids = {
        str(row.get("uid") or "").strip()
        for row in working_rows.values()
        if str(row.get("uid") or "").strip()
    }

    created_count = 0
    updated_count = 0

    for relative in selected_keys:
        scan_row = scanned_rows[relative]
        current = working_rows.get(relative, {})

        uid = str(current.get("uid") or "").strip()
        if not uid:
            uid = 生成_uid(used_uids)
        used_uids.add(uid)

        old_tags = 规范标签(list(current.get("scenario_tags") or []))
        new_tags = 规范标签(tags if mode == "replace" else old_tags + tags)

        if relative not in working_rows:
            created_count += 1
        if old_tags != new_tags:
            updated_count += 1

        working_rows[relative] = {
            "uid": uid,
            "name": scan_row["name"],
            "content_type": scan_row["content_type"],
            "scenario_tags": new_tags,
            "relative_path": relative,
            "item_type": scan_row["item_type"],
            "file_count": scan_row["file_count"],
        }

    if not dry_run:
        写入_items(paths, working_rows)
        写入关系表(paths, working_rows)

    return {
        "selected": len(selected_keys),
        "created": created_count,
        "tag_updated": updated_count,
        "tags": 规范标签(tags),
        "mode": mode,
        "only_new": only_new,
        "target_paths": target_paths,
        "dry_run": dry_run,
        "items_csv": str(paths.items_csv),
        "relation_csv": str(paths.relation_csv),
    }


def 同步_aol库(paths: 路径配置, *, dry_run: bool) -> dict[str, Any]:
    """把 `libs/` 中模板归一化为 AOB 文件。

    Args:
        paths: 路径配置。
        dry_run: 是否预演。

    Returns:
        dict[str, Any]: AOB 同步统计。
    """

    if 原位归一化libs_aol is None:
        return {
            "enabled": False,
            "reason": "aoc 模块不可用，跳过 AOL 同步",
            "dry_run": dry_run,
        }

    stats = 原位归一化libs_aol(libs_root=paths.libs_root, dry_run=dry_run)

    return {
        "enabled": True,
        "dry_run": dry_run,
        "output": str(paths.libs_root),
        "normalized_files": int(stats.get("normalized_files", 0)),
        "agents_converted": int(stats.get("agents", 0)),
        "skills_converted": int(stats.get("skills", 0)),
        "rules_converted": int(stats.get("rules", 0)),
    }


def 执行_items(argv: list[str], paths: 路径配置) -> int:
    """执行 `items` 子命令。

    Args:
        argv: 参数列表。
        paths: 路径配置。

    Returns:
        int: 退出码。
    """

    parser = argparse.ArgumentParser(description="条目清单管理")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="扫描 libs 并同步 items.csv")
    sync.add_argument("--strategy", default="mtime_size_then_hash")
    sync.add_argument("--dry-run", action="store_true")

    get_cmd = sub.add_parser("get", help="按 UID 查询条目")
    get_cmd.add_argument("--item-id", required=True)

    delete_cmd = sub.add_parser("delete", help="按 UID 删除条目")
    delete_cmd.add_argument("--item-id", required=True)
    delete_cmd.add_argument("--dry-run", action="store_true")

    upsert = sub.add_parser("upsert", help="新增或更新条目")
    upsert.add_argument("--item-id", default="")
    upsert.add_argument("--content-type", required=True)
    upsert.add_argument("--relative-path", required=True)
    upsert.add_argument("--scenario-name", default="")
    upsert.add_argument("--file-count", type=int, default=0)
    upsert.add_argument("--dry-run", action="store_true")

    import_cmd = sub.add_parser("import", help="批量导入条目并设置标签")
    import_cmd.add_argument("--tags", required=True, help="逗号分隔标签列表，例如：写论文,管理文献数据")
    import_cmd.add_argument("--paths", default="", help="可选：逗号分隔路径列表，仅处理这些路径")
    import_cmd.add_argument("--only-new", action="store_true", help="仅处理新增条目")
    import_cmd.add_argument("--mode", choices=["add", "replace"], default="add", help="标签写入模式")
    import_cmd.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    rows = 读取_items(paths)

    if args.command == "sync":
        stats = 同步_items(paths, dry_run=bool(args.dry_run))
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    if args.command == "get":
        for row in rows.values():
            if str(row.get("uid") or "") == str(args.item_id):
                print(json.dumps(row, ensure_ascii=False, indent=2))
                return 0
        print(f"[ERROR] 未找到 uid：{args.item_id}", file=sys.stderr)
        return 2

    if args.command == "delete":
        deleted = False
        for key, row in list(rows.items()):
            if str(row.get("uid") or "") == str(args.item_id):
                deleted = True
                rows.pop(key, None)
                break
        if deleted and not args.dry_run:
            写入_items(paths, rows)
            写入关系表(paths, rows)
        print(json.dumps({"deleted": deleted, "uid": str(args.item_id), "dry_run": bool(args.dry_run)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "upsert":
        relative = 规范路径(str(args.relative_path))
        if not relative.startswith("libs/"):
            relative = 规范路径(f"libs/{relative}")
        tags: list[str] | None = None
        if str(args.scenario_name).strip():
            parsed = json.loads(str(args.scenario_name))
            if not isinstance(parsed, list):
                raise ValueError("--scenario-name 必须为 JSON 列表")
            tags = 规范标签([str(item) for item in parsed if isinstance(item, str)])

        current = rows.get(relative, {})
        existing_uids = {str(row.get("uid") or "").strip() for row in rows.values() if str(row.get("uid") or "").strip()}
        uid = str(args.item_id or "").strip() or str(current.get("uid") or "").strip()
        if not uid:
            uid = 生成_uid(existing_uids)
        rows[relative] = {
            "uid": uid,
            "name": str(current.get("name") or Path(relative).name),
            "content_type": str(args.content_type),
            "scenario_tags": tags if tags is not None else list(current.get("scenario_tags") or []),
            "relative_path": relative,
            "item_type": str(current.get("item_type") or (Path(relative).suffix.lower().lstrip(".") or "文件")),
            "file_count": int(args.file_count),
        }
        if not args.dry_run:
            写入_items(paths, rows)
            写入关系表(paths, rows)
        print(json.dumps({"upserted": True, "uid": uid, "dry_run": bool(args.dry_run)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "import":
        tags = 解析标签参数(str(args.tags))
        target_paths = 解析路径参数(str(args.paths or ""))
        stats = 导入_items(
            paths,
            tags=tags,
            only_new=bool(args.only_new),
            target_paths=target_paths,
            mode=str(args.mode),
            dry_run=bool(args.dry_run),
        )
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    return 2


def 执行_tags(argv: list[str], paths: 路径配置) -> int:
    """执行 `tags` 子命令。

    Args:
        argv: 参数列表。
        paths: 路径配置。

    Returns:
        int: 退出码。
    """

    parser = argparse.ArgumentParser(description="标签与关系表管理")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-tags", help="列出全部标签")

    get_cmd = sub.add_parser("get-tags", help="获取条目标签")
    get_cmd.add_argument("--item-id", required=True)

    set_cmd = sub.add_parser("set-tags", help="设置条目标签")
    set_cmd.add_argument("--item-id", required=True)
    set_cmd.add_argument("--tags", required=True)
    set_cmd.add_argument("--mode", choices=["replace", "add", "remove"], default="replace")
    set_cmd.add_argument("--dry-run", action="store_true")

    sub.add_parser("export-relation", help="由 items.csv 导出关系表")

    apply_cmd = sub.add_parser("apply-relation", help="由关系表回写 items.csv")
    apply_cmd.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    rows = 读取_items(paths)

    if args.command == "list-tags":
        tags: list[str] = []
        for row in rows.values():
            tags.extend(list(row.get("scenario_tags") or []))
        print(json.dumps({"tags": 规范标签(tags)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "get-tags":
        target = str(args.item_id)
        for relative, row in rows.items():
            if target in {relative, str(row.get("uid") or ""), str(row.get("name") or "")}:
                print(json.dumps({"item_id": target, "tags": 规范标签(list(row.get("scenario_tags") or []))}, ensure_ascii=False, indent=2))
                return 0
        print(f"[ERROR] 未找到条目：{target}", file=sys.stderr)
        return 2

    if args.command == "set-tags":
        target = str(args.item_id)
        target_key = ""
        for relative, row in rows.items():
            if target in {relative, str(row.get("uid") or ""), str(row.get("name") or "")}:
                target_key = relative
                break
        if not target_key:
            print(f"[ERROR] 未找到条目：{target}", file=sys.stderr)
            return 2

        old_tags = 规范标签(list(rows[target_key].get("scenario_tags") or []))
        input_tags = 规范标签([part.strip() for part in str(args.tags).split(",") if part.strip()])
        if args.mode == "replace":
            new_tags = input_tags
        elif args.mode == "add":
            new_tags = 规范标签(old_tags + input_tags)
        else:
            remove_set = set(input_tags)
            new_tags = [tag for tag in old_tags if tag not in remove_set]

        rows[target_key]["scenario_tags"] = new_tags
        if not args.dry_run:
            写入_items(paths, rows)
            写入关系表(paths, rows)

        print(json.dumps({"item_id": target_key, "old": old_tags, "new": new_tags, "dry_run": bool(args.dry_run)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "export-relation":
        写入关系表(paths, rows)
        print(json.dumps({"relation_csv": str(paths.relation_csv), "items_count": len(rows)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "apply-relation":
        mapping = 读取关系表(paths)
        updated = 0
        for relative, row in rows.items():
            uid = str(row.get("uid") or "")
            new_tags = None
            if uid in mapping:
                new_tags = mapping[uid]
            if new_tags is None:
                continue
            old_tags = 规范标签(list(row.get("scenario_tags") or []))
            if old_tags != new_tags:
                rows[relative]["scenario_tags"] = new_tags
                updated += 1

        if not args.dry_run:
            写入_items(paths, rows)
        print(json.dumps({"updated_rows": updated, "dry_run": bool(args.dry_run)}, ensure_ascii=False, indent=2))
        return 0

    return 2


def 执行聚合用户级内容(argv: list[str], paths: 路径配置) -> int:
    """执行用户级内容聚合子命令。"""

    parser = argparse.ArgumentParser(description="按范围聚合当前设备或项目中的 AI 内容到 libs")
    parser.add_argument("--source-path", action="append", default=[], help="可选：显式指定来源路径，可重复传入")
    parser.add_argument("--scope", action="append", default=[], help="可选：自动发现范围，可重复传入 global/system/user/project")
    parser.add_argument("--project-dir", action="append", default=[], help="可选：项目级自动发现根目录，可重复传入")
    parser.add_argument("--home-dir", default="", help="可选：覆盖自动发现使用的用户主目录")
    parser.add_argument("--dry-run", action="store_true", help="仅输出变更预览，不写入磁盘")
    parser.add_argument("--skip-items-sync", action="store_true", help="聚合完成后跳过 items sync")
    parser.add_argument("--simulate-only", action="store_true", help="仅在沙盒副本中执行聚合，不修改真实目录")
    parser.add_argument("--sandbox-dir", default="", help="可选：沙盒根目录；不传则默认使用 Downloads 下的时间戳目录")
    args = parser.parse_args(argv)

    stats = 聚合用户级内容(
        paths,
        source_paths=[str(item).strip() for item in list(args.source_path or []) if str(item).strip()],
        home_dir=str(args.home_dir or "").strip(),
        scopes=[str(item).strip() for item in list(args.scope or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(args.project_dir or []) if str(item).strip()],
        dry_run=bool(args.dry_run),
        sync_items_after=not bool(args.skip_items_sync),
        simulate_only=bool(args.simulate_only),
        sandbox_dir=str(args.sandbox_dir or "").strip(),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def 执行发布用户级内容(argv: list[str], paths: 路径配置) -> int:
    """执行用户级内容发布子命令。"""

    parser = argparse.ArgumentParser(description="按范围把 libs 中的 AI 内容发布到当前设备、项目或显式目标")
    parser.add_argument("--target-path", action="append", default=[], help="可选：显式指定发布目标路径，可重复传入")
    parser.add_argument("--scope", action="append", default=[], help="可选：自动发现范围，可重复传入 global/system/user/project")
    parser.add_argument("--project-dir", action="append", default=[], help="可选：项目级自动发现根目录，可重复传入")
    parser.add_argument("--home-dir", default="", help="可选：覆盖自动发现使用的用户主目录")
    parser.add_argument("--engine", action="append", default=[], help="可选：按 engine_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--ide", action="append", default=[], help="可选：按 ide_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--include-missing", action="store_true", help="自动发现时包含当前尚不存在的候选目标目录")
    parser.add_argument("--dry-run", action="store_true", help="仅输出变更预览，不写入磁盘")
    parser.add_argument("--simulate-only", action="store_true", help="仅在沙盒副本中执行发布，不修改真实目录")
    parser.add_argument("--sandbox-dir", default="", help="可选：沙盒根目录；不传则默认使用 Downloads 下的时间戳目录")
    args = parser.parse_args(argv)

    stats = 发布用户级内容(
        paths,
        target_paths=[str(item).strip() for item in list(args.target_path or []) if str(item).strip()],
        home_dir=str(args.home_dir or "").strip(),
        engine_vendors=[str(item).strip() for item in list(args.engine or []) if str(item).strip()],
        ide_vendors=[str(item).strip() for item in list(args.ide or []) if str(item).strip()],
        include_missing=bool(args.include_missing),
        scopes=[str(item).strip() for item in list(args.scope or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(args.project_dir or []) if str(item).strip()],
        dry_run=bool(args.dry_run),
        simulate_only=bool(args.simulate_only),
        sandbox_dir=str(args.sandbox_dir or "").strip(),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def 执行备份用户级内容(argv: list[str], paths: 路径配置) -> int:
    """执行用户级内容备份子命令。"""

    parser = argparse.ArgumentParser(description="按范围备份当前设备或项目的 AI 内容（libs + 参与目标）")
    parser.add_argument("--target-path", action="append", default=[], help="可选：显式指定备份目标路径，可重复传入")
    parser.add_argument("--scope", action="append", default=[], help="可选：自动发现范围，可重复传入 global/system/user/project")
    parser.add_argument("--project-dir", action="append", default=[], help="可选：项目级自动发现根目录，可重复传入")
    parser.add_argument("--home-dir", default="", help="可选：覆盖自动发现使用的用户主目录")
    parser.add_argument("--engine", action="append", default=[], help="可选：按 engine_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--ide", action="append", default=[], help="可选：按 ide_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--include-missing", action="store_true", help="自动发现时包含当前尚不存在的候选目标目录")
    parser.add_argument("--backup-dir", default="", help="可选：备份根目录，默认使用 autodo-lib/datastore")
    parser.add_argument("--dry-run", action="store_true", help="仅输出备份计划，不写入磁盘")
    args = parser.parse_args(argv)

    stats = 备份用户级内容(
        paths,
        target_paths=[str(item).strip() for item in list(args.target_path or []) if str(item).strip()],
        home_dir=str(args.home_dir or "").strip(),
        engine_vendors=[str(item).strip() for item in list(args.engine or []) if str(item).strip()],
        ide_vendors=[str(item).strip() for item in list(args.ide or []) if str(item).strip()],
        include_missing=bool(args.include_missing),
        backup_dir=str(args.backup_dir or "").strip(),
        scopes=[str(item).strip() for item in list(args.scope or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(args.project_dir or []) if str(item).strip()],
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def 执行更新用户级内容(argv: list[str], paths: 路径配置) -> int:
    """执行用户级内容一键更新子命令。"""

    parser = argparse.ArgumentParser(description="按范围与 logical key + SQLite 元数据基线同步当前设备或项目的 AI 内容")
    parser.add_argument("--target-path", action="append", default=[], help="可选：显式指定同步参与目标路径，可重复传入")
    parser.add_argument("--scope", action="append", default=[], help="可选：自动发现范围，可重复传入 global/system/user/project")
    parser.add_argument("--project-dir", action="append", default=[], help="可选：项目级自动发现根目录，可重复传入")
    parser.add_argument("--home-dir", default="", help="可选：覆盖自动发现使用的用户主目录")
    parser.add_argument("--engine", action="append", default=[], help="可选：按 engine_vendor 过滤自动发现的同步参与方，可重复传入")
    parser.add_argument("--ide", action="append", default=[], help="可选：按 ide_vendor 过滤自动发现的同步参与方，可重复传入")
    parser.add_argument("--include-missing", action="store_true", help="自动发现时包含当前尚不存在的候选目标目录")
    parser.add_argument("--backup-dir", default="", help="可选：备份根目录，默认使用 autodo-lib/datastore")
    parser.add_argument("--dry-run", action="store_true", help="仅输出变更预览，不写入磁盘")
    parser.add_argument("--skip-backup", action="store_true", help="更新开始前跳过自动备份")
    parser.add_argument("--skip-items-sync", action="store_true", help="更新完成后跳过 items sync")
    parser.add_argument("--simulate-only", action="store_true", help="仅在沙盒副本中执行同步，不修改真实目录")
    parser.add_argument("--sandbox-dir", default="", help="可选：沙盒根目录；不传则默认使用 Downloads 下的时间戳目录")
    args = parser.parse_args(argv)

    stats = 更新用户级内容(
        paths,
        target_paths=[str(item).strip() for item in list(args.target_path or []) if str(item).strip()],
        home_dir=str(args.home_dir or "").strip(),
        engine_vendors=[str(item).strip() for item in list(args.engine or []) if str(item).strip()],
        ide_vendors=[str(item).strip() for item in list(args.ide or []) if str(item).strip()],
        include_missing=bool(args.include_missing),
        scopes=[str(item).strip() for item in list(args.scope or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(args.project_dir or []) if str(item).strip()],
        dry_run=bool(args.dry_run),
        sync_items_after=not bool(args.skip_items_sync),
        backup_before_sync=not bool(args.skip_backup),
        backup_dir=str(args.backup_dir or "").strip(),
        simulate_only=bool(args.simulate_only),
        sandbox_dir=str(args.sandbox_dir or "").strip(),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def 构建解析器() -> argparse.ArgumentParser:
    """构建顶层解析器。

    Returns:
        argparse.ArgumentParser: 顶层解析器。
    """

    parser = argparse.ArgumentParser(description="本地库管理统一入口")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("items", help="条目清单同步与 CRUD")
    sub.add_parser("tags", help="标签与关系表管理")
    sub.add_parser("aggregate-user-content", help="按范围聚合当前设备或项目 AI 内容到 libs")
    sub.add_parser("publish-user-content", help="按范围把 libs 中的 AI 内容发布到当前设备、项目或显式目标")
    sub.add_parser("backup-user-content", help="按范围备份当前设备或项目 AI 内容（libs + 参与目标）")
    sub.add_parser("update-user-content", help="按范围执行 参与方反编译 -> logical key 决策 -> canonical 回写 -> 定向发布 的同步")
    return parser


def main() -> int:
    """程序主入口。

    Returns:
        int: 退出码。
    """

    paths = 默认路径()
    parser = 构建解析器()
    args, passthrough = parser.parse_known_args()

    try:
        if args.command == "items":
            return 执行_items(list(passthrough), paths)
        if args.command == "tags":
            return 执行_tags(list(passthrough), paths)
        if args.command == "aggregate-user-content":
            return 执行聚合用户级内容(list(passthrough), paths)
        if args.command == "publish-user-content":
            return 执行发布用户级内容(list(passthrough), paths)
        if args.command == "backup-user-content":
            return 执行备份用户级内容(list(passthrough), paths)
        if args.command == "update-user-content":
            return 执行更新用户级内容(list(passthrough), paths)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
