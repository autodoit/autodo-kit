"""任务数据库初始化事务。"""

from __future__ import annotations

import json
from pathlib import Path

from autodokit.tools import load_json_or_py, write_affair_json_result


def bootstrap_taskdb(project_root: str | Path = ".") -> dict:
    """初始化任务数据库模板。"""

    root = Path(project_root).resolve()
    tasks_root = root / "database" / "tasks"
    tasks_root.mkdir(parents=True, exist_ok=True)
    files = {
        "tasks.csv": "task_uid,title,status,created_at,updated_at\n",
        "transactions.csv": "transaction_uid,task_uid,name,status,created_at,updated_at\n",
        "task_transaction_map.csv": "map_uid,task_uid,transaction_uid,step_status,created_at\n",
        "task_edges.csv": "edge_uid,from_transaction_uid,to_transaction_uid,weight\n",
    }
    created_paths: list[str] = []
    for file_name, content in files.items():
        target = tasks_root / file_name
        if not target.exists():
            target.write_text(content, encoding="utf-8")
        created_paths.append(str(target))
    execution_path = tasks_root / "execution_runs.jsonl"
    execution_path.touch(exist_ok=True)
    created_paths.append(str(execution_path))
    manifest_path = tasks_root / "manifests.json"
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps({"schema_version": "0.1.0", "generated_at": ""}, ensure_ascii=False, indent=2), encoding="utf-8")
    created_paths.append(str(manifest_path))
    return {
        "status": "PASS",
        "mode": "taskdb-bootstrap",
        "project_root": str(root),
        "artifacts": {"tasks_root": str(tasks_root)},
        "created_paths": created_paths,
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = bootstrap_taskdb(project_root=str(raw_cfg.get("project_root") or "."))
    return write_affair_json_result(raw_cfg, config_path, "taskdb_bootstrap_result.json", result)
