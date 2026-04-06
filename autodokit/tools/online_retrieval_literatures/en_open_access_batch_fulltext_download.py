"""英文开放源批量原文下载工具（调用单篇下载工具）。"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .retrieval_policy import evaluate_policy
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


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sample_delay(min_seconds: float, max_seconds: float) -> float:
    lower = max(float(min_seconds), 0.0)
    upper = max(float(max_seconds), lower)
    if upper == lower:
        return lower
    return random.uniform(lower, upper)


def download_batch(config: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    output_dir = Path(str(config.get("output_dir") or "sandbox/online_retrieval_debug/outputs/en_open_access/batch_single_calls")).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    activity_log_path = output_dir / "batch_download_activity.jsonl"

    limit = int(config.get("max_downloads") or len(records))
    min_inter_record_delay = float(config.get("min_inter_record_delay_seconds") or 2.8)
    max_inter_record_delay = float(config.get("max_inter_record_delay_seconds") or 7.4)
    pause_every_records = max(int(config.get("pause_every_records") or 7), 0)
    min_pause_delay = float(config.get("min_pause_delay_seconds") or 11.0)
    max_pause_delay = float(config.get("max_pause_delay_seconds") or 23.0)
    rules = dict(config.get("retrieval_rules") or {})
    results: list[dict[str, Any]] = []
    skipped_by_policy: list[dict[str, Any]] = []
    for index, item in enumerate(records[:limit], start=1):
        decision = evaluate_policy(item, rules, channel="download", source="en_open_access")
        if decision.skip:
            skipped_by_policy.append(
                {
                    "index": index,
                    "title": str(item.get("title") or ""),
                    "doi": str(item.get("doi") or ""),
                    "reason": decision.reason,
                    "matched_tokens": decision.matched_tokens,
                }
            )
            _append_jsonl(
                activity_log_path,
                {
                    "ts": _utc_now(),
                    "event": "record_skipped_by_policy",
                    "index": index,
                    "title": str(item.get("title") or ""),
                    "reason": decision.reason,
                    "matched_tokens": decision.matched_tokens,
                },
            )
            continue
        record = _to_record(item)
        run_config = dict(config)
        run_config["output_dir"] = str(output_dir / f"item_{index:04d}")
        started_at = time.perf_counter()
        _append_jsonl(
            activity_log_path,
            {
                "ts": _utc_now(),
                "event": "record_start",
                "index": index,
                "title": record.title,
                "source": record.source,
                "doi": record.doi,
            },
        )
        result = download_single(run_config, record)
        results.append(result)
        finished_at = time.perf_counter()
        _append_jsonl(
            activity_log_path,
            {
                "ts": _utc_now(),
                "event": "record_end",
                "index": index,
                "title": record.title,
                "source": record.source,
                "doi": record.doi,
                "status": str((result.get("result") or {}).get("status") or result.get("status") or "BLOCKED"),
                "duration_seconds": round(finished_at - started_at, 3),
                "saved_path": str(((result.get("result") or {}).get("saved_path") or "")),
                "output_path": str(result.get("output_path") or ""),
            },
        )

        if index >= limit:
            continue

        delay_seconds = round(_sample_delay(min_inter_record_delay, max_inter_record_delay), 3)
        _append_jsonl(
            activity_log_path,
            {
                "ts": _utc_now(),
                "event": "sleep_between_records",
                "index": index,
                "sleep_seconds": delay_seconds,
            },
        )
        time.sleep(delay_seconds)

        if pause_every_records > 0 and index % pause_every_records == 0 and index < limit:
            pause_seconds = round(_sample_delay(min_pause_delay, max_pause_delay), 3)
            _append_jsonl(
                activity_log_path,
                {
                    "ts": _utc_now(),
                    "event": "human_like_pause",
                    "index": index,
                    "sleep_seconds": pause_seconds,
                },
            )
            time.sleep(pause_seconds)

    summary = {
        "status": "PASS",
        "total_records": len(records),
        "executed_records": len(results),
        "policy_skipped_records": len(skipped_by_policy),
        "policy_skipped": skipped_by_policy,
        "pass_count": sum(1 for item in results if str((item.get("result") or {}).get("status") or "") == "PASS"),
        "blocked_count": sum(1 for item in results if str((item.get("result") or {}).get("status") or "") == "BLOCKED"),
        "no_open_pdf_count": sum(1 for item in results if str((item.get("result") or {}).get("status") or "") == "NO_OPEN_PDF"),
        "activity_log_path": str(activity_log_path),
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
    parser.add_argument("--min-request-delay-seconds", type=float, default=0.35, help="单条内部请求最小随机等待秒数")
    parser.add_argument("--max-request-delay-seconds", type=float, default=1.6, help="单条内部请求最大随机等待秒数")
    parser.add_argument("--min-inter-record-delay-seconds", type=float, default=2.8, help="批量下载条目间最小随机等待秒数")
    parser.add_argument("--max-inter-record-delay-seconds", type=float, default=7.4, help="批量下载条目间最大随机等待秒数")
    parser.add_argument("--pause-every-records", type=int, default=7, help="每处理多少条插入一次更长停顿，0 表示关闭")
    parser.add_argument("--min-pause-delay-seconds", type=float, default=11.0, help="长停顿最小秒数")
    parser.add_argument("--max-pause-delay-seconds", type=float, default=23.0, help="长停顿最大秒数")
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
        "min_request_delay_seconds": args.min_request_delay_seconds,
        "max_request_delay_seconds": args.max_request_delay_seconds,
        "min_inter_record_delay_seconds": args.min_inter_record_delay_seconds,
        "max_inter_record_delay_seconds": args.max_inter_record_delay_seconds,
        "pause_every_records": args.pause_every_records,
        "min_pause_delay_seconds": args.min_pause_delay_seconds,
        "max_pause_delay_seconds": args.max_pause_delay_seconds,
        "enable_barrier_analysis": args.enable_barrier_analysis,
    }
    result = download_batch(config, records)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
