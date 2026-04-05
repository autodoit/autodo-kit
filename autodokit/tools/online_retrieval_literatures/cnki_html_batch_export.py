"""CNKI HTML 阅读批量文章包导出脚本。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from online_retrieval_literatures.cnki_html_reader_probe import _build_probe_config, _open_context, run_probe_in_context


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_enabled(entry: dict[str, Any]) -> bool:
    value = entry.get("enabled", True)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _priority_value(entry: dict[str, Any]) -> int:
    try:
        return int(entry.get("priority", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_manifest_entry(entry: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(entry)
    normalized.setdefault("enabled", True)
    normalized.setdefault("priority", 0)
    normalized.setdefault("note", "")
    normalized.setdefault("tags", [])
    normalized.setdefault("reviewer", "")
    return normalized


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CNKI HTML 阅读批量文章包导出")
    parser.add_argument("--manifest", required=True, help="由 cnki_html_batch_prepare.py 生成的 manifest.json")
    parser.add_argument("--output-dir", default="", help="文章包输出根目录")
    parser.add_argument("--start-index", type=int, default=1, help="从 manifest 的第几条开始，1-based")
    parser.add_argument("--limit", type=int, default=0, help="最多导出多少条，0 表示不限制")
    parser.add_argument("--resume", action="store_true", help="若已有 batch_export_summary.json，则跳过已成功导出的详情页")
    parser.add_argument("--cdp-url", default="", help="已启动浏览器的 CDP URL")
    parser.add_argument("--cdp-port", type=int, default=0, help="远程调试端口")
    parser.add_argument("--timeout-ms", type=int, default=0, help="页面默认超时毫秒数")
    parser.add_argument("--skip-launch", action="store_true", help="只接管现有远程调试浏览器")
    parser.add_argument("--keep-browser-open", action="store_true", help="脚本结束后保留自动启动的浏览器")
    return parser


def export_batch(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = _load_json(manifest_path)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else (manifest_path.parent / "exports").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "batch_export_summary.json"

    summary: dict[str, Any]
    if args.resume and summary_path.exists():
        summary = _load_json(summary_path)
    else:
        summary = {
            "manifest_path": str(manifest_path),
            "query": manifest.get("query") or "",
            "manifest_schema_version": manifest.get("manifest_schema_version") or 1,
            "results": [],
        }
    completed_urls = {
        str(item.get("detail_url") or "")
        for item in list(summary.get("results") or [])
        if str(item.get("status") or "") == "PASS"
    }

    base_args = argparse.Namespace(
        query=str(manifest.get("query") or ""),
        detail_url="",
        result_index=0,
        prefer_database_tokens="学术期刊,中国学术期刊,学位论文",
        output_dir=str(output_dir),
        entry_url="",
        cdp_url=args.cdp_url,
        cdp_port=args.cdp_port,
        timeout_ms=args.timeout_ms,
        skip_launch=args.skip_launch,
        keep_browser_open=args.keep_browser_open,
    )
    runtime_config = _build_probe_config(base_args)

    playwright = None
    context = None
    browser_proc = None
    try:
        playwright, context, browser_proc = _open_context(runtime_config)
        entries = [_normalize_manifest_entry(item) for item in list(manifest.get("entries") or [])]
        sliced = entries[max(int(args.start_index) - 1, 0):]
        if int(args.limit or 0) > 0:
            sliced = sliced[: int(args.limit)]
        ordered_entries = sorted(
            sliced,
            key=lambda item: (-_priority_value(item), int(item.get("batch_index") or 0)),
        )

        skipped_disabled: list[dict[str, Any]] = []

        for offset, entry in enumerate(ordered_entries, start=max(int(args.start_index), 1)):
            detail_url = str(entry.get("detail_url") or "").strip()
            if not detail_url:
                continue
            if not _is_enabled(entry):
                skipped_disabled.append(
                    {
                        "batch_index": int(entry.get("batch_index") or offset),
                        "title": str(entry.get("title") or ""),
                        "detail_url": detail_url,
                        "priority": _priority_value(entry),
                        "note": str(entry.get("note") or ""),
                        "tags": list(entry.get("tags") or []),
                        "reviewer": str(entry.get("reviewer") or ""),
                        "status": "SKIPPED_DISABLED",
                    }
                )
                continue
            if args.resume and detail_url in completed_urls:
                continue
            config = dict(runtime_config)
            config.update(
                {
                    "query": str(entry.get("title") or entry.get("query") or manifest.get("query") or "CNKI HTML"),
                    "detail_url": detail_url,
                    "result_index": 0,
                    "output_root": output_dir,
                }
            )
            result = run_probe_in_context(context, config, output_dir)
            summary_record = {
                "batch_index": int(entry.get("batch_index") or offset),
                "title": str(entry.get("title") or ""),
                "detail_url": detail_url,
                "enabled": _is_enabled(entry),
                "priority": _priority_value(entry),
                "note": str(entry.get("note") or ""),
                "tags": list(entry.get("tags") or []),
                "reviewer": str(entry.get("reviewer") or ""),
                "status": str(result.get("status") or ""),
                "package_root": str((result.get("article_package") or {}).get("package_root") or ""),
                "bundle_path": str((result.get("article_package") or {}).get("bundle_path") or ""),
                "chapter_count": int((result.get("article_package") or {}).get("chapter_count") or 0),
                "paragraph_count": int((result.get("article_package") or {}).get("paragraph_count") or 0),
                "image_count": int((result.get("article_package") or {}).get("image_count") or 0),
                "table_count": int((result.get("article_package") or {}).get("table_count") or 0),
                "run_dir": str((result.get("artifacts") or {}).get("run_dir") or ""),
            }
            summary.setdefault("results", []).append(summary_record)
            summary["skipped_disabled"] = skipped_disabled
            _write_json(summary_path, summary)

        summary["result_count"] = len(list(summary.get("results") or []))
        summary["skipped_disabled_count"] = len(skipped_disabled)
        summary["skipped_disabled"] = skipped_disabled
        _write_json(summary_path, summary)
        return {
            "status": "PASS",
            "summary_path": str(summary_path),
            "result_count": summary["result_count"],
            "skipped_disabled_count": summary["skipped_disabled_count"],
        }
    finally:
        if playwright is not None:
            playwright.stop()
        if browser_proc is not None and not runtime_config["keep_browser_open"]:
            try:
                if browser_proc.poll() is None:
                    browser_proc.terminate()
            except OSError:
                pass


def main() -> None:
    args = _build_arg_parser().parse_args()
    result = export_batch(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()