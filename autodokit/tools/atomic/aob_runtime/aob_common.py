#!/usr/bin/env python3
"""AOB 用户级内容治理 — 共享基础设施。

本模块从 library_tool.py 拆分出所有子命令共用的常量、数据类、
工具函数、AOL 运行时桥接、SQLite 注册表等。
其他原子模块（aob_aggregate、aob_publish、aob_backup、aob_update）均依赖本模块。
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
    ".cursor",
    ".lingma",
    ".qoder",
    ".qwen",
    ".agents",
]

# 用户级 structured_root 路径片段映射。
# 键为 target_label，值为相对于用户主目录的路径片段元组。
# 未在此表中列出的 target 仍按 `~/.<target_label>` 回退解析。
默认用户级路径片段映射: dict[str, tuple[str, ...]] = {
    "opencode": (".config", "opencode"),
    "zed": (".agents",),
    "opencode_zed": (".agents",),
}

默认提示词目录候选 = [
    ("Code", "User", "prompts"),
    ("Cursor", "User", "prompts"),
    ("Lingma", "User", "prompts"),
]

# macOS 提示词目录候选（相对于用户主目录）
默认macOS提示词目录候选 = [
    ("Library", "Application Support", "Code", "User", "prompts"),
    ("Library", "Application Support", "Cursor", "User", "prompts"),
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
    {"folder_name": ".cursor", "target_label": "cursor", "layout": "structured_root", "engine_vendor": "claude", "ide_vendor": "cursor", "scope": "user"},
    {"folder_name": ".lingma", "target_label": "lingma", "layout": "structured_root", "engine_vendor": "lingma", "ide_vendor": "lingma", "scope": "user"},
    {"folder_name": ".qoder", "target_label": "qoder", "layout": "structured_root", "engine_vendor": "qoder", "ide_vendor": "qoder", "scope": "user"},
    {"folder_name": ".qwen", "target_label": "qwen", "layout": "structured_root", "engine_vendor": "qwen", "ide_vendor": "qwen", "scope": "user"},
    # opencode 使用路径片段映射（~/.config/opencode）
    {"path_parts": (".config", "opencode"), "target_label": "opencode", "layout": "structured_root", "engine_vendor": "opencode", "ide_vendor": "opencode", "scope": "user"},
    # zed 使用路径片段映射（~/.agents）
    {"path_parts": (".agents",), "target_label": "zed", "layout": "structured_root", "engine_vendor": "zed", "ide_vendor": "zed", "scope": "user"},
    # opencode_zed 组合（engine=opencode, ide=zed）- 待核验，暂用 ~/.agents
    {"path_parts": (".agents",), "target_label": "opencode_zed", "layout": "structured_root", "engine_vendor": "opencode", "ide_vendor": "zed", "scope": "user"},
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

同步撤销会话表名 = "sync_undo_sessions"
同步撤销变更表名 = "sync_undo_file_changes"
同步撤销数据库文件名 = "sync_undo.sqlite3"

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


def 计算沙盒镜像相对路径(*, real_path: Path, home_dir: str = "") -> Path:
    """把真实内容路径映射为沙盒内的镜像相对路径。

    映射目标：让沙盒目录结构尽量复刻真实结构，便于“假装是各个同步文件夹”。
    例如：
    - 用户级 `C:/Users/Ethan/.copilot/agents` -> `.copilot/agents`
    - 用户 prompts `~/AppData/Roaming/Code/User/prompts` -> `AppData/Roaming/Code/User/prompts`
    - 主目录之外的绝对路径，按盘符或根做去敏后的镜像，避免不同来源相互覆盖。

    Args:
        real_path: 真实内容路径（目标或来源容器根）。
        home_dir: 可选用户主目录，用于解析用户级镜像基准。

    Returns:
        Path: 相对沙盒根目录的镜像相对路径。
    """

    resolved = real_path.expanduser().resolve()
    home = 用户主目录(home_dir)

    if resolved == home:
        return Path(".")
    if 路径在目录内(resolved, home):
        return Path(resolved.relative_to(home))

    # 主目录之外：按盘符/根做去敏镜像，保留原始目录层级。
    drive = resolved.drive  # 形如 "C:"
    if drive:
        drive_token = f"_drive_{drive.rstrip(':').lower()}"
        tail = resolved.relative_to(Path(drive + "\\")) if resolved.is_absolute() else Path(resolved.name)
        return Path(drive_token) / tail

    anchor = resolved.anchor or "/"
    tail = resolved.relative_to(anchor) if resolved.is_absolute() else Path(resolved.name)
    return Path("_root") / tail


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


def 解析用户级聚合路径(home: Path, folder_name: str) -> tuple[Path, str, str]:
    """根据文件夹名解析用户级聚合路径与引擎/IDE 供应商。

    优先使用 `默认用户级路径片段映射` 中的映射；未命中时回退到 `~/.<folder_name>`。

    Args:
        home: 用户主目录。
        folder_name: 聚合根目录名（如 `.opencode`、`.agents`）。

    Returns:
        tuple[Path, str, str]: (source_path, engine_vendor, ide_vendor)
    """

    vendor = folder_name.lstrip(".").lower()

    # 特殊映射：cursor 使用 claude 引擎
    if vendor == "cursor":
        engine_vendor = "claude"
        ide_vendor = "cursor"
    # 特殊映射：.agents 目录对应 zed（原生 Agent）
    elif vendor == "agents":
        engine_vendor = "zed"
        ide_vendor = "zed"
    else:
        engine_vendor = vendor
        ide_vendor = vendor

    # 检查是否有路径片段映射
    target_label = vendor if vendor != "agents" else "zed"
    if target_label in 默认用户级路径片段映射:
        parts = 默认用户级路径片段映射[target_label]
        source_path = home.joinpath(*parts)
    else:
        source_path = home / folder_name

    return source_path, engine_vendor, ide_vendor


def 发现用户级聚合来源(*, home_dir: str = "") -> list[聚合来源]:
    """自动发现当前用户的 AI 内容来源目录。"""

    home = 用户主目录(home_dir)
    roaming_root = APPDATA根目录(home_dir)
    candidates: list[聚合来源] = []

    for folder_name in 默认用户级聚合根目录:
        source_path, engine_vendor, ide_vendor = 解析用户级聚合路径(home, folder_name)
        label = folder_name.lstrip(".")
        # .agents 目录的标签使用 zed
        if label == "agents":
            label = "zed"
        candidates.append(
            聚合来源(
                source_path=source_path,
                source_label=规范来源标签(label),
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
        # 支持 path_parts 字段（优先）或 folder_name 字段
        if "path_parts" in item:
            target_path = home.joinpath(*tuple(item["path_parts"]))
        else:
            target_path = home / str(item["folder_name"])
        
        target = 发布目标(
            target_path=target_path,
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


def 同步撤销数据库路径(paths: 路径配置) -> Path:
    """获取同步撤销数据库路径。"""

    return paths.db_root / 同步撤销数据库文件名


def 初始化同步撤销数据库(db_path: Path) -> sqlite3.Connection:
    """初始化同步撤销数据库并确保表结构存在。

    Args:
        db_path: 数据库文件路径。

    Returns:
        sqlite3.Connection: 已就绪的数据库连接。
    """

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS {同步撤销会话表名} (
            session_id TEXT PRIMARY KEY,
            started_at REAL NOT NULL,
            completed_at REAL,
            sync_type TEXT NOT NULL,
            dry_run INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            metadata_json TEXT
        );

        CREATE TABLE IF NOT EXISTS {同步撤销变更表名} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES {同步撤销会话表名}(session_id),
            change_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            target_label TEXT NOT NULL DEFAULT '',
            backup_content BLOB,
            post_content_hash TEXT NOT NULL DEFAULT '',
            rolled_back INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_undo_session
            ON {同步撤销变更表名}(session_id, rolled_back);
        """
    )
    conn.commit()
    return conn


