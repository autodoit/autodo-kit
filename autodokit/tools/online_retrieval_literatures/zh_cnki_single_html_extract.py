"""中文 CNKI 单篇 HTML 试读抽取工具。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .cnki_html_reader_probe import _build_probe_config, run_probe


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    """构造单篇 HTML 抽取配置。"""

    script_dir = Path(__file__).resolve().parent.parent
    defaults_path = script_dir / "debug_inputs.json"
    defaults: dict[str, Any] = json.loads(defaults_path.read_text(encoding="utf-8")) if defaults_path.exists() else {}
    merged = argparse.Namespace(**defaults)
    for key, value in vars(args).items():
        if value not in (None, "", 0, False):
            setattr(merged, key, value)
    return _build_probe_config(merged)


def extract_single(config: dict[str, Any]) -> dict[str, Any]:
    """执行单篇 HTML 阅读抽取。"""

    result = run_probe(config)
    return {
        "status": result.get("status", "BLOCKED"),
        "query": result.get("query", ""),
        "selected_result": result.get("selected_result", {}),
        "detail_record_bundle": result.get("detail_record_bundle", {}),
        "article_package": result.get("article_package", {}),
        "artifacts": result.get("artifacts", {}),
        "manual_events": result.get("manual_events", []),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="中文 CNKI 单篇 HTML 试读抽取")
    parser.add_argument("--query", default="", help="检索词（未提供 detail-url 时使用）")
    parser.add_argument("--detail-url", default="", help="直接指定详情页 URL")
    parser.add_argument("--result-index", type=int, default=0, help="检索结果索引，从 0 开始")
    parser.add_argument("--prefer-database-tokens", default="学术期刊,中国学术期刊,学位论文", help="优先数据库标签")
    parser.add_argument("--output-dir", default="", help="输出目录")
    parser.add_argument("--entry-url", default="", help="CNKI 入口 URL")
    parser.add_argument("--cdp-url", default="", help="远程调试浏览器 CDP URL")
    parser.add_argument("--cdp-port", type=int, default=0, help="远程调试端口")
    parser.add_argument("--timeout-ms", type=int, default=0, help="页面超时（毫秒）")
    parser.add_argument("--skip-launch", action="store_true", help="只接管现有浏览器")
    parser.add_argument("--keep-browser-open", action="store_true", help="结束后保留浏览器")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    result = extract_single(build_config(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
