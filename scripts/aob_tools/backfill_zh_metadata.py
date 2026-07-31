# -*- coding: utf-8 -*-
"""批量回填 SKILL.md / .agent.md 的中文元数据字段。

扫描 ~/.copilot/skills/ 和 ~/.copilot/agents/，对每个 SKILL.md 或 .agent.md：
1. 如果 metadata.display_zh 已存在 → 跳过。
2. 否则从目录名/文件名中提取中文部分作为 display_zh 草稿。
3. 从 description 中提取可能的触发词作为 aliases_zh 草稿。

用法：
    cd autodo-kit
    python scripts/aob_tools/backfill_zh_metadata.py --dry-run    # 预览
    python scripts/aob_tools/backfill_zh_metadata.py              # 正式执行
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
except ImportError:  # pragma: no cover
    print("[ERROR] 需要 PyYAML。请运行: uv pip install pyyaml", file=sys.stderr)
    raise SystemExit(1)


# ---------- 默认扫描根目录 ----------

默认技能根目录 = [
    Path.home() / ".copilot" / "skills",
    Path.home() / ".claude" / "skills",
]

# agents 是 flat 文件（.agent.md），不是目录
默认智能体根目录 = [
    Path.home() / ".copilot" / "agents",
    Path.home() / ".claude" / "agents",
]


# ---------- 工具函数 ----------

def _提取中文(text: str) -> str:
    """从文本中提取中文汉字与常见标点组成的连续片段。"""
    cleaned = re.sub(r"[_-]", " ", text)
    chinese_chars = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf·\u3000-\u303f\uff00-\uffef]+", cleaned)
    if not chinese_chars:
        return ""
    # 取最长的一段
    return max(chinese_chars, key=len).strip()


def _提取触发词(text: str) -> list[str]:
    """从描述文本中提取可能的触发词（中文双字词和三字词）。"""
    words = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    stop_words = {"学术科研", "文献导入", "导入和", "预处理", "固定主链", "默认由", "直接调用", "本智能体", "仅用于", "人工指定", "补充型",
                  "事务智能体", "配置路径", "常规主链", "执行优先", "当前", "使用", "需要", "提供", "承接", "子动作", "适用于",
                  "面向", "进行", "通过", "可以", "用于", "以及", "或者", "这种", "这个", "那么", "什么", "一个", "其中",
                  "所有", "这些", "那些", "之后", "之前", "按照", "根据", "关于", "对于", "为了", "因为", "所以",
                  "如果", "但是", "虽然", "不过", "而且", "并且", "以及", "还是", "另外", "此外", "因此"}
    # 去重、去停用词、保持顺序
    seen = set()
    result = []
    for w in words:
        if w not in stop_words and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:8]  # 最多 8 个触发词


def _读取frontmatter和正文(file_path: Path) -> tuple[dict[str, Any], str, str]:
    """读取 Markdown 文件的 YAML frontmatter 和正文。

    Returns:
        (frontmatter_dict, raw_frontmatter_text, body_text)
    """
    content = file_path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return {}, "", content
    # 找第二个 ---
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return {}, "", content
    raw = content[3:end_idx].strip()
    body = content[end_idx + 3:].lstrip("\n")
    try:
        fm = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}, raw, body
    if not isinstance(fm, dict):
        return {}, raw, body
    return fm, raw, body


def _回填单个技能(skill_dir: Path, dry_run: bool) -> dict[str, Any]:
    """回填单个技能目录的 SKILL.md。

    Returns:
        操作结果 dict。
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return {"path": str(skill_dir), "status": "no_skill_md"}

    fm, raw, body = _读取frontmatter和正文(skill_md)
    if not fm:
        return {"path": str(skill_dir), "status": "no_frontmatter"}

    name = str(fm.get("name") or skill_dir.name)

    # 检查是否已有 display_zh
    meta = fm.get("metadata")
    if isinstance(meta, dict) and meta.get("display_zh", "").strip():
        return {"path": str(skill_dir), "name": name, "status": "already_has_display_zh",
                "display_zh": meta["display_zh"]}

    # 从目录名提取中文
    display_zh = _提取中文(skill_dir.name)
    if not display_zh:
        # 从 name 字段提取
        display_zh = _提取中文(name)
    if not display_zh:
        # 尝试从 description 提取可能的名称
        desc = str(fm.get("description", "")).split("。")[0]
        display_zh_candidates = _提取中文(desc)
        display_zh = display_zh_candidates[:20] if len(display_zh_candidates) > 20 else display_zh_candidates

    # 从 description 提取触发词
    desc = str(fm.get("description", ""))
    aliases = _提取触发词(desc)

    result = {
        "path": str(skill_dir),
        "name": name,
        "status": "would_update" if dry_run else "updated",
        "display_zh": display_zh,
        "aliases_zh": aliases,
    }

    if dry_run:
        return result

    # 构建新的 frontmatter
    if not isinstance(meta, dict):
        meta = {}
    meta["display_zh"] = display_zh
    if aliases:
        meta["aliases_zh"] = ", ".join(aliases)
    fm["metadata"] = meta

    # 写回
    new_raw = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
    skill_md.write_text(f"---\n{new_raw.strip()}\n---\n{body}", encoding="utf-8")
    return result


