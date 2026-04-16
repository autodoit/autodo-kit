"""学校数据库集合站抓取、筛选与导出工具。"""

from __future__ import annotations

import argparse
import html
import json
import random
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from autodokit.tools.online_retrieval_literatures.progress_reporter import print_progress_line, write_progress_snapshot


# ===== Stable Contract Zone =====
# 本区属于相对稳定区域：
# 1) 输入参数语义（catalog_language、library_nav_url/portal_url、subject_categories）
# 2) 输出 summary 字段和 artifacts 主键命名
# 3) 生成文件的通用命名规则（school_database_*.json/jsonl, database_entry_list.md）
# 若非必要，不应随意修改，避免破坏上层事务/脚本兼容。

USER_AGENT = "AcademicResearchAutoWorkflow-SchoolForeignPortal/0.1"
DEFAULT_CATALOG_LANGUAGE = "英文"
DEFAULT_PORTAL_BASE_URL = "https://wisdom.chaoxing.com/newwisdom/doordatabase/database.html"
DEFAULT_PORTAL_COMMON_QUERY = {
    "scope": "1",
    "wfwfid": "125449",
    "pageId": "949810",
    "websiteId": "29436",
    "mhType": "1",
    "publicId": "a80ff01e89fce111ee1b37f761ec0cc0e034",
    "mhEnc": "a379e36017c3335b344303f5f4f8af64",
}
DEFAULT_SUBJECT_CATEGORIES = ["经济学", "管理学", "综合"]
SEARCH_CAPABLE_PROFILES = {
    "springer",
    "sciencedirect",
    "wiley",
    "jstor",
    "nature",
    "ebsco",
    "wos",
    "proquest",
    "discovery",
    "cnki",
    "wanfang",
    "cqvip",
    "cssci",
    "chaoxing",
    "sinomed",
}
RETRY_CAPABLE_PROFILES = {"springer", "sciencedirect", "wiley", "jstor", "nature"}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_catalog_language(raw_value: Any) -> str:
    value = _normalize_text(raw_value or DEFAULT_CATALOG_LANGUAGE).lower()
    if value in {"中文", "zh", "zh-cn", "cn", "chinese", "china", "国内", "本地"}:
        return "中文"
    if value in {"英文", "外文", "en", "en-us", "english", "foreign", "国际"}:
        return "英文"
    return DEFAULT_CATALOG_LANGUAGE


def _catalog_language_to_choren(catalog_language: str) -> int:
    return 0 if _normalize_catalog_language(catalog_language) == "中文" else 1


def build_default_portal_url(catalog_language: str = DEFAULT_CATALOG_LANGUAGE) -> str:
    query = dict(DEFAULT_PORTAL_COMMON_QUERY)
    query["choren"] = str(_catalog_language_to_choren(catalog_language))
    return DEFAULT_PORTAL_BASE_URL + "?" + urllib.parse.urlencode(query)


DEFAULT_PORTAL_URL = build_default_portal_url(DEFAULT_CATALOG_LANGUAGE)
DEFAULT_FOREIGN_PORTAL_URL = DEFAULT_PORTAL_URL
DEFAULT_CHINESE_PORTAL_URL = build_default_portal_url("中文")


# ===== Mutable Adapter Zone =====
# 本区属于易变区域：
# 1) 学校导航站 URL 结构、query 字段
# 2) 超星接口路径与请求参数
# 3) 页面/接口返回字段变化
# 当学校站点改版导致报错时，优先在此区域和 _fetch_list_payload / _build_entry_from_list_item 里适配。


def _request_text(url: str, *, referer: str = "", timeout: int = 30) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def _request_json(url: str, *, referer: str = "", timeout: int = 30) -> dict[str, Any]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def _sample_delay(min_seconds: float, max_seconds: float) -> float:
    lower = max(float(min_seconds), 0.0)
    upper = max(float(max_seconds), lower)
    if upper == lower:
        return lower
    return random.uniform(lower, upper)


