"""A070 单篇综述精读包工具。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from autodokit.tools.pdf_structured_data_tools import (
    extract_reference_lines_from_structured_data,
    load_structured_data,
    split_text_to_paragraphs,
)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe_repeated_heading(text: str) -> str:
    """去重形如“引言引言”的重复标题文本。"""

    stripped = _stringify(text)
    if len(stripped) < 4:
        return stripped
    half = len(stripped) // 2
    if len(stripped) % 2 == 0 and stripped[:half] == stripped[half:]:
        return stripped[:half]
    return stripped


def _is_noise_line(text: str) -> bool:
    """判断一行文本是否为非正文噪声。"""

    line = _stringify(text)
    if not line:
        return True
    if re.fullmatch(r"\[Page\s*\d+\]", line):
        return True
    if line.startswith("#") and any(token in line for token in ("年份：", "中图分类号", "文献标志码", "文章编号", "DOI")):
        return True
    if any(
        token in line
        for token in (
            "中图分类号",
            "文献标志码",
            "文章编号",
            "收稿日期",
            "作者简介",
            "责任编辑",
            "中国知网",
        )
    ):
        return True
    return False


def _is_reference_heading(line: str) -> bool:
    lowered = _stringify(line).lower().strip("# ")
    return lowered in {"参考文献", "参考文献：", "references", "reference"}


def _load_adjacent_json(base_path: Path, file_name: str) -> Dict[str, Any]:
    """读取与结构化主文件同目录的附属 JSON。"""

    target = base_path.with_name(file_name)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _clean_element_text(text: str) -> str:
    """清洗元素级文本中的页眉页脚、编号与空白噪声。"""

    cleaned = _stringify(text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"\[Page\s*\d+\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"中国知网\s*https?://\S+", "", cleaned)
    cleaned = re.sub(r"REAL\s+ESTATE\s+ECONOMY", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b2\s*0\s*\d\s*\d\s*年?第?\d+期总第\d+期\b", "", cleaned)
    cleaned = re.sub(r"(^|\n)\s*\d{1,3}\s*(?=$|\n)", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _build_clean_body_from_elements(base_path: Path, *, title: str = "") -> tuple[str, List[Dict[str, Any]]]:
    """优先基于结构化 elements 构造正文与证据索引。"""

    elements_payload = _load_adjacent_json(base_path, "elements.json")
    items = elements_payload.get("items") if isinstance(elements_payload.get("items"), list) else []
    if not items:
        return "", []

    ordered_items = sorted(
        items,
        key=lambda item: (
            int(item.get("page_number") or 0),
            int(item.get("reading_order") or 0),
        ),
    )

    paragraphs: List[Dict[str, Any]] = []
    inside_references = False
    for item in ordered_items:
        node_type = _stringify(item.get("node_type"))
        if node_type in {"document_title", "author_block", "affiliation_block"}:
            continue

        raw_text = _clean_element_text(_stringify(item.get("text")))
        if not raw_text:
            continue

        if node_type == "abstract_block":
            raw_text = re.sub(r"^摘\s*要[:：]\s*", "", raw_text)
        if node_type == "keywords_block":
            continue

        pieces = [segment.strip() for segment in re.split(r"\n{2,}|\n", raw_text) if segment.strip()]
        for piece in pieces:
            if _is_reference_heading(piece):
                inside_references = True
                break
            if inside_references or _is_noise_line(piece):
                continue
            normalized = _dedupe_repeated_heading(piece)
            if normalized == title:
                continue
            if paragraphs and normalized == paragraphs[-1]["text"]:
                continue
            page_number = item.get("page_number")
            paragraphs.append(
                {
                    "paragraph_index": len(paragraphs) + 1,
                    "text": normalized,
                    "char_start": None,
                    "char_end": None,
                    "section": "正文",
                    "subsection": "",
                    "page_hint": str(page_number) if page_number is not None else "",
                    "node_id": _stringify(item.get("node_id")),
                    "element_id": _stringify(item.get("node_id")),
                }
            )
        if inside_references:
            break

    if not paragraphs:
        return "", []

    clean_body = "\n\n".join(row["text"] for row in paragraphs if _stringify(row.get("text"))).strip()
    return clean_body, paragraphs


def _build_clean_body(full_text: str, *, title: str = "") -> tuple[str, List[Dict[str, Any]]]:
    """从全文构建过滤后的正文与证据索引。"""

    raw = str(full_text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    lines = [item.strip() for item in raw.split("\n")]

    cleaned_lines: List[str] = []
    for line in lines:
        if not line:
            cleaned_lines.append("")
            continue
        if _is_reference_heading(line):
            break
        if _is_noise_line(line):
            continue
        normalized = _dedupe_repeated_heading(line)
        if cleaned_lines and normalized == cleaned_lines[-1]:
            continue
        cleaned_lines.append(normalized)

    normalized_text = "\n".join(cleaned_lines).strip()
    paragraphs = split_text_to_paragraphs(normalized_text)
    evidence_rows: List[Dict[str, Any]] = []
    for idx, row in enumerate(paragraphs, start=1):
        evidence_rows.append(
            {
                "paragraph_index": idx,
                "text": _stringify(row.get("text")),
                "char_start": row.get("char_start"),
                "char_end": row.get("char_end"),
                "section": "正文",
                "subsection": "",
                "page_hint": "",
                "node_id": "",
                "element_id": "",
            }
        )

    body_parts: List[str] = []
    body_parts.extend([_stringify(item.get("text")) for item in evidence_rows if _stringify(item.get("text"))])
    clean_body = "\n\n".join([item for item in body_parts if item is not None]).strip()
    return clean_body, evidence_rows


def build_review_reading_packet(
    structured_json_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> Dict[str, Any]:
    """构建单篇综述精读包。

    Args:
        structured_json_path: 结构化结果路径。
        output_dir: 可选输出目录，若提供则写出中间产物。

    Returns:
        单篇综述精读包字典。
    """

    path = Path(structured_json_path).expanduser().resolve()
    payload = load_structured_data(path)
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    parse_profile = payload.get("parse_profile") if isinstance(payload.get("parse_profile"), dict) else {}
    text_payload = payload.get("text") if isinstance(payload.get("text"), dict) else {}

    title = _stringify(source.get("title"))
    full_text = _stringify(text_payload.get("full_text"))
    clean_body, evidence_rows = _build_clean_body_from_elements(path, title=title)
    if len(clean_body) < 500:
        clean_body, evidence_rows = _build_clean_body(full_text, title=title)
    ref_extraction = extract_reference_lines_from_structured_data(payload)
    reference_rows = [_stringify(item) for item in list(ref_extraction.get("reference_lines") or []) if _stringify(item)]

    orientation = {
        "uid_literature": _stringify(source.get("uid_literature")),
        "cite_key": _stringify(source.get("cite_key")),
        "title": title,
        "year": _stringify(source.get("year")),
        "pdf_abs_path": _stringify(source.get("pdf_abs_path")),
        "backend": _stringify(source.get("backend")),
        "task_type": _stringify(parse_profile.get("task_type")),
        "structured_json_path": str(path),
    }
    packet = {
        "orientation": orientation,
        "clean_body": clean_body,
        "evidence_index": evidence_rows,
        "references": reference_rows,
        "asset_manifest": {
            "structured_json_path": str(path),
            "pdf_abs_path": _stringify(source.get("pdf_abs_path")),
            "attachment_path": _stringify(ref_extraction.get("attachment_path")),
            "extract_status": _stringify(ref_extraction.get("extract_status")),
            "extract_method": _stringify(ref_extraction.get("extract_method")),
            "needs_pdf_fallback": len(clean_body) < 300,
        },
    }

    if output_dir is not None:
        out_dir = Path(output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "orientation.json").write_text(json.dumps(orientation, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "clean_body.md").write_text((clean_body or "").strip() + "\n", encoding="utf-8")
        with (out_dir / "evidence_index.jsonl").open("w", encoding="utf-8") as stream:
            for row in evidence_rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        with (out_dir / "references.jsonl").open("w", encoding="utf-8") as stream:
            for line in reference_rows:
                stream.write(json.dumps({"reference_text": line}, ensure_ascii=False) + "\n")
        (out_dir / "asset_manifest.json").write_text(
            json.dumps(packet["asset_manifest"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return packet


__all__ = ["build_review_reading_packet"]
