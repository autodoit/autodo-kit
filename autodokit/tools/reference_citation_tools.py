"""参考文献引文处理工具。

本模块把中可复用的引文处理逻辑下沉到 tools：

1. 从 PDF/CAJ 等附件中抽取参考文献原文；
2. 调用阿里百炼大模型解析单条引文；
3. 在本地文献数据库中做匹配；
4. 未命中时插入占位条目并生成 cite_key；
5. 将关键过程写入 AOK 日志，并在终端输出处理摘要。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from autodokit.tools.atomic.log_aok import append_aok_log_event, resolve_aok_log_db_path
from autodokit.tools.llm_clients import AliyunLLMClient, build_aliyun_llm_runtime_payload, load_aliyun_llm_config
from autodokit.tools.llm_parsing import parse_json_object_from_text
from autodokit.tools.old.bibliodb_csv_compat import (
    build_cite_key,
    clean_title_text,
    generate_uid,
    literature_insert_placeholder,
    literature_match,
    literature_upsert,
    normalize_text_for_match,
    parse_reference_text,
)


def _stringify(value: Any) -> str:
    """安全转换文本值。

    Args:
        value: 任意输入值。

    Returns:
        去除首尾空白后的字符串。
    """

    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _resolve_global_config_path(workspace_root: Path, config_path: Path | None = None) -> Path | None:
    """解析全局配置路径。

    Args:
        workspace_root: 工作区根目录。
        config_path: 显式传入的配置路径。

    Returns:
        可用的全局配置路径；若不存在则返回 None。
    """

    if config_path is not None and Path(config_path).exists():
        return Path(config_path)
    candidate = workspace_root / "config" / "config.json"
    return candidate if candidate.exists() else None


def _load_global_llm_settings(workspace_root: Path, config_path: Path | None = None) -> Dict[str, Any]:
    """读取全局 LLM 设置。

    Args:
        workspace_root: 工作区根目录。
        config_path: 可选显式配置路径。

    Returns:
        LLM 设置字典。
    """

    resolved = _resolve_global_config_path(workspace_root, config_path=config_path)
    if resolved is None:
        return {}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    llm_cfg = payload.get("llm")
    return dict(llm_cfg) if isinstance(llm_cfg, dict) else {}


def _resolve_logging_enabled(workspace_root: Path, config_path: Path | None = None) -> bool:
    """读取全局日志开关。"""

    resolved = _resolve_global_config_path(workspace_root, config_path=config_path)
    if resolved is None:
        return True
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except Exception:
        return True
    logging_cfg = payload.get("logging")
    if not isinstance(logging_cfg, dict):
        return True
    return bool(logging_cfg.get("enabled", True))


REFERENCE_MARKER_PATTERN = re.compile(r"\[\s*\d+\s*\]|［\s*\d+\s*］|\(\s*\d+\s*\)|（\s*\d+\s*）|\d{1,3}\s*[.、．]")
REFERENCE_BULLET_PATTERN = re.compile(r"^\s*(?:-|\*|•)\s+")
REFERENCE_TYPE_PATTERN = re.compile(r"\[\s*(?:J|M|D|R|C|P|N|EB|OL)(?:\s*/\s*OL)?\s*\]", re.IGNORECASE)
REFERENCE_YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")
REFERENCE_NOISE_PATTERNS = [
    re.compile(r"\babstract\b", re.IGNORECASE),
    re.compile(r"\bkey\s*words?\b", re.IGNORECASE),
    re.compile(r"责任编辑"),
    re.compile(r"摘\s*要"),
    re.compile(r"关\s*键\s*词"),
    re.compile(r"收稿日期"),
    re.compile(r"基金项目"),
    re.compile(r"作者简介"),
]
REFERENCE_SOURCE_HINT_PATTERN = re.compile(
    r"journal|review|press|university|economics|management|science|research|study|研究|学报|出版社|大学|经济|金融|管理|期刊",
    re.IGNORECASE,
)


def _normalize_reference_text(raw: str) -> str:
    """规范化参考文献候选文本。"""

    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("⁃\n", "").replace("-\n", "")
    normalized_lines: List[str] = []
    for line in text.split("\n"):
        cleaned = " ".join(line.strip().split())
        if not cleaned:
            continue
        if re.fullmatch(r"\d{1,3}", cleaned):
            continue
        normalized_lines.append(cleaned)
    return "\n".join(normalized_lines).strip()


def _truncate_reference_noise_suffix(text: str) -> Tuple[str, bool, List[str]]:
    """截断参考文献尾部的摘要或版心噪声。"""

    normalized = _normalize_reference_text(text)
    if not normalized:
        return "", False, []

    cut_position = len(normalized)
    triggered: List[str] = []
    for pattern in REFERENCE_NOISE_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        if match.start() < cut_position:
            cut_position = match.start()
        triggered.append(pattern.pattern)
    trimmed = normalized[:cut_position].strip()
    return trimmed, cut_position < len(normalized), triggered


def _find_reference_marker_positions(text: str) -> List[re.Match[str]]:
    """定位文本内部的参考文献编号标记。"""

    matches: List[re.Match[str]] = []
    for match in REFERENCE_MARKER_PATTERN.finditer(text):
        start = match.start()
        if start == 0:
            matches.append(match)
            continue
        prefix = text[max(0, start - 6) : start]
        if "\n" in prefix or prefix.rstrip().endswith((".", "。", "．", ";", "；", ":", "：")):
            matches.append(match)
    return matches


def _split_reference_chunk(raw: str) -> Tuple[List[str], int]:
    """把疑似并条的原始块拆成单条引文。"""

    text = _normalize_reference_text(raw)
    if not text:
        return [], 0

    if REFERENCE_MARKER_PATTERN.match(text):
        text = REFERENCE_MARKER_PATTERN.sub("", text, count=1).strip()

    marker_matches = _find_reference_marker_positions(text)
    internal_matches = [match for match in marker_matches if match.start() > 0]
    if not internal_matches:
        return [text], 0

    segments: List[str] = []
    start = 0
    for match in internal_matches:
        segment = text[start:match.start()].strip()
        if segment:
            segments.append(segment)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        segments.append(tail)
    return segments, len(internal_matches)


def _looks_like_reference_entry(text: str) -> bool:
    """判断文本是否仍像一条参考文献。"""

    candidate = _normalize_reference_text(text)
    if len(candidate) < 24:
        return False
    has_year = bool(REFERENCE_YEAR_PATTERN.search(candidate))
    has_source_type = bool(REFERENCE_TYPE_PATTERN.search(candidate))
    has_source_hint = bool(REFERENCE_SOURCE_HINT_PATTERN.search(candidate))
    punctuation_count = sum(candidate.count(mark) for mark in [".", "。", "，", ",", ":", "："])
    return has_year and (has_source_type or has_source_hint or punctuation_count >= 3)


def _looks_like_merged_reference(text: str) -> bool:
    """判断清洗后的文本是否仍疑似包含并条。"""

    candidate = _normalize_reference_text(text)
    if not candidate:
        return False
    internal_marker_count = len([match for match in _find_reference_marker_positions(candidate) if match.start() > 0])
    source_marker_count = len(REFERENCE_TYPE_PATTERN.findall(candidate))
    year_count = len(REFERENCE_YEAR_PATTERN.findall(candidate))
    return internal_marker_count > 0 or source_marker_count >= 2 or year_count >= 3


def _fallback_reference_chunks_from_text(text: str) -> List[str]:
    """当结构化提取失败时，从全文中兜底切出参考文献块。"""

    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
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

    chunks: List[str] = []
    current: List[str] = []
    for raw_line in lines[start_index:]:
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        if any(pattern.search(line) for pattern in REFERENCE_NOISE_PATTERNS) and not current:
            break
        if line.startswith("#"):
            break
        if REFERENCE_BULLET_PATTERN.match(line):
            if current:
                chunks.append("\n".join(current))
            current = [REFERENCE_BULLET_PATTERN.sub("", line, count=1).strip()]
            continue
        if REFERENCE_MARKER_PATTERN.match(line):
            if current:
                chunks.append("\n".join(current))
                current = []
            current.append(line)
            continue
        if not current:
            if len(line) >= 24:
                current.append(line)
            continue
        current.append(line)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _extract_reference_line_details_from_text(text: str) -> List[Dict[str, Any]]:
    """从全文中抽取并清洗单条参考文献，同时返回质量标记。"""

    raw_chunks: List[str] = []
    try:
        from autodokit.tools.ocr.classic.pdf_elements_extractors import extract_references_from_full_text

        structured_refs, _status = extract_references_from_full_text(text)
        raw_chunks = [
            _stringify(item.get("raw_text") or item.get("raw") or item.get("text"))
            for item in structured_refs
            if _stringify(item.get("raw_text") or item.get("raw") or item.get("text"))
        ]
    except Exception:
        raw_chunks = []

    if not raw_chunks:
        raw_chunks = _fallback_reference_chunks_from_text(text)

    details: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw_chunk in raw_chunks:
        split_segments, internal_marker_count = _split_reference_chunk(raw_chunk)
        for segment in split_segments:
            cleaned, noise_trimmed, noise_markers = _truncate_reference_noise_suffix(segment)
            cleaned = _normalize_reference_text(cleaned)
            if not cleaned:
                continue
            if not _looks_like_reference_entry(cleaned):
                continue
            dedupe_key = normalize_text_for_match(cleaned)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            details.append(
                {
                    "reference_text": cleaned,
                    "suspicious_merged": 1 if _looks_like_merged_reference(cleaned) else 0,
                    "noise_trimmed": 1 if noise_trimmed else 0,
                    "noise_markers": noise_markers,
                    "internal_marker_count": int(internal_marker_count),
                }
            )
    return details


def _extract_reference_lines_from_text(text: str) -> List[str]:
    """从全文文本提取参考文献行。

    Args:
        text: 全文文本。

    Returns:
        参考文献原文列表。
    """

    return [item["reference_text"] for item in _extract_reference_line_details_from_text(text)]


def _read_pdf_text(pdf_path: Path) -> Tuple[str, str]:
    """读取 PDF 文本。

    Args:
        pdf_path: PDF 路径。

    Returns:
        二元组 `(全文文本, 解析方式)`。
    """

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(pdf_path))
        parts: List[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
        if text:
            return text, "pypdf"
    except Exception:
        pass

    try:
        from pdfminer.high_level import extract_text  # type: ignore

        text = extract_text(str(pdf_path)) or ""
        if text.strip():
            return text, "pdfminer"
    except Exception:
        pass

    try:
        from autodokit.tools.ocr.classic.pdf_elements_extractors import extract_text_with_rapidocr

        text, status, _meta = extract_text_with_rapidocr(pdf_path)
        if text.strip():
            return text, "rapidocr"
        _ = status
    except Exception:
        pass

    return "", "none"


def _resolve_attachment_path(attachment_path_raw: str | Path, workspace_root: Path) -> Path | None:
    """解析原文附件路径。

    Args:
        attachment_path_raw: 原始附件路径。
        workspace_root: 工作区根目录。

    Returns:
        可访问的附件路径；若不存在则返回 None。
    """

    raw = _stringify(attachment_path_raw)
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
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def extract_reference_lines_from_attachment(
    attachment_path_raw: str | Path,
    *,
    workspace_root: str | Path,
    print_to_stdout: bool = False,
) -> Dict[str, Any]:
    """从附件提取参考文献原文列表。

    Args:
        attachment_path_raw: 原始附件路径。
        workspace_root: 工作区根目录。
        print_to_stdout: 是否打印终端摘要。

    Returns:
        抽取结果字典。
    """

    resolved_workspace_root = Path(workspace_root)
    attachment_path = _resolve_attachment_path(attachment_path_raw, resolved_workspace_root)
    result: Dict[str, Any] = {
        "attachment_path": str(attachment_path or ""),
        "attachment_type": "",
        "extract_status": "missing_attachment",
        "extract_method": "none",
        "reference_lines": [],
        "full_text": "",
        "pending_reason": "",
    }

    if attachment_path is None:
        if print_to_stdout:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    suffix = attachment_path.suffix.lower()
    result["attachment_type"] = suffix.lstrip(".")
    if suffix == ".caj":
        result["extract_status"] = "pending_caj_pipeline"
        result["pending_reason"] = "当前未实现 CAJ 引文抽取工具链。"
        if print_to_stdout:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    if suffix != ".pdf":
        result["extract_status"] = "unsupported_attachment_type"
        result["pending_reason"] = f"当前仅支持 PDF，收到类型: {suffix}"
        if print_to_stdout:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    full_text, extract_method = _read_pdf_text(attachment_path)
    result["full_text"] = full_text
    result["extract_method"] = extract_method
    reference_line_details = _extract_reference_line_details_from_text(full_text)
    result["reference_line_details"] = reference_line_details
    result["reference_lines"] = [item["reference_text"] for item in reference_line_details]
    result["extract_status"] = "ok" if result["reference_lines"] else "no_reference_lines"
    if print_to_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _build_placeholder_title(reference_text: str) -> str:
    """为解析失败的引文构造占位标题。

    Args:
        reference_text: 参考文献原文。

    Returns:
        占位标题。
    """

    digest = hashlib.sha1(reference_text.encode("utf-8")).hexdigest()[:12]
    return f"unparsed_reference_{digest}"


def repair_reference_text_with_llm(
    reference_text: str,
    *,
    workspace_root: str | Path,
    global_config_path: str | Path | None = None,
    api_key_file: str | Path | None = None,
    model: str | None = None,
    print_to_stdout: bool = False,
) -> Dict[str, Any]:
    """使用轻量文本模型修复单条引文断裂文本。"""

    raw_text = _stringify(reference_text)
    workspace_root_path = Path(workspace_root)
    llm_settings = _load_global_llm_settings(
        workspace_root_path,
        config_path=Path(global_config_path) if global_config_path else None,
    )
    resolved_api_key_file = _stringify(api_key_file) or _stringify(llm_settings.get("aliyun_api_key_file"))
    resolved_model = _stringify(model) or _stringify(llm_settings.get("reference_repair_model")) or "auto"
    log_db_path = resolve_aok_log_db_path(
        workspace_root_path,
        config_path=Path(global_config_path) if global_config_path else None,
    )

    result: Dict[str, Any] = {
        "input_text": raw_text,
        "repaired_text": raw_text,
        "repair_applied": 0,
        "repair_failed": 0,
        "repair_failure_reason": "",
        "model_name": "",
        "llm_backend": "",
        "routing_info": {},
    }
    if not raw_text:
        return result

    try:
        llm_config = load_aliyun_llm_config(
            model=resolved_model,
            api_key_file=resolved_api_key_file or None,
            affair_name="reference_text_repair",
            config_path=Path(global_config_path) if global_config_path else None,
            route_hints={
                "task_type": "general",
                "budget_tier": "cheap",
                "input_chars": len(raw_text),
            },
        )
        client = AliyunLLMClient(llm_config)
        runtime_payload = build_aliyun_llm_runtime_payload(llm_config)
        prompt = "\n".join(
            [
                "请修复下面单条参考文献原文中的 OCR 断词、断行、乱码片段。",
                "要求：",
                "1. 只做最小必要修复，不要编造作者、年份、题名。",
                "2. 保持单条引文，不要拆分成多条。",
                "3. 只返回 JSON：{\"reference_text\": \"...\"}。",
                "原文：",
                raw_text,
            ]
        )
        raw_output = client.generate_text(
            prompt=prompt,
            system="你是参考文献文本修复助手，只输出 JSON。",
            temperature=0.0,
            max_tokens=512,
        )
        parsed_obj, _debug = parse_json_object_from_text(raw_output)
        repaired_text = _stringify(parsed_obj.get("reference_text"))
        if repaired_text:
            result["repaired_text"] = repaired_text
            result["repair_applied"] = 1 if repaired_text != raw_text else 0
            result["model_name"] = client.model
        else:
            result["repair_failed"] = 1
            result["repair_failure_reason"] = "LLM 未返回有效 reference_text，保留原文。"
            result["model_name"] = client.model
        result["llm_backend"] = _stringify(runtime_payload.get("llm_backend"))
        result["routing_info"] = dict(runtime_payload.get("routing_info") or {})
    except Exception as exc:
        result["repair_failed"] = 1
        result["repair_failure_reason"] = str(exc)
        result["model_name"] = resolved_model

    payload = {
        "repair_applied": int(result.get("repair_applied") or 0),
        "repair_failed": int(result.get("repair_failed") or 0),
        "repair_failure_reason": _stringify(result.get("repair_failure_reason")),
        "input_chars": len(raw_text),
        "output_chars": len(_stringify(result.get("repaired_text"))),
        "llm_backend": _stringify(result.get("llm_backend")),
        "routing_info": result.get("routing_info") or {},
    }
    append_aok_log_event(
        event_type="REFERENCE_TEXT_REPAIR",
        project_root=workspace_root_path,
        log_db_path=log_db_path,
        enabled=_resolve_logging_enabled(
            workspace_root_path,
            config_path=Path(global_config_path) if global_config_path else None,
        ),
        handler_kind="llm_native",
        handler_name="repair_reference_text_with_llm",
        model_name=_stringify(result.get("model_name")),
        skill_names=["ar_A050_统一文献预处理解析_v1"],
        reasoning_summary="在单条参考文献解析前执行轻量文本修复。",
        payload=payload,
    )
    if print_to_stdout:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return result


def parse_reference_text_with_llm(
    reference_text: str,
    *,
    workspace_root: str | Path,
    global_config_path: str | Path | None = None,
    api_key_file: str | Path | None = None,
    model: str | None = None,
    print_to_stdout: bool = True,
) -> Dict[str, Any]:
    """使用 LLM 解析参考文献原文。

    Args:
        reference_text: 单条参考文献原文。
        workspace_root: 工作区根目录。
        global_config_path: 可选全局配置路径。
        api_key_file: 可选 API key 文件路径。
        model: 可选模型名。
        print_to_stdout: 是否打印终端摘要。

    Returns:
        解析结果字典。
    """

    workspace_root_path = Path(workspace_root)
    llm_settings = _load_global_llm_settings(workspace_root_path, config_path=Path(global_config_path) if global_config_path else None)
    resolved_api_key_file = _stringify(api_key_file) or _stringify(llm_settings.get("aliyun_api_key_file"))
    resolved_model = _stringify(model) or _stringify(llm_settings.get("reference_parse_model")) or "auto"
    log_db_path = resolve_aok_log_db_path(
        workspace_root_path,
        config_path=Path(global_config_path) if global_config_path else None,
    )

    result: Dict[str, Any] = {
        "reference_text": _stringify(reference_text),
        "llm_invoked": 1,
        "parse_method": "aliyun_llm",
        "parse_failed": 0,
        "parse_failure_reason": "",
        "is_reasonable": False,
        "recognized_fields": {},
        "recognized_text": "",
        "model_name": "",
        "llm_backend": "",
        "routing_info": {},
    }

    llm_error = ""
    try:
        llm_config = load_aliyun_llm_config(
            model=resolved_model,
            api_key_file=resolved_api_key_file or None,
            affair_name="reference_citation_parse",
            route_hints={"budget_tier": "cheap", "input_chars": len(reference_text)},
        )
        client = AliyunLLMClient(llm_config)
        runtime_payload = build_aliyun_llm_runtime_payload(llm_config)
        prompt = "\n".join(
            [
                "请解析下面这一条参考文献原文，只返回 JSON 对象。",
                "字段必须包含：first_author, year, title_raw, confidence, failure_reason。",
                "若字段无法判断，填空字符串，不要编造额外解释。",
                "参考文献原文：",
                reference_text,
            ]
        )
        raw_output = client.generate_text(
            prompt=prompt,
            system="你是文献引文解析助手，只输出 JSON。",
            temperature=0.1,
            max_tokens=256,
        )
        parsed_obj, _debug = parse_json_object_from_text(raw_output)
        first_author = _stringify(parsed_obj.get("first_author"))
        year = _stringify(parsed_obj.get("year"))
        title_raw = _stringify(parsed_obj.get("title_raw") or parsed_obj.get("title"))
        failure_reason = _stringify(parsed_obj.get("failure_reason"))
        result["recognized_fields"] = {
            "first_author": first_author,
            "year": year,
            "title_raw": title_raw,
            "confidence": _stringify(parsed_obj.get("confidence")),
        }
        result["recognized_text"] = title_raw
        result["is_reasonable"] = bool(title_raw or (first_author and year))
        result["parse_failed"] = 0 if result["is_reasonable"] else 1
        result["parse_failure_reason"] = failure_reason
        result["model_name"] = client.model
        result["llm_backend"] = _stringify(runtime_payload.get("llm_backend"))
        result["routing_info"] = dict(runtime_payload.get("routing_info") or {})
    except Exception as exc:
        llm_error = str(exc)
        fallback = parse_reference_text(reference_text)
        first_author = _stringify(fallback.first_author)
        year = "" if fallback.year_int is None else str(fallback.year_int)
        title_raw = _stringify(fallback.title)
        result["parse_method"] = "affair_fallback_parser"
        result["recognized_fields"] = {
            "first_author": first_author,
            "year": year,
            "title_raw": title_raw,
            "confidence": "",
        }
        result["recognized_text"] = title_raw
        result["is_reasonable"] = bool(title_raw or (first_author and year))
        result["parse_failed"] = 0 if result["is_reasonable"] else 1
        result["parse_failure_reason"] = llm_error or "LLM 解析失败，已退回事务内解析器。"
        result["model_name"] = resolved_model

    payload = {
        "reference_text": result["reference_text"],
        "is_reasonable": result["is_reasonable"],
        "recognized_fields": result["recognized_fields"],
        "parse_method": result["parse_method"],
        "parse_failed": result["parse_failed"],
        "parse_failure_reason": result["parse_failure_reason"],
        "llm_backend": _stringify(result.get("llm_backend")),
        "routing_info": result.get("routing_info") or {},
    }
    append_aok_log_event(
        event_type="REFERENCE_LLM_PARSE",
        project_root=workspace_root_path,
        log_db_path=log_db_path,
        enabled=_resolve_logging_enabled(
            workspace_root_path,
            config_path=Path(global_config_path) if global_config_path else None,
        ),
        handler_kind="llm_native" if result["parse_method"] == "aliyun_llm" else "local_script",
        handler_name="parse_reference_text_with_llm",
        model_name=_stringify(result["model_name"]),
        skill_names=["ar_插入引文_v1"],
        reasoning_summary="对单条参考文献原文执行 LLM 解析并记录解析方式。",
        payload=payload,
    )
    if print_to_stdout:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return result


def refine_reference_lines_with_llm(
    reference_lines: List[str],
    *,
    workspace_root: str | Path,
    global_config_path: str | Path | None = None,
    api_key_file: str | Path | None = None,
    model: str | None = None,
    cite_key: str = "",
    title: str = "",
    max_items: int = 120,
    print_to_stdout: bool = False,
) -> Dict[str, Any]:
    """使用单次独立 LLM 请求清洗单篇文献的参考文献列表。

    Args:
        reference_lines: 同一篇文献提取出的参考文献原文列表。
        workspace_root: 工作区根目录。
        global_config_path: 可选全局配置路径。
        api_key_file: 可选 API key 文件路径。
        model: 可选模型名。
        cite_key: 来源文献 cite_key。
        title: 来源文献标题。
        max_items: 参与 LLM 处理的最大条目数。
        print_to_stdout: 是否打印摘要。

    Returns:
        包含 `reference_lines` 与处理元信息的结果字典。
    """

    cleaned_input = [_stringify(item) for item in reference_lines if _stringify(item)]
    cleaned_input = cleaned_input[: max(int(max_items or 0), 1)]
    workspace_root_path = Path(workspace_root)
    llm_settings = _load_global_llm_settings(
        workspace_root_path,
        config_path=Path(global_config_path) if global_config_path else None,
    )
    resolved_api_key_file = _stringify(api_key_file) or _stringify(llm_settings.get("aliyun_api_key_file"))
    resolved_model = (
        _stringify(model)
        or _stringify(llm_settings.get("reference_block_model"))
        or _stringify(llm_settings.get("review_state_model"))
        or "auto"
    )
    log_db_path = resolve_aok_log_db_path(
        workspace_root_path,
        config_path=Path(global_config_path) if global_config_path else None,
    )

    result: Dict[str, Any] = {
        "cite_key": _stringify(cite_key),
        "title": _stringify(title),
        "reference_lines": cleaned_input,
        "llm_invoked": 0,
        "parse_method": "original_extraction",
        "parse_failed": 0,
        "parse_failure_reason": "",
        "model_name": "",
        "llm_backend": "",
        "routing_info": {},
    }
    if not cleaned_input:
        return result

    try:
        llm_config = load_aliyun_llm_config(
            model=resolved_model,
            api_key_file=resolved_api_key_file or None,
            affair_name="reference_block_cleanup",
            config_path=Path(global_config_path) if global_config_path else None,
            route_hints={
                "task_type": "general",
                "budget_tier": "balanced",
                "input_chars": sum(len(item) for item in cleaned_input),
            },
        )
        client = AliyunLLMClient(llm_config)
        runtime_payload = build_aliyun_llm_runtime_payload(llm_config)
        prompt = "\n".join(
            [
                "请把下面同一篇论文提取出的参考文献原文列表整理为标准化的单条列表。",
                "要求：",
                "1. 每个元素对应一条参考文献；不要合并两条不同文献。",
                "2. 删除明显噪声行、页码碎片、标题残片、重复项。",
                "3. 尽量保留原始引文内容，不要编造缺失信息。",
                "4. 只返回 JSON 对象，格式为 {\"reference_lines\": [\"...\"]}。",
                f"来源文献 cite_key: {_stringify(cite_key) or 'unknown'}",
                f"来源文献标题: {_stringify(title) or 'unknown'}",
                "原始参考文献列表：",
                json.dumps(cleaned_input, ensure_ascii=False, indent=2),
            ]
        )
        raw_output = client.generate_text(
            prompt=prompt,
            system="你是参考文献列表清洗助手，只输出 JSON。",
            temperature=0.1,
            max_tokens=2048,
        )
        parsed_obj, _debug = parse_json_object_from_text(raw_output)
        parsed_lines = parsed_obj.get("reference_lines")
        normalized_lines = [
            _stringify(item)
            for item in (parsed_lines if isinstance(parsed_lines, list) else [])
            if _stringify(item)
        ]
        if normalized_lines:
            result["reference_lines"] = normalized_lines
            result["parse_method"] = "aliyun_llm_reference_block"
            result["llm_invoked"] = 1
            result["model_name"] = client.model
        else:
            result["parse_method"] = "original_extraction"
            result["llm_invoked"] = 1
            result["parse_failed"] = 1
            result["parse_failure_reason"] = "LLM 未返回有效 reference_lines，保留原始抽取结果。"
            result["model_name"] = client.model
        result["llm_backend"] = _stringify(runtime_payload.get("llm_backend"))
        result["routing_info"] = dict(runtime_payload.get("routing_info") or {})
    except Exception as exc:
        result["llm_invoked"] = 1
        result["parse_failed"] = 1
        result["parse_failure_reason"] = str(exc)
        result["model_name"] = resolved_model

    payload = {
        "cite_key": result["cite_key"],
        "title": result["title"],
        "input_count": len(cleaned_input),
        "output_count": len(result["reference_lines"]),
        "parse_method": result["parse_method"],
        "parse_failed": result["parse_failed"],
        "parse_failure_reason": result["parse_failure_reason"],
        "llm_backend": _stringify(result.get("llm_backend")),
        "routing_info": result.get("routing_info") or {},
    }
    append_aok_log_event(
        event_type="REFERENCE_BLOCK_CLEANUP",
        project_root=workspace_root_path,
        log_db_path=log_db_path,
        enabled=_resolve_logging_enabled(
            workspace_root_path,
            config_path=Path(global_config_path) if global_config_path else None,
        ),
        handler_kind="llm_native" if result["parse_method"] == "aliyun_llm_reference_block" else "local_script",
        handler_name="refine_reference_lines_with_llm",
        model_name=_stringify(result["model_name"]),
        skill_names=["ar_A060_综述候选文献视图构建_v7"],
        reasoning_summary="对单篇文献的参考文献块执行一次独立 LLM 清洗请求。",
        payload=payload,
    )
    if print_to_stdout:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return result


def _ensure_cite_key(
    table: pd.DataFrame,
    record: Dict[str, Any],
    *,
    first_author: str,
    year: str,
    title_raw: str,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """确保记录具备 cite_key。

    Args:
        table: 文献主表。
        record: 目标记录。
        first_author: 第一作者。
        year: 年份。
        title_raw: 原始标题。

    Returns:
        `(更新后的表, 更新后的记录, cite_key)`。
    """

    cite_key = _stringify(record.get("cite_key"))
    if cite_key:
        return table, record, cite_key

    clean_title = _stringify(record.get("clean_title")) or clean_title_text(_stringify(record.get("title")) or title_raw)
    cite_key = build_cite_key(first_author, year, clean_title)
    payload = dict(record)
    payload["cite_key"] = cite_key
    updated_table, updated_record, _action = literature_upsert(table=table, literature=payload, overwrite=False)
    return updated_table, updated_record, cite_key


def generate_reference_cite_key(
    *,
    first_author: str,
    year: str,
    title_raw: str,
    clean_title: str = "",
) -> str:
    """生成参考文献的 cite_key。

    Args:
        first_author: 第一作者。
        year: 年份字符串。
        title_raw: 原始标题。
        clean_title: 可选的清洗后标题；为空时自动清洗。

    Returns:
        生成后的 cite_key。
    """

    normalized_clean_title = _stringify(clean_title) or clean_title_text(_stringify(title_raw))
    return build_cite_key(_stringify(first_author), _stringify(year), normalized_clean_title)


def match_reference_citation_record(
    table: pd.DataFrame,
    *,
    first_author: str,
    year: str,
    title_raw: str,
    top_n: int = 5,
) -> Dict[str, Any]:
    """原子能力：按作者-年份-标题匹配参考文献记录。

    Args:
        table: 文献主表。
        first_author: 第一作者。
        year: 年份字符串。
        title_raw: 原始标题。
        top_n: 匹配候选上限。

    Returns:
        匹配结果字典。
    """

    working = table.copy()
    matches = literature_match(
        working,
        first_author=_stringify(first_author),
        year=int(year) if _stringify(year).isdigit() else None,
        title=_stringify(title_raw),
        top_n=max(int(top_n or 0), 1),
    )
    if not matches:
        return {
            "matched": False,
            "record": {},
            "match_score": 0.0,
            "suspicious_mismatch": 0,
        }

    top_match = matches[0]
    record = dict(top_match.get("row") or {})
    match_score = float(top_match.get("score") or 0.0)
    suspicious_mismatch = 1 if _is_suspicious_match(
        reference_title=_stringify(title_raw),
        reference_first_author=_stringify(first_author),
        reference_year=_stringify(year),
        matched_record=record,
        match_score=match_score,
    ) else 0
    return {
        "matched": True,
        "record": record,
        "match_score": match_score,
        "suspicious_mismatch": int(suspicious_mismatch),
    }


def upsert_reference_citation_placeholder(
    table: pd.DataFrame,
    *,
    first_author: str,
    year: str,
    title_raw: str,
    source: str,
    placeholder_reason: str,
    placeholder_status: str = "pending",
    placeholder_run_uid: str = "",
    extra: Dict[str, Any] | None = None,
    top_n: int = 5,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """原子能力：插入或复用参考文献占位记录。"""

    return _upsert_reference_placeholder(
        table,
        first_author=_stringify(first_author),
        year=_stringify(year),
        title_raw=_stringify(title_raw),
        source=_stringify(source),
        placeholder_reason=_stringify(placeholder_reason),
        placeholder_status=_stringify(placeholder_status) or "pending",
        placeholder_run_uid=_stringify(placeholder_run_uid),
        extra=extra,
        top_n=max(int(top_n or 0), 0),
    )


def writeback_reference_citation_record(
    table: pd.DataFrame,
    *,
    record: Dict[str, Any],
    overwrite: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """原子能力：把引文记录写回文献主表。"""

    return literature_upsert(table=table, literature=dict(record or {}), overwrite=bool(overwrite))


def ensure_reference_citation_cite_key(
    table: pd.DataFrame,
    *,
    record: Dict[str, Any],
    first_author: str,
    year: str,
    title_raw: str,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """原子能力：确保引文记录存在 cite_key（必要时写回）。"""

    cite_key = _stringify((record or {}).get("cite_key"))
    if cite_key:
        return table, dict(record or {}), cite_key

    payload = dict(record or {})
    payload["cite_key"] = generate_reference_cite_key(
        first_author=_stringify(payload.get("first_author") or first_author),
        year=_stringify(payload.get("year") or year),
        title_raw=_stringify(payload.get("title") or title_raw),
        clean_title=_stringify(payload.get("clean_title")),
    )
    updated_table, updated_record, _action = writeback_reference_citation_record(
        table,
        record=payload,
        overwrite=False,
    )
    return updated_table, updated_record, _stringify(payload.get("cite_key"))


def build_online_lookup_placeholder_fields() -> Dict[str, str]:
    """构造在线检索补全占位字段。

    Returns:
        在线补全占位字段字典。
    """

    return {
        "online_lookup_status": "pending",
        "online_lookup_source": "",
        "online_lookup_note": "当前阶段未实现在线补全文献条目，仅保留占位状态。",
    }


def _tokenize_match_text(text: str) -> set[str]:
    """把标题等文本切成可比较 token 集合。"""

    normalized = normalize_text_for_match(text)
    return {token for token in re.split(r"[^0-9a-z\u4e00-\u9fff]+", normalized) if len(token) >= 2}


def _estimate_title_overlap(reference_title: str, matched_title: str) -> float:
    """估计识别标题与命中文献标题的 token 重合度。"""

    left = _tokenize_match_text(reference_title)
    right = _tokenize_match_text(matched_title)
    if not left or not right:
        return 0.0
    return round(len(left & right) / max(len(left), len(right), 1), 4)


def _is_suspicious_match(
    *,
    reference_title: str,
    reference_first_author: str,
    reference_year: str,
    matched_record: Dict[str, Any],
    match_score: float,
) -> bool:
    """基于弱匹配分数与标题重合度判断是否疑似误匹配。"""

    matched_title = _stringify(matched_record.get("title"))
    matched_author = normalize_text_for_match(_stringify(matched_record.get("first_author")))
    matched_year = _stringify(matched_record.get("year"))
    overlap = _estimate_title_overlap(reference_title, matched_title)
    same_author = bool(reference_first_author) and normalize_text_for_match(reference_first_author) == matched_author
    same_year = bool(reference_year) and reference_year == matched_year
    if match_score < 0.65 and overlap < 0.5:
        return True
    if overlap < 0.35 and not same_author and not same_year:
        return True
    return False


def build_reference_quality_summary(mapping_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """根据映射结果生成参考文献处理质量摘要。"""

    action_counts: Dict[str, int] = {}
    parse_method_counts: Dict[str, int] = {}
    placeholder_reason_counts: Dict[str, int] = {}
    placeholder_status_counts: Dict[str, int] = {}
    for row in mapping_rows:
        action = _stringify(row.get("action")) or "unknown"
        parse_method = _stringify(row.get("parse_method")) or "unknown"
        placeholder_reason = _stringify(row.get("placeholder_reason")) or "none"
        placeholder_status = _stringify(row.get("placeholder_status")) or "none"
        action_counts[action] = action_counts.get(action, 0) + 1
        parse_method_counts[parse_method] = parse_method_counts.get(parse_method, 0) + 1
        placeholder_reason_counts[placeholder_reason] = placeholder_reason_counts.get(placeholder_reason, 0) + 1
        placeholder_status_counts[placeholder_status] = placeholder_status_counts.get(placeholder_status, 0) + 1

    total_reference_count = len(mapping_rows)
    llm_recognized_count = sum(1 for row in mapping_rows if _stringify(row.get("parse_method")) == "aliyun_llm")
    placeholder_count = sum(1 for row in mapping_rows if _stringify(row.get("action")) == "inserted")
    suspicious_merged_count = sum(int(row.get("suspicious_merged") or 0) for row in mapping_rows)
    suspicious_mismatch_count = sum(int(row.get("suspicious_mismatch") or 0) for row in mapping_rows)
    noise_trimmed_count = sum(int(row.get("noise_trimmed") or 0) for row in mapping_rows)
    parse_failed_count = sum(int(row.get("parse_failed") or 0) for row in mapping_rows)
    mapped_placeholder_count = sum(int(row.get("is_placeholder") or 0) for row in mapping_rows)

    return {
        "total_reference_count": total_reference_count,
        "llm_recognized_count": llm_recognized_count,
        "placeholder_count": placeholder_count,
        "suspicious_merged_count": suspicious_merged_count,
        "suspicious_mismatch_count": suspicious_mismatch_count,
        "noise_trimmed_count": noise_trimmed_count,
        "parse_failed_count": parse_failed_count,
        "mapped_placeholder_count": mapped_placeholder_count,
        "action_counts": action_counts,
        "parse_method_counts": parse_method_counts,
        "placeholder_reason_counts": placeholder_reason_counts,
        "placeholder_status_counts": placeholder_status_counts,
    }


def _fallback_insert_reference_placeholder(
    table: pd.DataFrame,
    reference_text: str,
    *,
    source: str,
    parse_method: str,
    parse_failure_reason: str,
    placeholder_run_uid: str = "",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """当标准解析链路失败时，仍强制插入占位条目并返回 cite_key。"""

    fallback = parse_reference_text(reference_text)
    first_author = _stringify(fallback.first_author)
    year = "" if fallback.year_int is None else str(fallback.year_int)
    title_raw = _stringify(fallback.title) or _build_placeholder_title(reference_text)
    clean_title = clean_title_text(title_raw)
    title_norm = normalize_text_for_match(title_raw)

    extra = {
        "reference_text": _stringify(reference_text),
        "title_norm": title_norm,
        "clean_title": clean_title,
        "llm_invoked": 1,
        "parse_method": parse_method,
        "parse_failed": 1,
        "parse_failure_reason": _stringify(parse_failure_reason) or "process_reference_citation_unexpected_error",
        "placeholder_reason": "parse_failed",
        "placeholder_status": "pending",
        "placeholder_run_uid": _stringify(placeholder_run_uid),
        **build_online_lookup_placeholder_fields(),
    }
    working, record, action = _upsert_reference_placeholder(
        table,
        first_author=first_author,
        year=year,
        title_raw=title_raw,
        source=source,
        placeholder_reason="parse_failed",
        placeholder_status="pending",
        placeholder_run_uid=placeholder_run_uid,
        extra=extra,
        top_n=5,
    )
    matched_uid_literature = _stringify(record.get("uid_literature"))
    working, record, matched_cite_key = _ensure_cite_key(
        working,
        record,
        first_author=first_author,
        year=year,
        title_raw=title_raw,
    )
    return working, {
        "reference_text": _stringify(reference_text),
        "matched_uid_literature": matched_uid_literature,
        "matched_cite_key": matched_cite_key,
        "action": action,
        "parse_method": parse_method,
        "llm_invoked": 1,
        "parse_failed": 1,
        "parse_failure_reason": _stringify(parse_failure_reason) or "process_reference_citation_unexpected_error",
        "is_reasonable": bool(title_raw or (first_author and year)),
        "recognized_fields": {
            "first_author": first_author,
            "year": year,
            "title_raw": title_raw,
            "confidence": "",
        },
        "match_score": 0.0,
        "matched_title": _stringify(record.get("title")),
        "suspicious_mismatch": 0,
        "placeholder_reason": _stringify(record.get("placeholder_reason")) or "parse_failed",
        "placeholder_status": _stringify(record.get("placeholder_status")) or "pending",
        "placeholder_run_uid": _stringify(record.get("placeholder_run_uid")) or _stringify(placeholder_run_uid),
        "is_placeholder": int(record.get("is_placeholder") or 0),
    }


def _upsert_reference_placeholder(
    table: pd.DataFrame,
    *,
    first_author: str,
    year: str,
    title_raw: str,
    source: str,
    placeholder_reason: str,
    placeholder_status: str = "pending",
    placeholder_run_uid: str = "",
    extra: Dict[str, Any] | None = None,
    top_n: int = 5,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """稳定插入或复用参考文献占位条目。"""

    title_text = _stringify(title_raw)
    if not title_text:
        raise ValueError("_upsert_reference_placeholder 需要 title_raw")

    working = table.copy()
    matches = []
    if int(top_n or 0) > 0:
        matches = literature_match(
            working,
            first_author=first_author,
            year=int(year) if year.isdigit() else None,
            title=title_text,
            top_n=top_n,
        )
    if matches:
        return working, dict(matches[0].get("row") or {}), "exists"

    clean_title = clean_title_text(title_text)
    title_norm = normalize_text_for_match(title_text)
    uid_literature = generate_uid(first_author or None, int(year) if year.isdigit() else None, title_norm)
    payload: Dict[str, Any] = {
        "uid_literature": uid_literature,
        "title": title_text,
        "title_norm": title_norm,
        "first_author": first_author,
        "year": year,
        "entry_type": "placeholder",
        "is_placeholder": 1,
        "placeholder_reason": _stringify(placeholder_reason),
        "placeholder_status": _stringify(placeholder_status) or "pending",
        "placeholder_run_uid": _stringify(placeholder_run_uid),
        "has_fulltext": 0,
        "primary_attachment_name": "",
        "source": source,
        "clean_title": clean_title,
    }
    if extra:
        payload.update(extra)
    updated_table, updated_record, action = literature_upsert(table=working, literature=payload, overwrite=False)
    return updated_table, updated_record, action


def process_reference_citation(
    table: pd.DataFrame,
    reference_text: str,
    *,
    workspace_root: str | Path,
    global_config_path: str | Path | None = None,
    api_key_file: str | Path | None = None,
    model: str | None = None,
    source: str = "placeholder_from_a050_review_scan",
    top_n: int = 5,
    placeholder_run_uid: str = "",
    enable_reference_line_repair: bool = True,
    repair_model: str | None = None,
    print_to_stdout: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """处理单条参考文献引文。

    Args:
        table: 文献主表。
        reference_text: 单条引文原文。
        workspace_root: 工作区根目录。
        global_config_path: 可选全局配置路径。
        api_key_file: 可选 API key 文件。
        model: 可选模型名。
        source: 占位条目来源标记。
        top_n: 本地匹配候选上限。
        print_to_stdout: 是否打印终端摘要。

    Returns:
        `(更新后的文献表, 处理结果字典)`。
    """

    workspace_root_path = Path(workspace_root)
    model_name = ""
    try:
        reference_text_for_parse = _stringify(reference_text)
        repair_result: Dict[str, Any] = {
            "repair_applied": 0,
            "repair_failed": 0,
            "repair_failure_reason": "",
        }
        if enable_reference_line_repair:
            repair_result = repair_reference_text_with_llm(
                reference_text_for_parse,
                workspace_root=workspace_root_path,
                global_config_path=global_config_path,
                api_key_file=api_key_file,
                model=repair_model,
                print_to_stdout=False,
            )
            reference_text_for_parse = _stringify(repair_result.get("repaired_text")) or reference_text_for_parse

        parse_result = parse_reference_text_with_llm(
            reference_text_for_parse,
            workspace_root=workspace_root_path,
            global_config_path=global_config_path,
            api_key_file=api_key_file,
            model=model,
            print_to_stdout=print_to_stdout,
        )
        model_name = _stringify(parse_result.get("model_name"))
        recognized = dict(parse_result.get("recognized_fields") or {})
        first_author = _stringify(recognized.get("first_author"))
        year = _stringify(recognized.get("year"))
        title_raw = _stringify(recognized.get("title_raw"))
        if not title_raw:
            title_raw = _build_placeholder_title(reference_text)
        clean_title = clean_title_text(title_raw)
        title_norm = normalize_text_for_match(title_raw)

        working = table.copy()
        match_result = match_reference_citation_record(
            working,
            first_author=first_author,
            year=year,
            title_raw=title_raw,
            top_n=top_n,
        )

        action = "exists"
        matched_uid_literature = ""
        matched_cite_key = ""
        record: Dict[str, Any] = {}
        top_match_score = 0.0
        matched_title = ""
        suspicious_mismatch = 0
        if bool(match_result.get("matched")):
            top_match_score = float(match_result.get("match_score") or 0.0)
            matched_record = dict(match_result.get("record") or {})
            suspicious_mismatch = int(match_result.get("suspicious_mismatch") or 0)
            if suspicious_mismatch:
                extra = {
                    "reference_text": _stringify(reference_text),
                    "title_norm": title_norm,
                    "clean_title": clean_title,
                    "llm_invoked": int(parse_result.get("llm_invoked") or 0),
                    "parse_method": _stringify(parse_result.get("parse_method")),
                    "parse_failed": int(parse_result.get("parse_failed") or 0),
                    "parse_failure_reason": _stringify(parse_result.get("parse_failure_reason")),
                    **build_online_lookup_placeholder_fields(),
                }
                working, record, action = upsert_reference_citation_placeholder(
                    working,
                    first_author=first_author,
                    year=year,
                    title_raw=title_raw,
                    source=source,
                    placeholder_reason="suspicious_mismatch",
                    placeholder_status="pending",
                    placeholder_run_uid=placeholder_run_uid,
                    extra=extra,
                    top_n=0,
                )
                matched_uid_literature = _stringify(record.get("uid_literature"))
                working, record, matched_cite_key = ensure_reference_citation_cite_key(
                    working,
                    record=record,
                    first_author=first_author,
                    year=year,
                    title_raw=title_raw,
                )
                matched_title = _stringify(record.get("title"))
            else:
                record = matched_record
                matched_uid_literature = _stringify(record.get("uid_literature"))
                matched_title = _stringify(record.get("title"))
                working, record, matched_cite_key = ensure_reference_citation_cite_key(
                    working,
                    record=record,
                    first_author=first_author or _stringify(record.get("first_author")),
                    year=year or _stringify(record.get("year")),
                    title_raw=title_raw or _stringify(record.get("title")),
                )
        else:
            extra = {
                "reference_text": _stringify(reference_text),
                "title_norm": title_norm,
                "clean_title": clean_title,
                "llm_invoked": int(parse_result.get("llm_invoked") or 0),
                "parse_method": _stringify(parse_result.get("parse_method")),
                "parse_failed": int(parse_result.get("parse_failed") or 0),
                "parse_failure_reason": _stringify(parse_result.get("parse_failure_reason")),
                **build_online_lookup_placeholder_fields(),
            }
            working, record, action = upsert_reference_citation_placeholder(
                working,
                first_author=first_author,
                year=year,
                title_raw=title_raw,
                source=source,
                placeholder_reason="parse_failed" if int(parse_result.get("parse_failed") or 0) else "unmatched",
                placeholder_status="pending",
                placeholder_run_uid=placeholder_run_uid,
                extra=extra,
                top_n=top_n,
            )
            matched_uid_literature = _stringify(record.get("uid_literature"))
            working, record, matched_cite_key = ensure_reference_citation_cite_key(
                working,
                record=record,
                first_author=first_author,
                year=year,
                title_raw=title_raw,
            )

        log_db_path = resolve_aok_log_db_path(
            workspace_root_path,
            config_path=Path(global_config_path) if global_config_path else None,
        )
        result = {
            "reference_text": _stringify(reference_text),
            "reference_text_for_parse": reference_text_for_parse,
            "matched_uid_literature": matched_uid_literature,
            "matched_cite_key": matched_cite_key,
            "action": action,
            "parse_method": _stringify(parse_result.get("parse_method")),
            "llm_invoked": int(parse_result.get("llm_invoked") or 0),
            "parse_failed": int(parse_result.get("parse_failed") or 0),
            "parse_failure_reason": _stringify(parse_result.get("parse_failure_reason")),
            "is_reasonable": bool(parse_result.get("is_reasonable")),
            "recognized_fields": recognized,
            "match_score": round(top_match_score, 4),
            "matched_title": matched_title,
            "suspicious_mismatch": int(suspicious_mismatch),
            "repair_applied": int(repair_result.get("repair_applied") or 0),
            "repair_failed": int(repair_result.get("repair_failed") or 0),
            "repair_failure_reason": _stringify(repair_result.get("repair_failure_reason")),
            "llm_backend": _stringify(parse_result.get("llm_backend")),
            "routing_info": parse_result.get("routing_info") or {},
            "placeholder_reason": _stringify(record.get("placeholder_reason")),
            "placeholder_status": _stringify(record.get("placeholder_status")),
            "placeholder_run_uid": _stringify(record.get("placeholder_run_uid")) or _stringify(placeholder_run_uid),
            "is_placeholder": int(record.get("is_placeholder") or 0),
        }
    except Exception as exc:
        working, result = _fallback_insert_reference_placeholder(
            table,
            reference_text,
            source=source,
            parse_method="emergency_placeholder",
            parse_failure_reason=str(exc),
            placeholder_run_uid=placeholder_run_uid,
        )
        log_db_path = resolve_aok_log_db_path(
            workspace_root_path,
            config_path=Path(global_config_path) if global_config_path else None,
        )
    append_aok_log_event(
        event_type="REFERENCE_LOCAL_MATCH",
        project_root=workspace_root_path,
        log_db_path=log_db_path,
        enabled=_resolve_logging_enabled(
            workspace_root_path,
            config_path=Path(global_config_path) if global_config_path else None,
        ),
        handler_kind="local_script",
        handler_name="process_reference_citation",
        model_name=model_name,
        skill_names=["ar_插入引文_v1"],
        reasoning_summary="执行引文本地匹配，未命中则插入占位条目并生成 cite_key。",
        payload=result,
    )
    if print_to_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return working, result

