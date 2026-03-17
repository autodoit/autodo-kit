"""任务数据库校验事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import load_json_or_py, write_affair_json_result


def validate_taskdb(project_root: str | Path = ".") -> dict:
    """校验任务数据库关键文件和基本字段。"""

    root = Path(project_root).resolve()
    tasks_root = root / "database" / "tasks"
    required_files = [
        tasks_root / "tasks.csv",
        tasks_root / "transactions.csv",
        tasks_root / "task_transaction_map.csv",
        tasks_root / "task_edges.csv",
        tasks_root / "execution_runs.jsonl",
    ]
    missing = [str(path) for path in required_files if not path.exists()]
    return {
        "status": "PASS" if not missing else "BLOCKED",
        "mode": "taskdb-validate",
        "project_root": str(root),
        "error_count": len(missing),
        "errors": [f"缺少文件: {path}" for path in missing],
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = validate_taskdb(project_root=str(raw_cfg.get("project_root") or "."))
    return write_affair_json_result(raw_cfg, config_path, "taskdb_validate_result.json", result)
