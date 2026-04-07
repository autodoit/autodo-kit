"""英文开放源批量 HTML 结构化抽取工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .en_open_access_single_html_extract import extract_single
from .retrieval_policy import evaluate_policy


def extract_batch(config: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """执行英文批量 HTML 抽取。"""

    output_dir = Path(str(config.get("output_dir") or "sandbox/online_retrieval_debug/outputs/en_open_access/batch_html")).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rules = dict(config.get("retrieval_rules") or {})

    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for idx, record in enumerate(records, start=1):
        decision = evaluate_policy(record, rules, channel="html_extract", source="en_open_access")
        if decision.skip:
            skipped.append(
                {
                    "index": idx,
                    "title": str(record.get("title") or ""),
                    "landing_url": str(record.get("landing_url") or ""),
                    "reason": decision.reason,
                    "matched_tokens": decision.matched_tokens,
                }
            )
            continue
        per_item_config = dict(config)
        per_item_config["output_dir"] = str((output_dir / f"item_{idx:04d}").resolve())
        results.append(extract_single(per_item_config, record))

    summary = {
        "status": "PASS",
        "total_records": len(records),
        "executed_records": len(results),
        "policy_skipped_records": len(skipped),
        "policy_skipped": skipped,
        "pass_count": sum(1 for item in results if str(item.get("status") or "") == "PASS"),
        "blocked_count": sum(1 for item in results if str(item.get("status") or "") == "BLOCKED"),
        "results": results,
    }
    summary_path = output_dir / "batch_html_extract_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary
