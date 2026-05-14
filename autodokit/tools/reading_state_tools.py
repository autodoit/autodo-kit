"""阅读状态工作流辅助工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from autodokit.path_compat import resolve_portable_path


ANALYSIS_NOTE_SPECS: Dict[str, Dict[str, str]] = {
    "trajectory": {"title": "领域研究脉络", "relative_path": "knowledge/trajectories/领域研究脉络.md"},
    "core_findings": {"title": "核心成果", "relative_path": "knowledge/trajectories/核心成果.md"},
    "controversies": {"title": "争议点", "relative_path": "knowledge/trajectories/争议点.md"},
    "future_directions": {"title": "未来方向", "relative_path": "knowledge/trajectories/未来方向.md"},
    "framework": {"title": "领域知识框架", "relative_path": "knowledge/frameworks/领域知识框架.md"},
}


def _stringify(value: Any) -> str:
    return str(value or "").strip()


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _stringify(value).lower()
    return text in {"1", "true", "yes", "y", "on", "enabled", "enable"}


def resolve_analysis_note_paths(workspace_root: str | Path, raw_cfg: Dict[str, Any] | None = None) -> Dict[str, Path]:
    workspace = resolve_portable_path(workspace_root, base=Path.cwd())
    configured = raw_cfg.get("analysis_note_paths") if isinstance(raw_cfg, dict) else {}
    results: Dict[str, Path] = {}
    for key, spec in ANALYSIS_NOTE_SPECS.items():
        raw_value = _stringify((configured or {}).get(key))
        if raw_value:
            results[key] = resolve_portable_path(raw_value, base=workspace)
        else:
            results[key] = workspace / spec["relative_path"]
    return results


def ensure_markdown_note(note_path: str | Path, title: str) -> Path:
    path = Path(note_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"# {title}\n\n", encoding="utf-8")
    return path


def append_markdown_section(note_path: str | Path, title: str, lines: List[str]) -> Path:
    path = ensure_markdown_note(note_path, title)
    normalized_lines = [line for line in lines if _stringify(line)]
    if not normalized_lines:
        return path
    block = ["", f"## 更新记录", *normalized_lines, ""]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(block))
    return path


def build_standard_note_body(*, title: str, cite_key: str, summary_lines: List[str] | None = None) -> str:
    normalized = [line for line in (summary_lines or []) if _stringify(line)]
    bullets = normalized or ["- 待补充"]
    return "\n".join(
        [
            f"# {title}",
            "",
            f"- cite_key: {cite_key}",
            "",
            "## 文献概况",
            *bullets,
            "",
            "## 研究问题",
            "- 待补充",
            "",
            "## 方法与证据",
            "- 待补充",
            "",
            "## 核心发现",
            "- 待补充",
            "",
            "## 深读补充",
            "- 待补充",
            "",
        ]
    )


def build_followup_candidate_state_row(
    *,
    uid_literature: str,
    cite_key: str,
    source_stage: str,
    source_uid_literature: str,
    source_cite_key: str,
    recommended_reason: str,
    theme_relation: str,
    existing_state: Dict[str, Any] | None = None,
) -> Dict[str, Any] | None:
    """按普通文献主链规则构造新候选状态行。

    规则：
    1. 若目标文献已泛读或已在待/正泛读中，则不重复加入下一轮待泛读。
    2. 若目标文献已预处理，则直接加入待泛读清单。
    3. 若目标文献尚未预处理，则加入待预处理清单。
    """

    base = dict(existing_state or {})
    normalized_uid = _stringify(uid_literature)
    normalized_cite_key = _stringify(cite_key) or _stringify(base.get("cite_key")) or normalized_uid
    preprocessed = int(base.get("preprocessed") or 0)
    allow_unparsed_read = int(base.get("allow_unparsed_read") or 0)
    pending_preprocess = int(base.get("pending_preprocess") or 0)
    pending_rough_read = int(base.get("pending_rough_read") or 0)
    in_rough_read = int(base.get("in_rough_read") or 0)
    rough_read_done = int(base.get("rough_read_done") or 0)

    if rough_read_done or pending_rough_read or in_rough_read:
        return None

    row: Dict[str, Any] = dict(base)
    row.update(
        {
            "uid_literature": normalized_uid,
            "cite_key": normalized_cite_key,
            "source_stage": _stringify(source_stage),
            "source_uid_literature": _stringify(source_uid_literature),
            "source_cite_key": _stringify(source_cite_key),
            "recommended_reason": _stringify(recommended_reason),
            "theme_relation": _stringify(theme_relation),
        }
    )
    if preprocessed or allow_unparsed_read:
        row["pending_preprocess"] = 0
        row["pending_rough_read"] = 1
    else:
        row["pending_preprocess"] = 1 if not pending_preprocess else pending_preprocess
        row["pending_rough_read"] = 0
    row["in_rough_read"] = 0
    return row


def should_route_back_to_a040(
    *,
    mapping_row: Dict[str, Any],
    target_state: Dict[str, Any] | None = None,
    target_literature_row: Dict[str, Any] | None = None,
    prefer_fulltext: bool = True,
    min_match_score: int = 60,
) -> Dict[str, Any]:
    """判断参考文献映射结果是否应先回流 A040。

    Returns:
        dict: {
            "route_to_a040": bool,
            "reason": str,
            "reason_code": str,
        }
    """

    row = dict(mapping_row or {})
    state = dict(target_state or {})
    literature = dict(target_literature_row or {})

    matched_uid = _stringify(row.get("matched_uid_literature"))
    action = _stringify(row.get("action")).lower()
    parse_failed = _coerce_bool(row.get("parse_failed"))
    parse_failure_reason = _stringify(row.get("parse_failure_reason"))
    suspicious_mismatch = _coerce_bool(row.get("suspicious_mismatch"))
    suspicious_merged = _coerce_bool(row.get("suspicious_merged"))
    match_score = _coerce_int(row.get("match_score"), 0)

    if parse_failed:
        return {
            "route_to_a040": True,
            "reason": parse_failure_reason or "参考文献解析失败，需回流 A040 补检",
            "reason_code": "parse_failed",
        }

    if not matched_uid:
        return {
            "route_to_a040": True,
            "reason": "未匹配到目标文献，需回流 A040 补检",
            "reason_code": "no_match",
        }

    if suspicious_mismatch or suspicious_merged:
        return {
            "route_to_a040": True,
            "reason": "映射结果低置信度或存在可疑合并，需回流 A040 复核",
            "reason_code": "low_confidence_match",
        }

    if match_score and match_score < int(min_match_score):
        return {
            "route_to_a040": True,
            "reason": f"映射分值过低({match_score})，需回流 A040",
            "reason_code": "low_match_score",
        }

    if action in {"failed", "error", "no_match", "placeholder"}:
        return {
            "route_to_a040": True,
            "reason": f"映射动作为 {action}，需回流 A040",
            "reason_code": "action_requires_retry",
        }

    if prefer_fulltext:
        has_fulltext = _coerce_bool(literature.get("has_fulltext")) or _coerce_bool(state.get("has_fulltext"))
        pending_preprocess = _coerce_int(state.get("pending_preprocess"), 0)
        preprocessed = _coerce_int(state.get("preprocessed"), 0)
        if not has_fulltext and not preprocessed and not pending_preprocess:
            return {
                "route_to_a040": True,
                "reason": "目标文献缺正文且未进入预处理链，需回流 A040 补件",
                "reason_code": "missing_fulltext",
            }

    return {
        "route_to_a040": False,
        "reason": "映射结果可直接进入阅读状态机短闭环",
        "reason_code": "short_loop_ok",
    }


def build_retrieval_feedback_request(
    *,
    source_stage: str,
    source_task_uid: str,
    source_note_path: str,
    source_uid_literature: str,
    source_cite_key: str,
    reference_lines: List[str] | None,
    mapping_row: Dict[str, Any] | None = None,
    retrieval_reason: str = "",
    preferred_sources: List[str] | None = None,
    need_fulltext: bool = True,
    need_metadata_completion: bool = True,
) -> Dict[str, Any]:
    """构造标准化的阅读回流检索请求。"""

    mapping = dict(mapping_row or {})
    sanitized_lines = [_stringify(item) for item in list(reference_lines or []) if _stringify(item)]
    source_uid = _stringify(source_uid_literature)
    source_key = _stringify(source_cite_key)
    matched_uid = _stringify(mapping.get("matched_uid_literature"))
    matched_key = _stringify(mapping.get("matched_cite_key"))
    reference_text = _stringify(mapping.get("reference_text"))

    seed_items: List[Dict[str, Any]] = []
    if matched_key or matched_uid:
        seed_items.append(
            {
                "cite_key": matched_key,
                "uid_literature": matched_uid,
                "title": _stringify(mapping.get("title")),
                "detail_url": _stringify(mapping.get("detail_url")),
            }
        )
    if reference_text:
        seed_items.append({"title": reference_text})

    return {
        "source_stage": _stringify(source_stage),
        "source_task_uid": _stringify(source_task_uid),
        "source_note_path": _stringify(source_note_path),
        "source_uid_literature": source_uid,
        "source_cite_key": source_key,
        "reference_lines": sanitized_lines or ([reference_text] if reference_text else []),
        "seed_items": seed_items,
        "retrieval_reason": _stringify(retrieval_reason),
        "preferred_sources": [
            _stringify(item) for item in list(preferred_sources or ["zh_cnki", "en_open_access"]) if _stringify(item)
        ],
        "need_fulltext": bool(need_fulltext),
        "need_metadata_completion": bool(need_metadata_completion),
        "mapping_result": {
            "matched_uid_literature": matched_uid,
            "matched_cite_key": matched_key,
            "action": _stringify(mapping.get("action")),
            "parse_failed": _coerce_int(mapping.get("parse_failed"), 0),
            "match_score": _coerce_int(mapping.get("match_score"), 0),
            "parse_failure_reason": _stringify(mapping.get("parse_failure_reason")),
        },
    }


def merge_retrieval_feedback_requests(requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """去重合并阅读回流请求。"""

    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for request in list(requests or []):
        item = dict(request or {})
        source_stage = _stringify(item.get("source_stage"))
        source_uid = _stringify(item.get("source_uid_literature"))
        source_cite = _stringify(item.get("source_cite_key"))
        mapping = dict(item.get("mapping_result") or {})
        matched_uid = _stringify(mapping.get("matched_uid_literature"))
        matched_cite = _stringify(mapping.get("matched_cite_key"))
        ref_head = ""
        lines = [
            _stringify(line)
            for line in list(item.get("reference_lines") or [])
            if _stringify(line)
        ]
        if lines:
            ref_head = lines[0][:120]
        identity = "|".join([source_stage, source_uid, source_cite, matched_uid, matched_cite, ref_head]).lower()
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(item)
    return deduped


__all__ = [
    "ANALYSIS_NOTE_SPECS",
    "append_markdown_section",
    "build_retrieval_feedback_request",
    "build_followup_candidate_state_row",
    "build_standard_note_body",
    "ensure_markdown_note",
    "merge_retrieval_feedback_requests",
    "resolve_analysis_note_paths",
    "should_route_back_to_a040",
]