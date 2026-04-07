"""综述研读与研究地图生成事务。

本事务严格承接 A05 预创建资产：
1. 读取 A05 生成的 review_read_pool 与 review_reading_batches；
2. 从综述 PDF 中抽取原文句子与参考文献；
3. 仅在 A05 已存在的标准笔记与分析骨架中做局部回填；
4. 仅更新 A05 已存在的结构化附件文件；
5. 输出 G070 审计报告，不再额外生成平行 Markdown 汇总笔记。

设计边界：
1. 标准文献笔记必须保持无课题化，只忠实回写原文证据与结构。
2. 综述分析笔记允许弱主题引导，用于跨文献整合、脉络归纳与收敛。
3. 研究主题是否参与分析笔记生成，仅由 A070 配置显式控制，不应在标准笔记回写链路中强行注入。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pandas as pd

from autodokit.tools import (
    append_aok_log_event,
    build_review_reading_packet,
    build_gate_review,
    build_reference_quality_summary,
    build_research_trajectory,
    build_review_consensus_rows,
    build_review_controversy_rows,
    build_review_future_rows,
    build_review_general_reading_list,
    build_review_must_read_originals,
    extract_review_state_from_attachment,
    knowledge_bind_literature_standard_note,
    knowledge_index_sync_from_note,
    literature_bind_standard_note,
    load_json_or_py,
    get_current_time_iso,
    process_reference_citation,
    refine_review_state_with_llm,
    sentence_line_from_review_state,
)
from autodokit.tools.contentdb_sqlite import resolve_content_db_config
from autodokit.tools.bibliodb_sqlite import load_reading_queue_df, replace_tags_for_namespace, upsert_reading_queue_rows
from autodokit.tools.storage_backend import (
    load_knowledge_tables,
    load_reference_tables,
    persist_knowledge_tables,
    persist_reference_tables,
)
from autodokit.tools.review_synthesis_tools import extract_review_state_from_structured_file
from autodokit.tools.review_synthesis_tools import (
    build_note_wikilink,
    build_pdf_wikilink,
    generate_evidence_constrained_summary_lines,
    normalize_review_state_field_limits,
    sanitize_note_sentence,
    sentence_to_academic_statement,
)
from autodokit.tools.task_docs import split_frontmatter
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


DEFAULT_TOPIC = "未指定研究主题"
OUTPUT_FILES = {
    "gate_review": "gate_review.json",
}

STRUCTURED_ATTACHMENT_HEADERS: Dict[str, List[str]] = {
    "consensus_list.csv": ["consensus_uid", "topic", "finding", "evidence_notes", "status"],
    "controversy_list.csv": ["controversy_uid", "topic", "controversy", "evidence_notes", "status"],
    "future_directions.csv": ["direction_uid", "topic", "direction", "source_notes", "priority"],
    "must_read_originals.csv": ["uid_literature", "cite_key", "title", "reason", "status"],
    "review_general_reading_list.csv": ["uid_literature", "cite_key", "title", "source_review", "status"],
}

PROCESS_FILE_HEADERS: Dict[str, List[str]] = {
    "reference_citation_mapping.csv": [
        "source_uid_literature",
        "source_cite_key",
        "reference_text",
        "recognized_first_author",
        "recognized_year",
        "recognized_title_raw",
        "matched_uid_literature",
        "matched_cite_key",
        "matched_title",
        "action",
        "parse_method",
        "llm_invoked",
        "parse_failed",
        "parse_failure_reason",
        "suspicious_merged",
        "noise_trimmed",
        "match_score",
        "suspicious_mismatch",
        "reference_note_path",
    ],
}

SENTENCE_GROUP_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "research_problem": ("本文", "文章", "综述", "梳理", "总结", "评述", "探究", "研究"),
    "research_method": ("梳理", "总结", "评述", "分析", "模型", "基于", "角度", "文献"),
    "core_findings": ("影响", "作用", "机制", "路径", "关系", "表明", "发现", "结果"),
    "future_directions": ("建议", "需要", "防范", "提高", "稳定", "至关重要", "应当", "未来"),
}

CONSENSUS_THEME_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("核心对象关联", ("影响", "关系", "作用", "结果")),
    ("关键传导机制", ("机制", "路径", "传导", "中介")),
    ("治理与响应含义", ("防范", "治理", "应对", "建议")),
)

DEFAULT_EVIDENCE_CONSTRAINED_LINE_TARGETS: Dict[str, int] = {
    "领域研究脉络.md": 5,
    "核心成果.md": 5,
    "未来方向.md": 5,
    "领域知识框架.md": 4,
    "创新点补写.md": 6,
}

PLACEHOLDER_HINTS: Tuple[str, ...] = (
    "待 A070",
    "待补充",
    "待根据",
    "待回填",
    "待填写",
    "待扫描",
)


def _note_now_iso() -> str:
    return get_current_time_iso()


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
    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
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


def _a05_dirs(workspace_root: Path) -> Dict[str, Path]:
    knowledge_root = workspace_root / "knowledge"
    return {
        "standard_notes": knowledge_root / "standard_notes",
        "review_summaries": knowledge_root / "review_summaries",
        "trajectories": knowledge_root / "trajectories",
        "frameworks": knowledge_root / "frameworks",
        "innovation_pool": knowledge_root / "innovation_pool",
        "audits": knowledge_root / "audits",
        "batches": workspace_root / "batches" / "review_candidates",
        "views": workspace_root / "views" / "review_candidates",
    }


def _a05_asset_paths(workspace_root: Path) -> Dict[str, Path]:
    dirs = _a05_dirs(workspace_root)
    return {
        "trajectory_seed": dirs["trajectories"] / "领域研究脉络.md",
        "core_findings": dirs["review_summaries"] / "核心成果.md",
        "consensus_notes": dirs["review_summaries"] / "共识点.md",
        "controversy_notes": dirs["review_summaries"] / "争议点.md",
        "future_directions_notes": dirs["review_summaries"] / "未来方向.md",
        "knowledge_framework": dirs["frameworks"] / "领域知识框架.md",
        "innovation_seed": dirs["innovation_pool"] / "创新点补写.md",
        "consensus_csv": dirs["audits"] / "consensus_list.csv",
        "controversy_csv": dirs["audits"] / "controversy_list.csv",
        "future_csv": dirs["audits"] / "future_directions.csv",
        "must_read_csv": dirs["audits"] / "must_read_originals.csv",
        "general_reading_csv": dirs["audits"] / "review_general_reading_list.csv",
        "mapping_csv": dirs["audits"] / "reference_citation_mapping.csv",
        "reference_dump": dirs["audits"] / "引文识别原文.txt",
        "quality_summary": dirs["audits"] / "reference_citation_quality_summary.json",
        "review_reading_batches": dirs["batches"] / "review_reading_batches.csv",
    }


def _load_review_read_pool(raw_cfg: Dict[str, Any], workspace_root: Path, content_db: Path) -> pd.DataFrame:
    csv_value = _stringify(raw_cfg.get("review_read_pool_csv"))
    if csv_value:
        csv_path = Path(csv_value)
        if not csv_path.is_absolute():
            raise ValueError(f"review_read_pool_csv 必须为绝对路径: {csv_path}")
        if csv_path.exists():
            return pd.read_csv(csv_path, dtype=str, keep_default_na=False)

    queue_df = load_reading_queue_df(
        content_db,
        stage="A065",
        only_current=True,
        queue_statuses=["queued", "candidate", "in_progress"],
    )
    if queue_df.empty:
        queue_df = load_reading_queue_df(
            content_db,
            stage="A060",
            only_current=True,
            queue_statuses=["queued", "candidate", "in_progress"],
        )
    if not queue_df.empty:
        return queue_df.fillna("")

    canonical_csv = workspace_root / "views" / "review_candidates" / "review_read_pool.csv"
    if canonical_csv.exists():
        return pd.read_csv(canonical_csv, dtype=str, keep_default_na=False)

    with sqlite3.connect(content_db) as connection:
        try:
            table = pd.read_sql_query("SELECT * FROM review_read_pool", connection)
        except Exception as exc:
            try:
                table = pd.read_sql_query("SELECT * FROM review_read_pool_current_view", connection)
            except Exception as view_exc:
                raise FileNotFoundError(
                    "未找到可用的综述阅读池（A065/A060 队列、review_read_pool 表或 review_read_pool_current_view 视图）。"
                ) from view_exc
    return table.fillna("")


def _resolve_attachment_path(raw_path: str, workspace_root: Path) -> Path | None:
    text = _stringify(raw_path)
    if not text:
        return None

    candidate = Path(text)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    normalized = text.replace("\\", "/")
    trimmed = normalized
    for prefix in ("workspace/", "./workspace/"):
        if trimmed.startswith(prefix):
            trimmed = trimmed[len(prefix) :]
            break

    possible = [
        workspace_root / trimmed,
        workspace_root / normalized,
        workspace_root.parent / trimmed,
        workspace_root.parent / normalized,
        workspace_root / "references" / "attachments" / candidate.name,
        workspace_root.parent / "references" / "attachments" / candidate.name,
    ]
    seen: set[str] = set()
    for item in possible:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        if item.exists() and item.is_file():
            return item
    return None


def _read_pdf_text(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(pdf_path))
        parts: List[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
        if text:
            return text
    except Exception:
        pass

    try:
        from pdfminer.high_level import extract_text  # type: ignore

        text = extract_text(str(pdf_path)) or ""
        if text.strip():
            return text
    except Exception:
        pass

    return ""


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


def _extract_reference_lines_from_text(text: str) -> List[str]:
    try:
        from autodokit.tools.pdf_elements_extractors import extract_references_from_full_text

        structured_refs, _status = extract_references_from_full_text(text)
        extracted = [
            _stringify(item.get("raw_text") or item.get("raw") or item.get("text"))
            for item in structured_refs
        ]
        extracted = [item for item in extracted if item]
        if extracted:
            return extracted
    except Exception:
        pass

    lines = [line.strip() for line in str(text or "").splitlines()]
    if not lines:
        return []

    start_index = -1
    for idx, line in enumerate(lines):
        lower_line = line.lower().strip("# ")
        if lower_line in {"references", "reference", "参考文献"}:
            start_index = idx + 1
            break
    if start_index < 0:
        return []

    output_lines: List[str] = []
    seen: set[str] = set()
    for line in lines[start_index:]:
        if not line:
            continue
        if line.startswith("#"):
            break
        if len(line) < 20:
            continue
        if line in seen:
            continue
        seen.add(line)
        output_lines.append(line)
    return output_lines


def _score_sentence(sentence_obj: Dict[str, Any], keywords: Iterable[str], *, tail_bias: bool = False, total: int = 1) -> float:
    sentence = _stringify(sentence_obj.get("sentence"))
    lowered = sentence.lower()
    position = int(sentence_obj.get("index") or 0)
    score = max(0.0, 120.0 - position)
    for keyword in keywords:
        token = _stringify(keyword)
        if token and token.lower() in lowered:
            score += 24.0
    if any(noise in sentence for noise in ("收稿日期", "基金项目", "作者简介", "关键词")):
        score -= 80.0
    if len(sentence) > 220:
        score -= 10.0
    if tail_bias:
        score += position / max(total, 1) * 30.0
    return score


def _pick_sentences(sentences: Sequence[Dict[str, Any]], keywords: Iterable[str], *, limit: int, tail_bias: bool = False) -> List[Dict[str, Any]]:
    total = len(sentences)
    scored = sorted(
        ((
            _score_sentence(item, keywords, tail_bias=tail_bias, total=total),
            item,
        ) for item in sentences),
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
    sentence = sentence_to_academic_statement(_stringify(sentence_obj.get("sentence")))
    if not sentence:
        return ""
    return f"- {sentence} 见 {build_note_wikilink(cite_key)}。"


def _parse_evidence_note_line(raw_text: str) -> str:
    text = _stringify(raw_text)
    match = re.match(r"(.+?)#句([^:：]+)[:：](.+)", text)
    if not match:
        return f"- {text}" if text else ""
    cite_key, _index, sentence = match.groups()
    cleaned = sentence_to_academic_statement(sentence)
    if not cleaned:
        return ""
    return f"- {cleaned} 见 {build_note_wikilink(_stringify(cite_key))}。"


def _derive_review_dimensions(review_state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    sentences = list(review_state.get("sentences") or [])
    core = list(review_state.get("core_findings") or [])
    future = list(review_state.get("future_directions") or [])
    problem = list(review_state.get("research_problem") or [])
    method = list(review_state.get("research_method") or [])
    mechanism = list(review_state.get("mechanism_paths") or [])
    controversy = list(review_state.get("controversy_points") or [])
    limitation = list(review_state.get("limitation_points") or [])
    supporting = list(review_state.get("supporting_evidence") or [])

    trajectory_points = _pick_sentences(sentences, ("演进", "阶段", "以来", "脉络", "路径"), limit=6) or (problem[:4] + mechanism[:2])
    consensus_candidates = _pick_sentences(supporting or core or sentences, ("表明", "稳定", "普遍", "一致", "共识"), limit=6) or core[:6]
    controversy_candidates = controversy or _pick_sentences(sentences, ("争议", "差异", "分歧", "异质", "边界"), limit=6)
    knowledge_framework_points = mechanism or _pick_sentences(sentences, ("机制", "路径", "变量", "框架", "关系"), limit=8) or (core[:5] + method[:3])

    return {
        "trajectory_points": trajectory_points,
        "core_results": core,
        "consensus_candidates": consensus_candidates,
        "controversy_candidates": controversy_candidates,
        "future_directions": future,
        "knowledge_framework_points": knowledge_framework_points,
        "limitation_points": limitation,
        "supporting_evidence": supporting,
    }


def _resolve_evidence_constrained_line_targets(raw_cfg: Dict[str, Any]) -> Dict[str, int]:
    targets = dict(DEFAULT_EVIDENCE_CONSTRAINED_LINE_TARGETS)
    for note_name, raw_value in dict(raw_cfg or {}).items():
        if note_name not in targets:
            continue
        try:
            targets[note_name] = max(2, int(raw_value))
        except Exception:
            continue
    return targets


def _section_lines_from_sentences(cite_key: str, sentence_objs: Sequence[Dict[str, Any]], *, fallback: str) -> List[str]:
    lines = [sentence_line_from_review_state(cite_key, item) for item in sentence_objs if _stringify(item.get("sentence"))]
    return lines or [f"- {fallback}（cite_key: {cite_key}）"]


def _build_consensus_rows(review_states: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    current_index = 1
    for topic, keywords in CONSENSUS_THEME_DEFS:
        matches: List[Tuple[str, Dict[str, Any]]] = []
        for state in review_states:
            source_sentences = state.get("core_findings") or state.get("sentences") or []
            chosen = _pick_sentences(source_sentences, keywords, limit=1)
            if chosen:
                matches.append((state["cite_key"], chosen[0]))
        if len({cite_key for cite_key, _ in matches}) < 2:
            continue
        rows.append(
            {
                "consensus_uid": f"consensus_{current_index:02d}",
                "topic": topic,
                "finding": topic,
                "evidence_notes": " | ".join(
                    f"{cite_key}#句{_stringify(sentence_obj.get('index'))}:{_stringify(sentence_obj.get('sentence'))}"
                    for cite_key, sentence_obj in matches
                ),
                "status": "validated",
            }
        )
        current_index += 1
    return pd.DataFrame(rows, columns=STRUCTURED_ATTACHMENT_HEADERS["consensus_list.csv"])


def _build_controversy_rows(review_states: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    bank_specific: Tuple[str, Dict[str, Any]] | None = None
    broad_scope: Tuple[str, Dict[str, Any]] | None = None
    for state in review_states:
        for sentence_obj in state.get("core_findings") or state.get("sentences") or []:
            sentence = _stringify(sentence_obj.get("sentence"))
            if bank_specific is None and all(keyword in sentence for keyword in ("银行", "系统性风险")):
                bank_specific = (state["cite_key"], sentence_obj)
            if broad_scope is None and any(keyword in sentence for keyword in ("样本", "范围", "情境", "对象", "条件")):
                broad_scope = (state["cite_key"], sentence_obj)
    if bank_specific and broad_scope and bank_specific[0] != broad_scope[0]:
        rows.append(
            {
                "controversy_uid": "controversy_01",
                "topic": "研究范围差异",
                "controversy": "研究范围差异",
                "evidence_notes": (
                    f"{bank_specific[0]}#句{_stringify(bank_specific[1].get('index'))}:{_stringify(bank_specific[1].get('sentence'))}"
                    f" | {broad_scope[0]}#句{_stringify(broad_scope[1].get('index'))}:{_stringify(broad_scope[1].get('sentence'))}"
                ),
                "status": "observed",
            }
        )
    return pd.DataFrame(rows, columns=STRUCTURED_ATTACHMENT_HEADERS["controversy_list.csv"])


def _build_future_rows(review_states: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for review_index, state in enumerate(review_states, start=1):
        for sentence_obj in state.get("future_directions") or []:
            rows.append(
                {
                    "direction_uid": f"direction_{review_index:02d}_{_stringify(sentence_obj.get('index'))}",
                    "topic": DEFAULT_TOPIC,
                    "direction": _stringify(sentence_obj.get("sentence")),
                    "source_notes": f"{state['cite_key']}#句{_stringify(sentence_obj.get('index'))}",
                    "priority": "high" if review_index <= 2 else "medium",
                }
            )
    return pd.DataFrame(rows, columns=STRUCTURED_ATTACHMENT_HEADERS["future_directions.csv"])


def _build_must_read_originals(review_states: Sequence[Dict[str, Any]], literature_table: pd.DataFrame, mapping_rows: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    if not mapping_rows:
        return pd.DataFrame(columns=STRUCTURED_ATTACHMENT_HEADERS["must_read_originals.csv"])

    mapping = pd.DataFrame(mapping_rows).fillna("")
    review_cites = {state["cite_key"] for state in review_states}
    review_uids = {state["uid_literature"] for state in review_states}
    filtered = mapping[
        mapping["source_cite_key"].astype(str).isin(review_cites)
        & mapping["matched_uid_literature"].astype(str).ne("")
        & ~mapping["matched_uid_literature"].astype(str).isin(review_uids)
        & mapping["suspicious_mismatch"].astype(str).isin(["", "0"])
        & mapping["parse_failed"].astype(str).isin(["", "0"])
    ].copy()
    if filtered.empty:
        return pd.DataFrame(columns=STRUCTURED_ATTACHMENT_HEADERS["must_read_originals.csv"])

    lookup = literature_table[[column for column in ["uid_literature", "cite_key", "title"] if column in literature_table.columns]].copy()
    grouped = filtered.groupby(["matched_uid_literature", "matched_cite_key"], as_index=False).agg(source_count=("source_cite_key", "nunique"))
    merged = grouped.merge(lookup, how="left", left_on="matched_uid_literature", right_on="uid_literature")
    merged = merged.sort_values(by=["source_count", "matched_cite_key"], ascending=[False, True]).head(20)
    rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        count = int(float(_stringify(row.get("source_count")) or "0"))
        rows.append(
            {
                "uid_literature": _stringify(row.get("matched_uid_literature")),
                "cite_key": _stringify(row.get("matched_cite_key")),
                "title": _stringify(row.get("title")) or _stringify(row.get("matched_cite_key")),
                "reason": f"被 {count} 篇综述高置信引用",
                "status": "backlog",
            }
        )
    return pd.DataFrame(rows, columns=STRUCTURED_ATTACHMENT_HEADERS["must_read_originals.csv"])


def _build_general_reading_list(review_states: Sequence[Dict[str, Any]], literature_table: pd.DataFrame, mapping_rows: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    if not mapping_rows:
        return pd.DataFrame(columns=STRUCTURED_ATTACHMENT_HEADERS["review_general_reading_list.csv"])

    mapping = pd.DataFrame(mapping_rows).fillna("")
    review_cites = {state["cite_key"] for state in review_states}
    filtered = mapping[
        mapping["source_cite_key"].astype(str).isin(review_cites)
        & mapping["matched_uid_literature"].astype(str).ne("")
        & mapping["parse_failed"].astype(str).isin(["", "0"])
    ].copy()
    if filtered.empty:
        return pd.DataFrame(columns=STRUCTURED_ATTACHMENT_HEADERS["review_general_reading_list.csv"])

    lookup = literature_table[[column for column in ["uid_literature", "cite_key", "title"] if column in literature_table.columns]].copy()
    grouped = filtered.groupby(["matched_uid_literature", "matched_cite_key"], as_index=False).agg(
        source_review=("source_cite_key", lambda values: " | ".join(sorted({str(value).strip() for value in values if str(value).strip()})))
    )
    merged = grouped.merge(lookup, how="left", left_on="matched_uid_literature", right_on="uid_literature")
    merged = merged.sort_values(by=["matched_cite_key"], ascending=[True]).head(50)
    rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        rows.append(
            {
                "uid_literature": _stringify(row.get("matched_uid_literature")),
                "cite_key": _stringify(row.get("matched_cite_key")),
                "title": _stringify(row.get("title")) or _stringify(row.get("matched_cite_key")),
                "source_review": _stringify(row.get("source_review")),
                "status": "candidate",
            }
        )
    return pd.DataFrame(rows, columns=STRUCTURED_ATTACHMENT_HEADERS["review_general_reading_list.csv"])


def _is_placeholder_line(line: str) -> bool:
    stripped = _stringify(line)
    if not stripped:
        return True
    return any(hint in stripped for hint in PLACEHOLDER_HINTS)


def _merge_section_lines(existing_text: str, new_lines: Sequence[str]) -> List[str]:
    existing_lines = [line.rstrip() for line in str(existing_text or "").splitlines()]
    kept_existing = [line for line in existing_lines if not _is_placeholder_line(line)]
    merged = kept_existing[:]
    seen = {_stringify(line) for line in kept_existing if _stringify(line)}
    for line in new_lines:
        text = _stringify(line)
        if not text or text in seen:
            continue
        merged.append(line.rstrip())
        seen.add(text)
    if merged:
        return merged
    if new_lines:
        return [line.rstrip() for line in new_lines if _stringify(line)]
    return kept_existing or existing_lines


def _upsert_section(body: str, heading: str, new_lines: Sequence[str], *, before_heading: str | None = None) -> str:
    pattern = re.compile(rf"(?ms)^## {re.escape(heading)}\s*$\n?(.*?)(?=^## |\Z)")
    match = pattern.search(body)
    section_lines = _merge_section_lines(match.group(1) if match else "", new_lines)
    section_text = f"## {heading}\n" + "\n".join(section_lines).rstrip() + "\n\n"
    if match:
        return body[: match.start()] + section_text + body[match.end() :]

    if before_heading:
        anchor_pattern = re.compile(rf"(?m)^## {re.escape(before_heading)}\s*$")
        anchor_match = anchor_pattern.search(body)
        if anchor_match:
            return body[: anchor_match.start()] + section_text + body[anchor_match.start() :]

    suffix = "" if body.endswith("\n") else "\n"
    return body.rstrip() + suffix + "\n" + section_text


def _read_markdown(path: Path) -> Tuple[str, str, str]:
    text = path.read_text(encoding="utf-8")
    return split_frontmatter(text)


def _update_frontmatter_updated(frontmatter: str) -> str:
    updated_value = _note_now_iso()
    if re.search(r"(?m)^updated\s*:", frontmatter):
        return re.sub(r"(?m)^updated\s*:\s*.*$", f'updated: "{updated_value}"', frontmatter)
    return (frontmatter.rstrip() + "\n" if frontmatter.strip() else "") + f'updated: "{updated_value}"'


def _write_markdown(path: Path, prefix: str, frontmatter: str, body: str) -> None:
    body_text = body.rstrip() + "\n"
    if frontmatter.strip():
        content = f"{prefix}---\n{frontmatter.strip()}\n---\n\n{body_text}"
    else:
        content = f"{prefix}{body_text}"
    path.write_text(content, encoding="utf-8")


def _resolve_existing_standard_note_path(directory: Path, cite_key: str) -> Path | None:
    candidates = [directory / f"{cite_key}.md", directory / f"{_safe_file_stem(cite_key)}.md"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _sync_note(
    knowledge_index: pd.DataFrame,
    *,
    note_path: Path,
    workspace_root: Path,
    uid_literature: str = "",
    cite_key: str = "",
) -> Tuple[pd.DataFrame, str]:
    if uid_literature or cite_key:
        try:
            knowledge_bind_literature_standard_note(note_path, uid_literature, cite_key)
        except Exception:
            pass
    updated_index, note_row = knowledge_index_sync_from_note(knowledge_index, note_path, workspace_root=workspace_root)
    return updated_index, _stringify((note_row or {}).get("uid_knowledge"))


def _append_dump_sections(path: Path, sections: Sequence[Tuple[str, Sequence[str]]]) -> None:
    blocks: List[str] = []
    for title, lines in sections:
        blocks.append(f"## {title}")
        if lines:
            blocks.extend([_stringify(line) for line in lines if _stringify(line)])
        else:
            blocks.append("- 未提取到参考文献")
        blocks.append("")
    path.write_text("\n".join(blocks).strip() + "\n", encoding="utf-8")


def _write_dataframe_if_exists(table: pd.DataFrame, path: Path, missing_assets: List[str], asset_label: str) -> Path | None:
    if not path.exists():
        missing_assets.append(f"{asset_label}: 缺少 A05 预创建文件 {path}")
        return None
    table.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _update_batch_file(path: Path, review_states: Sequence[Dict[str, Any]], missing_assets: List[str]) -> Path | None:
    if not path.exists():
        missing_assets.append(f"review_reading_batches: 缺少 A05 预创建文件 {path}")
        return None
    batch_df = pd.read_csv(path, dtype=str, keep_default_na=False)
    completed_uids = {state["uid_literature"] for state in review_states if _stringify(state.get("uid_literature"))}
    completed_cites = {state["cite_key"] for state in review_states if _stringify(state.get("cite_key"))}
    if "a06_status" not in batch_df.columns:
        batch_df["a06_status"] = ""
    if "a06_note_filled" not in batch_df.columns:
        batch_df["a06_note_filled"] = ""
    if "a070_status" not in batch_df.columns:
        batch_df["a070_status"] = ""
    if "a070_note_filled" not in batch_df.columns:
        batch_df["a070_note_filled"] = ""
    for idx, row in batch_df.iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        is_completed = uid_literature in completed_uids or cite_key in completed_cites
        batch_df.at[idx, "a06_status"] = "completed" if is_completed else (_stringify(row.get("a06_status")) or "pending")
        batch_df.at[idx, "a06_note_filled"] = "1" if is_completed else (_stringify(row.get("a06_note_filled")) or "0")
        batch_df.at[idx, "a070_status"] = "completed" if is_completed else (_stringify(row.get("a070_status")) or "pending")
        batch_df.at[idx, "a070_note_filled"] = "1" if is_completed else (_stringify(row.get("a070_note_filled")) or "0")
    batch_df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _build_literature_lookup(literature_table: pd.DataFrame) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_uid: dict[str, dict[str, Any]] = {}
    by_cite: dict[str, dict[str, Any]] = {}
    if literature_table is None or literature_table.empty:
        return by_uid, by_cite
    for _, row in literature_table.fillna("").iterrows():
        payload = row.to_dict()
        uid_literature = _stringify(payload.get("uid_literature"))
        cite_key = _stringify(payload.get("cite_key"))
        if uid_literature:
            by_uid[uid_literature] = payload
        if cite_key:
            by_cite[cite_key] = payload
    return by_uid, by_cite


def _enrich_identity(table: pd.DataFrame, literature_table: pd.DataFrame) -> pd.DataFrame:
    if table is None or table.empty:
        return table.copy()
    working = table.copy()
    by_uid, by_cite = _build_literature_lookup(literature_table)
    for idx, row in working.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        matched = by_uid.get(uid_literature) if uid_literature else None
        if matched is None and cite_key:
            matched = by_cite.get(cite_key)
        if matched is None:
            continue
        if not uid_literature:
            working.at[idx, "uid_literature"] = _stringify(matched.get("uid_literature"))
        if not cite_key:
            working.at[idx, "cite_key"] = _stringify(matched.get("cite_key"))
        if not _stringify(row.get("title")):
            working.at[idx, "title"] = _stringify(matched.get("title"))
        if "year" not in working.columns or not _stringify(row.get("year")):
            working.at[idx, "year"] = _stringify(matched.get("year"))
    return working


def _classify_downstream_bucket(title: str, reason: str, year: str) -> str:
    text = f"{_stringify(title)} {_stringify(reason)}".lower()
    if any(token in text for token in ("counter", "contradict", "null", "边界", "反例", "异质")):
        return "counterexample"
    if any(token in text for token in ("method", "identification", "instrument", "did", "rdd", "iv", "方法", "识别")):
        return "method_transfer"
    year_text = _stringify(year)
    if year_text.isdigit() and int(year_text) <= datetime.now(tz=UTC).year - 5:
        return "classical_core"
    return "frontier"


def _build_downstream_candidates(
    must_read_df: pd.DataFrame,
    general_reading_df: pd.DataFrame,
    literature_table: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    must_read = _enrich_identity(must_read_df, literature_table)
    general_reading = _enrich_identity(general_reading_df, literature_table)
    downstream_rows: List[Dict[str, Any]] = []
    queue_rows: List[Dict[str, Any]] = []

    for _, row in must_read.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        title = _stringify(row.get("title"))
        reason = _stringify(row.get("reason")) or "综述高置信引用推荐"
        year = _stringify(row.get("year"))
        bucket = _classify_downstream_bucket(title, reason, year)
        downstream_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "title_or_hint": title or cite_key,
                "class": bucket,
                "recommended_reason": reason,
                "preferred_next_stage": "A080",
                "theme_relation": "review_must_read",
                "priority": 90.0 if bucket == "classical_core" else 84.0,
            }
        )
        queue_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "stage": "A080",
                "source_affair": "A070",
                "queue_status": "queued",
                "priority": 90.0 if bucket == "classical_core" else 84.0,
                "bucket": bucket,
                "preferred_next_stage": "A080",
                "recommended_reason": reason,
                "theme_relation": "review_must_read",
            }
        )

    for _, row in general_reading.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        title = _stringify(row.get("title"))
        reason = _stringify(row.get("source_review")) or "综述一般延伸阅读"
        year = _stringify(row.get("year"))
        bucket = _classify_downstream_bucket(title, reason, year)
        downstream_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "title_or_hint": title or cite_key,
                "class": bucket,
                "recommended_reason": reason,
                "preferred_next_stage": "A090",
                "theme_relation": "review_general_reading",
                "priority": 68.0 if bucket in {"method_transfer", "counterexample"} else 60.0,
            }
        )
        queue_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "stage": "A090",
                "source_affair": "A070",
                "queue_status": "queued",
                "priority": 68.0 if bucket in {"method_transfer", "counterexample"} else 60.0,
                "bucket": bucket,
                "preferred_next_stage": "A090",
                "recommended_reason": reason,
                "theme_relation": "review_general_reading",
            }
        )

    downstream_df = pd.DataFrame(downstream_rows).drop_duplicates(subset=["uid_literature", "cite_key", "preferred_next_stage"], keep="first") if downstream_rows else pd.DataFrame(columns=["uid_literature", "cite_key", "title_or_hint", "class", "recommended_reason", "preferred_next_stage", "theme_relation", "priority"])
    queue_df = pd.DataFrame(queue_rows).drop_duplicates(subset=["stage", "uid_literature", "cite_key"], keep="first") if queue_rows else pd.DataFrame(columns=["uid_literature", "cite_key", "stage", "source_affair", "queue_status", "priority", "bucket", "preferred_next_stage", "recommended_reason", "theme_relation"])
    return downstream_df, queue_df


def _composite_input_lines(review_states: Sequence[Dict[str, Any]]) -> List[str]:
    return [
        f"- {build_note_wikilink(state['cite_key'])}"
        for state in review_states
        if _stringify(state.get("cite_key"))
    ]


def _composite_evidence_lines(review_states: Sequence[Dict[str, Any]], field_name: str, *, limit_per_review: int = 1) -> List[str]:
    lines: List[str] = []
    for state in review_states:
        for sentence_obj in list(state.get(field_name) or [])[:limit_per_review]:
            line = _sentence_line(state["cite_key"], sentence_obj)
            if line:
                lines.append(line)
    return lines


def _consensus_summary_lines(consensus_df: pd.DataFrame) -> List[str]:
    if consensus_df.empty:
        return ["- 本轮未形成满足阈值的综述共识条目。"]
    rows: List[str] = []
    for _, row in consensus_df.iterrows():
        rows.append(f"- { _stringify(row.get('topic')) }：{ _stringify(row.get('finding')) or _stringify(row.get('topic')) }")
    return rows


def _controversy_summary_lines(controversy_df: pd.DataFrame) -> List[str]:
    if controversy_df.empty:
        return ["- 本轮未识别出稳定的综述争议条目。"]
    rows: List[str] = []
    for _, row in controversy_df.iterrows():
        rows.append(f"- { _stringify(row.get('topic')) }：{ _stringify(row.get('controversy')) or _stringify(row.get('topic')) }")
    return rows


def _future_summary_lines(future_df: pd.DataFrame) -> List[str]:
    if future_df.empty:
        return ["- 本轮未形成可回填的未来研究方向条目。"]
    return [f"- {_stringify(row.get('direction'))}" for _, row in future_df.iterrows()]


def _parse_evidence_column(series: pd.Series) -> List[str]:
    output: List[str] = []
    for value in series.astype(str).tolist():
        for chunk in [item.strip() for item in value.split("|") if item.strip()]:
            line = _parse_evidence_note_line(chunk)
            if line and line not in output:
                output.append(line)
    return output


def _framework_summary_lines(consensus_df: pd.DataFrame, future_df: pd.DataFrame) -> List[str]:
    lines: List[str] = []
    if not consensus_df.empty:
        lines.append("- 当前证据显示核心对象之间存在稳定关联，可围绕关键变量、传导路径与治理响应构建知识框架。")
    if not future_df.empty:
        lines.append("- 后续框架可继续围绕外部扰动、作用机制、主体行为、结果度量与响应策略分层扩展。")
    if not lines:
        lines.append("- 本轮尚未形成足够证据来充实领域知识框架。")
    return lines


def _innovation_summary_lines(review_states: Sequence[Dict[str, Any]], future_df: pd.DataFrame) -> List[str]:
    lines: List[str] = []
    if not future_df.empty:
        for _, row in future_df.head(5).iterrows():
            direction = sanitize_note_sentence(_stringify(row.get("direction")))
            if not direction:
                continue
            lines.append(f"- 可转化创新切口：围绕“{direction}”细化为可检验的研究命题。")
    if not lines:
        for state in review_states[:3]:
            sentence_objs = list(state.get("future_directions") or state.get("core_results") or [])[:1]
            for item in sentence_objs:
                sentence = sanitize_note_sentence(_stringify(item.get("sentence")))
                if sentence:
                    lines.append(f"- 可围绕“{sentence}”构造更聚焦的创新点与识别策略。")
    if not lines:
        lines.append("- 当前尚未形成稳定创新点，需要继续从综述高频引用的原始研究中提炼差异化切口。")
    return lines


def _title_from_body(body: str, fallback: str) -> str:
    match = re.search(r"(?m)^#\s+(.+)$", body)
    return _stringify(match.group(1)) if match else fallback


def _build_display_citation(cite_key: str) -> str:
    return build_note_wikilink(cite_key)


def _normalize_reference_match_token(text: str) -> str:
    value = _stringify(text).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", value)


def _reference_author_variants(first_author: str) -> List[str]:
    author = _stringify(first_author)
    if not author:
        return []
    variants = {
        _normalize_reference_match_token(author),
        _normalize_reference_match_token(re.sub(r"(?i)\bet\s*al\.?$", "", author)),
        _normalize_reference_match_token(re.sub(r"等$", "", author)),
    }
    for part in re.split(r"\s+", author):
        token = _normalize_reference_match_token(part)
        if token:
            variants.add(token)
    return [item for item in variants if item]


def _build_reference_display_label(mention: Dict[str, Any]) -> str:
    author_year_label = _stringify(mention.get("author_year_label"))
    title = sanitize_note_sentence(_stringify(mention.get("recognized_title_raw") or mention.get("matched_title")))
    duplicate_count = int(mention.get("duplicate_author_year_count") or 0)
    if duplicate_count > 1 and title:
        short_title = title[:12] + "…" if len(title) > 12 else title
        if author_year_label:
            return f"{author_year_label}，{short_title}"
        return short_title
    return author_year_label


def _extract_inline_reference_links(sentence: str, reference_mentions: Sequence[Dict[str, Any]]) -> List[str]:
    normalized_sentence = _normalize_reference_match_token(sentence)
    links: List[str] = []
    seen: set[str] = set()
    for mention in reference_mentions:
        cite_key = _stringify(mention.get("matched_cite_key"))
        year = _stringify(mention.get("recognized_year"))
        if not cite_key or not year or year not in sentence:
            continue
        variants = _reference_author_variants(_stringify(mention.get("recognized_first_author")))
        if variants and not any(token in normalized_sentence for token in variants):
            continue
        if cite_key in seen:
            continue
        seen.add(cite_key)
        display_text = _build_reference_display_label(mention)
        links.append(build_note_wikilink(cite_key, display_text=display_text or None))
    return links


def _sentence_points(
    sentence_objs: Sequence[Dict[str, Any]],
    cite_key: str,
    *,
    reference_mentions: Sequence[Dict[str, Any]] | None = None,
    prefix: str = "- ",
) -> List[str]:
    lines: List[str] = []
    for item in sentence_objs:
        sentence = sentence_to_academic_statement(_stringify(item.get("sentence")))
        if not sentence:
            continue
        inline_links = _extract_inline_reference_links(sentence, reference_mentions or [])
        if inline_links:
            lines.append(f"{prefix}{sentence} 见 {_build_display_citation(cite_key)}；相关原始研究：{'、'.join(inline_links)}。")
            continue
        lines.append(f"{prefix}{sentence} 见 {_build_display_citation(cite_key)}。")
    return lines


def _derive_pdf_link(workspace_root: Path, review_state: Dict[str, Any], literature_record: Dict[str, Any]) -> str:
    for candidate in [
        _stringify(review_state.get("attachment_path")),
        _stringify(literature_record.get("pdf_path")),
    ]:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists() and path.is_file():
            try:
                return build_pdf_wikilink(path, workspace_root=workspace_root)
            except Exception:
                continue
    return ""


def _keywords_from_record(literature_record: Dict[str, Any]) -> str:
    for field_name in ["keywords", "keyword", "keywords_cn"]:
        value = _stringify(literature_record.get(field_name))
        if value:
            return value
    return ""
    # New function to check for Chinese characters
def _contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", _stringify(text)))

    # New function to score Chinese signals
def _chinese_signal_score(literature_record: Dict[str, Any]) -> tuple[int, bool, str]:
    title = _stringify(literature_record.get("title"))
    keywords_cn = _stringify(literature_record.get("keywords_cn"))
    abstract = _stringify(literature_record.get("abstract"))
    source = _stringify(literature_record.get("source"))
    signals: List[str] = []
    score = 0

    if _contains_chinese(title):
        score += 4
        signals.append("title")
    if keywords_cn:
        score += 3
        signals.append("keywords_cn")
    if _contains_chinese(abstract):
        score += 2
        signals.append("abstract")
    if any(token in source.lower() for token in ("cnki", "万方", "维普", "cssci")):
        score += 3
        signals.append("source")

    return score, bool(signals), "+".join(signals)


def _render_callout(title: str, lines: Sequence[str], *, callout_type: str = "note") -> str:
    output = [f"> [!{callout_type}] {title}"]
    if lines:
        for line in lines:
            text = _stringify(line)
            if text:
                output.append(f"> {text}")
    else:
        output.append("> 当前无可展示内容。")
    return "\n".join(output)


def _render_standard_note_body(
    body_title: str,
    review_state: Dict[str, Any],
    literature_record: Dict[str, Any],
    *,
    workspace_root: Path,
) -> str:
    cite_key = _stringify(review_state.get("cite_key"))
    title = _stringify(literature_record.get("title")) or body_title
    year = _stringify(literature_record.get("year")) or _stringify(review_state.get("year")) or "未知"
    keywords = _keywords_from_record(literature_record) or "待补充"
    pdf_link = _derive_pdf_link(workspace_root, review_state, literature_record)
    note_link = build_note_wikilink(cite_key)
    reference_mentions = list(review_state.get("reference_mentions") or [])
    research_problem = _sentence_points(review_state.get("research_problem") or [], cite_key, reference_mentions=reference_mentions)
    methods = _sentence_points(review_state.get("research_method") or [], cite_key, reference_mentions=reference_mentions)
    trajectory = _sentence_points(review_state.get("trajectory_points") or [], cite_key, reference_mentions=reference_mentions)
    core = _sentence_points(review_state.get("core_results") or [], cite_key, reference_mentions=reference_mentions)
    consensus = _sentence_points(review_state.get("consensus_candidates") or [], cite_key, reference_mentions=reference_mentions)
    controversy = _sentence_points(review_state.get("controversy_candidates") or [], cite_key, reference_mentions=reference_mentions)
    future = _sentence_points(review_state.get("future_directions") or [], cite_key, reference_mentions=reference_mentions)
    framework = _sentence_points(review_state.get("knowledge_framework_points") or [], cite_key, reference_mentions=reference_mentions)
    references = list(review_state.get("reference_entries") or [f"- {note_link}"])
    evidence = _sentence_points((review_state.get("core_findings") or [])[:5], cite_key, reference_mentions=reference_mentions)

    if not consensus:
        consensus = [f"- 该综述更偏向整合已有解释框架，本轮尚未抽取出足以单独支撑稳定共识命题的独立表述，需结合其被引原始研究进一步核验。见 {note_link}。"]
    if not controversy:
        controversy = [f"- 当前未从该综述中抽取出足以支撑稳定争议命题的直接表述；后续宜回到其引用的原始研究比较结论边界。见 {note_link}。"]
    if not future:
        future = [f"- 该综述对后续阅读的启发主要在于继续追踪其引用的机制研究、政策评估研究与银行风险传导研究。见 {note_link}。"]

    sections = [
        f"# {body_title}",
        "",
        "## 文献信息",
        f"- 标题：{title}",
        f"- 年份：{year}",
        f"- 关键词：{keywords}",
        f"- 标准笔记：{note_link}",
        f"- 原文入口：{pdf_link or '待补充原文 PDF 链接'}",
        "",
        "## 研究对象与综述边界",
        "",
        "## 综述问题意识",
        *(research_problem or [f"- 该文试图组织既有问题意识与解释路径，但当前自动抽取尚未形成更细的问题意识分层。见 {note_link}。"]),
        "",
        "## 文献组织方式与综述方法",
        *(methods or [f"- 当前可确认该文属于综述型文献，但其文献组织方式仍需结合正文结构进一步精读。见 {note_link}。"]),
        "",
        "## 核心研究脉络",
        *(trajectory or [f"- 当前尚未从自动抽取结果中形成稳定的阶段性研究脉络，需要结合全文结构继续凝练。见 {note_link}。"]),
        "",
        "## 主要共识",
        *consensus,
        "",
        "## 关键争议",
        *controversy,
        "",
        "## 方法谱系与证据类型",
        *(methods or [f"- 现有抽取结果只能确认其主要依靠综述式整理与文献归纳，细分方法谱系仍待结合被引文献补充。见 {note_link}。"]),
        "",
        "## 研究缺口与可继续追踪的问题",
        *future,
        "",
        "## 综述使用说明",
        f"- 本标准笔记只忠实回写该综述自身的研究对象、证据与论述结构，不主动引入外部课题设定或下游研究主题。见 {note_link}。",
        "",
        "## 原文入口与参考文献导航",
        f"- 原文 PDF：{pdf_link or '待补充'}",
        *references,
        "",
        _render_callout("证据摘录", evidence, callout_type="quote"),
        "",
    ]
    return "\n".join(sections).rstrip() + "\n"


def _render_composite_note_body(
    note_name: str,
    body_title: str,
    *,
    input_lines: Sequence[str],
    summary_lines: Sequence[str],
    evidence_lines: Sequence[str],
    review_states: Sequence[Dict[str, Any]],
) -> str:
    input_block = list(input_lines) or ["- 当前没有可用的输入综述。"]
    summary_block = list(summary_lines) or ["- 当前没有形成稳定的综合结论。"]
    evidence_block = list(evidence_lines) or ["- 当前没有可回链的证据条目。"]

    if note_name == "领域研究脉络.md":
        sections = [
            f"# {body_title}",
            "",
            "## 输入综述",
            *input_block,
            "",
            "## 问题意识演进",
            *summary_block,
            "",
            "## 阶段性转向",
            "- 当前综述样本显示，研究重心已由一般房价波动事实描述，逐步转向传导机制、政策调控与金融稳定后果的综合讨论。",
            "",
            "## 对当前课题的启发",
            "- 后续应把房价波动研究与银行系统性风险研究对齐，重点比较抵押品渠道、信贷扩张渠道与风险传染渠道。",
            "",
            _render_callout("证据摘录", evidence_block, callout_type="quote"),
            "",
        ]
        return "\n".join(sections).rstrip() + "\n"

    if note_name == "领域知识框架.md":
        sections = [
            f"# {body_title}",
            "",
            "## 输入综述",
            *input_block,
            "",
            "## 核心对象",
            "- 当前综述共同围绕房价波动、信贷供给、银行风险承担与宏观金融稳定之间的联动展开。",
            "",
            "## 作用机制",
            *summary_block,
            "",
            "## 证据边界",
            "- 现有综述能够覆盖供需、预期、政策和金融传导等主线，但不同综述对样本范围、对象层级和结果变量的界定并不完全一致。",
            "",
            "## 政策与研究含义",
            "- 后续框架应继续细化为“核心对象 - 机制路径 - 结果变量 - 边界条件 - 政策响应”五层结构。",
            "",
            _render_callout("支撑证据", evidence_block, callout_type="quote"),
            "",
        ]
        return "\n".join(sections).rstrip() + "\n"

    if note_name == "共识点.md":
        sections = [
            f"# {body_title}",
            "",
            "## 共识命题",
            *summary_block,
            "",
            "## 稳定支持来源",
            *input_block,
            "",
            "## 对当前课题的含义",
            "- 可优先把这些共识作为后续构造研究问题与机制图的稳定背景，而不是直接当作待检验创新点。",
            "",
            _render_callout("证据摘录", evidence_block, callout_type="quote"),
            "",
        ]
        return "\n".join(sections).rstrip() + "\n"

    if note_name == "争议点.md":
        sections = [
            f"# {body_title}",
            "",
            "## 争议主题",
            *summary_block,
            "",
            "## 分歧来源",
            "- 现阶段分歧主要来自研究对象范围、样本时段、解释机制与结果变量口径差异。",
            "",
            "## 当前判断",
            "- 在缺少进一步原始研究比对前，当前更适合把这些分歧视为边界条件，而不是简单判定某一派结论绝对成立。",
            "",
            "## 待检验问题",
            "- 后续应补读被综述高频引用的原始研究，以确认争议究竟来自样本差异、模型设定还是机制识别差异。",
            "",
            _render_callout("证据摘录", evidence_block, callout_type="quote"),
            "",
        ]
        return "\n".join(sections).rstrip() + "\n"

    if note_name == "未来方向.md":
        sections = [
            f"# {body_title}",
            "",
            "## 后续阅读方向",
            *summary_block,
            "",
            "## 可转化研究问题",
            "- 可进一步围绕房价波动如何经由信贷和抵押品渠道影响银行系统性风险来细化研究问题。",
            "",
            "## 优先补读对象",
            *input_block,
            "",
            _render_callout("证据摘录", evidence_block, callout_type="quote"),
            "",
        ]
        return "\n".join(sections).rstrip() + "\n"

    if note_name == "创新点补写.md":
        sections = [
            f"# {body_title}",
            "",
            "## 输入综述",
            *input_block,
            "",
            "## 潜在创新切口",
            *summary_block,
            "",
            "## 与当前课题的对接方式",
            "- 这里的创新点不直接等同于综述建议，而是把综述暴露出的机制空白、证据边界和识别不足转化为当前课题可执行的问题。",
            "",
            "## 后续验证方向",
            "- 后续应将这些创新切口与数据可得性、识别策略和变量操作化方案联动校验。",
            "",
            _render_callout("证据摘录", evidence_block, callout_type="quote"),
            "",
        ]
        return "\n".join(sections).rstrip() + "\n"

    sections = [
        f"# {body_title}",
        "",
        "## 输入综述",
        *input_block,
        "",
        "## 综合结论",
        *summary_block,
        "",
        _render_callout("证据摘录", evidence_block, callout_type="quote"),
        "",
    ]
    return "\n".join(sections).rstrip() + "\n"


def _update_composite_note(
    knowledge_index: pd.DataFrame,
    *,
    note_path: Path,
    workspace_root: Path,
    input_lines: Sequence[str],
    summary_lines: Sequence[str],
    evidence_lines: Sequence[str],
    missing_assets: List[str],
    review_states: Sequence[Dict[str, Any]],
) -> Tuple[pd.DataFrame, bool]:
    if not note_path.exists():
        missing_assets.append(f"{note_path.name}: 缺少 A05 预创建笔记 {note_path}")
        return knowledge_index, False

    prefix, frontmatter, body = _read_markdown(note_path)
    updated_body = _render_composite_note_body(
        note_path.name,
        _title_from_body(body, note_path.stem),
        input_lines=input_lines,
        summary_lines=summary_lines,
        evidence_lines=evidence_lines,
        review_states=review_states,
    )
    updated_frontmatter = _update_frontmatter_updated(frontmatter)
    _write_markdown(note_path, prefix, updated_frontmatter, updated_body)
    updated_index, _ = _sync_note(knowledge_index, note_path=note_path, workspace_root=workspace_root)
    return updated_index, True


def _update_standard_note(
    knowledge_index: pd.DataFrame,
    *,
    note_path: Path,
    workspace_root: Path,
    uid_literature: str,
    cite_key: str,
    sections: Dict[str, Sequence[str]],
    missing_assets: List[str],
    review_state: Dict[str, Any] | None = None,
    literature_record: Dict[str, Any] | None = None,
) -> Tuple[pd.DataFrame, str, bool]:
    if not note_path.exists():
        missing_assets.append(f"{cite_key}: 缺少 A05 预创建标准笔记 {note_path}")
        return knowledge_index, "", False

    prefix, frontmatter, body = _read_markdown(note_path)
    if review_state is not None and literature_record is not None:
        updated_body = _render_standard_note_body(
            _title_from_body(body, cite_key),
            review_state,
            literature_record,
            workspace_root=workspace_root,
        )
    else:
        updated_body = body
        for heading, lines in sections.items():
            before_heading = "参考文献列表" if heading != "参考文献列表" else None
            updated_body = _upsert_section(updated_body, heading, lines, before_heading=before_heading)
    updated_frontmatter = _update_frontmatter_updated(frontmatter)
    _write_markdown(note_path, prefix, updated_frontmatter, updated_body)
    updated_index, note_uid = _sync_note(
        knowledge_index,
        note_path=note_path,
        workspace_root=workspace_root,
        uid_literature=uid_literature,
        cite_key=cite_key,
    )
    return updated_index, note_uid, True


@affair_auto_git_commit("A070")
def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    output_dir = _resolve_output_dir(config_path, raw_cfg)
    asset_paths = _a05_asset_paths(workspace_root)
    content_db_path, db_input_key = resolve_content_db_config(raw_cfg)

    if content_db_path is None:
        content_db_path = (workspace_root / "database" / "content" / "content.db").resolve()
        db_input_key = "default"
    global_config_path = workspace_root / "config" / "config.json"
    if not global_config_path.exists():
        global_config_path = None
    enable_review_state_llm = bool(raw_cfg.get("enable_review_state_llm", True))
    review_state_model = _stringify(raw_cfg.get("review_state_model") or raw_cfg.get("single_document_model"))
    review_state_max_chars = int(raw_cfg.get("review_state_max_chars") or 24000)
    analysis_note_cfg = dict(raw_cfg.get("analysis_note_generation") or {})
    single_review_cfg = dict(raw_cfg.get("single_review_materialization") or {})
    review_state_field_limits = normalize_review_state_field_limits(single_review_cfg.get("field_limits") or {})
    evidence_writing_cfg = dict(raw_cfg.get("evidence_constrained_writing") or {})
    evidence_writing_enabled = bool(evidence_writing_cfg.get("enabled", False))
    evidence_writer_model = _stringify(evidence_writing_cfg.get("writer_model") or analysis_note_cfg.get("writer_model") or raw_cfg.get("synthesis_model")) or None
    evidence_line_targets = _resolve_evidence_constrained_line_targets(evidence_writing_cfg.get("line_targets") or {})
    max_evidence_per_review = int(evidence_writing_cfg.get("max_evidence_per_review") or 3)
    provide_research_topic = bool(analysis_note_cfg.get("provide_research_topic", False))
    synthesis_research_topic = _stringify(raw_cfg.get("research_topic") or raw_cfg.get("topic")) if provide_research_topic else ""

    review_read_pool = _load_review_read_pool(raw_cfg, workspace_root, content_db_path)
    literature_table, attachment_table, _ = load_reference_tables(db_path=content_db_path)
    knowledge_index, knowledge_attachments, _ = load_knowledge_tables(db_path=content_db_path)

    review_states: List[Dict[str, Any]] = []
    artifacts: List[Path] = []
    missing_attachments: List[str] = []
    missing_text: List[str] = []
    missing_assets: List[str] = []
    mapping_rows: List[Dict[str, Any]] = []
    dump_sections: List[Tuple[str, Sequence[str]]] = []

    for _, row in review_read_pool.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        literature_rows = literature_table[literature_table.get("uid_literature", pd.Series(dtype=str)).astype(str) == uid_literature]
        if literature_rows.empty:
            missing_attachments.append(f"{cite_key}: 文献主表缺失")
            continue
        literature_record = literature_rows.iloc[0].to_dict()
        attachments = attachment_table[attachment_table.get("uid_literature", pd.Series(dtype=str)).astype(str) == uid_literature].copy()
        if not attachments.empty:
            attachments = attachments.sort_values(by=["is_primary", "attachment_name"], ascending=[False, True])

        structured_abs_path = _stringify(literature_record.get("structured_abs_path"))
        pdf_path = None
        for attachment_row in attachments.to_dict(orient="records"):
            pdf_path = _resolve_attachment_path(_stringify(attachment_row.get("storage_path") or attachment_row.get("source_path")), workspace_root)
            if pdf_path is not None:
                break
        if pdf_path is None:
            pdf_path = _resolve_attachment_path(_stringify(literature_record.get("pdf_path")), workspace_root)

        if structured_abs_path:
            structured_path = Path(structured_abs_path)
            if structured_path.is_absolute() and structured_path.exists() and structured_path.is_file():
                review_state = extract_review_state_from_structured_file(
                    str(structured_path),
                    uid_literature=uid_literature,
                    cite_key=cite_key,
                    title=_stringify(literature_record.get("title")) or cite_key,
                    year=_stringify(literature_record.get("year")),
                    sentence_group_keywords=SENTENCE_GROUP_KEYWORDS,
                )
                reading_packet = build_review_reading_packet(str(structured_path))
                clean_body = _stringify(reading_packet.get("clean_body"))
                if clean_body:
                    cleaned_sentences = _split_sentences(clean_body)
                    review_state["full_text"] = clean_body
                    review_state["sentences"] = cleaned_sentences
                    for field_name, limit in review_state_field_limits.items():
                        review_state[field_name] = _pick_sentences(
                            cleaned_sentences,
                            SENTENCE_GROUP_KEYWORDS.get(field_name, ()),
                            limit=limit,
                            tail_bias=(field_name == "future_directions"),
                        )
                packet_refs = list(reading_packet.get("references") or [])
                if packet_refs:
                    review_state["reference_lines"] = packet_refs
            else:
                structured_abs_path = ""
        if not structured_abs_path:
            if pdf_path is None:
                missing_attachments.append(f"{cite_key}: 未找到 PDF 附件")
                continue

            review_state = extract_review_state_from_attachment(
                str(pdf_path),
                workspace_root=str(workspace_root),
                uid_literature=uid_literature,
                cite_key=cite_key,
                title=_stringify(literature_record.get("title")) or cite_key,
                year=_stringify(literature_record.get("year")),
                sentence_group_keywords=SENTENCE_GROUP_KEYWORDS,
                field_limits=review_state_field_limits,
            )

        if not structured_abs_path and pdf_path is None:
            missing_attachments.append(f"{cite_key}: 未找到 PDF 附件")
            continue

        full_text = _stringify(review_state.get("full_text"))
        if not full_text:
            missing_text.append(f"{cite_key}: PDF 文本抽取失败")
            continue

        if enable_review_state_llm:
            review_state = refine_review_state_with_llm(
                review_state,
                workspace_root=workspace_root,
                global_config_path=global_config_path,
                model=review_state_model or None,
                max_chars=review_state_max_chars,
                field_limits=review_state_field_limits,
                print_to_stdout=False,
            )

        original_sentence_count = len(review_state.get("sentences") or [])
        sentences = list(review_state.get("sentences") or [])
        if not sentences:
            missing_text.append(f"{cite_key}: 未切出有效句子")
            continue

        review_state.update(_derive_review_dimensions(review_state))

        reference_lines = list(review_state.get("reference_lines") or [])
        review_state["processing_diagnostics"] = {
            "cite_key": cite_key,
            "title": _stringify(literature_record.get("title")) or cite_key,
            "source_type": "structured" if structured_abs_path else "pdf",
            "used_structured_data": bool(structured_abs_path),
            "structured_path": structured_abs_path,
            "full_text_chars": len(full_text),
            "original_sentence_count": original_sentence_count,
            "sentence_count": len(sentences),
            "reference_line_count": len(reference_lines),
            "review_state_field_limits": review_state_field_limits,
            "review_state_parse_method": _stringify((review_state.get("llm_review_state") or {}).get("parse_method") or review_state.get("extract_method")),
            "review_state_model_name": _stringify((review_state.get("llm_review_state") or {}).get("model_name")),
        }
        dump_sections.append((cite_key, reference_lines))

        note_path = _resolve_existing_standard_note_path(_a05_dirs(workspace_root)["standard_notes"], cite_key)
        review_state["note_path"] = note_path
        review_state["note_uid"] = ""
        review_state["note_updated"] = False
        review_state["reference_entries"] = [f"- [[{cite_key}]]"]

        if note_path is not None:
            sections = {
                "研究问题与对象界定": _section_lines_from_sentences(
                    cite_key,
                    review_state.get("research_problem") or [],
                    fallback="本篇综述未形成稳定的问题界定句。",
                ),
                "研究方法与证据来源": _section_lines_from_sentences(
                    cite_key,
                    review_state.get("research_method") or [],
                    fallback="本篇综述未形成稳定的方法与证据句。",
                ),
                "研究脉络": _section_lines_from_sentences(
                    cite_key,
                    review_state.get("trajectory_points") or [],
                    fallback="本篇综述未形成清晰的脉络演进句。",
                ),
                "核心成果": _section_lines_from_sentences(
                    cite_key,
                    review_state.get("core_results") or [],
                    fallback="本篇综述未形成可回填的核心成果句。",
                ),
                "共识点": _section_lines_from_sentences(
                    cite_key,
                    review_state.get("consensus_candidates") or [],
                    fallback="本篇综述未直接给出可判定共识的句子。",
                ),
                "争议点": _section_lines_from_sentences(
                    cite_key,
                    review_state.get("controversy_candidates") or [],
                    fallback="本篇综述未直接给出稳定争议命题。",
                ),
                "研究问题": [sentence_line_from_review_state(cite_key, item) for item in review_state["research_problem"]],
                "研究方法与证据": [sentence_line_from_review_state(cite_key, item) for item in review_state["research_method"]],
                "核心发现": [sentence_line_from_review_state(cite_key, item) for item in review_state["core_findings"]],
                "未来方向": _section_lines_from_sentences(
                    cite_key,
                    review_state.get("future_directions") or [],
                    fallback="本篇综述未给出明确未来方向句。",
                ),
                "知识框架": _section_lines_from_sentences(
                    cite_key,
                    review_state.get("knowledge_framework_points") or [],
                    fallback="本篇综述未形成完整知识框架句。",
                ),
            }
            knowledge_index, note_uid, note_updated = _update_standard_note(
                knowledge_index,
                note_path=note_path,
                workspace_root=workspace_root,
                uid_literature=uid_literature,
                cite_key=cite_key,
                sections=sections,
                missing_assets=missing_assets,
                review_state=review_state,
                literature_record=literature_record,
            )
            review_state["note_uid"] = note_uid
            review_state["note_updated"] = note_updated
            if note_updated:
                literature_table, _ = literature_bind_standard_note(literature_table, uid_literature, note_uid)
                artifacts.append(note_path)
        else:
            missing_assets.append(f"{cite_key}: 缺少 A05 预创建标准笔记")

        if not reference_lines:
            mapping_rows.append(
                {
                    "source_uid_literature": uid_literature,
                    "source_cite_key": cite_key,
                    "reference_text": "当前附件扫描未形成可解析参考文献文本，待补跑 PDF 文本抽取或 OCR。",
                    "recognized_first_author": "",
                    "recognized_year": "",
                    "recognized_title_raw": "",
                    "matched_uid_literature": "",
                    "matched_cite_key": "",
                    "matched_title": "",
                    "action": "scan_no_reference_text",
                    "parse_method": "",
                    "llm_invoked": 0,
                    "parse_failed": 1,
                    "parse_failure_reason": "no_reference_text",
                    "suspicious_merged": 0,
                    "noise_trimmed": 0,
                    "match_score": 0.0,
                    "suspicious_mismatch": 0,
                    "reference_note_path": str(note_path) if note_path else "",
                }
            )
            review_state["reference_entries"].append("- 当前附件扫描未形成可解析参考文献文本，待补跑 PDF 文本抽取或 OCR。")
        else:
            reference_mentions: List[Dict[str, Any]] = []
            for line in reference_lines:
                process_result: Dict[str, Any] = {
                    "action": "skipped",
                    "matched_uid_literature": "",
                    "matched_cite_key": "",
                    "parse_method": "",
                    "llm_invoked": 0,
                    "parse_failed": 1,
                    "parse_failure_reason": "unknown_error",
                    "match_score": 0.0,
                    "suspicious_mismatch": 0,
                }
                try:
                    literature_table, process_result = process_reference_citation(
                        literature_table,
                        line,
                        workspace_root=workspace_root,
                        global_config_path=global_config_path,
                        source="placeholder_from_a070_review_scan",
                        print_to_stdout=False,
                    )
                except Exception as exc:
                    process_result["parse_failure_reason"] = str(exc)

                matched_cite_key = _stringify(process_result.get("matched_cite_key"))
                recognized_fields = dict(process_result.get("recognized_fields") or {})
                recognized_first_author = _stringify(recognized_fields.get("first_author"))
                recognized_year = _stringify(recognized_fields.get("year"))
                recognized_title_raw = _stringify(recognized_fields.get("title_raw"))
                review_state["reference_entries"].append(f"- [[{matched_cite_key}]]" if matched_cite_key else f"- {line}")
                if matched_cite_key:
                    reference_mentions.append(
                        {
                            "matched_cite_key": matched_cite_key,
                            "matched_title": _stringify(process_result.get("matched_title")),
                            "recognized_first_author": recognized_first_author,
                            "recognized_year": recognized_year,
                            "recognized_title_raw": recognized_title_raw,
                            "author_year_label": f"{recognized_first_author}（{recognized_year}）" if recognized_first_author and recognized_year else "",
                        }
                    )
                mapping_rows.append(
                    {
                        "source_uid_literature": uid_literature,
                        "source_cite_key": cite_key,
                        "reference_text": line,
                        "recognized_first_author": recognized_first_author,
                        "recognized_year": recognized_year,
                        "recognized_title_raw": recognized_title_raw,
                        "matched_uid_literature": _stringify(process_result.get("matched_uid_literature")),
                        "matched_cite_key": matched_cite_key,
                        "matched_title": _stringify(process_result.get("matched_title")),
                        "action": _stringify(process_result.get("action")) or "skipped",
                        "parse_method": _stringify(process_result.get("parse_method")),
                        "llm_invoked": int(process_result.get("llm_invoked") or 0),
                        "parse_failed": int(process_result.get("parse_failed") or 0),
                        "parse_failure_reason": _stringify(process_result.get("parse_failure_reason")),
                        "suspicious_merged": 0,
                        "noise_trimmed": 0,
                        "match_score": float(process_result.get("match_score") or 0.0),
                        "suspicious_mismatch": int(process_result.get("suspicious_mismatch") or 0),
                        "reference_note_path": str(note_path) if note_path else "",
                    }
                )
            mention_counts: Dict[Tuple[str, str], int] = {}
            for mention in reference_mentions:
                key = (_stringify(mention.get("recognized_first_author")), _stringify(mention.get("recognized_year")))
                if key == ("", ""):
                    continue
                mention_counts[key] = mention_counts.get(key, 0) + 1
            for mention in reference_mentions:
                key = (_stringify(mention.get("recognized_first_author")), _stringify(mention.get("recognized_year")))
                mention["duplicate_author_year_count"] = mention_counts.get(key, 0)
            review_state["reference_mentions"] = reference_mentions

        review_states.append(review_state)

    consensus_df = build_review_consensus_rows(review_states, theme_defs=CONSENSUS_THEME_DEFS)
    controversy_df = build_review_controversy_rows(review_states)
    future_df = build_review_future_rows(
        review_states,
        topic=_stringify(raw_cfg.get("topic") or raw_cfg.get("research_topic") or DEFAULT_TOPIC),
    )
    must_read_df = build_review_must_read_originals(review_states, literature_table, mapping_rows)
    general_reading_df = build_review_general_reading_list(review_states, literature_table, mapping_rows)
    must_read_df = _enrich_identity(must_read_df, literature_table)
    general_reading_df = _enrich_identity(general_reading_df, literature_table)
    downstream_df, queue_df = _build_downstream_candidates(must_read_df, general_reading_df, literature_table)

    for state in review_states:
        note_path = state.get("note_path")
        if not note_path or not Path(note_path).exists():
            continue
        per_note_consensus: List[str] = []
        if not consensus_df.empty:
            for _, row in consensus_df.iterrows():
                evidence_notes = _stringify(row.get("evidence_notes"))
                if state["cite_key"] in evidence_notes:
                    per_note_consensus.append(f"- 共识：{_stringify(row.get('topic'))}")
        if not controversy_df.empty:
            for _, row in controversy_df.iterrows():
                evidence_notes = _stringify(row.get("evidence_notes"))
                if state["cite_key"] in evidence_notes:
                    per_note_consensus.append(f"- 争议：{_stringify(row.get('topic'))}")
        if not per_note_consensus:
            per_note_consensus.append("- 本轮未形成稳定共识/争议补写。")
        consensus_lines = [item for item in per_note_consensus if item.startswith("- 共识：")]
        controversy_lines = [item for item in per_note_consensus if item.startswith("- 争议：")]
        sections = {
            "共识点": consensus_lines or [f"- 本轮未形成稳定共识补写（cite_key: {state['cite_key']}）"],
            "争议点": controversy_lines or [f"- 本轮未形成稳定争议补写（cite_key: {state['cite_key']}）"],
            "共识与争议": per_note_consensus,
            "参考文献列表": state.get("reference_entries") or [f"- [[{state['cite_key']}]]"],
        }
        note_record_rows = literature_table[literature_table.get("uid_literature", pd.Series(dtype=str)).astype(str) == _stringify(state.get("uid_literature"))]
        note_record = note_record_rows.iloc[0].to_dict() if not note_record_rows.empty else {}
        knowledge_index, note_uid, note_updated = _update_standard_note(
            knowledge_index,
            note_path=Path(note_path),
            workspace_root=workspace_root,
            uid_literature=state["uid_literature"],
            cite_key=state["cite_key"],
            sections=sections,
            missing_assets=missing_assets,
            review_state=state,
            literature_record=note_record,
        )
        if note_updated and note_uid:
            state["note_uid"] = note_uid

    input_lines = _composite_input_lines(review_states)
    evidence_links = [f"- [[{state['cite_key']}]]" for state in review_states]
    trajectory_items = [
        {
            "year": state["year"],
            "title": state["title"],
            "uid_literature": state["uid_literature"],
            "view_note": _stringify((state.get("research_problem") or state.get("core_findings") or [{}])[0].get("sentence")),
        }
        for state in review_states
    ]
    trajectory = build_research_trajectory(trajectory_items, topic=_stringify(raw_cfg.get("topic") or raw_cfg.get("research_topic") or DEFAULT_TOPIC))
    trajectory_summary_lines = [
        f"- {_stringify(state.get('year')) or '未知年份'} | {build_note_wikilink(state['cite_key'])}：{sanitize_note_sentence(_stringify(item.get('view_note')))}"
        for state, item in zip(review_states, trajectory_items)
        if sanitize_note_sentence(_stringify(item.get("view_note")))
    ] or ["- 本轮未形成可回填的研究脉络条目。"]

    llm_generated_note_count = 0

    def _maybe_generate_summary_lines(note_name: str, fallback_lines: List[str]) -> List[str]:
        nonlocal llm_generated_note_count
        if not evidence_writing_enabled:
            return fallback_lines
        generated_lines = generate_evidence_constrained_summary_lines(
            note_name,
            review_states,
            research_topic=synthesis_research_topic,
            workspace_root=workspace_root,
            global_config_path=global_config_path,
            model=evidence_writer_model,
            line_target=evidence_line_targets.get(note_name, 5),
            max_evidence_per_review=max_evidence_per_review,
            print_to_stdout=False,
        )
        if generated_lines:
            llm_generated_note_count += 1
            return generated_lines
        return fallback_lines

    trajectory_summary_lines = _maybe_generate_summary_lines("领域研究脉络.md", trajectory_summary_lines)
    core_summary_lines = _maybe_generate_summary_lines(
        "核心成果.md",
        _composite_evidence_lines(review_states, "core_findings"),
    )
    future_summary_lines = _maybe_generate_summary_lines(
        "未来方向.md",
        _future_summary_lines(future_df),
    )
    framework_summary_lines = _maybe_generate_summary_lines(
        "领域知识框架.md",
        _framework_summary_lines(consensus_df, future_df),
    )
    innovation_summary_lines = _maybe_generate_summary_lines(
        "创新点补写.md",
        _innovation_summary_lines(review_states, future_df),
    )

    composite_updates = [
        (asset_paths["trajectory_seed"], trajectory_summary_lines, _composite_evidence_lines(review_states, "research_problem")),
        (asset_paths["core_findings"], core_summary_lines, evidence_links),
        (asset_paths["consensus_notes"], _consensus_summary_lines(consensus_df), _parse_evidence_column(consensus_df["evidence_notes"]) if not consensus_df.empty else ["- 本轮未形成满足阈值的综述共识证据。"]),
        (asset_paths["controversy_notes"], _controversy_summary_lines(controversy_df), _parse_evidence_column(controversy_df["evidence_notes"]) if not controversy_df.empty else ["- 本轮未形成稳定综述争议证据。"]),
        (asset_paths["future_directions_notes"], future_summary_lines, _composite_evidence_lines(review_states, "future_directions", limit_per_review=2)),
        (asset_paths["knowledge_framework"], framework_summary_lines, evidence_links),
        (asset_paths["innovation_seed"], innovation_summary_lines, _composite_evidence_lines(review_states, "future_directions", limit_per_review=1) or evidence_links),
    ]
    for note_path, summary_lines, evidence_lines in composite_updates:
        knowledge_index, updated = _update_composite_note(
            knowledge_index,
            note_path=note_path,
            workspace_root=workspace_root,
            input_lines=input_lines,
            summary_lines=summary_lines,
            evidence_lines=evidence_lines,
            missing_assets=missing_assets,
            review_states=review_states,
        )
        if updated:
            artifacts.append(note_path)

    if asset_paths["reference_dump"].exists():
        _append_dump_sections(asset_paths["reference_dump"], dump_sections)
        artifacts.append(asset_paths["reference_dump"])
    else:
        missing_assets.append(f"引文识别原文.txt: 缺少 A05 预创建文件 {asset_paths['reference_dump']}")

    if asset_paths["mapping_csv"].exists():
        mapping_df = pd.DataFrame(mapping_rows, columns=PROCESS_FILE_HEADERS["reference_citation_mapping.csv"])
        mapping_df.to_csv(asset_paths["mapping_csv"], index=False, encoding="utf-8-sig")
        artifacts.append(asset_paths["mapping_csv"])
        quality_summary = build_reference_quality_summary(mapping_rows)
        if asset_paths["quality_summary"].exists():
            asset_paths["quality_summary"].write_text(json.dumps(quality_summary, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts.append(asset_paths["quality_summary"])
        else:
            missing_assets.append(f"reference_citation_quality_summary.json: 缺少 A05 预创建文件 {asset_paths['quality_summary']}")
    else:
        quality_summary = {}
        missing_assets.append(f"reference_citation_mapping.csv: 缺少 A05 预创建文件 {asset_paths['mapping_csv']}")

    for asset_key, dataframe, label in [
        ("consensus_csv", consensus_df, "consensus_list.csv"),
        ("controversy_csv", controversy_df, "controversy_list.csv"),
        ("future_csv", future_df, "future_directions.csv"),
        ("must_read_csv", must_read_df, "must_read_originals.csv"),
        ("general_reading_csv", general_reading_df, "review_general_reading_list.csv"),
    ]:
        written_path = _write_dataframe_if_exists(dataframe, asset_paths[asset_key], missing_assets, label)
        if written_path is not None:
            artifacts.append(written_path)

    batch_path = _update_batch_file(asset_paths["review_reading_batches"], review_states, missing_assets)
    if batch_path is not None:
        artifacts.append(batch_path)

    step_output_dir = workspace_root / "steps" / "A070_review_synthesis"
    step_output_dir.mkdir(parents=True, exist_ok=True)
    downstream_path = step_output_dir / "downstream_non_review_candidates.csv"
    downstream_df.to_csv(downstream_path, index=False, encoding="utf-8-sig")
    artifacts.append(downstream_path)
    downstream_md_path = step_output_dir / "downstream_non_review_candidates.md"
    md_lines = ["# downstream_non_review_candidates", ""]
    if downstream_df.empty:
        md_lines.append("- 当前无可导出的非综述候选条目。")
    else:
        for _, row in downstream_df.fillna("").iterrows():
            md_lines.append(
                "- "
                + f"{_stringify(row.get('cite_key')) or _stringify(row.get('uid_literature'))} | "
                + f"{_stringify(row.get('preferred_next_stage'))} | "
                + f"{_stringify(row.get('recommended_reason'))}"
            )
    downstream_md_path.write_text("\n".join(md_lines).strip() + "\n", encoding="utf-8")
    artifacts.append(downstream_md_path)

    persist_knowledge_tables(index_df=knowledge_index, attachments_df=knowledge_attachments, db_path=content_db_path)
    persist_reference_tables(literatures_df=literature_table, attachments_df=attachment_table, db_path=content_db_path)

    if not queue_df.empty:
        upsert_reading_queue_rows(content_db_path, queue_df)
        a080_tag_rows = [
            {"uid_literature": _stringify(row.get("uid_literature")), "cite_key": _stringify(row.get("cite_key")), "tag": f"queued/{_stringify(row.get('queue_status'))}"}
            for _, row in queue_df[queue_df["stage"].astype(str) == "A080"].iterrows()
            if _stringify(row.get("uid_literature")) or _stringify(row.get("cite_key"))
        ]
        a080_bucket_rows = [
            {"uid_literature": _stringify(row.get("uid_literature")), "cite_key": _stringify(row.get("cite_key")), "tag": _stringify(row.get("bucket")) or "frontier"}
            for _, row in queue_df[queue_df["stage"].astype(str) == "A080"].iterrows()
            if _stringify(row.get("uid_literature")) or _stringify(row.get("cite_key"))
        ]
        a090_tag_rows = [
            {"uid_literature": _stringify(row.get("uid_literature")), "cite_key": _stringify(row.get("cite_key")), "tag": f"queued/{_stringify(row.get('queue_status'))}"}
            for _, row in queue_df[queue_df["stage"].astype(str) == "A090"].iterrows()
            if _stringify(row.get("uid_literature")) or _stringify(row.get("cite_key"))
        ]
        if a080_tag_rows:
            replace_tags_for_namespace(content_db_path, namespace="queue/a080", tag_rows=a080_tag_rows, source_type="a070_downstream")
        if a080_bucket_rows:
            replace_tags_for_namespace(content_db_path, namespace="bucket", tag_rows=a080_bucket_rows, source_type="a070_downstream")
        if a090_tag_rows:
            replace_tags_for_namespace(content_db_path, namespace="queue/a090", tag_rows=a090_tag_rows, source_type="a070_downstream")

    issues = missing_attachments + missing_text + missing_assets
    evidence_unit_count = sum(
        len(list(state.get("supporting_evidence") or []))
        + len(list(state.get("mechanism_paths") or []))
        + len(list(state.get("controversy_points") or []))
        + len(list(state.get("limitation_points") or []))
        for state in review_states
    )
    analysis_layer_ready = bool(review_states) and (llm_generated_note_count > 0 or bool(evidence_writing_enabled))
    score = max(40.0, 95.0 - len(issues) * 6.0)
    gate_review = build_gate_review(
        node_uid="A070",
        node_name="综述研读与研究脉络",
        summary=(
            f"已基于 A050/A065 资产回填 {len(review_states)} 篇综述标准笔记，并更新共识 {len(consensus_df)} 条、"
            f"争议 {len(controversy_df)} 条、未来方向 {len(future_df)} 条。"
        ),
        checks=[
            {"name": "review_processed_count", "value": len(review_states)},
            {"name": "missing_attachment_count", "value": len(missing_attachments)},
            {"name": "missing_text_count", "value": len(missing_text)},
            {"name": "missing_asset_count", "value": len(missing_assets)},
            {"name": "consensus_count", "value": len(consensus_df)},
            {"name": "controversy_count", "value": len(controversy_df)},
            {"name": "future_direction_count", "value": len(future_df)},
            {"name": "must_read_count", "value": len(must_read_df)},
            {"name": "evidence_unit_count", "value": evidence_unit_count},
            {"name": "analysis_note_llm_generated_count", "value": llm_generated_note_count},
            {"name": "analysis_layer_ready", "value": int(analysis_layer_ready)},
        ],
        artifacts=[str(path) for path in artifacts],
        recommendation="pass" if len(review_states) > 0 and not missing_attachments and not missing_text else "retry_current",
        score=score,
        issues=issues,
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db_path),
            "aok_log_db": str((workspace_root / "database" / "logs" / "aok_log.db")),
            "db_input_key": db_input_key,
            "processed_review_cite_keys": [state["cite_key"] for state in review_states],
            "review_processing_details": [state.get("processing_diagnostics") or {} for state in review_states],
            "single_review_materialization": single_review_cfg,
            "analysis_note_generation": analysis_note_cfg,
            "evidence_constrained_writing": evidence_writing_cfg,
            "trajectory": trajectory,
            "quality_summary": quality_summary,
        },
    )
    gate_path = output_dir / OUTPUT_FILES["gate_review"]
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        append_aok_log_event(
            event_type="A070_REVIEW_SYNTHESIS_BUILT",
            project_root=workspace_root,
            affair_code="A070",
            handler_name="综述研读与研究地图生成",
            agent_names=["ar_综述研读与研究脉络事务智能体_v5"],
            skill_names=["ar_综述精读与研究脉络梳理_v5"],
            reasoning_summary="严格复用 A050/A060 综述资产执行局部回填，并更新 G070 审计。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=[*artifacts, gate_path],
            payload={
                "review_processed_count": len(review_states),
                "consensus_count": len(consensus_df),
                "controversy_count": len(controversy_df),
                "future_direction_count": len(future_df),
                "must_read_count": len(must_read_df),
                "missing_attachment_count": len(missing_attachments),
                "missing_text_count": len(missing_text),
                "missing_asset_count": len(missing_assets),
            },
        )
    except Exception:
        pass

    return [*artifacts, gate_path]
