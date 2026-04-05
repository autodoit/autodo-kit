#!/usr/bin/env python3
"""部署安装统一入口。

本脚本仅保留一个文件作为“部署安装”功能入口，提供以下子命令：
- workflow：按工作流部署到目标项目。
- extras-bundle：打包扩展包为离线 zip。
- workspace-convert：在模板项目内执行办公区跨引擎转换流程。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .aoc_tool import (
        读取引擎办公区目录名,
        从引擎办公区构建_aol,
        从libs构建_aol,
        收集_opencode阻断错误,
        校验_aol,
        编译_aol到引擎办公区,
        编译到_claude,
        编译到_copilot,
        编译到_opencode,
    )
except Exception:  # pragma: no cover
    读取引擎办公区目录名 = None
    从引擎办公区构建_aol = None
    编译_aol到引擎办公区 = None
    收集_opencode阻断错误 = None
    校验_aol = None
    编译到_claude = None
    编译到_copilot = None
    编译到_opencode = None
    从libs构建_aol = None


@dataclass(frozen=True)
class 工作流规格:
    """工作流规格。

    Args:
        workflow_id: 工作流标识。
    """

    workflow_id: str


@dataclass(frozen=True)
class 引擎规格:
    """引擎规格。

    Args:
        engine_id: 引擎标识。
        模板目录: 引擎模板目录路径。
        引擎根目录名: 目标项目内引擎根目录名。
    """

    engine_id: str
    模板目录: Path
    引擎根目录名: str


@dataclass(frozen=True)
class 安装目标:
    """安装目标规格。

    Args:
        项目根目录: 解析后的项目根目录。
        项目名: 解析后的项目名称。
        部署模式: `new` 或 `existing`。
    """

    项目根目录: Path
    项目名: str
    部署模式: str


@dataclass(frozen=True)
class Git初始化配置:
    """Git 初始化配置。

    Args:
        启用: 是否执行 `git init`。
        默认分支: 初始化时的分支名。
        写入_gitignore: 是否写入 `.gitignore`。
        gitignore_content: `.gitignore` 内容。
        写入_gitattributes: 是否写入 `.gitattributes`。
        gitattributes_content: `.gitattributes` 内容。
        创建初始提交: 是否创建初始提交。
    """

    启用: bool
    默认分支: str
    写入_gitignore: bool
    gitignore_content: str
    写入_gitattributes: bool
    gitattributes_content: str
    创建初始提交: bool


默认支持标签 = ["学术研究", "文档管理", "软件开发"]
标签场景目录映射 = {
    "学术研究": "通用学术研究工作流",
    "文档管理": "通用文档管理工作流",
    "软件开发": "通用软件开发工作流",
}

默认_gitignore模板 = """# ===== 系统与编辑器 =====
.DS_Store
Thumbs.db
.vscode/
.idea/

# ===== Python =====
__pycache__/
*.py[cod]
*.pyo
*.pyd
.venv/
venv/

# ===== Node.js =====
node_modules/

# ===== 日志与缓存 =====
*.log
*.tmp
*.temp

