"""A090 文献泛读与轻量分析事务。"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pandas as pd

from autodokit.tools import append_aok_log_event, build_gate_review, build_reference_quality_summary, extract_reference_lines_from_attachment, knowledge_index_sync_from_note, knowledge_note_register, load_json_or_py, process_reference_citation
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.bibliodb_sqlite import load_reading_state_df, save_dataframe_table, upsert_reading_state_rows
from autodokit.tools.reading_state_tools import (
    ANALYSIS_NOTE_SPECS,
    append_markdown_section,
    build_followup_candidate_state_row,
    build_retrieval_feedback_request,
    merge_retrieval_feedback_requests,
    resolve_analysis_note_paths,
    should_route_back_to_a040,
)
from autodokit.tools.storage_backend import (
    load_knowledge_tables,
    load_reference_tables,
    persist_knowledge_tables,
    persist_reference_tables,
)
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


NOTE_DIR_NAME = "rough_read_notes"
OUTPUT_INDEX = "rough_reading_index.csv"
OUTPUT_MAPPING = "reference_citation_mapping.csv"
OUTPUT_QUALITY = "reference_citation_quality_summary.json"
OUTPUT_GATE = "gate_review.json"

SENTENCE_GROUP_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "research_problem": ("本文", "文章", "研究", "探究", "检验", "分析"),
    "method": ("基于", "模型", "样本", "数据", "方法", "识别", "实证"),
    "findings": ("发现", "表明", "影响", "风险", "系统性风险", "房价", "信贷", "银行"),
}


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
    value = re.sub(r"[\\/:*?\"<>|]", "_", _stringify(text))
    value = re.sub(r"\s+", " ", value).strip()
    return value or "untitled"


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


def _resolve_existing_path(raw_value: str, candidates: Sequence[Path]) -> Path:
    text = _stringify(raw_value)
    if text:
        path = Path(text)
        if not path.is_absolute():
            raise ValueError(f"路径字段必须为绝对路径: {path}")
        return path
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_rough_pool(content_db: Path, literature_table: pd.DataFrame) -> pd.DataFrame:
    state_df = load_reading_state_df(content_db, flag_filters={"pending_rough_read": 1})
    if state_df.empty:
        return pd.DataFrame()
    merged = state_df.copy()
    merged["uid_literature"] = merged.get("uid_literature", pd.Series(dtype=str)).astype(str)
    literature = literature_table.copy()
    literature["uid_literature"] = literature.get("uid_literature", pd.Series(dtype=str)).astype(str)
    merged = merged.merge(literature, on="uid_literature", how="left", suffixes=("_state", ""))
    merged["cite_key"] = merged.get("cite_key", merged.get("cite_key_state", pd.Series(dtype=str))).fillna("")
    return merged.fillna("")


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


def _register_note(knowledge_index: pd.DataFrame, note_path: Path, title: str, body: str, workspace_root: Path, *, uid_literature: str = "", cite_key: str = "") -> Tuple[pd.DataFrame, Dict[str, Any]]:
    note_info = knowledge_note_register(
        note_path=note_path,
        title=title,
        note_type="knowledge_note",
        status="draft",
        tags=["aok/rough_read", "a090"],
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
        "controversies": [f"- {cite_key}《{title}》：当前仅形成轻量争议占位，待 A100 正式修订。"],
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
    existing_state_by_uid: Dict[str, Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """基于当前文献自己的映射结果生成新候选回流行。"""

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
            source_stage="A090",
            source_uid_literature=uid_literature,
            source_cite_key=cite_key,
            recommended_reason=f"A090 从 {cite_key} 参考文献发现候选",
            theme_relation="a090_reference_discovery",
            existing_state=existing_state_by_uid.get(target_uid),
        )
        if candidate_row is None:
            continue
        discovered_rows.append(candidate_row)
        existing_state_by_uid[target_uid] = candidate_row
    return discovered_rows


@affair_auto_git_commit("A090")
def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
        # process_reference_citation 内部已按原子链路执行：匹配 -> 占位 -> 写回 -> cite_key 生成。
    legacy_output_dir = _resolve_output_dir(config_path, raw_cfg)
    output_dir = _build_task_instance_dir(workspace_root, "A090")
    content_db, db_input_key = resolve_content_db_config(
        raw_cfg,
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None
    global_config_path = workspace_root / "config" / "config.json"

    literature_table, attachment_table, _ = load_reference_tables(db_path=content_db)
    knowledge_index, knowledge_attachments, _ = load_knowledge_tables(db_path=content_db)
    existing_state_df = load_reading_state_df(content_db)
    existing_state_by_uid = {
        _stringify(row.get("uid_literature")): row.to_dict()
        for _, row in existing_state_df.fillna("").iterrows()
        if _stringify(row.get("uid_literature"))
    }
    rough_pool = _load_rough_pool(content_db, literature_table)
    consume_unparsed_bypass_items = bool(raw_cfg.get("consume_unparsed_bypass_items", False))
    if not rough_pool.empty and not consume_unparsed_bypass_items:
        preprocessed_series = pd.to_numeric(rough_pool.get("preprocessed", 0), errors="coerce").fillna(0).astype(int)
        allow_unparsed_series = pd.to_numeric(rough_pool.get("allow_unparsed_read", 0), errors="coerce").fillna(0).astype(int)
        rough_pool = rough_pool.loc[~((preprocessed_series == 0) & (allow_unparsed_series == 1))].copy()
    max_items = int(raw_cfg.get("max_items") or 6)
    max_references_per_item = int(raw_cfg.get("max_references_per_item") or 12)
    analysis_note_paths = resolve_analysis_note_paths(workspace_root, raw_cfg)
    if max_items > 0:
        rough_pool = rough_pool.head(max_items).reset_index(drop=True)

    note_dir = workspace_root / "knowledge" / "audits" / NOTE_DIR_NAME
    note_dir.mkdir(parents=True, exist_ok=True)

    index_rows: List[Dict[str, Any]] = []
    mapping_rows: List[Dict[str, Any]] = []
    retrieval_feedback_requests: List[Dict[str, Any]] = []
    state_rows: List[Dict[str, Any]] = []
    written_paths: List[Path] = []
    missing_items: List[str] = []

    for _, row in rough_pool.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        manual_guidance = _stringify(row.get("manual_guidance"))
        reading_objective = _stringify(row.get("reading_objective"))
        source_origin = _stringify(row.get("source_origin")) or "auto"
        unparsed_read_mode = int(row.get("preprocessed") or 0) == 0 and int(row.get("allow_unparsed_read") or 0) == 1
        upsert_reading_state_rows(
            content_db,
            [
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "pending_rough_read": 0,
                    "in_rough_read": 1,
                    "rough_read_done": 0,
                }
            ],
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
            state_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "pending_rough_read": 1,
                    "in_rough_read": 0,
                    "rough_read_done": 0,
                    "rough_read_decision": "missing_attachment",
                    "rough_read_reason": "缺少附件路径，无法进入粗读",
                    "theme_relation": _stringify(row.get("theme_relation")) or "a090_missing_attachment",
                }
            )
            continue

        extract_result = extract_reference_lines_from_attachment(attachment_value, workspace_root=workspace_root, print_to_stdout=False)
        full_text = _stringify(extract_result.get("full_text"))
        if not full_text:
            missing_items.append(f"{cite_key}: 未抽到全文")
            state_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "pending_rough_read": 1,
                    "in_rough_read": 0,
                    "rough_read_done": 0,
                    "rough_read_decision": "missing_text",
                    "rough_read_reason": "附件无法抽取正文，保留待复核",
                    "theme_relation": _stringify(row.get("theme_relation")) or "a090_missing_text",
                }
            )
            continue
        sentences = _split_sentences(full_text)
        if not sentences:
            missing_items.append(f"{cite_key}: 未切出句子")
            state_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "pending_rough_read": 1,
                    "in_rough_read": 0,
                    "rough_read_done": 0,
                    "rough_read_decision": "no_sentences",
                    "rough_read_reason": "正文无法切分为有效句子，暂不升级",
                    "theme_relation": _stringify(row.get("theme_relation")) or "a090_no_sentences",
                }
            )
            continue

        question_sentences = _pick_sentences(sentences, SENTENCE_GROUP_KEYWORDS["research_problem"], 2)
        method_sentences = _pick_sentences(sentences, SENTENCE_GROUP_KEYWORDS["method"], 2)
        finding_sentences = _pick_sentences(sentences, SENTENCE_GROUP_KEYWORDS["findings"], 3)
        note_path = note_dir / f"rough_reading_{_safe_file_stem(cite_key)}.md"
        note_lines = [f"# {cite_key} 粗读笔记", ""]
        note_lines.append("## 研究问题")
        note_lines.extend(_sentence_line(cite_key, item) for item in question_sentences)
        note_lines.append("")
        note_lines.append("## 方法与识别")
        note_lines.extend(_sentence_line(cite_key, item) for item in method_sentences)
        note_lines.append("")
        note_lines.append("## 核心发现")
        note_lines.extend(_sentence_line(cite_key, item) for item in finding_sentences)
        if manual_guidance or reading_objective:
            note_lines.append("")
            note_lines.append("## 人工阅读目标")
            if reading_objective:
                note_lines.append(f"- reading_objective: {reading_objective}")
            if manual_guidance:
                note_lines.append(f"- manual_guidance: {manual_guidance}")
        note_body = "\n".join(note_lines).strip() + "\n"
        knowledge_index, note_info = _register_note(knowledge_index, note_path, f"{cite_key} 粗读笔记", note_body, workspace_root, uid_literature=uid_literature, cite_key=cite_key)
        written_paths.append(note_path)

        item_reference_lines = list(extract_result.get("reference_lines") or [])[:max_references_per_item]
        processed_count = 0
        item_mapping_rows: List[Dict[str, Any]] = []
        literature_by_uid: Dict[str, Dict[str, Any]] = {
            _stringify(item.get("uid_literature")): item.to_dict()
            for _, item in literature_table.fillna("").iterrows()
            if _stringify(item.get("uid_literature"))
        }
        short_loop_mapping_rows: List[Dict[str, Any]] = []
        for reference_text in item_reference_lines:
            try:
                literature_table, result = process_reference_citation(
                    literature_table,
                    reference_text,
                    workspace_root=workspace_root,
                    global_config_path=global_config_path if global_config_path.exists() else None,
                    source="placeholder_from_a090_rough_read",
                    print_to_stdout=False,
                )
                mapping_row = {
                    "source_uid_literature": uid_literature,
                    "source_cite_key": cite_key,
                    "reference_text": reference_text,
                    "matched_uid_literature": _stringify(result.get("matched_uid_literature")),
                    "matched_cite_key": _stringify(result.get("matched_cite_key")),
                    "action": _stringify(result.get("action")),
                    "parse_method": _stringify(result.get("parse_method")),
                    "llm_invoked": result.get("llm_invoked") or 0,
                    "parse_failed": result.get("parse_failed") or 0,
                    "parse_failure_reason": _stringify(result.get("parse_failure_reason")),
                    "suspicious_merged": result.get("suspicious_merged") or 0,
                    "noise_trimmed": result.get("noise_trimmed") or 0,
                    "match_score": result.get("match_score") or 0,
                    "suspicious_mismatch": result.get("suspicious_mismatch") or 0,
                    "reference_note_path": str(note_path),
                }
                mapping_rows.append(mapping_row)
                item_mapping_rows.append(mapping_row)
                processed_count += 1

                target_uid = _stringify(mapping_row.get("matched_uid_literature"))
                decision = should_route_back_to_a040(
                    mapping_row=mapping_row,
                    target_state=existing_state_by_uid.get(target_uid) if target_uid else None,
                    target_literature_row=literature_by_uid.get(target_uid) if target_uid else None,
                )
                if decision.get("route_to_a040"):
                    retrieval_feedback_requests.append(
                        build_retrieval_feedback_request(
                            source_stage="A090",
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
                else:
                    short_loop_mapping_rows.append(mapping_row)
            except Exception as exc:
                mapping_row = {
                    "source_uid_literature": uid_literature,
                    "source_cite_key": cite_key,
                    "reference_text": reference_text,
                    "matched_uid_literature": "",
                    "matched_cite_key": "",
                    "action": "failed",
                    "parse_method": "error",
                    "llm_invoked": 0,
                    "parse_failed": 1,
                    "parse_failure_reason": str(exc),
                    "suspicious_merged": 0,
                    "noise_trimmed": 0,
                    "match_score": 0,
                    "suspicious_mismatch": 0,
                    "reference_note_path": str(note_path),
                }
                mapping_rows.append(mapping_row)
                item_mapping_rows.append(mapping_row)
                retrieval_feedback_requests.append(
                    build_retrieval_feedback_request(
                        source_stage="A090",
                        source_task_uid=output_dir.name,
                        source_note_path=str(note_path),
                        source_uid_literature=uid_literature,
                        source_cite_key=cite_key,
                        reference_lines=[reference_text],
                        mapping_row=mapping_row,
                        retrieval_reason="参考文献处理异常，需回流 A040 补检",
                        need_fulltext=True,
                        need_metadata_completion=True,
                    )
                )

        result_payload = {
            "uid_literature": uid_literature,
            "cite_key": cite_key,
            "note_path": str(note_path),
            "note_uid": _stringify(note_info.get("uid_knowledge")),
            "reference_count": len(item_reference_lines),
            "reference_processed_count": processed_count,
            "selected_question_sentences": [item.get("sentence") for item in question_sentences],
            "selected_method_sentences": [item.get("sentence") for item in method_sentences],
            "selected_finding_sentences": [item.get("sentence") for item in finding_sentences],
        }
        json_path = output_dir / f"rough_reading_result_{_safe_file_stem(cite_key)}.json"
        json_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written_paths.append(json_path)
        index_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "note_path": str(note_path),
                "result_json": str(json_path),
                "reference_count": len(item_reference_lines),
                "reference_processed_count": processed_count,
                "status": "completed",
            }
        )
        problem_lines = [item.get("sentence") for item in question_sentences if _stringify(item.get("sentence"))]
        method_lines = [item.get("sentence") for item in method_sentences if _stringify(item.get("sentence"))]
        finding_lines = [item.get("sentence") for item in finding_sentences if _stringify(item.get("sentence"))]
        _light_patch_analysis_notes(
            analysis_note_paths,
            cite_key=cite_key,
            title=_stringify(row.get("title")) or cite_key,
            problem_lines=problem_lines,
            method_lines=method_lines,
            finding_lines=finding_lines,
        )

        should_promote = processed_count > 0 or len(finding_sentences) >= 2
        state_rows.append(
            {
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
                "rough_read_reason": (
                    f"粗读完成，已形成轻量笔记与参考文献映射。"
                    f"阅读目标={reading_objective or '未指定'}；提示语={manual_guidance or '未指定'}"
                ),
                "analysis_light_synced": 1,
                "pending_deep_read": 1 if should_promote else 0,
                "theme_relation": _stringify(row.get("theme_relation")) or "a090_completed",
                "rough_read_without_parse_done": 1 if unparsed_read_mode else int(row.get("rough_read_without_parse_done") or 0),
                "require_reread_after_parse": 1 if unparsed_read_mode else int(row.get("require_reread_after_parse") or 0),
            }
        )

        discovered_rows = _build_discovered_rows_from_mappings(
            item_mapping_rows=short_loop_mapping_rows,
            uid_literature=uid_literature,
            cite_key=cite_key,
            existing_state_by_uid=existing_state_by_uid,
        )
        state_rows.extend(discovered_rows)

    index_df = pd.DataFrame(index_rows)
    mapping_df = pd.DataFrame(mapping_rows)
    quality_summary = build_reference_quality_summary(mapping_rows)

    index_path = output_dir / OUTPUT_INDEX
    mapping_path = output_dir / OUTPUT_MAPPING
    quality_path = output_dir / OUTPUT_QUALITY
    feedback_path = output_dir / "retrieval_feedback_requests_A090.json"
    feedback_summary_path = output_dir / "retrieval_feedback_summary_A090.json"
    gate_path = output_dir / OUTPUT_GATE
    index_df.to_csv(index_path, index=False, encoding="utf-8-sig")
    mapping_df.to_csv(mapping_path, index=False, encoding="utf-8-sig")
    quality_path.write_text(json.dumps(quality_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    merged_feedback_requests = merge_retrieval_feedback_requests(retrieval_feedback_requests)
    feedback_summary = {
        "task_uid": output_dir.name,
        "source_stage": "A090",
        "request_count": len(merged_feedback_requests),
        "processed_mapping_count": len(mapping_rows),
        "short_loop_mapping_count": max(0, len(mapping_rows) - len(merged_feedback_requests)),
    }
    feedback_path.write_text(json.dumps(merged_feedback_requests, ensure_ascii=False, indent=2), encoding="utf-8")
    feedback_summary_path.write_text(json.dumps(feedback_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    written_paths.extend([index_path, mapping_path, quality_path, feedback_path, feedback_summary_path])

    save_dataframe_table(content_db, "a090_rough_reading_index", index_df, if_exists="replace", unique_columns=["uid_literature"] if not index_df.empty else None)
    save_dataframe_table(content_db, "a090_reference_citation_mapping", mapping_df, if_exists="replace")
    persist_reference_tables(literatures_df=literature_table, attachments_df=attachment_table, db_path=content_db)
    persist_knowledge_tables(index_df=knowledge_index, attachments_df=knowledge_attachments, db_path=content_db)
    if state_rows:
        upsert_reading_state_rows(content_db, state_rows)

    gate_review = build_gate_review(
        node_uid="A090",
        node_name="文献泛读与粗读",
        summary=(
            f"完成粗读 {len(index_df)} 篇，处理参考文献 {quality_summary.get('total_reference_count', 0)} 条，"
            f"新增占位 {quality_summary.get('placeholder_count', 0)} 条。"
        ),
        checks=[
            {"name": "rough_read_count", "value": len(index_df)},
            {"name": "reference_total_count", "value": quality_summary.get("total_reference_count", 0)},
            {"name": "placeholder_count", "value": quality_summary.get("placeholder_count", 0)},
            {"name": "parse_failed_count", "value": quality_summary.get("parse_failed_count", 0)},
            {"name": "missing_item_count", "value": len(missing_items)},
            {"name": "retrieval_feedback_request_count", "value": len(merged_feedback_requests)},
        ],
        artifacts=[str(path) for path in written_paths],
        recommendation="pass" if len(index_df) > 0 else "retry_current",
        score=max(40.0, 92.0 - len(missing_items) * 8.0),
        issues=missing_items,
        metadata={"workspace_root": str(workspace_root), "content_db": str(content_db), "db_input_key": db_input_key},
    )
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
    written_paths.append(gate_path)

    if legacy_output_dir != output_dir:
        legacy_output_dir.mkdir(parents=True, exist_ok=True)
        for artifact_path in [index_path, mapping_path, quality_path, gate_path]:
            if artifact_path.exists():
                legacy_target = legacy_output_dir / artifact_path.name
                legacy_target.write_text(artifact_path.read_text(encoding="utf-8"), encoding="utf-8")

    try:
        append_aok_log_event(
            event_type="A090_ROUGH_READING_BUILT",
            project_root=workspace_root,
            affair_code="A090",
            handler_name="文献泛读与粗读",
            agent_names=["ar_A090_文献泛读与轻量分析事务智能体_v6"],
            skill_names=["ar_文献泛读与粗读_v5", "ar_单篇文献粗读_v2"],
            reasoning_summary="消费 literature_reading_state.pending_rough_read=1，生成粗读笔记并对五类分析笔记做轻量补写。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=written_paths,
            payload={
                "rough_read_count": len(index_df),
                "reference_total_count": quality_summary.get("total_reference_count", 0),
                "placeholder_count": quality_summary.get("placeholder_count", 0),
                "missing_item_count": len(missing_items),
                "retrieval_feedback_request_count": len(merged_feedback_requests),
                "consume_unparsed_bypass_items": consume_unparsed_bypass_items,
            },
        )
    except Exception:
        pass

    return written_paths