def _strip_html(raw_html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", str(raw_html or ""), flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return _normalize_text(html.unescape(text))


def _normalize_subjects(raw_value: str) -> list[str]:
    cleaned = _normalize_text(str(raw_value or "").replace(" ", ""))
    if not cleaned:
        return []
    items = [item.strip() for item in cleaned.split(",") if item.strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _slugify_catalog_language(catalog_language: str) -> str:
    return "chinese" if _normalize_catalog_language(catalog_language) == "中文" else "english"


def _resolve_portal_url(config: dict[str, Any]) -> str:
    # library_nav_url 是对外推荐参数名；portal_url 为兼容旧调用保留。
    raw_url = _normalize_text(config.get("library_nav_url") or config.get("portal_url") or "")
    if raw_url:
        return raw_url
    return build_default_portal_url(_normalize_catalog_language(config.get("catalog_language") or config.get("language")))


def _resolve_config_value(config: dict[str, Any], key: str, default: Any) -> Any:
    if key in config and config.get(key) is not None:
        return config.get(key)
    return default


def _resolve_choren(config: dict[str, Any], portal_url: str) -> int:
    if "choren" in config and config.get("choren") is not None:
        return int(config.get("choren"))
    query = urllib.parse.parse_qs(urllib.parse.urlparse(portal_url).query)
    if query.get("choren"):
        return int(str(query["choren"][0]))
    return _catalog_language_to_choren(_normalize_catalog_language(config.get("catalog_language") or config.get("language")))


def _infer_profile(name: str, access_links: list[str]) -> str:
    lowered = f"{name} {' '.join(access_links)}".lower()
    if "知网" in lowered or "cnki" in lowered:
        return "cnki"
    if "万方" in lowered or "wanfang" in lowered:
        return "wanfang"
    if "维普" in lowered or "cqvip" in lowered:
        return "cqvip"
    if "cssci" in lowered:
        return "cssci"
    if "超星" in lowered or "chaoxing" in lowered or "读秀" in lowered:
        return "chaoxing"
    if "sinomed" in lowered:
        return "sinomed"
    if "springer" in lowered:
        return "springer"
    if "sciencedirect" in lowered or "elsevier" in lowered:
        return "sciencedirect"
    if "wiley" in lowered:
        return "wiley"
    if "jstor" in lowered:
        return "jstor"
    if "nature" in lowered:
        return "nature"
    if "ebsco" in lowered or "businesssource" in lowered or "academic source" in lowered or "psycarticles" in lowered:
        return "ebsco"
    if "web of science" in lowered:
        return "wos"
    if "proquest" in lowered or "pqdt" in lowered:
        return "proquest"
    if "eds" in lowered or "发现系统" in lowered:
        return "discovery"
    return "generic"


def _estimate_generality_score(name: str, subjects: list[str]) -> int:
    lowered = name.lower()
    score = len(subjects) * 6
    if "综合" in subjects:
        score += 30
    if any(token in lowered for token in ["web of science", "sciencedirect", "springer", "wiley", "jstor", "ebsco", "proquest", "nature", "知网", "cnki", "万方", "维普", "cssci"]):
        score += 20
    if any(token in lowered for token in ["发现系统", "参考文献大全", "全文数据库"]):
        score += 12
    return score


def _parse_wfwfid(portal_url: str) -> str:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(portal_url).query)
    return str((query.get("wfwfid") or ["125449"])[0])


def _parse_page_id(portal_url: str) -> str:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(portal_url).query)
    return str((query.get("pageId") or ["949810"])[0])


