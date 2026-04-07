"""英文开放源单篇 HTML 结构化抽取工具。"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .en_open_access_single_fulltext_download import _to_record
from .retrieval_policy import evaluate_policy


class _SimpleHtmlStructureParser(HTMLParser):
    """轻量 HTML 结构解析器，仅提取常用结构字段。"""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.meta_description = ""
        self.h1: list[str] = []
        self.h2: list[str] = []
        self.h3: list[str] = []
        self.paragraphs: list[str] = []
        self._buffer: list[str] = []
        self._active_tag = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._active_tag = tag.lower()
        if self._active_tag == "meta":
            attr_dict = {str(k or "").lower(): str(v or "") for k, v in attrs}
            name = attr_dict.get("name", "").lower()
            prop = attr_dict.get("property", "").lower()
            if name == "description" or prop == "og:description":
                content = _normalize_text(attr_dict.get("content", ""))
                if content and not self.meta_description:
                    self.meta_description = content

    def handle_data(self, data: str) -> None:
        if self._active_tag in {"title", "h1", "h2", "h3", "p"}:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        text = _normalize_text("".join(self._buffer))
        self._buffer = []
        end_tag = tag.lower()
        if not text:
            self._active_tag = ""
            return
        if end_tag == "title" and not self.title:
            self.title = text
        elif end_tag == "h1":
            self.h1.append(text)
        elif end_tag == "h2":
            self.h2.append(text)
        elif end_tag == "h3":
            self.h3.append(text)
        elif end_tag == "p":
            self.paragraphs.append(text)
        self._active_tag = ""


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _pick_html_url(record: dict[str, Any]) -> str:
    landing_url = str(record.get("landing_url") or "").strip()
    pdf_url = str(record.get("pdf_url") or "").strip()
    if landing_url:
        return landing_url
    if pdf_url and not pdf_url.lower().endswith(".pdf"):
        return pdf_url
    return ""


def _fetch_html(url: str, timeout: int) -> tuple[str, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        content_type = str(resp.headers.get("Content-Type") or "")
        final_url = str(resp.geturl() or url)
        raw = resp.read()
    html = raw.decode("utf-8", errors="ignore")
    return html, final_url, content_type


def _extract_structure(html_text: str) -> dict[str, Any]:
    parser = _SimpleHtmlStructureParser()
    parser.feed(html_text)
    body_text = _normalize_text(re.sub(r"<[^>]+>", " ", html_text))
    return {
        "title": parser.title,
        "meta_description": parser.meta_description,
        "h1": parser.h1,
        "h2": parser.h2,
        "h3": parser.h3,
        "paragraph_count": len(parser.paragraphs),
        "paragraph_samples": parser.paragraphs[:8],
        "body_text_preview": body_text[:6000],
    }


def extract_single(config: dict[str, Any], record_payload: dict[str, Any]) -> dict[str, Any]:
    """执行单篇英文 HTML 结构化抽取。"""

    record_dict = dict(record_payload)
    rules = dict(config.get("retrieval_rules") or {})
    decision = evaluate_policy(record_dict, rules, channel="html_extract", source="en_open_access")
    if decision.skip:
        return {
            "status": "SKIPPED",
            "reason": decision.reason,
            "matched_tokens": decision.matched_tokens,
            "record": record_dict,
            "artifacts": {},
        }

    record = _to_record(record_dict)
    target_url = _pick_html_url(record.to_dict())
    if not target_url:
        return {
            "status": "BLOCKED",
            "error_type": "MissingLandingUrl",
            "error": "记录缺少 landing_url，无法提取英文 HTML 结构。",
            "record": record.to_dict(),
            "artifacts": {},
        }

    timeout = int(config.get("html_request_timeout") or 20)
    output_dir = Path(str(config.get("output_dir") or "sandbox/online_retrieval_debug/outputs/en_open_access/single_html")).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        html_text, final_url, content_type = _fetch_html(target_url, timeout=timeout)
        structure = _extract_structure(html_text)
        html_path = output_dir / "single_page.html"
        json_path = output_dir / "single_html_structure.json"
        html_path.write_text(html_text, encoding="utf-8")
        json_path.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "target_url": target_url,
                    "final_url": final_url,
                    "content_type": content_type,
                    "record": record.to_dict(),
                    "structure": structure,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "status": "PASS",
            "target_url": target_url,
            "final_url": final_url,
            "content_type": content_type,
            "record": record.to_dict(),
            "structure": structure,
            "artifacts": {
                "html": str(html_path),
                "structure_json": str(json_path),
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "BLOCKED",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
            "record": record.to_dict(),
            "artifacts": {},
        }


def _load_record_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.record_json:
        payload = json.loads(args.record_json)
        if not isinstance(payload, dict):
            raise ValueError("record-json 必须是 JSON 对象。")
        return payload
    if args.record_file:
        payload = json.loads(Path(args.record_file).expanduser().resolve().read_text(encoding="utf-8"))
        if isinstance(payload, list):
            if not payload:
                raise ValueError("record-file 数组为空。")
            payload = payload[0]
        if not isinstance(payload, dict):
            raise ValueError("record-file 必须是 JSON 对象或对象数组。")
        return payload
    raise ValueError("请提供 --record-json 或 --record-file。")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="英文开放源单篇 HTML 结构化抽取")
    parser.add_argument("--record-json", default="", help="记录 JSON 字符串")
    parser.add_argument("--record-file", default="", help="记录 JSON 文件")
    parser.add_argument("--output-dir", default="", help="输出目录")
    parser.add_argument("--html-request-timeout", type=int, default=20, help="HTML 请求超时秒数")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    record_payload = _load_record_payload(args)
    config = {
        "output_dir": args.output_dir,
        "html_request_timeout": args.html_request_timeout,
    }
    result = extract_single(config, record_payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
