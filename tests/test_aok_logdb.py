"""AOK SQLite 日志数据库工具测试。"""

from __future__ import annotations

import json
from pathlib import Path

from autodokit.tools.atomic.log_aok import (
    append_aok_log_event,
    bootstrap_aok_logdb,
    list_aok_log_events,
    repair_aok_logdb,
    record_aok_gate_review,
    record_aok_human_decision,
    record_aok_log_artifact,
    resolve_aok_log_db_path,
    validate_aok_logdb,
)


def test_bootstrap_and_validate_aok_logdb_should_work(tmp_path: Path) -> None:
    """AOK SQLite 日志数据库初始化与校验应可运行。"""

    boot = bootstrap_aok_logdb(project_root=tmp_path)
    assert boot["status"] == "PASS"
    assert Path(boot["db_path"]).exists()

    validate = validate_aok_logdb(project_root=tmp_path)
    assert validate["status"] == "PASS"
    assert validate["error_count"] == 0


def test_append_and_list_aok_log_events_should_work(tmp_path: Path) -> None:
    """AOK 极简日志事件与审计记录应可运行。"""

    bootstrap_aok_logdb(project_root=tmp_path)

    row = append_aok_log_event(
        project_root=tmp_path,
        event_type="step.completed",
        handler_kind="local_script",
        handler_name="run_items_sync.py",
        model_name="GPT-5.4",
        skill_names=["api-data-fetch"],
        agent_names=["通用任务运作智能体"],
        read_files=["docs/design-001.md", "docs/plan-001.md"],
        script_path="scripts/run_items_sync.py",
        third_party_tool="",
        reasoning_summary="读取计划后执行同步脚本并记录结果",
        conversation_excerpt="用户要求只在 AOK 内调试",
        payload={"status": "ok", "rows": 12},
    )

    assert row["event_type"] == "step.completed"
    assert row["handler_name"] == "run_items_sync.py"

    artifact = record_aok_log_artifact(
        project_root=tmp_path,
        affair_code="A04",
        artifact_type="csv",
        file_path="workspace/steps/A04/results.csv",
        file_role="working_output",
        produced_by_event_uid=row["event_uid"],
    )
    assert artifact["affair_code"] == "A04"

    review = record_aok_gate_review(
        project_root=tmp_path,
        gate_code="G04",
        affair_code="A04",
        reviewer_agent="审计Agent",
        review_summary="检索链路通过，允许进入下一步",
        decision_candidates=["pass_next", "revise_same_round"],
    )
    assert review["gate_code"] == "G04"

    decision = record_aok_human_decision(
        project_root=tmp_path,
        gate_code="G04",
        affair_code="A04",
        decision="pass_next",
        rationale="首轮基线足够进入后续流程",
        operator_name="Ethan",
    )
    assert decision["decision"] == "pass_next"

    all_rows = list_aok_log_events(project_root=tmp_path)
    assert len(all_rows) == 1

    filtered = list_aok_log_events(
        project_root=tmp_path,
        handler_kind="local_script",
        event_type="step.completed",
    )
    assert len(filtered) == 1
    assert filtered[0]["handler_name"] == "run_items_sync.py"


def test_bootstrap_should_block_when_db_path_is_directory(tmp_path: Path) -> None:
    """当日志数据库文件路径被目录占用时，应返回 BLOCKED。"""

    bad_db_path = tmp_path / "database" / "logs" / "aok_log.db"
    bad_db_path.mkdir(parents=True, exist_ok=True)

    boot = bootstrap_aok_logdb(project_root=tmp_path)
    assert boot["status"] == "BLOCKED"
    assert boot["reason"] == "invalid_logdb_path_shape"
    assert any("当前是目录" in error for error in boot["errors"])


def test_append_should_skip_when_logdb_unavailable(tmp_path: Path) -> None:
    """日志库不可用时写入接口应降级为 SKIPPED，不阻断业务。"""

    bad_db_path = tmp_path / "database" / "logs" / "aok_log.db"
    bad_db_path.mkdir(parents=True, exist_ok=True)

    row = append_aok_log_event(
        project_root=tmp_path,
        event_type="step.completed",
        handler_name="non_blocking_case.py",
    )
    assert row["status"] == "SKIPPED"
    assert row["reason"] == "logdb_unavailable"


def test_repair_should_quarantine_bad_directory_and_rebuild_db(tmp_path: Path) -> None:
    """修复接口应隔离错误目录并重建可用数据库文件。"""

    bad_db_path = tmp_path / "database" / "logs" / "aok_log.db"
    bad_db_path.mkdir(parents=True, exist_ok=True)

    repair = repair_aok_logdb(project_root=tmp_path)
    assert repair["status"] == "PASS"
    assert any(action.startswith("quarantine_directory:") for action in repair["actions"])
    assert any(action == "bootstrap_schema:PASS" for action in repair["actions"])

    db_path = Path(repair["db_path"])
    assert db_path.exists()
    assert db_path.is_file()

    quarantined = [Path(path) for path in repair["quarantined_paths"]]
    assert quarantined
    assert quarantined[0].exists()
    assert quarantined[0].is_dir()


def test_resolve_aok_log_db_path_should_anchor_relative_path_to_workspace_root(tmp_path: Path) -> None:
    """配置文件中的相对 log_db_path 应基于 workspace_root 解析。"""

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    config_payload = {
        "paths": {
            "log_db_path": "workspace/database/logs/aok_custom.db",
        }
    }
    config_path.write_text(json.dumps(config_payload, ensure_ascii=False), encoding="utf-8")

    resolved_path = resolve_aok_log_db_path(tmp_path)
    expected_path = (tmp_path / "workspace" / "database" / "logs" / "aok_custom.db").resolve()
    assert resolved_path == expected_path
