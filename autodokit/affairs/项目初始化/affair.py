"""项目初始化事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from autodokit.taskdb.csv_store import CsvStore, JsonArtifactStore
from autodokit.taskdb.schema_registry import SchemaRegistry
from autodokit.tools import load_json_or_py


class ProjectInitializationEngine:
    """项目初始化引擎。"""

    def run(self, project_root: str | Path = ".") -> dict[str, Any]:
        """初始化研究项目骨架。

        Args:
            project_root: 项目根目录。

        Returns:
            初始化结果摘要。
        """

        root = Path(project_root).resolve()
        schema_registry = SchemaRegistry.default()
        self._bootstrap_task_database(root, schema_registry)
        self._bootstrap_reference_database(root)
        self._bootstrap_knowledge_database(root)
        self._bootstrap_scheduler_config(root)
        return {
            "project_root": str(root),
            "status": "PASS",
            "created_paths": [
                str(root / "database" / "tasks"),
                str(root / "database" / "references"),
                str(root / "database" / "knowledge"),
                str(root / "config" / "scheduler"),
            ],
        }

    def _bootstrap_task_database(self, project_root: Path, schema_registry: SchemaRegistry) -> None:
        """初始化任务数据库模板。

        Args:
            project_root: 项目根目录。
            schema_registry: Schema 注册表。
        """

        tasks_root = project_root / "database" / "tasks"
        for table_name in schema_registry.tables:
            schema = schema_registry.get(table_name)
            CsvStore(file_path=tasks_root / f"{table_name}.csv", schema=schema).ensure_exists()

        JsonArtifactStore(tasks_root / "execution_runs.jsonl").file_path.touch(exist_ok=True)
        JsonArtifactStore(tasks_root / "manifests.json").write_json(
            {
                "schema_version": schema_registry.version,
                "generated_at": "",
                "row_counts": {},
                "hashes": {},
                "snapshot_id": "",
            }
        )
        self._touch_placeholder(tasks_root / "snapshots" / ".gitkeep")

    def _bootstrap_reference_database(self, project_root: Path) -> None:
        """初始化文献数据库模板。

        Args:
            project_root: 项目根目录。
        """

        references_root = project_root / "database" / "references"
        self._write_text_if_missing(
            references_root / "literature_items.csv",
            "item_uid,title,authors,year,source_type,origin_path,status,created_at,updated_at\n",
        )
        self._write_text_if_missing(
            references_root / "literature_files.csv",
            "file_uid,item_uid,file_path,file_type,checksum,created_at\n",
        )
        JsonArtifactStore(references_root / "literature_manifest.json").write_json(
            {
                "schema_version": "0.1.0",
                "generated_at": "",
                "item_count": 0,
                "vector_index_ready": False,
            }
        )
        JsonArtifactStore(references_root / "retrieval_bundles.jsonl").file_path.touch(exist_ok=True)
        self._touch_placeholder(references_root / "unit_db" / ".gitkeep")
        self._touch_placeholder(references_root / "vector_index" / ".gitkeep")

    def _bootstrap_knowledge_database(self, project_root: Path) -> None:
        """初始化知识数据库模板。

        Args:
            project_root: 项目根目录。
        """

        knowledge_root = project_root / "database" / "knowledge"
        self._write_text_if_missing(
            knowledge_root / "knowledge_notes.csv",
            "note_uid,title,task_uid,note_type,source_bundle_id,status,created_at,updated_at\n",
        )
        self._write_text_if_missing(
            knowledge_root / "knowledge_links.csv",
            "link_uid,from_note_uid,to_note_uid,relation_type,created_at\n",
        )
        self._write_text_if_missing(
            knowledge_root / "knowledge_evidence_map.csv",
            "map_uid,note_uid,evidence_uid,evidence_type,created_at\n",
        )
        JsonArtifactStore(knowledge_root / "knowledge_manifest.json").write_json(
            {
                "schema_version": "0.1.0",
                "generated_at": "",
                "note_count": 0,
                "vector_index_ready": False,
            }
        )
        self._touch_placeholder(knowledge_root / "notes" / ".gitkeep")
        self._touch_placeholder(knowledge_root / "vector_index" / ".gitkeep")

    def _bootstrap_scheduler_config(self, project_root: Path) -> None:
        """初始化调度配置模板。

        Args:
            project_root: 项目根目录。
        """

        scheduler_root = project_root / "config" / "scheduler"
        JsonArtifactStore(scheduler_root / "edge_weights.json").write_json(
            {
                "base": 1.0,
                "goal_gain": 1.0,
                "risk_penalty": 1.0,
                "cost_penalty": 1.0,
                "time_penalty": 1.0,
                "audit_bonus": 1.0,
                "dynamic_delta": 1.0,
            }
        )
        JsonArtifactStore(scheduler_root / "selection_policy.json").write_json(
            {
                "strategy": "argmax",
                "temperature": 1.0,
                "seed": 20260306,
            }
        )
        JsonArtifactStore(scheduler_root / "guard_policy.json").write_json(
            {
                "max_retry": 2,
                "retryable_result_codes": ["RETRY"],
                "blocking_audit_results": ["FAIL", "BLOCKED"],
            }
        )
        JsonArtifactStore(scheduler_root / "dispatch_map.json").write_json(
            {
                "literature_search": {
                    "kind": "placeholder",
                    "target": "literature_search",
                },
                "dataset_search": {
                    "kind": "placeholder",
                    "target": "dataset_search",
                },
                "knowledge_extract": {
                    "kind": "placeholder",
                    "target": "knowledge_extract",
                },
            }
        )

    def _write_text_if_missing(self, file_path: Path, content: str) -> None:
        """仅在文件缺失时写入模板内容。

        Args:
            file_path: 目标文件。
            content: 模板内容。
        """

        file_path.parent.mkdir(parents=True, exist_ok=True)
        if not file_path.exists():
            file_path.write_text(content, encoding="utf-8")

    def _touch_placeholder(self, file_path: Path) -> None:
        """写入占位文件。

        Args:
            file_path: 占位文件路径。
        """

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch(exist_ok=True)


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置路径。

    Returns:
        输出文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    result = ProjectInitializationEngine().run(project_root=str(raw_cfg.get("project_root") or "."))

    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={str(raw_cfg.get('output_dir') or '')!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / "project_initialization_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]