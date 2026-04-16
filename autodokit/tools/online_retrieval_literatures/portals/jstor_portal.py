"""JSTOR 门户候选链接构建。"""

from __future__ import annotations

import urllib.parse
from typing import Any

from .common import extract_hrefs, normalize_text, request_text


def build_candidates(base_url: str, record: dict[str, Any]) -> list[str]:
    title = normalize_text(record.get("title"))
    candidates: list[str] = []
    if title:
        search_url = f"{base_url.rstrip('/')}/action/doBasicSearch?Query={urllib.parse.quote(title)}&so=rel"
        candidates.append(search_url)
        try:
            html_text = request_text(search_url, referer=base_url)
            stable_links = extract_hrefs(html_text, base_url, [r"/stable/"])
            candidates.extend(stable_links[:3])
            for stable_link in stable_links[:2]:
                stable_id = stable_link.rstrip("/").split("/stable/")[-1]
                if stable_id:
                    candidates.append(f"{base_url.rstrip('/')}/stable/pdf/{stable_id}.pdf")
        except Exception:
            pass
    return candidates
