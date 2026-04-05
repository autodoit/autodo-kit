"""AOK 工具 CLI 入口。"""

from __future__ import annotations

import argparse
import json
from typing import Any

from autodokit.tools import get_tool, list_developer_tools, list_user_tools


def _parse_json(text: str) -> Any:
    """解析 JSON 文本。"""

    raw = str(text or "").strip()
    if not raw:
        return {}
    return json.loads(raw)


def main() -> int:
    """CLI 主入口。"""

    parser = argparse.ArgumentParser(prog="aok-tools", description="AOK 工具 CLI（直调函数）")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="列出工具")
    list_parser.add_argument("--scope", choices=["user", "developer", "all"], default="user")

    invoke_parser = sub.add_parser("call", help="按函数名调用工具")
    invoke_parser.add_argument("tool_name")
    invoke_parser.add_argument("--scope", choices=["user", "developer", "all"], default="user")
    invoke_parser.add_argument("--args", default="[]", help="JSON 数组参数")
    invoke_parser.add_argument("--kwargs", default="{}", help="JSON 对象参数")

    args = parser.parse_args()

    if args.command == "list":
        if args.scope == "user":
            rows = list_user_tools()
        elif args.scope == "developer":
            rows = list_developer_tools()
        else:
            rows = sorted(set(list_user_tools() + list_developer_tools()))
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.command == "call":
        call_args = _parse_json(args.args)
        call_kwargs = _parse_json(args.kwargs)
        if not isinstance(call_args, list):
            raise SystemExit("--args 必须是 JSON 数组")
        if not isinstance(call_kwargs, dict):
            raise SystemExit("--kwargs 必须是 JSON 对象")

        fn = get_tool(args.tool_name, scope=args.scope)
        result = fn(*call_args, **call_kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
