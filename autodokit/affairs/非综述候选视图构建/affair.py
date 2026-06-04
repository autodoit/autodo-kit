"""A150 普通文献泛读事务。

A150 优先消费正式 `A150` 阶段队列，并结合 `文献主表.current_parse_*`
与结构化摘要字段完成统一预处理；粗读候选筛选与批次汇总已剥离到 A160。
旧 reading_state 仅保留兼容回写。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pandas as pd

from autodokit.tools import (
    append_aok_log_event,
    build_gate_review,
    build_reference_quality_summary,
    extract_reference_lines_from_attachment,
    knowledge_index_sync_from_note,
    knowledge_note_register,
    load_json_or_py,
    process_reference_citation,
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
    save_dataframe_table,
    upsert_reading_queue_rows,
    upsert_reading_state_rows,
)
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.ocr.runtime.monkeyocr_manifest_runtime import (
    resolve_parse_runtime_settings,
    resolve_postprocess_settings,
    run_parse_manifest,
)
from autodokit.tools.ocr.classic.pdf_structured_data_tools import extract_reference_lines_from_structured_data, load_structured_data
from autodokit.tools.reading_state_tools import (
    ANALYSIS_NOTE_SPECS,
    append_markdown_section,
    build_followup_candidate_state_row,
    build_retrieval_feedback_request,
    merge_retrieval_feedback_requests,
    resolve_analysis_note_paths,
    should_route_back_to_a040,
)
from autodokit.tools.affair_request_bus import dispatch_affair_request, register_a040_requests_from_feedback
from autodokit.tools.storage_backend import (
    load_knowledge_tables,
    load_reference_tables,
    persist_knowledge_tables,
    persist_reference_tables,
)


OUTPUT_INDEX = "a080_preprocess_index.csv"
OUTPUT_GATE = "gate_review.json"
OUTPUT_RELATED_ITEMS_CSV = "related_literature_items.csv"
OUTPUT_RELATED_ITEMS_MD = "related_literature_items.md"
NOTE_DIR_NAME = "rough_read_notes"
SENTENCE_GROUP_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "research_problem": ("本文", "文章", "研究", "探究", "检验", "分析"),
    "method": ("基于", "模型", "样本", "数据", "方法", "识别", "实证"),
    "findings": ("发现", "表明", "影响", "风险", "系统性风险", "房价", "信贷", "银行"),
}


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _safe_file_stem(text: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", _stringify(text))
    value = re.sub(r"\s+", " ", value).strip()
    return value or "untitled"


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig")


def _extract_reference_source_from_structured(row: Dict[str, Any]) -> Dict[str, Any] | None:
    structured_candidates = [
        _stringify(row.get("normalized_structured_path")),
        _stringify(row.get("current_parse_path")),
        _stringify(row.get("structured_abs_path")),
    ]
    markdown_candidates = [
        _stringify(row.get("reconstructed_markdown_path")),
        _stringify(row.get("current_parse_markdown_path")),
    ]
    for candidate in structured_candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_absolute() or not path.exists() or not path.is_file():
            continue
        try:
            structured_data = load_structured_data(path)
            extract_result = extract_reference_lines_from_structured_data(structured_data)
            text_payload = structured_data.get("text") if isinstance(structured_data.get("text"), dict) else {}
            full_text = _stringify(text_payload.get("full_text"))
            if not full_text:
                for markdown_candidate in markdown_candidates:
                    if not markdown_candidate:
                        continue
                    markdown_path = Path(markdown_candidate)
                    if markdown_path.is_absolute() and markdown_path.exists() and markdown_path.is_file():
                        full_text = _read_text_file(markdown_path)
                        break
            return {
                "attachment_path": str(path),
                "attachment_type": "structured",
                "extract_status": "ok",
                "extract_method": "structured_summary",
                "reference_lines": list(extract_result.get("reference_lines") or []),
                "reference_line_details": list(extract_result.get("reference_line_details") or []),
                "full_text": full_text,
                "pending_reason": "",
            }
        except Exception:
            continue
    return None


def _normalize_full_text(text: str) -> str:
    normalized = str(text or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"(?<=[A-Za-z])-\n(?=[A-Za-z])", "", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", normalized)
    normalized = re.sub(r"\n+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _split_sentences(text: str) -> List[Dict[str, Any]]:
    normalized = _normalize_full_text(text)
    if not normalized:
        return []
    parts = re.split(r"(?<=[。！？；!?;])\s+", normalized)
    sentences: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for part in parts:
        sentence = re.sub(r"\s+", " ", part.strip(" \t\n-•"))
        if len(sentence) < 18:
            continue
        if sentence in seen:
            continue
        seen.add(sentence)
        sentences.append({"index": len(sentences) + 1, "sentence": sentence})
    return sentences


def _score_sentence(sentence_obj: Dict[str, Any], keywords: Iterable[str]) -> float:
    sentence = _stringify(sentence_obj.get("sentence"))
    lowered = sentence.lower()
    score = max(0.0, 120.0 - float(sentence_obj.get("index") or 0))
    for keyword in keywords:
        token = _stringify(keyword)
        if token and token.lower() in lowered:
            score += 24.0
    if any(noise in sentence for noise in ("收稿日期", "基金项目", "作者简介", "关键词")):
        score -= 80.0
    return score


def _pick_sentences(sentences: Sequence[Dict[str, Any]], keywords: Iterable[str], limit: int) -> List[Dict[str, Any]]:
    scored = sorted(
        ((_score_sentence(item, keywords), item) for item in sentences),
        key=lambda pair: (pair[0], -int(pair[1].get("index") or 0)),
        reverse=True,
    )
    chosen: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for score, item in scored:
        sentence = _stringify(item.get("sentence"))
        if score <= 0 or sentence in seen:
            continue
        seen.add(sentence)
        chosen.append(item)
        if len(chosen) >= limit:
            break
    return chosen or list(sentences[:limit])


def _sentence_line(cite_key: str, sentence_obj: Dict[str, Any]) -> str:
    sentence = _stringify(sentence_obj.get("sentence"))
    index = _stringify(sentence_obj.get("index")) or "?"
    return f"- {sentence}（cite_key: {cite_key}；句序: {index}；原文: {sentence}）"


def _register_note(
    knowledge_index: pd.DataFrame,
    note_path: Path,
    title: str,
    body: str,
    workspace_root: Path,
    *,
    stage_code: str,
    uid_literature: str = "",
    cite_key: str = "",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    note_info = knowledge_note_register(
        note_path=note_path,
        title=title,
        note_type="knowledge_note",
        status="draft",
        tags=["aok/rough_read", stage_code.lower()],
        aliases=[title],
        evidence_uids=[title],
        uid_literature=uid_literature,
        cite_key=cite_key,
        body=body,
    )
    updated_index, _ = knowledge_index_sync_from_note(knowledge_index, note_path, workspace_root=workspace_root)
    return updated_index, note_info


def _light_patch_analysis_notes(note_paths: Dict[str, Path], *, cite_key: str, title: str, problem_lines: List[str], method_lines: List[str], finding_lines: List[str]) -> None:
    lines_map = {
        "trajectory": [f"- {cite_key}《{title}》：补充进入当前研究脉络的相关性判断。", *problem_lines[:1]],
        "core_findings": [f"- {cite_key}《{title}》：{finding_lines[0] if finding_lines else '形成初步核心发现占位。'}"],
        "controversies": [f"- {cite_key}《{title}》：当前仅形成轻量争议占位，待 A170 正式修订。"],
        "future_directions": [f"- {cite_key}《{title}》：建议结合深读判断未来研究推进方向。"],
        "framework": [f"- {cite_key}《{title}》：方法/变量线索：{method_lines[0] if method_lines else '待补充'}"],
    }
    for key, spec in ANALYSIS_NOTE_SPECS.items():
        append_markdown_section(note_paths[key], spec["title"], lines_map.get(key, []))


def _build_discovered_rows_from_mappings(
    *,
    item_mapping_rows: Sequence[Dict[str, Any]],
    uid_literature: str,
    cite_key: str,
    source_stage: str,
    existing_state_by_uid: Dict[str, Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    if existing_state_by_uid is None:
        existing_state_by_uid = {}
    discovered_rows: List[Dict[str, Any]] = []
    seen_targets: set[tuple[str, str]] = set()
    for mapping_row in item_mapping_rows:
        target_uid = _stringify(mapping_row.get("matched_uid_literature"))
        target_cite_key = _stringify(mapping_row.get("matched_cite_key"))
        if not target_uid or target_uid == uid_literature:
            continue
        identity = (target_uid, target_cite_key)
        if identity in seen_targets:
            continue
        seen_targets.add(identity)
        candidate_row = build_followup_candidate_state_row(
            uid_literature=target_uid,
            cite_key=target_cite_key,
            source_stage=source_stage,
            source_uid_literature=uid_literature,
            source_cite_key=cite_key,
            recommended_reason=f"{source_stage} 从 {cite_key} 参考文献发现候选",
            theme_relation=f"{source_stage.lower()}_reference_discovery",
            existing_state=existing_state_by_uid.get(target_uid),
        )
        if candidate_row is None:
            continue
        discovered_rows.append(candidate_row)
        existing_state_by_uid[target_uid] = candidate_row
    return discovered_rows


def _build_followup_queue_rows(
    state_df: pd.DataFrame,
    *,
    stage: str,
    source_affair: str,
    preferred_next_stage: str,
    reason_fallback: str,
    theme_relation_fallback: str,
    bucket: str,
    scope_key: str,
) -> List[Dict[str, Any]]:
    queue_rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for _, row in state_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        identity = (uid_literature, cite_key)
        if identity in seen or not uid_literature:
            continue
        if int(row.get("deep_read_done") or 0) == 1:
            continue
        seen.add(identity)
        queue_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "stage": stage,
                "source_affair": source_affair,
                "queue_status": "queued",
                "priority": row.get("priority") or 80,
                "bucket": bucket,
                "preferred_next_stage": preferred_next_stage,
                "recommended_reason": _stringify(row.get("rough_read_reason")) or reason_fallback,
                "theme_relation": _stringify(row.get("theme_relation")) or theme_relation_fallback,
                "source_round": source_affair.lower(),
                "scope_key": scope_key,
                "is_current": 1,
            }
        )
    return queue_rows


def _build_a095_queue_rows(state_df: pd.DataFrame) -> List[Dict[str, Any]]:
    return _build_followup_queue_rows(
        state_df,
        stage="A160",
        source_affair="A150",
        preferred_next_stage="A170",
        reason_fallback="A150 普通文献泛读完成预处理，进入 A160 普通文献研读候选视图构建",
        theme_relation_fallback="a080_to_a095",
        bucket="non_review_rough_read",
        scope_key="a080_to_a095",
    )


def _build_a100_queue_rows(state_df: pd.DataFrame, *, source_affair: str = "A160") -> List[Dict[str, Any]]:
    return _build_followup_queue_rows(
        state_df,
        stage="A170",
        source_affair=source_affair,
        preferred_next_stage="A170",
        reason_fallback=f"{source_affair} 完成普通文献研读候选筛选与批次汇总，进入 A170 文献批判性研读",
        theme_relation_fallback=f"{source_affair.lower()}_to_a100",
        bucket="non_review_batch_summary",
        scope_key=f"{source_affair.lower()}_to_a100",
    )


def _run_rough_read_and_batch_summary(
    *,
    raw_cfg: Dict[str, Any],
    workspace_root: Path,
    output_dir: Path,
    content_db: Path,
    literature_table: pd.DataFrame,
    attachment_table: pd.DataFrame,
    ready_df: pd.DataFrame,
    source_stage: str,
    output_prefix: str,
) -> tuple[List[Path], Dict[str, Any]]:
    """执行普通阅读链的粗读与批次汇总逻辑。"""

    auto_dispatch_feedback_requests = bool(raw_cfg.get("auto_dispatch_feedback_requests_to_a040", True))
    knowledge_index, knowledge_attachments, _ = load_knowledge_tables(db_path=content_db)
    existing_state_df = load_reading_state_df(content_db)
    existing_state_by_uid = {
        _stringify(row.get("uid_literature")): row.to_dict()
        for _, row in existing_state_df.fillna("").iterrows()
        if _stringify(row.get("uid_literature"))
    }
    analysis_note_paths = resolve_analysis_note_paths(workspace_root, raw_cfg)
    note_dir = workspace_root / "knowledge" / "audits" / NOTE_DIR_NAME
    note_dir.mkdir(parents=True, exist_ok=True)

    index_rows: List[Dict[str, Any]] = []
    mapping_rows: List[Dict[str, Any]] = []
    retrieval_feedback_requests: List[Dict[str, Any]] = []
    state_rows: List[Dict[str, Any]] = []
    written_paths: List[Path] = []
    missing_items: List[str] = []
    max_references_per_item = int(raw_cfg.get("max_references_per_item") or 12)

    for _, row in ready_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        manual_guidance = _stringify(row.get("manual_guidance"))
        reading_objective = _stringify(row.get("reading_objective"))
        source_origin = _stringify(row.get("source_origin")) or "auto"
        upsert_reading_state_rows(
            content_db,
            [{
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "pending_rough_read": 0,
                "in_rough_read": 1,
                "rough_read_done": 0,
            }],
        )

        attachment_rows = attachment_table[attachment_table.get("uid_literature", pd.Series(dtype=str)).astype(str) == uid_literature].copy()
        if not attachment_rows.empty:
            attachment_rows = attachment_rows.sort_values(by=["is_primary", "attachment_name"], ascending=[False, True])
        attachment_value = ""
        if not attachment_rows.empty:
            first_attachment = attachment_rows.iloc[0].to_dict()
            attachment_value = _stringify(first_attachment.get("storage_path") or first_attachment.get("source_path"))
        if not attachment_value:
            literature_rows = literature_table[literature_table.get("uid_literature", pd.Series(dtype=str)).astype(str) == uid_literature]
            if not literature_rows.empty:
                attachment_value = _stringify(literature_rows.iloc[0].get("pdf_path"))
        if not attachment_value:
            missing_items.append(f"{cite_key}: 缺少附件路径")
            state_rows.append({
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "pending_rough_read": 1,
                "in_rough_read": 0,
                "rough_read_done": 0,
                "rough_read_decision": "missing_attachment",
                "rough_read_reason": "缺少附件路径，无法进入粗读",
                "theme_relation": _stringify(row.get("theme_relation")) or "a080_missing_attachment",
            })
            continue

        extract_result = _extract_reference_source_from_structured(row.to_dict())
        if extract_result is None:
            extract_result = extract_reference_lines_from_attachment(attachment_value, workspace_root=workspace_root, print_to_stdout=False)
        full_text = _stringify(extract_result.get("full_text"))
        if not full_text:
            missing_items.append(f"{cite_key}: 未抽到全文")
            state_rows.append({
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "pending_rough_read": 1,
                "in_rough_read": 0,
                "rough_read_done": 0,
                "rough_read_decision": "missing_text",
                "rough_read_reason": "附件无法抽取正文，保留待复核",
                "theme_relation": _stringify(row.get("theme_relation")) or "a080_missing_text",
            })
            continue

        sentences = _split_sentences(full_text)
        if not sentences:
            missing_items.append(f"{cite_key}: 未切出句子")
            state_rows.append({
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "pending_rough_read": 1,
                "in_rough_read": 0,
                "rough_read_done": 0,
                "rough_read_decision": "no_sentences",
                "rough_read_reason": "正文无法切分为有效句子，暂不升级",
                "theme_relation": _stringify(row.get("theme_relation")) or "a080_no_sentences",
            })
            continue

        problem_lines = [_sentence_line(cite_key, item) for item in _pick_sentences(sentences, SENTENCE_GROUP_KEYWORDS["research_problem"], 3)]
        method_lines = [_sentence_line(cite_key, item) for item in _pick_sentences(sentences, SENTENCE_GROUP_KEYWORDS["method"], 3)]
        finding_lines = [_sentence_line(cite_key, item) for item in _pick_sentences(sentences, SENTENCE_GROUP_KEYWORDS["findings"], 4)]
        title = _stringify(row.get("title")) or cite_key
        note_path = note_dir / f"rough_read_{_safe_file_stem(cite_key)}.md"
        note_body = "\n".join([
            f"# {title}",
            "",
            f"- cite_key: {cite_key}",
            f"- reading_objective: {reading_objective or '未指定'}",
            f"- manual_guidance: {manual_guidance or '未指定'}",
            "",
            "## 研究问题",
            *problem_lines,
            "",
            "## 方法与数据",
            *method_lines,
            "",
            "## 初步发现",
            *finding_lines,
            "",
        ])
        knowledge_index, note_info = _register_note(
            knowledge_index,
            note_path,
            title,
            note_body,
            workspace_root,
            stage_code=source_stage,
            uid_literature=uid_literature,
            cite_key=cite_key,
        )
        written_paths.append(note_path)
        _light_patch_analysis_notes(
            analysis_note_paths,
            cite_key=cite_key,
            title=title,
            problem_lines=problem_lines,
            method_lines=method_lines,
            finding_lines=finding_lines,
        )

        item_mapping_rows: List[Dict[str, Any]] = []
        reference_lines = list(extract_result.get("reference_lines") or [])[:max_references_per_item]
        literature_by_uid: Dict[str, Dict[str, Any]] = {
            _stringify(item.get("uid_literature")): item.to_dict()
            for _, item in literature_table.fillna("").iterrows()
            if _stringify(item.get("uid_literature"))
        }
        for reference_text in reference_lines:
            try:
                literature_table, result = process_reference_citation(
                    literature_table,
                    reference_text,
                    workspace_root=workspace_root,
                    global_config_path=workspace_root / "config" / "config.json",
                    source="placeholder_from_a080_rough_read",
                    print_to_stdout=False,
                )
            except Exception:
                continue
            mapping_row = {
                "source_uid_literature": uid_literature,
                "source_cite_key": cite_key,
                "reference_text": reference_text,
                "matched_uid_literature": _stringify(result.get("matched_uid_literature")),
                "matched_cite_key": _stringify(result.get("matched_cite_key")),
                "action": _stringify(result.get("action")),
                "parse_failed": _stringify(result.get("parse_failed") or "0"),
                "match_score": _stringify(result.get("match_score") or "0"),
                "parse_failure_reason": _stringify(result.get("parse_failure_reason")),
                "suspicious_mismatch": _stringify(result.get("suspicious_mismatch") or "0"),
                "suspicious_merged": _stringify(result.get("suspicious_merged") or "0"),
            }
            mapping_rows.append(mapping_row)
            item_mapping_rows.append(mapping_row)
            target_uid = _stringify(mapping_row.get("matched_uid_literature"))
            if target_uid and target_uid != uid_literature:
                decision = should_route_back_to_a040(
                    mapping_row=mapping_row,
                    target_state=existing_state_by_uid.get(target_uid),
                    target_literature_row=literature_by_uid.get(target_uid),
                )
                if decision.get("route_to_a040"):
                    retrieval_feedback_requests.append(
                        build_retrieval_feedback_request(
                            source_stage=source_stage,
                            source_task_uid=output_dir.name,
                            source_note_path=str(note_path),
                            source_uid_literature=uid_literature,
                            source_cite_key=cite_key,
                            reference_lines=[reference_text],
                            mapping_row=mapping_row,
                            retrieval_reason=_stringify(decision.get("reason")),
                            need_fulltext=True,
                            need_metadata_completion=True,
                        )
                    )

        discovered_rows = _build_discovered_rows_from_mappings(
            item_mapping_rows=item_mapping_rows,
            uid_literature=uid_literature,
            cite_key=cite_key,
            source_stage=source_stage,
            existing_state_by_uid=existing_state_by_uid,
        )
        processed_count = len(item_mapping_rows)
        should_promote = processed_count > 0 or len(finding_lines) >= 2
        state_rows.append({
            "uid_literature": uid_literature,
            "cite_key": cite_key,
            "source_origin": source_origin,
            "reading_objective": reading_objective,
            "manual_guidance": manual_guidance,
            "pending_rough_read": 0,
            "in_rough_read": 0,
            "rough_read_done": 1,
            "rough_read_note_path": str(note_path),
            "rough_read_decision": "promote_a100" if should_promote else "hold",
            "analysis_light_synced": 1,
            "analysis_batch_synced": 1,
            "pending_deep_read": 1 if should_promote else 0,
            "last_batch_id": output_dir.name,
            "rough_read_reason": f"{source_stage} 已完成轻量粗读与批次汇总。阅读目标={reading_objective or '未指定'}；提示语={manual_guidance or '未指定'}",
            "theme_relation": _stringify(row.get("theme_relation")) or f"{source_stage.lower()}_rough_read_complete",
        })
        state_rows.extend(discovered_rows)
        index_rows.append({
            "uid_literature": uid_literature,
            "cite_key": cite_key,
            "title": title,
            "status": "completed",
            "note_path": str(note_path),
            "result_json": _stringify(row.get("normalized_structured_path")),
            "reference_count": len(reference_lines),
            "reference_processed_count": len(item_mapping_rows),
            "source_origin": source_origin,
            "reading_objective": reading_objective,
            "manual_guidance": manual_guidance,
            "theme_relation": _stringify(row.get("theme_relation")),
        })

    if state_rows:
        upsert_reading_state_rows(content_db, state_rows)
    persist_reference_tables(literatures_df=literature_table, attachments_df=attachment_table, db_path=content_db)
    persist_knowledge_tables(index_df=knowledge_index, attachments_df=knowledge_attachments, db_path=content_db)

    index_df = pd.DataFrame(index_rows)
    index_path = output_dir / f"{output_prefix}_rough_reading_index.csv"
    index_df.to_csv(index_path, index=False, encoding="utf-8-sig")
    mapping_df = pd.DataFrame(mapping_rows)
    mapping_path = output_dir / f"{output_prefix}_reference_citation_mapping.csv"
    mapping_df.to_csv(mapping_path, index=False, encoding="utf-8-sig")
    quality_summary = build_reference_quality_summary(mapping_df.to_dict(orient="records"))
    quality_path = output_dir / f"{output_prefix}_reference_citation_quality_summary.json"
    quality_path.write_text(json.dumps(quality_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    related_item_paths = _write_related_literature_items(output_dir, index_df)

    summary_lines: List[str] = [f"# {source_stage} 普通文献研读候选汇总", ""]
    for _, row in index_df.fillna("").iterrows():
        cite_key = _stringify(row.get("cite_key"))
        title = _stringify(row.get("title")) or cite_key
        reason = _stringify(row.get("reading_objective")) or f"已完成 {source_stage} 粗读"
        summary_lines.append(f"- {cite_key}《{title}》：{reason}")
    summary_path = output_dir / f"{output_prefix}_batch_summary.md"
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    refreshed_state_df = load_reading_state_df(content_db, flag_filters={"rough_read_done": 1, "analysis_batch_synced": 1})
    if not refreshed_state_df.empty and not index_df.empty:
        target_uids = set(index_df["uid_literature"].astype(str).tolist())
        refreshed_state_df = refreshed_state_df[refreshed_state_df["uid_literature"].astype(str).isin(target_uids)].reset_index(drop=True)
    a100_queue_rows = _build_a100_queue_rows(refreshed_state_df, source_affair=source_stage)
    if a100_queue_rows:
        upsert_reading_queue_rows(content_db, a100_queue_rows)

    merged_feedback_requests = merge_retrieval_feedback_requests(retrieval_feedback_requests)
    need_download_feedback = any(bool(item.get("need_fulltext", False)) for item in merged_feedback_requests)
    registered_feedback_requests: List[Dict[str, Any]] = []
    dispatched_feedback_requests: List[Dict[str, Any]] = []
    dispatch_failures: List[str] = []
    if merged_feedback_requests:
        registered_feedback_requests = register_a040_requests_from_feedback(
            workspace_root=workspace_root,
            feedback_requests=merged_feedback_requests,
            source_node=source_stage,
            priority="高" if need_download_feedback else "中",
            creator_type="affair",
            creator_id=f"{source_stage}_普通文献研读候选视图构建",
            attribute_vector={
                "source_stage": source_stage,
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

    feedback_path = output_dir / f"retrieval_feedback_requests_{source_stage}.json"
    feedback_summary_path = output_dir / f"retrieval_feedback_summary_{source_stage}.json"
    affair_request_result_path = output_dir / f"affair_request_dispatch_{source_stage}.json"
    feedback_summary = {
        "task_uid": output_dir.name,
        "source_stage": source_stage,
        "request_count": len(merged_feedback_requests),
        "rough_read_count": len(index_df),
        "need_download_feedback": need_download_feedback,
        "registered_request_count": len(registered_feedback_requests),
        "dispatched_request_count": len(dispatched_feedback_requests),
        "dispatch_failed_count": len(dispatch_failures),
    }
    feedback_path.write_text(json.dumps(merged_feedback_requests, ensure_ascii=False, indent=2), encoding="utf-8")
    feedback_summary_path.write_text(json.dumps(feedback_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    affair_request_result_path.write_text(json.dumps({"registered_requests": registered_feedback_requests, "dispatched_results": dispatched_feedback_requests, "dispatch_failures": dispatch_failures}, ensure_ascii=False, indent=2), encoding="utf-8")

    artifact_paths = [index_path, mapping_path, quality_path, summary_path, feedback_path, feedback_summary_path, affair_request_result_path, *related_item_paths, *written_paths]
    return artifact_paths, {
        "rough_read_count": len(index_df),
        "a100_queue_count": len(a100_queue_rows),
        "rough_read_failures": [*missing_items, *dispatch_failures],
    }


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
    """优先从正式 A150 阶段队列构建输入池，必要时兼容旧 reading_state。"""

    queue_df = load_reading_queue_df(
        content_db,
        stage="A150",
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
        stage="A150",
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
                "recommended_reason": _stringify(row.get("recommended_reason")) or "legacy A150 queue seed",
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
    lines = ["# A150 相关文献条目", "", f"共 {len(snapshot_df)} 条。", ""]
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


@affair_auto_git_commit("A150")
def execute(config_path: Path) -> List[Path]:
    config_path = Path(config_path)
    raw_cfg = load_json_or_py(config_path)
    if not isinstance(raw_cfg, dict):
        raise ValueError("A150 配置必须是字典")

    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    legacy_output_dir = resolve_legacy_output_dir(
        raw_cfg,
        config_path,
        default_path=workspace_root / "tasks" / "A080_non_review_preprocess",
    )
    output_dir = create_task_instance_dir(workspace_root, "A150")
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
        source_stage="A150",
        upstream_stage="A140",
        downstream_stage="A150",
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
                "source_stage": "A150",
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
                    "source_stage": _stringify(existing.get("source_stage")) or "A140",
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

    rough_ready_df = ready_df.copy()
    if not rough_ready_df.empty:
        state_lookup_df = state_df.copy().fillna("")
        state_lookup_df["uid_literature"] = state_lookup_df.get("uid_literature", pd.Series(dtype=str)).astype(str)
        rough_ready_df["uid_literature"] = rough_ready_df.get("uid_literature", pd.Series(dtype=str)).astype(str)
        merge_columns = [column for column in ["uid_literature", "reading_objective", "manual_guidance", "theme_relation", "source_origin", "priority"] if column in state_lookup_df.columns]
        if "uid_literature" in merge_columns:
            rough_ready_df = rough_ready_df.merge(state_lookup_df[merge_columns].drop_duplicates(subset=["uid_literature"]), on="uid_literature", how="left", suffixes=("", "_state")).fillna("")

    a095_queue_rows = _build_a095_queue_rows(rough_ready_df) if not rough_ready_df.empty else []
    if a095_queue_rows:
        upsert_reading_queue_rows(content_db, a095_queue_rows)

    consumed_a080_queue_count = _consume_current_stage_queue_rows(content_db, stage="A150", ready_df=ready_df)

    result_df = pd.DataFrame(result_rows)
    index_path = output_dir / OUTPUT_INDEX
    result_df.to_csv(index_path, index=False, encoding="utf-8-sig")
    related_item_paths = _write_related_literature_items(output_dir, result_df)

    gate_review = build_gate_review(
        node_uid="A150",
        node_name="普通文献泛读",
        summary=(
            f"消费 A150 输入池 {len(state_df)} 条（mode={input_mode}）；"
            f"legacy queue 补种 {legacy_seeded_count} 条；"
            f"解析就绪 {ready_count} 条；"
            f"写入 A160 队列 {len(a095_queue_rows)} 条；"
            f"失败 {failed_count} 条；"
            f"后处理成功 {postprocess_success_count} 条；"
            f"消费 A150 兼容队列 {consumed_a080_queue_count} 条。"
        ),
        checks=[
            {"name": "a080_input_count", "value": len(state_df)},
            {"name": "a080_input_mode", "value": input_mode},
            {"name": "legacy_queue_seeded_count", "value": legacy_seeded_count},
            {"name": "preprocess_ready_count", "value": ready_count},
            {"name": "a095_queue_count", "value": len(a095_queue_rows)},
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
            "upstream_stage": "A140",
            "downstream_stage": "A160",
            "allow_unparsed_read_bypass": allow_unparsed_read_bypass,
            "auto_enable_unparsed_for_failed_items": auto_enable_unparsed_for_failed_items,
            "a095_queue_count": len(a095_queue_rows),
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
            affair_code="A150",
            handler_name="普通文献泛读",
            agent_names=["ar_A080_普通文献泛读事务智能体_v7"],
            skill_names=["a150-nonreview-preprocess-v6"],
            reasoning_summary="完成普通文献预处理，并把可泛读条目推进到 A160 普通文献研读候选视图构建。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=artifact_paths,
            payload={
                "input_count": len(state_df),
                "input_mode": input_mode,
                "legacy_queue_seeded_count": legacy_seeded_count,
                "ready_count": ready_count,
                "failed_count": failed_count,
                "a095_queue_count": len(a095_queue_rows),
                "postprocess_success_count": postprocess_success_count,
                "consumed_a080_queue_count": consumed_a080_queue_count,
            },
        )
    except Exception:
        pass

    return artifact_paths

