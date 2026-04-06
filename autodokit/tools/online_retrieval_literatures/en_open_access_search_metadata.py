"""英文开放源主题检索与题录导出工具。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .en_open_access_pipeline import run_pipeline as run_english_pipeline


def _load_defaults(script_dir: Path) -> dict[str, Any]:
    path = script_dir / "english_inputs.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    script_dir = Path(__file__).resolve().parent.parent
    config = dict(_load_defaults(script_dir))
    if args.query:
        config["query"] = str(args.query)
    if args.max_pages:
        config["max_pages"] = int(args.max_pages)
    if args.per_page:
        config["per_page"] = int(args.per_page)
    if args.output_dir:
        config["output_dir"] = str(args.output_dir)
    if args.sources:
        config["sources"] = [item.strip() for item in args.sources.split(",") if item.strip()]

    config["download_policy"] = "metadata-only"
    config["max_downloads"] = 0
    return config


def search_metadata(config: dict[str, Any]) -> dict[str, Any]:
    result = run_english_pipeline(config)
    return {
        "status": result.get("status", "BLOCKED"),
        "query": result.get("query", config.get("query", "")),
        "record_count": int(result.get("record_count") or 0),
        "source_runs": result.get("source_runs", []),
        "metadata_paths": result.get("metadata_paths", {}),
        "blocked_count": int(result.get("blocked_count") or 0),
        "error_type": result.get("error_type", ""),
        "error": result.get("error", ""),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="英文开放源主题检索与题录导出")
    parser.add_argument("--query", default="", help="检索主题词")
    parser.add_argument("--max-pages", type=int, default=0, help="每个来源最多页数")
    parser.add_argument("--per-page", type=int, default=0, help="每页条数")
    parser.add_argument("--sources", default="", help="来源列表，逗号分隔")
    parser.add_argument("--output-dir", default="", help="输出目录")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    result = search_metadata(build_config(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
