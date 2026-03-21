"""IDE 运行按钮通用脚本。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autodokit.tools import get_tool


def main() -> int:
    """读取参数文件并按工具名调用函数。"""

    parser = argparse.ArgumentParser(description="AOK 通用 Runner")
    parser.add_argument("--params", required=True, help="参数 JSON 文件路径")
    args = parser.parse_args()

    params_file = Path(args.params).expanduser().resolve()
    if not params_file.exists():
        raise SystemExit(f"参数文件不存在：{params_file}")

    payload = json.loads(params_file.read_text(encoding="utf-8"))
    tool_name = str(payload.get("tool_name") or payload.get("capability_id") or "").strip()
    if not tool_name:
        raise SystemExit("参数文件缺少 tool_name")

    scope = str(payload.get("scope") or "user").strip() or "user"
    call_args = payload.get("args", [])
    call_kwargs = payload.get("kwargs", {})
    if not isinstance(call_args, list):
        raise SystemExit("参数字段 args 必须为列表")
    if not isinstance(call_kwargs, dict):
        raise SystemExit("参数字段 kwargs 必须为字典")

    fn = get_tool(tool_name, scope=scope)
    result = fn(*call_args, **call_kwargs)
    print(json.dumps({"status": "success", "tool_name": tool_name, "data": result}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
