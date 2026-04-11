"""单篇文献粗读事务。

该事务用于在“单篇精读”之前做快速预处理：
- 读取目标文献的 structured 结果；
- 提取参考文献行并可选回写占位引文；
- 生成粗读笔记与结构化 JSON 结果，供后续精读链路复用。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件路径列表。

Examples:
    >>> from pathlib import Path
    >>> from autodokit.affairs.单篇粗读.affair import execute
    >>> execute(Path(r"D:/workspace/configs/single_rough_reading.json"))
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from autodokit.tools import load_json_or_py
from autodokit.tools.bibliodb import init_empty_table, insert_placeholder_from_reference
from autodokit.tools.llm_clients import postprocess_aliyun_multimodal_parse_outputs
from autodokit.tools.contentdb_sqlite import infer_workspace_root_from_content_db, resolve_content_db_config
from autodokit.tools.ocr.classic.pdf_parse_asset_manager import ensure_multimodal_parse_asset
from autodokit.tools.ocr.classic.pdf_structured_data_tools import load_single_document_record
from autodokit.tools.storage_backend import load_reference_main_table, persist_reference_main_table


@dataclass
class RoughReadingConfig:
    """单篇粗读配置。

    Args:
        output_dir: 输出目录。
        uid: 目标文献 uid（优先匹配 uid_literature，其次 uid）。
        doc_id: 可选目标文献 doc_id（提供时优先）。
        content_db: 可选统一内容主库路径。
        insert_placeholders_from_references: 是否将参考文献写入占位引文。
        reference_lines: 外部补充参考文献行（会与文内提取结果合并去重）。
        max_preview_chars: 粗读正文预览最大字符数。

    Returns:
        None。

    Examples:
        >>> RoughReadingConfig(
        ...     output_dir="D:/workspace/output",
        ...     uid="A001"
        ... )
    """

    output_dir: str
    uid: Optional[str] = None
    doc_id: Optional[str] = None
    content_db: str = ""
    insert_placeholders_from_references: bool = True
    reference_lines: Optional[List[str]] = None
    max_preview_chars: int = 4000
    input_structured_json: str = ""
    input_structured_dir: str = ""
    db_input_key: str = ""


def _read_target_doc_from_inputs(
    *,
    input_structured_json: str,
    input_structured_dir: str,
    content_db: str,
    uid: Optional[str],
    doc_id: Optional[str],
) -> Dict[str, Any]:
    """从结构化结果或统一内容主库读取目标文献。"""

    try:
        return load_single_document_record(
            uid=str(uid or ""),
            doc_id=str(doc_id or ""),
            structured_json_path=str(input_structured_json or ""),
            structured_dir=str(input_structured_dir or ""),
            content_db=str(content_db or ""),
        )
    except Exception as exc:
        raise ValueError(f"未能从结构化输入读取目标文献：{exc}") from exc


def _extract_reference_lines_from_text(text: str) -> List[str]:
    """从全文文本提取参考文献行。

    Args:
        text: 文献全文文本。

    Returns:
        去重后的参考文献行列表。
    """

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
    seen_lines: set[str] = set()
    for line in lines[start_index:]:
        if not line:
            continue
        if line.startswith("#"):
            break
        if len(line) < 20:
            continue
        if line not in seen_lines:
            seen_lines.add(line)
            output_lines.append(line)
    return output_lines


def _load_or_init_bibliography_table(csv_path: Path) -> pd.DataFrame:
    """加载或初始化文献数据库主表。

    Args:
        csv_path: 文献数据库路径，支持 `.db` 或 `.csv`。

    Returns:
        文献数据库 DataFrame。
    """

    if csv_path.exists():
        return load_reference_main_table(csv_path)
    return init_empty_table()


def _insert_placeholders_for_references(table: pd.DataFrame, reference_lines: List[str]) -> tuple[pd.DataFrame, Dict[str, Any]]:
    """将参考文献写入占位引文。

    Args:
        table: 文献表。
        reference_lines: 参考文献文本行。

    Returns:
        更新后的文献表与统计信息。
    """

    working = table.copy()
    inserted = 0
    exists = 0
    skipped = 0

    for line in reference_lines:
        try:
            working, _, action = insert_placeholder_from_reference(working, line)
            if action == "exists":
                exists += 1
            elif action in {"inserted", "updated"}:
                inserted += 1
        except Exception:
            skipped += 1

    return (
        working,
        {
            "total": len(reference_lines),
            "inserted": inserted,
            "exists": exists,
            "skipped": skipped,
        },
    )


def _build_rough_note(*, title: str, year: str, abstract: str, keywords: str, reference_lines: List[str], preview_text: str) -> str:
    """构建粗读 Markdown 笔记。

    Args:
        title: 文献标题。
        year: 年份。
        abstract: 摘要。
        keywords: 关键词。
        reference_lines: 参考文献行。
        preview_text: 正文预览文本。

    Returns:
        Markdown 文本。
    """

    refs_preview = reference_lines[:10]
    refs_section = "\n".join([f"- {line}" for line in refs_preview]) if refs_preview else "- 未检测到可用参考文献行"

    return "\n".join(
        [
            "## 粗读摘要",
            f"- 标题：{title}",
            f"- 年份：{year}",
            f"- 关键词：{keywords or '（缺失）'}",
            "",
            "## 摘要速览",
            abstract or "（缺失）",
            "",
            "## 正文预览",
            preview_text or "（缺失）",
            "",
            "## 参考文献扫描（最多展示10条）",
            refs_section,
            "",
            "## 后续建议",
            "- 若摘要与研究问题相关，进入单篇精读事务。",
            "- 若参考文献有效，可将占位引文写入文献库再批量追踪。",
        ]
    )


def execute(config_path: Path) -> List[Path]:
    """执行单篇粗读事务。

    Args:
        config_path: 配置文件绝对路径。

    Returns:
        输出文件路径列表（含 md/json，必要时含 csv）。

    Raises:
        ValueError: 关键路径不是绝对路径或目标文献不存在时抛出。
    """

    raw_cfg = load_json_or_py(config_path)
    content_db_path, db_input_key = resolve_content_db_config(raw_cfg)
    cfg = RoughReadingConfig(
        output_dir=str(raw_cfg.get("output_dir") or ""),
        uid=(
            str(raw_cfg.get("uid_literature")).strip()
            if raw_cfg.get("uid_literature") is not None
            else (str(raw_cfg.get("uid")).strip() if raw_cfg.get("uid") is not None else None)
        ),
        doc_id=str(raw_cfg.get("doc_id")) if raw_cfg.get("doc_id") else None,
        content_db=str(content_db_path) if content_db_path is not None else "",
        insert_placeholders_from_references=bool(raw_cfg.get("insert_placeholders_from_references", True)),
        reference_lines=list(raw_cfg.get("reference_lines") or []),
        max_preview_chars=int(raw_cfg.get("max_preview_chars") or 4000),
        input_structured_json=str(raw_cfg.get("input_structured_json") or ""),
        input_structured_dir=str(raw_cfg.get("input_structured_dir") or ""),
        db_input_key=db_input_key,
    )

    output_dir = Path(cfg.output_dir)
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认主流程已执行统一路径预处理，"
            f"当前值={cfg.output_dir!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    if cfg.content_db and not cfg.input_structured_json and not cfg.input_structured_dir:
        workspace_root = infer_workspace_root_from_content_db(Path(cfg.content_db))
        global_config_path = workspace_root / "config" / "config.json"
        parse_asset = ensure_multimodal_parse_asset(
            content_db=cfg.content_db,
            parse_level="non_review_rough",
            uid_literature=str(cfg.uid or ""),
            doc_id=str(cfg.doc_id or ""),
            source_stage="single_rough_read",
            api_key_file=raw_cfg.get("api_key_file"),
            global_config_path=global_config_path if global_config_path.exists() else None,
            overwrite_existing=False,
            model=str(raw_cfg.get("parse_model") or raw_cfg.get("structured_model") or "auto"),
        )
        postprocess_aliyun_multimodal_parse_outputs(
            normalized_structured_path=str(parse_asset.get("normalized_structured_path") or ""),
            reconstructed_markdown_path=str(parse_asset.get("reconstructed_markdown_path") or ""),
            rewrite_structured=True,
            rewrite_markdown=True,
            keep_page_markers=False,
        )
        cfg.input_structured_json = str(parse_asset.get("normalized_structured_path") or "")

    doc = _read_target_doc_from_inputs(
        input_structured_json=cfg.input_structured_json,
        input_structured_dir=cfg.input_structured_dir,
        content_db=cfg.content_db,
        uid=cfg.uid,
        doc_id=cfg.doc_id,
    )
    title = str(doc.get("title") or doc.get("meta", {}).get("title") or "未命名")
    year = str(doc.get("year") or doc.get("meta", {}).get("year") or "")
    abstract = str(doc.get("abstract") or doc.get("meta", {}).get("abstract") or "")
    keywords = str(doc.get("keywords") or doc.get("meta", {}).get("keywords") or "")
    text = str(doc.get("text") or "")
    preview_text = text[: cfg.max_preview_chars] if cfg.max_preview_chars > 0 else text

    extracted_reference_lines = _extract_reference_lines_from_text(text)
    merged_reference_lines = list(cfg.reference_lines or [])
    for line in extracted_reference_lines:
        if line not in merged_reference_lines:
            merged_reference_lines.append(line)

    bibliography_stats: Dict[str, Any] = {"total": 0, "inserted": 0, "exists": 0, "skipped": 0}
    written_paths: List[Path] = []

    if cfg.insert_placeholders_from_references and cfg.content_db:
        bib_path = Path(cfg.content_db)
        if not bib_path.is_absolute():
            raise ValueError(
                "content_db 必须为绝对路径：请确认主流程已执行统一路径预处理，"
                f"当前值={cfg.content_db!r}"
            )
        bib_path.parent.mkdir(parents=True, exist_ok=True)
        bib_table = _load_or_init_bibliography_table(bib_path)
        bib_table, bibliography_stats = _insert_placeholders_for_references(bib_table, merged_reference_lines)
        persist_reference_main_table(bib_table, bib_path)
        written_paths.append(bib_path)

    safe_uid = cfg.uid if cfg.uid is not None else (cfg.doc_id or "doc")
    markdown_path = output_dir / f"rough_reading_{safe_uid}.md"
    json_path = output_dir / f"rough_reading_result_{safe_uid}.json"

    note_text = _build_rough_note(
        title=title,
        year=year,
        abstract=abstract,
        keywords=keywords,
        reference_lines=merged_reference_lines,
        preview_text=preview_text,
    )
    markdown_path.write_text(
        "\n".join(
            [
                f"# 单篇粗读笔记：{title}",
                "",
                f"- uid/doc_id: {safe_uid}",
                f"- references_detected: {len(merged_reference_lines)}",
                f"- placeholder_inserted: {bibliography_stats.get('inserted', 0)}",
                f"- placeholder_exists: {bibliography_stats.get('exists', 0)}",
                f"- placeholder_skipped: {bibliography_stats.get('skipped', 0)}",
                "",
                "---",
                "",
                note_text,
                "",
            ]
        ),
        encoding="utf-8",
    )

    json_payload: Dict[str, Any] = {
        "status": "ok",
        "uid": safe_uid,
        "title": title,
        "year": year,
        "references_detected": len(merged_reference_lines),
        "bibliography_stats": bibliography_stats,
        "outputs": {
            "rough_note": str(markdown_path),
        },
    }
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    written_paths.insert(0, json_path)
    written_paths.insert(0, markdown_path)
    return written_paths


