#!/usr/bin/env python3
"""本地库管理统一入口。

本脚本仅保留一个文件作为“本地库管理”功能入口，提供以下子命令：
- items：条目清单管理（sync/get/delete/upsert）。
- tags：场景标签与关系表管理。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from aoc import 原位归一化libs_aol
except Exception:  # pragma: no cover
    原位归一化libs_aol = None


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
    """

    repo_root: Path
    libs_root: Path
    db_root: Path
    items_csv: Path
    relation_csv: Path
    manifest_json: Path


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
    )


def 规范路径(path_text: str) -> str:
    """规范化路径字符串。

    Args:
        path_text: 原始路径文本。

    Returns:
        str: 规范化后的相对路径。
    """

    text = str(path_text or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.strip("/")


def 规范标签(tags: list[str]) -> list[str]:
    """规范标签列表并按优先顺序稳定去重。

    Args:
        tags: 原始标签列表。

    Returns:
        list[str]: 规范后的标签列表。
    """

    clean = [str(tag).strip() for tag in tags if str(tag).strip()]
    seen: set[str] = set()
    ordered: list[str] = []

    for tag in 默认场景标签顺序:
        if tag in clean and tag not in seen:
            seen.add(tag)
            ordered.append(tag)

    for tag in clean:
        if tag not in seen:
            seen.add(tag)
            ordered.append(tag)

    return ordered


def 解析标签单元格(cell: str) -> list[str]:
    """解析 `scenario_tags` 单元格。

    Args:
        cell: 单元格内容。

    Returns:
        list[str]: 标签列表。
    """

    raw = str(cell or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
        if isinstance(payload, list):
            return 规范标签([str(item) for item in payload if isinstance(item, str)])
    except json.JSONDecodeError:
        pass
    return 规范标签([part.strip() for part in raw.split(",") if part.strip()])


def 序列化标签单元格(tags: list[str]) -> str:
    """序列化 `scenario_tags` 单元格。

    Args:
        tags: 标签列表。

    Returns:
        str: 逗号分隔文本。
    """

    return ",".join(规范标签(tags))


def 读取_items(paths: 路径配置) -> dict[str, dict[str, Any]]:
    """读取 `items.csv`。

    Args:
        paths: 路径配置。

    Returns:
        dict[str, dict[str, Any]]: `relative_path -> 行数据`。
    """

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
        rows: 行数据映射。
    """

    fields = ["uid", "name", "content_type", "scenario_tags", "relative_path", "item_type", "file_count"]
    paths.items_csv.parent.mkdir(parents=True, exist_ok=True)
    with paths.items_csv.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for key in sorted(rows.keys()):
            row = rows[key]
            writer.writerow(
                {
                    "uid": str(row.get("uid") or "").strip(),
                    "name": str(row.get("name") or "").strip(),
                    "content_type": str(row.get("content_type") or "").strip(),
                    "scenario_tags": 序列化标签单元格(list(row.get("scenario_tags") or [])),
                    "relative_path": key,
                    "item_type": str(row.get("item_type") or "").strip(),
                    "file_count": int(row.get("file_count") or 0),
                }
            )


def 读取关系表(paths: 路径配置) -> dict[str, list[str]]:
    """读取二维关系表为 UID 到标签映射。

    Args:
        paths: 路径配置。

    Returns:
        dict[str, list[str]]: UID 到标签映射。
    """

    if not paths.relation_csv.exists():
        return {}

    with paths.relation_csv.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        headers = list(reader.fieldnames or [])

        uid_field = "uid" if "uid" in headers else ("item_uid" if "item_uid" in headers else "")
        name_fields = {"name", "item_name"}
        tag_fields = [header for header in headers if header and header not in {uid_field, *name_fields}]

        mapping: dict[str, list[str]] = {}
        for row in reader:
            raw_uid = str(row.get(uid_field) or "").strip() if uid_field else ""
            if not raw_uid:
                continue
            uid = raw_uid.rsplit("_", 1)[-1] if "_" in raw_uid else raw_uid
            tags = [
                tag
                for tag in tag_fields
                if str(row.get(tag) or "").strip().lower() in {"1", "true", "yes", "y", "是", "✓", "v"}
            ]
            mapping[uid] = 规范标签(tags)
        return mapping


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
        写入_items(paths, final_rows)
        写入关系表(paths, final_rows)
        paths.manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        metadata_stats = 同步_items元数据(paths, final_rows, dry_run=True)

    return {
        "added": len(added),
        "removed": len(removed),
        "items_total": len(final_rows),
        "items_csv": str(paths.items_csv),
        "relation_csv": str(paths.relation_csv),
        "manifest": str(paths.manifest_json),
        "dry_run": dry_run,
        "metadata_sync": metadata_stats,
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


def 构建解析器() -> argparse.ArgumentParser:
    """构建顶层解析器。

    Returns:
        argparse.ArgumentParser: 顶层解析器。
    """

    parser = argparse.ArgumentParser(description="本地库管理统一入口")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("items", help="条目清单同步与 CRUD")
    sub.add_parser("tags", help="标签与关系表管理")
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
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
