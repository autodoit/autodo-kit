"""任务数据库回放事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def replay_taskdb(project_root: str | Path = ".") -> dict[str, Any]:
    """回放任务执行日志。"""

    root = Path(project_root).resolve()
    log_path = root / "database" / "tasks" / "execution_runs.jsonl"
    events: list[dict[str, Any]] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                events.append({"raw": raw, "parse_error": True})
    return {
        "status": "PASS",
        "mode": "taskdb-replay",
        "project_root": str(root),
        "result": {
            "event_count": len(events),
            "events": events,
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = replay_taskdb(project_root=str(raw_cfg.get("project_root") or "."))
    return write_affair_json_result(raw_cfg, config_path, "taskdb_replay_result.json", result)
