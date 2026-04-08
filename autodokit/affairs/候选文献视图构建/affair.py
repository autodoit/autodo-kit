"""候选文献视图构建事务。"""

from __future__ import annotations

from hashlib import sha1
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd

from autodokit.tools import (
    append_aok_log_event,
    allocate_reading_batches,
    build_candidate_readable_view,
    build_candidate_view_index,
    build_gate_review,
    build_reference_quality_summary,
    build_review_candidate_views,
    extract_reference_lines_from_attachment,
    extract_review_candidates,
    init_empty_knowledge_attachments_table,
    init_empty_knowledge_index_table,
    knowledge_bind_literature_standard_note,
    knowledge_index_sync_from_note,
    knowledge_note_register,
    knowledge_note_validate_obsidian,
    load_json_or_py,
    process_reference_citation,
    refine_reference_lines_with_llm,
)
from autodokit.tools.llm_clients import postprocess_aliyun_multimodal_parse_outputs
from autodokit.tools.pdf_parse_asset_manager import ensure_multimodal_parse_asset
from autodokit.tools.bibliodb_sqlite import replace_tags_for_namespace, save_structured_state
from autodokit.tools.bibliodb_sqlite import replace_tags_for_namespace, save_structured_state, upsert_reading_queue_rows
from autodokit.tools.contentdb_sqlite import get_pdf_structured_variant_column, resolve_content_db_config, resolve_pdf_structured_variant_output_dir
from autodokit.tools.pdf_to_structured_data_converter_local_pipeline_v2 import convert_pdf_to_structured_data_file as convert_pdf_to_structured_data_file_local_v2
from autodokit.tools.pdf_to_structure_data_converter_use_babeldoc import convert_pdf_to_structured_data_file as convert_pdf_to_structured_data_file_babeldoc
from autodokit.tools.storage_backend import (
    load_knowledge_tables,
    load_reference_main_table,
    persist_knowledge_tables,
    persist_reference_main_table,
    persist_review_candidate_views,
)
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.pdf_structured_data_tools import (
    extract_reference_lines_from_structured_data,
    load_structured_data,
)
from autodokit.tools.time_utils import now_compact


STRUCTURED_ATTACHMENT_HEADERS: Dict[str, List[str]] = {
    "consensus_list.csv": ["consensus_uid", "topic", "finding", "evidence_notes", "status"],
    "controversy_list.csv": ["controversy_uid", "topic", "controversy", "evidence_notes", "status"],
    "future_directions.csv": ["direction_uid", "topic", "direction", "source_notes", "priority"],
    "must_read_originals.csv": ["uid_literature", "cite_key", "title", "reason", "status"],
    "review_general_reading_list.csv": ["uid_literature", "cite_key", "title", "source_review", "status"],
}

PROCESS_FILE_HEADERS: Dict[str, List[str]] = {
    "created_notes.csv": ["uid_literature", "cite_key", "note_type", "note_path", "status"],
    "reference_citation_mapping.csv": [
        "source_uid_literature",
        "source_cite_key",
        "reference_text",
        "matched_uid_literature",
        "matched_cite_key",
        "action",
        "parse_method",
        "llm_invoked",
        "parse_failed",
        "parse_failure_reason",
        "is_placeholder",
        "placeholder_reason",
        "placeholder_status",
        "placeholder_run_uid",
        "suspicious_merged",
        "noise_trimmed",
        "match_score",
        "suspicious_mismatch",
        "reference_note_path",
    ],
    "reference_scan_status.csv": [
        "uid_literature",
        "cite_key",
        "scan_status",
        "reason",
        "pdf_path",
        "reference_note_path",
    ],
}

DEFAULT_STRUCTURED_VARIANTS: Tuple[Tuple[str, str], ...] = (
    ("local_pipeline_v2", "reference_context"),
    ("local_pipeline_v2", "full_fine_grained"),
    ("babeldoc", "reference_context"),
    ("babeldoc", "full_fine_grained"),
)


def _stringify(value: Any) -> str:
    """安全转换文本值。"""

    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _build_scope_key(raw_cfg: Dict[str, Any]) -> str:
    """构造 A05 当前态 scope 标识。"""

    topic = _stringify(raw_cfg.get("research_topic")) or "all_topics"
    min_year = _stringify(raw_cfg.get("min_year")) or ""
    max_year = _stringify(raw_cfg.get("max_year")) or ""
    recent_years = _stringify(raw_cfg.get("recent_years")) or ""
    year_window = f"{min_year}:{max_year}" if min_year or max_year else (f"recent:{recent_years}" if recent_years else "year:any")
    return f"topic={topic}|window={year_window}"


def _build_run_uid(scope_key: str) -> str:
    """生成本轮 A05 运行 UID。"""

    timestamp = now_compact()
    return f"a05-{timestamp}-{sha1(scope_key.encode('utf-8')).hexdigest()[:8]}"


def _resolve_workspace_root(config_path: Path, raw_cfg: Dict[str, Any]) -> Path:
    """根据配置推断 workspace 根目录。"""

    for key in ("workspace_root",):
        candidate = _stringify(raw_cfg.get(key))
        if candidate:
            path = Path(candidate)
            if not path.is_absolute():
                raise ValueError(f"{key} 必须为绝对路径: {path}")
            return path
    return config_path.parents[2]


def _load_global_config(global_config_path: Path | None) -> Dict[str, Any]:
    """加载 workspace 全局配置。"""

    if global_config_path is None or not global_config_path.exists():
        return {}
    loaded = load_json_or_py(global_config_path)
    return loaded if isinstance(loaded, dict) else {}


def _resolve_logging_enabled(global_cfg: Dict[str, Any]) -> bool:
    """读取全局日志开关。"""

    logging_cfg = global_cfg.get("logging") if isinstance(global_cfg.get("logging"), dict) else {}
    return bool(logging_cfg.get("enabled", True))


def _collect_structured_variants(raw_cfg: Dict[str, Any]) -> List[Tuple[str, str]]:
    """构造 structured 复用优先级。"""

    preferred_converter = _stringify(raw_cfg.get("structured_converter")) or "local_pipeline_v2"
    preferred_task_type = _stringify(raw_cfg.get("structured_task_type")) or "reference_context"
    ordered: List[Tuple[str, str]] = [(preferred_converter, preferred_task_type)]
    if bool(raw_cfg.get("structured_reuse_any_variant", True)):
        for item in DEFAULT_STRUCTURED_VARIANTS:
            if item not in ordered:
                ordered.append(item)
    return ordered


def _resolve_existing_structured_path(
    source_record: Dict[str, Any],
    structured_variants: List[Tuple[str, str]],
) -> Tuple[Path | None, str, str]:
    """按四组合优先顺序定位已有 structured 文件。"""

    # 优先使用当前记录声明的 structured_abs_path，避免误命中历史低质量变体文件。
    structured_abs_path = _stringify(source_record.get("structured_abs_path"))
    if structured_abs_path:
        path = Path(structured_abs_path)
        if path.is_absolute() and path.exists() and path.is_file():
            return path, _stringify(source_record.get("structured_backend")), _stringify(source_record.get("structured_task_type"))

    for converter, task_type in structured_variants:
        column_name = get_pdf_structured_variant_column(converter, task_type)
        if not column_name:
            continue
        path_text = _stringify(source_record.get(column_name))
        if not path_text:
            continue
        path = Path(path_text)
        if path.is_absolute() and path.exists() and path.is_file():
            return path, converter, task_type
    return None, "", ""


