"""A100 文献精解析资产化事务。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import append_aok_log_event, build_gate_review, knowledge_index_sync_from_note, knowledge_note_register, load_json_or_py, process_reference_citation
from autodokit.tools.bibliodb_sqlite import READING_QUEUE_COLUMNS, READING_QUEUE_STORAGE_TABLE, load_reading_queue_df, load_reading_state_df, upsert_reading_queue_rows, upsert_reading_state_rows
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, derive_literature_parse_state, resolve_content_db_config
from autodokit.tools.literature_translation_tools import run_literature_translation
from autodokit.tools.ocr.classic.pdf_parse_asset_manager import ensure_multimodal_parse_asset
from autodokit.tools.ocr.runtime.monkeyocr_manifest_runtime import (
    resolve_parse_runtime_settings,
    resolve_postprocess_settings,
    run_parse_manifest,
)
from autodokit.tools.ocr.classic.pdf_parse_asset_manager import ensure_pdf_text_fallback_asset
from autodokit.tools.ocr.classic.pdf_structured_data_tools import load_single_document_record
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.reading_state_tools import build_followup_candidate_state_row, build_retrieval_feedback_request, merge_retrieval_feedback_requests, should_route_back_to_a040
from autodokit.tools.affair_request_bus import dispatch_affair_request, register_a040_requests_from_feedback
from autodokit.tools.storage_backend import load_knowledge_tables, load_reference_tables, persist_knowledge_tables, persist_reference_tables


OUTPUT_INDEX = "a100_deep_parse_index.csv"
OUTPUT_GATE = "gate_review.json"
OUTPUT_RELATED_ITEMS_CSV = "related_literature_items.csv"
OUTPUT_RELATED_ITEMS_MD = "related_literature_items.md"


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


def _extract_reference_lines(text: str) -> List[str]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return []
    start_index = -1
    for index, line in enumerate(lines):
        lowered = line.lower().strip("# ")
        if lowered in {"references", "reference", "参考文献"}:
            start_index = index + 1
            break
    if start_index < 0:
        return []
    results: List[str] = []
    seen: set[str] = set()
    for line in lines[start_index:]:
        if line.startswith("#"):
            break
        if len(line) < 20 or line in seen:
            continue
        seen.add(line)
        results.append(line)
    return results[:12]


def _build_critical_note(*, title: str, cite_key: str, text: str, reading_objective: str, manual_guidance: str) -> str:
    normalized = " ".join(str(text or "").split())
    sample = normalized[:3500]
    fragments = [fragment.strip() for fragment in sample.replace("。", "。\n").splitlines() if fragment.strip()]
    bullets = [f"- {fragment}" for fragment in fragments[:8]] or ["- 未抽取到可用正文。"]
    return "\n".join(
        [
            f"# {title}",
            "",
            f"- cite_key: {cite_key}",
            f"- reading_objective: {reading_objective or '未指定'}",
            f"- manual_guidance: {manual_guidance or '未指定'}",
            "",
            "## 证据摘录",
            *bullets,
            "",
            "## 批判性研读问题",
            "- 这个结论的假设条件是什么？",
            "- 数据或模型是否存在局限？",
            "- 有没有相反案例或未覆盖场景？",
            "",
            "## 对当前课题的价值",
            "- 请在本节补充对当前研究问题的直接可用价值与边界。",
            "",
            "## 个人疑问与启发",
            "- 请在本节记录可回流检索的新关键词、新机制或新候选方向。",
            "",
        ]
    )


def _write_critical_related_items(output_dir: Path, frame: pd.DataFrame) -> list[Path]:
    snapshot_columns = [
        "uid_literature",
        "cite_key",
        "title",
        "deep_read_note_path",
        "structured_json",
        "discovered_candidate_count",
        "knowledge_uid",
        "asset_backend",
        "note_translation_status",
        "translated_note_path",
    ]
    available_columns = [column for column in snapshot_columns if column in frame.columns]
    snapshot_df = frame[available_columns].copy() if available_columns else pd.DataFrame()

    csv_path = output_dir / "a100_a105_related_literature_items.csv"
    md_path = output_dir / "a100_a105_related_literature_items.md"
    snapshot_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    label_map = {
        "uid_literature": "文献 UID",
        "cite_key": "题录键",
        "title": "标题",
        "deep_read_note_path": "标准笔记路径",
        "structured_json": "结构化 JSON",
        "discovered_candidate_count": "发现候选数",
        "knowledge_uid": "知识 UID",
        "asset_backend": "解析后端",
        "note_translation_status": "译文状态",
        "translated_note_path": "译文笔记路径",
    }
    lines = ["# A100-A105 相关文献条目", "", f"共 {len(snapshot_df)} 条。", ""]
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


def _run_critical_reading_merged(
    *,
    raw_cfg: Dict[str, Any],
    workspace_root: Path,
    output_dir: Path,
    content_db: Path,
    target_uid_set: set[str],
) -> tuple[List[Path], Dict[str, Any]]:
    """在 A100 内联执行原 A105 的标准笔记与回流逻辑。"""

    auto_dispatch_feedback_requests = bool(raw_cfg.get("auto_dispatch_feedback_requests_to_a040", True))
    allow_unparsed_critical_read = bool(raw_cfg.get("allow_unparsed_critical_read", False))
    state_df = load_reading_state_df(content_db, flag_filters={"deep_read_done": 0})
    if not state_df.empty:
        if target_uid_set:
            state_df = state_df[state_df["uid_literature"].astype(str).isin(target_uid_set)].reset_index(drop=True)
        if "deep_read_decision" in state_df.columns:
            allowed_decisions = ["parse_ready"]
            if allow_unparsed_critical_read:
                allowed_decisions.append("pdf_fallback_ready")
            state_df = state_df[state_df["deep_read_decision"].astype(str).isin(allowed_decisions)].reset_index(drop=True)

    existing_state_df = load_reading_state_df(content_db)
    existing_state_by_uid = {
        _stringify(row.get("uid_literature")): row.to_dict()
        for _, row in existing_state_df.fillna("").iterrows()
        if _stringify(row.get("uid_literature"))
    }
    literatures_df, attachments_df, _ = load_reference_tables(db_path=content_db)
    knowledge_index_df, knowledge_attachments_df, _ = load_knowledge_tables(db_path=content_db)

    result_rows: List[Dict[str, Any]] = []
    state_updates: List[Dict[str, Any]] = []
    retrieval_feedback_requests: List[Dict[str, Any]] = []
    failures: List[str] = []

    note_dir = workspace_root / "knowledge" / "standard_notes"
    note_dir.mkdir(parents=True, exist_ok=True)
    translation_policy = dict(raw_cfg.get("translation_policy") or {})

    for _, row in state_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        reading_objective = _stringify(row.get("reading_objective"))
        manual_guidance = _stringify(row.get("manual_guidance"))
        source_origin = _stringify(row.get("source_origin")) or "auto"
        deep_read_decision = _stringify(row.get("deep_read_decision"))
        is_unparsed_critical_read = deep_read_decision == "pdf_fallback_ready" and int(row.get("preprocessed") or 0) == 0

        upsert_reading_state_rows(
            content_db,
            [{
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "in_deep_read": 1,
                "deep_read_decision": "in_critical_read",
            }],
        )

        try:
            if deep_read_decision == "pdf_fallback_ready":
                parse_asset = ensure_pdf_text_fallback_asset(
                    content_db=content_db,
                    parse_level="non_review_deep",
                    uid_literature=uid_literature,
                    cite_key=cite_key,
                    source_stage="A100",
                    overwrite_existing=False,
                )
            else:
                parse_asset = ensure_multimodal_parse_asset(
                    content_db=content_db,
                    parse_level="non_review_deep",
                    uid_literature=uid_literature,
                    cite_key=cite_key,
                    source_stage="A100",
                    global_config_path=workspace_root / "config" / "config.json",
                    overwrite_existing=False,
                    model="auto",
                )

            structured_json = _stringify(parse_asset.get("normalized_structured_path"))
            document = load_single_document_record(
                uid=uid_literature,
                doc_id="",
                structured_json_path=structured_json,
                structured_dir="",
                content_db=str(content_db),
            )
            title = _stringify(document.get("title")) or cite_key
            full_text = _stringify(document.get("text"))
            note_path = note_dir / f"critical_reading_{_safe_file_stem(cite_key)}.md"
            note_info = knowledge_note_register(
                note_path=note_path,
                title=title,
                note_type="literature_standard_note",
                status="draft",
                tags=["aok/critical_read", "a100", "a105_merged"],
                aliases=[cite_key],
                evidence_uids=[uid_literature],
                uid_literature=uid_literature,
                cite_key=cite_key,
                body=_build_critical_note(
                    title=title,
                    cite_key=cite_key,
                    text=full_text,
                    reading_objective=reading_objective,
                    manual_guidance=manual_guidance,
                ),
            )
            knowledge_index_df, _ = knowledge_index_sync_from_note(knowledge_index_df, note_path, workspace_root=workspace_root)

            reference_lines = _extract_reference_lines(full_text)
            discovered_rows: List[Dict[str, Any]] = []
            short_loop_discovered_rows: List[Dict[str, Any]] = []
            literature_by_uid: Dict[str, Dict[str, Any]] = {
                _stringify(item.get("uid_literature")): item.to_dict()
                for _, item in literatures_df.fillna("").iterrows()
                if _stringify(item.get("uid_literature"))
            }
            for reference_text in reference_lines:
                try:
                    literatures_df, result = process_reference_citation(
                        literatures_df,
                        reference_text,
                        workspace_root=workspace_root,
                        global_config_path=workspace_root / "config" / "config.json",
                        source="placeholder_from_a100_critical_read",
                        print_to_stdout=False,
                    )
                except Exception:
                    continue
                target_uid = _stringify(result.get("matched_uid_literature"))
                target_cite_key = _stringify(result.get("matched_cite_key"))
                if target_uid and target_uid != uid_literature:
                    provisional_mapping_row = {
                        "matched_uid_literature": target_uid,
                        "matched_cite_key": target_cite_key,
                        "action": _stringify(result.get("action")),
                        "parse_failed": _stringify(result.get("parse_failed") or "0"),
                        "match_score": _stringify(result.get("match_score") or "0"),
                        "parse_failure_reason": _stringify(result.get("parse_failure_reason")),
                        "suspicious_mismatch": _stringify(result.get("suspicious_mismatch") or "0"),
                        "suspicious_merged": _stringify(result.get("suspicious_merged") or "0"),
                        "reference_text": reference_text,
                    }
                    decision = should_route_back_to_a040(
                        mapping_row=provisional_mapping_row,
                        target_state=existing_state_by_uid.get(target_uid),
                        target_literature_row=literature_by_uid.get(target_uid),
                    )
                    if decision.get("route_to_a040"):
                        retrieval_feedback_requests.append(
                            build_retrieval_feedback_request(
                                source_stage="A100",
                                source_task_uid=output_dir.name,
                                source_note_path=str(note_path),
                                source_uid_literature=uid_literature,
                                source_cite_key=cite_key,
                                reference_lines=[reference_text],
                                mapping_row=provisional_mapping_row,
                                retrieval_reason=_stringify(decision.get("reason")),
                                need_fulltext=True,
                                need_metadata_completion=True,
                            )
                        )
                        continue

                    candidate_row = build_followup_candidate_state_row(
                        uid_literature=target_uid,
                        cite_key=target_cite_key,
                        source_stage="A100",
                        source_uid_literature=uid_literature,
                        source_cite_key=cite_key,
                        recommended_reason=f"A100 从 {cite_key} 批判性研读参考文献发现新候选",
                        theme_relation="a100_reference_discovery",
                        existing_state=existing_state_by_uid.get(target_uid),
                    )
                    if candidate_row is None:
                        continue
                    discovered_rows.append(candidate_row)
                    short_loop_discovered_rows.append(candidate_row)
                    existing_state_by_uid[target_uid] = candidate_row

            deep_read_count = int(row.get("deep_read_count") or 0) + 1
            state_updates.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "source_origin": source_origin,
                    "reading_objective": reading_objective,
                    "manual_guidance": manual_guidance,
                    "in_deep_read": 0,
                    "deep_read_done": 1,
                    "deep_read_count": deep_read_count,
                    "deep_read_note_path": str(note_path),
                    "deep_read_decision": "completed",
                    "deep_read_reason": f"A100 已在同一事务内完成批判性研读与标准笔记。阅读目标={reading_objective or '未指定'}；提示语={manual_guidance or '未指定'}",
                    "deep_read_without_parse_done": 1 if is_unparsed_critical_read else int(row.get("deep_read_without_parse_done") or 0),
                    "require_reread_after_parse": 1 if is_unparsed_critical_read else int(row.get("require_reread_after_parse") or 0),
                }
            )
            state_updates.extend(discovered_rows)

            note_translation_result: Dict[str, Any] = {"status": "SKIP", "translated_note_path": "", "audit_path": ""}
            if translation_policy:
                try:
                    note_translation_result = run_literature_translation(
                        content_db=content_db,
                        translation_scope="standard_note",
                        translation_policy=translation_policy,
                        workspace_root=workspace_root,
                        uid_literature=uid_literature,
                        cite_key=cite_key,
                        source_note_path=note_path,
                        affair_name="A100",
                        config_path=workspace_root / "config" / "config.json",
                    )
                except Exception as translation_exc:
                    note_translation_result = {
                        "status": "FAIL",
                        "translated_note_path": "",
                        "audit_path": "",
                        "error": str(translation_exc),
                    }

            result_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "title": title,
                    "structured_json": structured_json,
                    "deep_read_note_path": str(note_path),
                    "discovered_candidate_count": len(short_loop_discovered_rows),
                    "knowledge_uid": _stringify(note_info.get("uid_knowledge")),
                    "asset_backend": _stringify(parse_asset.get("backend")),
                    "note_translation_status": str(note_translation_result.get("status") or "SKIP"),
                    "translated_note_path": str(note_translation_result.get("translated_note_path") or ""),
                    "note_translation_audit_path": str(note_translation_result.get("audit_path") or ""),
                }
            )
        except Exception as exc:
            failures.append(f"{cite_key}: 批判性研读失败: {exc}")
            state_updates.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "in_deep_read": 0,
                    "deep_read_done": 0,
                    "deep_read_decision": "critical_read_failed",
                    "deep_read_reason": str(exc),
                }
            )

    persist_reference_tables(literatures_df=literatures_df, attachments_df=attachments_df, db_path=content_db)
    persist_knowledge_tables(index_df=knowledge_index_df, attachments_df=knowledge_attachments_df, db_path=content_db)
    if state_updates:
        upsert_reading_state_rows(content_db, state_updates)

    result_df = pd.DataFrame(result_rows)
    index_path = output_dir / "a100_a105_critical_reading_index.csv"
    result_df.to_csv(index_path, index=False, encoding="utf-8-sig")
    related_item_paths = _write_critical_related_items(output_dir, result_df)
    merged_feedback_requests = merge_retrieval_feedback_requests(retrieval_feedback_requests)
    need_download_feedback = any(bool(item.get("need_fulltext", False)) for item in merged_feedback_requests)
    registered_feedback_requests: List[Dict[str, Any]] = []
    dispatched_feedback_requests: List[Dict[str, Any]] = []
    dispatch_failures: List[str] = []
    if merged_feedback_requests:
        registered_feedback_requests = register_a040_requests_from_feedback(
            workspace_root=workspace_root,
            feedback_requests=merged_feedback_requests,
            source_node="A100",
            priority="高" if need_download_feedback else "中",
            creator_type="affair",
            creator_id="A100_文献研读与正式知识回写",
            attribute_vector={
                "source_stage": "A100",
                "need_download_feedback": need_download_feedback,
                "request_count": len(merged_feedback_requests),
            },
        )
        if auto_dispatch_feedback_requests:
            for record in registered_feedback_requests:
                request_uid = _stringify(record.get("request_uid") or record.get("uid_请求"))
                if not request_uid:
                    continue
                try:
                    dispatched_feedback_requests.append(
                        dispatch_affair_request(
                            workspace_root=workspace_root,
                            request_uid=request_uid,
                            raise_on_error=True,
                        )
                    )
                except Exception as exc:
                    dispatch_failures.append(f"{request_uid}: {exc}")

    feedback_path = output_dir / "retrieval_feedback_requests_A100.json"
    feedback_summary_path = output_dir / "retrieval_feedback_summary_A100.json"
    affair_request_result_path = output_dir / "affair_request_dispatch_A100.json"
    feedback_summary = {
        "task_uid": output_dir.name,
        "source_stage": "A100",
        "request_count": len(merged_feedback_requests),
        "critical_read_count": len(result_rows),
        "need_retrieval_feedback": len(merged_feedback_requests) > 0,
        "need_download_feedback": need_download_feedback,
        "registered_request_count": len(registered_feedback_requests),
        "auto_dispatch_feedback_requests": auto_dispatch_feedback_requests,
        "dispatched_request_count": len(dispatched_feedback_requests),
        "dispatch_failed_count": len(dispatch_failures),
    }
    feedback_path.write_text(json.dumps(merged_feedback_requests, ensure_ascii=False, indent=2), encoding="utf-8")
    feedback_summary_path.write_text(json.dumps(feedback_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    affair_request_result_path.write_text(
        json.dumps(
            {
                "registered_requests": registered_feedback_requests,
                "dispatched_results": dispatched_feedback_requests,
                "dispatch_failures": dispatch_failures,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    gate_review = build_gate_review(
        node_uid="A100",
        node_name="文献精读链整合事务",
        summary=f"完成批判性研读 {len(result_rows)} 篇；失败 {len(failures)} 篇；在 A100 内联收口 A105。",
        checks=[
            {"name": "critical_read_count", "value": len(result_rows)},
            {"name": "failure_count", "value": len(failures)},
            {"name": "retrieval_feedback_request_count", "value": len(merged_feedback_requests)},
            {"name": "registered_feedback_request_count", "value": len(registered_feedback_requests)},
            {"name": "dispatch_failure_count", "value": len(dispatch_failures)},
        ],
        artifacts=[str(index_path), *[str(path) for path in related_item_paths], str(feedback_path), str(feedback_summary_path), str(affair_request_result_path)],
        recommendation="pass_next" if result_rows else "retry_current",
        score=max(45.0, 92.0 - len(failures) * 10.0),
        issues=[*failures, *dispatch_failures],
    )
    gate_path = output_dir / "a100_a105_gate_review.json"
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    return [index_path, *related_item_paths, feedback_path, feedback_summary_path, affair_request_result_path, gate_path], {
        "critical_read_count": len(result_rows),
        "critical_failures": [*failures, *dispatch_failures],
    }


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


def _has_parse_summary(row: Dict[str, Any]) -> bool:
    parse_state = derive_literature_parse_state(
        parse_state=row.get("parse_state") or row.get("解析状态"),
        current_parse_status=row.get("current_parse_status"),
        structured_status=row.get("structured_status"),
        has_parse_result=bool(_stringify(row.get("current_parse_path")) or _stringify(row.get("structured_abs_path"))),
    )
    if parse_state == "已完成" and _stringify(row.get("current_parse_path")):
        return True
    structured_status = _stringify(row.get("structured_status")).lower()
    if structured_status in {"ready", "succeeded", "success", "completed", "ok"} and _stringify(row.get("structured_abs_path")):
        return True
    return False


def _load_deep_parse_pool(
    content_db: Path,
    *,
    literature_df: pd.DataFrame,
    state_df: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    queue_df = load_reading_queue_df(
        content_db,
        stage="A100",
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
        pd.to_numeric(state_df.get("pending_deep_read", 0), errors="coerce").fillna(0).astype(int) == 1
    ].copy()
    if legacy_df.empty:
        return pd.DataFrame(), "queue"
    return legacy_df.fillna(""), "reading_state"


def _consume_current_stage_queue_rows(content_db: Path, *, stage: str, completed_df: pd.DataFrame) -> int:
    if completed_df is None or completed_df.empty:
        return 0
    identities: list[tuple[str, str]] = []
    for _, row in completed_df.fillna("").iterrows():
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
    now_iso = datetime.now().isoformat(timespec="seconds")
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
        "source_origin",
        "parse_status",
        "structured_json",
        "asset_dir",
        "postprocess_markdown_path",
        "parse_translation_status",
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
        "source_origin": "来源口径",
        "parse_status": "解析状态",
        "structured_json": "结构化 JSON",
        "asset_dir": "解析资产目录",
        "postprocess_markdown_path": "后处理 Markdown",
        "parse_translation_status": "译文状态",
    }
    lines = ["# A100 相关文献条目", "", f"共 {len(snapshot_df)} 条。", ""]
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


@affair_auto_git_commit("A100")
def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    legacy_output_dir = _resolve_output_dir(config_path, raw_cfg)
    output_dir = _build_task_instance_dir(workspace_root, "A100")
    content_db, _ = resolve_content_db_config(
        raw_cfg,
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None

    literature_df, _, _ = load_reference_tables(db_path=content_db)
    existing_state_df = load_reading_state_df(content_db)
    state_df, input_mode = _load_deep_parse_pool(
        content_db,
        literature_df=literature_df,
        state_df=existing_state_df,
    )
    max_items = int(raw_cfg.get("max_items") or 3)
    if max_items > 0:
        state_df = state_df.head(max_items).reset_index(drop=True)
    allow_pdf_text_fallback_on_parse_failure = bool(raw_cfg.get("allow_pdf_text_fallback_on_parse_failure", True))
    allow_unparsed_deep_read_bypass = bool(raw_cfg.get("allow_unparsed_deep_read_bypass", False))
    translation_policy = dict(raw_cfg.get("translation_policy") or {})
    global_config_path = workspace_root / "config" / "config.json"
    parse_runtime = resolve_parse_runtime_settings(raw_cfg, workspace_root=workspace_root, global_config_path=global_config_path)
    postprocess_settings = resolve_postprocess_settings(raw_cfg, workspace_root=workspace_root)

    result_rows: List[Dict[str, Any]] = []
    state_updates: List[Dict[str, Any]] = []
    failures: List[str] = []
    postprocess_success_count = 0

    if not state_df.empty:
        upsert_reading_state_rows(
            content_db,
            [
                {
                    "uid_literature": _stringify(row.get("uid_literature")),
                    "cite_key": _stringify(row.get("cite_key")) or _stringify(row.get("uid_literature")),
                    "pending_deep_read": 0,
                    "in_deep_read": 1,
                    "deep_read_done": int(row.get("deep_read_done") or 0),
                    "deep_read_decision": "in_parse",
                }
                for _, row in state_df.fillna("").iterrows()
                if _stringify(row.get("uid_literature"))
            ],
        )

    bypass_df = pd.DataFrame()
    parse_df = state_df.copy()
    if allow_unparsed_deep_read_bypass and not state_df.empty:
        bypass_mask = (
            ~state_df.apply(lambda row: _has_parse_summary(row.to_dict()), axis=1)
        ) & (
            pd.to_numeric(state_df.get("allow_unparsed_read", 0), errors="coerce").fillna(0).astype(int) == 1
        )
        bypass_df = state_df.loc[bypass_mask].copy()
        parse_df = state_df.loc[~bypass_mask].copy()

    if not bypass_df.empty:
        for _, row in bypass_df.fillna("").iterrows():
            uid_literature = _stringify(row.get("uid_literature"))
            cite_key = _stringify(row.get("cite_key")) or uid_literature
            source_origin = _stringify(row.get("source_origin")) or "auto"
            state_updates.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "source_origin": source_origin,
                    "pending_deep_read": 0,
                    "in_deep_read": 0,
                    "deep_read_done": 0,
                    "deep_read_decision": "pdf_fallback_ready",
                    "deep_read_reason": "A100 在未解析先读开关下跳过 MonkeyOCR，按未解析旁路移交 A105。",
                    "deep_read_without_parse_done": 1,
                    "require_reread_after_parse": 1,
                    "unparsed_read_in_effect": 1,
                }
            )
            result_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "structured_json": "",
                    "asset_dir": "",
                    "parse_status": "unparsed_bypass_ready",
                    "postprocess_enabled": 0,
                    "postprocess_ok": 0,
                    "postprocess_removed_noise_lines": 0,
                    "postprocess_llm_basic_cleanup_status": "skipped_unparsed_bypass",
                    "postprocess_llm_structure_status": "skipped_unparsed_bypass",
                    "postprocess_contamination_removed_block_count": 0,
                    "postprocess_markdown_path": "",
                    "postprocess_audit_path": "",
                    "parse_translation_status": "SKIP",
                    "parse_translation_markdown_path": "",
                    "parse_translation_audit_path": "",
                }
            )

    manifest_result = run_parse_manifest(
        content_db=content_db,
        source_df=parse_df,
        output_dir=output_dir,
        source_stage="A100",
        upstream_stage="A080",
        downstream_stage="A105",
        parse_level="non_review_deep",
        literature_scope="non_review",
        runtime_settings=parse_runtime,
        postprocess_settings=postprocess_settings,
        global_config_path=global_config_path,
        overwrite_existing=False,
        max_items=max_items,
    )
    manifest_df = manifest_result["manifest_df"]
    failures.extend(manifest_result["failures"])

    for _, row in manifest_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        source_origin = _stringify(row.get("source_origin")) or "auto"
        manifest_status = _stringify(row.get("manifest_status"))
        failure_reason = _stringify(row.get("failure_reason"))
        try:
            if manifest_status == "failed":
                raise RuntimeError(failure_reason or "parse_failed")

            structured_json = _stringify(row.get("normalized_structured_path"))
            if int(row.get("postprocess_ok") or 0):
                postprocess_success_count += 1
            rough_done_without_parse = int(row.get("rough_read_without_parse_done") or 0) == 1
            deep_done_without_parse = int(row.get("deep_read_without_parse_done") or 0) == 1
            require_reread = int(row.get("require_reread_after_parse") or 0) == 1
            should_force_rerough = require_reread and rough_done_without_parse
            should_force_redeep = require_reread and deep_done_without_parse
            state_updates.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "source_origin": source_origin,
                    "pending_rough_read": 1 if should_force_rerough else int(row.get("pending_rough_read") or 0),
                    "rough_read_done": 0 if should_force_rerough else int(row.get("rough_read_done") or 0),
                    "pending_deep_read": 0,
                    "in_deep_read": 0,
                    "deep_read_done": 0 if should_force_redeep else int(row.get("deep_read_done") or 0),
                    "deep_read_decision": "parse_ready",
                    "deep_read_reason": (
                        "A100 已完成 non_review_deep 解析资产准备，"
                        "等待 A105 执行批判性研读与标准笔记写回。"
                    ),
                    "allow_unparsed_read": 0,
                    "unparsed_read_in_effect": 0,
                    "require_reread_after_parse": 0,
                    "rough_read_without_parse_done": int(row.get("rough_read_without_parse_done") or 0),
                    "deep_read_without_parse_done": int(row.get("deep_read_without_parse_done") or 0),
                }
            )
            result_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "title": _stringify(row.get("title")) or cite_key,
                    "source_origin": source_origin,
                    "structured_json": structured_json,
                    "asset_dir": _stringify(row.get("asset_dir")),
                    "parse_status": "ready",
                    "postprocess_enabled": int(postprocess_settings.get("enabled", True)),
                    "postprocess_ok": int(row.get("postprocess_ok") or 0),
                    "postprocess_removed_noise_lines": 0,
                    "postprocess_llm_basic_cleanup_status": _stringify(row.get("postprocess_llm_basic_cleanup_status")),
                    "postprocess_llm_structure_status": _stringify(row.get("postprocess_llm_structure_status")),
                    "postprocess_contamination_removed_block_count": int(row.get("postprocess_contamination_removed_block_count") or 0),
                    "postprocess_markdown_path": _stringify(row.get("reconstructed_markdown_path")),
                    "postprocess_audit_path": "",
                    "parse_translation_status": "SKIP",
                    "parse_translation_markdown_path": "",
                    "parse_translation_audit_path": "",
                }
            )

            if translation_policy:
                try:
                    translation_result = run_literature_translation(
                        content_db=content_db,
                        translation_scope="parse_text",
                        translation_policy=translation_policy,
                        workspace_root=workspace_root,
                        uid_literature=uid_literature,
                        cite_key=cite_key,
                        parse_level="non_review_deep",
                        affair_name="A100",
                        config_path=workspace_root / "config" / "config.json",
                    )
                    result_rows[-1]["parse_translation_status"] = str(translation_result.get("status") or "SKIP")
                    result_rows[-1]["parse_translation_markdown_path"] = str(translation_result.get("translated_markdown_path") or "")
                    result_rows[-1]["parse_translation_audit_path"] = str(translation_result.get("audit_path") or "")
                except Exception as translation_exc:
                    result_rows[-1]["parse_translation_status"] = "FAIL"
                    result_rows[-1]["parse_translation_markdown_path"] = ""
                    result_rows[-1]["parse_translation_audit_path"] = ""
                    failures.append(f"{cite_key}: 解析译文生成失败: {translation_exc}")
        except Exception as exc:
            fallback_asset: Dict[str, Any] = {}
            fallback_exc: Exception | None = None
            if allow_pdf_text_fallback_on_parse_failure:
                try:
                    fallback_asset = ensure_pdf_text_fallback_asset(
                        content_db=content_db,
                        parse_level="non_review_deep",
                        uid_literature=uid_literature,
                        cite_key=cite_key,
                        source_stage="A100",
                        overwrite_existing=False,
                    )
                except Exception as fallback_error:
                    fallback_exc = fallback_error

            if fallback_asset:
                state_updates.append(
                    {
                        "uid_literature": uid_literature,
                        "cite_key": cite_key,
                        "source_origin": source_origin,
                        "pending_deep_read": 0,
                        "in_deep_read": 0,
                        "deep_read_done": 0,
                        "deep_read_decision": "pdf_fallback_ready",
                        "deep_read_reason": f"A100 多模态解析失败，已切换为原文 PDF 直读旁路。原始错误：{exc}",
                    }
                )
                result_rows.append(
                    {
                        "uid_literature": uid_literature,
                        "cite_key": cite_key,
                        "title": _stringify(row.get("title")) or cite_key,
                        "source_origin": source_origin,
                        "structured_json": _stringify(fallback_asset.get("normalized_structured_path")),
                        "asset_dir": _stringify(fallback_asset.get("asset_dir")),
                        "parse_status": "fallback_ready",
                        "postprocess_enabled": 0,
                        "postprocess_ok": 0,
                        "postprocess_removed_noise_lines": 0,
                        "postprocess_llm_basic_cleanup_status": "skipped_pdf_text_fallback",
                        "postprocess_llm_structure_status": "skipped_pdf_text_fallback",
                        "postprocess_contamination_removed_block_count": 0,
                        "postprocess_markdown_path": _stringify(fallback_asset.get("reconstructed_markdown_path")),
                        "postprocess_audit_path": "",
                    }
                )
                failures.append(f"{cite_key}: 多模态解析失败，已降级为原文 PDF 直读旁路: {exc}")
            else:
                reason = str(exc) if fallback_exc is None else f"{exc}; fallback 失败: {fallback_exc}"
                failures.append(f"{cite_key}: 深读失败: {reason}")
                state_updates.append(
                    {
                        "uid_literature": uid_literature,
                        "cite_key": cite_key,
                        "pending_deep_read": 1,
                        "in_deep_read": 0,
                        "deep_read_done": 0,
                        "deep_read_decision": "parse_failed",
                        "deep_read_reason": reason,
                    }
                )

    if state_updates:
        upsert_reading_state_rows(content_db, state_updates)
    completed_df = manifest_df.loc[
        manifest_df.get("manifest_status", pd.Series(dtype=str)).astype(str).str.lower().isin(["succeeded", "skipped"])
    ].copy() if not manifest_df.empty else pd.DataFrame()
    consumed_a100_queue_count = _consume_current_stage_queue_rows(content_db, stage="A100", completed_df=completed_df)

    result_df = pd.DataFrame(result_rows)
    index_path = output_dir / OUTPUT_INDEX
    result_df.to_csv(index_path, index=False, encoding="utf-8-sig")
    related_item_paths = _write_related_literature_items(output_dir, result_df)

    gate_review = build_gate_review(
        node_uid="A100",
        node_name="文献精解析资产化",
        summary=(
            f"完成 deep parse 准备 {len(result_rows)} 篇（mode={input_mode}）；"
            f"后处理成功 {postprocess_success_count} 篇；失败 {len(failures)} 篇；"
            f"消费 A100 队列 {consumed_a100_queue_count} 条。"
        ),
        checks=[
            {"name": "deep_parse_ready_count", "value": len(result_rows)},
            {"name": "input_mode", "value": input_mode},
            {"name": "postprocess_success_count", "value": postprocess_success_count},
            {"name": "failure_count", "value": len(failures)},
            {"name": "consumed_a100_queue_count", "value": consumed_a100_queue_count},
        ],
        artifacts=[str(index_path), *[str(path) for path in related_item_paths], str(manifest_result["manifest_path"]), str(manifest_result["management_table_path"]), str(manifest_result["handoff_path"])],
        recommendation="pass" if result_rows else "retry_current",
        score=max(45.0, 93.0 - len(failures) * 10.0),
        issues=failures,
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "manifest_path": str(manifest_result["manifest_path"]),
            "management_table_path": str(manifest_result["management_table_path"]),
            "handoff_path": str(manifest_result["handoff_path"]),
            "batch_report_path": str(manifest_result["batch_report_path"]),
            "parse_runtime": parse_runtime,
            "legacy_postprocess_enabled": bool(postprocess_settings.get("enabled", True)),
            "postprocess_rewrite_structured": bool(postprocess_settings.get("rewrite_structured", True)),
            "postprocess_rewrite_markdown": bool(postprocess_settings.get("rewrite_markdown", True)),
            "postprocess_keep_page_markers": bool(postprocess_settings.get("keep_page_markers", False)),
            "enable_llm_basic_cleanup": bool(postprocess_settings.get("enable_llm_basic_cleanup", True)),
            "basic_cleanup_llm_model": postprocess_settings.get("basic_cleanup_llm_model"),
            "basic_cleanup_llm_sdk_backend": postprocess_settings.get("basic_cleanup_llm_sdk_backend"),
            "basic_cleanup_llm_region": postprocess_settings.get("basic_cleanup_llm_region"),
            "enable_llm_structure_resolution": bool(postprocess_settings.get("enable_llm_structure_resolution", True)),
            "structure_llm_model": postprocess_settings.get("structure_llm_model"),
            "structure_llm_sdk_backend": postprocess_settings.get("structure_llm_sdk_backend"),
            "structure_llm_region": postprocess_settings.get("structure_llm_region"),
            "enable_llm_contamination_filter": bool(postprocess_settings.get("enable_llm_contamination_filter", True)),
            "contamination_llm_model": postprocess_settings.get("contamination_llm_model"),
            "contamination_llm_sdk_backend": postprocess_settings.get("contamination_llm_sdk_backend"),
            "contamination_llm_region": postprocess_settings.get("contamination_llm_region"),
            "allow_pdf_text_fallback_on_parse_failure": allow_pdf_text_fallback_on_parse_failure,
            "allow_unparsed_deep_read_bypass": allow_unparsed_deep_read_bypass,
            "input_mode": input_mode,
            "consumed_a100_queue_count": consumed_a100_queue_count,
        },
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    if legacy_output_dir != output_dir:
        legacy_output_dir.mkdir(parents=True, exist_ok=True)
        for artifact_path in [index_path, *related_item_paths, gate_path]:
            legacy_target = legacy_output_dir / artifact_path.name
            legacy_target.write_text(artifact_path.read_text(encoding="utf-8"), encoding="utf-8")

    try:
        append_aok_log_event(
            event_type="A100_DEEP_READING_COMPLETED",
            project_root=workspace_root,
            affair_code="A100",
            handler_name="文献精解析资产化",
            agent_names=["ar_A100_文献精解析资产化事务智能体_v7"],
            skill_names=[],
            reasoning_summary="优先消费 A100 正式阶段队列，并按文献主表 current_parse/结构化摘要决定深度解析与旁路准备。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=[str(index_path), *[str(path) for path in related_item_paths], str(manifest_result["manifest_path"]), str(manifest_result["management_table_path"]), str(manifest_result["handoff_path"])],
        )
    except Exception:
        pass

    current_batch_uid_set = {
        _stringify(row.get("uid_literature"))
        for row in result_rows
        if _stringify(row.get("uid_literature"))
    }
    merged_outputs, merged_summary = _run_critical_reading_merged(
        raw_cfg=raw_cfg,
        workspace_root=workspace_root,
        output_dir=output_dir,
        content_db=content_db,
        target_uid_set=current_batch_uid_set,
    )
    return [index_path, *related_item_paths, gate_path, manifest_result["manifest_path"], manifest_result["management_table_path"], manifest_result["batch_report_path"], manifest_result["handoff_path"], *merged_outputs]




