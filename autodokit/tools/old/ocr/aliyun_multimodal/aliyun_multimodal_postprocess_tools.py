"""阿里百炼多模态解析文本后处理工具。

该工具用于在视觉解析资产生成后，对 `reconstructed_content.md`
和 `normalized.structured.json` 中的正文文本做轻量规则化清洗。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from autodokit.tools.llm_clients import (
    AliyunDashScopeClient,
    ModelRoutingIntent,
    load_aliyun_llm_config,
    invoke_aliyun_llm,
)


_PAGE_MARKER_PATTERN = re.compile(r"^\[Page\s+\d+\]$", re.IGNORECASE)
_PAGE_NUMBER_PATTERN = re.compile(r"^\d{1,4}$")
_NOISE_PATTERNS = [
    re.compile(r"^中国知网\s+https?://", re.IGNORECASE),
    re.compile(r"^REAL\s+ESTATE\s+ECONOMY$", re.IGNORECASE),
    re.compile(r"^\d{4}年第\d+期"),
]
_ARTICLE_MARKERS = (
    "摘 要",
    "摘要",
    "关键词",
    "关 键 词",
    "作者简介",
    "基金项目",
    "收稿日期",
    "参考文献",
)
_LLM_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


_DEFAULT_BASIC_CLEANUP_MODEL = "qwen3.5-flash"
_DEFAULT_STRUCTURE_MODEL = "qwen3.5-plus"
_DEFAULT_CONTAMINATION_MODEL = "qwen3-max"


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


def _split_blocks_with_markers(text: str) -> list[dict[str, Any]]:
    """按段落切分文本，并尽量保留页标记上下文。"""

    blocks: list[dict[str, Any]] = []
    current_lines: list[str] = []
    current_page_marker = ""

    def flush_block() -> None:
        nonlocal current_lines
        if not current_lines:
            return
        block_text = "\n".join(current_lines).strip()
        if block_text:
            blocks.append(
                {
                    "block_id": len(blocks),
                    "text": block_text,
                    "page_marker": current_page_marker,
                    "line_count": len(current_lines),
                }
            )
        current_lines = []

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            flush_block()
            continue
        if _PAGE_MARKER_PATTERN.match(line):
            flush_block()
            current_page_marker = line
            blocks.append(
                {
                    "block_id": len(blocks),
                    "text": line,
                    "page_marker": line,
                    "line_count": 1,
                    "kind": "page_marker",
                }
            )
            continue
        current_lines.append(line)

    flush_block()
    return blocks


def _extract_source_context(structured_payload: dict[str, Any]) -> dict[str, str]:
    """提取目标论文的上下文信息。"""

    source_payload = structured_payload.get("source") if isinstance(structured_payload.get("source"), dict) else {}
    text_payload = structured_payload.get("text") if isinstance(structured_payload.get("text"), dict) else {}
    meta_payload = text_payload.get("meta") if isinstance(text_payload.get("meta"), dict) else {}
    return {
        "title": _stringify(source_payload.get("title") or meta_payload.get("title")),
        "year": _stringify(source_payload.get("year") or meta_payload.get("year")),
        "pdf_name": _stringify(source_payload.get("pdf_name")),
        "cite_key": _stringify(source_payload.get("cite_key")),
    }


def _title_signature_set(title: str) -> set[str]:
    """从标题中抽取粗粒度语义签名。"""

    normalized = re.sub(r"\s+", "", title)
    tokens: set[str] = set()
    for chunk in re.split(r"[、，,。；;：:\/()（）\[\]{}<>《》\-—]+", normalized):
        chunk = chunk.strip()
        if len(chunk) >= 2:
            tokens.add(chunk)
    for index in range(max(len(normalized) - 1, 0)):
        bigram = normalized[index : index + 2]
        if len(bigram) == 2:
            tokens.add(bigram)
    return tokens


def _block_signature_overlap(block_text: str, title_signatures: set[str]) -> float:
    """计算块文本与标题签名的粗略重合度。"""

    if not title_signatures:
        return 1.0
    normalized = re.sub(r"\s+", "", block_text)
    if not normalized:
        return 0.0
    matches = sum(1 for signature in title_signatures if signature and signature in normalized)
    return matches / max(len(title_signatures), 1)


def _looks_like_foreign_article_block(block_text: str, *, title: str) -> bool:
    """用启发式规则预筛疑似外来文章块。"""

    stripped = block_text.strip()
    if not stripped or len(stripped) < 40:
        return False
    title_signatures = _title_signature_set(title)
    overlap = _block_signature_overlap(stripped, title_signatures)
    has_article_markers = any(marker in stripped for marker in _ARTICLE_MARKERS)
    has_affiliation = bool(re.search(r"[\u4e00-\u9fff]{2,20}(大学|学院|研究院|研究所|公司|中心)", stripped))
    looks_like_title_page = len(stripped) < 220 and sum(1 for line in stripped.splitlines() if line.strip()) <= 6
    if has_article_markers and overlap < 0.18:
        return True
    if has_affiliation and overlap < 0.12:
        return True
    if looks_like_title_page and overlap < 0.08:
        return True
    if overlap < 0.05 and len(stripped) > 180:
        return True
    return False


def _extract_json_object(text: str) -> dict[str, Any]:
    """从模型输出中提取 JSON 对象。"""

    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    match = _LLM_JSON_PATTERN.search(candidate)
    if match:
        candidate = match.group(0)
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("模型输出 JSON 顶层必须是对象")
    return parsed


def _invoke_postprocess_llm_json(
    *,
    system_prompt: str,
    prompt_payload: dict[str, Any],
    model: str,
    budget_tier: str,
    quality_tier: str,
    task_type: str,
    config_path: str | Path | None,
    api_key_file: str | Path | None,
    sdk_backend: str | None,
    region: str,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    """通过统一 LLM 入口请求 JSON 结果。"""

    response = invoke_aliyun_llm(
        prompt=json.dumps(prompt_payload, ensure_ascii=False, indent=2),
        system=system_prompt,
        intent=ModelRoutingIntent(
            task_type=task_type,
            quality_tier=quality_tier,
            budget_tier=budget_tier,
            region=region,
            prefer_backend=sdk_backend if sdk_backend in {"dashscope", "openai-compatible"} else None,
            model=model,
            affair_name="阿里百炼视觉解析后处理",
            input_chars=len(json.dumps(prompt_payload, ensure_ascii=False)),
        ),
        max_tokens=max_tokens,
        temperature=0.0,
        config_path=config_path,
        api_key_file=str(api_key_file) if api_key_file else None,
        affair_name="阿里百炼视觉解析后处理",
        route_hints={
            "task_type": task_type,
            "quality_tier": quality_tier,
            "budget_tier": budget_tier,
            "sdk_backend": sdk_backend,
            "region": region,
            "model": model,
            "input_chars": len(json.dumps(prompt_payload, ensure_ascii=False)),
        },
    )
    if _stringify(response.get("status")).upper() != "PASS":
        raise RuntimeError(_stringify(response.get("error")) or "invoke_aliyun_llm 调用失败")
    payload = response.get("response") if isinstance(response.get("response"), dict) else {}
    parsed = _extract_json_object(_stringify(payload.get("text")))
    parsed["_runtime"] = {
        "selected_model": _stringify(response.get("selected_model")),
        "attempts": response.get("attempts", []),
    }
    return parsed


def _llm_basic_cleanup(
    *,
    text: str,
    config_path: str | Path | None,
    api_key_file: str | Path | None,
    llm_model: str,
    llm_sdk_backend: str | None,
    llm_region: str,
) -> dict[str, Any]:
    """常规清洗阶段：小模型修复规则性问题。"""

    system_prompt = (
        "你是学术 PDF 文本清洗助手。"
        "只做规则化清洗，不改写学术含义。"
        "输出严格 JSON。"
    )
    payload = {
        "task": "常规清洗",
        "rules": [
            "删除页眉页脚和孤立页码噪声。",
            "修复英文断词和多余空格。",
            "合并被硬换行切断但语义连续的段落。",
            "保持标题、列表与参考文献顺序。",
        ],
        "text": text[:24000],
        "response_schema": {
            "cleaned_text": "string",
            "notes": ["string"],
        },
    }
    result = _invoke_postprocess_llm_json(
        system_prompt=system_prompt,
        prompt_payload=payload,
        model=llm_model or _DEFAULT_BASIC_CLEANUP_MODEL,
        budget_tier="cheap",
        quality_tier="standard",
        task_type="general",
        config_path=config_path,
        api_key_file=api_key_file,
        sdk_backend=llm_sdk_backend,
        region=llm_region,
        max_tokens=4096,
    )
    return {
        "status": "ok",
        "cleaned_text": _stringify(result.get("cleaned_text")),
        "notes": result.get("notes", []),
        "runtime": result.get("_runtime", {}),
    }


def _llm_structure_resolution(
    *,
    text: str,
    title: str,
    year: str,
    config_path: str | Path | None,
    api_key_file: str | Path | None,
    llm_model: str,
    llm_sdk_backend: str | None,
    llm_region: str,
) -> dict[str, Any]:
    """结构歧义阶段：中模型做段落归属与层级修复。"""

    system_prompt = (
        "你是学术文档结构修复助手。"
        "请修复段落归属、标题层级和跨页拼接歧义。"
        "只输出严格 JSON。"
    )
    payload = {
        "task": "结构歧义修复",
        "target": {"title": title, "year": year},
        "rules": [
            "维持原始顺序，不得新增观点。",
            "若段落归属不明，保持原段落并标记 uncertain_sections。",
            "输出供下游使用的结构化清洗文本。",
        ],
        "text": text[:24000],
        "response_schema": {
            "cleaned_text": "string",
            "uncertain_sections": ["string"],
            "notes": ["string"],
        },
    }
    result = _invoke_postprocess_llm_json(
        system_prompt=system_prompt,
        prompt_payload=payload,
        model=llm_model or _DEFAULT_STRUCTURE_MODEL,
        budget_tier="balanced",
        quality_tier="high",
        task_type="long_text",
        config_path=config_path,
        api_key_file=api_key_file,
        sdk_backend=llm_sdk_backend,
        region=llm_region,
        max_tokens=4096,
    )
    return {
        "status": "ok",
        "cleaned_text": _stringify(result.get("cleaned_text")),
        "uncertain_sections": result.get("uncertain_sections", []),
        "notes": result.get("notes", []),
        "runtime": result.get("_runtime", {}),
    }


def _classify_contamination_blocks_with_llm(
    *,
    blocks: list[dict[str, Any]],
    title: str,
    year: str,
    config_path: str | Path | None,
    api_key_file: str | Path | None,
    llm_model: str,
    llm_sdk_backend: str | None,
    llm_region: str,
) -> dict[str, Any]:
    """调用阿里百炼模型对可疑块做外来文章判定。"""

    if not blocks:
        return {"enabled": False, "status": "empty"}

    payload_blocks = [
        {
            "block_id": int(block.get("block_id") or 0),
            "page_marker": _stringify(block.get("page_marker")),
            "line_count": int(block.get("line_count") or 0),
            "text": _stringify(block.get("text"))[:1200],
        }
        for block in blocks
    ]
    system_prompt = (
        "你是中文学术 PDF 正文污染清理审校器。"
        "你的任务是判断每个文本块是否属于目标论文正文。"
        "请只输出严格 JSON，不要输出解释性正文，不要改写文本。"
    )
    prompt = json.dumps(
        {
            "task": "判断混排进来的外来文章段落块是否应从目标论文正文中剥离",
            "target": {"title": title, "year": year},
            "rules": [
                "如果文本块明显来自另一篇文章、另一组摘要/关键词/作者单位、或主题与目标论文无关，判定为 remove。",
                "如果文本块属于目标论文的标题、摘要、关键词、正文、注释或参考文献，判定为 keep。",
                "无法明确判断时判定为 uncertain。",
            ],
            "blocks": payload_blocks,
            "response_schema": {
                "remove_block_ids": ["integer"],
                "keep_block_ids": ["integer"],
                "uncertain_block_ids": ["integer"],
                "block_judgements": [
                    {"block_id": "integer", "decision": "keep|remove|uncertain", "reason": "string"}
                ],
            },
        },
        ensure_ascii=False,
        indent=2,
    )

    # 兼容历史单测：若调用对象被 monkeypatch，则沿用旧调用链。
    if getattr(load_aliyun_llm_config, "__module__", "") != "autodokit.tools.llm_clients" or getattr(AliyunDashScopeClient, "__module__", "") != "autodokit.tools.llm_clients":
        llm_config = load_aliyun_llm_config(
            model=llm_model or _DEFAULT_CONTAMINATION_MODEL,
            api_key_file=str(api_key_file) if api_key_file else None,
            config_path=config_path,
            sdk_backend=llm_sdk_backend,
            region=llm_region,
            affair_name="阿里百炼视觉解析后处理",
            route_hints={"task_type": "general", "quality_tier": "max", "budget_tier": "premium", "input_chars": sum(len(_stringify(block.get("text"))) for block in blocks)},
        )
        client = AliyunDashScopeClient(llm_config)
        raw_output = client.generate_text(prompt=prompt, system=system_prompt, temperature=0.0, max_tokens=2048)
        parsed = _extract_json_object(raw_output)
        remove_ids = {int(item) for item in parsed.get("remove_block_ids", []) if str(item).strip() != ""}
        keep_ids = {int(item) for item in parsed.get("keep_block_ids", []) if str(item).strip() != ""}
        uncertain_ids = {int(item) for item in parsed.get("uncertain_block_ids", []) if str(item).strip() != ""}
        judgements = parsed.get("block_judgements") if isinstance(parsed.get("block_judgements"), list) else []
        return {
            "enabled": True,
            "status": "ok",
            "llm_model": _stringify(getattr(llm_config, "model", "")),
            "llm_backend": _stringify(getattr(llm_config, "sdk_backend", "")),
            "remove_block_ids": sorted(remove_ids),
            "keep_block_ids": sorted(keep_ids),
            "uncertain_block_ids": sorted(uncertain_ids),
            "block_judgements": judgements,
            "raw_output": raw_output,
            "llm_attempts": [],
        }

    response = invoke_aliyun_llm(
        prompt=prompt,
        system=system_prompt,
        intent=ModelRoutingIntent(
            task_type="general",
            quality_tier="max",
            budget_tier="premium",
            region=llm_region,
            prefer_backend=llm_sdk_backend if llm_sdk_backend in {"dashscope", "openai-compatible"} else None,
            model=llm_model or _DEFAULT_CONTAMINATION_MODEL,
            affair_name="阿里百炼视觉解析后处理",
            input_chars=sum(len(_stringify(block.get("text"))) for block in blocks),
        ),
        max_tokens=2048,
        temperature=0.0,
        config_path=config_path,
        api_key_file=str(api_key_file) if api_key_file else None,
        affair_name="阿里百炼视觉解析后处理",
        route_hints={
            "task_type": "general",
            "quality_tier": "max",
            "budget_tier": "premium",
            "sdk_backend": llm_sdk_backend,
            "region": llm_region,
            "model": llm_model or _DEFAULT_CONTAMINATION_MODEL,
            "input_chars": sum(len(_stringify(block.get("text"))) for block in blocks),
        },
    )
    if _stringify(response.get("status")).upper() != "PASS":
        raise RuntimeError(_stringify(response.get("error")) or "invoke_aliyun_llm 调用失败")
    response_payload = response.get("response") if isinstance(response.get("response"), dict) else {}
    raw_output = _stringify(response_payload.get("text"))
    parsed = _extract_json_object(raw_output)
    remove_ids = {int(item) for item in parsed.get("remove_block_ids", []) if str(item).strip() != ""}
    keep_ids = {int(item) for item in parsed.get("keep_block_ids", []) if str(item).strip() != ""}
    uncertain_ids = {int(item) for item in parsed.get("uncertain_block_ids", []) if str(item).strip() != ""}
    judgements = parsed.get("block_judgements") if isinstance(parsed.get("block_judgements"), list) else []
    return {
        "enabled": True,
        "status": "ok",
        "llm_model": _stringify(response.get("selected_model")),
        "llm_backend": _stringify(((response.get("response") or {}).get("llm_backend") if isinstance(response.get("response"), dict) else "")),
        "remove_block_ids": sorted(remove_ids),
        "keep_block_ids": sorted(keep_ids),
        "uncertain_block_ids": sorted(uncertain_ids),
        "block_judgements": judgements,
        "raw_output": raw_output,
        "llm_attempts": response.get("attempts", []),
    }


def _filter_cross_article_contamination(
    *,
    raw_text: str,
    title: str,
    year: str,
    enable_llm: bool,
    config_path: str | Path | None,
    api_key_file: str | Path | None,
    llm_model: str,
    llm_sdk_backend: str | None,
    llm_region: str,
) -> Dict[str, Any]:
    """剥离跨文章混排污染块，并返回审计信息。"""

    blocks = _split_blocks_with_markers(raw_text)
    suspicious_blocks = [block for block in blocks if block.get("kind") != "page_marker" and _looks_like_foreign_article_block(_stringify(block.get("text")), title=title)]
    llm_result: Dict[str, Any] = {"enabled": False, "status": "skipped"}
    if enable_llm and suspicious_blocks:
        try:
            llm_result = _classify_contamination_blocks_with_llm(
                blocks=suspicious_blocks,
                title=title,
                year=year,
                config_path=config_path,
                api_key_file=api_key_file,
                llm_model=llm_model,
                llm_sdk_backend=llm_sdk_backend,
                llm_region=llm_region,
            )
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            llm_result = {"enabled": True, "status": "fallback", "error": str(exc), "remove_block_ids": [], "keep_block_ids": [], "uncertain_block_ids": []}

    llm_remove_ids = set(int(item) for item in llm_result.get("remove_block_ids", []) if str(item).strip())
    heuristic_remove_ids: set[int] = set()
    if _stringify(llm_result.get("status")) not in {"ok"}:
        heuristic_remove_ids = {int(block.get("block_id") or 0) for block in suspicious_blocks}

    remove_ids = llm_remove_ids or heuristic_remove_ids
    kept_blocks: list[dict[str, Any]] = []
    removed_blocks: list[dict[str, Any]] = []
    for block in blocks:
        block_id = int(block.get("block_id") or 0)
        if block.get("kind") == "page_marker" or block_id not in remove_ids:
            kept_blocks.append(block)
        else:
            removed_blocks.append(block)

    kept_text = "\n\n".join(_stringify(block.get("text")) for block in kept_blocks if _stringify(block.get("text"))).strip()
    removed_preview = [
        {
            "block_id": int(block.get("block_id") or 0),
            "page_marker": _stringify(block.get("page_marker")),
            "line_count": int(block.get("line_count") or 0),
            "text_preview": _stringify(block.get("text"))[:240],
        }
        for block in removed_blocks
    ]
    return {
        "filtered_text": kept_text,
        "block_count_before": len(blocks),
        "block_count_after": len(kept_blocks),
        "suspicious_block_count": len(suspicious_blocks),
        "removed_block_count": len(removed_blocks),
        "removed_block_ids": [int(block.get("block_id") or 0) for block in removed_blocks],
        "removed_blocks": removed_preview,
        "llm": llm_result,
    }


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
    enable_llm_basic_cleanup: bool = True,
    basic_cleanup_llm_model: str = _DEFAULT_BASIC_CLEANUP_MODEL,
    basic_cleanup_llm_sdk_backend: str | None = None,
    basic_cleanup_llm_region: str = "cn-beijing",
    enable_llm_structure_resolution: bool = True,
    structure_llm_model: str = _DEFAULT_STRUCTURE_MODEL,
    structure_llm_sdk_backend: str | None = None,
    structure_llm_region: str = "cn-beijing",
    enable_llm_contamination_filter: bool = True,
    contamination_llm_model: str = _DEFAULT_CONTAMINATION_MODEL,
    contamination_llm_sdk_backend: str | None = None,
    contamination_llm_region: str = "cn-beijing",
    config_path: str | Path | None = None,
    api_key_file: str | Path | None = None,
    write_audit: bool = True,
) -> Dict[str, Any]:
    """对阿里百炼解析产物执行后处理并回写。

    Args:
        normalized_structured_path: `normalized.structured.json` 绝对路径。
        reconstructed_markdown_path: `reconstructed_content.md` 绝对路径。
        rewrite_structured: 是否回写 structured 的 `text.full_text`。
        rewrite_markdown: 是否回写 markdown 文件。
        keep_page_markers: 是否保留页标记行。
        enable_llm_basic_cleanup: 是否启用小模型常规清洗阶段。
        basic_cleanup_llm_model: 常规清洗阶段模型。
        basic_cleanup_llm_sdk_backend: 常规清洗阶段后端。
        basic_cleanup_llm_region: 常规清洗阶段地域。
        enable_llm_structure_resolution: 是否启用中模型结构歧义阶段。
        structure_llm_model: 结构歧义阶段模型。
        structure_llm_sdk_backend: 结构歧义阶段后端。
        structure_llm_region: 结构歧义阶段地域。
        enable_llm_contamination_filter: 是否启用 LLM 跨文章污染识别。
        contamination_llm_model: 污染识别所用模型。
        contamination_llm_sdk_backend: 污染识别所用后端。
        contamination_llm_region: 污染识别所用地域。
        config_path: 读取 API Key 的配置路径。
        api_key_file: 读取 API Key 的本地文件路径。
        write_audit: 是否写出审计 JSON。

    Returns:
        Dict[str, Any]: 后处理执行摘要。

    Raises:
        FileNotFoundError: 必需文件不存在时抛出。
        ValueError: structured 内容不合法时抛出。

    Examples:
        >>> # doctest: +SKIP
        >>> postprocess_aliyun_multimodal_parse_outputs(
        ...     normalized_structured_path='/home/ethan/workspace/normalized.structured.json'
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
    source_context = _extract_source_context(structured_payload)
    processing_source = "structured_full_text"

    markdown_file = Path(_stringify(reconstructed_markdown_path)).resolve() if _stringify(reconstructed_markdown_path) else None
    if (not raw_text) and markdown_file and markdown_file.exists() and markdown_file.is_file():
        raw_text = markdown_file.read_text(encoding="utf-8")
        processing_source = "reconstructed_markdown"

    if not raw_text:
        raise ValueError("未找到可处理的正文文本（structured.text.full_text 与 reconstructed_content.md 均为空）")

    processing_text = raw_text
    try:
        from autodokit.tools.review_reading_packet_tools import build_review_reading_packet

        reading_packet = build_review_reading_packet(structured_file)
        clean_body = _stringify(reading_packet.get("clean_body"))
        if len(clean_body) >= 10:
            processing_text = clean_body
            processing_source = "review_packet_clean_body"
    except Exception:
        pass

    contamination = _filter_cross_article_contamination(
        raw_text=processing_text,
        title=source_context.get("title", ""),
        year=source_context.get("year", ""),
        enable_llm=enable_llm_contamination_filter,
        config_path=config_path,
        api_key_file=api_key_file,
        llm_model=contamination_llm_model,
        llm_sdk_backend=contamination_llm_sdk_backend,
        llm_region=contamination_llm_region,
    )

    stage_text = _stringify(contamination.get("filtered_text") or processing_text)
    basic_cleanup_info: Dict[str, Any] = {"status": "skipped", "runtime": {}}
    if enable_llm_basic_cleanup:
        try:
            basic_cleanup_info = _llm_basic_cleanup(
                text=stage_text,
                config_path=config_path,
                api_key_file=api_key_file,
                llm_model=basic_cleanup_llm_model,
                llm_sdk_backend=basic_cleanup_llm_sdk_backend,
                llm_region=basic_cleanup_llm_region,
            )
            stage_text = _stringify(basic_cleanup_info.get("cleaned_text")) or stage_text
        except Exception as exc:
            basic_cleanup_info = {"status": "fallback", "error": str(exc), "runtime": {}}

    structure_resolution_info: Dict[str, Any] = {"status": "skipped", "runtime": {}}
    if enable_llm_structure_resolution:
        try:
            structure_resolution_info = _llm_structure_resolution(
                text=stage_text,
                title=source_context.get("title", ""),
                year=source_context.get("year", ""),
                config_path=config_path,
                api_key_file=api_key_file,
                llm_model=structure_llm_model,
                llm_sdk_backend=structure_llm_sdk_backend,
                llm_region=structure_llm_region,
            )
            stage_text = _stringify(structure_resolution_info.get("cleaned_text")) or stage_text
        except Exception as exc:
            structure_resolution_info = {"status": "fallback", "error": str(exc), "runtime": {}}

    result = clean_aliyun_multimodal_text(stage_text, keep_page_markers=keep_page_markers)
    cleaned_text = _stringify(result.get("cleaned_text"))

    target_markdown = markdown_file or (structured_file.parent / "reconstructed_content.md")
    raw_markdown_path = (structured_file.parent / "reconstructed_content_raw.md").resolve()
    postprocessed_markdown_path = (structured_file.parent / "reconstructed_content_postprocessed.md").resolve()

    if rewrite_markdown:
        target_markdown.parent.mkdir(parents=True, exist_ok=True)
        raw_markdown_path.write_text(raw_text.rstrip() + "\n", encoding="utf-8")
        postprocessed_markdown_path.write_text(cleaned_text + "\n", encoding="utf-8")
        # 兼容既有读取入口：保留 reconstructed_content.md 指向后处理正文。
        target_markdown.write_text(cleaned_text + "\n", encoding="utf-8")
        result["postprocessed_markdown_path"] = str(target_markdown)
        result["raw_markdown_path"] = str(raw_markdown_path)
        result["postprocessed_markdown_alt_path"] = str(postprocessed_markdown_path)
    else:
        result["postprocessed_markdown_path"] = _stringify(markdown_file) if markdown_file else ""
        result["raw_markdown_path"] = ""
        result["postprocessed_markdown_alt_path"] = ""

    if rewrite_structured:
        if not isinstance(text_payload, dict):
            text_payload = {}
        text_payload["raw_full_text"] = raw_text
        text_payload["full_text"] = cleaned_text
        structured_payload["text"] = text_payload
        metadata_payload = structured_payload.get("metadata") if isinstance(structured_payload.get("metadata"), dict) else {}
        metadata_payload["postprocess"] = {
            "applied": True,
            "tool": "aok_aliyun_multimodal_postprocess.v1",
            "processing_input_source": processing_source,
            "contamination_filter_applied": bool(contamination.get("suspicious_block_count") or contamination.get("removed_block_count")),
            "llm_basic_cleanup_status": _stringify(basic_cleanup_info.get("status")),
            "llm_structure_resolution_status": _stringify(structure_resolution_info.get("status")),
            "contamination_llm_status": _stringify((contamination.get("llm") or {}).get("status")),
            "contamination_suspicious_block_count": int(contamination.get("suspicious_block_count") or 0),
            "contamination_removed_block_count": int(contamination.get("removed_block_count") or 0),
            "contamination_removed_block_ids": list(contamination.get("removed_block_ids") or []),
            "removed_noise_lines": int(result.get("removed_noise_lines") or 0),
            "line_count_before": int(result.get("line_count_before") or 0),
            "line_count_after": int(result.get("line_count_after") or 0),
            "raw_char_count": int(result.get("raw_char_count") or 0),
            "cleaned_char_count": int(result.get("cleaned_char_count") or 0),
            "raw_markdown_path": str(raw_markdown_path) if rewrite_markdown else "",
            "postprocessed_markdown_path": str(postprocessed_markdown_path) if rewrite_markdown else "",
            "compat_markdown_path": str(target_markdown) if rewrite_markdown else "",
        }
        structured_payload["metadata"] = metadata_payload
        structured_file.write_text(json.dumps(structured_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    result["normalized_structured_path"] = str(structured_file)
    result["structured_rewritten"] = bool(rewrite_structured)
    result["markdown_rewritten"] = bool(rewrite_markdown)
    result["postprocess_tool"] = "aok_aliyun_multimodal_postprocess.v1"
    result["document_title"] = source_context.get("title", "")
    result["processing_input_source"] = processing_source
    result["contamination_filter_applied"] = bool(contamination.get("suspicious_block_count") or contamination.get("removed_block_count"))
    result["contamination_suspicious_block_count"] = int(contamination.get("suspicious_block_count") or 0)
    result["contamination_removed_block_count"] = int(contamination.get("removed_block_count") or 0)
    result["contamination_removed_block_ids"] = list(contamination.get("removed_block_ids") or [])
    result["contamination_llm_status"] = _stringify((contamination.get("llm") or {}).get("status"))
    result["llm_basic_cleanup_status"] = _stringify(basic_cleanup_info.get("status"))
    result["llm_structure_resolution_status"] = _stringify(structure_resolution_info.get("status"))
    result["llm_basic_cleanup_model"] = _stringify((basic_cleanup_info.get("runtime") or {}).get("selected_model"))
    result["llm_structure_model"] = _stringify((structure_resolution_info.get("runtime") or {}).get("selected_model"))

    audit_path = structured_file.parent / "postprocess_audit.json"
    audit_payload = {
        "postprocess_tool": result["postprocess_tool"],
        "normalized_structured_path": str(structured_file),
        "reconstructed_markdown_path": result.get("postprocessed_markdown_path", ""),
        "reconstructed_markdown_raw_path": result.get("raw_markdown_path", ""),
        "reconstructed_markdown_postprocessed_path": result.get("postprocessed_markdown_alt_path", ""),
        "document_context": source_context,
        "processing_input_source": processing_source,
        "cleanup": {
            "removed_noise_lines": int(result.get("removed_noise_lines") or 0),
            "raw_char_count": int(result.get("raw_char_count") or 0),
            "cleaned_char_count": int(result.get("cleaned_char_count") or 0),
            "line_count_before": int(result.get("line_count_before") or 0),
            "line_count_after": int(result.get("line_count_after") or 0),
        },
        "contamination": contamination,
        "llm_basic_cleanup": basic_cleanup_info,
        "llm_structure_resolution": structure_resolution_info,
    }
    if write_audit:
        audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        result["postprocess_audit_path"] = str(audit_path)
    else:
        result["postprocess_audit_path"] = ""
    return result


__all__ = [
    "clean_aliyun_multimodal_text",
    "postprocess_aliyun_multimodal_parse_outputs",
]
