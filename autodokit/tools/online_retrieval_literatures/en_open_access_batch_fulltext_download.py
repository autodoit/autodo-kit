"""英文开放源批量原文下载工具（调用单篇下载工具）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .en_open_access_single_fulltext_download import _to_record, download_single


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_records(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.records_path:
        payload = _read_json(Path(args.records_path).expanduser().resolve())
        if not isinstance(payload, list):
            raise ValueError("records-path 必须是对象数组。")
        return [dict(item) for item in payload if isinstance(item, dict)]

    if args.records_json:
        payload = json.loads(args.records_json)
        if not isinstance(payload, list):
            raise ValueError("records-json 必须是对象数组。")
        return [dict(item) for item in payload if isinstance(item, dict)]

    raise ValueError("请至少提供 --records-path 或 --records-json。")


def download_batch(config: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    output_dir = Path(str(config.get("output_dir") or "sandbox/online_retrieval_debug/outputs/en_open_access/batch_single_calls")).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    limit = int(config.get("max_downloads") or len(records))
    results: list[dict[str, Any]] = []
    for index, item in enumerate(records[:limit], start=1):
        record = _to_record(item)
        run_config = dict(config)
        run_config["output_dir"] = str(output_dir / f"item_{index:04d}")
        results.append(download_single(run_config, record))

    summary = {
        "status": "PASS",
        "total_records": len(records),
        "executed_records": len(results),
        "pass_count": sum(1 for item in results if str((item.get("result") or {}).get("status") or "") == "PASS"),
        "blocked_count": sum(1 for item in results if str((item.get("result") or {}).get("status") or "") == "BLOCKED"),
        "results": results,
    }
    summary_path = output_dir / "batch_download_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="英文开放源批量原文下载（调用单篇下载）")
    parser.add_argument("--records-path", default="", help="对象数组 JSON 文件路径")
    parser.add_argument("--records-json", default="", help="对象数组 JSON 字符串")
    parser.add_argument("--output-dir", default="", help="输出目录")
    parser.add_argument("--max-downloads", type=int, default=0, help="最大下载条数，0 表示不限制")
    parser.add_argument("--bailian-api-key-file", default="", help="百炼 API key 文件路径")
    parser.add_argument("--download-request-timeout", type=int, default=12, help="下载超时秒数")
    parser.add_argument("--per-record-max-attempts", type=int, default=6, help="单条最大尝试次数")
    parser.add_argument("--enable-barrier-analysis", action="store_true", help="启用阻断页分析")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    records = _load_records(args)
    config = {
        "output_dir": args.output_dir,
        "max_downloads": args.max_downloads,
        "bailian_api_key_file": args.bailian_api_key_file,
        "download_request_timeout": args.download_request_timeout,
        "per_record_max_attempts": args.per_record_max_attempts,
        "enable_barrier_analysis": args.enable_barrier_analysis,
    }
    result = download_batch(config, records)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
