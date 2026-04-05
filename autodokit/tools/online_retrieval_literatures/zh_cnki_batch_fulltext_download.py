"""中文 CNKI 批量全文下载工具（调用单篇下载工具）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .zh_cnki_single_fulltext_download import download_single


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_entries(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.manifest:
        manifest = _read_json(Path(args.manifest).expanduser().resolve())
        rows = list(manifest.get("entries") or [])
        return [
            {
                "detail_url": str(item.get("detail_url") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "journal": str(item.get("journal") or "").strip(),
                "date": str(item.get("date") or "").strip(),
                "enabled": bool(item.get("enabled", True)),
            }
            for item in rows
            if str(item.get("detail_url") or "").strip()
        ]

    if args.items_json:
        payload = _read_json(Path(args.items_json).expanduser().resolve())
        if not isinstance(payload, list):
            raise ValueError("items-json 必须是数组 JSON。")
        return [dict(item) for item in payload if isinstance(item, dict)]

    if args.detail_urls:
        return [{"detail_url": item.strip(), "enabled": True} for item in args.detail_urls.split(",") if item.strip()]

    raise ValueError("请至少提供 --manifest、--items-json 或 --detail-urls 之一。")


def download_batch(config: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    output_dir = Path(str(config.get("output_dir") or "sandbox/online_retrieval_debug/outputs/zh_cnki_batch_single_calls")).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    skipped = 0
    for index, entry in enumerate(entries, start=1):
        if not bool(entry.get("enabled", True)):
            skipped += 1
            continue
        run_config = dict(config)
        run_config.update(
            {
                "detail_url": str(entry.get("detail_url") or "").strip(),
                "title": str(entry.get("title") or "").strip(),
                "journal": str(entry.get("journal") or "").strip(),
                "date": str(entry.get("date") or "").strip(),
                "output_dir": str(output_dir / f"item_{index:04d}"),
            }
        )
        results.append(download_single(run_config))

    summary = {
        "status": "PASS",
        "total_entries": len(entries),
        "executed_entries": len(results),
        "skipped_entries": skipped,
        "pass_count": sum(1 for item in results if str(item.get("download", {}).get("status") or "") == "PASS"),
        "results": results,
    }
    summary_path = output_dir / "batch_download_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="中文 CNKI 批量全文下载（调用单篇下载）")
    parser.add_argument("--manifest", default="", help="manifest.json（优先读取 entries[].detail_url）")
    parser.add_argument("--items-json", default="", help="自定义数组 JSON")
    parser.add_argument("--detail-urls", default="", help="逗号分隔的 detail_url 列表")
    parser.add_argument("--output-dir", default="", help="输出目录")
    parser.add_argument("--cdp-url", default="", help="远程调试浏览器 CDP URL")
    parser.add_argument("--cdp-port", type=int, default=0, help="远程调试端口")
    parser.add_argument("--skip-launch", action="store_true", help="只接管现有浏览器")
    parser.add_argument("--keep-browser-open", action="store_true", help="结束后保留浏览器")
    return parser


def _build_config(args: argparse.Namespace) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if args.output_dir:
        config["output_dir"] = str(args.output_dir)
    if args.cdp_url:
        config["cnki_cdp_url"] = str(args.cdp_url)
    if args.cdp_port:
        config["cnki_cdp_port"] = int(args.cdp_port)
    if args.skip_launch:
        config["cnki_skip_launch"] = True
    if args.keep_browser_open:
        config["keep_browser_open"] = True
    return config


def main() -> None:
    args = _build_arg_parser().parse_args()
    entries = _load_entries(args)
    result = download_batch(_build_config(args), entries)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
