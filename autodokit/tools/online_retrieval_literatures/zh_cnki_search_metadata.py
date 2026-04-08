"""中文 CNKI 主题检索与题录导出工具。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .cnki_paged_retrieval import run_pipeline as run_cnki_pipeline


def _load_debug_defaults(script_dir: Path) -> dict[str, Any]:
    path = script_dir / "debug_inputs.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    script_dir = Path(__file__).resolve().parent.parent
    defaults = _load_debug_defaults(script_dir)
    config = dict(defaults)
    if args.query:
        config["zh_query"] = str(args.query)
    if args.max_pages:
        config["max_pages"] = int(args.max_pages)
    if args.output_dir:
        config["zh_output_dir"] = str(args.output_dir)
    if args.cdp_url:
        config["cnki_cdp_url"] = str(args.cdp_url)
    if args.cdp_port:
        config["cnki_cdp_port"] = int(args.cdp_port)
    if args.skip_launch:
        config["cnki_skip_launch"] = True
    if args.keep_browser_open:
        config["keep_browser_open"] = True
    if args.allow_manual_intervention is not None:
        config["allow_manual_intervention"] = bool(args.allow_manual_intervention)
    return config


def search_metadata(config: dict[str, Any]) -> dict[str, Any]:
    """执行中文主题检索并导出题录。"""

    result = run_cnki_pipeline(config)
    return {
        "status": result.get("status", "BLOCKED"),
        "query": result.get("query", config.get("zh_query", "")),
        "record_count": int(result.get("record_count") or 0),
        "page_summaries": result.get("page_summaries", []),
        "output_paths": result.get("output_paths", {}),
        "manual_events": result.get("manual_events", []),
        "error_type": result.get("error_type", ""),
        "error": result.get("error", ""),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="中文 CNKI 主题检索与题录导出")
    parser.add_argument("--query", default="", help="检索主题词")
    parser.add_argument("--max-pages", type=int, default=0, help="最多翻页数")
    parser.add_argument("--output-dir", default="", help="输出目录")
    parser.add_argument("--cdp-url", default="", help="远程调试浏览器 CDP URL")
    parser.add_argument("--cdp-port", type=int, default=0, help="远程调试端口")
    parser.add_argument("--skip-launch", action="store_true", help="只接管现有浏览器")
    parser.add_argument("--keep-browser-open", action="store_true", help="结束后保留浏览器")
    parser.add_argument(
        "--allow-manual-intervention",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否允许人工处理验证码/登录",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    result = search_metadata(build_config(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
