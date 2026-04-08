"""AOK 任务数据库事务隔离测试。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path


def test_aok_taskdb_bootstrap_affair_execute_should_work(tmp_path: Path) -> None:
    """AOK 任务数据库初始化事务应可执行并产出结果文件。"""

    module = importlib.import_module("autodokit.affairs.AOK任务数据库初始化.affair")
    config_path = tmp_path / "bootstrap_config.json"
    config_path.write_text(
        json.dumps({"project_root": str(tmp_path), "output_dir": str(tmp_path)}, ensure_ascii=False),
        encoding="utf-8",
    )

    outputs = module.execute(config_path)
    assert len(outputs) == 1
    result_file = outputs[0]
    assert result_file.exists()

    payload = json.loads(result_file.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"


def test_aok_taskdb_validate_affair_execute_should_work(tmp_path: Path) -> None:
    """AOK 任务数据库校验事务应可执行并返回校验状态。"""

    bootstrap_module = importlib.import_module("autodokit.affairs.AOK任务数据库初始化.affair")
    validate_module = importlib.import_module("autodokit.affairs.AOK任务数据库校验.affair")

    bootstrap_config = tmp_path / "bootstrap_config.json"
    bootstrap_config.write_text(
        json.dumps({"project_root": str(tmp_path), "output_dir": str(tmp_path)}, ensure_ascii=False),
        encoding="utf-8",
    )
    bootstrap_module.execute(bootstrap_config)

    validate_config = tmp_path / "validate_config.json"
    validate_config.write_text(
        json.dumps({"project_root": str(tmp_path), "output_dir": str(tmp_path)}, ensure_ascii=False),
        encoding="utf-8",
    )

    outputs = validate_module.execute(validate_config)
    assert len(outputs) == 1
    payload = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert payload["status"] in {"PASS", "BLOCKED"}


def test_aok_taskdb_affairs_should_support_custom_roots(tmp_path: Path) -> None:
    """AOK 任务数据库事务应支持自定义任务数据库目录。"""

    bootstrap_module = importlib.import_module("autodokit.affairs.AOK任务数据库初始化.affair")
    validate_module = importlib.import_module("autodokit.affairs.AOK任务数据库校验.affair")

    tasks_db_root = tmp_path / "db" / "tasks_db"
    tasks_workspace_root = tmp_path / "tasks"

    bootstrap_config = tmp_path / "bootstrap_custom_config.json"
    bootstrap_config.write_text(
        json.dumps(
            {
                "project_root": str(tmp_path),
                "tasks_db_root": str(tasks_db_root),
                "tasks_workspace_root": str(tasks_workspace_root),
                "output_dir": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bootstrap_module.execute(bootstrap_config)

    task_uid = "task-affair-001"
    task_dir = tasks_workspace_root / task_uid
    task_dir.mkdir(parents=True, exist_ok=True)
    (tasks_db_root / "tasks.csv").write_text(
        "aok_task_uid,task_name,task_goal,task_status,workspace_dir,literature_uids,knowledge_uids,created_at,updated_at\n"
        f"{task_uid},事务任务,目标,completed,{task_dir},,,2026-03-23T00:00:00+00:00,2026-03-23T00:00:00+00:00\n",
        encoding="utf-8",
    )
    artifact_file = task_dir / "artifact.txt"
    artifact_file.write_text("artifact", encoding="utf-8")
    (tasks_db_root / "task_artifacts.csv").write_text(
        "aok_task_uid,artifact_name,artifact_type,artifact_path,note,created_at\n"
        f"{task_uid},artifact,report,{artifact_file},,2026-03-23T00:00:00+00:00\n",
        encoding="utf-8",
    )

    validate_config = tmp_path / "validate_custom_config.json"
    validate_config.write_text(
        json.dumps(
            {
                "project_root": str(tmp_path),
                "tasks_db_root": str(tasks_db_root),
                "tasks_workspace_root": str(tasks_workspace_root),
                "output_dir": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    outputs = validate_module.execute(validate_config)
    payload = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert payload["status"] in {"PASS", "BLOCKED"}
    assert payload["error_count"] == 0
