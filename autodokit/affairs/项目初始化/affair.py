"""项目初始化事务。"""

from __future__ import annotations

from datetime import datetime
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, List

from autodokit.tools import (
    bootstrap_aok_logdb,
    bootstrap_aok_taskdb,
    load_json_or_py,
)
from autodokit.tools.atomic.task_aok.git_snapshot_ledger import git_workspace_init
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.atomic.task_aok.task_instance_dir import resolve_legacy_output_dir
from autodokit.tools.bibliodb_sqlite import init_db as init_references_db
from autodokit.tools.contentdb_sqlite import (
    CONTENT_DB_DIRECTORY_NAME,
    DEFAULT_CONTENT_DB_NAME,
    build_pdf_structured_variant_dir_map,
)
from autodokit.tools.knowledgedb_sqlite import init_db as init_knowledge_db


class ProjectInitializationEngine:
    """项目初始化引擎。"""

    def _run_git(self, project_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.setdefault("GIT_AUTHOR_NAME", "autodokit")
        env.setdefault("GIT_AUTHOR_EMAIL", "autodokit@example.com")
        env.setdefault("GIT_COMMITTER_NAME", "autodokit")
        env.setdefault("GIT_COMMITTER_EMAIL", "autodokit@example.com")
        return subprocess.run(
            ["git", *args],
            cwd=str(project_root),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def _create_initial_snapshot(self, project_root: Path) -> dict[str, Any]:
        add_result = self._run_git(project_root, ["add", "-A"])
        if add_result.returncode != 0:
            raise RuntimeError((add_result.stderr or add_result.stdout or "git add 失败").strip())

        status_result = self._run_git(project_root, ["status", "--porcelain"])
        changed_lines = [line for line in status_result.stdout.splitlines() if line.strip()]
        if not changed_lines:
            return {"status": "PASS", "created": False, "reason": "no_changes"}

        message = "AOK wf-a010-bootstrap A010 G010 task-a010-project-bootstrap PASS"
        commit_result = self._run_git(project_root, ["commit", "-m", message])
        if commit_result.returncode != 0:
            raise RuntimeError((commit_result.stderr or commit_result.stdout or "git commit 失败").strip())

        rev_result = self._run_git(project_root, ["rev-parse", "HEAD"])
        if rev_result.returncode != 0:
            raise RuntimeError((rev_result.stderr or rev_result.stdout or "git rev-parse 失败").strip())
        commit_hash = rev_result.stdout.strip()

        tag_result = self._run_git(project_root, ["tag", "-f", "aok/task/task-a010-project-bootstrap", commit_hash])
        if tag_result.returncode != 0:
            raise RuntimeError((tag_result.stderr or tag_result.stdout or "git tag 失败").strip())

        return {
            "status": "PASS",
            "created": True,
            "commit_hash": commit_hash,
            "tag_name": "aok/task/task-a010-project-bootstrap",
            "message": message,
        }

    def _bootstrap_minimal_task_db(self, project_root: Path) -> None:
        tasks_db_path = project_root / "database" / "tasks" / "tasks.db"
        tasks_db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(tasks_db_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_runs (
                    task_uid TEXT PRIMARY KEY,
                    workflow_uid TEXT NOT NULL,
                    node_code TEXT NOT NULL,
                    gate_code TEXT NOT NULL,
                    task_status TEXT NOT NULL DEFAULT '',
                    workspace_root TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT '',
                    ended_at TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT ''
                );
                """
            )
            connection.execute(
                """
                INSERT INTO task_runs (
                    task_uid, workflow_uid, node_code, gate_code, task_status,
                    workspace_root, started_at, ended_at, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_uid) DO UPDATE SET
                    workflow_uid=excluded.workflow_uid,
                    node_code=excluded.node_code,
                    gate_code=excluded.gate_code,
                    task_status=excluded.task_status,
                    workspace_root=excluded.workspace_root,
                    ended_at=excluded.ended_at,
                    note=excluded.note
                """,
                (
                    "task-a010-project-bootstrap",
                    "wf-a010-bootstrap",
                    "A010",
                    "G010",
                    "initialized",
                    str(project_root),
                    "",
                    "",
                    "project initialization task",
                ),
            )

    def _bootstrap_task_database(self, project_root: Path) -> None:
        tasks_root = project_root / "database" / "tasks"
        bootstrap_aok_taskdb(project_root=project_root)
        tasks_root.mkdir(parents=True, exist_ok=True)
        (tasks_root / "execution_runs.jsonl").touch(exist_ok=True)
        (tasks_root / "manifests.json").write_text(
            json.dumps(
                {
                    "schema_version": "0.4.0-sqlite-primary",
                    "generated_at": "",
                    "row_counts": {},
                    "hashes": {},
                    "snapshot_id": "",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self._touch_placeholder(tasks_root / "snapshots" / ".gitkeep")

    def _bootstrap_reference_database(self, project_root: Path) -> None:
        references_root = project_root / "database" / "references"
        references_root.mkdir(parents=True, exist_ok=True)
        content_db_path = project_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME
        init_references_db(content_db_path)

        (references_root / "references_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "0.4.0-sqlite-primary",
                    "generated_at": "",
                    "literature_count": 0,
                    "attachment_count": 0,
                    "primary_backend": "sqlite",
                    "primary_db_path": str(content_db_path),
                    "vector_index_ready": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (references_root / "retrieval_bundles.jsonl").touch(exist_ok=True)
        self._touch_placeholder(references_root / "attachments" / ".gitkeep")
        self._touch_placeholder(references_root / "unit_db" / ".gitkeep")
        self._touch_placeholder(references_root / "vector_index" / ".gitkeep")

        workspace_references_root = project_root / "references"
        workspace_references_root.mkdir(parents=True, exist_ok=True)
        for structured_dir in build_pdf_structured_variant_dir_map(workspace_references_root).values():
            self._touch_placeholder(structured_dir / ".gitkeep")

    def _bootstrap_knowledge_database(self, project_root: Path) -> None:
        knowledge_root = project_root / "database" / "knowledge"
        knowledge_root.mkdir(parents=True, exist_ok=True)
        content_db_path = project_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME
        init_knowledge_db(content_db_path)

        (knowledge_root / "knowledge_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "0.4.0-sqlite-primary",
                    "generated_at": "",
                    "knowledge_count": 0,
                    "attachment_count": 0,
                    "primary_backend": "sqlite",
                    "primary_db_path": str(content_db_path),
                    "vector_index_ready": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self._touch_placeholder(knowledge_root / "notes" / ".gitkeep")
        self._touch_placeholder(knowledge_root / "attachments" / ".gitkeep")
        self._touch_placeholder(project_root / "knowledge" / "views" / ".gitkeep")
        self._touch_placeholder(knowledge_root / "vector_index" / ".gitkeep")

    def _bootstrap_scheduler_config(self, project_root: Path) -> None:
        scheduler_root = project_root / "config" / "scheduler"
        scheduler_root.mkdir(parents=True, exist_ok=True)
        (scheduler_root / "edge_weights.json").write_text(
            json.dumps(
                {
                    "base": 1.0,
                    "goal_gain": 1.0,
                    "risk_penalty": 1.0,
                    "cost_penalty": 1.0,
                    "time_penalty": 1.0,
                    "audit_bonus": 1.0,
                    "dynamic_delta": 1.0,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (scheduler_root / "selection_policy.json").write_text(
            json.dumps(
                {
                    "strategy": "argmax",
                    "temperature": 1.0,
                    "seed": 20260306,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (scheduler_root / "guard_policy.json").write_text(
            json.dumps(
                {
                    "max_retry": 2,
                    "retryable_result_codes": ["RETRY"],
                    "blocking_audit_results": ["FAIL", "BLOCKED"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (scheduler_root / "dispatch_map.json").write_text(
            json.dumps(
                {
                    "literature_search": {"kind": "placeholder", "target": "literature_search"},
                    "dataset_search": {"kind": "placeholder", "target": "dataset_search"},
                    "knowledge_extract": {"kind": "placeholder", "target": "knowledge_extract"},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _touch_placeholder(self, file_path: Path) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch(exist_ok=True)

    def _bootstrap_task_instance_dir(self, project_root: Path) -> Path:
        tasks_root = project_root / "tasks"
        task_instance_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-A010"
        task_instance_dir = tasks_root / task_instance_name
        task_instance_dir.mkdir(parents=True, exist_ok=False)
        manifest_path = task_instance_dir / "task_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "task_uid": task_instance_name,
                    "node_code": "A010",
                    "workspace_root": str(project_root),
                    "task_instance_dir": str(task_instance_dir),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "purpose": "A010 项目初始化任务实例目录",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return task_instance_dir

    def run(self, project_root: str | Path = ".") -> dict[str, Any]:
        root = Path(project_root).resolve()
        task_instance_dir = self._bootstrap_task_instance_dir(root)
        git_init_result = git_workspace_init(root)
        self._bootstrap_task_database(root)
        self._bootstrap_minimal_task_db(root)
        self._bootstrap_reference_database(root)
        self._bootstrap_knowledge_database(root)

        aok_logdb_result = bootstrap_aok_logdb(project_root=root)
        if aok_logdb_result.get("status") != "PASS":
            raise RuntimeError(f"AOK 日志库初始化失败: {aok_logdb_result}")

        self._bootstrap_scheduler_config(root)
        snapshot_result = self._create_initial_snapshot(root)
        return {
            "project_root": str(root),
            "status": "PASS",
            "task_instance_dir": str(task_instance_dir),
            "git_init_result": git_init_result,
            "aok_logdb_result": aok_logdb_result,
            "snapshot_result": snapshot_result,
            "created_paths": [
                str(root / "tasks"),
                str(task_instance_dir),
                str(task_instance_dir / "task_manifest.json"),
                str(root / "database" / "tasks"),
                str(root / "database" / "tasks" / "tasks.db"),
                str(root / "database" / "content"),
                str(root / "database" / "references"),
                str(root / "database" / "knowledge"),
                str(root / "database" / "logs"),
                str(root / "database" / "logs" / "aok_log.db"),
                str(root / "references"),
                *[str(path) for path in build_pdf_structured_variant_dir_map(root / "references").values()],
                str(root / "config" / "scheduler"),
            ],
        }


@affair_auto_git_commit("A010")
def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = ProjectInitializationEngine().run(project_root=str(raw_cfg.get("project_root") or "."))

    output_dir = resolve_legacy_output_dir(raw_cfg, config_path)

    task_instance_dir = Path(str(result.get("task_instance_dir") or (output_dir / "task_instance")))
    task_instance_dir.mkdir(parents=True, exist_ok=True)
    task_out_path = task_instance_dir / "project_initialization_result.json"
    task_out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    out_path = output_dir / "project_initialization_result.json"
    if out_path != task_out_path:
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return [task_out_path, out_path]
    return [task_out_path]
