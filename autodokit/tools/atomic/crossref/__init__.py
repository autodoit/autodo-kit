from __future__ import annotations

"""CrossRef 在线验证工具子包。

提供 CrossRef API 检索、题录条目匹配评分与批量验证功能。
"""

from autodokit.tools.atomic.crossref.crossref_client import crossref_search
from autodokit.tools.atomic.crossref.verification import (
    crossref_match_score,
    crossref_verify_single,
    crossref_batch_verify,
    crossref_verify_tracker,
)

__all__ = [
    "crossref_search",
    "crossref_match_score",
    "crossref_verify_single",
    "crossref_batch_verify",
    "crossref_verify_tracker",
]

__all__ = [
    "crossref_search",
    "crossref_match_score",
    "crossref_verify_single",
    "crossref_batch_verify",
    "crossref_verify_tracker",
]
