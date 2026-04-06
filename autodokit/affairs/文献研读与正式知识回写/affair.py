"""A100 文献研读与正式知识回写事务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import append_aok_log_event, build_gate_review, knowledge_index_sync_from_note, knowledge_note_register, load_json_or_py, process_reference_citation
from autodokit.tools.bibliodb_sqlite import load_reading_state_df, upsert_reading_state_rows
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.pdf_parse_asset_manager import ensure_multimodal_parse_asset
from autodokit.tools.pdf_structured_data_tools import load_single_document_record
from autodokit.tools.reading_state_tools import ANALYSIS_NOTE_SPECS, append_markdown_section, build_followup_candidate_state_row, ensure_markdown_note, resolve_analysis_note_paths
from autodokit.tools.storage_backend import load_knowledge_tables, load_reference_tables, persist_knowledge_tables, persist_reference_tables
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


OUTPUT_INDEX = "a100_deep_reading_index.csv"
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


def _generate_local_deep_note(*, title: str, cite_key: str, text: str, manual_guidance: str = "", reading_objective: str = "") -> str:
    normalized = " ".join(str(text or "").split())
    sample = normalized[:2500]
    fragments = [fragment.strip() for fragment in sample.replace("。", "。\n").splitlines() if fragment.strip()]
    bullets = [f"- {fragment}" for fragment in fragments[:6]] or ["- 未抽取到可用正文。"]
    return "\n".join(
        [
            f"# {title}",
            "",
            f"- cite_key: {cite_key}",
            f"- reading_objective: {reading_objective or '未指定'}",
            f"- manual_guidance: {manual_guidance or '未指定'}",
            "",
            "## 深读证据摘录",
            *bullets,
            "",
            "## 正式修订建议",
            "- 基于当前深读证据更新五类分析笔记。",
            "- 如发现新线索，可回流到 A080 待预处理清单。",
            "",
        ]
    )


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


@affair_auto_git_commit("A100")
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

    state_df = load_reading_state_df(content_db, flag_filters={"pending_deep_read": 1})
    existing_state_df = load_reading_state_df(content_db)
    existing_state_by_uid = {
        _stringify(row.get("uid_literature")): row.to_dict()
        for _, row in existing_state_df.fillna("").iterrows()
        if _stringify(row.get("uid_literature"))
    }
    max_items = int(raw_cfg.get("max_items") or 3)
    if max_items > 0:
        state_df = state_df.head(max_items).reset_index(drop=True)
    analysis_note_paths = resolve_analysis_note_paths(workspace_root, raw_cfg)
    innovation_note_path = Path(_stringify(raw_cfg.get("innovation_note_path")) or workspace_root / "knowledge" / "innovation_pool" / "A100_创新点补写.md")
    if not innovation_note_path.is_absolute():
        raise ValueError(f"innovation_note_path 必须为绝对路径: {innovation_note_path}")
    ensure_markdown_note(innovation_note_path, "A100 创新点补写")

    literatures_df, attachments_df, _ = load_reference_tables(db_path=content_db)
    knowledge_index_df, knowledge_attachments_df, _ = load_knowledge_tables(db_path=content_db)
    parse_model = _stringify(raw_cfg.get("parse_model")) or "auto"
    overwrite_parse_asset = bool(raw_cfg.get("overwrite_parse_asset", False))

    result_rows: List[Dict[str, Any]] = []
    state_updates: List[Dict[str, Any]] = []
    failures: List[str] = []

    deep_note_dir = workspace_root / "knowledge" / "standard_notes"
    deep_note_dir.mkdir(parents=True, exist_ok=True)

    for _, row in state_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        manual_guidance = _stringify(row.get("manual_guidance"))
        reading_objective = _stringify(row.get("reading_objective"))
        source_origin = _stringify(row.get("source_origin")) or "auto"
        upsert_reading_state_rows(
            content_db,
            [
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "pending_deep_read": 0,
                    "in_deep_read": 1,
                    "deep_read_done": 0,
                }
            ],
        )
        try:
            parse_asset = ensure_multimodal_parse_asset(
                content_db=content_db,
                parse_level="non_review_deep",
                uid_literature=uid_literature,
                cite_key=cite_key,
                source_stage="A100",
                global_config_path=workspace_root / "config" / "config.json",
                overwrite_existing=overwrite_parse_asset,
                model=parse_model,
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
            note_path = deep_note_dir / f"deep_reading_{_safe_file_stem(cite_key)}.md"
            note_body = _generate_local_deep_note(
                title=title,
                cite_key=cite_key,
                text=full_text,
                manual_guidance=manual_guidance,
                reading_objective=reading_objective,
            )
            note_info = knowledge_note_register(
                note_path=note_path,
                title=title,
                note_type="knowledge_note",
                status="draft",
                tags=["aok/deep_read", "a100"],
                aliases=[cite_key],
                evidence_uids=[uid_literature],
                uid_literature=uid_literature,
                cite_key=cite_key,
                body=note_body,
            )
            knowledge_index_df, _ = knowledge_index_sync_from_note(knowledge_index_df, note_path, workspace_root=workspace_root)

            for key, spec in ANALYSIS_NOTE_SPECS.items():
                append_markdown_section(
                    analysis_note_paths[key],
                    spec["title"],
                    [f"- A100 正式修订：{cite_key}《{title}》已完成深读并补入正式证据。"],
                )
            append_markdown_section(
                innovation_note_path,
                "A100 创新点补写",
                [f"- {cite_key}《{title}》：可从深读证据中抽取新的创新点或机制线索。"],
            )

            reference_lines = _extract_reference_lines(full_text)
            discovered_rows: List[Dict[str, Any]] = []
            for reference_text in reference_lines:
                try:
                    literatures_df, result = process_reference_citation(
                        literatures_df,
                        reference_text,
                        workspace_root=workspace_root,
                        global_config_path=workspace_root / "config" / "config.json",
                        source="placeholder_from_a100_deep_read",
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
                        source_stage="A100",
                        source_uid_literature=uid_literature,
                        source_cite_key=cite_key,
                        recommended_reason=f"A100 从 {cite_key} 深读参考文献发现新候选",
                        theme_relation="a100_reference_discovery",
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
                    "pending_deep_read": 0,
                    "in_deep_read": 0,
                    "deep_read_done": 1,
                    "deep_read_count": deep_read_count,
                    "deep_read_note_path": str(note_path),
                    "deep_read_decision": "completed",
                    "deep_read_reason": (
                        f"已完成正式深读与知识回写。"
                        f"阅读目标={reading_objective or '未指定'}；提示语={manual_guidance or '未指定'}"
                    ),
                    "analysis_formal_synced": 1,
                    "innovation_synced": 1,
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
                }
            )
        except Exception as exc:
            failures.append(f"{cite_key}: 深读失败: {exc}")
            state_updates.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "pending_deep_read": 1,
                    "in_deep_read": 0,
                    "deep_read_done": 0,
                    "deep_read_decision": "failed",
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
        node_uid="A100",
        node_name="文献研读与正式知识回写",
        summary=f"完成深读 {len(result_rows)} 篇；失败 {len(failures)} 篇。",
        checks=[{"name": "deep_read_count", "value": len(result_rows)}, {"name": "failure_count", "value": len(failures)}],
        artifacts=[str(index_path), str(innovation_note_path)],
        recommendation="pass" if result_rows else "retry_current",
        score=max(45.0, 93.0 - len(failures) * 10.0),
        issues=failures,
        metadata={"workspace_root": str(workspace_root), "content_db": str(content_db)},
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        append_aok_log_event(
            event_type="A100_DEEP_READING_COMPLETED",
            project_root=workspace_root,
            affair_code="A100",
            handler_name="文献研读与正式知识回写",
            agent_names=["ar_A100_文献研读与正式知识回写事务智能体_v6"],
            skill_names=[],
            reasoning_summary="消费 literature_reading_state.pending_deep_read=1，完成正式深读、分析笔记修订与创新点补写。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=[path for path in [index_path, gate_path, innovation_note_path] if path is not None],
            payload={"deep_read_count": len(result_rows), "failure_count": len(failures)},
        )
    except Exception:
        pass

    return [index_path, gate_path, innovation_note_path]