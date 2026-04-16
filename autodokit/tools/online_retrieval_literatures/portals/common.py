"""英文门户候选链接构建共用工具。"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from typing import Any


USER_AGENT = "AcademicResearchAutoWorkflow-ChaoxingRetry/0.1"


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def request_text(url: str, *, timeout: int = 30, referer: str = "") -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def extract_hrefs(html_text: str, base_url: str, patterns: list[str]) -> list[str]:
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html_text, flags=re.I)
    results: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        absolute = urllib.parse.urljoin(base_url, href)
        lowered = absolute.lower()
        if any(re.search(pattern, lowered) for pattern in patterns):
            if absolute not in seen:
                seen.add(absolute)
                results.append(absolute)
    return results
