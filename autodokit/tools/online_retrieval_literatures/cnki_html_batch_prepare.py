"""CNKI HTML 阅读批处理预处理脚本。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from online_retrieval_literatures.cnki_html_reader_probe import (
    CNKI_DEBUG,
    _load_debug_inputs,
    _open_context,
    _resolve_repo_path,
    _select_working_page,
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _parse_tokens(raw_value: str) -> list[str]:
    raw_text = str(raw_value or "").strip()
    if raw_text in {"", "*", "ALL", "all", "NONE", "none"}:
        return []
    return [item.strip() for item in raw_text.split(",") if item.strip()]


def _slugify(value: str) -> str:
    return CNKI_DEBUG.slugify_filename(value)[:80]


def _build_manifest_entry(query: str, page_number: int, row_index: int, item: dict[str, Any], batch_index: int) -> dict[str, Any]:
    return {
        "batch_index": batch_index,
        "enabled": True,
        "priority": 0,
        "note": "",
        "tags": [],
        "reviewer": "",
        "query": query,
        "page": page_number,
        "row": row_index,
        "title": str(item.get("title") or "").strip(),
        "detail_url": str(item.get("href") or "").strip(),
        "journal": str(item.get("journal") or "").strip(),
        "date": str(item.get("date") or "").strip(),
        "database": str(item.get("database") or "").strip(),
        "authors": list(item.get("authors") or []),
        "citations": str(item.get("citations") or "").strip(),
        "downloads": str(item.get("downloads") or "").strip(),
    }


def _build_prepare_config(args: argparse.Namespace) -> dict[str, Any]:
    defaults = _load_debug_inputs()
    browser_config = dict(defaults.get("cnki_browser_config") or {})
    return {
        "query": str(args.query or defaults.get("zh_query") or "系统性风险"),
        "entry_url": str(args.entry_url or defaults.get("cnki_entry_url") or "https://kns.cnki.net/kns8s/search"),
        "cdp_url": str(args.cdp_url or defaults.get("cnki_cdp_url") or f"http://127.0.0.1:{int(defaults.get('cnki_cdp_port') or 9222)}"),
        "cdp_port": int(args.cdp_port or defaults.get("cnki_cdp_port") or 9222),
        "skip_launch": bool(args.skip_launch),
        "keep_browser_open": bool(args.keep_browser_open),
        "timeout_ms": int(args.timeout_ms or browser_config.get("timeout_ms") or 15000),
        "user_data_dir": _resolve_repo_path(browser_config.get("user_data_dir"), "sandbox/runtime/web_brower_profiles/cnki_debug"),
        "output_root": _resolve_repo_path(args.output_dir, "sandbox/online_retrieval_debug/outputs/cnki_reader_batches"),
        "max_pages": max(int(args.max_pages or 1), 1),
        "max_results": max(int(args.max_results or 20), 1),
        "include_database_tokens": _parse_tokens(args.include_database_tokens or "学术期刊,中国学术期刊,学位论文"),
        "exclude_database_tokens": _parse_tokens(args.exclude_database_tokens or "外文"),
    }


def _accept_result(item: dict[str, Any], include_tokens: list[str], exclude_tokens: list[str]) -> bool:
    database = str(item.get("database") or "")
    if exclude_tokens and any(token in database for token in exclude_tokens):
        return False
    if include_tokens and not any(token in database for token in include_tokens):
        return False
    return bool(str(item.get("href") or "").strip())


def prepare_batch_manifest(config: dict[str, Any]) -> dict[str, Any]:
    output_root = Path(config["output_root"]).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    playwright = None
    context = None
    browser_proc = None
    manual_events: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    try:
        playwright, context, browser_proc = _open_context(config)
        page = _select_working_page(context, config)
        page.goto(str(config["entry_url"]), wait_until="domcontentloaded")
        manual_events.extend(CNKI_DEBUG._wait_for_human_if_needed(page, "", True))
        if not CNKI_DEBUG._is_result_page(page):
            page.evaluate(CNKI_DEBUG._build_submit_search_script(), {"query": config["query"]})
            CNKI_DEBUG._wait_for_result_page(page)

        for _ in range(int(config["max_pages"])):
            manual_events.extend(CNKI_DEBUG._wait_for_human_if_needed(page, "", True))
            parsed = CNKI_DEBUG._parse_current_page(page)
            page_number = int(parsed.get("current_page") or 1)
            results = list(parsed.get("results") or [])
            for row_index, item in enumerate(results, start=1):
                if len(entries) >= int(config["max_results"]):
                    break
                if not _accept_result(item, list(config["include_database_tokens"]), list(config["exclude_database_tokens"])):
                    continue
                detail_url = str(item.get("href") or "").strip()
                if not detail_url or detail_url in seen_urls:
                    continue
                seen_urls.add(detail_url)
                entries.append(_build_manifest_entry(config["query"], page_number, row_index, item, len(entries) + 1))
            if len(entries) >= int(config["max_results"]):
                break
            if not parsed.get("has_next"):
                break
            before_page = f"{parsed.get('current_page') or 1}/{parsed.get('total_pages') or 1}"
            page.evaluate(CNKI_DEBUG._build_next_page_script(), {"beforePage": before_page})
            CNKI_DEBUG._wait_for_result_page(page)
            CNKI_DEBUG._human_pause(page)

        batch_dir = (output_root / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(config['query'])}").resolve()
        batch_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "manifest_schema_version": 2,
            "query": config["query"],
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "entry_url": config["entry_url"],
            "max_pages": config["max_pages"],
            "max_results": config["max_results"],
            "include_database_tokens": list(config["include_database_tokens"]),
            "exclude_database_tokens": list(config["exclude_database_tokens"]),
            "screening_fields": {
                "enabled": "是否纳入批量导出；false 时默认跳过",
                "priority": "人工优先级；数值越大越优先导出",
                "note": "人工备注；可记录筛选理由、主题标签或问题说明",
                "tags": "人工标签；用于主题筛选、批次分组或后续检索",
                "reviewer": "人工审核人；用于回查是谁做的筛选决策",
            },
            "manual_events": manual_events,
            "entry_count": len(entries),
            "entries": entries,
        }
        _write_json(batch_dir / "manifest.json", manifest)
        _write_jsonl(batch_dir / "manifest.jsonl", entries)
        return {
            "status": "PASS",
            "batch_dir": str(batch_dir),
            "manifest_path": str((batch_dir / "manifest.json").resolve()),
            "manifest_jsonl_path": str((batch_dir / "manifest.jsonl").resolve()),
            "entry_count": len(entries),
        }
    finally:
        if playwright is not None:
            playwright.stop()
        if browser_proc is not None and not config["keep_browser_open"]:
            try:
                if browser_proc.poll() is None:
                    browser_proc.terminate()
            except OSError:
                pass


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CNKI HTML 阅读批处理预处理")
    parser.add_argument("--query", default="", help="检索词")
    parser.add_argument("--max-pages", type=int, default=2, help="最多抓取多少页结果")
    parser.add_argument("--max-results", type=int, default=20, help="最多写入多少条详情页任务")
    parser.add_argument("--include-database-tokens", default="学术期刊,中国学术期刊,学位论文", help="仅保留这些数据库标签，逗号分隔；传 * 表示不过滤")
    parser.add_argument("--exclude-database-tokens", default="外文", help="排除这些数据库标签，逗号分隔；传 * 表示不过滤")
    parser.add_argument("--output-dir", default="", help="批处理输出根目录")
    parser.add_argument("--entry-url", default="", help="CNKI 检索入口 URL")
    parser.add_argument("--cdp-url", default="", help="已启动浏览器的 CDP URL")
    parser.add_argument("--cdp-port", type=int, default=0, help="远程调试端口")
    parser.add_argument("--timeout-ms", type=int, default=0, help="页面默认超时毫秒数")
    parser.add_argument("--skip-launch", action="store_true", help="只接管现有远程调试浏览器")
    parser.add_argument("--keep-browser-open", action="store_true", help="脚本结束后保留自动启动的浏览器")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    result = prepare_batch_manifest(_build_prepare_config(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()