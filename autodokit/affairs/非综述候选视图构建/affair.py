"""A080 非综述候选与预处理编排事务。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import (
    append_aok_log_event,
    build_gate_review,
    knowledge_bind_literature_standard_note,
    knowledge_index_sync_from_note,
    knowledge_note_register,
    literature_bind_standard_note,
    load_json_or_py,
)
from autodokit.tools.bibliodb_sqlite import load_reading_queue_df, load_reading_state_df, save_dataframe_table, upsert_reading_state_rows
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.ocr.runtime.monkeyocr_manifest_runtime import (
    resolve_parse_runtime_settings,
    resolve_postprocess_settings,
    run_parse_manifest,
)
from autodokit.tools.reading_state_tools import build_standard_note_body
from autodokit.tools.storage_backend import load_knowledge_tables, load_reference_tables, persist_knowledge_tables, persist_reference_tables
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


OUTPUT_INDEX = "a080_preprocess_index.csv"
OUTPUT_GATE = "gate_review.json"


def _build_task_instance_dir(workspace_root: Path, node_code: str) -> Path:
    task_instance_dir = workspace_root / "tasks" / f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{node_code}"
    task_instance_dir.mkdir(parents=True, exist_ok=False)
    (task_instance_dir / "task_manifest.json").write_text(
        json.dumps(
            {
                "task_uid": task_instance_dir.name,
                "node_code": node_code,
                "workspace_root": str(workspace_root),
                "task_instance_dir": str(task_instance_dir),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return task_instance_dir


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _safe_file_stem(text: str) -> str:
    return "".join(character if character not in "\\/:*?\"<>|" else "_" for character in _stringify(text)) or "untitled"


def _resolve_workspace_root(config_path: Path, raw_cfg: Dict[str, Any]) -> Path:
    candidate = _stringify(raw_cfg.get("workspace_root"))
    if candidate:
        path = Path(candidate)
        if not path.is_absolute():
            raise ValueError(f"workspace_root 必须为绝对路径: {path}")
        return path
    return config_path.parents[2]


def _resolve_output_dir(config_path: Path, raw_cfg: Dict[str, Any]) -> Path:
    output_dir = Path(str(raw_cfg.get("legacy_output_dir") or raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(f"output_dir 必须为绝对路径: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _seed_state_from_legacy_queue(content_db: Path) -> int:
    queue_df = load_reading_queue_df(content_db, stage="A080", only_current=True, queue_statuses=["queued", "candidate", "in_progress"])
    if queue_df.empty:
        return 0
    rows: List[Dict[str, Any]] = []
    for _, row in queue_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        if not uid_literature and not cite_key:
            continue
        rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "source_stage": "A080_queue",
                "recommended_reason": _stringify(row.get("recommended_reason")) or "legacy A080 queue seed",
                "theme_relation": _stringify(row.get("theme_relation")) or "legacy_a080_queue",
                "pending_preprocess": 1,
                "preprocessed": 0,
                "pending_rough_read": 0,
                "rough_read_done": 0,
                "pending_deep_read": 0,
                "deep_read_done": 0,
                "deep_read_count": 0,
            }
        )
    if rows:
        upsert_reading_state_rows(content_db, rows)
    return len(rows)


def _resolve_pdf_path(literature_row: pd.Series, attachments_df: pd.DataFrame) -> str:
    uid_literature = _stringify(literature_row.get("uid_literature"))
    attachment_rows = attachments_df[attachments_df.get("uid_literature", pd.Series(dtype=str)).astype(str) == uid_literature]
    if not attachment_rows.empty:
        attachment_rows = attachment_rows.sort_values(by=["is_primary", "attachment_name"], ascending=[False, True])
        path_text = _stringify(attachment_rows.iloc[0].get("storage_path") or attachment_rows.iloc[0].get("source_path"))
        if path_text:
            return path_text
    return _stringify(literature_row.get("pdf_path"))


def _build_human_seed_state_rows(
    *,
    seed_contract: Dict[str, Any],
    literatures_df: pd.DataFrame,
    attachments_df: pd.DataFrame,
    existing_state_by_uid: Dict[str, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[str]]:
    """把 human_seed_contract 转换为 reading_state 行。"""

    if not bool(seed_contract.get("enabled", False)):
        return [], []

    seed_items = seed_contract.get("seed_items") or []
    if not isinstance(seed_items, list):
        return [], ["human_seed_contract.seed_items 不是数组，已跳过"]

    default_target_stage = _stringify(seed_contract.get("default_target_stage") or "rough_read") or "rough_read"
    default_manual_guidance = _stringify(seed_contract.get("manual_guidance"))
    default_reading_objective = _stringify(seed_contract.get("reading_objective"))
    on_ambiguous = _stringify(seed_contract.get("on_ambiguous") or "manual_review") or "manual_review"
    on_missing = _stringify(seed_contract.get("on_missing") or "route_to_a040") or "route_to_a040"

    rows: List[Dict[str, Any]] = []
    issues: List[str] = []
    for item in seed_items:
        if not isinstance(item, dict):
            issues.append("human_seed_contract.seed_items 含非对象条目，已跳过")
            continue

        cite_key = _stringify(item.get("cite_key"))
        if not cite_key:
            issues.append("human_seed_contract.seed_items 存在空 cite_key，已跳过")
            continue

        matches = literatures_df[literatures_df.get("cite_key", pd.Series(dtype=str)).astype(str) == cite_key]
        if matches.empty:
            issues.append(f"{cite_key}: 未命中文献主表，策略={on_missing}")
            continue
        if len(matches) > 1:
            issues.append(f"{cite_key}: 命中多条文献，策略={on_ambiguous}")
            continue

        literature_row = matches.iloc[0]
        uid_literature = _stringify(literature_row.get("uid_literature"))
        if not uid_literature:
            issues.append(f"{cite_key}: 文献缺少 uid_literature，已跳过")
            continue

        existing = existing_state_by_uid.get(uid_literature, {})
        target_stage = _stringify(item.get("target_stage") or default_target_stage) or "rough_read"
        target_stage = "deep_read" if target_stage == "deep_read" else "rough_read"
        manual_guidance = _stringify(item.get("manual_guidance") or default_manual_guidance)
        reading_objective = _stringify(item.get("reading_objective") or default_reading_objective)
        reason = _stringify(item.get("recommended_reason") or item.get("reason") or f"human seed: {target_stage}")
        theme_relation = _stringify(item.get("theme_relation") or "human_seed")

        has_attachment = bool(_resolve_pdf_path(literature_row, attachments_df))
        preprocessed = int(existing.get("preprocessed") or 0)
        rough_done = int(existing.get("rough_read_done") or 0)
        deep_done = int(existing.get("deep_read_done") or 0)

        pending_preprocess = int(existing.get("pending_preprocess") or 0)
        pending_rough_read = int(existing.get("pending_rough_read") or 0)
        pending_deep_read = int(existing.get("pending_deep_read") or 0)

        if target_stage == "deep_read":
            if deep_done:
                issues.append(f"{cite_key}: 已 deep_read_done=1，跳过重复投递")
                continue
            if preprocessed and has_attachment:
                pending_deep_read = 1
                pending_preprocess = 0
            else:
                pending_preprocess = 1
        else:
            if rough_done:
                issues.append(f"{cite_key}: 已 rough_read_done=1，跳过重复投递")
                continue
            if preprocessed and has_attachment:
                pending_rough_read = 1
                pending_preprocess = 0
            else:
                pending_preprocess = 1

        row: Dict[str, Any] = {
            "uid_literature": uid_literature,
            "cite_key": cite_key,
            "source_stage": "A080_human_seed",
            "recommended_reason": reason,
            "theme_relation": theme_relation,
            "source_origin": "human",
            "manual_guidance": manual_guidance,
            "reading_objective": reading_objective,
            "pending_preprocess": pending_preprocess,
            "preprocessed": preprocessed,
            "pending_rough_read": pending_rough_read,
            "rough_read_done": rough_done,
            "pending_deep_read": pending_deep_read,
            "deep_read_done": deep_done,
            "deep_read_count": int(existing.get("deep_read_count") or 0),
        }
        rows.append(row)
        existing_state_by_uid[uid_literature] = row

    return rows, issues


@affair_auto_git_commit("A080")
def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    legacy_output_dir = _resolve_output_dir(config_path, raw_cfg)
    output_dir = _build_task_instance_dir(workspace_root, "A080")
    content_db, _ = resolve_content_db_config(
        raw_cfg,
        legacy_keys=("references_db",),
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None

    seeded_count = 0
    literatures_df, attachments_df, _ = load_reference_tables(db_path=content_db)
    existing_state_df = load_reading_state_df(content_db)
    existing_state_by_uid = {
        _stringify(row.get("uid_literature")): row.to_dict()
        for _, row in existing_state_df.fillna("").iterrows()
        if _stringify(row.get("uid_literature"))
    }

    seed_contract = raw_cfg.get("human_seed_contract") or {}
    human_seed_rows, human_seed_issues = _build_human_seed_state_rows(
        seed_contract=seed_contract if isinstance(seed_contract, dict) else {},
        literatures_df=literatures_df,
        attachments_df=attachments_df,
        existing_state_by_uid=existing_state_by_uid,
    )
    if human_seed_rows:
        upsert_reading_state_rows(content_db, human_seed_rows)
        seeded_count += len(human_seed_rows)

    state_df = load_reading_state_df(content_db, flag_filters={"pending_preprocess": 1})
    if state_df.empty:
        seeded_count += _seed_state_from_legacy_queue(content_db)
        state_df = load_reading_state_df(content_db, flag_filters={"pending_preprocess": 1})

    knowledge_index_df, knowledge_attachments_df, _ = load_knowledge_tables(db_path=content_db)
    max_items = int(raw_cfg.get("max_items") or 0)
    if max_items > 0:
        state_df = state_df.head(max_items).reset_index(drop=True)

    global_config_path = workspace_root / "config" / "config.json"
    parse_runtime = resolve_parse_runtime_settings(raw_cfg, workspace_root=workspace_root, global_config_path=global_config_path)
    postprocess_settings = resolve_postprocess_settings(raw_cfg, workspace_root=workspace_root)
    manifest_result = run_parse_manifest(
        content_db=content_db,
        source_df=state_df,
        output_dir=output_dir,
        source_stage="A080",
        upstream_stage="A070",
        downstream_stage="A090",
        parse_level="non_review_rough",
        literature_scope="non_review",
        runtime_settings=parse_runtime,
        postprocess_settings=postprocess_settings,
        global_config_path=global_config_path,
        overwrite_existing=False,
        max_items=max_items,
    )
    manifest_df = manifest_result["manifest_df"]

    note_dir = workspace_root / "knowledge" / "standard_notes"
    note_dir.mkdir(parents=True, exist_ok=True)
    result_rows: List[Dict[str, Any]] = []
    state_updates: List[Dict[str, Any]] = []
    failures: List[str] = list(human_seed_issues)
    failures.extend(manifest_result["failures"])

    for _, state_row in manifest_df.fillna("").iterrows():
        uid_literature = _stringify(state_row.get("uid_literature"))
        cite_key = _stringify(state_row.get("cite_key"))
        manifest_status = _stringify(state_row.get("manifest_status"))
        failure_reason = _stringify(state_row.get("failure_reason"))
        mask = literatures_df.get("uid_literature", pd.Series(dtype=str)).astype(str) == uid_literature
        if not mask.any():
            failures.append(f"{uid_literature}: 未在 literatures 中找到文献")
            state_updates.append({"uid_literature": uid_literature, "cite_key": cite_key, "pending_preprocess": 1, "preprocessed": 0, "preprocess_status": "missing_literature"})
            continue

        literature_row = literatures_df.loc[mask].iloc[0].copy()
        resolved_cite_key = cite_key or _stringify(literature_row.get("cite_key")) or uid_literature
        literatures_df.loc[mask, "cite_key"] = resolved_cite_key
        pdf_path = _resolve_pdf_path(literature_row, attachments_df)
        if manifest_status == "failed":
            preprocess_status = "parse_failed"
            if "附件" in failure_reason or "pdf" in failure_reason.lower():
                preprocess_status = "missing_attachment"
            state_updates.append({
                "uid_literature": uid_literature,
                "cite_key": resolved_cite_key,
                "pending_preprocess": 1,
                "preprocessed": 0,
                "preprocess_status": preprocess_status,
            })
            continue

        structured_path = _stringify(state_row.get("normalized_structured_path"))

        note_path = note_dir / f"{_safe_file_stem(resolved_cite_key)}.md"
        note_body = build_standard_note_body(
            title=_stringify(literature_row.get("title")) or resolved_cite_key,
            cite_key=resolved_cite_key,
            summary_lines=[
                f"- uid_literature: {uid_literature}",
                f"- year: {_stringify(literature_row.get('year'))}",
                f"- pdf_path: {pdf_path}",
                f"- structured_path: {structured_path or '待补充'}",
            ],
        )
        note_info = knowledge_note_register(
            note_path=note_path,
            title=_stringify(literature_row.get("title")) or resolved_cite_key,
            note_type="literature_standard_note",
            status="draft",
            evidence_uids=[uid_literature],
            tags=["aok/standard_note", "a080"],
            aliases=[resolved_cite_key],
            uid_literature=uid_literature,
            cite_key=resolved_cite_key,
            body=note_body,
        )
        knowledge_bind_literature_standard_note(note_path, uid_literature, resolved_cite_key)
        knowledge_index_df, _ = knowledge_index_sync_from_note(knowledge_index_df, note_path, workspace_root=workspace_root)
        literatures_df, _ = literature_bind_standard_note(literatures_df, uid_literature, note_info["uid_knowledge"])

        state_updates.append(
            {
                "uid_literature": uid_literature,
                "cite_key": resolved_cite_key,
                "source_stage": _stringify(state_row.get("source_stage")) or "A080",
                "recommended_reason": _stringify(state_row.get("recommended_reason")),
                "theme_relation": _stringify(state_row.get("theme_relation")),
                "source_origin": _stringify(state_row.get("source_origin")) or "auto",
                "reading_objective": _stringify(state_row.get("reading_objective")),
                "manual_guidance": _stringify(state_row.get("manual_guidance")),
                "pending_preprocess": 0,
                "preprocessed": 1,
                "preprocess_status": "ready",
                "preprocess_note_path": str(note_path),
                "standard_note_path": str(note_path),
                "pending_rough_read": 1,
                "rough_read_done": int(state_row.get("rough_read_done") or 0),
                "pending_deep_read": int(state_row.get("pending_deep_read") or 0),
                "deep_read_done": int(state_row.get("deep_read_done") or 0),
                "deep_read_count": int(state_row.get("deep_read_count") or 0),
            }
        )
        result_rows.append({
            "uid_literature": uid_literature,
            "cite_key": resolved_cite_key,
            "title": _stringify(literature_row.get("title")),
            "standard_note_path": str(note_path),
            "structured_path": structured_path,
            "preprocess_status": "ready",
            "postprocess_ok": int(state_row.get("postprocess_ok") or 0),
            "postprocess_llm_basic_cleanup_status": _stringify(state_row.get("postprocess_llm_basic_cleanup_status")),
            "postprocess_llm_structure_status": _stringify(state_row.get("postprocess_llm_structure_status")),
            "postprocess_contamination_removed_block_count": int(state_row.get("postprocess_contamination_removed_block_count") or 0),
        })

    persist_reference_tables(literatures_df=literatures_df, attachments_df=attachments_df, db_path=content_db)
    persist_knowledge_tables(index_df=knowledge_index_df, attachments_df=knowledge_attachments_df, db_path=content_db)
    if state_updates:
        upsert_reading_state_rows(content_db, state_updates)

    result_df = pd.DataFrame(result_rows)
    index_path = output_dir / OUTPUT_INDEX
    result_df.to_csv(index_path, index=False, encoding="utf-8-sig")
    save_dataframe_table(content_db, "a080_preprocess_index", result_df, if_exists="replace", unique_columns=["uid_literature"] if not result_df.empty else None)

    gate_review = build_gate_review(
        node_uid="A080",
        node_name="非综述候选与预处理编排",
        summary=f"完成预处理 {len(result_df)} 篇；从旧 A080 queue 引导 {seeded_count} 条；失败 {len(failures)} 条。",
        checks=[{"name": "seeded_from_legacy_queue", "value": seeded_count}, {"name": "preprocessed_count", "value": len(result_df)}, {"name": "failure_count", "value": len(failures)}],
        artifacts=[str(index_path), str(manifest_result["manifest_path"]), str(manifest_result["management_table_path"]), str(manifest_result["handoff_path"])],
        recommendation="pass" if len(result_df) > 0 else "retry_current",
        score=max(40.0, 92.0 - len(failures) * 8.0),
        issues=failures,
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "manifest_path": str(manifest_result["manifest_path"]),
            "management_table_path": str(manifest_result["management_table_path"]),
            "handoff_path": str(manifest_result["handoff_path"]),
            "batch_report_path": str(manifest_result["batch_report_path"]),
            "parse_runtime": parse_runtime,
            "enable_aliyun_postprocess": bool(postprocess_settings.get("enabled", True)),
            "enable_llm_basic_cleanup": bool(postprocess_settings.get("enable_llm_basic_cleanup", True)),
            "basic_cleanup_llm_model": postprocess_settings.get("basic_cleanup_llm_model"),
            "enable_llm_structure_resolution": bool(postprocess_settings.get("enable_llm_structure_resolution", True)),
            "structure_llm_model": postprocess_settings.get("structure_llm_model"),
            "enable_llm_contamination_filter": bool(postprocess_settings.get("enable_llm_contamination_filter", True)),
            "contamination_llm_model": postprocess_settings.get("contamination_llm_model"),
        },
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    if legacy_output_dir != output_dir:
        legacy_output_dir.mkdir(parents=True, exist_ok=True)
        for artifact_path in [index_path, gate_path]:
            legacy_target = legacy_output_dir / artifact_path.name
            legacy_target.write_text(artifact_path.read_text(encoding="utf-8"), encoding="utf-8")

    try:
        append_aok_log_event(
            event_type="A080_PREPROCESS_COMPLETED",
            project_root=workspace_root,
            affair_code="A080",
            handler_name="非综述候选与预处理编排",
            agent_names=["ar_A080_非综述候选与预处理编排事务智能体_v6"],
            skill_names=["ar_非综述候选文献视图构建_v5"],
            reasoning_summary="消费 literature_reading_state.pending_preprocess=1，并把成功条目推进到 pending_rough_read=1。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=[index_path, gate_path, manifest_result["manifest_path"], manifest_result["management_table_path"], manifest_result["handoff_path"]],
            payload={
                "preprocessed_count": len(result_df),
                "seeded_from_legacy_queue": seeded_count,
                "failure_count": len(failures),
                "enable_llm_basic_cleanup": bool(postprocess_settings.get("enable_llm_basic_cleanup", True)),
                "enable_llm_structure_resolution": bool(postprocess_settings.get("enable_llm_structure_resolution", True)),
                "enable_llm_contamination_filter": bool(postprocess_settings.get("enable_llm_contamination_filter", True)),
            },
        )
    except Exception:
        pass

    return [index_path, gate_path, manifest_result["manifest_path"], manifest_result["management_table_path"], manifest_result["batch_report_path"], manifest_result["handoff_path"]]



