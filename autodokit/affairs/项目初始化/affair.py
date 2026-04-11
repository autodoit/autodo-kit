"""项目初始化事务。"""

from __future__ import annotations

from datetime import datetime
import json
import os
import sqlite3
import shutil
import subprocess
from pathlib import Path
from typing import Any, List, Mapping

from autodokit.tools import (
    bootstrap_aok_logdb,
    bootstrap_aok_taskdb,
    load_json_or_py,
    write_mainline_affair_entry_registry,
)
from autodokit.tools.atomic.task_aok.git_snapshot_ledger import git_workspace_init
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.atomic.task_aok.task_instance_dir import resolve_legacy_output_dir
from autodokit.tools.bibliodb_sqlite import init_db as init_references_db
from autodokit.tools.bibliodb_sqlite import upsert_workspace_node_state_rows
from autodokit.tools.contentdb_sqlite import (
    CONTENT_DB_DIRECTORY_NAME,
    DEFAULT_CONTENT_DB_NAME,
    build_pdf_structured_variant_dir_map,
)
from autodokit.tools.knowledgedb_sqlite import init_db as init_knowledge_db


class ProjectInitializationEngine:
    """项目初始化引擎。"""

    _SKIPPED_TEMPLATE_FILE_NAMES = {".sync.ffs_db"}
    _DEFAULT_NODE_CODES = [
        "A010",
        "A020",
        "A030",
        "A040",
        "A050",
        "A060",
        "A065",
        "A070",
        "A080",
        "A090",
        "A095",
        "A100",
        "A105",
        "A110",
        "A120",
        "A130",
        "A140",
        "A150",
        "A160",
    ]

    def _resolve_workspace_root(self, raw_cfg: Mapping[str, Any], config_path: Path) -> Path:
        raw_workspace_root = raw_cfg.get("workspace_root") or raw_cfg.get("project_root")
        if raw_workspace_root:
            return Path(str(raw_workspace_root)).expanduser().resolve()
        candidate = config_path.resolve()
        if candidate.parent.name == "affairs_config" and candidate.parent.parent.name == "config":
            return candidate.parent.parent.parent.resolve()
        if candidate.parent.name == "config":
            return candidate.parent.parent.resolve()
        return Path.cwd().resolve()

    def _resolve_root_path(
        self,
        workspace_root: Path,
        raw_cfg: Mapping[str, Any],
        global_cfg: Mapping[str, Any],
    ) -> Path:
        raw_root_path = raw_cfg.get("root_path") or global_cfg.get("root_path")
        if raw_root_path:
            return Path(str(raw_root_path)).expanduser().resolve()
        return workspace_root.parent.resolve()

    def _load_global_config(self, workspace_root: Path) -> dict[str, Any]:
        config_path = workspace_root / "config" / "config.json"
        if not config_path.exists():
            return {}
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _render_template_text(self, text: str, replacements: Mapping[str, str]) -> str:
        rendered = text
        for placeholder, value in replacements.items():
            rendered = rendered.replace(placeholder, value)
        return rendered

    def _merge_template_value(self, existing: Any, template: Any) -> Any:
        if isinstance(existing, dict) and isinstance(template, dict):
            merged = dict(existing)
            for key, template_value in template.items():
                if key in merged:
                    merged[key] = self._merge_template_value(merged[key], template_value)
                else:
                    merged[key] = template_value
            return merged
        if isinstance(existing, list) and isinstance(template, list):
            merged = list(existing)
            for item in template:
                if item not in merged:
                    merged.append(item)
            return merged
        if existing in (None, "", [], {}):
            return template
        return existing

    def _sync_json_template_file(self, template_path: Path, target_path: Path, replacements: Mapping[str, str]) -> bool:
        rendered_text = self._render_template_text(template_path.read_text(encoding="utf-8"), replacements)
        template_payload = json.loads(rendered_text)
        if target_path.exists():
            try:
                existing_payload = json.loads(target_path.read_text(encoding="utf-8-sig"))
            except Exception:
                existing_payload = None
            if existing_payload is not None:
                merged_payload = self._merge_template_value(existing_payload, template_payload)
                if merged_payload == existing_payload:
                    return False
                target_path.write_text(json.dumps(merged_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                return True

        target_path.write_text(json.dumps(template_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def _copy_template_file(self, template_path: Path, target_path: Path) -> bool:
        if target_path.exists():
            return False
        shutil.copy2(template_path, target_path)
        return True

    def _sync_gitignore(self, template_path: Path, target_path: Path, replacements: Mapping[str, str]) -> bool:
        rendered_text = self._render_template_text(template_path.read_text(encoding="utf-8"), replacements)
        template_lines = [line.strip() for line in rendered_text.splitlines() if line.strip()]
        existing_lines: list[str] = []
        if target_path.exists():
            existing_lines = target_path.read_text(encoding="utf-8").splitlines()
        normalized_existing = {line.strip(): line for line in existing_lines if line.strip()}
        changed = False
        merged_lines = list(existing_lines)
        for line in template_lines:
            if line not in normalized_existing:
                merged_lines.append(line)
                changed = True
        if changed or not target_path.exists():
            target_path.write_text("\n".join(merged_lines).rstrip() + "\n", encoding="utf-8")
        return changed or not existing_lines

    def _sync_template_tree(
        self,
        workspace_root: Path,
        *,
        template_root: Path | None,
        replacements: Mapping[str, str],
    ) -> dict[str, Any]:
        if template_root is None or not template_root.exists() or not template_root.is_dir():
            return {"status": "SKIPPED", "reason": "template_root_missing", "created_files": [], "updated_files": []}

        created_files: list[str] = []
        updated_files: list[str] = []
        for template_path in sorted(template_root.rglob("*")):
            if template_path.name in self._SKIPPED_TEMPLATE_FILE_NAMES:
                continue
            relative_path = template_path.relative_to(template_root)
            target_path = workspace_root / relative_path
            if template_path.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            existed_before = target_path.exists()
            if template_path.suffix.lower() == ".json":
                changed = self._sync_json_template_file(template_path, target_path, replacements)
            elif template_path.name == ".gitignore":
                changed = self._sync_gitignore(template_path, target_path, replacements)
            else:
                changed = self._copy_template_file(template_path, target_path)

            if not changed:
                continue
            if existed_before:
                updated_files.append(str(target_path))
            else:
                created_files.append(str(target_path))

        return {
            "status": "PASS",
            "template_root": str(template_root),
            "created_files": created_files,
            "updated_files": updated_files,
        }

    def _build_template_replacements(
        self,
        *,
        workspace_root: Path,
        root_path: Path,
        template_root: Path | None,
        raw_cfg: Mapping[str, Any],
        global_cfg: Mapping[str, Any],
    ) -> dict[str, str]:
        project_payload = global_cfg.get("project") if isinstance(global_cfg.get("project"), dict) else {}
        llm_payload = global_cfg.get("llm") if isinstance(global_cfg.get("llm"), dict) else {}
        return {
            "__ROOT_PATH__": str(root_path),
            "__WORKSPACE_ROOT__": str(workspace_root),
            "__VENV_PATH__": str((root_path / ".venv").resolve()),
            "__PROJECT_NAME__": str(project_payload.get("project_name") or raw_cfg.get("project_name") or ""),
            "__PROJECT_GOAL__": str(project_payload.get("project_goal") or raw_cfg.get("project_goal") or ""),
            "__TEMPLATE_ROOT__": str(template_root.resolve()) if template_root is not None else "",
            "__ALIYUN_API_KEY_FILE__": str(llm_payload.get("aliyun_api_key_file") or raw_cfg.get("aliyun_api_key_file") or ""),
            "__GENERATED_AT__": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    def _default_required_dirs(self, workspace_root: Path) -> list[Path]:
        relative_dirs = [
            "config",
            "config/scheduler",
            "database/content",
            "database/literature",
            "database/knowledge",
            "database/logs",
            "database/tasks",
            "references",
            "references/attachments",
            "references/bib",
            "references/structured_monkeyocr_full",
            "steps",
            "views",
            "tasks",
            "batches",
            "docs",
            "runtime",
            "sandbox",
            "scripts",
            "knowledge/standard_notes",
            "knowledge/matrices",
            "knowledge/trajectories",
            "knowledge/frameworks",
            "knowledge/innovation_pool",
            "knowledge/proposal",
            "knowledge/audits",
            "logs",
        ]
        return [(workspace_root / relative_dir).resolve() for relative_dir in relative_dirs]

    def _ensure_required_dirs(
        self,
        workspace_root: Path,
        raw_cfg: Mapping[str, Any],
        global_cfg: Mapping[str, Any],
    ) -> list[str]:
        required_dirs: list[Path] = []
        for source in [raw_cfg.get("required_dirs"), (global_cfg.get("bootstrap") or {}).get("required_dirs") if isinstance(global_cfg.get("bootstrap"), dict) else None]:
            if isinstance(source, list):
                for item in source:
                    required_dirs.append(Path(str(item)).expanduser().resolve())
        if not required_dirs:
            required_dirs = self._default_required_dirs(workspace_root)

        created_paths: list[str] = []
        for directory in required_dirs:
            directory.mkdir(parents=True, exist_ok=True)
            created_paths.append(str(directory))
        return created_paths

    def _write_self_check_report(
        self,
        workspace_root: Path,
        raw_cfg: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> str:
        output_path = raw_cfg.get("self_check_output_path")
        if not output_path:
            output_path = workspace_root / "steps" / "A010_project_bootstrap" / "self_check.json"
        target_path = Path(str(output_path)).expanduser().resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": "PASS",
            "workspace_root": str(workspace_root),
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "required_dirs": result.get("required_dirs_created", []),
            "tasks_db_path": str(workspace_root / "database" / "tasks" / "tasks.db"),
            "log_db_path": str(workspace_root / "database" / "logs" / "aok_log.db"),
            "registry_path": result.get("affair_entry_registry_path", ""),
        }
        target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(target_path)

    def _resolve_node_inputs(self, workspace_root: Path, global_cfg: Mapping[str, Any]) -> dict[str, str]:
        node_inputs = global_cfg.get("node_inputs") if isinstance(global_cfg.get("node_inputs"), dict) else {}
        resolved: dict[str, str] = {}
        for node_code in self._DEFAULT_NODE_CODES:
            if node_code in node_inputs:
                resolved[node_code] = str(Path(str(node_inputs[node_code])).expanduser().resolve())
            else:
                resolved[node_code] = str((workspace_root / "config" / "affairs_config" / f"{node_code}.json").resolve())
        return resolved

    def _sync_affair_entry_registry(self, workspace_root: Path, global_cfg: Mapping[str, Any]) -> str:
        paths_cfg = global_cfg.get("paths") if isinstance(global_cfg.get("paths"), dict) else {}
        registry_path = paths_cfg.get("affair_entry_registry_path") or (workspace_root / "config" / "affair_entry_registry.json")
        resolved_registry_path = Path(str(registry_path)).expanduser().resolve()
        write_mainline_affair_entry_registry(
            resolved_registry_path,
            workspace_root=workspace_root,
            node_inputs=self._resolve_node_inputs(workspace_root, global_cfg),
        )
        return str(resolved_registry_path)

    def _run_git(self, project_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        global_cfg = self._load_global_config(project_root)
        project_cfg = global_cfg.get("project") if isinstance(global_cfg.get("project"), dict) else {}
        git_cfg = global_cfg.get("git") if isinstance(global_cfg.get("git"), dict) else {}
        project_name = str(project_cfg.get("project_name") or "").strip() or "project"
        author_name = str(git_cfg.get("author_name") or project_name).strip() or project_name
        author_email = str(git_cfg.get("author_email") or f"{author_name}@localhost").strip() or f"{author_name}@localhost"
        committer_name = str(git_cfg.get("committer_name") or author_name).strip() or author_name
        committer_email = str(git_cfg.get("committer_email") or author_email).strip() or author_email
        env.setdefault("GIT_AUTHOR_NAME", author_name)
        env.setdefault("GIT_AUTHOR_EMAIL", author_email)
        env.setdefault("GIT_COMMITTER_NAME", committer_name)
        env.setdefault("GIT_COMMITTER_EMAIL", committer_email)
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

    def _write_json_if_missing(self, file_path: Path, payload: Mapping[str, Any]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists():
            return
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _bootstrap_scheduler_config(self, project_root: Path) -> None:
        scheduler_root = project_root / "config" / "scheduler"
        scheduler_root.mkdir(parents=True, exist_ok=True)
        self._write_json_if_missing(
            scheduler_root / "edge_weights.json",
            {
                "base": 1.0,
                "goal_gain": 1.0,
                "risk_penalty": 1.0,
                "cost_penalty": 1.0,
                "time_penalty": 1.0,
                "audit_bonus": 1.0,
                "dynamic_delta": 1.0,
            },
        )
        self._write_json_if_missing(
            scheduler_root / "selection_policy.json",
            {
                "strategy": "argmax",
                "temperature": 1.0,
                "seed": 20260306,
            },
        )
        self._write_json_if_missing(
            scheduler_root / "guard_policy.json",
            {
                "max_retry": 2,
                "retryable_result_codes": ["RETRY"],
                "blocking_audit_results": ["FAIL", "BLOCKED"],
            },
        )
        self._write_json_if_missing(
            scheduler_root / "dispatch_map.json",
            {
                "literature_search": {"kind": "placeholder", "target": "literature_search"},
                "dataset_search": {"kind": "placeholder", "target": "dataset_search"},
                "knowledge_extract": {"kind": "placeholder", "target": "knowledge_extract"},
            },
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

    def run(self, config_path: Path, raw_cfg: Mapping[str, Any]) -> dict[str, Any]:
        root = self._resolve_workspace_root(raw_cfg, config_path)
        global_cfg_before = self._load_global_config(root)
        bootstrap_cfg_before = global_cfg_before.get("bootstrap") if isinstance(global_cfg_before.get("bootstrap"), dict) else {}
        template_root_value = raw_cfg.get("template_root") or bootstrap_cfg_before.get("template_root")
        template_root = Path(str(template_root_value)).expanduser().resolve() if template_root_value else None
        root_path = self._resolve_root_path(root, raw_cfg, global_cfg_before)
        replacements = self._build_template_replacements(
            workspace_root=root,
            root_path=root_path,
            template_root=template_root,
            raw_cfg=raw_cfg,
            global_cfg=global_cfg_before,
        )
        template_sync_result = self._sync_template_tree(root, template_root=template_root, replacements=replacements)
        global_cfg = self._load_global_config(root)
        required_dirs_created = self._ensure_required_dirs(root, raw_cfg, global_cfg)
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
        affair_entry_registry_path = self._sync_affair_entry_registry(root, global_cfg)
        snapshot_result = self._create_initial_snapshot(root)
        result = {
            "project_root": str(root),
            "status": "PASS",
            "task_instance_dir": str(task_instance_dir),
            "git_init_result": git_init_result,
            "aok_logdb_result": aok_logdb_result,
            "snapshot_result": snapshot_result,
            "template_sync_result": template_sync_result,
            "required_dirs_created": required_dirs_created,
            "affair_entry_registry_path": affair_entry_registry_path,
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
        result["self_check_output_path"] = self._write_self_check_report(root, raw_cfg, result)
        return result


@affair_auto_git_commit("A010")
def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    if not isinstance(raw_cfg, dict):
        raise ValueError("A010 配置必须为字典")
    result = ProjectInitializationEngine().run(config_path=config_path, raw_cfg=raw_cfg)

    try:
        workspace_root = Path(str(result.get("workspace_root") or "")).resolve()
        content_db = workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME
        upsert_workspace_node_state_rows(
            content_db,
            [
                {
                    "node_code": "A010",
                    "node_name": "项目初始化",
                    "pending_run": 0,
                    "in_progress": 0,
                    "completed": 1,
                    "gate_status": "pass_next",
                    "last_task_uid": str(result.get("task_instance_name") or ""),
                    "current_task_uid": "",
                    "summary": "A010 初始化完成",
                    "next_node_code": "A020",
                    "failure_reason": "",
                    "retry_count": 0,
                }
            ],
        )
    except Exception:
        # 节点状态写入失败不阻断初始化主流程。
        pass

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