# ===== 密钥与本地私密配置 =====
.env
.env.*
*.pem
*.key
*api_key*.txt
*bailian_api_key*.txt
.autodo/private/
"""

默认_gitattributes模板 = """* text=auto eol=lf
*.bat text eol=crlf
*.cmd text eol=crlf
*.ps1 text eol=crlf
*.sh text eol=lf
*.py text eol=lf
*.md text eol=lf
"""


def 仓库根目录() -> Path:
    """获取仓库根目录。

    Returns:
        Path: 仓库根目录。
    """

    env_root = str(os.environ.get("AOB_REPO_ROOT", "")).strip()
    if env_root:
        return Path(env_root).resolve()

    kit_root = Path(__file__).resolve().parents[4]
    sibling_aob = kit_root.parent / "autodo-lib"
    if sibling_aob.exists():
        return sibling_aob.resolve()
    return kit_root


def 读取引擎配置数据库(root: Path) -> dict[str, Any]:
    """读取引擎配置数据库。

    Args:
        root: 仓库根目录。

    Returns:
        dict[str, Any]: 引擎配置数据库。
    """

    db_path = root / "database" / "engine_config_profiles.json"
    if not db_path.exists():
        return {
            "schema_version": 1,
            "supported_tags": list(默认支持标签),
            "engines": {},
        }

    payload = json.loads(db_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"引擎配置数据库格式错误：{db_path}")
    if not isinstance(payload.get("engines"), dict):
        raise SystemExit(f"引擎配置数据库缺少 engines：{db_path}")
    if not isinstance(payload.get("supported_tags", []), list):
        raise SystemExit(f"引擎配置数据库 supported_tags 格式错误：{db_path}")
    return payload


def 解析标签参数(*, raw_tags: str, supported_tags: list[str]) -> list[str]:
    """解析并校验标签参数。

    Args:
        raw_tags: 原始标签参数，逗号分隔。
        supported_tags: 支持的标签列表。

    Returns:
        list[str]: 解析后的标签列表。

    Raises:
        SystemExit: 包含不支持的标签时抛出。
    """

    raw = str(raw_tags or "").strip()
    if not raw:
        return []

    ordered: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        tag = token.strip()
        if tag and tag not in seen:
            seen.add(tag)
            ordered.append(tag)

    invalid = [tag for tag in ordered if tag not in set(supported_tags)]
    if invalid:
        raise SystemExit(f"--tags 含不支持标签：{invalid}，支持值：{supported_tags}")
    return ordered


def 读取条目标签映射(root: Path) -> dict[str, set[str]]:
    """读取条目到标签的映射。

    Args:
        root: 仓库根目录。

    Returns:
        dict[str, set[str]]: `relative_path -> tags` 映射。
    """

    items_csv = root / "database" / "items.csv"
    if not items_csv.exists():
        return {}

    result: dict[str, set[str]] = {}
    with items_csv.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            relative_path = str(row.get("relative_path") or "").strip().replace("\\", "/")
            tags_cell = str(row.get("scenario_tags") or "").strip()
            tags = {part.strip() for part in tags_cell.split(",") if part.strip()}
            if relative_path:
                result[relative_path] = tags
    return result


def 构建标签过滤libs视图(*, root: Path, selected_tags: list[str], output_libs_root: Path) -> dict[str, int]:
    """按标签构建临时 libs 视图。

    Args:
        root: 仓库根目录。
        selected_tags: 目标标签列表。
        output_libs_root: 临时 libs 输出目录。

    Returns:
        dict[str, int]: 构建统计信息。
    """

    src_libs = root / "libs"
    item_tags = 读取条目标签映射(root)
    selected_tag_set = set(selected_tags)
    copied_files = 0
    copied_dirs = 0

    for relative_path, tags in item_tags.items():
        if not relative_path.startswith("libs/"):
            continue
        if not (tags & selected_tag_set):
            continue

        source_path = root / relative_path
        if not source_path.exists():
            continue

        sub_rel = Path(relative_path).relative_to("libs")
        target_path = output_libs_root / sub_rel
        if source_path.is_dir():
            shutil.copytree(source_path, target_path, dirs_exist_ok=True)
            copied_dirs += 1
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            copied_files += 1

    for top_name in ["agents", "skills", "rules"]:
        (output_libs_root / top_name).mkdir(parents=True, exist_ok=True)

    return {
        "selected_tags": len(selected_tags),
        "copied_dirs": copied_dirs,
        "copied_files": copied_files,
        "source_libs_exists": int(src_libs.exists()),
    }


def 读取前言颜色(file_path: Path) -> str | None:
    """读取 Markdown front-matter 中的 `color`。

    Args:
        file_path: Markdown 文件路径。

    Returns:
        str | None: 颜色值或 `None`。
    """

    text = file_path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    front_matter = parts[1]
    for line in front_matter.splitlines():
        if line.strip().startswith("color:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return None


def 工作流映射(root: Path) -> dict[str, 工作流规格]:
    """获取工作流映射。

    Args:
        root: 仓库根目录。

    Returns:
        dict[str, 工作流规格]: 工作流映射表。
    """

    _ = root
    return {
        "academic": 工作流规格("academic"),
        "documentation": 工作流规格("documentation"),
        "software": 工作流规格("software"),
    }


def 引擎映射(root: Path) -> dict[str, 引擎规格]:
    """获取引擎映射。

    Args:
        root: 仓库根目录。

    Returns:
        dict[str, 引擎规格]: 引擎映射表。
    """

    templates = root / "engine_shell_templates"
    return {
        "claude": 引擎规格("claude", templates / "claude" / ".claude", ".claude"),
        "opencode": 引擎规格("opencode", templates / "opencode" / ".opencode", ".opencode"),
        "copilot": 引擎规格("copilot", templates / "copilot" / ".copilot", ".copilot"),
        "custom": 引擎规格("custom", templates / "custom" / ".engine", ".engine"),
    }


def 解析安装目标(*, target: str, project_name: str | None) -> 安装目标:
    """解析安装目标并自动判定新旧项目。

    Args:
        target: `--target` 原始值。
        project_name: `--project-name` 可选值。

    Returns:
        安装目标: 解析结果。

    Raises:
        SystemExit: 目标存在但不是目录时抛出。
    """

    target_path = Path(target).expanduser().resolve()
    if project_name:
        项目根目录 = target_path / project_name
        项目名 = project_name
    else:
        项目根目录 = target_path
        项目名 = 项目根目录.name

    if 项目根目录.exists() and not 项目根目录.is_dir():
        raise SystemExit(f"目标路径存在但不是目录：{项目根目录}")

    部署模式 = "existing" if 项目根目录.exists() else "new"
    return 安装目标(项目根目录=项目根目录, 项目名=项目名, 部署模式=部署模式)


def 生成时间戳() -> str:
    """生成备份时间戳。

    Returns:
        str: 时间戳字符串。
    """

    return datetime.now().strftime("%Y%m%d-%H%M%S")


def 确保目录(path: Path, *, dry_run: bool) -> None:
    """确保目录存在。

    Args:
        path: 目录路径。
        dry_run: 是否预演。
    """

    if dry_run:
        return
    path.mkdir(parents=True, exist_ok=True)


def 冲突处理(*, existing: Path, target_root: Path, on_conflict: str, dry_run: bool) -> bool:
    """处理目标路径冲突。

    Args:
        existing: 已存在路径。
        target_root: 目标项目根目录。
        on_conflict: 冲突策略。
        dry_run: 是否预演。

    Returns:
        bool: 是否允许继续写入。
    """

    if on_conflict == "skip":
        print(f"[SKIP] 目标已存在：{existing}")
        return False

    if on_conflict == "overwrite":
        print(f"[OVERWRITE] {existing}")
        if dry_run:
            return True
        if existing.is_dir():
            shutil.rmtree(existing)
        else:
            existing.unlink()
        return True

    if on_conflict == "backup":
        rel = existing.relative_to(target_root)
        backup = target_root / ".autodo" / "backups" / 生成时间戳() / rel
        print(f"[BACKUP] {existing} -> {backup}")
        if dry_run:
            return True
        backup.parent.mkdir(parents=True, exist_ok=True)
        if existing.is_dir():
            shutil.copytree(existing, backup, dirs_exist_ok=True)
            shutil.rmtree(existing)
        else:
            shutil.copy2(existing, backup)
            existing.unlink()
        return True

    raise ValueError(f"未知冲突策略：{on_conflict}")


def 合并目录(*, src: Path, dst: Path, target_root: Path, on_conflict: str, dry_run: bool, clean_target: bool) -> None:
    """将源目录合并到目标目录。

    Args:
        src: 源目录。
        dst: 目标目录。
        target_root: 目标项目根目录。
        on_conflict: 冲突策略。
        dry_run: 是否预演。
        clean_target: 是否先清空目标目录。
    """

    if not src.exists() or not src.is_dir():
        print(f"[SKIP] 源目录不存在：{src}")
        return

    print(f"[SYNC] {src} -> {dst}")
    if clean_target and dst.exists():
        print(f"[CLEAN] {dst}")
        if not dry_run:
            shutil.rmtree(dst)

    if dry_run:
        return

    dst.mkdir(parents=True, exist_ok=True)
    for child in sorted(src.iterdir()):
        target = dst / child.name
        if child.is_dir():
            if target.exists() and target.is_file():
                if not 冲突处理(existing=target, target_root=target_root, on_conflict=on_conflict, dry_run=dry_run):
                    continue
            合并目录(
                src=child,
                dst=target,
                target_root=target_root,
                on_conflict=on_conflict,
                dry_run=dry_run,
                clean_target=False,
            )
            continue

        if target.exists() and not 冲突处理(existing=target, target_root=target_root, on_conflict=on_conflict, dry_run=dry_run):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, target)


def 写入引擎配置模板(
    *,
    engine_id: str,
    target_root: Path,
    profile_db: dict[str, Any],
    on_conflict: str,
    dry_run: bool,
    allow_project_root_changes: bool,
) -> None:
    """按引擎配置数据库写入配置模板。

    Args:
        engine_id: 引擎标识。
        target_root: 目标项目根目录。
        profile_db: 引擎配置数据库。
        on_conflict: 冲突策略。
        dry_run: 是否预演。
        allow_project_root_changes: 是否允许写项目根目录文件。
    """

    engine_payload = profile_db.get("engines", {}).get(engine_id, {})
    if not isinstance(engine_payload, dict):
        return

    profile = engine_payload.get("profile", {})
    if not isinstance(profile, dict):
        profile = {}

    workspace_rel = str(engine_payload.get("workspace_config_path") or "").strip()
    project_rel = str(engine_payload.get("project_config_path") or "").strip()

    if workspace_rel and profile:
        写文本文件(
            dst=target_root / workspace_rel,
            content=json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
            target_root=target_root,
            on_conflict=on_conflict,
            dry_run=dry_run,
        )

    if allow_project_root_changes and project_rel and profile:
        写文本文件(
            dst=target_root / project_rel,
            content=json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
            target_root=target_root,
            on_conflict=on_conflict,
            dry_run=dry_run,
        )


def 初始化_opencode(
    *,
    target_root: Path,
    on_conflict: str,
    dry_run: bool,
    allow_project_root_changes: bool,
    profile_db: dict[str, Any],
) -> None:
    """初始化 OpenCode 项目文件。

    Args:
        target_root: 目标项目根目录。
        on_conflict: 冲突策略。
        dry_run: 是否预演。
        allow_project_root_changes: 是否允许写项目根目录文件。
    """

    opencode_root = target_root / ".opencode"
    for subdir in ["agents", "commands", "modes", "plugins", "skills", "tools", "themes", "rules", "plans"]:
        确保目录(opencode_root / subdir, dry_run=dry_run)

    写入引擎配置模板(
        engine_id="opencode",
        target_root=target_root,
        profile_db=profile_db,
        on_conflict=on_conflict,
        dry_run=dry_run,
        allow_project_root_changes=allow_project_root_changes,
    )

    if not allow_project_root_changes:
        print("[INFO] existing 模式：跳过 AGENTS.md")
        return

    写文本文件(
        dst=target_root / "AGENTS.md",
        content="# 项目规则（AGENTS.md）\n\n本项目已安装 autodo-lib 工作流到 OpenCode。\n",
        target_root=target_root,
        on_conflict=on_conflict,
        dry_run=dry_run,
    )


def 初始化_通用引擎配置(
    *,
    engine_id: str,
    target_root: Path,
    on_conflict: str,
    dry_run: bool,
    allow_project_root_changes: bool,
    profile_db: dict[str, Any],
) -> None:
    """初始化 OpenCode 之外的引擎配置模板。

    Args:
        engine_id: 引擎标识。
        target_root: 目标项目根目录。
        on_conflict: 冲突策略。
        dry_run: 是否预演。
        allow_project_root_changes: 是否允许写项目根目录文件。
        profile_db: 引擎配置数据库。
    """

    写入引擎配置模板(
        engine_id=engine_id,
        target_root=target_root,
        profile_db=profile_db,
        on_conflict=on_conflict,
        dry_run=dry_run,
        allow_project_root_changes=allow_project_root_changes,
    )


def 写文本文件(*, dst: Path, content: str, target_root: Path, on_conflict: str, dry_run: bool) -> None:
    """写入文本文件。

    Args:
        dst: 目标文件。
        content: 文本内容。
        target_root: 目标项目根目录。
        on_conflict: 冲突策略。
        dry_run: 是否预演。
    """

    print(f"[WRITE] {dst}")
    if dst.exists() and not 冲突处理(existing=dst, target_root=target_root, on_conflict=on_conflict, dry_run=dry_run):
        return
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content, encoding="utf-8", newline="\n")


def 读取模板文件内容(*, template_path: str, default_content: str) -> str:
    """读取模板内容。

    Args:
        template_path: 模板文件路径；为空时使用默认内容。
        default_content: 内置默认模板内容。

    Returns:
        str: 模板文本内容。

    Raises:
        SystemExit: 指定模板不存在或不是文件时抛出。
    """

    raw_path = str(template_path or "").strip()
    if not raw_path:
        return default_content

    path = Path(raw_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise SystemExit(f"模板文件不存在或不是文件：{path}")
    return path.read_text(encoding="utf-8")


def 读取布尔输入(*, 提示: str, 默认值: bool) -> bool:
    """读取布尔输入。

    Args:
        提示: 提示语。
        默认值: 默认布尔值。

    Returns:
        bool: 用户选择结果。
    """

    suffix = "Y/n" if 默认值 else "y/N"
    while True:
        raw = input(f"{提示} [{suffix}]：").strip().lower()
        if not raw:
            return 默认值
        if raw in {"y", "yes", "1", "true", "t"}:
            return True
        if raw in {"n", "no", "0", "false", "f"}:
            return False
        print("[WARN] 请输入 y 或 n")


def 读取字符串输入(*, 提示: str, 默认值: str) -> str:
    """读取字符串输入。

    Args:
        提示: 提示语。
        默认值: 默认字符串。

    Returns:
        str: 用户输入或默认值。
    """

    raw = input(f"{提示} [默认: {默认值}]：").strip()
    return raw or 默认值


def 交互选择布尔配置项(*, 名称: str, 默认值: bool) -> bool:
    """交互选择布尔配置项。

    Args:
        名称: 配置项名称。
        默认值: 默认布尔值。

    Returns:
        bool: 选择后的布尔值。
    """

    if 读取布尔输入(提示=f"配置项【{名称}】是否使用默认值（{默认值}）", 默认值=True):
        return 默认值
    return 读取布尔输入(提示=f"配置项【{名称}】请输入自定义值", 默认值=默认值)


def 交互选择字符串配置项(*, 名称: str, 默认值: str) -> str:
    """交互选择字符串配置项。

    Args:
        名称: 配置项名称。
        默认值: 默认字符串。

    Returns:
        str: 选择后的字符串。
    """

    if 读取布尔输入(提示=f"配置项【{名称}】是否使用默认值（{默认值}）", 默认值=True):
        return 默认值
    return 读取字符串输入(提示=f"配置项【{名称}】请输入自定义值", 默认值=默认值)


def 构建_git初始化配置(*, args: argparse.Namespace) -> Git初始化配置:
    """构建 Git 初始化配置。

    Args:
        args: workflow 子命令参数。

    Returns:
        Git初始化配置: 最终配置。
    """

    gitignore_content = 读取模板文件内容(
        template_path=str(args.gitignore_template or ""),
        default_content=默认_gitignore模板,
    )
    gitattributes_content = 读取模板文件内容(
        template_path=str(args.gitattributes_template or ""),
        default_content=默认_gitattributes模板,
    )

    config = Git初始化配置(
        启用=args.git_init != "off",
        默认分支=str(args.git_default_branch or "main").strip() or "main",
        写入_gitignore=bool(args.git_write_ignore),
        gitignore_content=gitignore_content,
        写入_gitattributes=bool(args.git_write_attributes),
        gitattributes_content=gitattributes_content,
        创建初始提交=bool(args.git_create_initial_commit),
    )

    if args.git_init != "interactive":
        return config

    print("[INTERACTIVE] 进入 Git 初始化交互配置")
    启用 = 交互选择布尔配置项(名称="是否执行 git init", 默认值=config.启用)
    默认分支 = 交互选择字符串配置项(名称="默认分支名", 默认值=config.默认分支)
    写入_gitignore = 交互选择布尔配置项(名称="是否写入 .gitignore", 默认值=config.写入_gitignore)
    gitignore_template = 交互选择字符串配置项(
        名称=".gitignore 模板路径（留空使用内置模板）",
        默认值=str(args.gitignore_template or ""),
    )
    写入_gitattributes = 交互选择布尔配置项(名称="是否写入 .gitattributes", 默认值=config.写入_gitattributes)
    gitattributes_template = 交互选择字符串配置项(
        名称=".gitattributes 模板路径（留空使用内置模板）",
        默认值=str(args.gitattributes_template or ""),
    )
    创建初始提交 = 交互选择布尔配置项(名称="是否创建初始提交", 默认值=config.创建初始提交)

    return Git初始化配置(
        启用=启用,
        默认分支=默认分支,
        写入_gitignore=写入_gitignore,
        gitignore_content=读取模板文件内容(template_path=gitignore_template, default_content=默认_gitignore模板),
        写入_gitattributes=写入_gitattributes,
        gitattributes_content=读取模板文件内容(template_path=gitattributes_template, default_content=默认_gitattributes模板),
        创建初始提交=创建初始提交,
    )


def 执行_git命令(*, args: list[str], cwd: Path) -> tuple[int, str]:
    """执行 Git 命令。

    Args:
        args: Git 参数列表。
        cwd: 命令执行目录。

    Returns:
        tuple[int, str]: `(return_code, stderr_or_stdout)`。
    """

    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except FileNotFoundError:
        return (127, "未找到 git 可执行文件，请先安装 Git")

    output = (completed.stderr or "").strip() or (completed.stdout or "").strip()
    return (int(completed.returncode), output)


def 执行_git初始化(
    *,
    target_root: Path,
    config: Git初始化配置,
    on_conflict: str,
    dry_run: bool,
) -> None:
    """执行部署阶段 Git 初始化。

    Args:
        target_root: 目标项目根目录。
        config: Git 初始化配置。
        on_conflict: 冲突策略。
        dry_run: 是否预演。
    """

    if config.写入_gitignore:
        写文本文件(
            dst=target_root / ".gitignore",
            content=config.gitignore_content.rstrip("\n") + "\n",
            target_root=target_root,
            on_conflict=on_conflict,
            dry_run=dry_run,
        )

    if config.写入_gitattributes:
        写文本文件(
            dst=target_root / ".gitattributes",
            content=config.gitattributes_content.rstrip("\n") + "\n",
            target_root=target_root,
            on_conflict=on_conflict,
            dry_run=dry_run,
        )

    if not config.启用:
        print("[INFO] 已禁用部署阶段 Git 初始化")
        return

    git_dir = target_root / ".git"
    if dry_run:
        if git_dir.exists():
            print(f"[DRY-RUN] Git 仓库已存在，跳过初始化：{git_dir}")
        else:
            print(f"[DRY-RUN] 将执行 git init，默认分支：{config.默认分支}")
        return

    if git_dir.exists():
        print(f"[INFO] Git 仓库已存在，跳过 git init：{git_dir}")
    else:
        code, output = 执行_git命令(args=["init"], cwd=target_root)
        if code != 0:
            raise SystemExit(f"git init 失败：{output}")
        code, output = 执行_git命令(args=["symbolic-ref", "HEAD", f"refs/heads/{config.默认分支}"], cwd=target_root)
        if code != 0:
            print(f"[WARN] 设置默认分支失败（可忽略）：{output}")
        print(f"[DONE] Git 仓库初始化完成：{target_root}")

    if not config.创建初始提交:
        return

    code, output = 执行_git命令(args=["add", "-A"], cwd=target_root)
    if code != 0:
        raise SystemExit(f"git add 失败：{output}")

    code, output = 执行_git命令(args=["commit", "-m", "chore: 初始化 autodo 工作流"], cwd=target_root)
    if code != 0:
        print(f"[WARN] 创建初始提交失败（可能无变更或未配置用户身份）：{output}")
    else:
        print("[DONE] 已创建初始提交")


def 从aol部署到引擎(
    *,
    repo_root: Path,
    target_root: Path,
    engine_id: str,
    on_conflict: str,
    dry_run: bool,
    selected_tags: list[str],
) -> bool:
    """从 AOL 编译并部署到指定引擎。

    Args:
        repo_root: 仓库根目录。
        target_root: 目标项目根目录。
        engine_id: 引擎标识。
        on_conflict: 冲突策略。
        dry_run: 是否预演。
        selected_tags: 标签过滤列表。
    Returns:
        bool: 是否执行了 AOL 部署。
    """

    if engine_id not in {"opencode", "claude", "copilot"}:
        return False
    if any(x is None for x in [从libs构建_aol, 校验_aol, 编译到_opencode, 编译到_claude, 编译到_copilot]):
        print("[WARN] aoc 模块不可用，跳过 AOL 部署")
        return False

    libs_root = repo_root / "libs"
    if not libs_root.exists():
        print(f"[INFO] 未找到 libs 目录，跳过：{libs_root}")
        return False

    aol_title = "autodo-lib 模板库 AOL"
    if selected_tags:
        aol_title = f"autodo-lib 模板库 AOL（tags={','.join(selected_tags)}）"

    with tempfile.TemporaryDirectory(prefix=f"aol-libs-{engine_id}-") as temp_libs_dir:
        effective_libs_root = libs_root
        if selected_tags:
            temp_libs_root = Path(temp_libs_dir)
            stats = 构建标签过滤libs视图(root=repo_root, selected_tags=selected_tags, output_libs_root=temp_libs_root)
            if stats["copied_dirs"] == 0 and stats["copied_files"] == 0:
                print(f"[WARN] 标签过滤后无可编译条目：tags={selected_tags}，跳过 AOL 部署")
                return False
            print(f"[INFO] AOL 标签过滤统计：{stats}")
            effective_libs_root = temp_libs_root

        aol, _ = 从libs构建_aol(libs_root=effective_libs_root, title=aol_title)
    for warning in 校验_aol(aol):
        print(f"[WARN] {warning}")

    if engine_id == "opencode" and 收集_opencode阻断错误 is not None:
        blocking = 收集_opencode阻断错误(aol)
        if blocking:
            for item in blocking:
                print(f"[ERROR] {item}")
            raise SystemExit("AOL 编译到 OpenCode 被阻断；请修复 AOL 源码后再部署")

    with tempfile.TemporaryDirectory(prefix=f"aoc-build-{engine_id}-") as temp_dir:
        compile_root = Path(temp_dir)
        if engine_id == "opencode":
            编译到_opencode(aol, compile_root)
        elif engine_id == "claude":
            编译到_claude(aol, compile_root)
        elif engine_id == "copilot":
            编译到_copilot(aol, compile_root)

        if engine_id == "opencode":
            for root_name in ["opencode.json", "AGENTS.md"]:
                generated_root_file = compile_root / root_name
                if generated_root_file.exists() and generated_root_file.is_file():
                    print(f"[INFO] 保留项目根配置，跳过 AOL 产物：{generated_root_file}")
                    if not dry_run:
                        generated_root_file.unlink()

        合并目录(
            src=compile_root,
            dst=target_root,
            target_root=target_root,
            on_conflict=on_conflict,
            dry_run=dry_run,
            clean_target=False,
        )
    return True


def 健康检查_opencode_agents颜色(*, opencode_root: Path) -> list[str]:
    """校验 OpenCode agents 颜色字段是否为十六进制。

    Args:
        opencode_root: OpenCode 根目录。

    Returns:
        list[str]: 错误列表。
    """

    errors: list[str] = []
    agents_dir = opencode_root / "agents"
    if not agents_dir.exists():
        return errors

    color_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
    for file_path in sorted(path for path in agents_dir.glob("*.md") if path.is_file()):
        color = 读取前言颜色(file_path)
        if color is None:
            continue
        if not color_pattern.match(color):
            errors.append(f"{file_path} 的 color 非法：{color}")
    return errors


def 执行引擎健康检查(*, engine_id: str, target_root: Path, profile_db: dict[str, Any]) -> list[str]:
    """执行单引擎部署健康检查。

    Args:
        engine_id: 引擎标识。
        target_root: 目标项目根目录。
        profile_db: 引擎配置数据库。

    Returns:
        list[str]: 错误列表。
    """

    errors: list[str] = []
    engines_payload = profile_db.get("engines", {})
    engine_payload = engines_payload.get(engine_id, {}) if isinstance(engines_payload, dict) else {}
    if not isinstance(engine_payload, dict):
        engine_payload = {}

    engine_root_mapping = {
        "opencode": ".opencode",
        "claude": ".claude",
        "copilot": ".copilot",
        "custom": ".engine",
    }
    engine_root = target_root / engine_root_mapping.get(engine_id, ".engine")
    if not engine_root.exists():
        errors.append(f"缺少引擎目录：{engine_root}")

    workspace_rel = str(engine_payload.get("workspace_config_path") or "").strip()
    if workspace_rel:
        workspace_cfg = target_root / workspace_rel
        if not workspace_cfg.exists():
            errors.append(f"缺少工作区配置文件：{workspace_cfg}")
        else:
            try:
                json.loads(workspace_cfg.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"工作区配置文件 JSON 解析失败：{workspace_cfg}，{exc}")

    project_rel = str(engine_payload.get("project_config_path") or "").strip()
    if project_rel:
        project_cfg = target_root / project_rel
        if project_cfg.exists():
            try:
                parsed = json.loads(project_cfg.read_text(encoding="utf-8"))
                if engine_id == "opencode":
                    permission = parsed.get("permission", {}) if isinstance(parsed, dict) else {}
                    if not isinstance(permission, dict):
                        errors.append("opencode.json 的 permission 字段必须是对象")
                    else:
                        if permission.get("external_directory") != "deny":
                            errors.append("opencode.json 缺少 permission.external_directory=deny")
                        if permission.get("bash") != "ask":
                            errors.append("opencode.json 缺少 permission.bash=ask")
                        if permission.get("edit") != "ask":
                            errors.append("opencode.json 缺少 permission.edit=ask")
            except Exception as exc:
                errors.append(f"项目配置文件 JSON 解析失败：{project_cfg}，{exc}")

    if engine_id == "opencode":
        errors.extend(健康检查_opencode_agents颜色(opencode_root=engine_root))

    return errors


def 执行_workflow(argv: list[str]) -> int:
    """执行 workflow 子命令。

    Args:
        argv: 子命令参数。

    Returns:
        int: 退出码。
    """

    root = 仓库根目录()
    workflows = 工作流映射(root)
    engines = 引擎映射(root)
    profile_db = 读取引擎配置数据库(root)
    supported_tags = [str(tag) for tag in profile_db.get("supported_tags", 默认支持标签)]

    parser = argparse.ArgumentParser(description="按工作流部署到目标项目")
    parser.add_argument("--workflow", required=True, choices=sorted(workflows.keys()))
    parser.add_argument("--engine", required=True, action="append")
    parser.add_argument("--target", required=True)
    parser.add_argument("--project-name", default=None)
    parser.add_argument("--tags", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--on-conflict", choices=["skip", "overwrite", "backup"], default="skip")
    parser.add_argument("--skip-health-check", action="store_true")
    parser.add_argument("--extras", choices=["none", "ai-tools", "dev", "all"], default="none")
    parser.add_argument("--git-init", choices=["auto", "interactive", "off"], default="auto")
    parser.add_argument("--git-default-branch", default="main")
    parser.add_argument("--gitignore-template", default="")
    parser.add_argument("--gitattributes-template", default="")
    parser.add_argument("--git-create-initial-commit", action="store_true")
    parser.add_argument("--git-write-ignore", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--git-write-attributes", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)
    git_config = 构建_git初始化配置(args=args)

    selected_tags = 解析标签参数(raw_tags=str(args.tags), supported_tags=supported_tags)

    engine_ids: list[str] = []
    for part in args.engine:
        for token in str(part).split(","):
            token = token.strip()
            if token and token not in engine_ids:
                engine_ids.append(token)
    invalid = [eid for eid in engine_ids if eid not in engines]
    if invalid:
        print(f"[ERROR] 未知 engine: {invalid}", file=sys.stderr)
        return 2

    _ = workflows[args.workflow]

    target = 解析安装目标(target=args.target, project_name=args.project_name)
    target_root = target.项目根目录
    if not args.dry_run:
        target_root.mkdir(parents=True, exist_ok=True)

    print(
        f"[INFO] workflow={args.workflow}, target={target_root}, mode={target.部署模式}, "
        f"engines={engine_ids}, tags={selected_tags or ['<workflow-default>']}"
    )

    for engine_id in engine_ids:
        spec = engines[engine_id]
        engine_dst = target_root / spec.引擎根目录名
        engine_preexisted = engine_dst.exists()

        合并目录(
            src=spec.模板目录,
            dst=engine_dst,
            target_root=target_root,
            on_conflict=args.on_conflict,
            dry_run=args.dry_run,
            clean_target=False,
        )

        allow_project_root_changes = target.部署模式 == "new"
        if engine_id == "opencode":
            初始化_opencode(
                target_root=target_root,
                on_conflict=args.on_conflict,
                dry_run=args.dry_run,
                allow_project_root_changes=allow_project_root_changes,
                profile_db=profile_db,
            )
        else:
            初始化_通用引擎配置(
                engine_id=engine_id,
                target_root=target_root,
                on_conflict=args.on_conflict,
                dry_run=args.dry_run,
                allow_project_root_changes=allow_project_root_changes,
                profile_db=profile_db,
            )

        从aol部署到引擎(
            repo_root=root,
            target_root=target_root,
            engine_id=engine_id,
            on_conflict=args.on_conflict,
            dry_run=args.dry_run,
            selected_tags=selected_tags,
        )

        写入引擎配置模板(
            engine_id=engine_id,
            target_root=target_root,
            profile_db=profile_db,
            on_conflict=args.on_conflict,
            dry_run=args.dry_run,
            allow_project_root_changes=allow_project_root_changes,
        )

        if not args.dry_run and not args.skip_health_check:
            health_errors = 执行引擎健康检查(
                engine_id=engine_id,
                target_root=target_root,
                profile_db=profile_db,
            )
            if health_errors:
                print(f"[HEALTH] {engine_id} 健康检查失败：")
                for item in health_errors:
                    print(f"[HEALTH][ERROR] {item}")
                return 3
            print(f"[HEALTH] {engine_id} 健康检查通过")

    执行_git初始化(
        target_root=target_root,
        config=git_config,
        on_conflict=args.on_conflict,
        dry_run=args.dry_run,
    )

    return 0


def 解析_extras(extras: str) -> list[str]:
    """解析扩展包选项。

    Args:
        extras: 扩展包选项。

    Returns:
        list[str]: 扩展包目录名列表。
    """

    mapping = {
        "none": [],
        "ai-tools": ["ai-tools"],
        "dev": ["dev"],
        "all": ["ai-tools", "dev"],
    }
    return list(mapping[extras])


def 执行_extras_bundle(argv: list[str]) -> int:
    """执行 extras-bundle 子命令。

    Args:
        argv: 子命令参数。

    Returns:
        int: 退出码。
    """

    parser = argparse.ArgumentParser(description="打包扩展包离线 bundle")
    parser.add_argument("--workflow", default="academic", choices=["academic", "documentation", "software"])
    parser.add_argument("--extras", default="ai-tools", choices=["none", "ai-tools", "dev", "all"])
    parser.add_argument("--output-dir", default=str(仓库根目录() / "dist" / "extras"))
    parser.add_argument("--output-name", default="")
    args = parser.parse_args(argv)

    root = 仓库根目录()
    _ = 工作流映射(root)[args.workflow]
    extras_root = root / "libs" / "skills_extras"
    selected = 解析_extras(args.extras)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = args.output_name or f"{args.workflow}_{args.extras}_{datetime.now().strftime('%Y%m%d')}.zip"
    zip_path = output_dir / output_name

    manifest_files: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for extra_name in selected:
            extra_dir = extras_root / extra_name
            if not extra_dir.exists():
                continue
            for file_path in sorted(path for path in extra_dir.rglob("*") if path.is_file()):
                rel = file_path.relative_to(extra_dir)
                arcname = str((Path("skills") / rel).as_posix())
                raw = file_path.read_bytes()
                zf.writestr(arcname, raw)
                manifest_files.append(
                    {
                        "path": arcname,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "size": len(raw),
                    }
                )

        install_md = (
            "# 扩展包离线安装说明\n\n"
            f"- 工作流：{args.workflow}\n"
            f"- 扩展包：{args.extras}\n"
        )
        zf.writestr("INSTALL.md", install_md)
        zf.writestr("requirements.txt", "# 按需补充依赖\n")
        zf.writestr(
            "MANIFEST.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "generatedAt": datetime.now().isoformat(timespec="seconds"),
                    "workflow": args.workflow,
                    "extras": args.extras,
                    "files": manifest_files,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    print(f"[DONE] Bundle 已生成：{zip_path}")
    return 0


def 执行_workspace_convert(argv: list[str]) -> int:
    """执行模板项目办公区跨引擎转换流程。

    Args:
        argv: 子命令参数。

    Returns:
        int: 退出码。
    """

    if (
        读取引擎办公区目录名 is None
        or 从引擎办公区构建_aol is None
        or 编译_aol到引擎办公区 is None
        or 校验_aol is None
        or 收集_opencode阻断错误 is None
    ):
        print("[ERROR] AOC 翻译内核不可用，无法执行 workspace-convert", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description="在模板项目内执行办公区跨引擎转换")
    parser.add_argument("--project-dir", required=True, help="模板项目目录")
    parser.add_argument("--source-engine", required=True, choices=["opencode", "claude", "copilot"])
    parser.add_argument("--target-engine", required=True, choices=["opencode", "claude", "copilot"])
    parser.add_argument("--title", default="", help="可选：转换过程的 AOL 标题")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入目标办公区")
    args = parser.parse_args(argv)

    if args.source_engine == args.target_engine:
        print("[ERROR] --source-engine 与 --target-engine 不能相同", file=sys.stderr)
        return 2

    project_dir = Path(args.project_dir).expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        print(f"[ERROR] 模板项目目录不存在：{project_dir}", file=sys.stderr)
        return 2

    source_workspace_name = 读取引擎办公区目录名(engine=args.source_engine)
    target_workspace_name = 读取引擎办公区目录名(engine=args.target_engine)
    source_workspace_dir = (project_dir / source_workspace_name).resolve()
    target_workspace_dir = (project_dir / target_workspace_name).resolve()

    if source_workspace_dir.parent != project_dir or target_workspace_dir.parent != project_dir:
        print("[ERROR] 办公区路径边界校验失败，已阻断", file=sys.stderr)
        return 2

    title = str(args.title).strip() or f"{project_dir.name} 办公区跨引擎转换"
    try:
        aol, stats = 从引擎办公区构建_aol(
            source_workspace_dir=source_workspace_dir,
            source_engine=args.source_engine,
            title=title,
        )
    except Exception as exc:
        print(f"[ERROR] 构建 AOL 失败：{exc}", file=sys.stderr)
        return 2

    warnings = 校验_aol(aol)
    for warning in warnings:
        print(f"[WARN] {warning}")

    if args.target_engine == "opencode":
        blocking_errors = 收集_opencode阻断错误(aol)
        if blocking_errors:
            for item in blocking_errors:
                print(f"[ERROR] {item}")
            print("[ERROR] 目标为 OpenCode，编译已阻断。请先修复源办公区内容后重试。", file=sys.stderr)
            return 2

    if args.dry_run:
        print("[DRY-RUN] 已完成转换预览，不写入文件")
        print(f"[DRY-RUN] source={source_workspace_dir}")
        print(f"[DRY-RUN] target={target_workspace_dir}")
        print(f"[DRY-RUN] stats={stats}")
        return 0

    try:
        编译_aol到引擎办公区(
            aol=aol,
            target_workspace_dir=target_workspace_dir,
            target_engine=args.target_engine,
        )
    except Exception as exc:
        print(f"[ERROR] 写入目标办公区失败：{exc}", file=sys.stderr)
        return 2

    print(f"[DONE] 已完成办公区转换：{args.source_engine} -> {args.target_engine}")
    print(f"[DONE] source={source_workspace_dir}")
    print(f"[DONE] target={target_workspace_dir}")
    print(f"[DONE] stats={stats}")
    return 0


def 构建解析器() -> argparse.ArgumentParser:
    """构建顶层命令解析器。

    Returns:
        argparse.ArgumentParser: 解析器对象。
    """

    parser = argparse.ArgumentParser(description="部署安装统一入口")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("workflow", help="按 workflow 部署")
    sub.add_parser("extras-bundle", help="打包扩展包离线 bundle")
    sub.add_parser("workspace-convert", help="在模板项目内执行办公区跨引擎转换")
    return parser


def main() -> int:
    """程序主入口。

    Returns:
        int: 退出码。
    """

    parser = 构建解析器()
    args, passthrough = parser.parse_known_args()
    if args.command == "workflow":
        return 执行_workflow(list(passthrough))
    if args.command == "extras-bundle":
        return 执行_extras_bundle(list(passthrough))
    if args.command == "workspace-convert":
        return 执行_workspace_convert(list(passthrough))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