def 记录同步撤销会话开始(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    sync_type: str,
    dry_run: bool,
    metadata: dict[str, Any] | None = None,
) -> None:
    """记录同步撤销会话开始。"""

    now_ts = float(time.time())
    conn.execute(
        f"""
        INSERT OR REPLACE INTO {同步撤销会话表名}
        (session_id, started_at, sync_type, dry_run, status, metadata_json)
        VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (session_id, now_ts, sync_type, 1 if dry_run else 0, json.dumps(metadata or {}, ensure_ascii=False)),
    )
    conn.commit()


def 记录撤销文件变更(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    change_type: str,
    file_path: str,
    target_label: str,
    backup_content: bytes | None = None,
    post_content_hash: str = "",
) -> None:
    """记录单条文件变更用于撤销。

    Args:
        conn: 数据库连接。
        session_id: 会话 ID。
        change_type: 变更类型（added/modified/deleted）。
        file_path: 文件绝对路径。
        target_label: 目标标签。
        backup_content: 修改或删除前的原始文件内容。
        post_content_hash: 操作后内容的 SHA256。
    """

    now_ts = float(time.time())
    conn.execute(
        f"""
        INSERT INTO {同步撤销变更表名}
        (session_id, change_type, file_path, target_label, backup_content, post_content_hash, rolled_back, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (session_id, change_type, file_path, target_label, backup_content, post_content_hash, now_ts),
    )


def 记录同步撤销会话完成(conn: sqlite3.Connection, *, session_id: str, status: str = "completed") -> None:
    """标记同步撤销会话完成。"""

    now_ts = float(time.time())
    conn.execute(
        f"UPDATE {同步撤销会话表名} SET completed_at=?, status=? WHERE session_id=?",
        (now_ts, status, session_id),
    )
    conn.commit()


def 计算文件_sha256(file_path: Path) -> str:
    """计算文件 SHA256 摘要。"""

    if not file_path.exists() or not file_path.is_file():
        return ""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def 读取文件原始内容(file_path: Path) -> bytes | None:
    """读取文件原始字节内容。"""

    if not file_path.exists() or not file_path.is_file():
        return None
    return file_path.read_bytes()


def 执行同步撤销(
    db_path: Path,
    *,
    session_id: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """执行指定会话的同步撤销（幂等）。

    撤销逻辑：
    - added 文件 -> 删除（仅当内容 hash 匹配时）
    - modified 文件 -> 用 backup_content 恢复
    - deleted 文件 -> 用 backup_content 重建

    Args:
        db_path: 撤销数据库路径。
        session_id: 要撤销的会话 ID。
        dry_run: 是否仅预览不执行。

    Returns:
        dict[str, Any]: 撤销结果摘要。
    """

    if not db_path.exists():
        return {"status": "FAIL", "error": f"撤销数据库不存在：{db_path}"}

    with sqlite3.connect(str(db_path)) as conn:
        session_row = conn.execute(
            f"SELECT session_id, status, dry_run, sync_type FROM {同步撤销会话表名} WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if session_row is None:
            return {"status": "FAIL", "error": f"会话不存在：{session_id}"}

        session_status = str(session_row[1])
        if session_status == "rolled_back":
            return {"status": "PASS", "message": f"会话 {session_id} 已经撤销过，幂等跳过", "idempotent": True}

        changes = conn.execute(
            f"""SELECT id, change_type, file_path, target_label, backup_content, post_content_hash, rolled_back
            FROM {同步撤销变更表名}
            WHERE session_id=? AND rolled_back=0
            ORDER BY id DESC""",
            (session_id,),
        ).fetchall()

        result_summary = {
            "session_id": session_id,
            "dry_run": dry_run,
            "total_pending": len(changes),
            "restored": 0,
            "deleted": 0,
            "skipped": 0,
            "errors": [],
            "changes": [],
        }

        for row in changes:
            row_id, change_type, file_path, target_label, backup_content, post_hash, rolled_back = row
            file_obj = Path(file_path)
            change_record = {
                "id": row_id,
                "change_type": change_type,
                "file_path": file_path,
                "target_label": target_label,
                "action": "",
            }

            if change_type == "added":
                if file_obj.exists() and file_obj.is_file():
                    current_hash = 计算文件_sha256(file_obj)
                    if post_hash and current_hash != post_hash:
                        change_record["action"] = "skipped_hash_mismatch"
                        result_summary["skipped"] += 1
                        result_summary["errors"].append(f"文件内容已变更，跳过删除：{file_path}")
                    else:
                        if not dry_run:
                            file_obj.unlink()
                        change_record["action"] = "deleted" if not dry_run else "would_delete"
                        result_summary["deleted"] += 1
                else:
                    change_record["action"] = "skipped_not_found"
                    result_summary["skipped"] += 1

            elif change_type == "modified":
                if backup_content is not None:
                    if not dry_run:
                        file_obj.parent.mkdir(parents=True, exist_ok=True)
                        file_obj.write_bytes(backup_content)
                    change_record["action"] = "restored" if not dry_run else "would_restore"
                    result_summary["restored"] += 1
                else:
                    change_record["action"] = "skipped_no_backup"
                    result_summary["errors"].append(f"缺少备份内容，无法恢复：{file_path}")
                    result_summary["skipped"] += 1

            elif change_type == "deleted":
                if backup_content is not None:
                    if not dry_run:
                        file_obj.parent.mkdir(parents=True, exist_ok=True)
                        file_obj.write_bytes(backup_content)
                    change_record["action"] = "restored" if not dry_run else "would_restore"
                    result_summary["restored"] += 1
                else:
                    change_record["action"] = "skipped_no_backup"
                    result_summary["errors"].append(f"缺少备份内容，无法重建：{file_path}")
                    result_summary["skipped"] += 1

            result_summary["changes"].append(change_record)
            if not dry_run:
                conn.execute(
                    f"UPDATE {同步撤销变更表名} SET rolled_back=1 WHERE id=?",
                    (row_id,),
                )

        if not dry_run:
            记录同步撤销会话完成(conn, session_id=session_id, status="rolled_back")
            result_summary["status"] = "PASS"
        else:
            result_summary["status"] = "DRY_RUN"

    return result_summary


# 旧同步 bug 污染产生的 vendor 后缀模式（不应出现在 logical key 中）
_旧同步污染后缀: tuple[str, ...] = (
    "-claude", "-codex", "-copilot", "-cursor",
    "-gemini", "-lingma", "-qoder", "-qwen",
    "-opencode",
)

_旧同步数字后缀重复 = re.compile(r"^(.+)-(\d+)$")


def 是否旧同步污染key(
    logical_key: str,
    *,
    all_known_keys: set[str] | None = None,
    all_entries: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """判断 logical key 是否为旧同步 bug 产生的污染 key。

    污染类型：
    1. vendor 后缀：agents::agent-xxx-claude
    2. 数字后缀重复：agents::agent-xxx-2（base key 存在且内容相同时）
    """

    parts = logical_key.split("::", 1)
    if len(parts) < 2:
        return False
    prefix = parts[0]
    key_id = parts[1]

    # vendor 后缀
    if any(key_id.endswith(suffix) for suffix in _旧同步污染后缀):
        return True

    # 数字后缀重复：仅当 base key 存在且内容相同时才算污染
    if all_known_keys is not None:
        m = _旧同步数字后缀重复.match(key_id)
        if m:
            base_id = m.group(1)
            num = int(m.group(2))
            if num >= 2:
                base_key = f"{prefix}::{base_id}"
                if base_key in all_known_keys:
                    # 内容验证：仅当内容与 base 相同时才过滤
                    if all_entries is not None:
                        dup_content = str(all_entries.get(logical_key, {}).get("content", ""))
                        base_content = str(all_entries.get(base_key, {}).get("content", ""))
                        if dup_content == base_content:
                            return True
                    else:
                        return True

    return False


def 过滤旧同步污染条目(
    side_entries: dict[str, dict[str, dict[str, Any]]],
) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, int]]:
    """过滤所有侧中的旧同步污染条目。

    污染类型：
    - vendor 后缀：agent-xxx-claude（不应存在）
    - 数字后缀重复：agent-xxx-2 / agent-xxx-3（旧同步冲突解决产物）

    Returns:
        (cleaned_entries, filter_stats)
    """

    # 先收集所有已知 key 和 entries（用于检测数字后缀重复）
    all_keys: set[str] = set()
    all_entries_merged: dict[str, dict[str, Any]] = {}
    for entries in side_entries.values():
        all_keys.update(entries.keys())
        for k, v in entries.items():
            if k not in all_entries_merged:
                all_entries_merged[k] = v

    cleaned_entries: dict[str, dict[str, dict[str, Any]]] = {}
    total_removed = 0
    per_side: dict[str, int] = {}
    for side_id, entries in side_entries.items():
        cleaned: dict[str, dict[str, Any]] = {}
        removed = 0
        for key, entry in entries.items():
            if 是否旧同步污染key(key, all_known_keys=all_keys, all_entries=all_entries_merged):
                removed += 1
            else:
                cleaned[key] = entry
        cleaned_entries[side_id] = cleaned
        if removed > 0:
            per_side[side_id] = removed
        total_removed += removed

    return cleaned_entries, {"removed": total_removed, "per_side": per_side}


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
        key_has_registry = False
        # 第一轮：计算每个 side 的 changed_at，并区分 present / absent。
        present_candidates: list[tuple[str, float]] = []   # (side_id, changed_at)
        absent_candidates: list[tuple[str, float]] = []    # (side_id, changed_at)

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

            # 判断该 side 是否曾经真实拥有过此 key（区分"天然缺席"与"已删除"）。
            previously_existed = previous is not None and int(previous.get("exists_flag", 0)) == 1

            if previous and int(previous.get("exists_flag", 0)) == exists_flag and str(previous.get("value_hash") or "") == value_hash:
                changed_at = float(previous.get("changed_at_epoch", 0.0) or 0.0)
                registry_hit_count += 1
                # 即使注册表命中，若供应商始终未拥有此 key，也不应参与胜出。
                if exists_flag == 0 and not previously_existed:
                    changed_at = 0.0
            else:
                if exists_flag == 0 and not previously_existed:
                    # 供应商当前缺席且从未拥有过此 key：不应参与胜出比较，
                    # 避免目录 mtime 或脏注册表冒充"变更信号"压过真实存在内容。
                    changed_at = 0.0
                elif observe_at > 0:
                    changed_at = float(observe_at)
                else:
                    # 对有历史基线的缺席或无观测新增，回退为当前决策时刻。
                    changed_at = decision_now

            updated_at = max(observe_at, decision_now)
            registry_rows.append((logical_key, side_id, exists_flag, value_hash, changed_at, updated_at))

            if exists_flag == 1:
                present_candidates.append((side_id, changed_at))
            else:
                absent_candidates.append((side_id, changed_at))

        if not key_has_registry:
            fallback_count += 1

        # 第二轮：选出胜出 side。
        # 核心规则：当前存在（presence）永远优先于当前缺席（absence）。
        # 只要有任何 side 当前拥有此 key，就在 present 中选最新的；
        # 仅当所有 side 都缺席时（全部删除），才在 absent 中选最新的。
        winner_side = ""
        winner_changed_at = -1.0
        winner_exists = False

        if present_candidates:
            for side_id, changed_at in present_candidates:
                if changed_at > winner_changed_at:
                    winner_side = side_id
                    winner_changed_at = changed_at
                    winner_exists = True
                elif changed_at == winner_changed_at and ranked.get(side_id, 9999) < ranked.get(winner_side, 9999):
                    winner_side = side_id
                    winner_changed_at = changed_at
                    winner_exists = True
        else:
            # 所有 side 均缺席：选最新的缺席信号（用于传播真正删除）。
            for side_id, changed_at in absent_candidates:
                if changed_at > winner_changed_at:
                    winner_side = side_id
                    winner_changed_at = changed_at
                    winner_exists = False
                elif changed_at == winner_changed_at and ranked.get(side_id, 9999) < ranked.get(winner_side, 9999):
                    winner_side = side_id
                    winner_changed_at = changed_at
                    winner_exists = False

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


def 删除目标过期托管文件(*, target: 发布目标, stale_files: set[str], dry_run: bool, stats: dict[str, Any], journal: Any = None) -> None:
    """删除目标中过期托管文件。"""

    for relative_path in sorted({规范路径(item) for item in stale_files if 规范路径(item)}):
        target_file = (target.target_path / Path(relative_path)).resolve()
        if not target_file.exists() or not target_file.is_file():
            continue
        stats["deleted"] += 1
        stats["touched_paths"].append(str(target_file))
        if dry_run:
            continue
        if journal is not None:
            journal.记录将删除(target_file)
        target_file.unlink()
        if 路径在目录内(target_file.parent, target.target_path):
            清理空目录到根(start_dir=target_file.parent, root_dir=target.target_path)


# 托管目录模式：每个目录对应的文件 glob 模式
_托管目录扫描模式: dict[str, list[str]] = {
    "agents": ["*.md", "*.agent.md"],
    "skills": ["**/SKILL.md", "*.md"],
    "rules": ["*.md"],
    "commands": ["*.md"],
    "hooks": ["*.md", "*.json", "*.yaml", "*.yml"],
}


def 清理目标未跟踪文件(
    *,
    target: 发布目标,
    managed_files: set[str],
    dry_run: bool,
    stats: dict[str, Any],
    journal: Any = None,
) -> int:
    """清理目标目录中不在 managed_files 中的未跟踪文件。

    仅扫描已知的托管目录（agents/, skills/, rules/ 等），
    删除不在编译输出中的残留文件。

    Returns:
        删除的文件数。
    """

    deleted = 0
    target_root = target.target_path.resolve()
    if not target_root.exists():
        return 0

    for subdir_name in _托管目录扫描模式:
        subdir = target_root / subdir_name
        if not subdir.exists() or not subdir.is_dir():
            continue
        for file_path in sorted(subdir.rglob("*")):
            if not file_path.is_file():
                continue
            rel = 规范路径(str(file_path.relative_to(target_root)))
            if rel in managed_files:
                continue
            # 该文件不在编译输出中，删除
            deleted += 1
            stats["deleted"] += 1
            stats.setdefault("cleanup_unknown_files", []).append(rel)
            stats["touched_paths"].append(str(file_path))
            if dry_run:
                continue
            if journal is not None:
                journal.记录将删除(file_path)
            file_path.unlink()
            if 路径在目录内(file_path.parent, target_root):
                清理空目录到根(start_dir=file_path.parent, root_dir=target_root)

    return deleted


