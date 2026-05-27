"""A080 非综述文献预处理事务。

A080 优先消费正式 `A080` 阶段队列，并结合 `文献主表.current_parse_*`
与结构化摘要字段完成统一预处理；旧 reading_state 仅保留兼容回写。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from autodokit.tools import (
    append_aok_log_event,
    build_gate_review,
    load_json_or_py,
)
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.atomic.task_aok.task_instance_dir import (
    create_task_instance_dir,
    mirror_artifacts_to_legacy,
    resolve_legacy_output_dir,
)
from autodokit.tools.bibliodb_sqlite import (
    READING_QUEUE_COLUMNS,
    READING_QUEUE_STORAGE_TABLE,
    load_reading_queue_df,
    load_reading_state_df,
    upsert_reading_queue_rows,
    upsert_reading_state_rows,
)
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.ocr.runtime.monkeyocr_manifest_runtime import (
    resolve_parse_runtime_settings,
    resolve_postprocess_settings,
    run_parse_manifest,
)
from autodokit.tools.storage_backend import (
    load_reference_tables,
    persist_reference_tables,
)


OUTPUT_INDEX = "a080_preprocess_index.csv"
OUTPUT_GATE = "gate_review.json"
OUTPUT_RELATED_ITEMS_CSV = "related_literature_items.csv"
OUTPUT_RELATED_ITEMS_MD = "related_literature_items.md"


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


def _load_preprocess_pool(
    content_db: Path,
    *,
    literature_df: pd.DataFrame,
    state_df: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    """优先从正式 A080 阶段队列构建输入池，必要时兼容旧 reading_state。"""

    queue_df = load_reading_queue_df(
        content_db,
        stage="A080",
        only_current=True,
        queue_statuses=["queued", "candidate", "in_progress"],
    )
    if not queue_df.empty:
        literature_by_uid = {
            _stringify(row.get("uid_literature")): row.to_dict()
            for _, row in literature_df.fillna("").iterrows()
            if _stringify(row.get("uid_literature"))
        }
        state_by_uid = {
            _stringify(row.get("uid_literature")): row.to_dict()
            for _, row in state_df.fillna("").iterrows()
            if _stringify(row.get("uid_literature"))
        }
        merged_rows: list[dict[str, Any]] = []
        for _, row in queue_df.fillna("").iterrows():
            queue_row = row.to_dict()
            uid_literature = _stringify(queue_row.get("uid_literature"))
            combined: dict[str, Any] = {}
            if uid_literature:
                combined.update(literature_by_uid.get(uid_literature, {}))
                combined.update(state_by_uid.get(uid_literature, {}))
            combined.update(queue_row)
            combined["cite_key"] = _stringify(combined.get("cite_key")) or uid_literature
            merged_rows.append(combined)
        return pd.DataFrame(merged_rows).fillna(""), "queue"

    legacy_df = state_df.loc[
        pd.to_numeric(state_df.get("pending_preprocess", 0), errors="coerce").fillna(0).astype(int) == 1
    ].copy()
    if legacy_df.empty:
        return pd.DataFrame(), "queue"
    return legacy_df.fillna(""), "reading_state"


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


def _consume_current_stage_queue_rows(content_db: Path, *, stage: str, ready_df: pd.DataFrame) -> int:
    """消费已成功推进的兼容队列 current 行，避免后续重复命中。"""

    if ready_df is None or ready_df.empty:
        return 0

    identities: List[Tuple[str, str]] = []
    for _, row in ready_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        if not uid_literature and not cite_key:
            continue
        identities.append((uid_literature, cite_key))

    if not identities:
        return 0

    queue_df = load_reading_queue_df(content_db).copy()
    if queue_df.empty:
        return 0
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    identity_set = set(identities)
    mask = (
        queue_df.get("stage", pd.Series(dtype=str)).astype(str).eq(stage)
        & queue_df.get("is_current", pd.Series(dtype=int)).fillna(0).astype(int).eq(1)
        & pd.Series(
            [(_stringify(row.get("uid_literature")), _stringify(row.get("cite_key"))) in identity_set for _, row in queue_df.fillna("").iterrows()],
            index=queue_df.index,
        )
    )
    affected = int(mask.sum())
    if affected <= 0:
        return 0
    queue_df.loc[mask, "is_current"] = 0
    queue_df.loc[mask, "queue_status"] = "completed"
    queue_df.loc[mask, "updated_at"] = now_iso
    if "id" in queue_df.columns:
        queue_df = queue_df.drop(columns=["id"])
    queue_df = queue_df[[column for column in READING_QUEUE_COLUMNS if column in queue_df.columns]].copy()
    upsert_reading_queue_rows(content_db, queue_df)
    return affected


def _write_related_literature_items(output_dir: Path, frame: pd.DataFrame) -> list[Path]:
    snapshot_columns = [
        "uid_literature",
        "cite_key",
        "title",
        "manifest_status",
        "pdf_path",
        "recommended_reason",
        "theme_relation",
        "source_origin",
        "reading_objective",
        "manual_guidance",
        "failure_reason",
    ]
    available_columns = [column for column in snapshot_columns if column in frame.columns]
    snapshot_df = frame[available_columns].copy() if available_columns else pd.DataFrame()

    csv_path = output_dir / OUTPUT_RELATED_ITEMS_CSV
    md_path = output_dir / OUTPUT_RELATED_ITEMS_MD
    snapshot_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    label_map = {
        "uid_literature": "文献 UID",
        "cite_key": "题录键",
        "title": "标题",
        "manifest_status": "处理状态",
        "pdf_path": "PDF 路径",
        "recommended_reason": "推荐原因",
        "theme_relation": "主题关系",
        "source_origin": "来源口径",
        "reading_objective": "阅读目标",
        "manual_guidance": "人工提示",
        "failure_reason": "失败原因",
    }
    lines = ["# A080 相关文献条目", "", f"共 {len(snapshot_df)} 条。", ""]
    if snapshot_df.empty:
        lines.append("当前任务没有产出可记录的相关文献条目。")
    else:
        for index, row in snapshot_df.fillna("").iterrows():
            title = _stringify(row.get("title")) or _stringify(row.get("cite_key")) or _stringify(row.get("uid_literature")) or f"条目 {index + 1}"
            lines.append(f"## {index + 1}. {title}")
            for column in available_columns:
                value = _stringify(row.get(column))
                if not value:
                    continue
                lines.append(f"- {label_map.get(column, column)}：{value}")
            lines.append("")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return [csv_path, md_path]


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

    literatures_df, attachments_df, _ = load_reference_tables(db_path=content_db)
    existing_state_df = load_reading_state_df(content_db)
    state_df, input_mode = _load_preprocess_pool(
        content_db,
        literature_df=literatures_df,
        state_df=existing_state_df,
    )
    legacy_seeded_count = 0
    if state_df.empty:
        legacy_seeded_count = _seed_state_from_legacy_queue(content_db)
        if legacy_seeded_count > 0:
            existing_state_df = load_reading_state_df(content_db)
            state_df, input_mode = _load_preprocess_pool(
                content_db,
                literature_df=literatures_df,
                state_df=existing_state_df,
            )
    failed_preprocess_statuses = {"missing_attachment", "parse_failed", "note_skeleton_failed"}
    if not state_df.empty and "preprocess_status" in state_df.columns:
        state_df = state_df.loc[
            ~state_df["preprocess_status"].fillna("").astype(str).str.lower().isin(failed_preprocess_statuses)
        ].copy()

    max_items = int(raw_cfg.get("max_items") or 0)
    if max_items > 0:
        state_df = state_df.head(max_items).reset_index(drop=True)
    allow_unparsed_read_bypass = bool(raw_cfg.get("allow_unparsed_read_bypass", False))
    auto_enable_unparsed_for_failed_items = bool(raw_cfg.get("auto_enable_unparsed_for_failed_items", True))

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
    postprocess_success_count = 0

    for _, row in manifest_df.iterrows():
        row_dict = dict(row.to_dict())
        uid_literature = _stringify(row_dict.get("uid_literature"))
        cite_key = _stringify(row_dict.get("cite_key")) or uid_literature
        title = _stringify(row_dict.get("title")) or cite_key
        manifest_status = _stringify(row_dict.get("manifest_status")) or "failed"
        if int(row_dict.get("postprocess_ok") or 0):
            postprocess_success_count += 1
        failure_reason = _stringify(row_dict.get("failure_reason"))
        existing = existing_state_by_uid.get(uid_literature, {})
        recommended_reason = _stringify(row_dict.get("recommended_reason") or existing.get("recommended_reason"))
        theme_relation = _stringify(row_dict.get("theme_relation") or existing.get("theme_relation"))
        source_origin = _stringify(row_dict.get("source_origin") or existing.get("source_origin")) or "auto"
        reading_objective = _stringify(row_dict.get("reading_objective") or existing.get("reading_objective"))
        manual_guidance = _stringify(row_dict.get("manual_guidance") or existing.get("manual_guidance"))
        preprocess_status = ""

        if manifest_status in {"succeeded", "skipped"}:
            ready_count += 1
            preprocess_status = "ready"
            was_unparsed_read = int(existing.get("allow_unparsed_read") or 0) == 1 or int(existing.get("unparsed_read_in_effect") or 0) == 1
            rough_done_without_parse = int(existing.get("rough_read_without_parse_done") or 0) == 1
            deep_done_without_parse = int(existing.get("deep_read_without_parse_done") or 0) == 1
            should_force_reread_after_parse = was_unparsed_read and (rough_done_without_parse or deep_done_without_parse)

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
                "allow_unparsed_read": 0,
                "unparsed_read_in_effect": 0,
                "preprocess_status": preprocess_status,
                "preprocess_note_path": "",
                "pending_rough_read": 1 if should_force_reread_after_parse or int(existing.get("rough_read_done") or 0) == 0 else int(existing.get("pending_rough_read") or 0),
                "in_rough_read": int(existing.get("in_rough_read") or 0),
                "rough_read_done": 0 if should_force_reread_after_parse and rough_done_without_parse else int(existing.get("rough_read_done") or 0),
                "pending_deep_read": 1 if should_force_reread_after_parse and deep_done_without_parse else int(existing.get("pending_deep_read") or 0),
                "deep_read_done": 0 if should_force_reread_after_parse and deep_done_without_parse else int(existing.get("deep_read_done") or 0),
                "deep_read_count": int(existing.get("deep_read_count") or 0),
                "rough_read_without_parse_done": int(existing.get("rough_read_without_parse_done") or 0),
                "deep_read_without_parse_done": int(existing.get("deep_read_without_parse_done") or 0),
                "require_reread_after_parse": 0,
            }
            state_updates.append(state_row)
            existing_state_by_uid[uid_literature] = state_row
        else:
            failed_count += 1
            preprocess_status = "missing_attachment" if "未找到可用 PDF 附件" in failure_reason else "parse_failed"
            enable_unparsed_bypass = allow_unparsed_read_bypass and auto_enable_unparsed_for_failed_items
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
                    "pending_preprocess": 0,
                    "preprocessed": int(existing.get("preprocessed") or 0),
                    "allow_unparsed_read": 1 if enable_unparsed_bypass else int(existing.get("allow_unparsed_read") or 0),
                    "unparsed_read_in_effect": 1 if enable_unparsed_bypass else int(existing.get("unparsed_read_in_effect") or 0),
                    "preprocess_status": preprocess_status,
                    "preprocess_note_path": _stringify(existing.get("preprocess_note_path")),
                    "pending_rough_read": 1 if enable_unparsed_bypass else int(existing.get("pending_rough_read") or 0),
                    "in_rough_read": int(existing.get("in_rough_read") or 0),
                    "rough_read_done": int(existing.get("rough_read_done") or 0),
                    "pending_deep_read": int(existing.get("pending_deep_read") or 0),
                    "deep_read_done": int(existing.get("deep_read_done") or 0),
                    "deep_read_count": int(existing.get("deep_read_count") or 0),
                    "rough_read_without_parse_done": int(existing.get("rough_read_without_parse_done") or 0),
                    "deep_read_without_parse_done": int(existing.get("deep_read_without_parse_done") or 0),
                    "require_reread_after_parse": 1 if enable_unparsed_bypass else int(existing.get("require_reread_after_parse") or 0),
                }
            )

        result_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "title": title,
                "manifest_status": manifest_status,
                "pdf_path": _stringify(row_dict.get("pdf_path")),
                "normalized_structured_path": _stringify(row_dict.get("normalized_structured_path")),
                "reconstructed_markdown_path": _stringify(row_dict.get("reconstructed_markdown_path")),
                "asset_dir": _stringify(row_dict.get("asset_dir")),
                "recommended_reason": recommended_reason,
                "theme_relation": theme_relation,
                "source_origin": source_origin,
                "reading_objective": reading_objective,
                "manual_guidance": manual_guidance,
                "failure_reason": failure_reason,
            }
        )

    if state_updates:
        upsert_reading_state_rows(content_db, state_updates)

    ready_df = manifest_df.loc[
        manifest_df["manifest_status"].astype(str).str.lower().isin(["succeeded", "skipped"])
    ].copy() if not manifest_df.empty and "manifest_status" in manifest_df.columns else pd.DataFrame()
    consumed_a080_queue_count = _consume_current_stage_queue_rows(content_db, stage="A080", ready_df=ready_df)

    if ready_count > 0:
        persist_reference_tables(
            literatures_df=literatures_df,
            attachments_df=attachments_df,
            db_path=content_db,
        )

    result_df = pd.DataFrame(result_rows)
    index_path = output_dir / OUTPUT_INDEX
    result_df.to_csv(index_path, index=False, encoding="utf-8-sig")
    related_item_paths = _write_related_literature_items(output_dir, result_df)

    gate_review = build_gate_review(
        node_uid="A080",
        node_name="非综述文献预处理",
        summary=(
            f"消费 A080 输入池 {len(state_df)} 条（mode={input_mode}）；"
            f"legacy queue 补种 {legacy_seeded_count} 条；"
            f"解析就绪 {ready_count} 条；"
            f"失败 {failed_count} 条；"
            f"后处理成功 {postprocess_success_count} 条；"
            f"消费 A080 兼容队列 {consumed_a080_queue_count} 条。"
        ),
        checks=[
            {"name": "a080_input_count", "value": len(state_df)},
            {"name": "a080_input_mode", "value": input_mode},
            {"name": "legacy_queue_seeded_count", "value": legacy_seeded_count},
            {"name": "preprocess_ready_count", "value": ready_count},
            {"name": "preprocess_failed_count", "value": failed_count},
            {"name": "postprocess_success_count", "value": postprocess_success_count},
            {"name": "consumed_a080_queue_count", "value": consumed_a080_queue_count},
        ],
        artifacts=[
            str(index_path),
            *[str(path) for path in related_item_paths],
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
            "input_mode": input_mode,
            "upstream_stage": "A075",
            "downstream_stage": "A090",
            "allow_unparsed_read_bypass": allow_unparsed_read_bypass,
            "auto_enable_unparsed_for_failed_items": auto_enable_unparsed_for_failed_items,
        },
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    artifact_paths = [
        index_path,
        gate_path,
        *related_item_paths,
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
            skill_names=["a080-nonreview-preprocess-v6"],
            reasoning_summary="优先消费 A080 正式阶段队列，并按文献主表 current_parse/结构化摘要执行统一预处理与粗读推进。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=artifact_paths,
            payload={
                "input_count": len(state_df),
                "input_mode": input_mode,
                "legacy_queue_seeded_count": legacy_seeded_count,
                "ready_count": ready_count,
                "failed_count": failed_count,
                "postprocess_success_count": postprocess_success_count,
                "consumed_a080_queue_count": consumed_a080_queue_count,
            },
        )
    except Exception:
        pass

    return artifact_paths

