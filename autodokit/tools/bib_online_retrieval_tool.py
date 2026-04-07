"""Bib -> 在线检索路由批处理工具（通用工具层）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bibtexparser

from autodokit.tools.llm_clients import ModelRoutingIntent, invoke_aliyun_llm

from .online_retrieval_literatures.online_retrieval_router import route


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _slug(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", value)
    return text.strip("_")[:80] or "item"


def _first_author(author_field: str) -> str:
    parts = [item.strip() for item in str(author_field or "").split(" and ") if item.strip()]
    if not parts:
        return ""
    first = parts[0]
    if "," in first:
        return _normalize_text(first.split(",", 1)[0])
    tokens = first.split()
    return _normalize_text(tokens[-1] if tokens else "")


def _is_probably_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _read_json(path_text: str) -> Any:
    return json.loads(Path(path_text).expanduser().resolve().read_text(encoding="utf-8"))


def _extract_json_obj(text: str) -> dict[str, Any] | None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    for candidate in [cleaned, cleaned.replace("```json", "").replace("```", "").strip()]:
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return payload
        except Exception:
            continue
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _pick_best_record_heuristic(records: list[dict[str, Any]], *, title: str, year: str, first_author: str) -> dict[str, Any] | None:
    if not records:
        return None
    title_low = title.lower()
    year_text = _normalize_text(year)
    author_low = first_author.lower()

    def score(record: dict[str, Any]) -> int:
        s = 0
        rec_title = str(record.get("title") or "").lower()
        rec_year = str(record.get("year") or "").strip()
        authors = [str(item or "").lower() for item in list(record.get("authors") or [])]
        if rec_title == title_low:
            s += 40
        elif (rec_title and rec_title in title_low) or (title_low and title_low in rec_title):
            s += 25
        if year_text and rec_year == year_text:
            s += 20
        if author_low and any(author_low in item for item in authors):
            s += 20
        if record.get("pdf_url"):
            s += 5
        if record.get("landing_url"):
            s += 3
        return s

    ranked = sorted(records, key=score, reverse=True)
    return ranked[0]


def _pick_best_record_llm(
    records: list[dict[str, Any]],
    *,
    title: str,
    year: str,
    first_author: str,
    api_key_file: str,
) -> dict[str, Any] | None:
    if not records:
        return None
    candidates = records[: min(len(records), 12)]
    lines: list[str] = []
    for idx, item in enumerate(candidates, start=1):
        lines.append(
            json.dumps(
                {
                    "index": idx,
                    "title": str(item.get("title") or ""),
                    "year": str(item.get("year") or ""),
                    "authors": list(item.get("authors") or []),
                    "doi": str(item.get("doi") or ""),
                    "journal": str(item.get("journal") or ""),
                    "landing_url": str(item.get("landing_url") or ""),
                    "pdf_url": str(item.get("pdf_url") or ""),
                },
                ensure_ascii=False,
            )
        )

    prompt = (
        "你是文献记录匹配器。请从候选中选择最匹配目标文献的一条。\n"
        "目标字段："
        f"title={title!r}, year={year!r}, first_author={first_author!r}\n"
        "候选记录（JSON 行）：\n"
        + "\n".join(lines)
        + "\n"
        "只输出一个 JSON 对象："
        '{"best_index": 正整数, "confidence": 0到1小数, "reason": "简短原因"}'
    )

    result = invoke_aliyun_llm(
        prompt=prompt,
        system="你只输出 JSON，不要解释。",
        intent=ModelRoutingIntent(task_type="general", quality_tier="standard", budget_tier="cheap", input_chars=len(prompt)),
        max_tokens=240,
        temperature=0.0,
        api_key_file=api_key_file,
        affair_name="online_retrieval_bib_matching",
    )
    if str(result.get("status") or "") != "PASS":
        return None
    text = str(((result.get("response") or {}).get("text") or ""))
    payload = _extract_json_obj(text)
    if not payload:
        return None
    idx = int(payload.get("best_index") or 0)
    if idx <= 0 or idx > len(candidates):
        return None
    return candidates[idx - 1]


@dataclass
class BibRetrievalConfig:
    bib_path: Path
    output_dir: Path
    max_pages: int = 1
    en_per_page: int = 20
    en_sources: tuple[str, ...] = ("openalex", "crossref", "europe_pmc", "arxiv")
    max_entries: int = 0
    allow_manual_intervention: bool = False
    keep_browser_open: bool = False
    use_llm_matching: bool = False
    llm_api_key_file: str = ""


def _safe_route(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return route(payload)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "BLOCKED",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
            "payload": payload,
        }


def _build_query(title: str, year: str, first_author: str) -> str:
    return _normalize_text(f"{title} {year} {first_author}")


def _resolve_selected_record(
    en_search: dict[str, Any],
    *,
    title: str,
    year: str,
    first_author: str,
    config: BibRetrievalConfig,
) -> tuple[dict[str, Any] | None, str]:
    metadata_json_path = str((en_search.get("metadata_paths") or {}).get("json") or "")
    if not metadata_json_path:
        return None, "none"
    try:
        metadata_records = _read_json(metadata_json_path)
        if not isinstance(metadata_records, list):
            return None, "none"
    except Exception:
        return None, "none"

    if config.use_llm_matching and config.llm_api_key_file:
        picked = _pick_best_record_llm(
            metadata_records,
            title=title,
            year=year,
            first_author=first_author,
            api_key_file=config.llm_api_key_file,
        )
        if picked:
            return picked, "llm"

    return _pick_best_record_heuristic(metadata_records, title=title, year=year, first_author=first_author), "heuristic"


def _process_entry(entry: dict[str, Any], config: BibRetrievalConfig, index: int) -> dict[str, Any]:
    cite_key = str(entry.get("ID") or f"entry_{index}")
    title = _normalize_text(entry.get("title"))
    year = _normalize_text(entry.get("year"))
    author_field = str(entry.get("author") or "")
    first_author = _first_author(author_field)
    language = str(entry.get("language") or "")
    query = _build_query(title, year, first_author)
    entry_dir = (config.output_dir / f"{index:03d}_{_slug(cite_key)}").resolve()
    entry_dir.mkdir(parents=True, exist_ok=True)

    zh_search = _safe_route(
        {
            "source": "zh_cnki",
            "mode": "search",
            "action": "metadata",
            "zh_query": query,
            "max_pages": config.max_pages,
            "zh_output_dir": str((entry_dir / "zh_cnki").resolve()),
            "allow_manual_intervention": config.allow_manual_intervention,
            "keep_browser_open": config.keep_browser_open,
        }
    )
    zh_download = _safe_route(
        {
            "source": "zh_cnki",
            "mode": "single",
            "action": "download",
            "entries": [{"title": title, "cite_key": cite_key}],
            "zh_query": query,
            "title": title,
            "date": year,
            "zh_output_dir": str((entry_dir / "zh_cnki").resolve()),
            "allow_manual_intervention": config.allow_manual_intervention,
            "keep_browser_open": config.keep_browser_open,
        }
    )
    zh_html = _safe_route(
        {
            "source": "zh_cnki",
            "mode": "single",
            "action": "html_extract",
            "entries": [{"title": title, "cite_key": cite_key}],
            "query": query,
            "output_dir": str((entry_dir / "zh_cnki_html").resolve()),
            "allow_manual_intervention": config.allow_manual_intervention,
            "keep_browser_open": config.keep_browser_open,
        }
    )

    en_query = query if not _is_probably_chinese(title) and language.lower().startswith("en") else _normalize_text(f"{title} {first_author}")
    en_search = _safe_route(
        {
            "source": "en_open_access",
            "mode": "search",
            "action": "metadata",
            "query": en_query,
            "max_pages": config.max_pages,
            "per_page": config.en_per_page,
            "sources": list(config.en_sources),
            "output_dir": str((entry_dir / "en_open_access").resolve()),
        }
    )

    selected_record, match_method = _resolve_selected_record(
        en_search,
        title=title,
        year=year,
        first_author=first_author,
        config=config,
    )

    en_download_payload: dict[str, Any] = {
        "source": "en_open_access",
        "mode": "single",
        "action": "download",
        "output_dir": str((entry_dir / "en_open_access_download").resolve()),
    }
    en_html_payload: dict[str, Any] = {
        "source": "en_open_access",
        "mode": "single",
        "action": "html_extract",
        "output_dir": str((entry_dir / "en_open_access_html").resolve()),
        "html_request_timeout": 20,
    }
    if selected_record:
        en_download_payload["record"] = selected_record
        en_html_payload["record"] = selected_record
    else:
        seed = {"title": title, "cite_key": cite_key}
        en_download_payload["seed_items"] = [seed]
        en_html_payload["seed_items"] = [seed]

    en_download = _safe_route(en_download_payload)
    en_html = _safe_route(en_html_payload)

    return {
        "index": index,
        "cite_key": cite_key,
        "title": title,
        "year": year,
        "first_author": first_author,
        "query": query,
        "entry_output_dir": str(entry_dir),
        "zh_search": zh_search,
        "zh_download": zh_download,
        "zh_html_extract": zh_html,
        "en_search": en_search,
        "selected_en_record": selected_record or {},
        "match_method": match_method,
        "en_download": en_download,
        "en_html_extract": en_html,
    }


def run_online_retrieval_from_bib(payload: dict[str, Any]) -> dict[str, Any]:
    """根据 bib 批量执行在线检索四任务并输出汇总。"""

    config = BibRetrievalConfig(
        bib_path=Path(str(payload.get("bib_path") or "")).expanduser().resolve(),
        output_dir=Path(str(payload.get("output_dir") or "")).expanduser().resolve(),
        max_pages=max(int(payload.get("max_pages") or 1), 1),
        en_per_page=max(int(payload.get("en_per_page") or 20), 1),
        en_sources=tuple(str(item).strip() for item in list(payload.get("en_sources") or ["openalex", "crossref", "europe_pmc", "arxiv"]) if str(item).strip()),
        max_entries=max(int(payload.get("max_entries") or 0), 0),
        allow_manual_intervention=bool(payload.get("allow_manual_intervention", False)),
        keep_browser_open=bool(payload.get("keep_browser_open", False)),
        use_llm_matching=bool(payload.get("use_llm_matching", False)),
        llm_api_key_file=str(payload.get("llm_api_key_file") or payload.get("bailian_api_key_file") or "").strip(),
    )

    if not config.bib_path.exists():
        raise FileNotFoundError(f"bib 文件不存在: {config.bib_path}")

    db = bibtexparser.load(config.bib_path.open("r", encoding="utf-8"))
    entries = list(db.entries or [])
    if config.max_entries > 0:
        entries = entries[: config.max_entries]

    config.output_dir.mkdir(parents=True, exist_ok=True)
    all_results: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries, start=1):
        all_results.append(_process_entry(entry, config, idx))

    status_counts = {
        "zh_download_pass": sum(1 for item in all_results if str((item.get("zh_download") or {}).get("status") or "") == "PASS"),
        "en_download_pass": sum(1 for item in all_results if str((item.get("en_download") or {}).get("status") or "") == "PASS"),
        "zh_html_pass": sum(1 for item in all_results if str((item.get("zh_html_extract") or {}).get("status") or "") == "PASS"),
        "en_html_pass": sum(1 for item in all_results if str((item.get("en_html_extract") or {}).get("status") or "") == "PASS"),
        "llm_match_used": sum(1 for item in all_results if str(item.get("match_method") or "") == "llm"),
    }

    summary = {
        "status": "PASS",
        "bib_path": str(config.bib_path.resolve()),
        "output_dir": str(config.output_dir.resolve()),
        "total_entries": len(entries),
        "status_counts": status_counts,
        "results": all_results,
    }
    summary_json = config.output_dir / "router_bib_tasks_summary.json"
    summary_md = config.output_dir / "router_bib_tasks_summary.md"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Bib 路由批处理结果",
        "",
        f"- bib_path: {config.bib_path.resolve()}",
        f"- output_dir: {config.output_dir.resolve()}",
        f"- total_entries: {len(entries)}",
        f"- zh_download_pass: {status_counts['zh_download_pass']}",
        f"- en_download_pass: {status_counts['en_download_pass']}",
        f"- zh_html_pass: {status_counts['zh_html_pass']}",
        f"- en_html_pass: {status_counts['en_html_pass']}",
        f"- llm_match_used: {status_counts['llm_match_used']}",
        "",
        "## 每条目状态",
    ]
    for item in all_results:
        lines.append(
            "- "
            f"[{item.get('index')}] {item.get('cite_key')} | "
            f"match={item.get('match_method')} | "
            f"ZH-DL={((item.get('zh_download') or {}).get('status') or '')} | "
            f"EN-DL={((item.get('en_download') or {}).get('status') or '')} | "
            f"ZH-HTML={((item.get('zh_html_extract') or {}).get('status') or '')} | "
            f"EN-HTML={((item.get('en_html_extract') or {}).get('status') or '')}"
        )
    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary["artifacts"] = {
        "summary_json": str(summary_json.resolve()),
        "summary_md": str(summary_md.resolve()),
    }
    return summary
