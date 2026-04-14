"""A080 非综述文献预处理事务。

A080 仅消费 literature_reading_state.pending_preprocess=1 当前态，完成：
1. MonkeyOCR 解析资产准备。
2. 标准文献笔记骨架创建与绑定。
3. 状态推进到 pending_rough_read。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

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
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.atomic.task_aok.task_instance_dir import (
    create_task_instance_dir,
    mirror_artifacts_to_legacy,
    resolve_legacy_output_dir,
)
from autodokit.tools.bibliodb_sqlite import (
    load_reading_queue_df,
    load_reading_state_df,
    upsert_reading_state_rows,
)
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.ocr.runtime.monkeyocr_manifest_runtime import (
    resolve_parse_runtime_settings,
    resolve_postprocess_settings,
    run_parse_manifest,
)
from autodokit.tools.reading_state_tools import build_standard_note_body
from autodokit.tools.storage_backend import (
    load_knowledge_tables,
    load_reference_tables,
    persist_knowledge_tables,
    persist_reference_tables,
)


OUTPUT_INDEX = "a080_preprocess_index.csv"
OUTPUT_GATE = "gate_review.json"


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


def _resolve_global_config_path(workspace_root: Path) -> Path | None:
    candidate = workspace_root / "config" / "config.json"
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _seed_state_from_legacy_queue(content_db: Path) -> int:
    queue_df = load_reading_queue_df(
        content_db,
        stage="A080",
        only_current=True,
        queue_statuses=["queued", "candidate", "in_progress"],
    )
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
                "source_stage": "A080_legacy_queue",
                "recommended_reason": _stringify(row.get("recommended_reason")) or "legacy A080 queue seed",
                "theme_relation": _stringify(row.get("theme_relation")) or "legacy_a080_queue",
                "source_origin": _stringify(row.get("source_origin")) or "legacy_queue",
                "pending_preprocess": 1,
                "preprocessed": 0,
                "pending_rough_read": 0,
                "in_rough_read": 0,
                "rough_read_done": 0,
                "pending_deep_read": 0,
                "deep_read_done": 0,
                "deep_read_count": 0,
                "reading_objective": _stringify(row.get("reading_objective")),
                "manual_guidance": _stringify(row.get("manual_guidance")),
            }
        )

    if rows:
        upsert_reading_state_rows(content_db, rows)
    return len(rows)


def _match_literature_row(literatures_df: pd.DataFrame, *, uid_literature: str, cite_key: str) -> Dict[str, Any]:
    if literatures_df is None or literatures_df.empty:
        return {}
    if uid_literature and "uid_literature" in literatures_df.columns:
        matched = literatures_df[literatures_df["uid_literature"].astype(str) == uid_literature]
        if not matched.empty:
            return dict(matched.iloc[0].to_dict())
    if cite_key and "cite_key" in literatures_df.columns:
        matched = literatures_df[literatures_df["cite_key"].astype(str) == cite_key]
        if not matched.empty:
            return dict(matched.iloc[0].to_dict())
    return {}


def _build_standard_note_summary_lines(
    *,
    recommended_reason: str,
    reading_objective: str,
    manual_guidance: str,
) -> List[str]:
    lines = ["- 已完成 A080 预处理。"]
    if recommended_reason:
        lines.append(f"- 推荐原因：{recommended_reason}")
    if reading_objective:
        lines.append(f"- 阅读目标：{reading_objective}")
    if manual_guidance:
        lines.append(f"- 人工提示：{manual_guidance}")
    return lines


def _ensure_standard_note_skeleton(
    *,
    workspace_root: Path,
    task_uid: str,
    knowledge_index_df: pd.DataFrame,
    knowledge_attachments_df: pd.DataFrame,
    literatures_df: pd.DataFrame,
    uid_literature: str,
    cite_key: str,
    title: str,
    recommended_reason: str,
    reading_objective: str,
    manual_guidance: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Path, str]:
    del knowledge_attachments_df
    note_name = _safe_file_stem(cite_key or uid_literature)
    note_path = workspace_root / "knowledge" / "standard_notes" / f"{note_name}.md"
    literature_row = _match_literature_row(literatures_df, uid_literature=uid_literature, cite_key=cite_key)
    standard_note_uid = _stringify(literature_row.get("standard_note_uid"))

    if not note_path.exists():
        register_result = knowledge_note_register(
            note_path=note_path,
            title=title or cite_key or uid_literature,
            uid_knowledge=standard_note_uid,
            note_type="literature_standard_note",
            status="draft",
            source_task_uid=task_uid,
            uid_literature=uid_literature,
            cite_key=cite_key,
            body=build_standard_note_body(
                title=title or cite_key or uid_literature,
                cite_key=cite_key or uid_literature,
                summary_lines=_build_standard_note_summary_lines(
                    recommended_reason=recommended_reason,
                    reading_objective=reading_objective,
                    manual_guidance=manual_guidance,
                ),
            ),
        )
        standard_note_uid = _stringify(register_result.get("uid_knowledge"))

    knowledge_bind_literature_standard_note(note_path, uid_literature, cite_key)
    knowledge_index_df, index_row = knowledge_index_sync_from_note(
        knowledge_index_df,
        note_path,
        workspace_root=workspace_root,
    )
    standard_note_uid = _stringify(index_row.get("uid_knowledge")) or standard_note_uid
    if standard_note_uid:
        literatures_df, _ = literature_bind_standard_note(literatures_df, uid_literature, standard_note_uid)
    return literatures_df, knowledge_index_df, knowledge_attachments_df, note_path, standard_note_uid


@affair_auto_git_commit("A080")
def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    if not isinstance(raw_cfg, dict):
        raise ValueError("A080 配置必须是字典")

    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    legacy_output_dir = resolve_legacy_output_dir(
        raw_cfg,
        config_path,
        default_path=workspace_root / "tasks" / "A080_non_review_preprocess",
    )
    output_dir = create_task_instance_dir(workspace_root, "A080")
    task_uid = output_dir.name
    global_config_path = _resolve_global_config_path(workspace_root)

    content_db, _ = resolve_content_db_config(
        raw_cfg,
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None

    state_df = load_reading_state_df(content_db, flag_filters={"pending_preprocess": 1})
    legacy_seeded_count = 0
    if state_df.empty:
        legacy_seeded_count = _seed_state_from_legacy_queue(content_db)
        if legacy_seeded_count > 0:
            state_df = load_reading_state_df(content_db, flag_filters={"pending_preprocess": 1})

    max_items = int(raw_cfg.get("max_items") or 0)
    if max_items > 0:
        state_df = state_df.head(max_items).reset_index(drop=True)

    parse_runtime = resolve_parse_runtime_settings(
        raw_cfg,
        workspace_root=workspace_root,
        global_config_path=global_config_path,
    )
    postprocess_settings = resolve_postprocess_settings(raw_cfg, workspace_root=workspace_root)
    manifest_result = run_parse_manifest(
        content_db=content_db,
        source_df=state_df,
        output_dir=output_dir,
        source_stage="A080",
        upstream_stage="A075",
        downstream_stage="A090",
        parse_level="non_review_rough",
        literature_scope="non_review",
        runtime_settings=parse_runtime,
        postprocess_settings=postprocess_settings,
        global_config_path=global_config_path,
        overwrite_existing=False,
        max_items=max_items,
    )

    manifest_df = manifest_result["manifest_df"].fillna("")
    literatures_df, attachments_df, _ = load_reference_tables(db_path=content_db)
    knowledge_index_df, knowledge_attachments_df, _ = load_knowledge_tables(db_path=content_db)
    existing_state_df = load_reading_state_df(content_db)
    existing_state_by_uid = {
        _stringify(row.get("uid_literature")): row.to_dict()
        for _, row in existing_state_df.fillna("").iterrows()
        if _stringify(row.get("uid_literature"))
    }

    result_rows: List[Dict[str, Any]] = []
    state_updates: List[Dict[str, Any]] = []
    failures: List[str] = list(manifest_result.get("failures") or [])
    ready_count = 0
    failed_count = 0
    note_ready_count = 0

    for _, row in manifest_df.iterrows():
        row_dict = dict(row.to_dict())
        uid_literature = _stringify(row_dict.get("uid_literature"))
        cite_key = _stringify(row_dict.get("cite_key")) or uid_literature
        title = _stringify(row_dict.get("title")) or cite_key
        manifest_status = _stringify(row_dict.get("manifest_status")) or "failed"
        failure_reason = _stringify(row_dict.get("failure_reason"))
        existing = existing_state_by_uid.get(uid_literature, {})
        recommended_reason = _stringify(row_dict.get("recommended_reason") or existing.get("recommended_reason"))
        theme_relation = _stringify(row_dict.get("theme_relation") or existing.get("theme_relation"))
        source_origin = _stringify(row_dict.get("source_origin") or existing.get("source_origin")) or "auto"
        reading_objective = _stringify(row_dict.get("reading_objective") or existing.get("reading_objective"))
        manual_guidance = _stringify(row_dict.get("manual_guidance") or existing.get("manual_guidance"))
        note_path_text = ""
        standard_note_uid = _stringify(existing.get("standard_note_uid"))
        note_issue = ""

        if manifest_status in {"succeeded", "skipped"}:
            ready_count += 1
            try:
                literatures_df, knowledge_index_df, knowledge_attachments_df, note_path, standard_note_uid = _ensure_standard_note_skeleton(
                    workspace_root=workspace_root,
                    task_uid=task_uid,
                    knowledge_index_df=knowledge_index_df,
                    knowledge_attachments_df=knowledge_attachments_df,
                    literatures_df=literatures_df,
                    uid_literature=uid_literature,
                    cite_key=cite_key,
                    title=title,
                    recommended_reason=recommended_reason,
                    reading_objective=reading_objective,
                    manual_guidance=manual_guidance,
                )
                note_path_text = str(note_path)
                note_ready_count += 1
            except Exception as exc:
                note_issue = str(exc)
                failures.append(f"{cite_key}: 标准笔记骨架生成失败: {note_issue}")

            state_row = {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "source_stage": "A080",
                "recommended_reason": recommended_reason,
                "theme_relation": theme_relation,
                "source_origin": source_origin,
                "reading_objective": reading_objective,
                "manual_guidance": manual_guidance,
                "pending_preprocess": 0,
                "preprocessed": 1,
                "pending_rough_read": 1 if int(existing.get("rough_read_done") or 0) == 0 else int(existing.get("pending_rough_read") or 0),
                "in_rough_read": int(existing.get("in_rough_read") or 0),
                "rough_read_done": int(existing.get("rough_read_done") or 0),
                "pending_deep_read": int(existing.get("pending_deep_read") or 0),
                "deep_read_done": int(existing.get("deep_read_done") or 0),
                "deep_read_count": int(existing.get("deep_read_count") or 0),
            }
            state_updates.append(state_row)
            existing_state_by_uid[uid_literature] = state_row
        else:
            failed_count += 1
            state_updates.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "source_stage": _stringify(existing.get("source_stage")) or "A075",
                    "recommended_reason": recommended_reason,
                    "theme_relation": theme_relation,
                    "source_origin": source_origin,
                    "reading_objective": reading_objective,
                    "manual_guidance": manual_guidance,
                    "pending_preprocess": 1,
                    "preprocessed": int(existing.get("preprocessed") or 0),
                    "pending_rough_read": int(existing.get("pending_rough_read") or 0),
                    "in_rough_read": int(existing.get("in_rough_read") or 0),
                    "rough_read_done": int(existing.get("rough_read_done") or 0),
                    "pending_deep_read": int(existing.get("pending_deep_read") or 0),
                    "deep_read_done": int(existing.get("deep_read_done") or 0),
                    "deep_read_count": int(existing.get("deep_read_count") or 0),
                }
            )

        result_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "title": title,
                "manifest_status": manifest_status,
                "normalized_structured_path": _stringify(row_dict.get("normalized_structured_path")),
                "reconstructed_markdown_path": _stringify(row_dict.get("reconstructed_markdown_path")),
                "asset_dir": _stringify(row_dict.get("asset_dir")),
                "recommended_reason": recommended_reason,
                "theme_relation": theme_relation,
                "source_origin": source_origin,
                "reading_objective": reading_objective,
                "manual_guidance": manual_guidance,
                "standard_note_path": note_path_text,
                "standard_note_uid": standard_note_uid,
                "note_issue": note_issue,
                "failure_reason": failure_reason,
            }
        )

    if state_updates:
        upsert_reading_state_rows(content_db, state_updates)

    if ready_count > 0:
        persist_reference_tables(
            literatures_df=literatures_df,
            attachments_df=attachments_df,
            db_path=content_db,
        )
        persist_knowledge_tables(
            index_df=knowledge_index_df,
            attachments_df=knowledge_attachments_df,
            db_path=content_db,
        )

    result_df = pd.DataFrame(result_rows)
    index_path = output_dir / OUTPUT_INDEX
    result_df.to_csv(index_path, index=False, encoding="utf-8-sig")

    gate_review = build_gate_review(
        node_uid="A080",
        node_name="非综述文献预处理",
        summary=(
            f"消费 pending_preprocess {len(state_df)} 条；"
            f"legacy queue 补种 {legacy_seeded_count} 条；"
            f"解析就绪 {ready_count} 条；"
            f"失败 {failed_count} 条；"
            f"标准笔记骨架 {note_ready_count} 条。"
        ),
        checks=[
            {"name": "pending_preprocess_input_count", "value": len(state_df)},
            {"name": "legacy_queue_seeded_count", "value": legacy_seeded_count},
            {"name": "preprocess_ready_count", "value": ready_count},
            {"name": "preprocess_failed_count", "value": failed_count},
            {"name": "standard_note_count", "value": note_ready_count},
        ],
        artifacts=[
            str(index_path),
            str(manifest_result["manifest_path"]),
            str(manifest_result["management_table_path"]),
            str(manifest_result["handoff_path"]),
            str(manifest_result["batch_report_path"]),
        ],
        recommendation="pass_next" if ready_count > 0 else "retry_current",
        score=max(50.0, 94.0 - len(failures) * 4.0),
        issues=failures,
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "manifest_path": str(manifest_result["manifest_path"]),
            "management_table_path": str(manifest_result["management_table_path"]),
            "handoff_path": str(manifest_result["handoff_path"]),
            "batch_report_path": str(manifest_result["batch_report_path"]),
            "parse_runtime": parse_runtime,
            "postprocess_enabled": bool(postprocess_settings.get("enabled", False)),
            "upstream_stage": "A075",
            "downstream_stage": "A090",
        },
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    artifact_paths = [
        index_path,
        gate_path,
        Path(manifest_result["manifest_path"]),
        Path(manifest_result["management_table_path"]),
        Path(manifest_result["handoff_path"]),
        Path(manifest_result["batch_report_path"]),
    ]
    mirror_artifacts_to_legacy(artifact_paths, legacy_output_dir, output_dir)

    try:
        append_aok_log_event(
            event_type="A080_NON_REVIEW_PREPROCESS_READY",
            project_root=workspace_root,
            affair_code="A080",
            handler_name="非综述文献预处理",
            agent_names=["ar_A080_非综述文献预处理事务智能体_v6"],
            skill_names=["ar_A080_非综述候选文献视图构建_v6"],
            reasoning_summary="仅消费 pending_preprocess 当前态，完成 MonkeyOCR 解析、标准笔记骨架与 pending_rough_read 推进。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=artifact_paths,
            payload={
                "input_count": len(state_df),
                "legacy_queue_seeded_count": legacy_seeded_count,
                "ready_count": ready_count,
                "failed_count": failed_count,
                "standard_note_count": note_ready_count,
            },
        )
    except Exception:
        pass

    return artifact_paths