def _fetch_list_payload(config: dict[str, Any]) -> dict[str, Any]:
    portal_url = _resolve_portal_url(config)
    params = {
        "wfwfid": str(_resolve_config_value(config, "wfwfid", _parse_wfwfid(portal_url))),
        "pageno": str(_resolve_config_value(config, "pageno", 1)),
        "pagesize": str(_resolve_config_value(config, "pagesize", 1000)),
        "pageType": str(_resolve_config_value(config, "page_type", 1)),
        "scope": str(_resolve_config_value(config, "scope", 1)),
        "choren": str(_resolve_choren(config, portal_url)),
        "sort": str(_resolve_config_value(config, "sort", "clickOrderNum")),
        "sw": str(_resolve_config_value(config, "sw", "")),
        "classifyid": str(_resolve_config_value(config, "classifyid", "")),
        "selfclassifyid": str(_resolve_config_value(config, "selfclassifyid", "")),
        "application": str(_resolve_config_value(config, "application", "")),
        "dataType": str(_resolve_config_value(config, "dataType", "")),
        "layerid": str(_resolve_config_value(config, "layerid", "")),
        "productid": str(_resolve_config_value(config, "productid", "")),
        "providerid": str(_resolve_config_value(config, "providerid", "")),
        "initial": str(_resolve_config_value(config, "initial", "")),
    }
    url = "https://wisdom.chaoxing.com/center/doorElecresource/list.action?" + urllib.parse.urlencode(params)
    return _request_json(url, referer=portal_url, timeout=int(config.get("timeout") or 30))


def resolve_redirect_url(raw_url: str, config: dict[str, Any], *, redirect_type: int = 0) -> str:
    normalized = _normalize_text(raw_url)
    if not normalized:
        return ""
    portal_url = _resolve_portal_url(config)
    wfwfid = str(_resolve_config_value(config, "wfwfid", _parse_wfwfid(portal_url)))
    request_url = (
        "https://wisdom.chaoxing.com/center/doorElecresource/getredirecturl.action?flag="
        f"{redirect_type}&readUrl={urllib.parse.quote(normalized, safe='')}&wfwfid={wfwfid}"
    )
    try:
        return _normalize_text(_request_text(request_url, referer=portal_url, timeout=int(config.get("timeout") or 30)))
    except Exception:
        return normalized


def _is_search_capable(profile: str, resource_type: str, resolved_links: list[str]) -> bool:
    if not resolved_links:
        return False
    lowered_type = resource_type.lower()
    if profile in SEARCH_CAPABLE_PROFILES:
        return True
    return any(token in lowered_type for token in ["期刊", "图书", "学位论文", "文摘索引", "报告"])