def _resolve_source_pdf_path(source_record: Dict[str, Any], workspace_root: Path) -> Path | None:
    """从文献记录解析当前工作区中的 PDF 附件路径。"""

    for field_name in (
        "pdf_path",
        "primary_attachment_path",
        "attachment_path",
        "storage_path",
        "source_path",
        "primary_attachment_name",
    ):
        resolved = _resolve_pdf_file(_stringify(source_record.get(field_name)), workspace_root)
        if resolved is not None:
            return resolved
    return None


def _apply_structured_state_to_table(
    table: pd.DataFrame,
    *,
    uid_literature: str,
    structured_abs_path: str,
    structured_backend: str,
    structured_task_type: str,
    structured_updated_at: str,
    structured_schema_version: str,
    structured_text_length: int,
    structured_reference_count: int,
) -> pd.DataFrame:
    """把 structured 状态同步回当前内存中的文献表。"""

    if table.empty or not uid_literature or "uid_literature" not in table.columns:
        return table
    working = table.copy()
    mask = working["uid_literature"].astype(str) == uid_literature
    if not mask.any():
        return working

    working.loc[mask, "structured_status"] = "ready"
    working.loc[mask, "structured_abs_path"] = structured_abs_path
    working.loc[mask, "structured_backend"] = structured_backend
    working.loc[mask, "structured_task_type"] = structured_task_type
    working.loc[mask, "structured_updated_at"] = structured_updated_at
    working.loc[mask, "structured_schema_version"] = structured_schema_version
    working.loc[mask, "structured_text_length"] = int(structured_text_length or 0)
    working.loc[mask, "structured_reference_count"] = int(structured_reference_count or 0)
    variant_column = get_pdf_structured_variant_column(structured_backend, structured_task_type)
    if variant_column and variant_column in working.columns:
        working.loc[mask, variant_column] = structured_abs_path
    return working


