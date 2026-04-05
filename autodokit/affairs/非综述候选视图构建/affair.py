"""A080 非综述候选与预处理编排事务。"""

from __future__ import annotations

import json
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
from autodokit.tools.pdf_parse_asset_manager import ensure_multimodal_parse_asset
from autodokit.tools.reading_state_tools import build_standard_note_body
from autodokit.tools.storage_backend import load_knowledge_tables, load_reference_tables, persist_knowledge_tables, persist_reference_tables


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


def _resolve_output_dir(config_path: Path, raw_cfg: Dict[str, Any]) -> Path:
    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
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


def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    output_dir = _resolve_output_dir(config_path, raw_cfg)
    content_db, _ = resolve_content_db_config(
        raw_cfg,
        legacy_keys=("references_db",),
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None

    seeded_count = 0
    state_df = load_reading_state_df(content_db, flag_filters={"pending_preprocess": 1})
    if state_df.empty:
        seeded_count = _seed_state_from_legacy_queue(content_db)
        state_df = load_reading_state_df(content_db, flag_filters={"pending_preprocess": 1})

    literatures_df, attachments_df, _ = load_reference_tables(db_path=content_db)
    knowledge_index_df, knowledge_attachments_df, _ = load_knowledge_tables(db_path=content_db)
    ensure_parse_on_entry = bool(raw_cfg.get("ensure_parse_on_entry", True))
    overwrite_parse_asset = bool(raw_cfg.get("overwrite_parse_asset", False))
    parse_model = _stringify(raw_cfg.get("parse_model")) or "auto"
    max_items = int(raw_cfg.get("max_items") or 0)
    if max_items > 0:
        state_df = state_df.head(max_items).reset_index(drop=True)

    note_dir = workspace_root / "knowledge" / "standard_notes"
    note_dir.mkdir(parents=True, exist_ok=True)
    result_rows: List[Dict[str, Any]] = []
    state_updates: List[Dict[str, Any]] = []
    failures: List[str] = []

    for _, state_row in state_df.fillna("").iterrows():
        uid_literature = _stringify(state_row.get("uid_literature"))
        cite_key = _stringify(state_row.get("cite_key"))
        mask = literatures_df.get("uid_literature", pd.Series(dtype=str)).astype(str) == uid_literature
        if not mask.any():
            failures.append(f"{uid_literature}: 未在 literatures 中找到文献")
            state_updates.append({"uid_literature": uid_literature, "cite_key": cite_key, "pending_preprocess": 1, "preprocessed": 0, "preprocess_status": "missing_literature"})
            continue

        literature_row = literatures_df.loc[mask].iloc[0].copy()
        resolved_cite_key = cite_key or _stringify(literature_row.get("cite_key")) or uid_literature
        literatures_df.loc[mask, "cite_key"] = resolved_cite_key
        pdf_path = _resolve_pdf_path(literature_row, attachments_df)
        if not pdf_path:
            failures.append(f"{resolved_cite_key}: 缺少附件路径")
            state_updates.append({"uid_literature": uid_literature, "cite_key": resolved_cite_key, "pending_preprocess": 1, "preprocessed": 0, "preprocess_status": "missing_attachment"})
            continue

        parse_status = "skipped"
        structured_path = ""
        if ensure_parse_on_entry:
            try:
                parse_asset = ensure_multimodal_parse_asset(
                    content_db=content_db,
                    parse_level="non_review_rough",
                    uid_literature=uid_literature,
                    cite_key=resolved_cite_key,
                    source_stage="A080",
                    global_config_path=workspace_root / "config" / "config.json",
                    overwrite_existing=overwrite_parse_asset,
                    model=parse_model,
                )
                structured_path = _stringify(parse_asset.get("normalized_structured_path"))
                parse_status = "ready"
            except Exception as exc:
                failures.append(f"{resolved_cite_key}: 解析资产生成失败: {exc}")
                state_updates.append({"uid_literature": uid_literature, "cite_key": resolved_cite_key, "pending_preprocess": 1, "preprocessed": 0, "preprocess_status": "parse_failed"})
                continue

        note_path = note_dir / f"standard_note_{_safe_file_stem(resolved_cite_key)}.md"
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
                "pending_preprocess": 0,
                "preprocessed": 1,
                "preprocess_status": parse_status,
                "preprocess_note_path": str(note_path),
                "standard_note_path": str(note_path),
                "pending_rough_read": 1,
                "rough_read_done": int(state_row.get("rough_read_done") or 0),
                "pending_deep_read": int(state_row.get("pending_deep_read") or 0),
                "deep_read_done": int(state_row.get("deep_read_done") or 0),
                "deep_read_count": int(state_row.get("deep_read_count") or 0),
            }
        )
        result_rows.append({"uid_literature": uid_literature, "cite_key": resolved_cite_key, "title": _stringify(literature_row.get("title")), "standard_note_path": str(note_path), "structured_path": structured_path, "preprocess_status": parse_status})

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
        artifacts=[str(index_path)],
        recommendation="pass" if len(result_df) > 0 else "retry_current",
        score=max(40.0, 92.0 - len(failures) * 8.0),
        issues=failures,
        metadata={"workspace_root": str(workspace_root), "content_db": str(content_db)},
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        append_aok_log_event(
            event_type="A080_PREPROCESS_COMPLETED",
            project_root=workspace_root,
            handler_name="非综述候选与预处理编排",
            agent_names=["ar_A080_非综述候选与预处理编排事务智能体_v6"],
            skill_names=["ar_非综述候选文献视图构建_v5"],
            reasoning_summary="消费 literature_reading_state.pending_preprocess=1，并把成功条目推进到 pending_rough_read=1。",
            payload={"preprocessed_count": len(result_df), "seeded_from_legacy_queue": seeded_count, "failure_count": len(failures)},
        )
    except Exception:
        pass

    return [index_path, gate_path]
