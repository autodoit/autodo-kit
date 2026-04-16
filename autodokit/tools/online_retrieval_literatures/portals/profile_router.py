"""英文门户 profile 路由。"""

from __future__ import annotations

from typing import Any, Callable

from .common import normalize_text
from .jstor_portal import build_candidates as build_jstor_candidates
from .nature_portal import build_candidates as build_nature_candidates
from .sciencedirect_portal import build_candidates as build_sciencedirect_candidates
from .springer_portal import build_candidates as build_springer_candidates
from .wiley_portal import build_candidates as build_wiley_candidates


CandidateBuilder = Callable[[str, dict[str, Any]], list[str]]

_PROFILE_BUILDERS: dict[str, CandidateBuilder] = {
    "springer": build_springer_candidates,
    "sciencedirect": build_sciencedirect_candidates,
    "wiley": build_wiley_candidates,
    "jstor": build_jstor_candidates,
    "nature": build_nature_candidates,
}


def infer_record_profile(record: dict[str, Any]) -> str:
    doi = normalize_text(record.get("doi"))
    merged = " ".join(
        [
            doi,
            normalize_text(record.get("landing_url")),
            normalize_text(record.get("pdf_url")),
            " ".join(str(item) for item in list((record.get("raw") or {}).get("download_candidates") or [])),
        ]
    ).lower()
    if doi.startswith("10.1007/") or "springer" in merged:
        return "springer"
    if doi.startswith("10.1016/") or any(token in merged for token in ["sciencedirect", "elsevier", "linkinghub"]):
        return "sciencedirect"
    if any(token in merged for token in ["onlinelibrary.wiley", "wiley"]):
        return "wiley"
    if "jstor" in merged:
        return "jstor"
    if "nature.com" in merged:
        return "nature"
    return "generic"


def build_portal_candidates(profile: str, base_url: str, record: dict[str, Any]) -> list[str]:
    builder = _PROFILE_BUILDERS.get(profile)
    if builder is None:
        return []
    return builder(base_url, record)
