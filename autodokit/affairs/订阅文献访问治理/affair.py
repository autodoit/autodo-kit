"""订阅文献访问治理事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def govern_subscribed_access(
    target_records: list[dict[str, Any]],
    access_scope: str,
    auth_mode: str,
) -> dict[str, Any]:
    """评估订阅文献访问范围与授权方式。"""

    allowed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in target_records:
        title = str(item.get("title") or item.get("query") or "").strip()
        if auth_mode == "manual" or access_scope == "campus":
            blocked.append({"title": title, "reason": "需要人工授权或校园网环境"})
        else:
            allowed.append({"title": title, "status": "approved"})

    return {
        "status": "PASS" if not blocked else "BLOCKED",
        "mode": "cn-subscribed-literature-access",
        "result": {
            "access_scope": access_scope,
            "auth_mode": auth_mode,
            "allowed": allowed,
            "blocked": blocked,
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = govern_subscribed_access(
        target_records=list(raw_cfg.get("target_records") or []),
        access_scope=str(raw_cfg.get("access_scope") or "campus"),
        auth_mode=str(raw_cfg.get("auth_mode") or "manual"),
    )
    return write_affair_json_result(raw_cfg, config_path, "cn_subscribed_literature_access_result.json", result)
