"""在线检索下载路由工具。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .en_open_access_batch_fulltext_download import download_batch as en_batch_download
from .en_open_access_search_metadata import search_metadata as en_search_metadata
from .en_open_access_pipeline import run_pipeline as run_english_pipeline
from .en_open_access_single_fulltext_download import _to_record as en_to_record
from .en_open_access_single_fulltext_download import download_single as en_single_download
from .cnki_paged_retrieval import run_pipeline as run_cnki_pipeline
from .zh_cnki_batch_fulltext_download import download_batch as zh_batch_download
from .zh_cnki_batch_html_extract import extract_batch as zh_batch_html
from .zh_cnki_search_metadata import search_metadata as zh_search_metadata
from .zh_cnki_single_fulltext_download import download_single as zh_single_download
from .zh_cnki_single_html_extract import extract_single as zh_single_html


def _safe_run(func: Any, config: dict[str, Any]) -> dict[str, Any]:
    try:
        return func(config)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "BLOCKED",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }


def _load_debug_inputs(script_dir: Path) -> dict[str, Any]:
    input_path = script_dir / "debug_inputs.json"
    return json.loads(input_path.read_text(encoding="utf-8"))


def _build_english_config(inputs: dict[str, Any], script_dir: Path) -> dict[str, Any]:
    config: dict[str, Any] = {
        "query": str(inputs.get("en_query") or ""),
        "max_pages": int(inputs.get("max_pages") or 1),
        "per_page": int(inputs.get("en_per_page") or 20),
        "output_dir": str(inputs.get("en_output_dir") or ""),
        "sources": [item.strip() for item in str(inputs.get("en_sources") or "openalex,crossref,europe_pmc,arxiv").split(",") if item.strip()],
        "download_policy": str(inputs.get("en_download_policy") or "download"),
        "max_downloads": int(inputs.get("en_max_downloads") or 0),
    }
    if inputs.get("bailian_api_key_file"):
        config["bailian_api_key_file"] = str(inputs.get("bailian_api_key_file"))
    return config


def _evaluate_targets(cnki_result: dict[str, Any], english_result: dict[str, Any]) -> dict[str, Any]:
    zh_record_count = int(cnki_result.get("record_count") or 0)
    zh_download_count = int(cnki_result.get("download_count") or 0)
    en_record_count = int(english_result.get("record_count") or 0)
    en_download_count = int(english_result.get("download_count") or 0)

    zh_status = "PASS" if zh_record_count > 0 else str(cnki_result.get("status") or "BLOCKED")
    zh_download_status = "PASS" if zh_download_count > 0 else ("MANUAL_REQUIRED" if cnki_result.get("manual_events") else "BLOCKED")
    en_status = "PASS" if en_record_count > 0 else str(english_result.get("status") or "BLOCKED")
    en_download_status = "PASS" if en_download_count > 0 else ("BLOCKED" if english_result.get("blocked_count") else "NO_OPEN_PDF")

    return {
        "target_1_zh_bib_paged": {
            "status": zh_status,
            "reason": f"已处理 {zh_record_count} 条中文记录，分页摘要 {len(cnki_result.get('page_summaries') or [])} 页。",
        },
        "target_2_zh_fulltext_download": {
            "status": zh_download_status,
            "reason": f"已下载 {zh_download_count} 个中文全文文件；若存在人工事件，浏览器会保持打开供继续处理。",
        },
        "target_3_en_bib_paged": {
            "status": en_status,
            "reason": f"开放源已合并 {en_record_count} 条英文记录，来源数 {len(english_result.get('source_runs') or [])}。",
        },
        "target_4_en_fulltext_download": {
            "status": en_download_status,
            "reason": f"开放获取全文下载 {en_download_count} 条，阻断 {int(english_result.get('blocked_count') or 0)} 条。",
        },
    }


def _safe_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_markdown_summary(path: Path, inputs: dict[str, Any], targets: dict[str, Any]) -> None:
    lines = [
        "# 在线检索与下载调试总结",
        "",
        "## 调试输入",
        f"- 中文主题词：{inputs.get('zh_query', '')}",
        f"- 英文主题词：{inputs.get('en_query', '')}",
        f"- 最大翻页数：{inputs.get('max_pages', '')}",
        f"- 尝试真实 CNKI 检索：{inputs.get('attempt_real_cnki_search', False)}",
        "",
        "## 四项目标判定",
    ]
    for key, value in targets.items():
        lines.append(f"- {key}: {value.get('status')} - {value.get('reason')}")
    lines.extend(
        [
            "",
            "## 人工介入说明",
            "- CNKI 链在遇到登录或验证码时会优先调用百炼分析页面文本，并保留浏览器窗口等待人工继续。",
            "- 英文链只使用无需登录的开放源与 OA 链接，不主动进入付费库。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_full_debug(script_dir: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    inputs = _load_debug_inputs(script_dir)
    if payload:
        inputs.update(payload)
    cnki_result = _safe_run(run_cnki_pipeline, inputs)
    english_result = _safe_run(run_english_pipeline, _build_english_config(inputs, script_dir))
    targets = _evaluate_targets(cnki_result, english_result)

    _safe_json_write(
        script_dir / "zh_retrieval_debug.json",
        {
            "status": cnki_result.get("status", "BLOCKED"),
            "query": cnki_result.get("query", inputs.get("zh_query", "")),
            "page_summaries": cnki_result.get("page_summaries", []),
            "record_count": cnki_result.get("record_count", 0),
            "manual_events": cnki_result.get("manual_events", []),
            "output_paths": cnki_result.get("output_paths", {}),
            "error_type": cnki_result.get("error_type", ""),
            "error": cnki_result.get("error", ""),
        },
    )
    _safe_json_write(
        script_dir / "zh_download_debug.json",
        {
            "status": cnki_result.get("status", "BLOCKED"),
            "download_count": cnki_result.get("download_count", 0),
            "records": [
                {
                    "title": ((item.get("record") or {}).get("title") or ((item.get("search_item") or {}).get("title") or "")),
                    "download": item.get("download", {}),
                }
                for item in cnki_result.get("records", [])
            ],
            "browser": cnki_result.get("browser", {}),
        },
    )
    _safe_json_write(
        script_dir / "en_retrieval_debug.json",
        {
            "status": english_result.get("status", "BLOCKED"),
            "query": english_result.get("query", inputs.get("en_query", "")),
            "source_runs": english_result.get("source_runs", []),
            "record_count": english_result.get("record_count", 0),
            "metadata_paths": english_result.get("metadata_paths", {}),
            "error_type": english_result.get("error_type", ""),
            "error": english_result.get("error", ""),
        },
    )
    _safe_json_write(
        script_dir / "en_download_debug.json",
        {
            "status": english_result.get("status", "BLOCKED"),
            "download_count": english_result.get("download_count", 0),
            "blocked_count": english_result.get("blocked_count", 0),
            "manifest": english_result.get("manifest", []),
            "download_paths": english_result.get("download_paths", {}),
        },
    )
    _safe_json_write(script_dir / "debug_result_summary.json", targets)
    _write_markdown_summary(script_dir / "debug_summary.md", inputs, targets)
    return {
        "status": "PASS",
        "inputs": inputs,
        "targets": targets,
        "artifacts": {
            "zh_retrieval_debug": str((script_dir / "zh_retrieval_debug.json").resolve()),
            "zh_download_debug": str((script_dir / "zh_download_debug.json").resolve()),
            "en_retrieval_debug": str((script_dir / "en_retrieval_debug.json").resolve()),
            "en_download_debug": str((script_dir / "en_download_debug.json").resolve()),
            "debug_result_summary": str((script_dir / "debug_result_summary.json").resolve()),
            "debug_summary": str((script_dir / "debug_summary.md").resolve()),
        },
    }


def route(payload: dict[str, Any]) -> dict[str, Any]:
    source = str(payload.get("source") or "").strip()
    mode = str(payload.get("mode") or "").strip()
    action = str(payload.get("action") or "").strip()

    if source == "all" and mode == "debug" and action == "run":
        return run_full_debug(Path(__file__).resolve().parent, payload)

    source = str(payload.get("source") or "").strip()
    mode = str(payload.get("mode") or "").strip()
    action = str(payload.get("action") or "").strip()

    if source == "zh_cnki" and mode == "search" and action == "metadata":
        return zh_search_metadata(payload)

    if source == "zh_cnki" and mode == "single" and action == "download":
        return zh_single_download(payload)

    if source == "zh_cnki" and mode == "single" and action == "html_extract":
        return zh_single_html(payload)

    if source == "zh_cnki" and mode == "batch" and action == "download":
        entries = list(payload.get("entries") or [])
        if not entries:
            raise ValueError("zh_cnki batch download 需要 entries 数组。")
        return zh_batch_download(payload, entries)

    if source == "zh_cnki" and mode == "batch" and action == "html_extract":
        entries = list(payload.get("entries") or [])
        if not entries:
            raise ValueError("zh_cnki batch html_extract 需要 entries 数组。")
        return zh_batch_html(payload, entries)

    if source == "en_open_access" and mode == "search" and action == "metadata":
        return en_search_metadata(payload)

    if source == "en_open_access" and mode == "single" and action == "download":
        record_payload = payload.get("record")
        if not isinstance(record_payload, dict):
            raise ValueError("en_open_access single download 需要 record 对象。")
        return en_single_download(payload, en_to_record(record_payload))

    if source == "en_open_access" and mode == "batch" and action == "download":
        records = list(payload.get("records") or [])
        if not records:
            raise ValueError("en_open_access batch download 需要 records 数组。")
        return en_batch_download(payload, records)

    raise ValueError(f"不支持的路由组合: source={source}, mode={mode}, action={action}")


def _load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.preset == "full-debug":
        return {"source": "all", "mode": "debug", "action": "run"}
    if args.payload_json:
        payload = json.loads(args.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("payload-json 必须是 JSON 对象。")
        return payload
    if args.payload_file:
        path = Path(args.payload_file).expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload-file 必须是 JSON 对象文件。")
        return payload
    raise ValueError("请提供 --payload-json 或 --payload-file。")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="在线检索下载路由工具")
    parser.add_argument("--preset", default="", help="内置场景，当前支持 full-debug")
    parser.add_argument("--payload-json", default="", help="路由请求 JSON 字符串")
    parser.add_argument("--payload-file", default="", help="路由请求 JSON 文件")
    parser.add_argument("--output", default="", help="可选输出文件路径")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    payload = _load_payload(args)
    result = route(payload)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
