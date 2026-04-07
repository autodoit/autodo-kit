"""阿里百炼多模态解析文本后处理工具。

该工具用于在视觉解析资产生成后，对 `reconstructed_content.md`
和 `normalized.structured.json` 中的正文文本做轻量规则化清洗。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict


_PAGE_MARKER_PATTERN = re.compile(r"^\[Page\s+\d+\]$", re.IGNORECASE)
_PAGE_NUMBER_PATTERN = re.compile(r"^\d{1,4}$")
_NOISE_PATTERNS = [
    re.compile(r"^中国知网\s+https?://", re.IGNORECASE),
    re.compile(r"^REAL\s+ESTATE\s+ECONOMY$", re.IGNORECASE),
    re.compile(r"^\d{4}年第\d+期"),
]


def _stringify(value: Any) -> str:
    """把任意值转换为安全字符串。

    Args:
        value: 待转换值。

    Returns:
        str: 去首尾空白后的字符串。

    Raises:
        None.

    Examples:
        >>> _stringify(None)
        ''
    """

    if value is None:
        return ""
    return str(value).strip()


def _is_noise_line(text: str, *, keep_page_markers: bool) -> bool:
    """判断单行文本是否属于版面噪声。

    Args:
        text: 单行文本。
        keep_page_markers: 是否保留页标记行。

    Returns:
        bool: True 表示应删除。

    Raises:
        None.

    Examples:
        >>> _is_noise_line('[Page 2]', keep_page_markers=False)
        True
    """

    stripped = text.strip()
    if not stripped:
        return False
    if _PAGE_MARKER_PATTERN.match(stripped):
        return not keep_page_markers
    if _PAGE_NUMBER_PATTERN.match(stripped):
        return True
    for pattern in _NOISE_PATTERNS:
        if pattern.search(stripped):
            return True
    return False


def _normalize_soft_wraps(text: str) -> str:
    """合并由版式导致的软换行与断词。

    Args:
        text: 原始文本。

    Returns:
        str: 清洗后的文本。

    Raises:
        None.

    Examples:
        >>> _normalize_soft_wraps('per-\\nvasive')
        'pervasive'
    """

    # 英文断词：`per-\nvasive` -> `pervasive`
    normalized = re.sub(r"([A-Za-z])-\n([A-Za-z])", r"\1\2", text)

    lines = normalized.split("\n")
    cleaned_lines: list[str] = []
    for line in lines:
        cleaned_lines.append(line.rstrip())

    merged: list[str] = []
    for line in cleaned_lines:
        stripped = line.strip()
        if not stripped:
            if merged and merged[-1] != "":
                merged.append("")
            continue

        if not merged or merged[-1] == "":
            merged.append(stripped)
            continue

        prev = merged[-1]
        prev_tail = prev[-1] if prev else ""
        curr_head = stripped[0]

        prev_ends_sentence = prev_tail in "。！？；.!?:："
        curr_looks_header = stripped.startswith("#") or stripped.startswith("[")

        if prev_ends_sentence or curr_looks_header:
            merged.append(stripped)
            continue

        # 中文与中文直接拼接，英文语句补空格。
        if "\u4e00" <= prev_tail <= "\u9fff" and "\u4e00" <= curr_head <= "\u9fff":
            merged[-1] = prev + stripped
        else:
            merged[-1] = prev + " " + stripped

    return "\n".join(merged).strip() + "\n"


def clean_aliyun_multimodal_text(
    text: str,
    *,
    keep_page_markers: bool = False,
) -> Dict[str, Any]:
    """清洗阿里百炼多模态重建文本。

    Args:
        text: 原始文本。
        keep_page_markers: 是否保留 `[Page n]` 行。

    Returns:
        Dict[str, Any]: 包含清洗文本与统计信息。

    Raises:
        None.

    Examples:
        >>> result = clean_aliyun_multimodal_text('[Page 1]\\n正文')
        >>> result['cleaned_text'].strip()
        '正文'
    """

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = normalized.split("\n")

    retained_lines: list[str] = []
    removed_noise_count = 0
    for line in raw_lines:
        if _is_noise_line(line, keep_page_markers=keep_page_markers):
            removed_noise_count += 1
            continue
        retained_lines.append(line)

    retained_text = "\n".join(retained_lines)
    cleaned_text = _normalize_soft_wraps(retained_text)

    return {
        "cleaned_text": cleaned_text,
        "raw_char_count": len(text),
        "cleaned_char_count": len(cleaned_text),
        "removed_noise_lines": removed_noise_count,
        "line_count_before": len(raw_lines),
        "line_count_after": len(cleaned_text.splitlines()),
    }


def postprocess_aliyun_multimodal_parse_outputs(
    *,
    normalized_structured_path: str | Path,
    reconstructed_markdown_path: str | Path = "",
    rewrite_structured: bool = True,
    rewrite_markdown: bool = True,
    keep_page_markers: bool = False,
) -> Dict[str, Any]:
    """对阿里百炼解析产物执行后处理并回写。

    Args:
        normalized_structured_path: `normalized.structured.json` 绝对路径。
        reconstructed_markdown_path: `reconstructed_content.md` 绝对路径。
        rewrite_structured: 是否回写 structured 的 `text.full_text`。
        rewrite_markdown: 是否回写 markdown 文件。
        keep_page_markers: 是否保留页标记行。

    Returns:
        Dict[str, Any]: 后处理执行摘要。

    Raises:
        FileNotFoundError: 必需文件不存在时抛出。
        ValueError: structured 内容不合法时抛出。

    Examples:
        >>> # doctest: +SKIP
        >>> postprocess_aliyun_multimodal_parse_outputs(
        ...     normalized_structured_path='C:/workspace/normalized.structured.json'
        ... )
    """

    structured_file = Path(normalized_structured_path).resolve()
    if not structured_file.exists() or not structured_file.is_file():
        raise FileNotFoundError(f"normalized_structured_path 不存在: {structured_file}")

    structured_payload = json.loads(structured_file.read_text(encoding="utf-8-sig"))
    if not isinstance(structured_payload, dict):
        raise ValueError("normalized.structured.json 顶层必须是对象")

    text_payload = structured_payload.get("text") if isinstance(structured_payload.get("text"), dict) else {}
    raw_text = _stringify(text_payload.get("full_text"))

    markdown_file = Path(_stringify(reconstructed_markdown_path)).resolve() if _stringify(reconstructed_markdown_path) else None
    if (not raw_text) and markdown_file and markdown_file.exists() and markdown_file.is_file():
        raw_text = markdown_file.read_text(encoding="utf-8")

    if not raw_text:
        raise ValueError("未找到可处理的正文文本（structured.text.full_text 与 reconstructed_content.md 均为空）")

    result = clean_aliyun_multimodal_text(raw_text, keep_page_markers=keep_page_markers)
    cleaned_text = _stringify(result.get("cleaned_text"))

    if rewrite_markdown:
        target_markdown = markdown_file or (structured_file.parent / "reconstructed_content.md")
        target_markdown.parent.mkdir(parents=True, exist_ok=True)
        target_markdown.write_text(cleaned_text + "\n", encoding="utf-8")
        result["postprocessed_markdown_path"] = str(target_markdown)
    else:
        result["postprocessed_markdown_path"] = _stringify(markdown_file) if markdown_file else ""

    if rewrite_structured:
        if not isinstance(text_payload, dict):
            text_payload = {}
        text_payload["full_text"] = cleaned_text
        structured_payload["text"] = text_payload
        metadata_payload = structured_payload.get("metadata") if isinstance(structured_payload.get("metadata"), dict) else {}
        metadata_payload["postprocess"] = {
            "applied": True,
            "tool": "aok_aliyun_multimodal_postprocess.v1",
            "removed_noise_lines": int(result.get("removed_noise_lines") or 0),
            "line_count_before": int(result.get("line_count_before") or 0),
            "line_count_after": int(result.get("line_count_after") or 0),
            "raw_char_count": int(result.get("raw_char_count") or 0),
            "cleaned_char_count": int(result.get("cleaned_char_count") or 0),
        }
        structured_payload["metadata"] = metadata_payload
        structured_file.write_text(json.dumps(structured_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    result["normalized_structured_path"] = str(structured_file)
    result["structured_rewritten"] = bool(rewrite_structured)
    result["markdown_rewritten"] = bool(rewrite_markdown)
    result["postprocess_tool"] = "aok_aliyun_multimodal_postprocess.v1"
    return result


__all__ = [
    "clean_aliyun_multimodal_text",
    "postprocess_aliyun_multimodal_parse_outputs",
]
