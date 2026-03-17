"""LLM 输出解析工具。

本模块用于沉淀“跨事务可复用”的 LLM 输出解析能力，避免每个事务重复实现：
- 从 LLM 返回文本中提取 JSON（兼容 ```json 代码块、前后解释文字、截断）。
- 字段别名兼容（例如 keywords/keywords_zh/keywords_en）。
- 基础类型校验（对象/数组/字符串等），并提供友好的错误信息。
- 可观测性：解析失败时可将原始输出落盘到 debug 目录，便于排障。

注意：本模块不会理解具体业务 schema（例如“关键词集合”的 domains 结构）。
业务侧应在拿到解析结果后完成更细的 schema 校验与后处理。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, NoReturn, Optional, Sequence, Tuple


class LLMOutputParseError(ValueError):
    """LLM 输出解析错误。"""


@dataclass(frozen=True)
class ParseDebugInfo:
    """解析调试信息。

    Attributes:
        raw_preview: 原始文本截断预览。
        extracted_preview: 抽取后的候选 JSON 文本预览（若有）。
        error: 失败原因（若有）。
    """

    raw_preview: str
    extracted_preview: Optional[str] = None
    error: Optional[str] = None


def truncate_text(text: str, *, limit: int = 1200) -> str:
    """截断文本用于日志/落盘，避免文件过大。

    Args:
        text: 原始文本。
        limit: 最大字符数。

    Returns:
        截断后的文本。
    """

    s = (text or "").strip()
    return s if len(s) <= int(limit) else (s[: int(limit)] + "\n...[truncated]...")


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def strip_code_fences(text: str) -> str:
    """移除 Markdown 代码块围栏并返回其中内容。

    如果找到一个或多个代码块，将返回“最长的代码块内容”，因为多数情况下 JSON 在最长块中。

    Args:
        text: 原始文本。

    Returns:
        去围栏后的文本。
    """

    s = (text or "").strip()
    if not s:
        return ""

    matches = _CODE_FENCE_RE.findall(s)
    if not matches:
        return s

    # 取最长的块作为候选
    return max((m.strip() for m in matches if str(m).strip()), key=len, default=s)


def extract_outermost_json_substring(text: str) -> Optional[str]:
    """从文本中抽取最外层 JSON 子串。

    策略：寻找第一个 '{' 与最后一个 '}'，截取为候选。

    Args:
        text: 原始文本。

    Returns:
        候选 JSON 子串或 None。
    """

    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= 0 and end > start:
        return text[start : end + 1]
    return None


def parse_json_object_from_text(
    text: str,
    *,
    allow_outermost_extraction: bool = True,
    debug_dir: str | Path | None = None,
    debug_prefix: str = "llm_output",
) -> Tuple[Dict[str, Any], ParseDebugInfo]:
    """从 LLM 返回文本中解析 JSON 对象（dict）。

    解析顺序：
    1) 直接 json.loads(text)
    2) 去除代码围栏后再 json.loads
    3) 从文本中抽取最外层 JSON 子串再 json.loads（可选）

    Args:
        text: LLM 返回文本。
        allow_outermost_extraction: 是否允许抽取最外层 JSON 子串。
        debug_dir: 若提供且解析失败，则把原始输出落盘到该目录。
        debug_prefix: 落盘文件名前缀。

    Returns:
        (parsed_dict, debug_info)

    Raises:
        LLMOutputParseError: 无法解析为 JSON 对象。
    """

    raw = (text or "")
    raw_preview = truncate_text(raw)

    def _fail(msg: str, extracted: Optional[str] = None) -> NoReturn:
        info = ParseDebugInfo(
            raw_preview=raw_preview,
            extracted_preview=truncate_text(extracted or "") if extracted else None,
            error=msg,
        )
        if debug_dir:
            dump_raw_output(raw, debug_dir=debug_dir, prefix=debug_prefix, meta={"error": msg, "preview": info.raw_preview})
        raise LLMOutputParseError(msg)

    # 1) 直接解析
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj, ParseDebugInfo(raw_preview=raw_preview)
    except Exception:
        pass

    # 2) 去 code fence
    s2 = strip_code_fences(raw)
    if s2 != raw:
        try:
            obj2 = json.loads(s2)
            if isinstance(obj2, dict):
                return obj2, ParseDebugInfo(raw_preview=raw_preview, extracted_preview=truncate_text(s2))
        except Exception:
            pass

    # 3) 抽取最外层 JSON
    if allow_outermost_extraction:
        candidate = extract_outermost_json_substring(s2)
        if candidate:
            try:
                obj3 = json.loads(candidate)
                if isinstance(obj3, dict):
                    return obj3, ParseDebugInfo(raw_preview=raw_preview, extracted_preview=truncate_text(candidate))
            except Exception as exc:
                _fail(f"JSON 抽取后仍无法解析：{exc}", extracted=candidate)

    _fail("无法从文本中解析出 JSON 对象（dict）")


def pick_first_list_field(
    obj: Mapping[str, Any],
    *,
    candidates: Sequence[str],
) -> Tuple[List[str], Optional[str]]:
    """从对象中按候选键名提取字符串列表。

    Args:
        obj: JSON 对象。
        candidates: 候选键名列表（按优先级顺序）。

    Returns:
        (values, picked_key)
    """

    for k in candidates:
        if k in obj:
            vals = to_str_list(obj.get(k))
            if vals:
                return vals, k
            return [], k
    return [], None


def to_str_list(value: Any) -> List[str]:
    """将任意值转换为字符串列表并清理空项。

    Args:
        value: 任意值。

    Returns:
        字符串列表。
    """

    if value is None:
        return []
    if isinstance(value, list):
        out: List[str] = []
        for v in value:
            s = str(v).strip()
            if s:
                out.append(s)
        return out
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    s2 = str(value).strip()
    return [s2] if s2 else []


def dump_raw_output(
    text: str,
    *,
    debug_dir: str | Path,
    prefix: str = "llm_output",
    meta: Optional[Dict[str, Any]] = None,
) -> Path:
    """将原始输出落盘到 debug 目录。

    Args:
        text: 原始输出。
        debug_dir: 输出目录。
        prefix: 文件名前缀。
        meta: 可选元信息（会一并写入 .json）。

    Returns:
        写出的文件路径（.txt）。
    """

    d = Path(debug_dir)
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    txt_path = d / f"{prefix}_{ts}.txt"
    txt_path.write_text(text or "", encoding="utf-8")

    if meta is not None:
        meta_path = d / f"{prefix}_{ts}.meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return txt_path


def is_likely_sdk_response_blob(text: str) -> bool:
    """判断文本是否像 SDK 返回对象的字符串化结果。

    Args:
        text: 文本。

    Returns:
        是否疑似包含 status_code/request_id/usage 等元数据。
    """

    s = (text or "")
    return any(k in s for k in ["\"status_code\"", "\"request_id\"", "\"usage\"", "finish_reason"])  # 保守判断


def extract_output_text_from_response_like_blob(text: str) -> Optional[str]:
    """从疑似 SDK Response blob 中抽取 output.text。

    说明：
    - 这是一个“最大努力”的容错工具。
    - 如果输入不符合 JSON，也可能返回 None。

    Args:
        text: 原始文本。

    Returns:
        output.text 或 None。
    """

    s = (text or "").strip()
    if not s:
        return None

    # 尝试整体 JSON
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            out = obj.get("output")
            if isinstance(out, dict) and isinstance(out.get("text"), str) and out["text"].strip():
                return out["text"].strip()
    except Exception:
        pass

    # 抽取最外层 JSON
    candidate = extract_outermost_json_substring(s)
    if not candidate:
        return None
    try:
        obj2 = json.loads(candidate)
        if isinstance(obj2, dict):
            out2 = obj2.get("output")
            if isinstance(out2, dict) and isinstance(out2.get("text"), str) and out2["text"].strip():
                return out2["text"].strip()
    except Exception:
        return None

    return None

