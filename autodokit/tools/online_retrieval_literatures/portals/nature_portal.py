"""Nature 门户候选链接构建。"""

from __future__ import annotations

import urllib.parse
from typing import Any

from .common import extract_hrefs, normalize_text, request_text


def build_candidates(base_url: str, record: dict[str, Any]) -> list[str]:
    title = normalize_text(record.get("title"))
    candidates: list[str] = []
    if title:
        search_url = f"{base_url.rstrip('/')}/search?q={urllib.parse.quote(title)}"
        candidates.append(search_url)
        try:
            html_text = request_text(search_url, referer=base_url)
            candidates.extend(extract_hrefs(html_text, base_url, [r"/articles/"])[:4])
        except Exception:
            pass
    return candidates