def _ensure_structured_reference_lines(
    *,
    source_record: Dict[str, Any],
    workspace_root: Path,
    content_db: Path,
    working_literature: pd.DataFrame,
    structured_variants: List[Tuple[str, str]],
    structured_converter: str,
    structured_task_type: str,
    structured_overwrite: bool,
    structured_generation_required: bool,
    structured_extractors: Dict[str, Any] | None,
    api_key_file: str = "",
    parse_model: str = "",
    structured_babeldoc: Dict[str, Any] | None = None,
    enable_aliyun_postprocess: bool = True,
    enable_llm_basic_cleanup: bool = True,
    basic_cleanup_llm_model: str = "qwen3.5-flash",
    basic_cleanup_llm_sdk_backend: str | None = None,
    basic_cleanup_llm_region: str = "cn-beijing",
    enable_llm_structure_resolution: bool = True,
    structure_llm_model: str = "qwen3.5-plus",
    structure_llm_sdk_backend: str | None = None,
    structure_llm_region: str = "cn-beijing",
    enable_llm_contamination_filter: bool = True,
    contamination_llm_model: str = "qwen3-max",
    contamination_llm_sdk_backend: str | None = None,
    contamination_llm_region: str = "cn-beijing",
    postprocess_rewrite_structured: bool = True,
    postprocess_rewrite_markdown: bool = True,
    postprocess_keep_page_markers: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, Any], List[str], List[Dict[str, Any]], bool]:
    """优先复用 structured 文件，缺失时按配置生成。"""

    structured_path, backend, task_type = _resolve_existing_structured_path(source_record, structured_variants)
    if structured_path is None:
        pdf_file = _resolve_source_pdf_path(source_record, workspace_root)
        if pdf_file is None:
            if structured_generation_required:
                raise ValueError(
                    f"uid_literature={_stringify(source_record.get('uid_literature')) or 'unknown'} 缺少可用 PDF，无法生成 structured.json"
                )
            return working_literature, source_record, [], [], False

        if structured_converter == "aliyun_multimodal":
            global_config_path = workspace_root / "config" / "config.json"
            parse_level = structured_task_type if structured_task_type not in {"reference_context", "full_fine_grained"} else "review_deep"
            parse_asset = ensure_multimodal_parse_asset(
                content_db=content_db,
                parse_level=parse_level,
                uid_literature=_stringify(source_record.get("uid_literature")),
                cite_key=_stringify(source_record.get("cite_key")),
                source_stage="A050",
                api_key_file=api_key_file or None,
                global_config_path=global_config_path if global_config_path.exists() else None,
                overwrite_existing=structured_overwrite,
                model=parse_model or "auto",
            )
            if enable_aliyun_postprocess:
                postprocess_aliyun_multimodal_parse_outputs(
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
                    config_path=global_config_path,
                    api_key_file=api_key_file or None,
                )
            structured_path = Path(_stringify(parse_asset.get("normalized_structured_path"))).resolve()
            backend = "aliyun_multimodal"
            task_type = parse_level
        else:
            output_dir = resolve_pdf_structured_variant_output_dir(
                workspace_root,
                converter=structured_converter,
                task_type=structured_task_type,
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            output_name = _stringify(source_record.get("cite_key")) or _stringify(source_record.get("uid_literature")) or pdf_file.stem
            structured_path = (output_dir / f"{output_name}.structured.json").resolve()
            if not structured_path.exists() or structured_overwrite:
                if structured_converter == "local_pipeline_v2":
                    convert_pdf_to_structured_data_file_local_v2(
                        pdf_file.resolve(),
                        structured_path,
                        extractors=structured_extractors,
                        task_type=structured_task_type,
                        uid_literature=_stringify(source_record.get("uid_literature")),
                        cite_key=_stringify(source_record.get("cite_key")),
                        source_metadata={
                            "title": _stringify(source_record.get("title")),
                            "year": _stringify(source_record.get("year")),
                        },
                    )
                elif structured_converter == "babeldoc":
                    convert_pdf_to_structured_data_file_babeldoc(
                        pdf_file.resolve(),
                        structured_path,
                        babeldoc=structured_babeldoc,
                        task_type=structured_task_type,
                        uid_literature=_stringify(source_record.get("uid_literature")),
                        cite_key=_stringify(source_record.get("cite_key")),
                        source_metadata={
                            "title": _stringify(source_record.get("title")),
                            "year": _stringify(source_record.get("year")),
                        },
                    )
                else:
                    raise ValueError(f"不支持的 structured_converter: {structured_converter}")
            backend = structured_converter
            task_type = structured_task_type

    structured_data = load_structured_data(structured_path)
    extract_result = extract_reference_lines_from_structured_data(structured_data)
    text_payload = structured_data.get("text") if isinstance(structured_data.get("text"), dict) else {}
    references_payload = structured_data.get("references") if isinstance(structured_data.get("references"), list) else []
    structured_updated_at = _stringify(((structured_data.get("parse_profile") or {}).get("created_at")))
    structured_schema_version = _stringify(structured_data.get("schema"))
    structured_text_length = len(str(text_payload.get("full_text") or ""))
    structured_reference_count = len(references_payload)
    uid_literature = _stringify(source_record.get("uid_literature"))
    if uid_literature:
        save_structured_state(
            content_db,
            uid_literature=uid_literature,
            structured_status="ready",
            structured_abs_path=str(structured_path),
            structured_backend=backend,
            structured_task_type=task_type,
            structured_updated_at=structured_updated_at,
            structured_schema_version=structured_schema_version,
            structured_text_length=structured_text_length,
            structured_reference_count=structured_reference_count,
        )
        working_literature = _apply_structured_state_to_table(
            working_literature,
            uid_literature=uid_literature,
            structured_abs_path=str(structured_path),
            structured_backend=backend,
            structured_task_type=task_type,
            structured_updated_at=structured_updated_at,
            structured_schema_version=structured_schema_version,
            structured_text_length=structured_text_length,
            structured_reference_count=structured_reference_count,
        )

    source_record["structured_abs_path"] = str(structured_path)
    source_record["structured_backend"] = backend
    source_record["structured_task_type"] = task_type
    source_record["pdf_path"] = _stringify(extract_result.get("attachment_path")) or _stringify(source_record.get("pdf_path"))
    return working_literature, source_record, list(extract_result.get("reference_lines") or []), list(extract_result.get("reference_line_details") or []), True


def _resolve_content_db_path(
    raw_cfg: Dict[str, Any],
    global_cfg: Dict[str, Any],
) -> Tuple[Path | None, str]:
    """优先使用节点配置，其次回退到 workspace 全局 config。"""

    content_db_path, db_input_key = resolve_content_db_config(raw_cfg)
    if content_db_path is not None:
        return content_db_path, db_input_key

    paths_cfg = global_cfg.get("paths") if isinstance(global_cfg.get("paths"), dict) else {}
    fallback_raw = _stringify(paths_cfg.get("content_db_path"))
    if not fallback_raw:
        return None, ""

    fallback_path = Path(fallback_raw)
    if not fallback_path.is_absolute():
        raise ValueError(f"config.paths.content_db_path 必须为绝对路径: {fallback_path}")
    return fallback_path, "config.paths.content_db_path"


def _ensure_csv(path: Path, headers: Iterable[str]) -> Path:
    """确保 CSV 文件存在且至少带表头。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        pd.DataFrame(columns=list(headers)).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _append_section(path: Path, title: str, lines: List[str]) -> None:
    """向文本文件追加带标题的区块。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    block_lines = [f"## {title}"]
    if lines:
        block_lines.extend(lines)
    else:
        block_lines.append("- 未提取到参考文献")
    block = "\n".join(block_lines).strip() + "\n\n"
    path.write_text(existing + block, encoding="utf-8")


def _extract_reference_lines_from_text(text: str) -> List[str]:
    """从全文文本提取参考文献行。"""

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


def _read_pdf_text(pdf_path: Path) -> str:
    """尽量读取本地 PDF 文本，失败时返回空串。"""

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

    try:
        from autodokit.tools.pdf_elements_extractors import extract_text_with_rapidocr

        text, status, _meta = extract_text_with_rapidocr(pdf_path)
        if text.strip():
            return text
        _ = status
    except Exception:
        return ""

    return ""


def _resolve_pdf_file(pdf_path_raw: str, workspace_root: Path) -> Path | None:
    """把数据库中的附件路径解析为当前工作区可访问的真实 PDF 路径。"""

    raw = _stringify(pdf_path_raw)
    if not raw:
        return None

    raw_path = Path(raw)
    candidates: List[Path] = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        normalized = raw.replace("\\", "/")
        trimmed = normalized
        for prefix in ("workspace/", "./workspace/"):
            if trimmed.startswith(prefix):
                trimmed = trimmed[len(prefix) :]
                break
        candidates.extend(
            [
                workspace_root / trimmed,
                workspace_root / normalized,
                workspace_root.parent / trimmed,
                workspace_root.parent / normalized,
                workspace_root / "references" / "attachments" / raw_path.name,
                workspace_root.parent / "references" / "attachments" / raw_path.name,
            ]
        )

    seen: set[str] = set()
    for candidate in candidates:
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None

def _render_standard_note_body(
    row: Dict[str, Any],
    reference_lines: List[str],
    batch_rows: List[Dict[str, Any]] | None = None,
) -> str:
    """生成综述标准笔记骨架正文。"""

    title = _stringify(row.get("title")) or _stringify(row.get("cite_key")) or _stringify(row.get("uid_literature"))
    year = _stringify(row.get("year")) or ""
    keywords = _stringify(row.get("keywords")) or ""
    abstract = _stringify(row.get("abstract")) or ""
    placeholder_refs = [f"- [[{_stringify(row.get('cite_key')) or _stringify(row.get('uid_literature'))}]]"]
    if reference_lines:
        placeholder_refs.extend([f"- {item}" for item in reference_lines])
    else:
        placeholder_refs.append("- 待 A070 扫描后回填")
    batch_lines = ["- 待补充批次"]
    if batch_rows:
        batch_lines = [
            f"- 批次：{_stringify(item.get('batch_id')) or 'unknown'} | 优先级：{_stringify(item.get('priority')) or 'unknown'} | 阶段：{_stringify(item.get('read_stage')) or 'unknown'}"
            for item in batch_rows
        ]
    return "\n".join(
        [
            f"# {(_stringify(row.get('cite_key')) or _stringify(row.get('uid_literature')))}",
            "",
            "## 文献信息",
            f"- 标题：{title}",
            f"- 年份：{year}",
            f"- 关键词：{keywords or '待补充'}",
            "- 当前综述回链：[[" + (_stringify(row.get("cite_key")) or _stringify(row.get("uid_literature"))) + "]]",
            "",
            "## 研究问题",
            "- 待 A070 填充",
            "",
            "## 研究方法与证据",
            "- 待 A070 填充",
            "",
            "## 核心发现",
            "- 待 A070 填充",
            "",
            "## 阅读批次",
            *batch_lines,
            "",
            "## 共识与争议",
            "- 待 A070 填充",
            "",
            "## 未来方向",
            "- 待 A070 填充",
            "",
            "## 摘要摘录",
            abstract or "- 待补充",
            "",
            "## 参考文献列表",
            *placeholder_refs,
        ]
    )


def _render_composite_note(title: str, summary: str) -> str:
    """生成综合笔记骨架正文。"""

    return "\n".join(
        [
            f"# {title}",
            "",
            "> [!note]",
            f"> {summary}",
            "",
            "## 输入综述",
            "- 待 A070 回填 `[[cite_key]]` 列表",
            "",
            "## 结构化提要",
            "- 待 A070 填充",
            "",
            "## 证据回链",
            "- 待 A070 填充 `[[cite_key]]`",
        ]
    )


def _write_standard_note_references(note_path: Path, reference_entries: List[str]) -> None:
    """回填标准笔记的参考文献列表章节。"""

    text = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
    marker = "## 参考文献列表"
    prefix, _, _ = text.partition(marker)
    entries = reference_entries or ["- 待 A070 扫描后回填"]
    new_text = prefix.rstrip() + "\n\n" + marker + "\n" + "\n".join(entries) + "\n"
    note_path.write_text(new_text, encoding="utf-8")


def _build_note_dirs(workspace_root: Path) -> Dict[str, Path]:
    """返回 A05/A06 相关目录。"""

    knowledge_root = workspace_root / "knowledge"
    return {
        "views": workspace_root / "views" / "review_candidates",
        "batches": workspace_root / "batches" / "review_candidates",
        "standard_notes": knowledge_root / "standard_notes",
        "review_summaries": knowledge_root / "review_summaries",
        "trajectories": knowledge_root / "trajectories",
        "frameworks": knowledge_root / "frameworks",
        "audits": knowledge_root / "audits",
        "matrices": knowledge_root / "matrices",
    }


def _register_note(
    knowledge_index: pd.DataFrame,
    note_path: Path,
    *,
    title: str,
    note_type: str,
    status: str,
    tags: List[str],
    aliases: List[str] | None = None,
    uid_literature: str = "",
    cite_key: str = "",
    body: str,
    workspace_root: Path,
) -> Tuple[pd.DataFrame, Dict[str, Any], Dict[str, Any]]:
    """创建并同步知识笔记。"""

    note_info = knowledge_note_register(
        note_path=note_path,
        title=title,
        note_type=note_type,
        status=status,
        tags=tags,
        aliases=aliases or [],
        evidence_uids=[uid_literature] if uid_literature else [cite_key or title],
        uid_literature=uid_literature,
        cite_key=cite_key,
        body=body,
    )
    if note_type == "literature_standard_note":
        knowledge_bind_literature_standard_note(note_path, uid_literature, cite_key)
    validation = knowledge_note_validate_obsidian(note_path)
    updated_index, _ = knowledge_index_sync_from_note(knowledge_index, note_path, workspace_root=workspace_root)
    return updated_index, note_info, validation


def _prepare_review_assets(
    *,
    workspace_root: Path,
    content_db: Path,
    review_read_pool: pd.DataFrame,
    review_reading_batches: pd.DataFrame,
    literature_table: pd.DataFrame,
    global_config_path: Path | None = None,
    enable_reference_block_llm: bool = True,
    reference_block_model: str = "",
    reference_block_max_items: int = 120,
    structured_variants: List[Tuple[str, str]] | None = None,
    structured_converter: str = "local_pipeline_v2",
    structured_task_type: str = "reference_context",
    structured_overwrite: bool = False,
    structured_generation_required: bool = True,
    structured_extractors: Dict[str, Any] | None = None,
    api_key_file: str = "",
    parse_model: str = "",
    structured_babeldoc: Dict[str, Any] | None = None,
    strict_structured_only: bool = False,
    enable_reference_line_repair: bool = True,
    reference_line_repair_model: str = "auto",
    placeholder_source: str = "placeholder_from_a065_review_scan",
    run_uid_prefix: str = "a065",
    enable_aliyun_postprocess: bool = True,
    enable_llm_basic_cleanup: bool = True,
    basic_cleanup_llm_model: str = "qwen3.5-flash",
    basic_cleanup_llm_sdk_backend: str | None = None,
    basic_cleanup_llm_region: str = "cn-beijing",
    enable_llm_structure_resolution: bool = True,
    structure_llm_model: str = "qwen3.5-plus",
    structure_llm_sdk_backend: str | None = None,
    structure_llm_region: str = "cn-beijing",
    enable_llm_contamination_filter: bool = True,
    contamination_llm_model: str = "qwen3-max",
    contamination_llm_sdk_backend: str | None = None,
    contamination_llm_region: str = "cn-beijing",
    postprocess_rewrite_structured: bool = True,
    postprocess_rewrite_markdown: bool = True,
    postprocess_keep_page_markers: bool = False,
) -> Dict[str, Any]:
    """预创建 A06 所需资产骨架并执行参考文献占位映射。"""

    dirs = _build_note_dirs(workspace_root)
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)

    for filename, headers in STRUCTURED_ATTACHMENT_HEADERS.items():
        _ensure_csv(dirs["audits"] / filename, headers)
    created_notes_path = _ensure_csv(dirs["audits"] / "created_notes.csv", PROCESS_FILE_HEADERS["created_notes.csv"])
    mapping_path = _ensure_csv(dirs["audits"] / "reference_citation_mapping.csv", PROCESS_FILE_HEADERS["reference_citation_mapping.csv"])
    reference_scan_status_path = _ensure_csv(dirs["audits"] / "reference_scan_status.csv", PROCESS_FILE_HEADERS["reference_scan_status.csv"])
    reference_dump_path = dirs["audits"] / "引文识别原文.txt"
    quality_summary_path = dirs["audits"] / "reference_citation_quality_summary.json"
    reference_dump_path.write_text("", encoding="utf-8")

    composite_specs = [
        (dirs["trajectories"] / "领域研究脉络.md", "领域研究脉络", "研究脉络种子，记录时间线与主题演进骨架。"),
        (dirs["review_summaries"] / "核心成果.md", "核心成果", "核心成果汇总骨架。"),
        (dirs["review_summaries"] / "共识点.md", "共识点", "综述共识汇总骨架。"),
        (dirs["review_summaries"] / "争议点.md", "争议点", "综述争议汇总骨架。"),
        (dirs["review_summaries"] / "未来方向.md", "未来方向", "未来研究方向骨架。"),
        (dirs["frameworks"] / "领域知识框架.md", "领域知识框架", "领域知识框架骨架。"),
        (dirs["matrices"] / "综述矩阵.md", "综述矩阵", "综述矩阵骨架，用于后续整理主题、方法与结论。"),
    ]

    try:
        knowledge_index, knowledge_attachments, knowledge_db = load_knowledge_tables(db_path=content_db)
    except Exception:
        knowledge_index = init_empty_knowledge_index_table()
        knowledge_attachments = init_empty_knowledge_attachments_table()
        knowledge_db = content_db
    _ = knowledge_attachments

    created_note_rows: List[Dict[str, Any]] = []
    validation_errors: List[str] = []
    placeholder_run_uid = f"{run_uid_prefix}-{now_compact()}"
    for path, title, summary in composite_specs:
        knowledge_index, note_info, validation = _register_note(
            knowledge_index,
            path,
            title=title,
            note_type="knowledge_note",
            status="draft",
            tags=["aok/review", "a05"],
            body=_render_composite_note(title, summary),
            workspace_root=workspace_root,
        )
        created_note_rows.append(
            {
                "uid_literature": "",
                "cite_key": title,
                "note_type": "knowledge_note",
                "note_path": str(path),
                "status": note_info.get("status", "draft"),
            }
        )
        validation_errors.extend(validation.get("errors") or [])

    working_literature = literature_table.copy()
    reference_mapping_rows: List[Dict[str, Any]] = []
    reference_scan_rows: List[Dict[str, Any]] = []
    reference_scan_tag_rows: List[Dict[str, Any]] = []
    per_note_references: Dict[str, List[str]] = {}
    literature_by_uid = {}
    if not working_literature.empty and "uid_literature" in working_literature.columns:
        literature_by_uid = {
            _stringify(row.get("uid_literature")): dict(row)
            for _, row in working_literature.iterrows()
            if _stringify(row.get("uid_literature"))
        }
    batch_rows_by_uid: Dict[str, List[Dict[str, Any]]] = {}
    if not review_reading_batches.empty and "uid_literature" in review_reading_batches.columns:
        for _, batch_row in review_reading_batches.iterrows():
            uid_key = _stringify(batch_row.get("uid_literature"))
            if not uid_key:
                continue
            batch_rows_by_uid.setdefault(uid_key, []).append(dict(batch_row))

    for _, row in review_read_pool.iterrows():
        record = dict(row)
        uid_literature = _stringify(record.get("uid_literature"))
        source_record = literature_by_uid.get(uid_literature, record)
        cite_key = _stringify(source_record.get("cite_key")) or uid_literature
        source_record["cite_key"] = cite_key
        note_path = dirs["standard_notes"] / f"{cite_key}.md"

        pdf_path = _stringify(
            source_record.get("pdf_path")
            or source_record.get("primary_attachment_path")
            or source_record.get("attachment_path")
        )
        reference_lines: List[str] = []
        reference_line_details: List[Dict[str, Any]] = []
        used_structured = False
        scan_status = "scanned"
        scan_reason = ""
        try:
            working_literature, source_record, reference_lines, reference_line_details, used_structured = _ensure_structured_reference_lines(
                source_record=source_record,
                workspace_root=workspace_root,
                content_db=content_db,
                working_literature=working_literature,
                structured_variants=structured_variants or list(DEFAULT_STRUCTURED_VARIANTS),
                structured_converter=structured_converter,
                structured_task_type=structured_task_type,
                structured_overwrite=structured_overwrite,
                structured_generation_required=structured_generation_required,
                structured_extractors=structured_extractors,
                api_key_file=api_key_file,
                parse_model=parse_model,
                structured_babeldoc=structured_babeldoc,
            )
        except Exception as exc:
            if strict_structured_only:
                raise RuntimeError(f"strict_structured_only=True 且 structured 不可用: uid={uid_literature}, reason={exc}") from exc
            if structured_generation_required and pdf_path:
                raise
            scan_status = "missing_pdf" if not pdf_path else "structured_extract_failed"
            scan_reason = "缺少 PDF，跳过参考文献扫描。" if not pdf_path else f"结构化参考文献抽取失败：{exc}"
        if strict_structured_only and not used_structured:
            raise RuntimeError(f"strict_structured_only=True，禁止降级到 PDF 抽取: uid={uid_literature}")

        if not used_structured and pdf_path and not strict_structured_only:
            extract_result = extract_reference_lines_from_attachment(
                pdf_path,
                workspace_root=workspace_root,
                print_to_stdout=True,
            )
            source_record["pdf_path"] = _stringify(extract_result.get("attachment_path")) or pdf_path
            reference_lines = list(extract_result.get("reference_lines") or [])
            reference_line_details = list(extract_result.get("reference_line_details") or [])
        if not used_structured and not pdf_path:
            reference_line_details = []
            scan_status = "missing_pdf"
            scan_reason = scan_reason or "缺少 PDF，跳过参考文献扫描。"

        if enable_reference_block_llm and reference_lines:
            cleanup_result = refine_reference_lines_with_llm(
                reference_lines,
                workspace_root=workspace_root,
                global_config_path=global_config_path,
                model=reference_block_model or None,
                cite_key=cite_key,
                title=_stringify(source_record.get("title")),
                max_items=reference_block_max_items,
                print_to_stdout=False,
            )
            reference_lines = list(cleanup_result.get("reference_lines") or reference_lines)

        if reference_line_details:
            detail_by_text = {
                _stringify(item.get("reference_text")): dict(item)
                for item in reference_line_details
                if _stringify(item.get("reference_text"))
            }
        else:
            detail_by_text = {
                line: {
                    "reference_text": line,
                    "suspicious_merged": 0,
                    "noise_trimmed": 0,
                }
                for line in reference_lines
            }

        knowledge_index, note_info, validation = _register_note(
            knowledge_index,
            note_path,
            title=cite_key,
            note_type="literature_standard_note",
            status="draft",
            tags=["aok/review", "a05", "literature/review"],
            aliases=[_stringify(source_record.get("title"))] if _stringify(source_record.get("title")) else [],
            uid_literature=uid_literature,
            cite_key=cite_key,
            body=_render_standard_note_body(
                source_record,
                reference_lines,
                batch_rows=batch_rows_by_uid.get(uid_literature, []),
            ),
            workspace_root=workspace_root,
        )
        created_note_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "note_type": "literature_standard_note",
                "note_path": str(note_path),
                "status": note_info.get("status", "draft"),
            }
        )
        validation_errors.extend(validation.get("errors") or [])

        _append_section(reference_dump_path, cite_key, reference_lines)
        note_reference_entries: List[str] = [f"- [[{cite_key}]]"]
        if not reference_lines:
            if scan_status == "scanned":
                scan_status = "no_reference_list"
                scan_reason = "有 PDF 或结构化文本，但文末未识别到参考文献列表，跳过参考文献处理。"
            reference_scan_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "scan_status": scan_status,
                    "reason": scan_reason,
                    "pdf_path": pdf_path,
                    "reference_note_path": str(note_path),
                }
            )
            reference_scan_tag_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "tag": f"status/{scan_status}",
                }
            )
            reference_mapping_rows.append(
                {
                    "source_uid_literature": uid_literature,
                    "source_cite_key": cite_key,
                    "reference_text": scan_reason or "当前附件扫描未形成可解析参考文献文本，待补跑 PDF 文本抽取或 OCR。",
                    "matched_uid_literature": "",
                    "matched_cite_key": "",
                    "action": "scan_skipped_missing_pdf" if scan_status == "missing_pdf" else "scan_no_reference_list",
                    "reference_note_path": str(note_path),
                }
            )
            note_reference_entries.append(f"- {scan_reason or '当前附件扫描未形成可解析参考文献文本，待补跑 PDF 文本抽取或 OCR。'}")
        else:
            reference_scan_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "scan_status": "ready",
                    "reason": "已识别参考文献列表。",
                    "pdf_path": pdf_path,
                    "reference_note_path": str(note_path),
                }
            )
            reference_scan_tag_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "tag": "status/ready",
                }
            )
        for line in reference_lines:
            line_detail = dict(detail_by_text.get(line) or {"reference_text": line, "suspicious_merged": 0, "noise_trimmed": 0})
            process_result: Dict[str, Any] = {
                "action": "skipped",
                "matched_uid_literature": "",
                "matched_cite_key": "",
                "parse_method": "",
                "llm_invoked": 0,
                "parse_failed": 1,
                "parse_failure_reason": "unknown_error",
                "is_placeholder": 0,
                "placeholder_reason": "",
                "placeholder_status": "",
                "placeholder_run_uid": "",
                "match_score": 0.0,
                "suspicious_mismatch": 0,
            }
            try:
                working_literature, process_result = process_reference_citation(
                    working_literature,
                    line,
                    workspace_root=workspace_root,
                    global_config_path=global_config_path,
                    source=placeholder_source,
                    placeholder_run_uid=placeholder_run_uid,
                    enable_reference_line_repair=enable_reference_line_repair,
                    repair_model=reference_line_repair_model,
                    print_to_stdout=True,
                )
            except Exception as exc:
                process_result["parse_failure_reason"] = str(exc)

            action = _stringify(process_result.get("action")) or "skipped"
            matched_uid = _stringify(process_result.get("matched_uid_literature"))
            matched_cite_key = _stringify(process_result.get("matched_cite_key"))
            note_reference_entries.append(f"- [[{matched_cite_key}]]" if matched_cite_key else f"- {line}")
            reference_mapping_rows.append(
                {
                    "source_uid_literature": uid_literature,
                    "source_cite_key": cite_key,
                    "reference_text": line,
                    "matched_uid_literature": matched_uid,
                    "matched_cite_key": matched_cite_key,
                    "action": action,
                    "parse_method": _stringify(process_result.get("parse_method")),
                    "llm_invoked": int(process_result.get("llm_invoked") or 0),
                    "parse_failed": int(process_result.get("parse_failed") or 0),
                    "parse_failure_reason": _stringify(process_result.get("parse_failure_reason")),
                    "is_placeholder": int(process_result.get("is_placeholder") or 0),
                    "placeholder_reason": _stringify(process_result.get("placeholder_reason")),
                    "placeholder_status": _stringify(process_result.get("placeholder_status")),
                    "placeholder_run_uid": _stringify(process_result.get("placeholder_run_uid")) or placeholder_run_uid,
                    "suspicious_merged": int(line_detail.get("suspicious_merged") or 0),
                    "noise_trimmed": int(line_detail.get("noise_trimmed") or 0),
                    "match_score": float(process_result.get("match_score") or 0.0),
                    "suspicious_mismatch": int(process_result.get("suspicious_mismatch") or 0),
                    "reference_note_path": str(note_path),
                }
            )

        per_note_references[str(note_path)] = note_reference_entries

    for note_path_str, entries in per_note_references.items():
        _write_standard_note_references(Path(note_path_str), entries)

    pd.DataFrame(created_note_rows, columns=PROCESS_FILE_HEADERS["created_notes.csv"]).to_csv(
        created_notes_path,
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(reference_mapping_rows, columns=PROCESS_FILE_HEADERS["reference_citation_mapping.csv"]).to_csv(
        mapping_path,
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(reference_scan_rows, columns=PROCESS_FILE_HEADERS["reference_scan_status.csv"]).to_csv(
        reference_scan_status_path,
        index=False,
        encoding="utf-8-sig",
    )
    quality_summary = build_reference_quality_summary(reference_mapping_rows)
    quality_summary_path.write_text(json.dumps(quality_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"reference_quality_summary": quality_summary}, ensure_ascii=False, indent=2))

    persist_reference_main_table(working_literature, content_db)
    persist_knowledge_tables(index_df=knowledge_index, attachments_df=knowledge_attachments, db_path=knowledge_db)
    if reference_scan_tag_rows:
        replace_tags_for_namespace(
            content_db,
            namespace="a050/reference_scan",
            tag_rows=reference_scan_tag_rows,
            source_type="a050_review_scan",
        )

    return {
        "created_notes_path": created_notes_path,
        "reference_dump_path": reference_dump_path,
        "mapping_path": mapping_path,
        "reference_scan_status_path": reference_scan_status_path,
        "quality_summary_path": quality_summary_path,
        "quality_summary": quality_summary,
        "validation_errors": validation_errors,
        "created_note_count": len(created_note_rows),
        "mapped_reference_count": len(reference_mapping_rows),
        "reference_scan_skipped_count": sum(1 for row in reference_scan_rows if _stringify(row.get("scan_status")) != "ready"),
    }


def _load_candidate_records(raw_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """加载候选记录集合。"""

    if raw_cfg.get("candidates"):
        return list(raw_cfg.get("candidates") or [])
    input_csv_raw = str(raw_cfg.get("input_csv") or "").strip()
    if not input_csv_raw:
        return []
    input_csv = Path(input_csv_raw)
    if input_csv.is_file():
        return pd.read_csv(input_csv, dtype=str, keep_default_na=False).to_dict(orient="records")
    return []


@affair_auto_git_commit("A050")
def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    global_config_path = workspace_root / "config" / "config.json"
    if not global_config_path.exists():
        global_config_path = None
    global_cfg = _load_global_config(global_config_path)
    content_db_path, db_input_key = _resolve_content_db_path(raw_cfg, global_cfg)
    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(f"output_dir 必须为绝对路径: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    global_config_path = workspace_root / "config" / "config.json"
    if not global_config_path.exists():
        global_config_path = None
    enable_reference_block_llm = bool(raw_cfg.get("enable_reference_block_llm", True))
    reference_block_model = _stringify(raw_cfg.get("reference_block_model") or raw_cfg.get("single_document_model"))
    reference_block_max_items = int(raw_cfg.get("reference_block_max_items") or 120)
    structured_variants = _collect_structured_variants(raw_cfg)
    structured_converter = structured_variants[0][0]
    structured_task_type = structured_variants[0][1]
    structured_overwrite = bool(raw_cfg.get("structured_overwrite", False))
    structured_generation_required = bool(raw_cfg.get("structured_generation_required", True))
    structured_extractors = raw_cfg.get("structured_extractors") if isinstance(raw_cfg.get("structured_extractors"), dict) else None
    structured_babeldoc = raw_cfg.get("structured_babeldoc") if isinstance(raw_cfg.get("structured_babeldoc"), dict) else None
    logging_enabled = _resolve_logging_enabled(global_cfg)
    canonical_dirs = _build_note_dirs(workspace_root)
    canonical_dirs["views"].mkdir(parents=True, exist_ok=True)
    canonical_dirs["batches"].mkdir(parents=True, exist_ok=True)

    candidates = _load_candidate_records(raw_cfg)
    content_db_raw = str(content_db_path) if content_db_path is not None else str(raw_cfg.get("literature_csv") or "").strip()
    literature_table = pd.DataFrame()
    content_db: Path | None = None
    if content_db_raw:
        content_db = Path(content_db_raw)
        if not content_db.is_absolute():
            raise ValueError(f"content_db 必须为绝对路径: {content_db}")
        if content_db.exists():
            literature_table = load_reference_main_table(content_db)

    extra_fields = list(raw_cfg.get("extra_fields") or [])
    for field in ["topic_relevance_score", "topic_group_match_count", "topic_matched_terms", "research_topic"]:
        if field not in extra_fields:
            extra_fields.append(field)

    scope_key = _build_scope_key(raw_cfg)
    run_uid = _build_run_uid(scope_key)

    direct_from_reference_db = not candidates and not literature_table.empty

    if direct_from_reference_db:
        views = build_review_candidate_views(
            literature_table,
            source_round=str(raw_cfg.get("source_round") or "round_direct_topic"),
            source_affair=str(raw_cfg.get("source_affair") or "review_candidate_views"),
            min_score=float(raw_cfg.get("min_score") or 0.0),
            top_k=int(raw_cfg.get("top_k")) if raw_cfg.get("top_k") else None,
            batch_size=int(raw_cfg.get("batch_size") or raw_cfg.get("review_batch_size") or 10),
            extra_fields=extra_fields,
            research_topic=str(raw_cfg.get("research_topic") or "").strip(),
            topic_terms=raw_cfg.get("topic_terms") or [],
            topic_keyword_groups=raw_cfg.get("topic_keyword_groups") or [],
            required_topic_group_indices=raw_cfg.get("required_topic_group_indices") or [],
            min_topic_group_matches=int(raw_cfg.get("min_topic_group_matches")) if raw_cfg.get("min_topic_group_matches") is not None else None,
            min_year=int(raw_cfg.get("min_year")) if raw_cfg.get("min_year") is not None else None,
            max_year=int(raw_cfg.get("max_year")) if raw_cfg.get("max_year") is not None else None,
            recent_years=int(raw_cfg.get("recent_years")) if raw_cfg.get("recent_years") is not None else None,
            review_detection_fields=raw_cfg.get("review_detection_fields") or ["title", "keywords", "entry_type"],
            relevance_text_fields=raw_cfg.get("relevance_text_fields") or ["title", "keywords", "abstract"],
        )
        review_candidate_pool_index = views["review_candidate_pool_index"]
        review_candidate_pool_readable = views["review_candidate_pool_readable"]
        review_priority_view = views["review_priority_view"]
        review_deep_read_queue_seed = views["review_deep_read_queue_seed"]
        review_read_pool = views["review_read_pool"]
        review_already_read_exit_view = views["review_already_read_exit_view"]
        review_reading_batches = views["review_reading_batches"]
    else:
        candidate_index = build_candidate_view_index(
            candidates,
            source_round=str(raw_cfg.get("source_round") or "round_01"),
            source_affair=str(raw_cfg.get("source_affair") or "review_candidate_views"),
            min_score=float(raw_cfg.get("min_score") or 0.0),
            top_k=int(raw_cfg.get("top_k")) if raw_cfg.get("top_k") else None,
        )
        readable_view = build_candidate_readable_view(candidate_index, literature_table, extra_fields=extra_fields)
        review_candidate_pool_readable = extract_review_candidates(readable_view)
        review_uids = review_candidate_pool_readable.get("uid_literature", pd.Series(dtype=str)).tolist()
        review_candidate_pool_index = candidate_index[candidate_index["uid_literature"].astype(str).isin(review_uids)].reset_index(drop=True) if not candidate_index.empty else candidate_index.copy()
        review_priority_view = review_candidate_pool_readable.sort_values(by=["score", "year"], ascending=[False, False], na_position="last").reset_index(drop=True) if not review_candidate_pool_readable.empty else review_candidate_pool_readable.copy()
        review_read_pool = review_priority_view.copy()
        if not review_priority_view.empty:
            unread_mask = ~review_priority_view.get("status", pd.Series(dtype=str)).astype(str).str.lower().isin(["read", "completed"])
            review_read_pool = review_priority_view.loc[unread_mask].reset_index(drop=True)
            review_already_read_exit_view = review_priority_view.loc[~unread_mask].reset_index(drop=True)
        else:
            review_already_read_exit_view = review_priority_view.copy()
        review_deep_read_queue_seed = review_read_pool.head(min(max(int(raw_cfg.get("batch_size") or 10), 1), 5)).reset_index(drop=True)
        review_reading_batches = allocate_reading_batches(
            review_candidate_pool_index,
            batch_size=int(raw_cfg.get("batch_size") or raw_cfg.get("review_batch_size") or 10),
            review_uid_set=review_uids,
        )

    index_path = output_dir / "review_candidate_pool_index.csv"
    readable_path = output_dir / "review_candidate_pool_readable.csv"
    review_path = output_dir / "review_priority_view.csv"
    queue_seed_path = output_dir / "review_deep_read_queue_seed.csv"
    read_pool_path = output_dir / "review_read_pool.csv"
    exit_view_path = output_dir / "review_already_read_exit_view.csv"
    batch_path = output_dir / "review_reading_batches.csv"
    canonical_index_path = canonical_dirs["views"] / index_path.name
    canonical_readable_path = canonical_dirs["views"] / readable_path.name
    canonical_review_path = canonical_dirs["views"] / review_path.name
    canonical_queue_seed_path = canonical_dirs["views"] / queue_seed_path.name
    canonical_read_pool_path = canonical_dirs["views"] / read_pool_path.name
    canonical_exit_view_path = canonical_dirs["views"] / exit_view_path.name
    canonical_batch_path = canonical_dirs["batches"] / batch_path.name
    review_candidate_pool_index.to_csv(index_path, index=False, encoding="utf-8-sig")
    review_candidate_pool_readable.to_csv(readable_path, index=False, encoding="utf-8-sig")
    review_priority_view.to_csv(review_path, index=False, encoding="utf-8-sig")
    review_deep_read_queue_seed.to_csv(queue_seed_path, index=False, encoding="utf-8-sig")
    review_read_pool.to_csv(read_pool_path, index=False, encoding="utf-8-sig")
    review_already_read_exit_view.to_csv(exit_view_path, index=False, encoding="utf-8-sig")
    review_reading_batches.to_csv(batch_path, index=False, encoding="utf-8-sig")
    review_candidate_pool_index.to_csv(canonical_index_path, index=False, encoding="utf-8-sig")
    review_candidate_pool_readable.to_csv(canonical_readable_path, index=False, encoding="utf-8-sig")
    review_priority_view.to_csv(canonical_review_path, index=False, encoding="utf-8-sig")
    review_deep_read_queue_seed.to_csv(canonical_queue_seed_path, index=False, encoding="utf-8-sig")
    review_read_pool.to_csv(canonical_read_pool_path, index=False, encoding="utf-8-sig")
    review_already_read_exit_view.to_csv(canonical_exit_view_path, index=False, encoding="utf-8-sig")
    review_reading_batches.to_csv(canonical_batch_path, index=False, encoding="utf-8-sig")

    review_view_tables = {
        "review_candidate_pool_index": review_candidate_pool_index,
        "review_candidate_pool_readable": review_candidate_pool_readable,
        "review_priority_view": review_priority_view,
        "review_deep_read_queue_seed": review_deep_read_queue_seed,
        "review_read_pool": review_read_pool,
        "review_already_read_exit_view": review_already_read_exit_view,
        "review_reading_batches": review_reading_batches,
    }

    prepared_assets = {
        "created_note_count": 0,
        "mapped_reference_count": 0,
        "validation_errors": [],
    }
    a060_queue_count = 0
    if content_db is not None:
        a060_queue_rows: List[Dict[str, Any]] = []
        for _, row in review_read_pool.fillna("").iterrows():
            uid_literature = _stringify(row.get("uid_literature"))
            cite_key = _stringify(row.get("cite_key"))
            if not uid_literature and not cite_key:
                continue
            a060_queue_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "stage": "A060",
                    "source_affair": "A050",
                    "queue_status": "queued",
                    "priority": row.get("score") or row.get("priority") or 70.0,
                    "bucket": "review_read_pool",
                    "preferred_next_stage": "A060",
                    "recommended_reason": _stringify(row.get("recommended_reason")) or "A050 review read pool",
                    "theme_relation": _stringify(row.get("research_topic")) or _stringify(raw_cfg.get("research_topic")) or "A050_topic",
                    "source_round": _stringify(raw_cfg.get("source_round")) or "a050",
                    "run_uid": run_uid,
                    "scope_key": scope_key,
                    "is_current": 1,
                }
            )
        if a060_queue_rows:
            upsert_reading_queue_rows(content_db, a060_queue_rows)
            a060_queue_count = len(a060_queue_rows)
            replace_tags_for_namespace(
                content_db,
                namespace="queue/a060",
                tag_rows=[
                    {
                        "uid_literature": _stringify(item.get("uid_literature")),
                        "cite_key": _stringify(item.get("cite_key")),
                        "tag": "status/queued",
                    }
                    for item in a060_queue_rows
                ],
                source_type="a050_queue",
            )

    gate_review = build_gate_review(
        node_uid="A05",
        node_name="候选文献视图构建",
        summary=f"基于文献总库生成综述候选 {len(review_candidate_pool_index)} 条，可读视图 {len(review_candidate_pool_readable)} 条，阅读批次 {review_reading_batches['batch_id'].nunique() if not review_reading_batches.empty else 0} 个，并写入 A060 当前态队列 {a060_queue_count} 条。",
        checks=[
            {"name": "review_candidate_count", "value": len(review_candidate_pool_index)},
            {"name": "review_read_pool_count", "value": len(review_read_pool)},
            {"name": "batch_count", "value": int(review_reading_batches['batch_id'].nunique()) if not review_reading_batches.empty else 0},
            {"name": "created_note_count", "value": prepared_assets["created_note_count"]},
            {"name": "mapped_reference_count", "value": prepared_assets["mapped_reference_count"]},
            {"name": "a060_queue_count", "value": a060_queue_count},
            {"name": "reference_total_count", "value": (prepared_assets.get("quality_summary") or {}).get("total_reference_count", 0)},
            {"name": "llm_recognized_count", "value": (prepared_assets.get("quality_summary") or {}).get("llm_recognized_count", 0)},
            {"name": "placeholder_count", "value": (prepared_assets.get("quality_summary") or {}).get("placeholder_count", 0)},
            {"name": "suspicious_merged_count", "value": (prepared_assets.get("quality_summary") or {}).get("suspicious_merged_count", 0)},
            {"name": "suspicious_mismatch_count", "value": (prepared_assets.get("quality_summary") or {}).get("suspicious_mismatch_count", 0)},
            {"name": "reference_scan_skipped_count", "value": prepared_assets.get("reference_scan_skipped_count", 0)},
            {"name": "recent_years", "value": raw_cfg.get("recent_years")},
            {"name": "research_topic", "value": raw_cfg.get("research_topic")},
        ],
        artifacts=[
            str(index_path),
            str(readable_path),
            str(review_path),
            str(queue_seed_path),
            str(read_pool_path),
            str(exit_view_path),
            str(batch_path),
            str(canonical_index_path),
            str(canonical_readable_path),
            str(canonical_review_path),
            str(canonical_read_pool_path),
            str(canonical_batch_path),
        ],
        recommendation="pass" if len(review_candidate_pool_index) > 0 else "fallback",
        score=90.0 if len(review_candidate_pool_index) > 0 else 35.0,
        issues=(prepared_assets["validation_errors"] or []) if len(review_candidate_pool_index) > 0 else ["当前文献总库在给定年份窗口与主题条件下未筛出可用综述候选，建议回流 A04 补充专题综述来源。"],
        metadata={
            "direct_from_reference_db": direct_from_reference_db,
            "scope_key": scope_key,
            "run_uid": run_uid,
            "workspace_root": str(workspace_root),
            "content_db": content_db_raw,
            "db_input_key": db_input_key,
            "research_topic": raw_cfg.get("research_topic"),
            "topic_terms": raw_cfg.get("topic_terms") or [],
            "topic_keyword_groups": raw_cfg.get("topic_keyword_groups") or [],
            "required_topic_group_indices": raw_cfg.get("required_topic_group_indices") or [],
            "recent_years": raw_cfg.get("recent_years"),
            "created_note_count": prepared_assets["created_note_count"],
            "mapped_reference_count": prepared_assets["mapped_reference_count"],
            "a060_queue_count": a060_queue_count,
            "reference_quality_summary": prepared_assets.get("quality_summary") or {},
        },
    )
    gate_path = output_dir / "gate_review.json"
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    if content_db is not None:
        persist_review_candidate_views(
            content_db,
            view_tables=review_view_tables,
            gate_review=gate_review,
            scope_key=scope_key,
            run_uid=run_uid,
        )

    append_aok_log_event(
        event_type="A050_REVIEW_CANDIDATE_VIEWS_BUILT",
        project_root=workspace_root,
        enabled=logging_enabled,
        affair_code="A050",
        handler_name="候选文献视图构建",
        agent_names=["ar_A050_综述候选文献视图构建事务智能体_v5"],
        skill_names=["ar_A050_综述候选文献视图构建_v5", "m_ObsidianMarkdown_v1"],
        reasoning_summary="生成综述候选视图，并为 A060 预处理与 A070 研读准备输入资产。",
        gate_review=gate_review,
        gate_review_path=gate_path,
        artifact_paths=[
            index_path,
            readable_path,
            review_path,
            queue_seed_path,
            read_pool_path,
            exit_view_path,
            batch_path,
            canonical_index_path,
            canonical_readable_path,
            gate_path,
        ],
        payload={
            "review_candidate_count": len(review_candidate_pool_index),
            "read_pool_count": len(review_read_pool),
            "batch_count": int(review_reading_batches['batch_id'].nunique()) if not review_reading_batches.empty else 0,
            "a060_queue_count": a060_queue_count,
        },
    )
    return [
        index_path,
        readable_path,
        review_path,
        queue_seed_path,
        read_pool_path,
        exit_view_path,
        batch_path,
        canonical_index_path,
        canonical_readable_path,
        canonical_review_path,
        canonical_read_pool_path,
        canonical_batch_path,
        gate_path,
    ]