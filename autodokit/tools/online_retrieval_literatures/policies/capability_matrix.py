"""在线检索能力矩阵策略。

矩阵用于显式声明 source+mode+action 组合是否可执行。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autodokit.tools.online_retrieval_literatures.catalogs import canonical_source

_FALLBACK_CAPABILITY_MATRIX: dict[tuple[str, str, str], dict[str, Any]] = {
    ("zh_cnki", "search", "metadata"): {"layer": "executor", "stable": True},
    ("zh_cnki", "single", "download"): {"layer": "executor", "stable": True},
    ("zh_cnki", "single", "html_extract"): {"layer": "executor", "stable": True},
    ("zh_cnki", "batch", "download"): {"layer": "orchestrator", "stable": True},
    ("zh_cnki", "batch", "html_extract"): {"layer": "orchestrator", "stable": True},

    ("en_open_access", "search", "metadata"): {"layer": "executor", "stable": True},
    ("en_open_access", "single", "download"): {"layer": "executor", "stable": True},
    ("en_open_access", "single", "html_extract"): {"layer": "executor", "stable": True},
    ("en_open_access", "batch", "download"): {"layer": "orchestrator", "stable": True},
    ("en_open_access", "batch", "html_extract"): {"layer": "orchestrator", "stable": True},
    ("en_open_access", "retry", "chaoxing_portal"): {"layer": "orchestrator", "stable": True},

    ("spis", "search", "metadata"): {"layer": "executor", "stable": True},
    ("spis", "single", "download"): {"layer": "executor", "stable": True},
    ("spis", "single", "html_extract"): {"layer": "executor", "stable": True},
    ("spis", "batch", "download"): {"layer": "orchestrator", "stable": True},
    ("spis", "batch", "html_extract"): {"layer": "orchestrator", "stable": True},

    ("school_foreign_database_portal", "catalog", "fetch"): {"layer": "orchestrator", "stable": True},

    ("all", "debug", "run"): {"layer": "router", "stable": True},
    ("zh_cnki", "debug", "pipeline"): {"layer": "router", "stable": True},
    ("en_open_access", "debug", "pipeline"): {"layer": "router", "stable": True},
}


def _load_from_config() -> dict[tuple[str, str, str], dict[str, Any]]:
    config_path = Path(__file__).resolve().parent.parent / "config.json"
    if not config_path.exists():
        return {}
    loaded = json.loads(config_path.read_text(encoding="utf-8"))
    rows = list((loaded or {}).get("capability_matrix") or [])
    matrix: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = canonical_source(str(row.get("source") or ""))
        mode = str(row.get("mode") or "").strip()
        action = str(row.get("action") or "").strip()
        if not source or not mode or not action:
            continue
        matrix[(source, mode, action)] = {"layer": str(row.get("layer") or "unknown"), "stable": True}
    return matrix


def load_capability_matrix() -> dict[tuple[str, str, str], dict[str, Any]]:
    """返回能力矩阵副本。

    Returns:
        dict[tuple[str, str, str], dict[str, Any]]: 能力矩阵拷贝。
    """
    merged = dict(_FALLBACK_CAPABILITY_MATRIX)
    loaded = _load_from_config()
    if loaded:
        merged.update(loaded)
    return merged


def get_capability_cell(source: str, mode: str, action: str) -> dict[str, Any] | None:
    """查询能力矩阵单元。

    Args:
        source: 来源名称。
        mode: 运行模式。
        action: 动作名称。

    Returns:
        dict[str, Any] | None: 命中的矩阵单元。
    """
    key = (canonical_source(source), (mode or "").strip(), (action or "").strip())
    cell = load_capability_matrix().get(key)
    return dict(cell) if isinstance(cell, dict) else None


def assert_supported_combo(source: str, mode: str, action: str) -> dict[str, Any]:
    """校验路由组合是否在能力矩阵中。

    Args:
        source: 来源名称。
        mode: 运行模式。
        action: 动作名称。

    Returns:
        dict[str, Any]: 命中的矩阵单元。

    Raises:
        ValueError: 组合不在能力矩阵中。
    """
    cell = get_capability_cell(source, mode, action)
    if cell is None:
        normalized_source = canonical_source(source)
        raise ValueError(
            f"不支持的路由组合: source={normalized_source}, mode={(mode or '').strip()}, action={(action or '').strip()}"
        )
    return cell
