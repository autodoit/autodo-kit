"""中文 CNKI 单篇全文下载工具（PDF/CAJ）。"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from . import cnki_paged_retrieval as cnki
from .retrieval_policy import evaluate_policy
from playwright.sync_api import BrowserContext, Page, Playwright


def _prepare_item(config: dict[str, Any], page: Page) -> dict[str, Any]:
    detail_url = str(config.get("detail_url") or "").strip()
    if detail_url:
        return {
            "title": str(config.get("title") or ""),
            "authors": list(config.get("authors") or []),
            "journal": str(config.get("journal") or ""),
            "date": str(config.get("date") or ""),
            "href": detail_url,
            "exportId": str(config.get("export_id") or ""),
        }

    query = str(config.get("zh_query") or "").strip()
    if not query:
        raise ValueError("未提供 detail_url 且 zh_query 为空，无法定位单篇文献。")
    if not cnki._is_result_page(page):
        page.evaluate(cnki._build_submit_search_script(), {"query": query})
        cnki._wait_for_result_page(page)
    parsed = cnki._parse_current_page(page)
    for item in list(parsed.get("results") or []):
        href = cnki._normalize_text((item or {}).get("href"))
        database = cnki._normalize_text((item or {}).get("database"))
        if href and "外文" not in database:
            return dict(item)
    raise RuntimeError("未找到可下载的中文 CNKI 条目。")


def download_single(config: dict[str, Any]) -> dict[str, Any]:
    """下载单篇中文 CNKI 原文。"""

    rules = dict(config.get("retrieval_rules") or {})
    pre_record = {
        "title": str(config.get("title") or ""),
        "journal": str(config.get("journal") or ""),
        "date": str(config.get("date") or ""),
        "detail_url": str(config.get("detail_url") or ""),
    }
    pre_decision = evaluate_policy(pre_record, rules, channel="download", source="zh_cnki")
    if pre_decision.skip:
        return {
            "status": "SKIPPED",
            "reason": pre_decision.reason,
            "matched_tokens": pre_decision.matched_tokens,
            "query": str(config.get("zh_query") or ""),
            "search_item": pre_record,
            "record": {},
            "download": {},
            "output_paths": {},
            "manual_events": [],
        }

    project_root = cnki._resolve_project_root(config)
    output_dir = cnki._resolve_repo_path(
        project_root,
        config.get("zh_output_dir") or config.get("output_dir"),
        "sandbox/online_retrieval_debug/outputs/zh_cnki_single",
    )
    profile_dir = cnki._resolve_repo_path(
        project_root,
        (config.get("cnki_browser_config") or {}).get("user_data_dir"),
        "sandbox/runtime/web_brower_profiles/cnki_debug",
    )
    port = int(config.get("cnki_cdp_port") or 9222)
    cdp_url = str(config.get("cnki_cdp_url") or f"http://127.0.0.1:{port}")
    entry_url = str(config.get("cnki_entry_url") or "https://kns.cnki.net/kns8s/search")
    skip_launch = bool(config.get("cnki_skip_launch", False))
    keep_browser = bool(config.get("keep_browser_open", True))
    allow_manual = bool(config.get("allow_manual_intervention", True))
    bailian_api_key_file = str(
        cnki._resolve_repo_path(project_root, config.get("bailian_api_key_file"), "configs/bailian-api-key.txt")
        if config.get("bailian_api_key_file")
        else ""
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    browser_proc: subprocess.Popen[str] | None = None
    playwright: Playwright | None = None
    context: BrowserContext | None = None
    manual_events: list[dict[str, Any]] = []

    try:
        if not skip_launch:
            browser_proc = cnki._launch_edge_with_cdp(profile_dir=profile_dir, port=port, start_url=entry_url)
            time.sleep(2)
        try:
            playwright, context = cnki._connect_context(cdp_url)
        except Exception:
            if skip_launch:
                browser_proc = cnki._launch_edge_with_cdp(profile_dir=profile_dir, port=port, start_url=entry_url)
                time.sleep(2)
                playwright, context = cnki._connect_context(cdp_url)
            else:
                raise

        page = cnki._select_existing_page(context, preferred_url=entry_url)
        page.set_default_timeout(int((config.get("cnki_browser_config") or {}).get("timeout_ms") or 15000))
        manual_events.extend(cnki._wait_for_human_if_needed(page, bailian_api_key_file, allow_manual))

        blocked = cnki._detect_blocking_state(page)
        if blocked.get("reason") == "auth_client_invalid":
            return {
                "status": "BLOCKED",
                "error_type": "AuthClientInvalid",
                "error": blocked.get("message", "无效的 Client ID"),
                "manual_events": manual_events,
            }

        item = _prepare_item(config, page)
        return_url = page.url or entry_url
        record = cnki._process_record(context, page, item, output_dir, return_url)
        output_paths = cnki._write_outputs([record], output_dir)
        return {
            "status": record.get("status", "BLOCKED"),
            "query": str(config.get("zh_query") or ""),
            "search_item": record.get("search_item", item),
            "record": record.get("record", {}),
            "download": record.get("download", {}),
            "output_paths": output_paths,
            "manual_events": manual_events,
        }
    finally:
        if playwright is not None:
            playwright.stop()
        if browser_proc and not keep_browser:
            try:
                if browser_proc.poll() is None:
                    browser_proc.terminate()
                    time.sleep(1)
                    if browser_proc.poll() is None:
                        browser_proc.kill()
            except OSError:
                pass


def _load_debug_defaults(script_dir: Path) -> dict[str, Any]:
    path = script_dir / "debug_inputs.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    script_dir = Path(__file__).resolve().parent.parent
    defaults = _load_debug_defaults(script_dir)
    config = dict(defaults)
    if args.detail_url:
        config["detail_url"] = str(args.detail_url)
    if args.query:
        config["zh_query"] = str(args.query)
    if args.output_dir:
        config["output_dir"] = str(args.output_dir)
    if args.title:
        config["title"] = str(args.title)
    if args.journal:
        config["journal"] = str(args.journal)
    if args.date:
        config["date"] = str(args.date)
    if args.export_id:
        config["export_id"] = str(args.export_id)
    if args.skip_launch:
        config["cnki_skip_launch"] = True
    if args.keep_browser_open:
        config["keep_browser_open"] = True
    if args.cdp_url:
        config["cnki_cdp_url"] = str(args.cdp_url)
    if args.cdp_port:
        config["cnki_cdp_port"] = int(args.cdp_port)
    return config


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="中文 CNKI 单篇全文下载（PDF/CAJ）")
    parser.add_argument("--detail-url", default="", help="详情页 URL（优先）")
    parser.add_argument("--query", default="", help="未提供 detail-url 时用于定位单篇的检索词")
    parser.add_argument("--title", default="", help="可选标题")
    parser.add_argument("--journal", default="", help="可选期刊")
    parser.add_argument("--date", default="", help="可选日期")
    parser.add_argument("--export-id", default="", help="可选导出 ID")
    parser.add_argument("--output-dir", default="", help="输出目录")
    parser.add_argument("--cdp-url", default="", help="远程调试浏览器 CDP URL")
    parser.add_argument("--cdp-port", type=int, default=0, help="远程调试端口")
    parser.add_argument("--skip-launch", action="store_true", help="只接管现有浏览器")
    parser.add_argument("--keep-browser-open", action="store_true", help="结束后保留浏览器")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    result = download_single(build_config(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
