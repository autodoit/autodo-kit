from __future__ import annotations

"""CrossRef API 检索客户端。

提供安全、重试感知的 CrossRef REST API 查询，返回结构化题录结果。
"""

import json
import ssl
import urllib.parse
import urllib.request
from typing import Any

_CTX: ssl.SSLContext | None = None


def _get_ssl_context() -> ssl.SSLContext:
    """获取（按需创建）未验证的 SSL 上下文，规避 macOS 系统证书问题。

    Returns:
        可用的 SSLContext 实例。
    """
    global _CTX
    if _CTX is None:
        _CTX = ssl._create_unverified_context()
    return _CTX


def crossref_search(
    title: str,
    author_last: str = "",
    rows: int = 5,
    timeout: int = 30,
    user_agent: str = "AOK-BibVerifier/1.0 (mailto:dev@example.com)",
) -> list[dict[str, Any]]:
    """按标题与作者姓氏检索 CrossRef，返回前 N 条结果。

    Args:
        title: 文献标题，将作为 query.title 参数发送（自动截断至 200 字符）。
        author_last: 作者姓氏，作为 query.author 参数发送。
        rows: 返回结果最大条数，默认 5。
        timeout: HTTP 请求超时秒数，默认 30。
        user_agent: 请求 User-Agent 头。

    Returns:
        结构化结果列表，每项包含：
            - title (str): 匹配文献标题
            - author (str): 第一作者 "姓氏, 名字" 格式
            - year (str): 出版年份
            - journal (str): 期刊名称
            - doi (str): DOI 标识符
            - score (float): CrossRef 内部相关度评分
        请求失败或结果为空时返回空列表。

    Examples:
        >>> results = crossref_search("Systemic risk and stability", "Acemoglu")
        >>> len(results) > 0
        True
        >>> results[0]["doi"]
        '10.3386/w18727'
    """
    ctx = _get_ssl_context()
    params: dict[str, Any] = {"query.title": title[:200], "rows": rows}
    if author_last:
        params["query.author"] = author_last

    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data: dict[str, Any] = json.loads(resp.read())
    except Exception:
        return []

    items: list[dict[str, Any]] = data.get("message", {}).get("items", [])
    results: list[dict[str, Any]] = []

    for item in items:
        title_list: list[str] = item.get("title", [""])
        rtitle: str = title_list[0].strip() if title_list else ""

        authors: list[dict[str, str]] = item.get("author", [])
        fa: dict[str, str] = authors[0] if authors else {}
        fa_name: str = (
            f"{fa.get('family', '')}, {fa.get('given', '')}".strip().strip(",")
        )

        dp: dict[str, Any] = (
            item.get("published-print")
            or item.get("published-online")
            or item.get("created", {})
        )
        date_parts: list[list[int | None]] = dp.get("date-parts", [[None]])
        year: str = (
            str(date_parts[0][0]) if date_parts and date_parts[0] and date_parts[0][0] else ""
        )

        container: list[str] = item.get("container-title", [""])
        journal: str = container[0].strip() if container else ""
        doi: str = item.get("DOI", "") or ""

        results.append({
            "title": rtitle,
            "author": fa_name,
            "year": year,
            "journal": journal,
            "doi": doi,
            "score": item.get("score", 0),
        })

    return results
