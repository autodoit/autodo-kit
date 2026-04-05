"""综述研读与研究脉络工具。

本模块把 A06 综述研读与研究地图生成中可复用的逻辑下沉到 tools：

1. 从附件提取综述全文与参考文献；
2. 切分句子并抽取研究问题、方法、结论、未来方向；
3. 基于多篇综述生成共识、争议、未来方向与阅读清单表。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pandas as pd

from autodokit.tools.atomic.log_aok import append_aok_log_event, resolve_aok_log_db_path
from autodokit.tools.llm_clients import AliyunLLMClient, load_aliyun_llm_config
from autodokit.tools.llm_parsing import parse_json_object_from_text
from autodokit.tools.pdf_structured_data_tools import (
    extract_reference_lines_from_structured_data,
    load_structured_data,
)
from autodokit.tools.reference_citation_tools import extract_reference_lines_from_attachment


DEFAULT_TOPIC = "未指定研究主题"

DEFAULT_SENTENCE_GROUP_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "research_problem": ("本文", "文章", "综述", "梳理", "总结", "评述", "探究", "研究"),
    "research_method": ("梳理", "总结", "评述", "分析", "模型", "基于", "角度", "文献"),
    "core_findings": ("影响", "作用", "机制", "路径", "关系", "表明", "发现", "结果"),
    "future_directions": ("建议", "需要", "防范", "提高", "稳定", "至关重要", "应当", "未来"),
}

DEFAULT_CONSENSUS_THEME_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("核心对象关联", ("影响", "关系", "作用", "结果")),
    ("关键传导机制", ("机制", "路径", "传导", "中介")),
    ("治理与响应含义", ("防范", "治理", "应对", "建议")),
)

TOPIC_ANALYSIS_NOTE_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "trajectory_seed.md": {
        "note_label": "研究脉络",
        "goal": "围绕研究主题，归纳多篇综述的问题意识演进、机制主线变化和研究焦点转向。",
        "focus": ["时间演进", "问题意识", "机制主线", "与当前课题的衔接"],
    },
    "core_findings.md": {
        "note_label": "核心成果",
        "goal": "围绕研究主题，提炼已经被多篇综述稳定支持的关键结论。",
        "focus": ["稳定结论", "关键变量", "传导路径", "结论边界"],
    },
    "consensus_notes.md": {
        "note_label": "共识点",
        "goal": "围绕研究主题，筛出跨综述可交叉支持的共识判断。",
        "focus": ["一致性判断", "支撑来源", "适用边界", "对当前课题的作用"],
    },
    "controversy_notes.md": {
        "note_label": "争议点",
        "goal": "围绕研究主题，识别真实争议而不是泛泛差异，并解释争议来源。",
        "focus": ["争议命题", "分歧来源", "可能解释", "仍待检验的问题"],
    },
    "future_directions_notes.md": {
        "note_label": "未来方向",
        "goal": "围绕研究主题，把综述中的后续方向改写成真正有研究用途的后续阅读与研究建议。",
        "focus": ["后续阅读", "机制补强", "识别深化", "变量与数据扩展"],
    },
    "knowledge_framework.md": {
        "note_label": "知识框架",
        "goal": "围绕研究主题，建立核心对象、作用机制、结果变量、边界条件和政策响应之间的结构关系。",
        "focus": ["核心对象", "机制", "结果变量", "边界条件", "政策含义"],
    },
    "innovation_seed.md": {
        "note_label": "创新点",
        "goal": "围绕研究主题，把综述暴露的机制空白、证据边界和识别不足转化为可研究的创新切口。",
        "focus": ["研究空白", "机制空白", "识别策略", "可执行创新点"],
    },
}

NOISE_PATTERNS: Tuple[str, ...] = (
    r"REAL\s+ESTATE\s+ECONOMY",
    r"中国知网\s+https?://www\.cnki\.net",
    r"中国市场\s+\d{4}\s+年第\d+期.*",
    r"管理方略\s*\|.*",
    r"前沿理论.*",
    r"责任编辑/.*",
    r"School of .*?China\)",
    r"\bAbstract\b.*",
    r"\d{4}\s*年第\s*\d+\s*期\s*总第\s*\d+\s*期",
)

CONSENSUS_COLUMNS: List[str] = ["consensus_uid", "topic", "finding", "evidence_notes", "status"]
CONTROVERSY_COLUMNS: List[str] = ["controversy_uid", "topic", "controversy", "evidence_notes", "status"]
FUTURE_COLUMNS: List[str] = ["direction_uid", "topic", "direction", "source_notes", "priority"]
MUST_READ_COLUMNS: List[str] = ["uid_literature", "cite_key", "title", "reason", "status"]
GENERAL_READING_COLUMNS: List[str] = ["uid_literature", "cite_key", "title", "source_review", "status"]


def _normalize_bullet_lines(values: Any, *, limit: int = 8) -> List[str]:
    lines: List[str] = []
    if isinstance(values, list):
        candidates = values
    elif values is None:
        candidates = []
    else:
        candidates = [values]

    for item in candidates:
        text = sanitize_note_sentence(_stringify(item))
        if not text:
            continue
        if text.startswith("- "):
            lines.append(text)
        else:
            lines.append(f"- {text}")
        if len(lines) >= max(limit, 1):
            break
    return lines


def _topic_analysis_digest_lines(review_states: Sequence[Dict[str, Any]], *, max_items_per_section: int = 2) -> List[str]:
    lines: List[str] = []
    for state in review_states:
        cite_key = _stringify(state.get("cite_key"))
        title = _stringify(state.get("title")) or cite_key
        year = _stringify(state.get("year")) or "未知年份"
        lines.append(f"文献：{title} | cite_key={cite_key} | year={year}")
        for section_name, key in (
            ("研究问题", "research_problem"),
            ("研究方法", "research_method"),
            ("核心发现", "core_findings"),
            ("未来方向", "future_directions"),
            ("研究脉络", "trajectory_points"),
            ("知识框架", "knowledge_framework_points"),
        ):
            sentence_objs = list(state.get(key) or [])[: max_items_per_section]
            if not sentence_objs:
                continue
            lines.append(f"- {section_name}：")
            for item in sentence_objs:
                sentence = sanitize_note_sentence(_stringify(item.get("sentence")))
                if sentence:
                    lines.append(f"  - {sentence}")
        lines.append("")
    return lines


def _build_topic_analysis_writer_prompt(
    *,
    note_name: str,
    topic: str,
    provide_research_topic: bool,
    review_states: Sequence[Dict[str, Any]],
    feedback_lines: Sequence[str],
    previous_draft_lines: Sequence[str],
    off_topic_blocklist: Sequence[str],
) -> str:
    requirement = TOPIC_ANALYSIS_NOTE_REQUIREMENTS.get(
        note_name,
        {
            "note_label": note_name,
            "goal": "围绕研究主题撰写专题分析笔记。",
            "focus": ["主题对齐", "证据依托", "分析深度"],
        },
    )
    if provide_research_topic and _stringify(topic):
        prompt_lines = [
            "请你作为学术研究助理，基于多篇单篇综述标准笔记，为当前研究主题撰写专题分析笔记摘要。",
            f"研究主题：{topic}",
            f"分析笔记类型：{_stringify(requirement.get('note_label'))}",
            f"本轮任务目标：{_stringify(requirement.get('goal'))}",
            "写作要求：",
            "1. 只围绕当前研究主题写，不要泛化到无关的宏观话题。",
            "2. 只使用输入笔记中已经出现的证据与判断，不要编造。",
            "3. 若发现输入中有明显无关、疑似串文或污染的内容，必须主动忽略。",
            "4. 输出必须体现比较、归纳、抽象，不要只是原句改写。",
            "5. 每一条都应是后续研究可继续使用的判断。",
            f"6. 特别关注：{'、'.join([_stringify(item) for item in requirement.get('focus') or []])}",
            "7. 输出只返回 JSON 对象，不要返回额外解释。",
            '8. JSON 格式必须为：{"summary_lines": ["- ..."], "self_check": ["..."], "ignored_signals": ["..."]}',
        ]
    else:
        prompt_lines = [
            "请你作为学术研究助理，基于多篇单篇综述标准笔记，撰写综合分析笔记摘要。",
            "当前模式：未提供研究主题，请只围绕输入综述做跨文献综合，不要自行假设外部课题。",
            f"分析笔记类型：{_stringify(requirement.get('note_label'))}",
            f"本轮任务目标：{_stringify(requirement.get('goal'))}",
            "写作要求：",
            "1. 当前没有提供研究主题，不要伪造一个主题，也不要把分析强行套到特定对象上。",
            "2. 只使用输入笔记中已经出现的证据与判断，不要编造。",
            "3. 若发现输入中有明显无关、疑似串文或污染的内容，必须主动忽略。",
            "4. 输出必须体现比较、归纳、抽象，不要只是原句改写。",
            "5. 每一条都应是后续研究可继续使用的判断。",
            f"6. 特别关注：{'、'.join([_stringify(item) for item in requirement.get('focus') or []])}",
            "7. 输出只返回 JSON 对象，不要返回额外解释。",
            '8. JSON 格式必须为：{"summary_lines": ["- ..."], "self_check": ["..."], "ignored_signals": ["..."]}',
        ]
    if off_topic_blocklist:
        prompt_lines.append(f"9. 对以下明显偏题信号保持严格排除：{'、'.join([_stringify(item) for item in off_topic_blocklist if _stringify(item)])}")
    if previous_draft_lines:
        prompt_lines.extend([
            "上一轮草稿：",
            *previous_draft_lines,
        ])
    if feedback_lines:
        prompt_lines.extend([
            "上一轮评审意见：",
            *[f"- {_stringify(item)}" for item in feedback_lines if _stringify(item)],
        ])
    prompt_lines.extend([
        "输入笔记摘要：",
        *_topic_analysis_digest_lines(review_states),
    ])
    return "\n".join(prompt_lines)


def _build_topic_analysis_review_prompt(
    *,
    note_name: str,
    topic: str,
    provide_research_topic: bool,
    draft_lines: Sequence[str],
) -> str:
    requirement = TOPIC_ANALYSIS_NOTE_REQUIREMENTS.get(note_name, {})
    if provide_research_topic and _stringify(topic):
        prompt_lines = [
            "请你作为导师，对下面这份综合分析笔记摘要打分并给出可执行评语。",
            f"研究主题：{topic}",
            f"分析笔记类型：{_stringify(requirement.get('note_label') or note_name)}",
            "评分维度：研究主题对齐度、证据依托度、分析深度、机制相关性、创新转化度、去污染能力、表达质量。",
            "判分要求：",
            "1. 如果内容偏题、空泛、只是综述原句改写、存在明显串文污染，必须降分。",
            "2. 如果已经围绕主题做出清楚、有判断力的综合归纳，可以高分。",
            "3. 评分采用 0-100 分。",
            "4. 输出只返回 JSON 对象。",
            '5. JSON 格式必须为：{"score": 0, "passed": false, "strengths": ["..."], "issues": ["..."], "revision_instructions": ["..."]}',
            "待评审摘要：",
            *draft_lines,
        ]
    else:
        prompt_lines = [
            "请你作为导师，对下面这份综合分析笔记摘要打分并给出可执行评语。",
            "当前模式：未提供研究主题，请判断其是否忠实覆盖输入综述并形成稳定的跨文献综合。",
            f"分析笔记类型：{_stringify(requirement.get('note_label') or note_name)}",
            "评分维度：证据依托度、分析深度、机制相关性、创新转化度、去污染能力、表达质量。",
            "判分要求：",
            "1. 如果内容空泛、只是综述原句改写、存在明显串文污染，必须降分。",
            "2. 如果已经基于输入材料做出清楚、有判断力的综合归纳，可以高分。",
            "3. 评分采用 0-100 分。",
            "4. 输出只返回 JSON 对象。",
            '5. JSON 格式必须为：{"score": 0, "passed": false, "strengths": ["..."], "issues": ["..."], "revision_instructions": ["..."]}',
            "待评审摘要：",
            *draft_lines,
        ]
    return "\n".join(prompt_lines)


def _parse_topic_analysis_review(parsed_obj: Dict[str, Any], *, min_score: int) -> Dict[str, Any]:
    raw_score = _stringify(parsed_obj.get("score")) or "0"
    try:
        score = int(float(raw_score))
    except Exception:
        score = 0
    score = max(0, min(100, score))
    passed = bool(parsed_obj.get("passed", score >= min_score))
    strengths = [_stringify(item) for item in parsed_obj.get("strengths") or [] if _stringify(item)]
    issues = [_stringify(item) for item in parsed_obj.get("issues") or [] if _stringify(item)]
    revision_instructions = [
        _stringify(item) for item in parsed_obj.get("revision_instructions") or [] if _stringify(item)
    ]
    return {
        "score": score,
        "passed": passed,
        "strengths": strengths,
        "issues": issues,
        "revision_instructions": revision_instructions,
    }


def synthesize_topic_analysis_note(
    review_states: Sequence[Dict[str, Any]],
    *,
    note_name: str,
    topic: str,
    provide_research_topic: bool = True,
    workspace_root: str | Path,
    global_config_path: str | Path | None = None,
    api_key_file: str | Path | None = None,
    writer_model: str | None = None,
    reviewer_model: str | None = None,
    min_score: int = 88,
    max_rounds: int = 2,
    off_topic_blocklist: Sequence[str] | None = None,
    print_to_stdout: bool = False,
) -> Dict[str, Any]:
    """为综合分析笔记执行写作-评审-修订循环。"""

    if not review_states:
        return {
            "summary_lines": [],
            "review_result": {"score": 0, "passed": False, "strengths": [], "issues": ["无可用综述输入"], "revision_instructions": []},
            "round_count": 0,
            "writer_model": _stringify(writer_model),
            "reviewer_model": _stringify(reviewer_model),
            "used_llm": False,
        }

    workspace_root_path = Path(workspace_root)
    topic_text = _stringify(topic) if provide_research_topic else ""
    analysis_mode = "topic_guided" if topic_text else "topic_agnostic"
    resolved_min_score = max(0, min(100, int(min_score or 0)))
    resolved_max_rounds = max(1, int(max_rounds or 1))
    blocklist = [_stringify(item) for item in off_topic_blocklist or [] if _stringify(item)]
    writer_model_text = _stringify(writer_model) or "qwen3-max"
    reviewer_model_text = _stringify(reviewer_model) or writer_model_text
    log_db_path = resolve_aok_log_db_path(
        workspace_root_path,
        config_path=Path(global_config_path) if global_config_path else None,
    )

    review_result = {"score": 0, "passed": False, "strengths": [], "issues": [], "revision_instructions": []}
    summary_lines: List[str] = []
    previous_draft_lines: List[str] = []
    feedback_lines: List[str] = []
    executed_round_count = 0
    writer_client = None
    reviewer_client = None

    try:
        writer_cfg = load_aliyun_llm_config(
            model=writer_model_text,
            api_key_file=_stringify(api_key_file) or None,
            config_path=Path(global_config_path) if global_config_path else None,
            affair_name="a070_topic_analysis_writer",
            route_hints={
                "task_type": "reasoning",
                "budget_tier": "premium",
                "input_chars": len("\n".join(_topic_analysis_digest_lines(review_states))),
                "analysis_mode": analysis_mode,
            },
        )
        reviewer_cfg = load_aliyun_llm_config(
            model=reviewer_model_text,
            api_key_file=_stringify(api_key_file) or None,
            config_path=Path(global_config_path) if global_config_path else None,
            affair_name="a070_topic_analysis_reviewer",
            route_hints={
                "task_type": "reasoning",
                "budget_tier": "premium",
                "input_chars": len("\n".join(_topic_analysis_digest_lines(review_states))),
                "analysis_mode": f"{analysis_mode}_review",
            },
        )
        writer_client = AliyunLLMClient(writer_cfg)
        reviewer_client = AliyunLLMClient(reviewer_cfg)

        for round_index in range(1, resolved_max_rounds + 1):
            executed_round_count = round_index
            writer_prompt = _build_topic_analysis_writer_prompt(
                note_name=note_name,
                topic=topic_text,
                provide_research_topic=bool(topic_text),
                review_states=review_states,
                feedback_lines=feedback_lines,
                previous_draft_lines=previous_draft_lines,
                off_topic_blocklist=blocklist,
            )
            writer_output = writer_client.generate_text(
                prompt=writer_prompt,
                system=(
                    "你是学术研究写作助手，必须围绕当前研究主题输出结构化 JSON，不得偏题。"
                    if topic_text
                    else "你是学术研究写作助手，必须忠实基于输入综述输出结构化 JSON，不得擅自假设外部主题。"
                ),
                temperature=0.2,
                max_tokens=4096,
            )
            writer_parsed, _ = parse_json_object_from_text(writer_output)
            summary_lines = _normalize_bullet_lines(writer_parsed.get("summary_lines"), limit=8)
            if not summary_lines:
                summary_lines = _normalize_bullet_lines(writer_parsed.get("self_check"), limit=6)
            if not summary_lines:
                summary_lines = ["- 当前未形成稳定的综合分析摘要，需要人工复核。"]

            review_prompt = _build_topic_analysis_review_prompt(
                note_name=note_name,
                topic=topic_text,
                provide_research_topic=bool(topic_text),
                draft_lines=summary_lines,
            )
            review_output = reviewer_client.generate_text(
                prompt=review_prompt,
                system=(
                    "你是严格的学术导师，只输出 JSON，必须对主题偏离、证据不足和分析空泛严厉扣分。"
                    if topic_text
                    else "你是严格的学术导师，只输出 JSON，必须对证据不足、分析空泛和擅自假设外部主题严厉扣分。"
                ),
                temperature=0.1,
                max_tokens=2048,
            )
            review_parsed, _ = parse_json_object_from_text(review_output)
            review_result = _parse_topic_analysis_review(review_parsed, min_score=resolved_min_score)
            previous_draft_lines = list(summary_lines)
            feedback_lines = list(review_result.get("revision_instructions") or [])
            if review_result["passed"] or review_result["score"] >= resolved_min_score:
                break
    except Exception as exc:
        review_result = {
            "score": 0,
            "passed": False,
            "strengths": [],
            "issues": [f"主题化分析写作或评审失败：{exc}"],
            "revision_instructions": [],
        }
        summary_lines = []

    payload = {
        "note_name": note_name,
        "topic": topic_text,
        "provide_research_topic": bool(topic_text),
        "analysis_mode": analysis_mode,
        "round_count": executed_round_count,
        "score": int(review_result.get("score") or 0),
        "passed": bool(review_result.get("passed")),
        "writer_model": writer_client.model if writer_client else writer_model_text,
        "reviewer_model": reviewer_client.model if reviewer_client else reviewer_model_text,
        "issue_count": len(review_result.get("issues") or []),
    }
    try:
        append_aok_log_event(
            event_type="A070_TOPIC_ANALYSIS_NOTE",
            project_root=workspace_root_path,
            log_db_path=log_db_path,
            handler_kind="llm_native" if summary_lines else "local_script",
            handler_name="synthesize_topic_analysis_note",
            model_name=f"writer={payload['writer_model']};reviewer={payload['reviewer_model']}",
            skill_names=["ar_A070_综述精读与研究脉络梳理_v5"],
            reasoning_summary=(
                "围绕研究主题执行综合分析笔记写作、导师评审与必要修订。"
                if topic_text
                else "在未提供研究主题的模式下执行综合分析笔记写作、导师评审与必要修订。"
            ),
            payload=payload,
        )
    except Exception:
        pass
    if print_to_stdout:
        print(json.dumps({"payload": payload, "review_result": review_result}, ensure_ascii=False, indent=2))
    return {
        "summary_lines": summary_lines,
        "review_result": review_result,
        "round_count": payload["round_count"],
        "writer_model": payload["writer_model"],
        "reviewer_model": payload["reviewer_model"],
        "used_llm": bool(summary_lines),
    }


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_review_full_text(text: str) -> str:
    """规范化综述全文文本。

    Args:
        text: 原始全文文本。

    Returns:
        规整后的全文文本。
    """

    normalized = str(text or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"(?<=[A-Za-z])-\n(?=[A-Za-z])", "", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", normalized)
    normalized = re.sub(r"\n+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def normalize_cite_key_display(cite_key: str) -> str:
    """把 cite_key 规范成适合正文展示的作者年份格式。"""

    value = _stringify(cite_key)
    if not value:
        return "未署名文献"

    parts = value.split("-")
    if len(parts) >= 2 and parts[1].isdigit():
        author = parts[0].replace("_", " ").strip()
        year = parts[1].strip()
        if author:
            return f"{author}（{year}）"
    return value


def build_note_wikilink(cite_key: str, display_text: str | None = None) -> str:
    """生成标准文献笔记 wikilink。"""

    target = _stringify(cite_key)
    if not target:
        return ""
    label = _stringify(display_text) or normalize_cite_key_display(target)
    return f"[[{target}|{label}]]"


def build_pdf_wikilink(pdf_path: str | Path, *, workspace_root: str | Path, display_text: str = "原文 PDF") -> str:
    """生成相对于 workspace vault 的 PDF wikilink。"""

    pdf = Path(pdf_path).expanduser().resolve()
    root = Path(workspace_root).expanduser().resolve()
    try:
        relative = pdf.relative_to(root)
    except ValueError:
        relative = pdf
    target = str(relative).replace("\\", "/")
    return f"[[{target}|{display_text}]]"


def sanitize_note_sentence(text: str) -> str:
    """清洗适合写入 Obsidian 学术笔记的句子。"""

    value = _stringify(text)
    if not value:
        return ""

    cleaned = value.replace("\u3000", " ")
    cleaned = re.sub(r"\[[0-9]+(?:[-,，、][0-9]+)*\]", "", cleaned)
    cleaned = re.sub(r"\bDOI[:：]?\s*[^\s]+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"文献标志码[:：]?\s*[A-Za-z]", "", cleaned)
    cleaned = re.sub(r"文章编号[:：]?\s*[0-9\-]+", "", cleaned)
    cleaned = re.sub(r"关键词[:：].*", "", cleaned)
    cleaned = re.sub(r"收稿日期[:：].*", "", cleaned)
    cleaned = re.sub(r"作者简介[:：].*", "", cleaned)
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"^(?:[-*+•]+|\d+[.)、．])\s*", "", cleaned)
    cleaned = re.sub(r"^[（(]?[一二三四五六七八九十0-9]+[）).、．]\s*", "", cleaned)
    cleaned = re.sub(r"^(?:引言|摘要|结语|结论与展望|参考文献)\s*", "", cleaned)
    cleaned = re.sub(r"^(?:第[一二三四五六七八九十]+部分?|[一二三四五六七八九十]+、|\(?[一二三四五六七八九十]+\))\s*", "", cleaned)
    cleaned = re.sub(r"^\s*[0-9]{1,3}\s+", "", cleaned)
    cleaned = re.sub(r"\b(?:[12]\s?0\s?){2}[0-9]\s*年?第?\d+期?总?第?\d+期?", "", cleaned)
    cleaned = re.sub(r"\s*\[[0-9]+(?:[-,，、][0-9]+)*\]", "", cleaned)
    for pattern in NOISE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    for anchor in ("本文系统梳理", "文章基于", "文章着重", "防范化解系统性金融风险", "房价波动不仅能直观反映"):
        if anchor in cleaned:
            cleaned = cleaned[cleaned.find(anchor):]
            break
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" -:：;；,.，。")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def sentence_to_academic_statement(text: str) -> str:
    """把原始句子转成更适合学术笔记的陈述。"""

    cleaned = sanitize_note_sentence(text)
    if not cleaned:
        return ""
    if not cleaned.endswith(("。", "！", "？", ".")):
        cleaned = f"{cleaned}。"
    return cleaned


def split_review_sentences(text: str) -> List[Dict[str, Any]]:
    """把全文切分为可评分句子。

    Args:
        text: 全文文本。

    Returns:
        句子对象列表。
    """

    normalized = normalize_review_full_text(text)
    if not normalized:
        return []

    parts = re.split(r"(?<=[。！？；!?;])\s*", normalized)
    sentences: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for part in parts:
        sentence = sentence_to_academic_statement(part)
        if len(sentence) < 18:
            continue
        if any(token in sentence for token in ("[Page", "收稿日期", "作者简介", "文献标志码", "文章编号", "DOI", "参考文献", "## References")):
            continue
        if sentence.startswith("#"):
            continue
        if sentence in seen:
            continue
        seen.add(sentence)
        sentences.append({"index": len(sentences) + 1, "sentence": sentence})
    return sentences


def _score_sentence(sentence_obj: Dict[str, Any], keywords: Iterable[str], *, tail_bias: bool = False, total: int = 1) -> float:
    sentence = _stringify(sentence_obj.get("sentence"))
    lowered = sentence.lower()
    position = int(sentence_obj.get("index") or 0)
    score = max(0.0, 120.0 - position)
    for keyword in keywords:
        token = _stringify(keyword)
        if token and token.lower() in lowered:
            score += 24.0
    if any(noise in sentence for noise in ("收稿日期", "基金项目", "作者简介", "关键词")):
        score -= 80.0
    if len(sentence) > 220:
        score -= 10.0
    if tail_bias:
        score += position / max(total, 1) * 30.0
    return score


def pick_review_sentences(
    sentences: Sequence[Dict[str, Any]],
    keywords: Iterable[str],
    *,
    limit: int,
    tail_bias: bool = False,
) -> List[Dict[str, Any]]:
    """按关键词挑选综述关键句。

    Args:
        sentences: 句子对象列表。
        keywords: 关键词集合。
        limit: 返回上限。
        tail_bias: 是否偏向末尾句子。

    Returns:
        选中的句子对象列表。
    """

    total = len(sentences)
    scored = sorted(
        ((
            _score_sentence(item, keywords, tail_bias=tail_bias, total=total),
            item,
        ) for item in sentences),
        key=lambda pair: (pair[0], -int(pair[1].get("index") or 0)),
        reverse=True,
    )
    chosen: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for score, item in scored:
        sentence = _stringify(item.get("sentence"))
        if score <= 0 or sentence in seen:
            continue
        seen.add(sentence)
        chosen.append(item)
        if len(chosen) >= limit:
            break
    return chosen or list(sentences[:limit])


def sentence_line_from_review_state(cite_key: str, sentence_obj: Dict[str, Any]) -> str:
    """把句子对象转成带 cite_key 的回链行。"""

    sentence = sentence_to_academic_statement(_stringify(sentence_obj.get("sentence")))
    if not sentence:
        return ""
    return f"- {sentence} 见 {build_note_wikilink(cite_key)}。"


def _build_review_state_from_payload(
    payload: Dict[str, Any],
    *,
    uid_literature: str,
    cite_key: str,
    title: str,
    year: str = "",
    attachment_path: str,
    attachment_type: str,
    extract_status: str,
    extract_method: str,
    keyword_map: Dict[str, Tuple[str, ...]],
    reference_lines: Sequence[str],
    reference_line_details: Sequence[Dict[str, Any]],
    pending_reason: str = "",
) -> Dict[str, Any]:
    """构造统一的综述 review state。"""

    full_text = _stringify(payload.get("full_text"))
    sentences = split_review_sentences(full_text)
    return {
        "uid_literature": uid_literature,
        "cite_key": cite_key,
        "title": title,
        "year": year,
        "attachment_path": attachment_path,
        "attachment_type": attachment_type,
        "extract_status": extract_status,
        "extract_method": extract_method,
        "full_text": full_text,
        "sentences": sentences,
        "research_problem": pick_review_sentences(sentences, keyword_map["research_problem"], limit=2),
        "research_method": pick_review_sentences(sentences, keyword_map["research_method"], limit=2),
        "core_findings": pick_review_sentences(sentences, keyword_map["core_findings"], limit=3),
        "future_directions": pick_review_sentences(sentences, keyword_map["future_directions"], limit=2, tail_bias=True),
        "reference_lines": list(reference_lines),
        "reference_line_details": list(reference_line_details),
        "pending_reason": pending_reason,
    }


def extract_review_state_from_attachment(
    attachment_path_raw: str,
    *,
    workspace_root: str,
    uid_literature: str,
    cite_key: str,
    title: str,
    year: str = "",
    sentence_group_keywords: Dict[str, Tuple[str, ...]] | None = None,
) -> Dict[str, Any]:
    """从附件构造单篇综述研读状态。

    Args:
        attachment_path_raw: 附件路径。
        workspace_root: 工作区根目录。
        uid_literature: 文献 UID。
        cite_key: 文献 cite_key。
        title: 文献标题。
        year: 年份。
        sentence_group_keywords: 可选关键词配置。

    Returns:
        单篇综述状态字典，包含全文、句子分组与参考文献行。
    """

    keyword_map = sentence_group_keywords or DEFAULT_SENTENCE_GROUP_KEYWORDS
    extraction = extract_reference_lines_from_attachment(
        attachment_path_raw,
        workspace_root=workspace_root,
        print_to_stdout=False,
    )
    return _build_review_state_from_payload(
        {"full_text": extraction.get("full_text")},
        uid_literature=uid_literature,
        cite_key=cite_key,
        title=title,
        year=year,
        attachment_path=_stringify(extraction.get("attachment_path")),
        attachment_type=_stringify(extraction.get("attachment_type")),
        extract_status=_stringify(extraction.get("extract_status")),
        extract_method=_stringify(extraction.get("extract_method")),
        keyword_map=keyword_map,
        reference_lines=list(extraction.get("reference_lines") or []),
        reference_line_details=list(extraction.get("reference_line_details") or []),
        pending_reason=_stringify(extraction.get("pending_reason")),
    )


def extract_review_state_from_structured_file(
    structured_json_path: str,
    *,
    uid_literature: str,
    cite_key: str,
    title: str,
    year: str = "",
    sentence_group_keywords: Dict[str, Tuple[str, ...]] | None = None,
) -> Dict[str, Any]:
    """从结构化 JSON 构造单篇综述研读状态。"""

    keyword_map = sentence_group_keywords or DEFAULT_SENTENCE_GROUP_KEYWORDS
    payload = load_structured_data(Path(structured_json_path))
    extraction = extract_reference_lines_from_structured_data(payload)
    text_payload = payload.get("text") if isinstance(payload.get("text"), dict) else {}
    return _build_review_state_from_payload(
        {"full_text": text_payload.get("full_text")},
        uid_literature=uid_literature,
        cite_key=cite_key,
        title=title,
        year=year,
        attachment_path=_stringify(extraction.get("attachment_path")) or structured_json_path,
        attachment_type="structured_json",
        extract_status=_stringify(extraction.get("extract_status")) or "ok",
        extract_method=_stringify(extraction.get("extract_method")) or "structured_json",
        keyword_map=keyword_map,
        reference_lines=list(extraction.get("reference_lines") or []),
        reference_line_details=list(extraction.get("reference_line_details") or []),
        pending_reason=_stringify(extraction.get("pending_reason")),
    )


def _resolve_global_config_path(workspace_root: Path, config_path: Path | None = None) -> Path | None:
    if config_path is not None and Path(config_path).exists():
        return Path(config_path)
    candidate = workspace_root / "config" / "config.json"
    return candidate if candidate.exists() else None


def _load_global_llm_settings(workspace_root: Path, config_path: Path | None = None) -> Dict[str, Any]:
    resolved = _resolve_global_config_path(workspace_root, config_path=config_path)
    if resolved is None:
        return {}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    llm_cfg = payload.get("llm")
    return dict(llm_cfg) if isinstance(llm_cfg, dict) else {}


def _coerce_sentence_objects(
    original_sentences: Sequence[Dict[str, Any]],
    llm_sentences: Sequence[Any],
) -> List[Dict[str, Any]]:
    chosen: List[Dict[str, Any]] = []
    seen: set[str] = set()
    normalized_originals = [(_stringify(item.get("sentence")), item) for item in original_sentences]
    for raw_item in llm_sentences:
        sentence = _stringify(raw_item)
        if not sentence or sentence in seen:
            continue
        seen.add(sentence)
        matched: Dict[str, Any] | None = None
        for original_sentence, original_obj in normalized_originals:
            if sentence == original_sentence or sentence in original_sentence or original_sentence in sentence:
                matched = {
                    "index": original_obj.get("index") or len(chosen) + 1,
                    "sentence": original_sentence,
                }
                break
        if matched is None:
            matched = {"index": len(chosen) + 1, "sentence": sentence}
        chosen.append(matched)
    return chosen


def refine_review_state_with_llm(
    review_state: Dict[str, Any],
    *,
    workspace_root: str | Path,
    global_config_path: str | Path | None = None,
    api_key_file: str | Path | None = None,
    model: str | None = None,
    max_chars: int = 24000,
    print_to_stdout: bool = False,
) -> Dict[str, Any]:
    """使用单次独立 LLM 请求提炼单篇综述的 review_state。"""

    full_text = normalize_review_full_text(_stringify(review_state.get("full_text")))
    if not full_text:
        return dict(review_state)

    workspace_root_path = Path(workspace_root)
    llm_settings = _load_global_llm_settings(
        workspace_root_path,
        config_path=Path(global_config_path) if global_config_path else None,
    )
    resolved_api_key_file = _stringify(api_key_file) or _stringify(llm_settings.get("aliyun_api_key_file"))
    resolved_model = _stringify(model) or _stringify(llm_settings.get("review_state_model")) or "auto"
    log_db_path = resolve_aok_log_db_path(
        workspace_root_path,
        config_path=Path(global_config_path) if global_config_path else None,
    )
    truncated_text = full_text[: max(int(max_chars or 0), 1000)]
    original_sentences = list(review_state.get("sentences") or split_review_sentences(truncated_text))

    result = dict(review_state)
    result["llm_review_state"] = {
        "enabled": True,
        "parse_method": "original_rule_based",
        "parse_failed": 0,
        "parse_failure_reason": "",
        "model_name": "",
    }

    try:
        llm_config = load_aliyun_llm_config(
            model=resolved_model,
            api_key_file=resolved_api_key_file or None,
            affair_name="review_state_single_document",
            config_path=Path(global_config_path) if global_config_path else None,
            route_hints={
                "task_type": "general",
                "budget_tier": "balanced",
                "input_chars": len(truncated_text),
            },
        )
        client = AliyunLLMClient(llm_config)
        prompt = "\n".join(
            [
                "请基于下面单篇综述/述评/研究进展全文，提炼结构化阅读结果。",
                "只返回 JSON 对象，格式必须为：",
                "{",
                '  "research_problem": ["..."],',
                '  "research_method": ["..."],',
                '  "core_findings": ["..."],',
                '  "future_directions": ["..."]',
                "}",
                "要求：",
                "1. 每个字段返回 1-3 条句子。",
                "2. 尽量复用原文句子，不要编造文中没有的信息。",
                "3. 若某字段没有足够内容，返回空列表。",
                f"标题：{_stringify(review_state.get('title')) or 'unknown'}",
                f"年份：{_stringify(review_state.get('year')) or 'unknown'}",
                f"cite_key：{_stringify(review_state.get('cite_key')) or 'unknown'}",
                "全文：",
                truncated_text,
            ]
        )
        raw_output = client.generate_text(
            prompt=prompt,
            system="你是综述文献精读助手，只输出 JSON。",
            temperature=0.1,
            max_tokens=4096,
        )
        parsed_obj, _debug = parse_json_object_from_text(raw_output)
        for field_name in ["research_problem", "research_method", "core_findings", "future_directions"]:
            llm_sentences = parsed_obj.get(field_name)
            if isinstance(llm_sentences, list):
                result[field_name] = _coerce_sentence_objects(original_sentences, llm_sentences)
        result["sentences"] = original_sentences
        result["llm_review_state"] = {
            "enabled": True,
            "parse_method": "aliyun_llm_single_document",
            "parse_failed": 0,
            "parse_failure_reason": "",
            "model_name": client.model,
        }
    except Exception as exc:
        result["llm_review_state"] = {
            "enabled": True,
            "parse_method": "original_rule_based",
            "parse_failed": 1,
            "parse_failure_reason": str(exc),
            "model_name": resolved_model,
        }

    payload = {
        "cite_key": _stringify(result.get("cite_key")),
        "title": _stringify(result.get("title")),
        "parse_method": _stringify((result.get("llm_review_state") or {}).get("parse_method")),
        "parse_failed": int((result.get("llm_review_state") or {}).get("parse_failed") or 0),
        "parse_failure_reason": _stringify((result.get("llm_review_state") or {}).get("parse_failure_reason")),
        "input_chars": len(truncated_text),
    }
    append_aok_log_event(
        event_type="REVIEW_STATE_SINGLE_DOCUMENT",
        project_root=workspace_root_path,
        log_db_path=log_db_path,
        handler_kind="llm_native" if payload["parse_method"] == "aliyun_llm_single_document" else "local_script",
        handler_name="refine_review_state_with_llm",
        model_name=_stringify((result.get("llm_review_state") or {}).get("model_name")),
        skill_names=["ar_A070_综述精读与研究脉络梳理_v5"],
        reasoning_summary="对单篇综述执行一次独立 LLM 请求，提炼 review_state。",
        payload=payload,
    )
    if print_to_stdout:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return result


def build_review_consensus_rows(
    review_states: Sequence[Dict[str, Any]],
    *,
    theme_defs: Sequence[Tuple[str, Tuple[str, ...]]] | None = None,
) -> pd.DataFrame:
    """基于多篇综述生成共识表。"""

    rows: List[Dict[str, Any]] = []
    current_index = 1
    for topic, keywords in theme_defs or DEFAULT_CONSENSUS_THEME_DEFS:
        matches: List[Tuple[str, Dict[str, Any]]] = []
        for state in review_states:
            source_sentences = state.get("core_findings") or state.get("sentences") or []
            chosen = pick_review_sentences(source_sentences, keywords, limit=1)
            if chosen:
                matches.append((_stringify(state.get("cite_key")), chosen[0]))
        if len({cite_key for cite_key, _ in matches if cite_key}) < 2:
            continue
        rows.append(
            {
                "consensus_uid": f"consensus_{current_index:02d}",
                "topic": topic,
                "finding": topic,
                "evidence_notes": " | ".join(
                    f"{cite_key}#句{_stringify(sentence_obj.get('index'))}:{_stringify(sentence_obj.get('sentence'))}"
                    for cite_key, sentence_obj in matches
                ),
                "status": "validated",
            }
        )
        current_index += 1
    return pd.DataFrame(rows, columns=CONSENSUS_COLUMNS)


def build_review_controversy_rows(review_states: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    """基于多篇综述生成争议表。"""

    rows: List[Dict[str, Any]] = []
    bank_specific: Tuple[str, Dict[str, Any]] | None = None
    broad_scope: Tuple[str, Dict[str, Any]] | None = None
    for state in review_states:
        for sentence_obj in state.get("core_findings") or state.get("sentences") or []:
            sentence = _stringify(sentence_obj.get("sentence"))
            cite_key = _stringify(state.get("cite_key"))
            if bank_specific is None and any(keyword in sentence for keyword in ("风险", "结果", "效应", "影响")):
                bank_specific = (cite_key, sentence_obj)
            if broad_scope is None and any(keyword in sentence for keyword in ("样本", "范围", "情境", "对象", "条件")):
                broad_scope = (cite_key, sentence_obj)
    if bank_specific and broad_scope and bank_specific[0] != broad_scope[0]:
        rows.append(
            {
                "controversy_uid": "controversy_01",
                "topic": "研究范围差异",
                "controversy": "研究范围差异",
                "evidence_notes": (
                    f"{bank_specific[0]}#句{_stringify(bank_specific[1].get('index'))}:{_stringify(bank_specific[1].get('sentence'))}"
                    f" | {broad_scope[0]}#句{_stringify(broad_scope[1].get('index'))}:{_stringify(broad_scope[1].get('sentence'))}"
                ),
                "status": "observed",
            }
        )
    return pd.DataFrame(rows, columns=CONTROVERSY_COLUMNS)


def build_review_future_rows(review_states: Sequence[Dict[str, Any]], *, topic: str = DEFAULT_TOPIC) -> pd.DataFrame:
    """基于多篇综述生成未来方向表。"""

    rows: List[Dict[str, Any]] = []
    for review_index, state in enumerate(review_states, start=1):
        for sentence_obj in state.get("future_directions") or []:
            rows.append(
                {
                    "direction_uid": f"direction_{review_index:02d}_{_stringify(sentence_obj.get('index'))}",
                    "topic": topic,
                    "direction": _stringify(sentence_obj.get("sentence")),
                    "source_notes": f"{_stringify(state.get('cite_key'))}#句{_stringify(sentence_obj.get('index'))}",
                    "priority": "high" if review_index <= 2 else "medium",
                }
            )
    return pd.DataFrame(rows, columns=FUTURE_COLUMNS)


def build_review_must_read_originals(
    review_states: Sequence[Dict[str, Any]],
    literature_table: pd.DataFrame,
    mapping_rows: Sequence[Dict[str, Any]],
) -> pd.DataFrame:
    """从引文映射中生成必读原始文献表。"""

    if not mapping_rows:
        return pd.DataFrame(columns=MUST_READ_COLUMNS)

    mapping = pd.DataFrame(mapping_rows).fillna("")
    review_cites = {_stringify(state.get("cite_key")) for state in review_states}
    review_uids = {_stringify(state.get("uid_literature")) for state in review_states}
    filtered = mapping[
        mapping["source_cite_key"].astype(str).isin(review_cites)
        & mapping["matched_uid_literature"].astype(str).ne("")
        & ~mapping["matched_uid_literature"].astype(str).isin(review_uids)
        & mapping["suspicious_mismatch"].astype(str).isin(["", "0"])
        & mapping["parse_failed"].astype(str).isin(["", "0"])
    ].copy()
    if filtered.empty:
        return pd.DataFrame(columns=MUST_READ_COLUMNS)

    lookup = literature_table[[column for column in ["uid_literature", "cite_key", "title"] if column in literature_table.columns]].copy()
    grouped = filtered.groupby(["matched_uid_literature", "matched_cite_key"], as_index=False).agg(source_count=("source_cite_key", "nunique"))
    merged = grouped.merge(lookup, how="left", left_on="matched_uid_literature", right_on="uid_literature")
    merged = merged.sort_values(by=["source_count", "matched_cite_key"], ascending=[False, True]).head(20)

    rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        count = int(float(_stringify(row.get("source_count")) or "0"))
        rows.append(
            {
                "uid_literature": _stringify(row.get("matched_uid_literature")),
                "cite_key": _stringify(row.get("matched_cite_key")),
                "title": _stringify(row.get("title")) or _stringify(row.get("matched_cite_key")),
                "reason": f"被 {count} 篇综述高置信引用",
                "status": "backlog",
            }
        )
    return pd.DataFrame(rows, columns=MUST_READ_COLUMNS)


def build_review_general_reading_list(
    review_states: Sequence[Dict[str, Any]],
    literature_table: pd.DataFrame,
    mapping_rows: Sequence[Dict[str, Any]],
) -> pd.DataFrame:
    """从引文映射中生成泛读文献表。"""

    if not mapping_rows:
        return pd.DataFrame(columns=GENERAL_READING_COLUMNS)

    mapping = pd.DataFrame(mapping_rows).fillna("")
    review_cites = {_stringify(state.get("cite_key")) for state in review_states}
    filtered = mapping[
        mapping["source_cite_key"].astype(str).isin(review_cites)
        & mapping["matched_uid_literature"].astype(str).ne("")
        & mapping["parse_failed"].astype(str).isin(["", "0"])
    ].copy()
    if filtered.empty:
        return pd.DataFrame(columns=GENERAL_READING_COLUMNS)

    lookup = literature_table[[column for column in ["uid_literature", "cite_key", "title"] if column in literature_table.columns]].copy()
    grouped = filtered.groupby(["matched_uid_literature", "matched_cite_key"], as_index=False).agg(
        source_review=("source_cite_key", lambda values: " | ".join(sorted({str(value).strip() for value in values if str(value).strip()})))
    )
    merged = grouped.merge(lookup, how="left", left_on="matched_uid_literature", right_on="uid_literature")
    merged = merged.sort_values(by=["matched_cite_key"], ascending=[True]).head(50)

    rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        rows.append(
            {
                "uid_literature": _stringify(row.get("matched_uid_literature")),
                "cite_key": _stringify(row.get("matched_cite_key")),
                "title": _stringify(row.get("title")) or _stringify(row.get("matched_cite_key")),
                "source_review": _stringify(row.get("source_review")),
                "status": "candidate",
            }
        )
    return pd.DataFrame(rows, columns=GENERAL_READING_COLUMNS)
