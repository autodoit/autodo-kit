"""单篇精读笔记（占位可运行版）。

本脚本用于对单篇文献生成“精读笔记”。

本版实现保持简单：
- 从 structured 结果或统一内容主库读取目标文献全文
- 拼接一个较短的提示词
- 调用阿里百炼（DashScope）生成笔记
- 将结果写入 output_dir 下的 markdown 文件

注意：
- 不在代码中写任何 key；请通过环境变量 `DASHSCOPE_API_KEY` 或本地文件注入。
- 本脚本不做“复杂的容错/重试/降级”。缺依赖就让用户自行安装。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from autodokit.tools.llm_clients import AliyunDashScopeClient, load_aliyun_llm_config
from autodokit.tools import load_json_or_py
from autodokit.tools.bibliodb import init_empty_table, insert_placeholder_from_reference
from autodokit.tools.llm_clients import postprocess_aliyun_multimodal_parse_outputs
from autodokit.tools.contentdb_sqlite import infer_workspace_root_from_content_db, resolve_content_db_config
from autodokit.tools.ocr.classic.pdf_parse_asset_manager import ensure_multimodal_parse_asset
from autodokit.tools.ocr.classic.pdf_structured_data_tools import load_single_document_record
from autodokit.tools.storage_backend import load_reference_main_table, persist_reference_main_table


@dataclass
class SinglePaperConfig:
    """单篇精读配置。

    Attributes:
        output_dir: 输出目录。
        uid: 目标文献主键（与文献数据表中的 uid_literature/uid 一致）。
        doc_id: 可选，目标文献 doc_id（若提供则优先使用）。
        model: 大模型名称。
        system_prompt: 可选系统提示词。
        user_prompt_template: 用户提示词模板正文，或其对应的绝对路径（可用 {title}/{year}/{text} 占位）。
        max_chars: 为避免输入过长，本版按字符截断全文（不是严格 token）。
    """

    output_dir: str
    uid: Optional[str] = None
    doc_id: Optional[str] = None
    model: str = "auto"
    system_prompt: str = "你是一名严谨的学术研究助理。请用中文输出，结构清晰。"
    user_prompt_template: str = ""
    max_chars: int = 12000
    use_llm: bool = False
    content_db: str = ""
    insert_placeholders_from_references: bool = True
    reference_lines: Optional[List[str]] = None
    input_structured_json: str = ""
    input_structured_dir: str = ""
    db_input_key: str = ""


def _load_prompt_template(template_or_path: str) -> str:
    """加载用户提示词模板。

    Args:
        template_or_path: 提示词正文，或提示词文件绝对路径。

    Returns:
        可直接用于 format 的提示词正文。

    Raises:
        ValueError: 当提供了不存在的绝对路径时抛出。
    """

    raw_value = str(template_or_path or "").strip()
    if not raw_value:
        raise ValueError("use_llm=true 时必须提供 user_prompt_template 的绝对路径或提示词正文")

    candidate = Path(raw_value)
    if candidate.is_absolute():
        if not candidate.exists():
            raise ValueError(f"user_prompt_template 指向的文件不存在：{candidate}")
        return candidate.read_text(encoding="utf-8")

    return raw_value


def _read_target_doc_from_inputs(
    *,
    input_structured_json: str,
    input_structured_dir: str,
    content_db: str,
    uid: Optional[str],
    doc_id: Optional[str],
) -> Dict[str, Any]:
    """从结构化输入或统一内容主库读取目标文献。"""

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
    """从文献文本中提取“参考文献行”列表。

    策略说明：
    - 优先识别“References/参考文献”标题后的段落；
    - 若未命中，则返回空列表（避免误抽正文句子）。

    Args:
        text: 文献全文文本。

    Returns:
        参考文献行列表（去重且保持顺序）。
    """

    raw = str(text or "")
    if not raw.strip():
        return []

    lines = [line.strip() for line in raw.splitlines()]
    start_idx = -1
    for idx, line in enumerate(lines):
        lowered = line.lower().strip("# ")
        if lowered in {"references", "reference", "参考文献"}:
            start_idx = idx + 1
            break

    if start_idx < 0:
        return []

    refs: List[str] = []
    seen: set[str] = set()
    for line in lines[start_idx:]:
        if not line:
            continue
        if line.startswith("#"):
            break
        if len(line) < 20:
            continue
        if line not in seen:
            seen.add(line)
            refs.append(line)
    return refs


def _generate_local_reading_note(title: str, year: str, text: str) -> str:
    """在不调用 LLM 的情况下生成精读笔记草稿。

    Args:
        title: 标题。
        year: 年份。
        text: 文本内容。

    Returns:
        Markdown 格式的笔记正文。
    """

    normalized = " ".join(str(text or "").split())
    sample = normalized[:2000]
    sentences = [s.strip() for s in sample.replace("\n", " ").split(".") if s.strip()]
    key_points = sentences[:5]

    bullets = "\n".join([f"- {point}." for point in key_points]) if key_points else "- 未从文本中抽取到可用句子。"

    return "\n".join(
        [
            "## 论文信息",
            f"- 标题：{title}",
            f"- 年份：{year}",
            "",
            "## 核心内容速记（本地规则生成）",
            bullets,
            "",
            "## 阅读建议",
            "- 补充查看方法与数据部分，确认识别策略是否可复用。",
            "- 后续可将关键结论映射到研究问题-方法-证据三元结构。",
        ]
    )


def _load_or_init_bibliography_table(csv_path: Path) -> pd.DataFrame:
    """加载或初始化文献数据库主表。

    Args:
        csv_path: 文献数据库路径，支持 `.db` 或 `.csv`。

    Returns:
        DataFrame 文献表。
    """

    if csv_path.exists():
        return load_reference_main_table(csv_path)
    return init_empty_table()


def _insert_placeholders_for_references(table: pd.DataFrame, reference_lines: List[str]) -> tuple[pd.DataFrame, Dict[str, Any]]:
    """根据参考文献行批量插入占位引文。

    Args:
        table: 当前文献表。
        reference_lines: 参考文献行文本列表。

    Returns:
        (更新后的表, 统计信息字典)。
    """

    working = table.copy()
    inserted = 0
    exists = 0
    skipped = 0
    details: List[Dict[str, Any]] = []

    for line in reference_lines:
        try:
            working, record, action = insert_placeholder_from_reference(working, line)
            if action == "exists":
                exists += 1
            elif action in {"inserted", "updated"}:
                inserted += 1
            details.append({"action": action, "record": record})
        except Exception as exc:
            skipped += 1
            details.append({"action": "skipped", "error": str(exc), "reference_text": line})

    return (
        working,
        {
            "total": len(reference_lines),
            "inserted": inserted,
            "exists": exists,
            "skipped": skipped,
            "details": details,
        },
    )


def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)

    merged: Dict[str, Any] = dict(raw_cfg)
    model_route = merged.get("model_route") if isinstance(merged.get("model_route"), dict) else {}
    content_db_path, db_input_key = resolve_content_db_config(merged)

    cfg = SinglePaperConfig(
        output_dir=str(merged.get("output_dir") or ""),
        uid=(
            str(merged.get("uid_literature")).strip()
            if merged.get("uid_literature") is not None
            else (str(merged.get("uid")).strip() if merged.get("uid") is not None else None)
        ),
        doc_id=str(merged.get("doc_id")) if merged.get("doc_id") else None,
        model=str(merged.get("model") or "auto"),
        system_prompt=str(merged.get("system_prompt") or "").strip() or SinglePaperConfig.system_prompt,
        user_prompt_template=str(merged.get("user_prompt_template") or "").strip(),
        max_chars=int(merged.get("max_chars") or 12000),
        use_llm=bool(merged.get("use_llm", False)),
        content_db=str(content_db_path) if content_db_path is not None else "",
        insert_placeholders_from_references=bool(merged.get("insert_placeholders_from_references", True)),
        reference_lines=list(merged.get("reference_lines") or []),
        input_structured_json=str(merged.get("input_structured_json") or ""),
        input_structured_dir=str(merged.get("input_structured_dir") or ""),
        db_input_key=db_input_key,
    )

    out_dir = Path(cfg.output_dir)
    if not out_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={cfg.output_dir!r}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    if cfg.content_db and not cfg.input_structured_json and not cfg.input_structured_dir:
        workspace_root = infer_workspace_root_from_content_db(Path(cfg.content_db))
        global_config_path = workspace_root / "config" / "config.json"
        parse_asset = ensure_multimodal_parse_asset(
            content_db=cfg.content_db,
            parse_level="non_review_deep",
            uid_literature=str(cfg.uid or ""),
            doc_id=str(cfg.doc_id or ""),
            source_stage="single_deep_read",
            api_key_file=merged.get("api_key_file"),
            global_config_path=global_config_path if global_config_path.exists() else None,
            overwrite_existing=False,
            model=str(merged.get("parse_model") or merged.get("structured_model") or "auto"),
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
    text = str(doc.get("text") or "")
    if cfg.max_chars and len(text) > cfg.max_chars:
        text = text[: cfg.max_chars]

    extracted_reference_lines = _extract_reference_lines_from_text(text)
    merged_reference_lines = list(cfg.reference_lines or [])
    for line in extracted_reference_lines:
        if line not in merged_reference_lines:
            merged_reference_lines.append(line)

    bibliography_stats: Dict[str, Any] = {"total": 0, "inserted": 0, "exists": 0, "skipped": 0, "details": []}
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

    if cfg.use_llm:
        prompt_template = _load_prompt_template(cfg.user_prompt_template)
        prompt = prompt_template.format(title=title, year=year, text=text)
        route_hints: Dict[str, Any] = dict(model_route)
        route_hints.setdefault("input_chars", len(text))
        llm_cfg = load_aliyun_llm_config(
            model=cfg.model,
            affair_name="单篇精读",
            route_hints=route_hints,
        )
        client = AliyunDashScopeClient(llm_cfg)
        answer = client.generate_text(prompt=prompt, system=cfg.system_prompt)
        model_name = llm_cfg.model
        backend_name = llm_cfg.sdk_backend
    else:
        answer = _generate_local_reading_note(title=title, year=year, text=text)
        model_name = "local-rule-based"
        backend_name = "none"

    safe_uid = cfg.uid if cfg.uid is not None else (cfg.doc_id or "doc")
    out_path = out_dir / f"single_reading_{safe_uid}.md"
    out_path.write_text(
        "\n".join(
            [
                f"# 单篇精读笔记：{title}",
                "",
                f"- uid/doc_id: {safe_uid}",
                f"- year: {year}",
                f"- model: {model_name}",
                f"- backend: {backend_name}",
                f"- references_detected: {len(merged_reference_lines)}",
                f"- placeholder_inserted: {bibliography_stats.get('inserted', 0)}",
                f"- placeholder_exists: {bibliography_stats.get('exists', 0)}",
                f"- placeholder_skipped: {bibliography_stats.get('skipped', 0)}",
                "",
                "---",
                "",
                answer,
                "",
            ]
        ),
        encoding="utf-8",
    )
    written_paths.insert(0, out_path)
    return written_paths



