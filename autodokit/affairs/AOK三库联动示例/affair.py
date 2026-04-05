"""AOK 三库联动示例事务。

该事务用于演示最近落地的三库协同最小闭环：
1. 文献库：从 BibTeX 导入条目并登记附件；
2. 知识库：生成文献标准笔记并同步索引；
3. 任务库：创建 AOK 任务并绑定文献/知识 UID，再登记产物。

特别说明：
- 输入的 RDF 数据目录是 Zotero 嵌套结构，事务会手动把 `files/` 下附件提取并复制到
  示例工作区 `references/attachments/` 目录，不依赖扁平目录结构。
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any, Dict, List, Tuple

import bibtexparser
import pandas as pd

from autodokit.tools import (
    bootstrap_aok_taskdb,
    knowledge_bind_literature_standard_note,
    knowledge_index_sync_from_note,
    knowledge_note_register,
    literature_attach_file,
    literature_bind_standard_note,
    literature_upsert,
    load_json_or_py,
    task_artifact_register,
    task_bind_knowledges,
    task_bind_literatures,
    task_bundle_export,
    task_create_or_update,
    write_affair_json_result,
)
from autodokit.tools.bibliodb import init_empty_attachments_table, init_empty_literatures_table
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME
from autodokit.tools.knowledgedb import init_empty_knowledge_attachments_table, init_empty_knowledge_index_table
from autodokit.tools.storage_backend import (
    load_knowledge_tables,
    load_reference_tables,
    persist_knowledge_tables,
    persist_reference_tables,
)
from autodokit.tools.atomic.task_aok.taskdb import init_empty_task_artifacts_table, init_empty_tasks_table


def _ensure_table(csv_path: Path, init_fn: Any) -> pd.DataFrame:
    """读取已有 CSV 或创建空表。

    Args:
        csv_path: CSV 文件路径。
        init_fn: 空表初始化函数。

    Returns:
        DataFrame 表对象。
    """

    if csv_path.exists():
        return pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    return init_fn()


def _save_table(csv_path: Path, table: pd.DataFrame) -> None:
    """保存 DataFrame 到 CSV。

    Args:
        csv_path: CSV 文件路径。
        table: 待保存数据表。
    """

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(csv_path, index=False, encoding="utf-8")


def _collect_rdf_attachments(rdf_files_root: Path) -> List[Path]:
    """从 Zotero RDF `files/` 根目录递归收集附件文件。

    Args:
        rdf_files_root: RDF 附件根目录，一般是 `.../测试用文献/files`。

    Returns:
        附件文件路径列表。
    """

    if not rdf_files_root.exists():
        return []

    supported_suffixes = {".pdf", ".md", ".html", ".htm", ".txt", ".doc", ".docx", ".caj"}
    collected: List[Path] = []
    for file_path in rdf_files_root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in supported_suffixes:
            continue
        collected.append(file_path)
    return collected


def _copy_attachments_to_workspace(source_files: List[Path], target_dir: Path) -> List[Path]:
    """手动复制附件到示例工作区文献附件目录。

    Args:
        source_files: 源附件路径列表。
        target_dir: 目标目录。

    Returns:
        复制后的目标文件路径列表。
    """

    target_dir.mkdir(parents=True, exist_ok=True)
    copied: List[Path] = []
    used_names: set[str] = set(path.name for path in target_dir.glob("*") if path.is_file())

    for source in source_files:
        base_name = source.name
        if base_name not in used_names:
            target = target_dir / base_name
        else:
            stem = source.stem
            suffix = source.suffix
            idx = 1
            while True:
                candidate_name = f"{stem}_{idx}{suffix}"
                if candidate_name not in used_names:
                    target = target_dir / candidate_name
                    break
                idx += 1

        shutil.copy2(source, target)
        used_names.add(target.name)
        copied.append(target)

    return copied


def _load_bib_entries(bib_path: Path, max_records: int) -> List[Dict[str, Any]]:
    """从 BibTeX 文件读取条目。

    Args:
        bib_path: BibTeX 路径。
        max_records: 最大读取条目数。

    Returns:
        Bib 条目字典列表。
    """

    if not bib_path.exists():
        return []
    with bib_path.open("r", encoding="utf-8") as handle:
        bib_db = bibtexparser.load(handle)
    return list(bib_db.entries)[:max_records]


def run_demo(
    *,
    project_root: Path,
    bib_path: Path,
    rdf_files_root: Path,
    output_dir: Path,
    max_bib_records: int = 3,
    max_attachments: int = 6,
) -> Dict[str, Any]:
    """执行三库联动示例。

    Args:
        project_root: 示例工作区根目录。
        bib_path: BibTeX 测试数据路径。
        rdf_files_root: Zotero RDF 附件根目录（`files/`）。
        output_dir: 输出目录。
        max_bib_records: 最多导入 Bib 条目数。
        max_attachments: 最多复制并登记附件数。

    Returns:
        结果摘要字典。

    Raises:
        ValueError: 输入参数非法时抛出异常。
    """

    if not project_root.is_absolute():
        raise ValueError(f"project_root 必须是绝对路径: {project_root}")
    if not output_dir.is_absolute():
        raise ValueError(f"output_dir 必须是绝对路径: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) 初始化任务库（AOK 隔离版）。
    task_bootstrap = bootstrap_aok_taskdb(project_root=project_root)

    # 2) 准备三库目录。
    content_db_root = project_root / "database" / CONTENT_DB_DIRECTORY_NAME
    knowledge_notes_root = project_root / "knowledge" / "notes"
    knowledge_attachments_root = project_root / "knowledge" / "attachments"
    knowledge_views_root = project_root / "knowledge" / "views"
    literature_attachments_root = project_root / "references" / "attachments"

    content_db_root.mkdir(parents=True, exist_ok=True)
    knowledge_notes_root.mkdir(parents=True, exist_ok=True)
    knowledge_attachments_root.mkdir(parents=True, exist_ok=True)
    knowledge_views_root.mkdir(parents=True, exist_ok=True)
    literature_attachments_root.mkdir(parents=True, exist_ok=True)

    content_db = project_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME
    tasks_csv = project_root / "database" / "tasks" / "tasks.csv"
    task_artifacts_csv = project_root / "database" / "tasks" / "task_artifacts.csv"

    literatures, literature_attachments, _ = load_reference_tables(db_path=content_db)
    knowledge_index, knowledge_attachments, _ = load_knowledge_tables(db_path=content_db)
    if literatures.empty:
        literatures = init_empty_literatures_table()
    if literature_attachments.empty:
        literature_attachments = init_empty_attachments_table()
    if knowledge_index.empty:
        knowledge_index = init_empty_knowledge_index_table()
    if knowledge_attachments.empty:
        knowledge_attachments = init_empty_knowledge_attachments_table()
    tasks = _ensure_table(tasks_csv, init_empty_tasks_table)
    task_artifacts = _ensure_table(task_artifacts_csv, init_empty_task_artifacts_table)

    # 3) 导入文献主表。
    imported_entries = _load_bib_entries(bib_path=bib_path, max_records=max_bib_records)
    imported_literature_uids: List[str] = []
    for entry in imported_entries:
        title = str(entry.get("title") or "").strip()
        if not title:
            continue
        authors = str(entry.get("author") or "").strip()
        first_author = authors.split(" and ")[0].strip() if authors else ""
        year = str(entry.get("year") or "").strip()
        entry_type = str(entry.get("ENTRYTYPE") or "article").strip() or "article"

        literatures, row, _ = literature_upsert(
            literatures,
            {
                "title": title,
                "first_author": first_author,
                "authors": authors,
                "year": year,
                "entry_type": entry_type,
                "source_type": "demo_bib_import",
                "origin_path": str(bib_path),
                "is_placeholder": 0,
            },
            overwrite=True,
        )
        imported_literature_uids.append(str(row.get("uid_literature") or ""))

    imported_literature_uids = [uid for uid in imported_literature_uids if uid]

    # 4) 手动提取并复制 RDF 嵌套目录附件。
    rdf_attachments = _collect_rdf_attachments(rdf_files_root)
    copied_attachments = _copy_attachments_to_workspace(
        source_files=rdf_attachments[:max_attachments],
        target_dir=literature_attachments_root,
    )

    # 5) 把附件登记到文献库（循环绑定到已导入文献）。
    if imported_literature_uids:
        for index, attachment_path in enumerate(copied_attachments):
            uid = imported_literature_uids[index % len(imported_literature_uids)]
            is_primary = 1 if attachment_path.suffix.lower() == ".pdf" else 0
            attachment_type = "fulltext" if is_primary else (attachment_path.suffix.lower().lstrip(".") or "other")
            literatures, literature_attachments, _ = literature_attach_file(
                literatures,
                literature_attachments,
                uid_literature=uid,
                attachment_name=str(attachment_path),
                attachment_type=attachment_type,
                is_primary=is_primary,
                note="demo_manual_extract_from_rdf",
            )

    # 6) 基于文献生成知识标准笔记并同步知识索引。
    generated_knowledge_uids: List[str] = []
    generated_note_paths: List[Path] = []
    for uid in imported_literature_uids[: min(2, len(imported_literature_uids))]:
        current = literatures[literatures["uid_literature"].astype(str) == uid]
        if current.empty:
            continue
        row = dict(current.iloc[0])
        cite_key = str(row.get("cite_key") or uid)
        note_path = (knowledge_notes_root / f"{cite_key}.md").resolve()

        created = knowledge_note_register(
            note_path=note_path,
            title=f"文献标准笔记-{cite_key}",
            note_type="literature_standard_note",
            status="draft",
            evidence_uids=[uid],
            tags=["aok/knowledge", "aok/demo"],
            uid_literature=uid,
            cite_key=cite_key,
        )

        knowledge_bind_literature_standard_note(
            note_path=note_path,
            uid_literature=uid,
            cite_key=cite_key,
        )
        knowledge_index, synced_row = knowledge_index_sync_from_note(
            knowledge_index,
            note_path,
            workspace_root=project_root,
        )
        knowledge_uid = str(synced_row.get("uid_knowledge") or created.get("uid_knowledge") or "")
        if knowledge_uid:
            generated_knowledge_uids.append(knowledge_uid)
            literatures, _ = literature_bind_standard_note(
                literatures,
                uid_literature=uid,
                standard_note_uid=knowledge_uid,
            )
        generated_note_paths.append(note_path)

    # 7) 创建任务并绑定文献、知识。
    tasks, task_row, _ = task_create_or_update(
        tasks,
        {
            "task_name": "AOK三库联动示例任务",
            "task_goal": "演示文献-知识-任务最小闭环",
            "task_status": "running",
        },
        workspace_root=project_root,
        overwrite=True,
        ensure_workspace_dir=True,
    )
    task_uid = str(task_row.get("aok_task_uid") or "")

    tasks, _, invalid_lits = task_bind_literatures(
        tasks,
        aok_task_uid=task_uid,
        literature_uids=imported_literature_uids,
    )
    tasks, _, invalid_kns = task_bind_knowledges(
        tasks,
        aok_task_uid=task_uid,
        knowledge_uids=generated_knowledge_uids,
    )

    # 8) 登记任务产物。
    artifact_paths = [
        content_db,
        content_db,
        *generated_note_paths,
    ]
    for artifact_path in artifact_paths:
        if not artifact_path.exists():
            continue
        tasks, task_artifacts, _ = task_artifact_register(
            tasks,
            task_artifacts,
            aok_task_uid=task_uid,
            artifact_name=artifact_path.name,
            artifact_type="data" if artifact_path.suffix.lower() == ".csv" else "note",
            artifact_path=str(artifact_path),
            note="demo_generated",
        )

    # 9) 持久化三库数据。
    persist_reference_tables(
        literatures_df=literatures,
        attachments_df=literature_attachments,
        db_path=content_db,
    )
    persist_knowledge_tables(
        index_df=knowledge_index,
        attachments_df=knowledge_attachments,
        db_path=content_db,
    )
    _save_table(tasks_csv, tasks)
    _save_table(task_artifacts_csv, task_artifacts)

    # 10) 导出任务包。
    bundle_result = task_bundle_export(
        task_artifacts,
        aok_task_uid=task_uid,
        output_dir=output_dir / "task_bundle",
    )

    return {
        "status": "PASS",
        "mode": "aok-triple-db-demo",
        "project_root": str(project_root),
        "task_bootstrap": task_bootstrap,
        "input": {
            "bib_path": str(bib_path),
            "rdf_files_root": str(rdf_files_root),
            "max_bib_records": max_bib_records,
            "max_attachments": max_attachments,
        },
        "summary": {
            "literature_count": len(imported_literature_uids),
            "knowledge_count": len(generated_knowledge_uids),
            "copied_attachment_count": len(copied_attachments),
            "task_uid": task_uid,
            "invalid_literature_uids": invalid_lits,
            "invalid_knowledge_uids": invalid_kns,
        },
        "outputs": {
            "content_db": str(content_db),
            "tasks_csv": str(tasks_csv),
            "task_artifacts_csv": str(task_artifacts_csv),
            "generated_note_paths": [str(path) for path in generated_note_paths],
            "copied_attachments": [str(path) for path in copied_attachments],
            "bundle": bundle_result,
        },
    }


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置路径。

    Returns:
        事务结果文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)

    project_root = Path(str(raw_cfg.get("project_root") or "")).resolve()
    bib_path = Path(str(raw_cfg.get("bib_path") or "")).resolve()
    rdf_files_root = Path(str(raw_cfg.get("rdf_files_root") or "")).resolve()
    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent)).resolve()

    result = run_demo(
        project_root=project_root,
        bib_path=bib_path,
        rdf_files_root=rdf_files_root,
        output_dir=output_dir,
        max_bib_records=int(raw_cfg.get("max_bib_records") or 3),
        max_attachments=int(raw_cfg.get("max_attachments") or 6),
    )
    return write_affair_json_result(raw_cfg, config_path, "aok_triple_db_demo_result.json", result)
