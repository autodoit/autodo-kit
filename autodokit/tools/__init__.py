"""AOK 工具统一导出入口。

本模块采用“直调函数优先”的设计：

1. 用户侧直接 `from autodokit.tools import 某工具` 后调用函数；
2. 开发侧通过开发者清单了解内部辅助工具；
3. 公开调用入口保持为“函数直调 + 分组导出”。
"""

from __future__ import annotations

import ast
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

def load_json_or_py(config_path: str | Path) -> Any:
    config_path = Path(config_path)
    if config_path.suffix.lower() == ".json":
        return json.loads(config_path.read_text(encoding="utf-8-sig"))
    if config_path.suffix.lower() == ".py":
        namespace = ast.parse(config_path.read_text(encoding="utf-8"))
        for node in namespace.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "CONFIG":
                        return ast.literal_eval(node.value)
        raise ValueError(f"Python 配置文件缺少 CONFIG 变量: {config_path}")
    raise ValueError(f"不支持的配置文件类型: {config_path.suffix}")


def find_repo_root(path: str | Path | None = None) -> Path:
    current = Path(path or ".").resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").exists():
            return candidate
    return current


def resolve_path_from_base(base: str | Path, raw_path: str | Path) -> Path:
    raw = Path(raw_path)
    return raw if raw.is_absolute() else (Path(base).resolve() / raw)


def _looks_like_path(key: str, value: str) -> bool:
    key_l = key.lower()
    if any(token in key_l for token in ["path", "dir", "root", "file", "workspace"]):
        return True
    if value.startswith("http://") or value.startswith("https://"):
        return False
    return "/" in value or "\\" in value


