"""A105 文献批判性研读与标准笔记事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import append_aok_log_event, build_gate_review, knowledge_index_sync_from_note, knowledge_note_register, load_json_or_py, process_reference_citation
from autodokit.tools.llm_clients import postprocess_aliyun_multimodal_parse_outputs
from autodokit.tools.bibliodb_sqlite import load_reading_state_df, upsert_reading_state_rows
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.pdf_parse_asset_manager import ensure_multimodal_parse_asset, ensure_pdf_text_fallback_asset
from autodokit.tools.pdf_structured_data_tools import load_single_document_record
from autodokit.tools.reading_state_tools import build_followup_candidate_state_row
from autodokit.tools.storage_backend import load_knowledge_tables, load_reference_tables, persist_knowledge_tables, persist_reference_tables
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


OUTPUT_INDEX = "a105_critical_reading_index.csv"
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


@affair_auto_git_commit("A105")
def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    output_dir = _resolve_output_dir(config_path, raw_cfg)
    content_db, _ = resolve_content_db_config(
        raw_cfg,
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None

    parse_ready_only = bool(raw_cfg.get("parse_ready_only", True))
    if parse_ready_only:
        state_df = load_reading_state_df(content_db, flag_filters={"deep_read_done": 0})
        if not state_df.empty and "deep_read_decision" in state_df.columns:
            state_df = state_df[state_df["deep_read_decision"].astype(str).isin(["parse_ready", "pdf_fallback_ready"])].reset_index(drop=True)
    else:
        state_df = load_reading_state_df(content_db, flag_filters={"pending_deep_read": 1, "deep_read_done": 0})

    existing_state_df = load_reading_state_df(content_db)
    existing_state_by_uid = {
        _stringify(row.get("uid_literature")): row.to_dict()
        for _, row in existing_state_df.fillna("").iterrows()
        if _stringify(row.get("uid_literature"))
    }

    max_items = int(raw_cfg.get("max_items") or 3)
    if max_items > 0:
        state_df = state_df.head(max_items).reset_index(drop=True)

    enable_aliyun_postprocess = bool(raw_cfg.get("enable_aliyun_postprocess", True))
    enable_llm_basic_cleanup = bool(raw_cfg.get("enable_llm_basic_cleanup", True))
    basic_cleanup_llm_model = _stringify(raw_cfg.get("basic_cleanup_llm_model")) or "qwen3.5-flash"
    basic_cleanup_llm_sdk_backend = _stringify(raw_cfg.get("basic_cleanup_llm_sdk_backend")) or None
    basic_cleanup_llm_region = _stringify(raw_cfg.get("basic_cleanup_llm_region")) or "cn-beijing"
    enable_llm_structure_resolution = bool(raw_cfg.get("enable_llm_structure_resolution", True))
    structure_llm_model = _stringify(raw_cfg.get("structure_llm_model")) or "qwen3.5-plus"
    structure_llm_sdk_backend = _stringify(raw_cfg.get("structure_llm_sdk_backend")) or None
    structure_llm_region = _stringify(raw_cfg.get("structure_llm_region")) or "cn-beijing"
    enable_llm_contamination_filter = bool(raw_cfg.get("enable_llm_contamination_filter", True))
    contamination_llm_model = _stringify(raw_cfg.get("contamination_llm_model")) or "qwen3-max"
    contamination_llm_sdk_backend = _stringify(raw_cfg.get("contamination_llm_sdk_backend")) or None
    contamination_llm_region = _stringify(raw_cfg.get("contamination_llm_region")) or "cn-beijing"
    postprocess_rewrite_structured = bool(raw_cfg.get("postprocess_rewrite_structured", True))
    postprocess_rewrite_markdown = bool(raw_cfg.get("postprocess_rewrite_markdown", True))
    postprocess_keep_page_markers = bool(raw_cfg.get("postprocess_keep_page_markers", False))

    literatures_df, attachments_df, _ = load_reference_tables(db_path=content_db)
    knowledge_index_df, knowledge_attachments_df, _ = load_knowledge_tables(db_path=content_db)

    result_rows: List[Dict[str, Any]] = []
    state_updates: List[Dict[str, Any]] = []
    failures: List[str] = []

    note_dir = workspace_root / "knowledge" / "standard_notes"
    note_dir.mkdir(parents=True, exist_ok=True)

    for _, row in state_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        reading_objective = _stringify(row.get("reading_objective"))
        manual_guidance = _stringify(row.get("manual_guidance"))
        source_origin = _stringify(row.get("source_origin")) or "auto"
        deep_read_decision = _stringify(row.get("deep_read_decision"))

        upsert_reading_state_rows(
            content_db,
            [
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "in_deep_read": 1,
                    "deep_read_decision": "in_critical_read",
                }
            ],
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

            asset_backend = _stringify(parse_asset.get("backend"))
            postprocess_summary: Dict[str, Any] = {}
            if enable_aliyun_postprocess and asset_backend == "aliyun_multimodal":
                postprocess_summary = postprocess_aliyun_multimodal_parse_outputs(
                    normalized_structured_path=_stringify(parse_asset.get("normalized_structured_path")),
                    reconstructed_markdown_path=_stringify(parse_asset.get("reconstructed_markdown_path")),
                    rewrite_structured=postprocess_rewrite_structured,
                    rewrite_markdown=postprocess_rewrite_markdown,
                    keep_page_markers=postprocess_keep_page_markers,
                    enable_llm_basic_cleanup=enable_llm_basic_cleanup,
                    basic_cleanup_llm_model=basic_cleanup_llm_model,
                    basic_cleanup_llm_sdk_backend=basic_cleanup_llm_sdk_backend,
                    basic_cleanup_llm_region=basic_cleanup_llm_region,
                    enable_llm_structure_resolution=enable_llm_structure_resolution,
                    structure_llm_model=structure_llm_model,
                    structure_llm_sdk_backend=structure_llm_sdk_backend,
                    structure_llm_region=structure_llm_region,
                    enable_llm_contamination_filter=enable_llm_contamination_filter,
                    contamination_llm_model=contamination_llm_model,
                    contamination_llm_sdk_backend=contamination_llm_sdk_backend,
                    contamination_llm_region=contamination_llm_region,
                    config_path=workspace_root / "config" / "config.json",
                )
            elif asset_backend == "pdf_text_fallback":
                postprocess_summary = {
                    "llm_basic_cleanup_status": "skipped_pdf_text_fallback",
                    "llm_structure_resolution_status": "skipped_pdf_text_fallback",
                    "contamination_removed_block_count": 0,
                }
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
            note_body = _build_critical_note(
                title=title,
                cite_key=cite_key,
                text=full_text,
                reading_objective=reading_objective,
                manual_guidance=manual_guidance,
            )
            note_info = knowledge_note_register(
                note_path=note_path,
                title=title,
                note_type="literature_standard_note",
                status="draft",
                tags=["aok/critical_read", "a105"],
                aliases=[cite_key],
                evidence_uids=[uid_literature],
                uid_literature=uid_literature,
                cite_key=cite_key,
                body=note_body,
            )
            knowledge_index_df, _ = knowledge_index_sync_from_note(knowledge_index_df, note_path, workspace_root=workspace_root)

            reference_lines = _extract_reference_lines(full_text)
            discovered_rows: List[Dict[str, Any]] = []
            for reference_text in reference_lines:
                try:
                    literatures_df, result = process_reference_citation(
                        literatures_df,
                        reference_text,
                        workspace_root=workspace_root,
                        global_config_path=workspace_root / "config" / "config.json",
                        source="placeholder_from_a105_critical_read",
                        print_to_stdout=False,
                    )
                except Exception:
                    continue
                target_uid = _stringify(result.get("matched_uid_literature"))
                target_cite_key = _stringify(result.get("matched_cite_key"))
                if target_uid and target_uid != uid_literature:
                    candidate_row = build_followup_candidate_state_row(
                        uid_literature=target_uid,
                        cite_key=target_cite_key,
                        source_stage="A105",
                        source_uid_literature=uid_literature,
                        source_cite_key=cite_key,
                        recommended_reason=f"A105 从 {cite_key} 批判性研读参考文献发现新候选",
                        theme_relation="a105_reference_discovery",
                        existing_state=existing_state_by_uid.get(target_uid),
                    )
                    if candidate_row is None:
                        continue
                    discovered_rows.append(candidate_row)
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
                    "deep_read_reason": (
                        f"A105 已完成批判性研读与标准笔记。"
                        f"阅读目标={reading_objective or '未指定'}；提示语={manual_guidance or '未指定'}"
                    ),
                }
            )
            state_updates.extend(discovered_rows)
            result_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "title": title,
                    "structured_json": structured_json,
                    "deep_read_note_path": str(note_path),
                    "discovered_candidate_count": len(discovered_rows),
                    "knowledge_uid": _stringify(note_info.get("uid_knowledge")),
                    "asset_backend": asset_backend,
                    "postprocess_ok": int(bool(postprocess_summary) or (not enable_aliyun_postprocess)),
                    "postprocess_llm_basic_cleanup_status": _stringify(postprocess_summary.get("llm_basic_cleanup_status")),
                    "postprocess_llm_structure_status": _stringify(postprocess_summary.get("llm_structure_resolution_status")),
                    "postprocess_contamination_removed_block_count": int(postprocess_summary.get("contamination_removed_block_count") or 0),
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
    index_path = output_dir / OUTPUT_INDEX
    result_df.to_csv(index_path, index=False, encoding="utf-8-sig")

    gate_review = build_gate_review(
        node_uid="A105",
        node_name="文献批判性研读与标准笔记",
        summary=f"完成批判性研读 {len(result_rows)} 篇；失败 {len(failures)} 篇。",
        checks=[{"name": "critical_read_count", "value": len(result_rows)}, {"name": "failure_count", "value": len(failures)}],
        artifacts=[str(index_path)],
        recommendation="pass" if result_rows else "retry_current",
        score=max(45.0, 92.0 - len(failures) * 10.0),
        issues=failures,
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "enable_aliyun_postprocess": enable_aliyun_postprocess,
            "enable_llm_basic_cleanup": enable_llm_basic_cleanup,
            "basic_cleanup_llm_model": basic_cleanup_llm_model,
            "enable_llm_structure_resolution": enable_llm_structure_resolution,
            "structure_llm_model": structure_llm_model,
            "enable_llm_contamination_filter": enable_llm_contamination_filter,
            "contamination_llm_model": contamination_llm_model,
        },
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        append_aok_log_event(
            event_type="A105_CRITICAL_READING_COMPLETED",
            project_root=workspace_root,
            affair_code="A105",
            handler_name="文献批判性研读与标准笔记",
            agent_names=["ar_A105_文献批判性研读与标准笔记事务智能体_v1"],
            skill_names=[],
            reasoning_summary="消费 parse_ready 条目，完成批判性研读、标准文献笔记写回与新候选回流。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=[path for path in [index_path, gate_path] if path is not None],
            payload={
                "critical_read_count": len(result_rows),
                "failure_count": len(failures),
                "enable_llm_basic_cleanup": enable_llm_basic_cleanup,
                "enable_llm_structure_resolution": enable_llm_structure_resolution,
                "enable_llm_contamination_filter": enable_llm_contamination_filter,
            },
        )
    except Exception:
        pass

    return [index_path, gate_path]