def _回填单个智能体(agent_file: Path, dry_run: bool) -> dict[str, Any]:
    """回填单个 agent 文件。

    Returns:
        操作结果 dict。
    """
    if not agent_file.exists():
        return {"path": str(agent_file), "status": "not_found"}
    if not agent_file.name.endswith(".agent.md"):
        return {"path": str(agent_file), "status": "not_agent_md"}

    fm, raw, body = _读取frontmatter和正文(agent_file)
    if not fm:
        return {"path": str(agent_file), "status": "no_frontmatter"}

    name = str(fm.get("name") or agent_file.stem.replace(".agent", ""))

    # 检查是否已有 display_zh
    meta = fm.get("metadata")
    if isinstance(meta, dict) and meta.get("display_zh", "").strip():
        return {"path": str(agent_file), "name": name, "status": "already_has_display_zh",
                "display_zh": meta["display_zh"]}

    # 从文件名提取中文
    stem = agent_file.stem.replace(".agent", "")
    display_zh = _提取中文(stem)
    if not display_zh:
        display_zh = _提取中文(name)

    # 从 description 提取触发词
    desc = str(fm.get("description", ""))
    aliases = _提取触发词(desc)

    result = {
        "path": str(agent_file),
        "name": name,
        "status": "would_update" if dry_run else "updated",
        "display_zh": display_zh,
        "aliases_zh": aliases,
    }

    if dry_run:
        return result

    if not isinstance(meta, dict):
        meta = {}
    meta["display_zh"] = display_zh
    if aliases:
        meta["aliases_zh"] = ", ".join(aliases)
    fm["metadata"] = meta

    new_raw = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
    agent_file.write_text(f"---\n{new_raw.strip()}\n---\n{body}", encoding="utf-8")
    return result


def 批量回填(
    *,
    skill_roots: list[Path] | None = None,
    agent_roots: list[Path] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """批量回填所有技能和智能体。

    Args:
        skill_roots: 技能根目录列表。
        agent_roots: 智能体根目录列表。
        dry_run: 是否仅预览。

    Returns:
        统计结果。
    """
    if skill_roots is None:
        skill_roots = [r for r in 默认技能根目录 if r.is_dir()]
    if agent_roots is None:
        agent_roots = [r for r in 默认智能体根目录 if r.is_dir()]

    stats: dict[str, Any] = {
        "skills_scanned": 0,
        "skills_updated": 0,
        "skills_skipped": 0,
        "agents_scanned": 0,
        "agents_updated": 0,
        "agents_skipped": 0,
        "details": [],
        "dry_run": dry_run,
    }

    # 扫描技能
    for root in skill_roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith("."):
                continue
            detail = _回填单个技能(child, dry_run)
            stats["skills_scanned"] += 1
            if detail["status"] in ("would_update", "updated"):
                stats["skills_updated"] += 1
            else:
                stats["skills_skipped"] += 1
            stats["details"].append(detail)

    # 扫描智能体
    for root in agent_roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.name.endswith(".agent.md"):
                continue
            detail = _回填单个智能体(child, dry_run)
            stats["agents_scanned"] += 1
            if detail["status"] in ("would_update", "updated"):
                stats["agents_updated"] += 1
            else:
                stats["agents_skipped"] += 1
            stats["details"].append(detail)

    return stats


def main() -> int:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(description="批量回填 SKILL.md / .agent.md 的 metadata.display_zh")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际写入")
    parser.add_argument("--skill-root", action="append", default=[], help="技能根目录（可重复）")
    parser.add_argument("--agent-root", action="append", default=[], help="智能体根目录（可重复）")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    args = parser.parse_args()

    skill_roots = [Path(p) for p in args.skill_root] if args.skill_root else None
    agent_roots = [Path(p) for p in args.agent_root] if args.agent_root else None

    stats = 批量回填(skill_roots=skill_roots, agent_roots=agent_roots, dry_run=bool(args.dry_run))

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"\n批量回填 metadata.display_zh  {'[DRY-RUN]' if args.dry_run else ''}")
        print(f"  技能: 扫描 {stats['skills_scanned']}, "
              f"{'将更新' if args.dry_run else '已更新'} {stats['skills_updated']}, "
              f"跳过 {stats['skills_skipped']}")
        print(f"  智能体: 扫描 {stats['agents_scanned']}, "
              f"{'将更新' if args.dry_run else '已更新'} {stats['agents_updated']}, "
              f"跳过 {stats['agents_skipped']}")
        total_updated = stats["skills_updated"] + stats["agents_updated"]
        if total_updated > 0:
            print(f"\n  {'预览' if args.dry_run else '更新'}样例:")
            for d in stats["details"]:
                if d["status"] in ("would_update", "updated"):
                    print(f"    {Path(d['path']).name} → display_zh: {d['display_zh']}")
                    if d.get("aliases_zh"):
                        print(f"      aliases_zh: {', '.join(d['aliases_zh'][:5])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