def _resolve_value_to_absolute(value: Any, workspace_root: Path, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _resolve_value_to_absolute(v, workspace_root, parent_key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value_to_absolute(item, workspace_root, parent_key=parent_key) for item in value]
    if isinstance(value, str) and _looks_like_path(parent_key, value):
        return str(resolve_path_from_base(workspace_root, value).resolve())
    return value


def resolve_config_paths(config: dict[str, Any], base: str | Path) -> dict[str, Any]:
    return resolve_paths_to_absolute(config, workspace_root=base)


def resolve_path_with_workspace_root(workspace_root: str | Path, raw_path: str | Path) -> Path:
    return resolve_path_from_base(workspace_root, raw_path).resolve()


def resolve_paths_to_absolute(config: dict[str, Any], workspace_root: str | Path) -> dict[str, Any]:
    return _resolve_value_to_absolute(dict(config), Path(workspace_root).resolve())


def resolve_workflow_config_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def build_adjacency_matrix_df(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("build_adjacency_matrix_df 暂未在 autodokit 内置运行时实现")


def build_inverted_from_adjacency(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("build_inverted_from_adjacency 暂未在 autodokit 内置运行时实现")


def build_inverted_index(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("build_inverted_index 暂未在 autodokit 内置运行时实现")

def sparse_from_inverted(inv: dict[str, list[int]], row_ids: list[int]):
    from scipy.sparse import csc_matrix  # type: ignore

    row_pos = {int(rid): idx for idx, rid in enumerate(row_ids)}
    labels = list(inv.keys())
    data: list[int] = []
    rows: list[int] = []
    cols: list[int] = []
    for col_idx, label in enumerate(labels):
        for rid in inv.get(label, []):
            pos = row_pos.get(int(rid))
            if pos is None:
                continue
            rows.append(pos)
            cols.append(col_idx)
            data.append(1)
    return csc_matrix((data, (rows, cols)), shape=(len(row_ids), len(labels)), dtype=int), labels

def load_affair_tags(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("load_affair_tags 暂未在 autodokit 内置运行时实现")

def get_affairs_by_scenario(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("get_affairs_by_scenario 暂未在 autodokit 内置运行时实现")

def get_tags_by_affair(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("get_tags_by_affair 暂未在 autodokit 内置运行时实现")

class ExpressionEngineError(RuntimeError):
    pass

@dataclass
class ExpressionEvalResult:
    value: Any = None
    success: bool = False
    error: str = ""

def evaluate_expression(expression: str, names: dict[str, Any] | None = None) -> ExpressionEvalResult:
    try:
        from simpleeval import simple_eval

        value = simple_eval(expression, names=names or {})
        return ExpressionEvalResult(value=value, success=True, error="")
    except Exception as exc:
        return ExpressionEvalResult(value=None, success=False, error=str(exc))

def evaluate_predicate(expression: str, names: dict[str, Any] | None = None) -> bool:
    result = evaluate_expression(expression, names=names)
    if not result.success:
        raise ExpressionEngineError(result.error)
    return bool(result.value)

@dataclass
class NodeExecutionResult:
    success: bool = False
    outputs: dict[str, Any] | None = None
    error: str | None = None

def load_json_file(path: str | Path) -> Any:
    return load_json_or_py(path)

def resolve_config_path(path: str | Path | None = None) -> Path:
    if path is None:
        raise ValueError("config_path 不能为空")
    return Path(path).expanduser().resolve()

def resolve_workspace_root(config_file: str | Path | None = None, config: dict[str, Any] | None = None) -> Path:
    if config and config.get("workspace_root"):
        return Path(str(config["workspace_root"])).expanduser().resolve()
    if config_file is not None:
        return Path(config_file).expanduser().resolve().parent
    return Path.cwd().resolve()

def summarize_workflow(path: str | Path) -> dict[str, Any]:
    workflow_path = Path(path).expanduser().resolve()
    data = load_json_or_py(workflow_path)
    if not isinstance(data, dict):
        return {"workflow_path": str(workflow_path), "node_count": 0, "edge_count": 0, "name": workflow_path.stem}
    nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
    edges = data.get("edges") if isinstance(data.get("edges"), list) else []
    return {
        "workflow_path": str(workflow_path),
        "name": str(data.get("name") or workflow_path.stem),
        "node_count": len(nodes),
        "edge_count": len(edges),
    }

def load_dispatch_map(path: str | Path) -> dict[str, Any]:
    data = load_json_or_py(path)
    if not isinstance(data, dict):
        raise ValueError("dispatch_map 必须是字典")
    return data

def append_flow_trace_event(trace_file: str | Path, event: dict[str, Any]) -> Path:
    target = Path(trace_file).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    return target

def local_reference_lookup_and_materialize(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """延迟加载本地参考文献清单检索工具，避免入口模块循环导入。"""

    module = importlib.import_module("autodokit.tools.local_reference_lookup_tools")
    impl = getattr(module, "local_reference_lookup_and_materialize")
    return impl(*args, **kwargs)


def incremental_import_bib_into_content_db(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """延迟加载 Bib 增量导入工具，避免入口模块循环导入。"""

    module = importlib.import_module("autodokit.tools.incremental_bib_import_tools")
    impl = getattr(module, "incremental_import_bib_into_content_db")
    return impl(*args, **kwargs)


def normalize_primary_fulltext_attachment_names(payload: dict[str, Any]) -> dict[str, Any]:
    """延迟加载主附件规范化命名工具。"""

    module = importlib.import_module("autodokit.tools.literature_attachment_name_normalization_tools")
    impl = getattr(module, "normalize_primary_fulltext_attachment_names")
    return impl(payload)


def resolve_primary_attachment_normalization_settings(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """延迟加载主附件规范化命名配置解析工具。"""

    module = importlib.import_module("autodokit.tools.literature_attachment_name_normalization_tools")
    impl = getattr(module, "resolve_primary_attachment_normalization_settings")
    return impl(*args, **kwargs)

def scan_affairs(affairs_root: str | Path | None = None) -> list[dict[str, Any]]:
    if affairs_root is None:
        affairs_root = Path(__file__).resolve().parents[1] / "affairs"
    root = Path(affairs_root).resolve()
    if not root.exists():
        return []
    results: list[dict[str, Any]] = []
    for affair_dir in sorted(root.iterdir()):
        if not affair_dir.is_dir():
            continue
        affair_file = affair_dir / "affair.py"
        if not affair_file.exists():
            continue
        uid = affair_dir.name
        results.append(
            {
                "affair_uid": uid,
                "module": f"autodokit.affairs.{uid}.affair",
                "runner": {"module": f"autodokit.affairs.{uid}.affair", "callable": "execute"},
                "source": str(affair_file),
            }
        )
    return results

def validate_affair_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    uid = str(manifest.get("affair_uid") or "").strip()
    module = str(((manifest.get("runner") or {}).get("module") or "")).strip()
    return {"valid": bool(uid and module), "errors": [] if uid and module else ["affair_uid 或 runner.module 缺失"]}

def build_registry(affairs_root: str | Path | None = None) -> dict[str, dict[str, Any]]:
    return {item["affair_uid"]: item for item in scan_affairs(affairs_root=affairs_root)}

def build_runtime_registry_view(affairs_root: str | Path | None = None) -> list[dict[str, Any]]:
    return scan_affairs(affairs_root=affairs_root)

def build_module_alias_index(affairs_root: str | Path | None = None) -> dict[str, str]:
    return {item["affair_uid"]: item["module"] for item in scan_affairs(affairs_root=affairs_root)}

def resolve_runner(affair_uid: str, affairs_root: str | Path | None = None) -> tuple[str, str]:
    registry = build_registry(affairs_root=affairs_root)
    record = registry.get(str(affair_uid))
    if not record:
        raise KeyError(f"未找到事务: {affair_uid}")
    runner = record.get("runner") or {}
    return str(runner.get("module") or ""), str(runner.get("callable") or "execute")

def get_affair_docs(affair_uid: str, affairs_root: str | Path | None = None) -> str:
    if affairs_root is None:
        affairs_root = Path(__file__).resolve().parents[1] / "affairs"
    docs_path = Path(affairs_root).resolve() / str(affair_uid) / "affair.md"
    if not docs_path.exists():
        return ""
    return docs_path.read_text(encoding="utf-8")

def lint_affairs(affairs_root: str | Path | None = None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in scan_affairs(affairs_root=affairs_root):
        report = validate_affair_manifest(item)
        if not report["valid"]:
            findings.append({"affair_uid": item.get("affair_uid"), "errors": report["errors"]})
    return findings
from autodokit.tools.affair_result import ensure_absolute_output_dir, write_affair_json_result
from autodokit.tools.atomic.path.windows_long_filename_tools import (
    WindowsShortPathAlias,
    build_short_alias_name,
    materialize_short_alias,
    needs_short_alias,
)
from autodokit.tools.aob_tools import (
    run_aob_aoc,
    run_aob_deploy,
    run_aob_library,
    run_aob_regression_opencode_deploy_check,
    run_aob_workflow_deploy,
    run_aob_items_sync,
    run_aob_external_templates_import,
    run_aob_workspace_convert,
)
from autodokit.tools.cnki_affair_helpers import build_cnki_result
from autodokit.tools.bibliodb import (
    parse_reference_text,
    insert_placeholder_from_reference,
    literature_upsert,
    literature_insert_placeholder,
    literature_match,
    literature_attach_file,
    literature_bind_standard_note,
    literature_get,
)
from autodokit.tools.reference_citation_tools import (
    build_reference_quality_summary,
    build_online_lookup_placeholder_fields,
    extract_reference_lines_from_attachment,
    parse_reference_text_with_llm,
    process_reference_citation,
    refine_reference_lines_with_llm,
)
from autodokit.tools.literature_main_table_tools import build_literature_main_table
from autodokit.tools.literature_attachment_tools import build_literature_attachment_inverted_index
from autodokit.tools.literature_tag_tools import build_literature_tag_inverted_index
from autodokit.tools.literature_audit_table_tools import (
    build_entity_to_literatures_csv,
    build_literature_main_audit_csv,
)
from autodokit.tools.knowledgedb import (
    generate_knowledge_uid,
    init_empty_knowledge_index_table,
    init_empty_knowledge_attachments_table,
    knowledge_upsert,
    knowledge_note_register,
    knowledge_note_validate_obsidian,
    knowledge_bind_literature_standard_note,
    knowledge_base_generate,
    knowledge_index_sync_from_note,
    knowledge_attachment_register,
    knowledge_sync_note,
    knowledge_attach_file,
    knowledge_get,
    knowledge_find_by_literature,
)
from autodokit.tools.obsidian_note_timezone_tools import (
    DEFAULT_OBSIDIAN_NOTE_TIMEZONE,
    DEFAULT_OBSIDIAN_TIME_FIELDS,
    batch_rewrite_obsidian_note_timestamps,
    convert_timestamp_to_timezone,
    get_current_time_iso,
    rewrite_obsidian_note_timestamps,
)
from autodokit.tools.affair_entry_registry_tools import (
    MAINLINE_AFFAIR_ENTRY_MAP,
    build_mainline_affair_entry_registry,
    resolve_mainline_affair_entry,
    write_mainline_affair_entry_registry,
)
from autodokit.tools.bibliodb_sqlite import (
    build_stable_attachment_uid,
    init_db as init_references_db,
    load_literatures_df,
    load_attachments_df as load_literature_attachments_df,
    load_reading_queue_df,
    load_tags_df as load_literature_tags_df,
    load_chunk_sets_df,
    load_chunks_df,
    replace_tags_for_namespace,
    save_structured_state,
    get_structured_state,
    replace_chunk_set_records,
    rebuild_reference_relation_tables,
    rebuild_reference_relation_tables_from_config,
    save_tables as save_reference_tables,
    upsert_reading_queue_rows,
)
from autodokit.tools.knowledgedb_sqlite import (
    init_db as init_knowledge_db,
    load_index_df,
    load_attachments_df as load_knowledge_attachments_df,
    save_tables as save_knowledge_tables,
)
from autodokit.tools.contentdb_sqlite import (
    init_content_db,
    load_attachment_entities_df,
    load_knowledge_evidence_links_df,
    load_knowledge_literature_links_df,
    load_literature_attachment_links_df,
    resolve_content_db_path,
)
from autodokit.tools.literature_translation_tools import (
    DEFAULT_TRANSLATION_POLICY,
    run_literature_translation,
    translate_literature_metadata,
    translate_parse_asset_text,
    translate_standard_note,
)
from autodokit.tools.storage_backend import (
    load_reference_tables,
    persist_reference_tables,
    load_knowledge_tables,
    persist_knowledge_tables,
)
from autodokit.tools.atomic.task_aok import (
    bootstrap_aok_taskdb,
    create_task_ledger_readonly_views,
    init_empty_task_artifacts_table,
    init_empty_task_gate_decisions_table,
    init_empty_task_handoffs_table,
    init_empty_task_knowledge_bindings_table,
    init_empty_task_literature_bindings_table,
    init_empty_task_relations_table,
    init_empty_task_releases_table,
    init_empty_task_round_views_table,
    init_empty_task_status_log_table,
    init_empty_tasks_table,
    normalize_affair_receipt,
    run_unified_postprocess,
    task_artifact_register,
    task_bind_knowledges,
    task_bind_literatures,
    task_bundle_export,
    task_create_or_update,
    task_gate_decision_record,
    task_get,
    task_handoff_record,
    task_knowledge_binding_register,
    task_literature_binding_register,
    task_relation_upsert,
    task_release_promote,
    task_release_register,
    task_round_snapshot_register,
    task_status_append,
    validate_aok_taskdb,
)
from autodokit.tools.atomic.log_aok import (
    DEFAULT_AOK_LOG_DB_FILENAME,
    DEFAULT_AOK_LOG_EVENT_COLUMNS,
    append_aok_log_event,
    bootstrap_aok_logdb,
    create_aok_log_readonly_views,
    init_empty_log_events_table,
    list_aok_log_events,
    record_aok_gate_review,
    record_aok_human_decision,
    record_aok_log_artifact,
    validate_aok_logdb,
)
from autodokit.tools.research_workflow_tools import (
    init_empty_candidate_view_table,
    init_empty_reading_batch_table,
    init_empty_innovation_pool_table,
    build_candidate_view_index,
    build_candidate_readable_view,
    build_review_candidate_views,
    build_non_review_candidate_views,
    allocate_reading_batches,
    extract_review_candidates,
    build_research_trajectory,
    build_gate_review,
    score_gate_review,
    merge_human_gate_decision,
    innovation_pool_upsert,
    innovation_feasibility_score,
)
from autodokit.tools.review_synthesis_tools import (
    build_review_consensus_rows,
    build_review_controversy_rows,
    build_review_future_rows,
    build_review_general_reading_list,
    build_review_must_read_originals,
    extract_review_state_from_attachment,
    extract_review_state_from_structured_file,
    refine_review_state_with_llm,
    sentence_line_from_review_state,
)
from autodokit.tools.review_reading_packet_tools import (
    build_review_reading_packet,
    resolve_review_text_by_priority,
)
from autodokit.tools.ocr.classic.pdf_structured_data_tools import (
    build_chunk_entries_from_structured_data,
    build_doc_record_from_structured_data,
    build_structured_data_payload,
    extract_reference_lines_from_structured_data,
    iter_chunk_files_from_manifest,
    load_document_records_from_structured_source,
    load_single_document_record,
    load_structured_data,
    write_chunk_shards,
)
from autodokit.tools.ocr.babeldoc.pdf_structured_element_extractor_from_babeldoc import (
    extract_pdf_elements_from_structured_data,
    extract_pdf_elements_from_structured_file,
)
from autodokit.tools.ocr.classic.pdf_page_image_tools import (
    crop_image_by_normalized_bbox,
    render_pdf_pages_to_png,
)
from autodokit.tools.ocr.aliyun_multimodal.pdf_multimodal_tree_builder import (
    build_elements_payload as build_pdf_multimodal_elements_payload,
    build_quality_report as build_pdf_multimodal_quality_report,
    build_tree_linear_index as build_pdf_multimodal_tree_linear_index,
    build_structure_tree as build_pdf_multimodal_structure_tree,
    render_reconstructed_markdown as render_pdf_multimodal_reconstructed_markdown,
)
from autodokit.tools.ocr.monkeyocr.monkeyocr_windows_tools import (
    prepare_monkeyocr_windows_runtime,
    run_monkeyocr_windows_batch_folder,
    run_monkeyocr_windows_single_pdf,
)
from autodokit.tools.ocr.aliyun_multimodal.aok_pdf_aliyun_multimodal_parse import (
    build_aliyun_multimodal_chunks,
    generate_aok_pdf_parse_uid,
    parse_pdf_with_aliyun_multimodal,
    resolve_aok_pdf_parse_output_dir,
)
from autodokit.tools.ocr.aliyun_multimodal.aok_pdf_aliyun_multimodal_batch_manage import (
    batch_manage_pdf_with_aliyun_multimodal,
)
from autodokit.tools.workspace_path_migration import (
    PathMapping,
    migrate_workspace_paths,
)
def run_online_retrieval_router(payload: dict[str, Any]) -> dict[str, Any]:
    """延迟加载在线检索路由器并执行路由调用。

    这样做可以避免在模块导入时触发内部实现文件的顶级导入，从而
    将 `run_online_retrieval_router` 作为用户可用的安全入口。
    """
    module = importlib.import_module("autodokit.tools.online_retrieval_literatures.online_retrieval_router")
    route = getattr(module, "route")
    return route(payload)


def run_online_retrieval_from_bib(payload: dict[str, Any]) -> dict[str, Any]:
    """根据 Bib 条目执行在线检索四项任务（通过路由层统一入口）。"""

    module = importlib.import_module("autodokit.tools.bib_online_retrieval_tool")
    runner = getattr(module, "run_online_retrieval_from_bib")
    return runner(payload)


_用户公开工具 = [
    "parse_reference_text",
    "insert_placeholder_from_reference",
    "literature_upsert",
    "literature_insert_placeholder",
    "literature_match",
    "literature_attach_file",
    "literature_bind_standard_note",
    "literature_get",
    "extract_reference_lines_from_attachment",
    "parse_reference_text_with_llm",
    "process_reference_citation",
    "refine_reference_lines_with_llm",
    "build_reference_quality_summary",
    "build_online_lookup_placeholder_fields",
    "local_reference_lookup_and_materialize",
    "incremental_import_bib_into_content_db",
    "generate_knowledge_uid",
    "init_empty_knowledge_index_table",
    "init_empty_knowledge_attachments_table",
    "knowledge_upsert",
    "knowledge_note_register",
    "knowledge_note_validate_obsidian",
    "knowledge_bind_literature_standard_note",
    "knowledge_base_generate",
    "knowledge_index_sync_from_note",
    "knowledge_attachment_register",
    "knowledge_sync_note",
    "knowledge_attach_file",
    "knowledge_get",
    "knowledge_find_by_literature",
    "DEFAULT_OBSIDIAN_NOTE_TIMEZONE",
    "DEFAULT_OBSIDIAN_TIME_FIELDS",
    "get_current_time_iso",
    "convert_timestamp_to_timezone",
    "rewrite_obsidian_note_timestamps",
    "batch_rewrite_obsidian_note_timestamps",
    "DEFAULT_AOK_LOG_DB_FILENAME",
    "DEFAULT_AOK_LOG_EVENT_COLUMNS",
    "init_empty_log_events_table",
    "bootstrap_aok_logdb",
    "validate_aok_logdb",
    "append_aok_log_event",
    "list_aok_log_events",
    "record_aok_log_artifact",
    "record_aok_gate_review",
    "record_aok_human_decision",
    "init_empty_candidate_view_table",
    "init_empty_reading_batch_table",
    "init_empty_innovation_pool_table",
    "build_candidate_view_index",
    "build_candidate_readable_view",
    "build_review_candidate_views",
    "build_non_review_candidate_views",
    "allocate_reading_batches",
    "extract_review_candidates",
    "build_research_trajectory",
    "build_gate_review",
    "score_gate_review",
    "merge_human_gate_decision",
    "innovation_pool_upsert",
    "innovation_feasibility_score",
    "build_review_consensus_rows",
    "build_review_controversy_rows",
    "build_review_future_rows",
    "build_review_general_reading_list",
    "build_review_must_read_originals",
    "extract_review_state_from_attachment",
    "extract_review_state_from_structured_file",
    "sentence_line_from_review_state",
    "build_review_reading_packet",
    "resolve_review_text_by_priority",
    "extract_pdf_elements_from_structured_data",
    "extract_pdf_elements_from_structured_file",
    "render_pdf_pages_to_png",
    "crop_image_by_normalized_bbox",
    "build_pdf_multimodal_elements_payload",
    "build_pdf_multimodal_structure_tree",
    "build_pdf_multimodal_tree_linear_index",
    "build_pdf_multimodal_quality_report",
    "render_pdf_multimodal_reconstructed_markdown",
    "generate_aok_pdf_parse_uid",
    "resolve_aok_pdf_parse_output_dir",
    "build_aliyun_multimodal_chunks",
    "parse_pdf_with_aliyun_multimodal",
    "batch_manage_pdf_with_aliyun_multimodal",
    "PathMapping",
    "migrate_workspace_paths",
    "build_structured_data_payload",
    "load_structured_data",
    "extract_reference_lines_from_structured_data",
    "load_single_document_record",
    "load_document_records_from_structured_source",
    "build_doc_record_from_structured_data",
    "build_chunk_entries_from_structured_data",
    "write_chunk_shards",
    "iter_chunk_files_from_manifest",
    "build_cnki_result",
    "run_aob_aoc",
    "run_aob_deploy",
    "run_aob_library",
    "run_aob_regression_opencode_deploy_check",
    "run_aob_workflow_deploy",
    "run_aob_items_sync",
    "run_aob_external_templates_import",
    "run_aob_workspace_convert",
    "ensure_absolute_output_dir",
    "write_affair_json_result",
    "build_literature_main_table",
    "build_literature_attachment_inverted_index",
    "build_literature_tag_inverted_index",
    "build_entity_to_literatures_csv",
    "build_literature_main_audit_csv",
    "build_stable_attachment_uid",
    "init_references_db",
    "init_knowledge_db",
    "init_content_db",
    "load_reference_tables",
    "persist_reference_tables",
    "load_knowledge_tables",
    "persist_knowledge_tables",
    "resolve_content_db_path",
    "load_knowledge_literature_links_df",
    "load_knowledge_evidence_links_df",
    "DEFAULT_TRANSLATION_POLICY",
    "translate_literature_metadata",
    "translate_standard_note",
    "translate_parse_asset_text",
    "run_literature_translation",
    "normalize_primary_fulltext_attachment_names",
    "resolve_primary_attachment_normalization_settings",
]

_开发者工具 = [
    "load_json_or_py",
    "find_repo_root",
    "resolve_path_from_base",
    "resolve_config_paths",
    "resolve_path_with_workspace_root",
    "resolve_paths_to_absolute",
    "resolve_workflow_config_path",
    "build_adjacency_matrix_df",
    "build_inverted_from_adjacency",
    "build_inverted_index",
    "sparse_from_inverted",
    "load_affair_tags",
    "get_affairs_by_scenario",
    "get_tags_by_affair",
    "ExpressionEngineError",
    "ExpressionEvalResult",
    "evaluate_expression",
    "evaluate_predicate",
    "NodeExecutionResult",
    "append_flow_trace_event",
    "ensure_absolute_output_dir",
    "write_affair_json_result",
    "build_literature_main_table",
    "build_literature_attachment_inverted_index",
    "build_literature_tag_inverted_index",
    "build_entity_to_literatures_csv",
    "build_literature_main_audit_csv",
    "build_stable_attachment_uid",
    "init_references_db",
    "init_knowledge_db",
    "init_content_db",
    "load_attachment_entities_df",
    "load_literatures_df",
    "load_literature_attachment_links_df",
    "load_literature_attachments_df",
    "load_literature_tags_df",
    "load_chunk_sets_df",
    "load_chunks_df",
    "save_structured_state",
    "get_structured_state",
    "replace_chunk_set_records",
    "rebuild_reference_relation_tables",
    "rebuild_reference_relation_tables_from_config",
    "load_literature_tags_df",
    "rebuild_reference_relation_tables",
    "rebuild_reference_relation_tables_from_config",
    "save_reference_tables",
    "load_index_df",
    "load_knowledge_attachments_df",
    "save_knowledge_tables",
    "load_reference_tables",
    "persist_reference_tables",
    "load_knowledge_tables",
    "persist_knowledge_tables",
    "resolve_content_db_path",
    "load_knowledge_literature_links_df",
    "load_knowledge_evidence_links_df",
    "DEFAULT_TRANSLATION_POLICY",
    "translate_literature_metadata",
    "translate_standard_note",
    "translate_parse_asset_text",
    "run_literature_translation",
    "build_cnki_result",
    "run_aob_aoc",
    "run_aob_deploy",
    "run_aob_library",
    "run_aob_regression_opencode_deploy_check",
    "run_aob_workflow_deploy",
    "run_aob_items_sync",
    "run_aob_external_templates_import",
    "run_aob_workspace_convert",
    "PathMapping",
    "migrate_workspace_paths",
    "parse_reference_text",
    "insert_placeholder_from_reference",
    "literature_upsert",
    "literature_insert_placeholder",
    "literature_match",
    "literature_attach_file",
    "literature_bind_standard_note",
    "literature_get",
    "extract_reference_lines_from_attachment",
    "parse_reference_text_with_llm",
    "process_reference_citation",
    "local_reference_lookup_and_materialize",
    "incremental_import_bib_into_content_db",
    "normalize_primary_fulltext_attachment_names",
    "resolve_primary_attachment_normalization_settings",
    "build_reference_quality_summary",
    "build_online_lookup_placeholder_fields",
    "generate_knowledge_uid",
    "init_empty_knowledge_index_table",
    "init_empty_knowledge_attachments_table",
    "knowledge_upsert",
    "knowledge_note_register",
    "knowledge_note_validate_obsidian",
    "knowledge_bind_literature_standard_note",
    "knowledge_base_generate",
    "knowledge_index_sync_from_note",
    "knowledge_attachment_register",
    "knowledge_sync_note",
    "knowledge_attach_file",
    "knowledge_get",
    "knowledge_find_by_literature",
    "DEFAULT_OBSIDIAN_NOTE_TIMEZONE",
    "DEFAULT_OBSIDIAN_TIME_FIELDS",
    "get_current_time_iso",
    "convert_timestamp_to_timezone",
    "rewrite_obsidian_note_timestamps",
    "batch_rewrite_obsidian_note_timestamps",
    "init_empty_tasks_table",
    "init_empty_task_artifacts_table",
    "init_empty_task_status_log_table",
    "init_empty_task_gate_decisions_table",
    "init_empty_task_handoffs_table",
    "init_empty_task_relations_table",
    "init_empty_task_round_views_table",
    "init_empty_task_releases_table",
    "init_empty_task_literature_bindings_table",
    "init_empty_task_knowledge_bindings_table",
    "task_create_or_update",
    "task_bind_literatures",
    "task_bind_knowledges",
    "task_artifact_register",
    "task_status_append",
    "task_gate_decision_record",
    "task_handoff_record",
    "task_relation_upsert",
    "task_round_snapshot_register",
    "task_release_register",
    "task_release_promote",
    "task_literature_binding_register",
    "task_knowledge_binding_register",
    "task_bundle_export",
    "task_get",
    "normalize_affair_receipt",
    "run_unified_postprocess",
    "create_task_ledger_readonly_views",
    "DEFAULT_AOK_LOG_DB_FILENAME",
    "DEFAULT_AOK_LOG_EVENT_COLUMNS",
    "init_empty_log_events_table",
    "bootstrap_aok_logdb",
    "create_aok_log_readonly_views",
    "validate_aok_logdb",
    "append_aok_log_event",
    "list_aok_log_events",
    "record_aok_log_artifact",
    "record_aok_gate_review",
    "record_aok_human_decision",
    "init_empty_candidate_view_table",
    "init_empty_reading_batch_table",
    "init_empty_innovation_pool_table",
    "build_candidate_view_index",
    "build_candidate_readable_view",
    "build_review_candidate_views",
    "build_non_review_candidate_views",
    "allocate_reading_batches",
    "extract_review_candidates",
    "build_research_trajectory",
    "build_gate_review",
    "score_gate_review",
    "merge_human_gate_decision",
    "innovation_pool_upsert",
    "innovation_feasibility_score",
    "build_review_consensus_rows",
    "build_review_controversy_rows",
    "build_review_future_rows",
    "build_review_general_reading_list",
    "build_review_must_read_originals",
    "extract_review_state_from_attachment",
    "refine_review_state_with_llm",
    "sentence_line_from_review_state",
    "build_review_reading_packet",
    "resolve_review_text_by_priority",
    "load_dispatch_map",
    "load_json_file",
    "resolve_config_path",
    "resolve_workspace_root",
    "summarize_workflow",
    "scan_affairs",
    "validate_affair_manifest",
    "build_registry",
    "build_runtime_registry_view",
    "build_module_alias_index",
    "resolve_runner",
    "get_affair_docs",
    "lint_affairs",
    "MAINLINE_AFFAIR_ENTRY_MAP",
    "build_mainline_affair_entry_registry",
    "write_mainline_affair_entry_registry",
    "resolve_mainline_affair_entry",
    "render_pdf_pages_to_png",
    "crop_image_by_normalized_bbox",
    "build_pdf_multimodal_elements_payload",
    "build_pdf_multimodal_structure_tree",
    "build_pdf_multimodal_tree_linear_index",
    "build_pdf_multimodal_quality_report",
    "render_pdf_multimodal_reconstructed_markdown",
    "generate_aok_pdf_parse_uid",
    "resolve_aok_pdf_parse_output_dir",
    "prepare_monkeyocr_windows_runtime",
    "run_monkeyocr_windows_single_pdf",
    "build_aliyun_multimodal_chunks",
    "parse_pdf_with_aliyun_multimodal",
    "batch_manage_pdf_with_aliyun_multimodal",
    "run_online_retrieval_router",
    "run_online_retrieval_from_bib",
]


def list_user_tools() -> list[str]:
    """返回面向用户公开的工具名列表。

    Returns:
        list[str]: 用户可直接导入与调用的工具函数名。

    Examples:
        >>> "parse_reference_text" in list_user_tools()
        True
    """

    return list(_用户公开工具)


def list_developer_tools() -> list[str]:
    """返回面向开发者的工具名列表。

    Returns:
        list[str]: 开发者可使用的工具函数名。

    Examples:
        >>> "load_json_or_py" in list_developer_tools()
        True
    """

    return list(_开发者工具)


def get_tool(tool_name: str, *, scope: str = "user") -> Callable[..., Any]:
    """按名称读取工具函数。

    Args:
        tool_name: 工具函数名。
        scope: 工具范围，支持 `user`、`developer`、`all`。

    Returns:
        Callable[..., Any]: 工具函数对象。

    Raises:
        KeyError: 工具不存在或不在指定范围内时抛出。

    Examples:
        >>> fn = get_tool("parse_reference_text")
        >>> callable(fn)
        True
    """

    target = str(tool_name or "").strip()
    if not target:
        raise KeyError("tool_name 不能为空")

    if scope == "user":
        allowed = set(_用户公开工具)
    elif scope == "developer":
        allowed = set(_开发者工具)
    else:
        allowed = set(_用户公开工具) | set(_开发者工具)

    if target not in allowed or target not in globals():
        raise KeyError(f"工具不存在或未在范围[{scope}]内公开：{target}")
    symbol = globals()[target]
    if not callable(symbol):
        raise KeyError(f"目标不是可调用工具：{target}")
    return symbol


__all__ = list(_用户公开工具)

