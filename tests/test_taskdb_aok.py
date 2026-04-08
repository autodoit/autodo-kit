"""AOK 任务管理系统隔离工具测试。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools.atomic.task_aok.taskdb import (
    bootstrap_aok_taskdb,
    init_empty_task_artifacts_table,
    init_empty_tasks_table,
    task_artifact_register,
    task_bind_knowledges,
    task_bind_literatures,
    task_bundle_export,
    task_create_or_update,
    task_get,
    validate_aok_taskdb,
)


def test_task_create_and_bind_should_work() -> None:
    """任务创建与文献/知识绑定应按预期工作。"""

    tasks = init_empty_tasks_table()
    tasks, record, action = task_create_or_update(
        tasks,
        {
            "task_name": "AOK任务001",
            "task_goal": "验证任务系统",
            "task_status": "running",
        },
        workspace_root=Path.cwd(),
    )
    assert action == "inserted"
    assert record["aok_task_uid"].startswith("task-")
    assert Path(record["workspace_dir"]).exists()

    tasks, bound_lit, invalid_lit = task_bind_literatures(
        tasks,
        aok_task_uid=record["aok_task_uid"],
        literature_uids=["lit-001", "lit-001", "lit-002"],
    )
    assert invalid_lit == []
    assert bound_lit["literature_uids"] == "lit-001|lit-002"

    tasks, bound_kn, invalid_kn = task_bind_knowledges(
        tasks,
        aok_task_uid=record["aok_task_uid"],
        knowledge_uids="kn-001|kn-002|kn-001",
    )
    assert invalid_kn == []
    assert bound_kn["knowledge_uids"] == "kn-001|kn-002"


def test_task_artifact_register_and_bundle_export_should_work(tmp_path: Path) -> None:
    """任务产物登记与导出应按任务 UID 正常运行。"""

    tasks = init_empty_tasks_table()
    artifacts = init_empty_task_artifacts_table()

    tasks, record, _ = task_create_or_update(
        tasks,
        {
            "task_name": "AOK任务产物测试",
            "task_goal": "登记并导出产物",
        },
        workspace_root=tmp_path,
    )

    task_uid = record["aok_task_uid"]
    temp_file = Path(record["workspace_dir"]) / "result.txt"
    temp_file.write_text("ok", encoding="utf-8")

    tasks, artifacts, row = task_artifact_register(
        tasks,
        artifacts,
        aok_task_uid=task_uid,
        artifact_name="结果文件",
        artifact_type="report",
        artifact_path=str(temp_file),
    )
    assert row["artifact_name"] == "结果文件"

    result = task_bundle_export(artifacts, aok_task_uid=task_uid, output_dir=tmp_path / "tmp_task_bundle")
    assert result["status"] in {"PASS", "WARN"}
    assert result["export_count"] == 1

    fetched = task_get(tasks, artifacts, aok_task_uid=task_uid)
    assert fetched["artifact_count"] == 1


def test_bootstrap_and_validate_aok_taskdb_should_work(tmp_path: Path) -> None:
    """AOK 任务数据库初始化与校验事务工具应可工作。"""

    boot = bootstrap_aok_taskdb(project_root=tmp_path)
    assert boot["status"] == "PASS"

    task_uid = "task-001"
    task_dir = tmp_path / "tasks" / task_uid
    task_dir.mkdir(parents=True, exist_ok=True)

    tasks_csv = tmp_path / "database" / "tasks" / "tasks.csv"
    tasks_csv.write_text(
        "aok_task_uid,task_name,task_goal,task_status,workspace_dir,literature_uids,knowledge_uids,created_at,updated_at\n"
        f"{task_uid},测试任务,目标,draft,{task_dir},,,2026-03-23T00:00:00+00:00,2026-03-23T00:00:00+00:00\n",
        encoding="utf-8",
    )

    artifact_file = task_dir / "artifact.txt"
    artifact_file.write_text("artifact", encoding="utf-8")
    artifacts_csv = tmp_path / "database" / "tasks" / "task_artifacts.csv"
    artifacts_csv.write_text(
        "aok_task_uid,artifact_name,artifact_type,artifact_path,note,created_at\n"
        f"{task_uid},artifact,report,{artifact_file},,2026-03-23T00:00:00+00:00\n",
        encoding="utf-8",
    )

    validate = validate_aok_taskdb(project_root=tmp_path)
    assert validate["status"] in {"PASS", "BLOCKED"}
    assert validate["error_count"] == 0


def test_bootstrap_and_validate_aok_taskdb_with_custom_roots_should_work(tmp_path: Path) -> None:
    """AOK 任务数据库支持自定义元数据目录与任务目录。"""

    tasks_db_root = tmp_path / "db" / "tasks_db"
    tasks_workspace_root = tmp_path / "work" / "task_runs"

    boot = bootstrap_aok_taskdb(
        project_root=tmp_path,
        tasks_db_root=tasks_db_root,
        tasks_workspace_root=tasks_workspace_root,
    )
    assert boot["status"] == "PASS"
    assert (tasks_db_root / "tasks.csv").exists()
    assert (tasks_db_root / "task_artifacts.csv").exists()

    task_uid = "task-custom-001"
    task_dir = tasks_workspace_root / task_uid
    task_dir.mkdir(parents=True, exist_ok=True)

    (tasks_db_root / "tasks.csv").write_text(
        "aok_task_uid,task_name,task_goal,task_status,workspace_dir,literature_uids,knowledge_uids,created_at,updated_at\n"
        f"{task_uid},自定义任务,目标,completed,{task_dir},,,2026-03-23T00:00:00+00:00,2026-03-23T00:00:00+00:00\n",
        encoding="utf-8",
    )

    artifact_file = task_dir / "artifact.txt"
    artifact_file.write_text("artifact", encoding="utf-8")
    (tasks_db_root / "task_artifacts.csv").write_text(
        "aok_task_uid,artifact_name,artifact_type,artifact_path,note,created_at\n"
        f"{task_uid},artifact,report,{artifact_file},,2026-03-23T00:00:00+00:00\n",
        encoding="utf-8",
    )

    validate = validate_aok_taskdb(
        project_root=tmp_path,
        tasks_db_root=tasks_db_root,
        tasks_workspace_root=tasks_workspace_root,
    )
    assert validate["status"] in {"PASS", "BLOCKED"}
    assert validate["error_count"] == 0
