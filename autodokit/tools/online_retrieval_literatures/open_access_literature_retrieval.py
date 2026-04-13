"""英文开放源检索与下载工具。

优先使用无需登录、无需验证码的开放源：
1. OpenAlex 获取元数据与 OA 线索；
2. Crossref 作为元数据补充；
3. Europe PMC 与 arXiv 作为补充开放源；
4. 直接尝试下载公开 PDF；
5. 若遇到访问障碍，可选调用百炼做文本级障碍判断。
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from autodokit.tools.llm_clients import ModelRoutingIntent, invoke_aliyun_llm

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 45
DOWNLOAD_REQUEST_TIMEOUT = 12
DOWNLOAD_HTML_EXPANSION_LIMIT = 6


@dataclass(slots=True)
class RetrievalRecord:
    """统一的英文文献记录。

    Args:
        source: 来源名。
        source_id: 来源内 ID。
        title: 标题。
        year: 年份。
        doi: DOI。
        journal: 期刊或来源。
        authors: 作者列表。
        abstract: 摘要。
        landing_url: 落地页 URL。
        pdf_url: 直接 PDF URL。
        bibtex_key: BibTeX 键。
        raw: 原始记录。
    """

    source: str
    source_id: str
    title: str
    year: str
    doi: str
    journal: str
    authors: list[str]
    abstract: str
    landing_url: str
    pdf_url: str
    bibtex_key: str
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""

        return {
            "source": self.source,
            "source_id": self.source_id,
            "title": self.title,
            "year": self.year,
            "doi": self.doi,
            "journal": self.journal,
            "authors": self.authors,
            "abstract": self.abstract,
            "landing_url": self.landing_url,
            "pdf_url": self.pdf_url,
            "bibtex_key": self.bibtex_key,
            "raw": self.raw,
        }


class PdfLinkExtractor(HTMLParser):
    """从 HTML 中提取潜在 PDF 链接。"""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "meta":
            name = str(attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
            content = str(attrs_dict.get("content") or "").strip()
            if name in {"citation_pdf_url", "og:pdf"} and content:
                self.links.append(content)
        if tag == "a":
            href = str(attrs_dict.get("href") or "").strip()
            if href and (href.lower().endswith(".pdf") or "/pdf" in href.lower()):
                self.links.append(href)


def _request(
    url: str,
    *,
    accept: str = "application/json",
    sleep_seconds: float = 0.0,
    timeout: int = REQUEST_TIMEOUT,
    extra_headers: dict[str, str] | None = None,
) -> tuple[bytes, dict[str, str], str]:
    """执行 HTTP 请求。

    Args:
        url: 请求地址。
        accept: Accept 头。
        sleep_seconds: 请求前等待秒数。
        timeout: 请求超时秒数。

    Returns:
        响应体、响应头和最终 URL。
    """

    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            **dict(extra_headers or {}),
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        headers = {key.lower(): value for key, value in response.headers.items()}
        return body, headers, response.geturl()


def _request_json(url: str, *, sleep_seconds: float = 0.0) -> dict[str, Any]:
    """请求 JSON 接口。"""

    body, _headers, _final_url = _request(url, accept="application/json", sleep_seconds=sleep_seconds)
    return json.loads(body.decode("utf-8"))


def _sample_delay(min_seconds: float, max_seconds: float) -> float:
    """生成一个随机等待时长。"""

    lower = max(float(min_seconds), 0.0)
    upper = max(float(max_seconds), lower)
    if upper == lower:
        return lower
    return random.uniform(lower, upper)


def _normalize_text(value: Any) -> str:
    """清洗文本。"""

    return re.sub(r"\s+", " ", str(value or "")).strip()


def _slug(text: str) -> str:
    """生成安全 slug。"""

    lowered = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return lowered or "untitled"


def _safe_filename(text: str, suffix: str) -> str:
    """生成安全文件名。"""

    sanitized = re.sub(r"[\\/:*?\"<>|]", "_", text)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    if not sanitized:
        sanitized = "untitled"
    return f"{sanitized}{suffix}"


def _build_bibtex_key(authors: list[str], year: str, title: str) -> str:
    """构造 BibTeX 键。"""

    lead = _slug(authors[0].split()[-1] if authors else "anon")
    year_text = re.sub(r"[^0-9]", "", year) or "nd"
    title_token = _slug(title).split("-")[0] or "work"
    return f"{lead}{year_text}{title_token}"


def _escape_bibtex(value: str) -> str:
    """转义 BibTeX 文本。"""

    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _record_to_bibtex(record: RetrievalRecord) -> str:
    """把记录转换为 BibTeX 条目。"""

    authors = " and ".join(record.authors)
    fields = {
        "title": record.title,
        "author": authors,
        "year": record.year,
        "journal": record.journal,
        "doi": record.doi,
        "url": record.landing_url or record.pdf_url,
    }
    lines = [f"@article{{{record.bibtex_key},"]
    for key, value in fields.items():
        normalized = _normalize_text(value)
        if normalized:
            lines.append(f"  {key} = {{{_escape_bibtex(normalized)}}},")
    lines.append("}")
    return "\n".join(lines)


def _normalize_url_candidate(value: str) -> str:
    """清理来源元数据中的 URL 噪声。"""

    normalized = _normalize_text(value).strip("<>'\" ")
    normalized = re.sub(r"[>\]\),.;:]+$", "", normalized)
    normalized = normalized.replace("http://dx.doi.org/", "https://doi.org/")
    normalized = normalized.replace("https://dx.doi.org/", "https://doi.org/")
    return normalized


def _collect_pdf_candidates(urls: list[str], doi: str) -> list[str]:
    """合并并去重下载候选 URL。"""

    merged: list[str] = []
    seen: set[str] = set()
    for item in urls:
        normalized = _normalize_url_candidate(str(item or ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
    if doi:
        doi_url = f"https://doi.org/{doi}"
        if doi_url not in seen:
            merged.append(doi_url)
    return merged


def _pdf_candidate_priority(url: str) -> tuple[int, str]:
    """计算下载候选的优先级。"""

    lowered = _normalize_text(url).lower()
    if not lowered:
        return (99, lowered)
    if "arxiv.org/pdf/" in lowered:
        return (0, lowered)
    if lowered.endswith(".pdf"):
        return (1, lowered)
    if "pdf=render" in lowered:
        return (2, lowered)
    if "/pdf" in lowered or "pdf=" in lowered:
        return (3, lowered)
    if "download" in lowered:
        return (4, lowered)
    if "doi.org" in lowered:
        return (8, lowered)
    return (6, lowered)


def _prioritize_pdf_candidates(urls: list[str], doi: str) -> list[str]:
    """对下载候选进行去重和优先级排序。"""

    candidates = _collect_pdf_candidates(urls, doi)
    return sorted(candidates, key=_pdf_candidate_priority)


def _collect_doi_resolver_candidates(doi: str) -> list[str]:
    """通过 DOI 解析器补充可下载候选。"""

    normalized_doi = _normalize_text(doi)
    if not normalized_doi:
        return []
    normalized_doi = normalized_doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    encoded = urllib.parse.quote(normalized_doi, safe="")
    resolved_urls: list[str] = []

    # Crossref: 优先利用 link/URL 字段补充下载候选。
    try:
        crossref_payload = _request_json(f"https://api.crossref.org/works/{encoded}")
        message = dict(crossref_payload.get("message") or {})
        for link in list(message.get("link") or []):
            link_dict = dict(link or {})
            candidate = _normalize_text(link_dict.get("URL"))
            if not candidate:
                continue
            content_type = _normalize_text(link_dict.get("content-type")).lower()
            if "pdf" in content_type or candidate.lower().endswith(".pdf") or "pdf" in candidate.lower():
                resolved_urls.append(candidate)
            else:
                resolved_urls.append(candidate)
        landing = _normalize_text(message.get("URL"))
        if landing:
            resolved_urls.append(landing)
    except Exception:
        pass

    # OpenAlex: 读取 OA URL、best/location 的 pdf_url 与 landing_page_url。
    try:
        openalex_payload = _request_json(f"https://api.openalex.org/works/https://doi.org/{encoded}")
        open_access = dict(openalex_payload.get("open_access") or {})
        oa_url = _normalize_text(open_access.get("oa_url"))
        if oa_url:
            resolved_urls.append(oa_url)
        best = dict(openalex_payload.get("best_oa_location") or {})
        for key in ("pdf_url", "landing_page_url"):
            candidate = _normalize_text(best.get(key))
            if candidate:
                resolved_urls.append(candidate)
        for location in list(openalex_payload.get("locations") or []):
            location_dict = dict(location or {})
            for key in ("pdf_url", "landing_page_url"):
                candidate = _normalize_text(location_dict.get(key))
                if candidate:
                    resolved_urls.append(candidate)
    except Exception:
        pass

    return _collect_pdf_candidates(resolved_urls, normalized_doi)


def _openalex_record(item: dict[str, Any]) -> RetrievalRecord:
    """标准化 OpenAlex 记录。"""

    authors = [
        _normalize_text((author.get("author") or {}).get("display_name"))
        for author in list(item.get("authorships") or [])
        if _normalize_text((author.get("author") or {}).get("display_name"))
    ]
    title = _normalize_text(item.get("display_name"))
    year = _normalize_text(item.get("publication_year"))
    doi_raw = _normalize_text(item.get("doi"))
    doi = doi_raw.replace("https://doi.org/", "").replace("http://doi.org/", "")
    primary = item.get("primary_location") or {}
    best = item.get("best_oa_location") or {}
    journal = _normalize_text(((primary.get("source") or {}).get("display_name")) or ((best.get("source") or {}).get("display_name")))
    landing_url = _normalize_text(best.get("landing_page_url") or primary.get("landing_page_url") or item.get("id"))
    pdf_urls: list[str] = []
    for location in [best, primary, *(item.get("locations") or [])]:
        pdf_url = _normalize_text(location.get("pdf_url"))
        landing = _normalize_text(location.get("landing_page_url"))
        if pdf_url:
            pdf_urls.append(pdf_url)
        if landing:
            pdf_urls.append(landing)
    abstract = ""
    abstract_inverted = item.get("abstract_inverted_index") or {}
    if abstract_inverted:
        words = sorted(
            ((position, token) for token, positions in abstract_inverted.items() for position in positions),
            key=lambda pair: pair[0],
        )
        abstract = " ".join(token for _position, token in words)
    return RetrievalRecord(
        source="openalex",
        source_id=_normalize_text(item.get("id")),
        title=title,
        year=year,
        doi=doi,
        journal=journal,
        authors=authors,
        abstract=abstract,
        landing_url=landing_url,
        pdf_url=_normalize_text(best.get("pdf_url") or primary.get("pdf_url")),
        bibtex_key=_build_bibtex_key(authors, year, title),
        raw={
            "id": item.get("id"),
            "type": item.get("type"),
            "is_oa": (item.get("open_access") or {}).get("is_oa"),
            "download_candidates": _collect_pdf_candidates(pdf_urls, doi),
        },
    )


def _crossref_record(item: dict[str, Any]) -> RetrievalRecord:
    """标准化 Crossref 记录。"""

    title = _normalize_text((item.get("title") or [""])[0])
    year_parts = ((item.get("issued") or {}).get("date-parts") or [[]])[0]
    year = _normalize_text(year_parts[0] if year_parts else "")
    authors = []
    for author in item.get("author") or []:
        full_name = " ".join(part for part in [_normalize_text(author.get("given")), _normalize_text(author.get("family"))] if part)
        if full_name:
            authors.append(full_name)
    links = []
    for link in item.get("link") or []:
        candidate = _normalize_text(link.get("URL"))
        if candidate:
            links.append(candidate)
    doi = _normalize_text(item.get("DOI"))
    return RetrievalRecord(
        source="crossref",
        source_id=doi or _normalize_text(item.get("URL")),
        title=title,
        year=year,
        doi=doi,
        journal=_normalize_text((item.get("container-title") or [""])[0]),
        authors=authors,
        abstract=_normalize_text(item.get("abstract")),
        landing_url=_normalize_text(item.get("URL")),
        pdf_url="",
        bibtex_key=_build_bibtex_key(authors, year, title),
        raw={
            "type": item.get("type"),
            "download_candidates": _collect_pdf_candidates(links, doi),
        },
    )


def _europe_pmc_record(item: dict[str, Any]) -> RetrievalRecord:
    """标准化 Europe PMC 记录。"""

    title = _normalize_text(item.get("title"))
    year = _normalize_text(item.get("pubYear"))
    doi = _normalize_text(item.get("doi"))
    authors = [author.strip() for author in _normalize_text(item.get("authorString")).split(",") if author.strip()]
    pmcid = _normalize_text(item.get("pmcid"))
    landing_url = _normalize_text(item.get("sourceUrl") or item.get("fullTextUrlList") or "")
    if not landing_url and pmcid:
        landing_url = f"https://europepmc.org/article/PMC/{pmcid}"

    pdf_candidates: list[str] = []
    full_text_list = (((item.get("fullTextUrlList") or {}).get("fullTextUrl")) or [])
    for url_item in full_text_list:
        candidate = _normalize_text(url_item.get("url"))
        style = _normalize_text(url_item.get("documentStyle")).lower()
        if candidate:
            pdf_candidates.append(candidate)
        if candidate and style == "pdf":
            pdf_candidates.insert(0, candidate)
    if pmcid:
        pdf_candidates.insert(0, f"https://europepmc.org/articles/{pmcid}?pdf=render")
        pdf_candidates.insert(0, f"https://europepmc.org/articles/{pmcid}/pdf")

    return RetrievalRecord(
        source="europe_pmc",
        source_id=_normalize_text(item.get("id") or pmcid or doi or title),
        title=title,
        year=year,
        doi=doi,
        journal=_normalize_text(item.get("journalTitle")),
        authors=authors,
        abstract=_normalize_text(item.get("abstractText")),
        landing_url=landing_url,
        pdf_url=pdf_candidates[0] if pdf_candidates else "",
        bibtex_key=_build_bibtex_key(authors, year, title),
        raw={
            "source": item.get("source"),
            "pmcid": pmcid,
            "download_candidates": _collect_pdf_candidates(pdf_candidates, doi),
        },
    )


def _arxiv_record(entry: ET.Element, namespace: dict[str, str]) -> RetrievalRecord:
    """标准化 arXiv 记录。"""

    title = _normalize_text(entry.findtext("atom:title", default="", namespaces=namespace))
    published = _normalize_text(entry.findtext("atom:published", default="", namespaces=namespace))
    year = published[:4] if published else ""
    authors = [
        _normalize_text(author.findtext("atom:name", default="", namespaces=namespace))
        for author in entry.findall("atom:author", namespaces=namespace)
        if _normalize_text(author.findtext("atom:name", default="", namespaces=namespace))
    ]
    summary = _normalize_text(entry.findtext("atom:summary", default="", namespaces=namespace))
    source_id = _normalize_text(entry.findtext("atom:id", default="", namespaces=namespace))
    landing_url = source_id
    pdf_url = ""
    candidates: list[str] = []
    for link in entry.findall("atom:link", namespaces=namespace):
        href = _normalize_text(link.attrib.get("href"))
        link_type = _normalize_text(link.attrib.get("type")).lower()
        title_attr = _normalize_text(link.attrib.get("title")).lower()
        if href:
            candidates.append(href)
        if href and (title_attr == "pdf" or link_type == "application/pdf"):
            pdf_url = href
    if not pdf_url and landing_url and "/abs/" in landing_url:
        pdf_url = landing_url.replace("/abs/", "/pdf/") + ".pdf"
        candidates.insert(0, pdf_url)

    return RetrievalRecord(
        source="arxiv",
        source_id=source_id,
        title=title,
        year=year,
        doi="",
        journal="arXiv",
        authors=authors,
        abstract=summary,
        landing_url=landing_url,
        pdf_url=pdf_url,
        bibtex_key=_build_bibtex_key(authors, year, title),
        raw={
            "download_candidates": _collect_pdf_candidates(candidates, ""),
        },
    )


def search_openalex(query: str, *, max_pages: int, per_page: int, language: str = "en") -> dict[str, Any]:
    """使用 OpenAlex 检索。"""

    cursor = "*"
    all_records: list[RetrievalRecord] = []
    pages = 0
    total_count = None
    for _ in range(max_pages):
        url = (
            "https://api.openalex.org/works?search="
            + urllib.parse.quote(query)
            + f"&filter=language:{urllib.parse.quote(language)}&per-page={per_page}&cursor={urllib.parse.quote(cursor)}"
        )
        data = _request_json(url, sleep_seconds=0.2)
        pages += 1
        total_count = (data.get("meta") or {}).get("count")
        results = data.get("results") or []
        if not results:
            break
        all_records.extend(_openalex_record(item) for item in results)
        next_cursor = (data.get("meta") or {}).get("next_cursor")
        if not next_cursor:
            break
        cursor = str(next_cursor)
    return {
        "source": "openalex",
        "page_count": pages,
        "total_count": total_count,
        "records": [record.to_dict() for record in all_records],
    }


def search_crossref(query: str, *, max_pages: int, per_page: int) -> dict[str, Any]:
    """使用 Crossref 检索。"""

    all_records: list[RetrievalRecord] = []
    total_count = None
    for page_index in range(max_pages):
        offset = page_index * per_page
        url = (
            "https://api.crossref.org/works?query.bibliographic="
            + urllib.parse.quote(query)
            + f"&rows={per_page}&offset={offset}&select=DOI,title,author,issued,container-title,type,URL,link,abstract"
        )
        data = _request_json(url, sleep_seconds=0.2)
        message = data.get("message") or {}
        total_count = message.get("total-results")
        items = message.get("items") or []
        if not items:
            break
        all_records.extend(_crossref_record(item) for item in items)
    return {
        "source": "crossref",
        "page_count": max_pages,
        "total_count": total_count,
        "records": [record.to_dict() for record in all_records],
    }


def search_europe_pmc(query: str, *, max_pages: int, per_page: int) -> dict[str, Any]:
    """使用 Europe PMC 检索。"""

    all_records: list[RetrievalRecord] = []
    total_count = None
    actual_pages = 0
    for page_index in range(1, max_pages + 1):
        url = (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query="
            + urllib.parse.quote(query)
            + f"&pageSize={per_page}&page={page_index}&format=json"
        )
        data = _request_json(url, sleep_seconds=0.2)
        actual_pages += 1
        total_count = data.get("hitCount")
        items = ((data.get("resultList") or {}).get("result")) or []
        if not items:
            break
        all_records.extend(_europe_pmc_record(item) for item in items)
        if len(items) < per_page:
            break
    return {
        "source": "europe_pmc",
        "page_count": actual_pages,
        "total_count": total_count,
        "records": [record.to_dict() for record in all_records],
    }


def search_arxiv(query: str, *, max_pages: int, per_page: int) -> dict[str, Any]:
    """使用 arXiv API 检索。"""

    namespace = {"atom": "http://www.w3.org/2005/Atom", "opensearch": "http://a9.com/-/spec/opensearch/1.1/"}
    all_records: list[RetrievalRecord] = []
    total_count = None
    actual_pages = 0
    for page_index in range(max_pages):
        start = page_index * per_page
        url = (
            "http://export.arxiv.org/api/query?search_query=all:"
            + urllib.parse.quote(query)
            + f"&start={start}&max_results={per_page}&sortBy=relevance&sortOrder=descending"
        )
        body, _headers, _final_url = _request(url, accept="application/atom+xml,text/xml", sleep_seconds=0.4)
        root = ET.fromstring(body)
        actual_pages += 1
        if total_count is None:
            total_node = root.find("opensearch:totalResults", namespace)
            total_count = int(total_node.text) if total_node is not None and total_node.text else None
        entries = root.findall("atom:entry", namespace)
        if not entries:
            break
        all_records.extend(_arxiv_record(entry, namespace) for entry in entries)
        if len(entries) < per_page:
            break
    return {
        "source": "arxiv",
        "page_count": actual_pages,
        "total_count": total_count,
        "records": [record.to_dict() for record in all_records],
    }


def merge_records(source_results: list[dict[str, Any]]) -> list[RetrievalRecord]:
    """按 DOI 或标题合并记录。"""

    merged: dict[str, RetrievalRecord] = {}
    for source_result in source_results:
        for raw_record in source_result.get("records") or []:
            record = RetrievalRecord(
                source=_normalize_text(raw_record.get("source")),
                source_id=_normalize_text(raw_record.get("source_id")),
                title=_normalize_text(raw_record.get("title")),
                year=_normalize_text(raw_record.get("year")),
                doi=_normalize_text(raw_record.get("doi")),
                journal=_normalize_text(raw_record.get("journal")),
                authors=[_normalize_text(item) for item in raw_record.get("authors") or [] if _normalize_text(item)],
                abstract=_normalize_text(raw_record.get("abstract")),
                landing_url=_normalize_text(raw_record.get("landing_url")),
                pdf_url=_normalize_text(raw_record.get("pdf_url")),
                bibtex_key=_normalize_text(raw_record.get("bibtex_key")),
                raw=dict(raw_record.get("raw") or {}),
            )
            key = record.doi.lower() if record.doi else _slug(record.title)
            existing = merged.get(key)
            if existing is None:
                merged[key] = record
                continue
            existing_candidates = existing.raw.setdefault("download_candidates", [])
            new_candidates = record.raw.get("download_candidates") or []
            existing.raw["download_candidates"] = _collect_pdf_candidates(existing_candidates + new_candidates, existing.doi or record.doi)
            if not existing.abstract and record.abstract:
                existing.abstract = record.abstract
            if not existing.journal and record.journal:
                existing.journal = record.journal
            if not existing.landing_url and record.landing_url:
                existing.landing_url = record.landing_url
            if not existing.pdf_url and record.pdf_url:
                existing.pdf_url = record.pdf_url
    return list(merged.values())


def _extract_pdf_links_from_html(html_text: str, base_url: str) -> list[str]:
    """从 HTML 中解析 PDF 链接。"""

    parser = PdfLinkExtractor()
    parser.feed(html_text)
    resolved: list[str] = []
    for link in parser.links:
        resolved.append(urllib.parse.urljoin(base_url, link))
    if "arxiv.org/abs/" in base_url:
        resolved.append(base_url.replace("/abs/", "/pdf/") + ".pdf")
    return _prioritize_pdf_candidates(resolved, "")


def _sha256_bytes(content: bytes) -> str:
    """计算 SHA256。"""

    return hashlib.sha256(content).hexdigest()


def _detect_access_barrier(text: str) -> tuple[str, str] | None:
    """识别访问障碍。"""

    lowered = text.lower()
    patterns = [
        ("captcha_required", ["captcha", "verify you are human", "security check"]),
        ("login_required", ["sign in", "log in", "institutional login", "shibboleth"]),
        ("paywalled", ["purchase pdf", "buy article", "institutional access", "access through your institution"]),
    ]
    for barrier, tokens in patterns:
        if any(token in lowered for token in tokens):
            return barrier, tokens[0]
    return None


def _find_edge_executable() -> str:
    """定位 Edge 可执行文件。"""

    candidates = [
        shutil.which("msedge"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise RuntimeError("未找到 Microsoft Edge，可先安装 Edge 或补充浏览器路径。")


def _launch_edge_with_cdp(profile_dir: Path, port: int, start_url: str) -> subprocess.Popen[str]:
    """以远程调试模式启动 Edge。"""

    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        _find_edge_executable(),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={str(profile_dir.resolve())}",
        start_url,
    ]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)


def _connect_context(cdp_url: str) -> tuple[Any, Any]:
    """连接 CDP 浏览器上下文。"""

    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = playwright.chromium.connect_over_cdp(cdp_url)
    if browser.contexts:
        return playwright, browser.contexts[0]
    return playwright, browser.new_context()


def _select_existing_page(context: Any, preferred_url: str = "") -> Any:
    """从现有上下文中选择页面。"""

    pages = list(context.pages)
    if preferred_url:
        for page in pages:
            try:
                if preferred_url in page.url:
                    return page
            except Exception:
                continue
    if pages:
        return pages[0]
    page = context.new_page()
    return page


def _page_inner_text(page: Any) -> str:
    """读取页面主体文本。"""

    return _normalize_text(page.locator("body").first.inner_text(timeout=2500))


def _read_page_state(page: Any) -> tuple[str, str, str]:
    """稳定读取页面状态。"""

    current_url = ""
    for _ in range(3):
        try:
            current_url = page.url
            current_title = page.title()
            page_text = _page_inner_text(page)
            return current_url, current_title, page_text
        except Exception:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                page.wait_for_timeout(1000)
    return current_url, "", ""


def _detect_browser_blocking_state(page: Any) -> dict[str, Any] | None:
    """识别英文门户页面的登录或验证阻断。"""

    current_url, current_title, page_text = _read_page_state(page)
    lowered_url = current_url.lower()
    lowered_title = current_title.lower()
    lowered_text = page_text.lower()
    if any(token in lowered_url for token in ["captcha", "verify", "challenge"]):
        return {"reason": "captcha_required", "url": current_url, "title": current_title}
    if any(token in lowered_text for token in ["captcha", "verify you are human", "security check", "robot check"]):
        return {"reason": "captcha_required", "url": current_url, "title": current_title}
    if any(token in lowered_url for token in ["login", "signin", "shibboleth", "auth.elsevier.com", "institutionlogin", "idp/"]):
        return {"reason": "login_required", "url": current_url, "title": current_title}
    if any(token in lowered_title for token in ["sign in", "login", "institutional login"]):
        return {"reason": "login_required", "url": current_url, "title": current_title}
    if any(token in lowered_text for token in ["sign in", "log in", "institutional login", "access through your institution", "shibboleth"]):
        return {"reason": "login_required", "url": current_url, "title": current_title}
    return None


def _wait_for_human_if_needed(page: Any, allow_manual_intervention: bool, timeout_seconds: int) -> list[dict[str, Any]]:
    """若遇到登录或验证码则等待人工处理。"""

    manual_events: list[dict[str, Any]] = []
    wait_started_at = time.time()
    while True:
        blocked_state = _detect_browser_blocking_state(page)
        if not blocked_state:
            return manual_events
        event = dict(blocked_state)
        manual_events.append(event)
        if not allow_manual_intervention:
            return manual_events
        elapsed = int(time.time() - wait_started_at)
        if elapsed >= timeout_seconds:
            event["timeout_seconds"] = elapsed
            event["status"] = "manual_timeout"
            return manual_events
        remaining = timeout_seconds - elapsed
        print(
            "[人工接管][英文下载] 当前页面需要登录或完成验证，请在已打开的 Edge 窗口中完成认证。"
            f" 已等待 {elapsed} 秒，剩余约 {remaining} 秒。"
        )
        page.wait_for_timeout(5000)


def _get_cookie_header(context: Any, url: str) -> str:
    """提取浏览器上下文 Cookie 头。"""

    cookies = context.cookies([url])
    return "; ".join(f"{item['name']}={item['value']}" for item in cookies)


def _download_with_browser_session(
    record: RetrievalRecord,
    download_dir: Path,
    *,
    context: Any,
    page: Any,
    ref_url: str,
    request_timeout: int,
    max_attempts: int,
    min_request_delay_seconds: float,
    max_request_delay_seconds: float,
) -> dict[str, Any]:
    """在人工登录后复用浏览器 Cookie 继续下载。"""

    page_html = page.content()
    page_candidates = _extract_pdf_links_from_html(page_html, ref_url)
    queue = _prioritize_pdf_candidates(
        [*page_candidates, page.url, record.pdf_url, *list(record.raw.get("download_candidates") or []), record.landing_url],
        record.doi,
    )
    visited: set[str] = set()
    attempts: list[dict[str, Any]] = []
    while queue and len(attempts) < max_attempts:
        candidate = queue.pop(0)
        if candidate in visited:
            continue
        visited.add(candidate)

        # 优先走浏览器原生会话，请求链路更接近真实用户，命中率高于 urllib+cookie。
        try:
            response = page.goto(candidate, wait_until="domcontentloaded", timeout=max(8000, request_timeout * 1000))
            response_headers = {str(k).lower(): str(v) for k, v in dict((response.headers if response else {}) or {}).items()}
            response_ct = _normalize_text(response_headers.get("content-type")).lower()
            if response and ("application/pdf" in response_ct):
                body = response.body()
                if body and body[:4] == b"%PDF":
                    filename = _safe_filename(record.bibtex_key or record.title, ".pdf")
                    output_path = download_dir / filename
                    output_path.write_bytes(body)
                    attempts.append(
                        {
                            "url": candidate,
                            "status": "PASS",
                            "message": "已通过浏览器会话直接下载 PDF",
                            "final_url": page.url,
                            "request_delay_seconds": 0.0,
                        }
                    )
                    return {
                        "status": "PASS",
                        "title": record.title,
                        "source": record.source,
                        "saved_path": str(output_path),
                        "sha256": _sha256_bytes(body),
                        "final_url": page.url,
                        "attempts": attempts,
                    }
        except Exception as exc:
            attempts.append(
                {
                    "url": candidate,
                    "status": "BROWSER_ERROR",
                    "message": str(exc),
                    "request_delay_seconds": 0.0,
                }
            )

        request_delay_seconds = round(_sample_delay(min_request_delay_seconds, max_request_delay_seconds), 3)
        try:
            cookie_header = _get_cookie_header(context, candidate or ref_url)
            body, headers, final_url = _request(
                candidate,
                accept="application/pdf,text/html,application/xhtml+xml",
                sleep_seconds=request_delay_seconds,
                timeout=request_timeout,
                extra_headers={
                    "Cookie": cookie_header,
                    "Referer": ref_url,
                },
            )
        except Exception as exc:
            attempts.append({
                "url": candidate,
                "status": "ERROR",
                "message": str(exc),
                "request_delay_seconds": request_delay_seconds,
            })
            continue

        content_type = headers.get("content-type", "")
        if "application/pdf" in content_type.lower() or body[:4] == b"%PDF":
            filename = _safe_filename(record.bibtex_key or record.title, ".pdf")
            output_path = download_dir / filename
            output_path.write_bytes(body)
            attempts.append({
                "url": candidate,
                "status": "PASS",
                "message": "已通过登录后浏览器会话下载 PDF",
                "final_url": final_url,
                "request_delay_seconds": request_delay_seconds,
            })
            return {
                "status": "PASS",
                "title": record.title,
                "source": record.source,
                "saved_path": str(output_path),
                "sha256": _sha256_bytes(body),
                "final_url": final_url,
                "attempts": attempts,
            }

        if "html" in content_type.lower() or body.startswith(b"<!DOCTYPE html") or body.startswith(b"<html"):
            html_text = body.decode("utf-8", errors="ignore")
            for next_candidate in _extract_pdf_links_from_html(html_text, final_url):
                if next_candidate not in visited:
                    queue.append(next_candidate)
            queue = _prioritize_pdf_candidates(queue, record.doi)
            attempts.append({
                "url": candidate,
                "status": "HTML",
                "message": "登录后会话已解析 HTML 并继续寻找 PDF",
                "final_url": final_url,
                "request_delay_seconds": request_delay_seconds,
            })
            continue

        attempts.append({
            "url": candidate,
            "status": "SKIPPED",
            "message": f"未识别的内容类型: {content_type}",
            "final_url": final_url,
            "request_delay_seconds": request_delay_seconds,
        })

    return {
        "status": "NO_OPEN_PDF",
        "title": record.title,
        "source": record.source,
        "attempt_count": len(attempts),
        "attempts": attempts,
    }


def _manual_login_retry(
    record: RetrievalRecord,
    download_dir: Path,
    *,
    start_url: str,
    request_timeout: int,
    max_attempts: int,
    min_request_delay_seconds: float,
    max_request_delay_seconds: float,
    allow_manual_intervention: bool,
    keep_browser_open: bool,
    browser_profile_dir: str,
    browser_cdp_port: int,
    manual_wait_timeout_seconds: int,
) -> dict[str, Any]:
    """打开浏览器等待人工登录后重试下载。"""

    profile_dir = Path(browser_profile_dir).expanduser().resolve()
    cdp_url = f"http://127.0.0.1:{browser_cdp_port}"
    browser_proc = _launch_edge_with_cdp(profile_dir, browser_cdp_port, start_url)
    playwright = None
    context = None
    try:
        time.sleep(2)
        playwright, context = _connect_context(cdp_url)
        page = _select_existing_page(context, preferred_url=start_url)
        page.goto(start_url, wait_until="domcontentloaded", timeout=45000)
        manual_events = _wait_for_human_if_needed(page, allow_manual_intervention, manual_wait_timeout_seconds)
        retry_result = _download_with_browser_session(
            record,
            download_dir,
            context=context,
            page=page,
            ref_url=page.url or start_url,
            request_timeout=request_timeout,
            max_attempts=max_attempts,
            min_request_delay_seconds=min_request_delay_seconds,
            max_request_delay_seconds=max_request_delay_seconds,
        )
        retry_result["manual_events"] = manual_events
        retry_result["browser"] = {
            "cdp_url": cdp_url,
            "profile_dir": str(profile_dir),
            "kept_open": keep_browser_open,
        }
        return retry_result
    finally:
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        if browser_proc is not None and not keep_browser_open:
            try:
                if browser_proc.poll() is None:
                    browser_proc.terminate()
            except Exception:
                pass


def analyze_barrier_with_bailian(barrier_text: str, api_key_file: str) -> dict[str, Any]:
    """用百炼辅助判断访问障碍文本。

    Args:
        barrier_text: 页面文本片段。
        api_key_file: API Key 文件路径。

    Returns:
        百炼分析结果。
    """

    prompt = (
        "请判断以下英文网页文本更像是验证码、登录页还是付费墙，并给出一句简短中文建议。\n\n"
        + barrier_text[:4000]
    )
    return invoke_aliyun_llm(
        prompt=prompt,
        system="你是开放获取访问诊断助手，输出简洁结论。",
        intent=ModelRoutingIntent(
            task_type="general",
            quality_tier="standard",
            budget_tier="cheap",
            latency_tier="medium",
            risk_level="low",
            affair_name="open_access_barrier_analysis",
            input_chars=len(barrier_text),
        ),
        max_tokens=512,
        temperature=0.1,
        api_key_file=api_key_file,
        affair_name="open_access_barrier_analysis",
        route_hints={
            "task_type": "general",
            "budget_tier": "cheap",
            "quality_tier": "standard",
            "input_chars": len(barrier_text),
        },
    )


def download_record(
    record: RetrievalRecord,
    download_dir: Path,
    *,
    bailian_api_key_file: str = "",
    request_timeout: int = DOWNLOAD_REQUEST_TIMEOUT,
    max_attempts: int = DOWNLOAD_HTML_EXPANSION_LIMIT,
    enable_barrier_analysis: bool = True,
    min_request_delay_seconds: float = 0.35,
    max_request_delay_seconds: float = 1.6,
    allow_manual_intervention: bool = False,
    keep_browser_open: bool = False,
    browser_profile_dir: str = "sandbox/runtime/web_browser_profiles/en_open_access_auth",
    browser_cdp_port: int = 9332,
    manual_wait_timeout_seconds: int = 900,
) -> dict[str, Any]:
    """尝试下载单条记录的公开 PDF。

    Args:
        record: 文献记录。
        download_dir: 下载目录。
        bailian_api_key_file: 可选百炼 Key 文件路径。
        request_timeout: 单次下载请求超时秒数。
        max_attempts: 单条记录最多尝试的候选数。
        enable_barrier_analysis: 是否对阻断页调用百炼分析。

    Returns:
        下载结果。
    """

    doi_resolved_candidates = _collect_doi_resolver_candidates(record.doi)
    queue = _prioritize_pdf_candidates(
        [record.pdf_url, *list(record.raw.get("download_candidates") or []), record.landing_url, *doi_resolved_candidates],
        record.doi,
    )
    visited: set[str] = set()
    attempts: list[dict[str, Any]] = []
    blocked_http_detected = False
    while queue and len(attempts) < max_attempts:
        candidate = queue.pop(0)
        if candidate in visited:
            continue
        visited.add(candidate)
        request_delay_seconds = round(_sample_delay(min_request_delay_seconds, max_request_delay_seconds), 3)
        try:
            body, headers, final_url = _request(
                candidate,
                accept="application/pdf,text/html,application/xhtml+xml",
                sleep_seconds=request_delay_seconds,
                timeout=request_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, urllib.error.HTTPError) and int(getattr(exc, "code", 0) or 0) in {401, 403, 429}:
                blocked_http_detected = True
            attempts.append(
                {
                    "url": candidate,
                    "status": "ERROR",
                    "message": str(exc),
                    "request_delay_seconds": request_delay_seconds,
                }
            )
            continue

        content_type = headers.get("content-type", "")
        if "application/pdf" in content_type.lower() or body[:4] == b"%PDF":
            filename = _safe_filename(record.bibtex_key or record.title, ".pdf")
            output_path = download_dir / filename
            output_path.write_bytes(body)
            attempts.append(
                {
                    "url": candidate,
                    "status": "PASS",
                    "message": "已下载 PDF",
                    "final_url": final_url,
                    "request_delay_seconds": request_delay_seconds,
                }
            )
            return {
                "status": "PASS",
                "title": record.title,
                "source": record.source,
                "saved_path": str(output_path),
                "sha256": _sha256_bytes(body),
                "final_url": final_url,
                "attempts": attempts,
            }

        if "html" in content_type.lower() or body.startswith(b"<!DOCTYPE html") or body.startswith(b"<html"):
            html_text = body.decode("utf-8", errors="ignore")
            barrier = _detect_access_barrier(html_text)
            if barrier is not None:
                barrier_payload = {
                    "status": "BLOCKED",
                    "title": record.title,
                    "source": record.source,
                    "barrier_type": barrier[0],
                    "evidence": barrier[1],
                    "final_url": final_url,
                    "attempts": attempts,
                    "request_delay_seconds": request_delay_seconds,
                }
                if bailian_api_key_file and enable_barrier_analysis:
                    try:
                        barrier_payload["bailian_analysis"] = analyze_barrier_with_bailian(html_text, bailian_api_key_file)
                    except Exception as exc:  # noqa: BLE001
                        barrier_payload["bailian_analysis_error"] = str(exc)
                if barrier[0] in {"login_required", "captcha_required"} and allow_manual_intervention:
                    manual_result = _manual_login_retry(
                        record,
                        download_dir,
                        start_url=final_url or candidate or record.landing_url or record.pdf_url,
                        request_timeout=request_timeout,
                        max_attempts=max_attempts,
                        min_request_delay_seconds=min_request_delay_seconds,
                        max_request_delay_seconds=max_request_delay_seconds,
                        allow_manual_intervention=allow_manual_intervention,
                        keep_browser_open=keep_browser_open,
                        browser_profile_dir=browser_profile_dir,
                        browser_cdp_port=browser_cdp_port,
                        manual_wait_timeout_seconds=manual_wait_timeout_seconds,
                    )
                    manual_result["pre_manual_barrier"] = barrier_payload
                    return manual_result
                return barrier_payload

            for next_candidate in _extract_pdf_links_from_html(html_text, final_url):
                if next_candidate not in visited:
                    queue.append(next_candidate)
            queue = _prioritize_pdf_candidates(queue, record.doi)
            attempts.append(
                {
                    "url": candidate,
                    "status": "HTML",
                    "message": "已解析 HTML 并继续寻找 PDF",
                    "final_url": final_url,
                    "request_delay_seconds": request_delay_seconds,
                }
            )
            continue

        attempts.append(
            {
                "url": candidate,
                "status": "SKIPPED",
                "message": f"未识别的内容类型: {content_type}",
                "final_url": final_url,
                "request_delay_seconds": request_delay_seconds,
            }
        )

    if allow_manual_intervention and blocked_http_detected:
        manual_result = _manual_login_retry(
            record,
            download_dir,
            start_url=record.landing_url or (f"https://doi.org/{record.doi}" if record.doi else ""),
            request_timeout=request_timeout,
            max_attempts=max_attempts,
            min_request_delay_seconds=min_request_delay_seconds,
            max_request_delay_seconds=max_request_delay_seconds,
            allow_manual_intervention=allow_manual_intervention,
            keep_browser_open=keep_browser_open,
            browser_profile_dir=browser_profile_dir,
            browser_cdp_port=browser_cdp_port,
            manual_wait_timeout_seconds=manual_wait_timeout_seconds,
        )
        manual_result["pre_manual_http_blocked"] = True
        return manual_result

    return {
        "status": "NO_OPEN_PDF",
        "title": record.title,
        "source": record.source,
        "attempt_count": len(attempts),
        "attempts": attempts,
    }


def write_metadata_outputs(records: list[RetrievalRecord], output_dir: Path) -> dict[str, str]:
    """写出元数据产物。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "english_metadata.json"
    csv_path = output_dir / "english_metadata.csv"
    bib_path = output_dir / "english_metadata.bib"

    json_path.write_text(
        json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["source", "title", "year", "doi", "journal", "authors", "landing_url", "pdf_url", "bibtex_key"],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "source": record.source,
                    "title": record.title,
                    "year": record.year,
                    "doi": record.doi,
                    "journal": record.journal,
                    "authors": "; ".join(record.authors),
                    "landing_url": record.landing_url,
                    "pdf_url": record.pdf_url,
                    "bibtex_key": record.bibtex_key,
                }
            )

    bib_path.write_text("\n\n".join(_record_to_bibtex(record) for record in records) + "\n", encoding="utf-8")
    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "bib": str(bib_path),
    }


def write_download_outputs(manifest: list[dict[str, Any]], output_dir: Path) -> dict[str, str]:
    """写出下载产物。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "english_download_manifest.json"
    csv_path = output_dir / "english_download_manifest.csv"

    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["status", "title", "source", "saved_path", "sha256", "final_url", "barrier_type"],
        )
        writer.writeheader()
        for item in manifest:
            writer.writerow(
                {
                    "status": item.get("status", ""),
                    "title": item.get("title", ""),
                    "source": item.get("source", ""),
                    "saved_path": item.get("saved_path", ""),
                    "sha256": item.get("sha256", ""),
                    "final_url": item.get("final_url", ""),
                    "barrier_type": item.get("barrier_type", ""),
                }
            )
    return {
        "json": str(json_path),
        "csv": str(csv_path),
    }
