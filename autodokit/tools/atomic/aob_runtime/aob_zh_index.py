# -*- coding: utf-8 -*-
"""AOB 中文技能/智能体索引生成与查询工具。

功能：
1. 扫描指定根目录下所有 SKILL.md / .agent.md
2. 提取 name、description、metadata.display_zh、metadata.aliases_zh、metadata.category_zh
3. 生成 skills_zh_index.yaml（给 AI 读）和 skills_zh_index.md（给人看）
4. 支持按中文关键词或分类查询

用法：
    python -m autodokit.tools.atomic.aob_runtime.aob_zh_index generate [--source-root ...] [--output-dir ...]
    python -m autodokit.tools.atomic.aob_runtime.aob_zh_index query --keyword 精读
    python -m autodokit.tools.atomic.aob_runtime.aob_zh_index query --category 文献处理
    python -m autodokit.tools.atomic.aob_runtime.aob_zh_index query --all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None  # type: ignore[assignment]


# ---------- 默认路径 ----------

默认源根目录 = [
    Path.home() / ".copilot" / "skills",
    Path.home() / ".copilot" / "agents",
    Path.home() / ".claude" / "skills",
    Path.home() / ".claude" / "agents",
]

默认输出目录 = Path.home() / "CoreFiles" / "ProjectsFile" / "autodo-lib" / "datastore"


# ---------- 索引条目 ----------

def _读取frontmatter(文件路径: Path) -> dict[str, Any]:
    """读取 Markdown 文件的 YAML frontmatter。"""
    content = 文件路径.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return {}
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return {}
    raw = content[3:end_idx].strip()
    try:
        fm = yaml.safe_load(raw) or {}
    except Exception:
        return {}
    return fm if isinstance(fm, dict) else {}


def _提取条目_技能(技能目录: Path) -> dict[str, Any] | None:
    """从技能目录提取索引条目。"""
    skill_md = 技能目录 / "SKILL.md"
    if not skill_md.exists():
        return None
    fm = _读取frontmatter(skill_md)
    if not fm:
        return None

    name = str(fm.get("name") or 技能目录.name)
    description = str(fm.get("description") or "")[:200]
    meta = fm.get("metadata")
    display_zh = ""
    aliases_zh: list[str] = []
    category_zh = ""

    if isinstance(meta, dict):
        display_zh = str(meta.get("display_zh", "")).strip()
        aliases_raw = str(meta.get("aliases_zh", "")).strip()
        if aliases_raw:
            aliases_zh = [a.strip() for a in aliases_raw.split(",") if a.strip()]
        category_zh = str(meta.get("category_zh", "")).strip()

    return {
        "name": name,
        "display_zh": display_zh,
        "aliases_zh": aliases_zh,
        "category_zh": category_zh,
        "description": description,
        "type": "skill",
        "source_path": str(skill_md),
    }


def _提取条目_智能体(智能体文件: Path) -> dict[str, Any] | None:
    """从智能体文件提取索引条目。"""
    if not 智能体文件.name.endswith(".agent.md"):
        return None
    fm = _读取frontmatter(智能体文件)
    if not fm:
        return None

    name = str(fm.get("name") or 智能体文件.stem.replace(".agent", ""))
    description = str(fm.get("description") or "")[:200]
    meta = fm.get("metadata")
    display_zh = ""
    aliases_zh: list[str] = []
    category_zh = ""

    if isinstance(meta, dict):
        display_zh = str(meta.get("display_zh", "")).strip()
        aliases_raw = str(meta.get("aliases_zh", "")).strip()
        if aliases_raw:
            aliases_zh = [a.strip() for a in aliases_raw.split(",") if a.strip()]
        category_zh = str(meta.get("category_zh", "")).strip()

    return {
        "name": name,
        "display_zh": display_zh,
        "aliases_zh": aliases_zh,
        "category_zh": category_zh,
        "description": description,
        "type": "agent",
        "source_path": str(智能体文件),
    }


def 生成中文索引(
    *,
    source_roots: list[Path] | None = None,
    output_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """扫描源目录，生成中文索引数据结构。

    Args:
        source_roots: 扫描根目录列表。
        output_dir: 输出目录（用于生成 yaml/md 文件）。
        dry_run: 仅返回数据，不写文件。

    Returns:
        包含 entries 列表和统计信息的 dict。
    """
    if source_roots is None:
        source_roots = [r for r in 默认源根目录 if r.is_dir()]

    entries: list[dict[str, Any]] = []
    skills_count = 0
    agents_count = 0

    for root in source_roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.name.startswith("."):
                continue
            # 技能：目录 + SKILL.md
            if child.is_dir():
                entry = _提取条目_技能(child)
                if entry:
                    entries.append(entry)
                    skills_count += 1
                continue
            # 智能体：.agent.md 文件
            if child.name.endswith(".agent.md"):
                entry = _提取条目_智能体(child)
                if entry:
                    entries.append(entry)
                    agents_count += 1

    # 去重：按 name 字段，保留首次出现
    seen_names: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for e in entries:
        nm = e.get("name", "")
        if nm in seen_names:
            continue
        seen_names.add(nm)
        deduped.append(e)
    entries = deduped

    # 重算去重后的计数
    skills_count = sum(1 for e in entries if e.get("type") == "skill")
    agents_count = sum(1 for e in entries if e.get("type") == "agent")

    # 按 display_zh 排序（中文排前，无中文的排后）
    def _排序键(e: dict[str, Any]) -> tuple[int, str]:
        dz = e.get("display_zh", "")
        if dz:
            return (0, dz)
        return (1, e.get("name", ""))

    entries.sort(key=_排序键)

    result: dict[str, Any] = {
        "generated_at": "",
        "source_roots": [str(r) for r in source_roots],
        "total": len(entries),
        "skills_count": skills_count,
        "agents_count": agents_count,
        "entries": entries,
    }

    if not dry_run and output_dir:
        import time as _time
        result["generated_at"] = _time.strftime("%Y-%m-%dT%H:%M:%S")
        _输出yaml(result, output_dir)
        _输出markdown(result, output_dir)
        result["output_yaml"] = str(output_dir / "skills_zh_index.yaml")
        result["output_md"] = str(output_dir / "skills_zh_index.md")

    return result


def 查询中文索引(
    *,
    source_roots: list[Path] | None = None,
    keyword: str = "",
    category: str = "",
    list_all: bool = False,
) -> list[dict[str, Any]]:
    """按关键词或分类查询中文索引。

    Args:
        source_roots: 扫描根目录。
        keyword: 搜索关键词（模糊匹配 display_zh / aliases_zh / description）。
        category: 按分类筛选。
        list_all: 列出全部。

    Returns:
        匹配的条目列表。
    """
    index_data = 生成中文索引(source_roots=source_roots, dry_run=True)
    entries = index_data.get("entries", [])

    if list_all:
        return entries

    results: list[dict[str, Any]] = []
    kw = keyword.strip().lower()

    for e in entries:
        if category:
            if e.get("category_zh", "") != category:
                continue

        if kw:
            searchable = (
                e.get("display_zh", "").lower() + " " +
                " ".join(e.get("aliases_zh", [])).lower() + " " +
                e.get("description", "").lower() + " " +
                e.get("name", "").lower()
            )
            if kw not in searchable:
                continue

        results.append(e)

    return results


# ---------- 输出函数 ----------

def _输出yaml(data: dict[str, Any], output_dir: Path) -> None:
    """输出 YAML 索引文件。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = output_dir / "skills_zh_index.yaml"
    # 精简 entries 以便于 AI 读取
    compact = {
        "generated_at": data["generated_at"],
        "source_roots": data["source_roots"],
        "total": data["total"],
        "skills_count": data["skills_count"],
        "agents_count": data["agents_count"],
        "entries": [
            {
                "name": e["name"],
                "display_zh": e.get("display_zh", ""),
                "aliases_zh": e.get("aliases_zh", []),
                "category_zh": e.get("category_zh", ""),
                "type": e["type"],
            }
            for e in data["entries"]
        ],
    }
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(compact, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _输出markdown(data: dict[str, Any], output_dir: Path) -> None:
    """输出 Markdown 索引表格。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "skills_zh_index.md"

    lines = [
        f"# 技能与智能体中文索引",
        "",
        f"> 自动生成于 {data['generated_at']}。共 {data['total']} 个条目（技能 {data['skills_count']}、智能体 {data['agents_count']}）。",
        f"> 键入 `/` 后按中文别名搜索即可触发对应技能。",
        "",
        "| 中文名 | 标识符 | 触发词 | 类型 |",
        "|--------|--------|--------|------|",
    ]

    for e in data["entries"]:
        display = e.get("display_zh", "") or e["name"]
        name = f"`{e['name']}`"
        aliases = ", ".join(e.get("aliases_zh", [])[:5])
        typ = "🎯 skill" if e["type"] == "skill" else "🤖 agent"
        lines.append(f"| {display} | {name} | {aliases} | {typ} |")

    # 按分类分组的索引
    by_category: dict[str, list[dict[str, Any]]] = {}
    for e in data["entries"]:
        cat = e.get("category_zh", "").strip() or "未分类"
        by_category.setdefault(cat, []).append(e)

    if len(by_category) > 1:
        lines.append("")
        lines.append("## 按分类浏览")
        lines.append("")
        for cat in sorted(by_category.keys()):
            lines.append(f"### {cat}")
            lines.append("")
            for e in by_category[cat]:
                display = e.get("display_zh", "") or e["name"]
                lines.append(f"- **{display}** (`{e['name']}`)")

    lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------- CLI 入口 ----------

def main() -> int:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(description="AOB 中文技能/智能体索引生成与查询")
    sub = parser.add_subparsers(dest="command")

    # generate 子命令
    gen = sub.add_parser("generate", help="扫描并生成索引")
    gen.add_argument("--source-root", action="append", default=[], help="源根目录（可重复）")
    gen.add_argument("--output-dir", default="", help="输出目录，默认 autodo-lib/datastore")
    gen.add_argument("--dry-run", action="store_true", help="仅显示统计，不写文件")

    # query 子命令
    q = sub.add_parser("query", help="查询索引")
    q.add_argument("--source-root", action="append", default=[], help="源根目录（可重复）")
    q.add_argument("--keyword", default="", help="关键词搜索")
    q.add_argument("--category", default="", help="按分类筛选")
    q.add_argument("--all", action="store_true", help="列出全部条目")
    q.add_argument("--json", action="store_true", help="以 JSON 格式输出")

    args = parser.parse_args()

    if args.command == "generate" or not args.command:
        source_roots = [Path(p) for p in args.source_root] if args.source_root else None
        output_dir = Path(args.output_dir) if args.output_dir else 默认输出目录
        result = 生成中文索引(source_roots=source_roots, output_dir=output_dir, dry_run=bool(args.dry_run))
        print(f"索引{'预览' if args.dry_run else '已生成'}:")
        print(f"  技能: {result['skills_count']}, 智能体: {result['agents_count']}, 合计: {result['total']}")
        if not args.dry_run:
            print(f"  YAML: {result.get('output_yaml', 'N/A')}")
            print(f"  MD:   {result.get('output_md', 'N/A')}")
        return 0

    if args.command == "query":
        source_roots = [Path(p) for p in args.source_root] if args.source_root else None
        results = 查询中文索引(
            source_roots=source_roots,
            keyword=args.keyword,
            category=args.category,
            list_all=bool(args.all),
        )
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"\n查询结果: {len(results)} 条")
            for r in results:
                display = r.get("display_zh", "") or r["name"]
                typ = "技能" if r["type"] == "skill" else "智能体"
                aliases = ", ".join(r.get("aliases_zh", [])[:3])
                cat = f" [{r.get('category_zh', '')}]" if r.get("category_zh") else ""
                print(f"  {display}{cat}  ({typ})  `{r['name']}`")
                if aliases:
                    print(f"    触发词: {aliases}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
