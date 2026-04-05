"""阅读状态工作流辅助工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


ANALYSIS_NOTE_SPECS: Dict[str, Dict[str, str]] = {
    "trajectory": {"title": "领域研究脉络", "relative_path": "knowledge/trajectories/领域研究脉络.md"},
    "core_findings": {"title": "核心成果", "relative_path": "knowledge/trajectories/核心成果.md"},
    "controversies": {"title": "争议点", "relative_path": "knowledge/trajectories/争议点.md"},
    "future_directions": {"title": "未来方向", "relative_path": "knowledge/trajectories/未来方向.md"},
    "framework": {"title": "领域知识框架", "relative_path": "knowledge/frameworks/领域知识框架.md"},
}


def _stringify(value: Any) -> str:
    return str(value or "").strip()


def resolve_analysis_note_paths(workspace_root: str | Path, raw_cfg: Dict[str, Any] | None = None) -> Dict[str, Path]:
    workspace = Path(workspace_root).resolve()
    configured = raw_cfg.get("analysis_note_paths") if isinstance(raw_cfg, dict) else {}
    results: Dict[str, Path] = {}
    for key, spec in ANALYSIS_NOTE_SPECS.items():
        raw_value = _stringify((configured or {}).get(key))
        if raw_value:
            path = Path(raw_value)
            if not path.is_absolute():
                raise ValueError(f"analysis_note_paths.{key} 必须为绝对路径：{path}")
            results[key] = path
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
    if preprocessed:
        row["pending_preprocess"] = 0
        row["pending_rough_read"] = 1
    else:
        row["pending_preprocess"] = 1 if not pending_preprocess else pending_preprocess
        row["pending_rough_read"] = 0
    row["in_rough_read"] = 0
    return row


__all__ = [
    "ANALYSIS_NOTE_SPECS",
    "append_markdown_section",
    "build_followup_candidate_state_row",
    "build_standard_note_body",
    "ensure_markdown_note",
    "resolve_analysis_note_paths",
]