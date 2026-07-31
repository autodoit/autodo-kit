# -*- coding: utf-8 -*-
"""AOB 标签管理（tags 子命令）。

本模块负责场景标签与关系表的查询、设置、导入导出。
所有函数从 library_tool.py 等价提取，CLI 接口 100% 向后兼容。
"""

from __future__ import annotations

from .aob_common import *

import argparse
import json
import sys
from typing import Any

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
