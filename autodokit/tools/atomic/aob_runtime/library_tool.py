#!/usr/bin/env python3
"""AOB CLI 路由层。共享基础设施已拆分到 aob_common.py。"""
from __future__ import annotations
from .aob_common import *
# --- items/tags 委托到 aob_items / aob_tags ---
from .aob_items import 读取_items, 写入_items, 写入关系表, 读取关系表, 同步_items, 执行_items
from .aob_tags import 执行_tags
# --- 聚合委托到 aob_aggregate ---
from .aob_aggregate import 执行聚合用户级内容, 聚合用户级内容
# --- 发布/备份/同步委托到对应工具模块 ---
from .aob_publish import 执行发布用户级内容, 发布用户级内容
from .aob_backup import 执行备份用户级内容, 备份用户级内容
from .aob_update import 执行更新用户级内容, 更新用户级内容
import argparse, json, sys
from pathlib import Path
from typing import Any
try:
    from .aob_sync_undo import 创建撤销账本 as _撤销账本
except Exception:
    _撤销账本 = None
try:
    from .aob_zh_index import 生成中文索引, 查询中文索引, 默认输出目录 as _默认zh输出目录
except Exception:
    生成中文索引 = None
    查询中文索引 = None
    _默认zh输出目录 = None
def _执行生成中文索引(argv: list[str], paths: 路径配置) -> int:
    """执行 generate-zh-index 子命令。"""
    parser = argparse.ArgumentParser(description="扫描技能/智能体的 metadata.display_zh 并生成中文索引")
    parser.add_argument("--source-root", action="append", default=[], help="源根目录（可重复）")
    parser.add_argument("--output-dir", default="", help="输出目录，默认 autodo-lib/datastore")
    parser.add_argument("--dry-run", action="store_true", help="仅显示统计，不写文件")
    args = parser.parse_args(argv)

    if 生成中文索引 is None:
        print("[ERROR] aob_zh_index 模块不可用", file=sys.stderr)
        return 2

    from pathlib import Path
    source_roots = [Path(p) for p in args.source_root] if args.source_root else None
    output_dir = Path(args.output_dir) if args.output_dir else (_默认zh输出目录 or Path("."))
    result = 生成中文索引(source_roots=source_roots, output_dir=output_dir, dry_run=bool(args.dry_run))
    print(f"索引{'预览' if args.dry_run else '已生成'}:")
    print(f"  技能: {result['skills_count']}, 智能体: {result['agents_count']}, 合计: {result['total']}")
    if not args.dry_run:
        print(f"  YAML: {result.get('output_yaml', 'N/A')}")
        print(f"  MD:   {result.get('output_md', 'N/A')}")
    return 0


def _执行查询中文索引(argv: list[str], paths: 路径配置) -> int:
    """执行 query-zh-index 子命令。"""
    parser = argparse.ArgumentParser(description="按中文关键词或分类查询技能/智能体索引")
    parser.add_argument("--source-root", action="append", default=[], help="源根目录（可重复）")
    parser.add_argument("--keyword", default="", help="关键词搜索")
    parser.add_argument("--category", default="", help="按分类筛选")
    parser.add_argument("--all", action="store_true", help="列出全部条目")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args(argv)

    if 查询中文索引 is None:
        print("[ERROR] aob_zh_index 模块不可用", file=sys.stderr)
        return 2

    from pathlib import Path
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
    sub.add_parser("generate-zh-index", help="扫描技能/智能体的 metadata.display_zh 并生成中文索引（yaml + md）")
    sub.add_parser("query-zh-index", help="按中文关键词或分类查询技能/智能体索引")
    sub.add_parser("flow-backup-aggregate", help="【流程】备份 → 聚合")
    sub.add_parser("flow-backup-publish", help="【流程】备份 → 发布")
    sub.add_parser("flow-backup-update", help="【流程】备份 → 同步")
    sub.add_parser("flow-aggregate-publish", help="【流程】聚合 → 发布")
    sub.add_parser("flow-full-sync", help="【流程】备份 → 聚合 → 发布 → 中文索引（一键全流程）")
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
        if args.command == "generate-zh-index":
            return _执行生成中文索引(list(passthrough), paths)
        if args.command == "query-zh-index":
            return _执行查询中文索引(list(passthrough), paths)
        if args.command == "flow-backup-aggregate":
            from .aob_flow_pipeline import _execute_flow_backup_aggregate
            return _execute_flow_backup_aggregate(list(passthrough), paths)
        if args.command == "flow-backup-publish":
            from .aob_flow_pipeline import _execute_flow_backup_publish
            return _execute_flow_backup_publish(list(passthrough), paths)
        if args.command == "flow-backup-update":
            from .aob_flow_pipeline import _execute_flow_backup_update
            return _execute_flow_backup_update(list(passthrough), paths)
        if args.command == "flow-aggregate-publish":
            from .aob_flow_pipeline import _execute_flow_aggregate_publish
            return _execute_flow_aggregate_publish(list(passthrough), paths)
        if args.command == "flow-full-sync":
            from .aob_flow_pipeline import _execute_flow_full_sync
            return _execute_flow_full_sync(list(passthrough), paths)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