def _build_entry_from_list_item(item: dict[str, Any], config: dict[str, Any], popularity_rank: int) -> dict[str, Any]:
    portal_url = _resolve_portal_url(config)
    page_id = str(_resolve_config_value(config, "pageId", _parse_page_id(portal_url)))
    wfwfid = str(_resolve_config_value(config, "wfwfid", _parse_wfwfid(portal_url)))
    database_id = str(item.get("id") or "")
    doorid = database_id if int(item.get("series") or 0) and database_id else ""
    detail_param = f"doorid={doorid}" if doorid else f"id={database_id}"
    detail_url = (
        "https://wisdom.chaoxing.com/newwisdom/doordatabase/databasedetail.html?"
        f"wfwfid={wfwfid}&pageId={page_id}&{detail_param}"
    )

    open_url = _normalize_text(item.get("openUrl") or item.get("openUrlOut"))
    official_url = _normalize_text(item.get("officialUrl"))
    extra_urls = [
        _normalize_text((entry or {}).get("url"))
        for entry in list(item.get("urls") or [])
        if _normalize_text((entry or {}).get("url"))
    ]
    raw_links = [open_url, official_url, *extra_urls]
    resolved_links: list[str] = []
    for raw_link in raw_links:
        if not raw_link:
            continue
        resolved = resolve_redirect_url(raw_link, config, redirect_type=0)
        if resolved and resolved not in resolved_links:
            resolved_links.append(resolved)

    subjects = _normalize_subjects(str(item.get("showClassify") or item.get("showSelfFirstClassify") or ""))
    name = _normalize_text(item.get("name") or "")
    profile = _infer_profile(name, resolved_links or raw_links)
    resource_type = _normalize_text(item.get("showAllDatatype") or item.get("showDatatype") or item.get("showcontentLevel") or "")
    return {
        "database_id": database_id,
        "name": name,
        "catalog_language": _normalize_catalog_language(config.get("catalog_language") or config.get("language")),
        "detail_url": detail_url,
        "popularity_rank": popularity_rank,
        "visit_count": int(item.get("othervisit") or item.get("visitNum") or item.get("clickOrderNum") or 0),
        "generality_score": _estimate_generality_score(name, subjects),
        "subjects": subjects,
        "summary": _strip_html(str(item.get("summary") or item.get("resourcePlatSummary") or item.get("providerSummary") or "")),
        "notes": _strip_html(str(item.get("notes") or item.get("instructions") or "")),
        "profile": profile,
        "resource_type": resource_type,
        "access_mode": _normalize_text(item.get("accessMode") or item.get("showAccessMode") or ""),
        "accesslink": int(item.get("accesslink") or 0),
        "open_url": open_url,
        "official_url": official_url,
        "extra_urls": extra_urls,
        "resolved_links": resolved_links,
        "carsi_url": _normalize_text(item.get("carsiUrl") or ""),
        "jxurl": _normalize_text(item.get("jxurl") or ""),
        "provider": _normalize_text(item.get("provider") or item.get("showProvider") or ""),
        "search_capable": _is_search_capable(profile, resource_type, resolved_links),
        "retry_capable": profile in RETRY_CAPABLE_PROFILES,
        "raw_detail": item,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_entry_list_markdown(path: Path, selected: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        f"# {summary.get('catalog_language', DEFAULT_CATALOG_LANGUAGE)}数据库入口清单",
        "",
        f"- 目录总数：{int(summary.get('total_databases') or 0)}",
        f"- 筛选后数据库数：{int(summary.get('selected_databases') or 0)}",
        f"- 学科分类：{', '.join(list(summary.get('subject_categories') or []))}",
        "",
        "| 序号 | 数据库 | Profile | Search Capable | Retry Capable | 入口 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for index, item in enumerate(selected, start=1):
        links = list(item.get("resolved_links") or [])
        entry_url = links[0] if links else str(item.get("open_url") or item.get("official_url") or "")
        lines.append(
            "| "
            f"{index} | {str(item.get('name') or '')} | {str(item.get('profile') or '')} | "
            f"{str(bool(item.get('search_capable'))).lower()} | {str(bool(item.get('retry_capable'))).lower()} | {entry_url} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _normalize_subject_categories(config: dict[str, Any]) -> list[str]:
    raw = config.get("subject_category") or config.get("subject_categories") or DEFAULT_SUBJECT_CATEGORIES
    if isinstance(raw, str):
        items = [item.strip() for item in raw.split(",") if item.strip()]
        return items or list(DEFAULT_SUBJECT_CATEGORIES)
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()] or list(DEFAULT_SUBJECT_CATEGORIES)
    return list(DEFAULT_SUBJECT_CATEGORIES)


def select_databases(entries: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    subject_categories = _normalize_subject_categories(config)
    require_search_capable = bool(config.get("require_search_capable", True))
    selected: list[dict[str, Any]] = []
    for entry in entries:
        subjects = list(entry.get("subjects") or [])
        if subject_categories and not any(category == "全部" or category in subjects for category in subject_categories):
            continue
        if require_search_capable and not bool(entry.get("search_capable")):
            continue
        selected.append(entry)

    selected.sort(
        key=lambda item: (
            int(item.get("popularity_rank") or 9999),
            -int(item.get("generality_score") or 0),
            -int(item.get("visit_count") or 0),
            str(item.get("name") or ""),
        )
    )
    limit = int(config.get("max_databases") or 0)
    if limit > 0:
        return selected[:limit]
    return selected


def fetch_school_databases(config: dict[str, Any]) -> dict[str, Any]:
    """抓取学校数据库导航并输出结构化清单。

    Stable I/O Contract:
    - 输入: catalog_language, library_nav_url/portal_url, subject_categories, output_dir
    - 输出: summary.status/selected_databases/artifacts 固定键

    Mutable Implementation:
    - 超星站点接口与字段解析可能随改版变化，可在适配区更新。
    """
    catalog_language = _normalize_catalog_language(config.get("catalog_language") or config.get("language"))
    portal_url = _resolve_portal_url(config)
    library_nav_url = _normalize_text(config.get("library_nav_url") or portal_url)
    output_dir = Path(str(config.get("output_dir") or "sandbox/online_retrieval_debug/outputs/school_foreign_database_portal")).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    list_payload = _fetch_list_payload(config)
    datas = list(list_payload.get("datas") or [])
    total_catalog_items = len(datas)
    detail_rows: list[dict[str, Any]] = []
    activity_log_path = output_dir / "portal_activity.jsonl"
    progress_snapshot_path = output_dir / "portal_progress.json"
    for index, entry in enumerate(datas, start=1):
        detail_rows.append(_build_entry_from_list_item(dict(entry), config, index))
        with activity_log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": "list_item_processed", "index": index, "database_id": entry.get("id"), "name": entry.get("name")}, ensure_ascii=False) + "\n")
        print_progress_line(
            prefix="A040-portal-catalog",
            total=total_catalog_items,
            completed=index,
            current_label=str(entry.get("name") or ""),
            current_status="LIST_ITEM_PROCESSED",
            counters={
                "db_id": str(entry.get("id") or ""),
            },
        )
        write_progress_snapshot(
            progress_snapshot_path,
            {
                "stage": "catalog_list_scan",
                "total": total_catalog_items,
                "completed": index,
                "remaining": max(total_catalog_items - index, 0),
                "current": {
                    "database_id": entry.get("id"),
                    "name": entry.get("name"),
                },
            },
        )
        time.sleep(round(_sample_delay(float(config.get("min_catalog_delay_seconds") or 0.4), float(config.get("max_catalog_delay_seconds") or 1.3)), 3))

    selected = select_databases(detail_rows, config)
    summary = {
        "status": "PASS",
        "catalog_language": catalog_language,
        "portal_url": portal_url,
        "library_nav_url": library_nav_url,
        "total_databases": len(detail_rows),
        "selected_databases": len(selected),
        "subject_categories": _normalize_subject_categories(config),
        "catalog": detail_rows,
        "selected": selected,
        "artifacts": {},
    }

    language_slug = _slugify_catalog_language(catalog_language)
    catalog_json = output_dir / "school_database_catalog.json"
    selected_json = output_dir / "school_database_selected.json"
    catalog_jsonl = output_dir / "school_database_catalog.jsonl"
    entry_list_markdown = output_dir / "database_entry_list.md"
    language_catalog_json = output_dir / f"school_{language_slug}_database_catalog.json"
    language_selected_json = output_dir / f"school_{language_slug}_database_selected.json"
    language_catalog_jsonl = output_dir / f"school_{language_slug}_database_catalog.jsonl"
    language_entry_list_markdown = output_dir / f"{language_slug}_database_entry_list.md"
    catalog_payload = json.dumps(detail_rows, ensure_ascii=False, indent=2)
    selected_payload = json.dumps(selected, ensure_ascii=False, indent=2)
    catalog_json.write_text(catalog_payload, encoding="utf-8")
    selected_json.write_text(selected_payload, encoding="utf-8")
    language_catalog_json.write_text(catalog_payload, encoding="utf-8")
    language_selected_json.write_text(selected_payload, encoding="utf-8")
    _write_jsonl(catalog_jsonl, detail_rows)
    _write_jsonl(language_catalog_jsonl, detail_rows)
    _write_entry_list_markdown(entry_list_markdown, selected, summary)
    _write_entry_list_markdown(language_entry_list_markdown, selected, summary)
    legacy_artifacts: dict[str, str] = {}
    if catalog_language == "英文":
        legacy_catalog_json = output_dir / "school_foreign_database_catalog.json"
        legacy_selected_json = output_dir / "school_foreign_database_selected.json"
        legacy_catalog_jsonl = output_dir / "school_foreign_database_catalog.jsonl"
        legacy_catalog_json.write_text(catalog_payload, encoding="utf-8")
        legacy_selected_json.write_text(selected_payload, encoding="utf-8")
        _write_jsonl(legacy_catalog_jsonl, detail_rows)
        legacy_artifacts = {
            "legacy_catalog_json": str(legacy_catalog_json),
            "legacy_selected_json": str(legacy_selected_json),
            "legacy_catalog_jsonl": str(legacy_catalog_jsonl),
        }
    summary["artifacts"] = {
        "catalog_json": str(catalog_json),
        "selected_json": str(selected_json),
        "catalog_jsonl": str(catalog_jsonl),
        "entry_list_markdown": str(entry_list_markdown),
        "language_catalog_json": str(language_catalog_json),
        "language_selected_json": str(language_selected_json),
        "language_catalog_jsonl": str(language_catalog_jsonl),
        "language_entry_list_markdown": str(language_entry_list_markdown),
        "activity_log_path": str(activity_log_path),
        "progress_snapshot_path": str(progress_snapshot_path),
        **legacy_artifacts,
    }
    return summary


def fetch_school_foreign_databases(config: dict[str, Any]) -> dict[str, Any]:
    """兼容旧函数名，内部转发到通用入口 fetch_school_databases。"""
    return fetch_school_databases(config)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="学校数据库集合站抓取与筛选")
    parser.add_argument("--catalog-language", default=DEFAULT_CATALOG_LANGUAGE, help="目录语种，可选 中文 或 英文")
    parser.add_argument("--library-nav-url", default="", help="学校图书馆数据库导航页 URL；优先级高于 --portal-url")
    parser.add_argument("--portal-url", default="", help="学校数据库集合站入口 URL；留空时按目录语种自动生成")
    parser.add_argument("--subject-categories", default=",".join(DEFAULT_SUBJECT_CATEGORIES), help="学科分类，逗号分隔")
    parser.add_argument("--max-databases", type=int, default=0, help="最多输出多少个数据库，0 表示不限制")
    parser.add_argument("--output-dir", default="", help="输出目录")
    parser.add_argument("--timeout", type=int, default=30, help="请求超时秒数")
    parser.add_argument("--min-catalog-delay-seconds", type=float, default=0.4, help="目录抓取最小随机等待秒数")
    parser.add_argument("--max-catalog-delay-seconds", type=float, default=1.3, help="目录抓取最大随机等待秒数")
    parser.add_argument("--sort", default="clickOrderNum", help="列表接口排序字段")
    parser.add_argument("--require-search-capable", action="store_true", help="仅保留可检索数据库")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    config = {
        "catalog_language": args.catalog_language,
        "library_nav_url": args.library_nav_url,
        "portal_url": args.portal_url,
        "subject_categories": [item.strip() for item in str(args.subject_categories or "").split(",") if item.strip()],
        "max_databases": args.max_databases,
        "output_dir": args.output_dir,
        "timeout": args.timeout,
        "min_catalog_delay_seconds": args.min_catalog_delay_seconds,
        "max_catalog_delay_seconds": args.max_catalog_delay_seconds,
        "sort": args.sort,
        "require_search_capable": args.require_search_capable,
    }
    result = fetch_school_databases(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()