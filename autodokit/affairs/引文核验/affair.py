"""引文核验事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def verify_citations(
    citations: list[dict[str, Any]],
    references: list[dict[str, Any]] | list[str],
) -> dict[str, Any]:
    """核验正文引文与参考文献的对应关系。

    Args:
        citations: 正文引文列表。
        references: 参考文献列表。

    Returns:
        核验结果。
    """

    reference_keys: set[str] = set()
    for item in references:
        if isinstance(item, dict):
            key = str(item.get("citation_key") or item.get("key") or item.get("title") or "").strip()
        else:
            key = str(item).strip()
        if key:
            reference_keys.add(key)

    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for item in citations:
        citation_key = str(item.get("citation_key") or item.get("key") or "").strip()
        if citation_key and citation_key in reference_keys:
            matched.append({"citation_key": citation_key, "statement": str(item.get("statement") or "")})
        else:
            missing.append({"citation_key": citation_key, "statement": str(item.get("statement") or "")})

    return {
        "status": "PASS" if not missing else "BLOCKED",
        "mode": "citation-verification",
        "result": {
            "matched_count": len(matched),
            "missing_count": len(missing),
            "matched": matched,
            "missing": missing,
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = verify_citations(
        citations=list(raw_cfg.get("citations") or []),
        references=list(raw_cfg.get("references") or []),
    )
    return write_affair_json_result(raw_cfg, config_path, "citation_verification_result.json", result)
