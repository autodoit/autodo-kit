"""生成关键词集合事务。

本事务的目标：
- 输入自然语言描述与初始关键词集合，调用大语言模型生成扩展关键词集合（中英文与短语）。
- 支持将关键词按研究领域进行初步分类，生成每个研究领域的关键词集合，并计算领域集合的笛卡尔积组合。
- 将生成结果写入指定输出目录，供后续预筛选或检索使用。

输入（必需）：
- description: 自然语言描述（研究主题/问题/范围）。
- initial_keywords: 初始关键词列表（中文或中英混合）。

输出（必需产物）：
- keyword_set.json: 结构化结果（包含领域划分、各领域关键词集合、笛卡尔积组合等）。
- keyword_set.txt: 扁平关键词列表（每行一个，来自 all_keywords）。
- keyword_pairs.txt: 领域组合串列表（每行一个，例如 "房地产 | 銀行系统性风险" 的关键词组合）。
- keyword_debug.json: 调试信息（LLM 两阶段解析与参考资料统计）。
- keyword_domains.json: 中间结构（按领域聚合关键词与跨领域短语）。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。

Examples:
    >>> from pathlib import Path
    >>> # 注意：Windows/某些 IDE 对中文模块名的静态解析可能不完善，但运行时可正常 import
    >>> from autodokit.affairs import 生成关键词集合 as keyword_set_affair
    >>> keyword_set_affair.execute(Path("workflows/workflow_生成关键词集合/workflow.json"))
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from autodokit.tools.llm_clients import AliyunDashScopeClient, load_aliyun_llm_config
from autodokit.tools.llm_parsing import (
    LLMOutputParseError,
    extract_output_text_from_response_like_blob,
    is_likely_sdk_response_blob,
    parse_json_object_from_text,
    pick_first_list_field,
    truncate_text,
)
from autodokit.tools import load_json_or_py
from autodokit.tools.text_corpus_loader import load_reference_corpus_from_dir


@dataclass
class KeywordSetConfig:
    """关键词集合生成配置。

    Attributes:
        description: 自然语言描述（研究主题/问题/范围）。
        initial_keywords: 初始关键词列表（中文或中英混合）。
        research_domains: 研究领域到种子关键词列表的映射（可选）。
            - 键：领域名称（例如“房地产”“银行系统性风险”）
            - 值：该领域的种子关键词列表
        reference_materials_dir: 参考资料目录（可选，目录内支持 .md/.tex）。
        reference_materials_max_files: 参考资料最多读取文件数（可选）。
        reference_materials_max_chars: 参考资料合并后最多保留字符数（可选）。
        output_dir: 输出目录。
        output_json_name: JSON 输出文件名。
        output_txt_name: str = "keyword_set.txt"扁平关键词。
        output_pairs_name: 关键词组合输出文件名（领域集合笛卡尔积）。
        output_debug_name: 调试信息输出文件名。
        output_domains_name: 领域中间结构输出文件名。
        model: 阿里百炼模型名。
        temperature: 采样温度。
        max_keywords: 扩展关键词数量上限（不含初始关键词，模型侧约束）。
        include_chinese: 是否要求输出中文扩展词。
        include_english: 是否要求输出英文扩展词。
        include_phrases: 是否要求输出短语级关键词。
        num_domains: 研究领域数量（2 表示两个领域交叉；允许 >=2）。
        max_domain_keywords: 每个领域最多保留多少关键词（用于控制组合爆炸）。
        max_pairs: 生成的组合条目上限（用于控制输出大小）。
        dry_run: 是否跳过 LLM 调用（用于快速测试）。
        env_api_key_name: API Key 环境变量名。
        api_key_file: 可选密钥文件路径。
        base_url: 可选自定义 base_url。
        model_route: 模型路由提示（可选）。
        allow_fallback: bool = False  # 是否允许解析失败时退回 seeds（默认 False，避免静默失败）
    """

    description: str
    initial_keywords: List[str]
    research_domains: Optional[Dict[str, List[str]]] = None
    reference_materials_dir: Optional[str] = None  # 参考资料目录（绝对路径）
    reference_materials_max_files: Optional[int] = None  # 最多读取文件数
    reference_materials_max_chars: Optional[int] = None  # 合并后最多字符数
    output_dir: str = ""
    output_json_name: str = "keyword_set.json"
    output_txt_name: str = "keyword_set.txt"
    output_pairs_name: str = "keyword_pairs.txt"
    output_debug_name: str = "keyword_debug.json"
    output_domains_name: str = "keyword_domains.json"
    model: str = "auto"
    temperature: float = 0.2
    max_keywords: int = 60
    include_chinese: bool = True
    include_english: bool = True
    include_phrases: bool = True
    num_domains: int = 2
    max_domain_keywords: int = 40
    max_pairs: int = 2000
    dry_run: bool = False
    env_api_key_name: str = "DASHSCOPE_API_KEY"
    api_key_file: Optional[str] = None
    base_url: Optional[str] = None
    model_route: Optional[Dict[str, Any]] = None
    allow_fallback: bool = False  # 是否允许解析失败时退回 seeds（默认 False，避免静默失败）
    domain_purify_enable: bool = True  # 是否启用领域纯化（降低跨领域词污染）
    domain_purify_margin: float = 1.15  # 领域归属最小优势倍数（越大越严格）
    domain_purify_min_score: float = 1.0  # 关键词最低相关性得分（越大越严格）


def _safe_list(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, list):
        return [str(v).strip() for v in values if str(v).strip()]
    return [str(values).strip()] if str(values).strip() else []


def _resolve_output_filename(raw_value: Any, *, default_name: str) -> str:
    """解析输出文件名配置，仅允许文件名生效。

    规则：
    - 缺失或空字符串时，回退到默认文件名。
    - 若误传入路径（绝对/相对），仅保留最终文件名部分，路径统一由 output_dir 控制。

    Args:
        raw_value: 配置中的文件名字段。
        default_name: 默认文件名。

    Returns:
        可用于 output_dir / <name> 的文件名。
    """

    if raw_value is None:
        return default_name

    raw_text = str(raw_value).strip()
    if not raw_text:
        return default_name

    name = Path(raw_text).name.strip()
    return name or default_name


def _normalize_research_domains(value: Any) -> Optional[Dict[str, List[str]]]:
    """规范化 research_domains 配置。

    Args:
        value: workflow.json 中的 research_domains 字段（期望为 dict）。

    Returns:
        规范化后的 dict 或 None。

    Raises:
        ValueError: research_domains 结构非法。
    """

    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("research_domains 必须为对象（dict）：{领域名: [种子词...]}")

    cleaned: Dict[str, List[str]] = {}
    for k, v in value.items():
        name = str(k).strip()
        if not name:
            continue
        if v is None:
            cleaned[name] = []
            continue
        if isinstance(v, list):
            cleaned[name] = [str(x).strip() for x in v if str(x).strip()]
        else:
            # 兼容用户误传单个字符串
            cleaned[name] = [str(v).strip()] if str(v).strip() else []

    return cleaned or None


def _build_prompt(cfg: KeywordSetConfig) -> str:
    """构造模型提示词。

    Args:
        cfg: 关键词集合生成配置。

    Returns:
        可直接用于 LLM 的提示词。
    """

    include_flags = {
        "include_chinese": cfg.include_chinese,
        "include_english": cfg.include_english,
        "include_phrases": cfg.include_phrases,
    }

    reference_hint = ""
    if cfg.reference_materials_dir:
        reference_dir = Path(cfg.reference_materials_dir)
        corpus = load_reference_corpus_from_dir(
            reference_dir,
            max_files=cfg.reference_materials_max_files,
            max_chars=cfg.reference_materials_max_chars,
        )
        if corpus.text:
            # 关键逻辑说明：把参考资料作为“可引用背景”放在描述之前，减少模型忽略概率。
            reference_hint = (
                "\n参考资料（可作为背景知识引用，不要逐字复述，重点提炼检索术语与同义表达）：\n"
                + corpus.text
                + "\n"
            )

    research_domains_hint = ""
    if cfg.research_domains:
        # 关键逻辑说明：当用户显式提供领域结构时，要求模型按该结构输出 domains，避免领域漂移。
        research_domains_hint = (
            "\n补充约束（必须遵守）：\n"
            "- 你必须严格使用 research_domains 提供的领域名称作为 domains[*].domain_name。\n"
            "- domains 的数量必须与 research_domains 的键数量一致，不要新增或删减领域。\n"
            "- 每个领域的扩展应围绕该领域的 seed_keywords，补充中英文与短语。\n"
            f"research_domains = {json.dumps(cfg.research_domains, ensure_ascii=False)}\n"
        )

    return (
        "你是一个学术检索关键词扩展与领域划分助手。\n"
        "任务：根据输入的研究主题描述与初始关键词，生成按研究领域分组的关键词集合，并提供中英文与短语。\n\n"
        "输出必须是一个合法 JSON 对象，只输出 JSON，不要解释文字。\n"
        "JSON 格式要求如下（字段允许为空数组，但必须存在）：\n"
        "{\n"
        "  \"domains\": [\n"
        "    {\n"
        "      \"domain_name\": \"领域名称（中文为主）\",\n"
        "      \"domain_description\": \"一句话描述该领域\",\n"
        "      \"keywords\": [\"该领域关键词（中英可混合）\"],\n"
        "      \"chinese_keywords\": [\"中文关键词\"],\n"
        "      \"english_keywords\": [\"英文关键词\"],\n"
        "      \"keyword_phrases\": [\"短语关键词\"]\n"
        "    }\n"
        "  ],\n"
        "  \"cross_domain_phrases\": [\"跨领域组合短语（可选）\"]\n"
        "}\n\n"
        "硬性约束：\n"
        f"- 总扩展关键词规模不超过 {cfg.max_keywords}（不含初始关键词）。\n"
        f"- 输出语言开关：{json.dumps(include_flags, ensure_ascii=False)}\n"
        "- 关键词尽量用于学术检索（Web of Science / Google Scholar / CNKI），避免口语化。\n"
        + research_domains_hint
        + "\n"
        + reference_hint
        + f"自然语言描述：{cfg.description}\n"
        + f"初始关键词：{json.dumps(cfg.initial_keywords, ensure_ascii=False)}\n"
    )


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出中提取 JSON。"""

    if not text:
        return None

    # 关键逻辑说明：先尝试直接解析；失败再从文本中截取最外层 JSON。
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= 0 and end > start:
        candidate = text[start: end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            return None
    return None


def _normalize_keywords(values: List[str]) -> List[str]:
    """去重并清理关键词列表。"""

    seen = set()
    cleaned: List[str] = []
    for v in values:
        s = str(v).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(s)
    return cleaned


def _normalize_text_for_match(text: str) -> str:
    """规范化文本，便于进行中英文混合匹配。

    Args:
        text: 原始文本。

    Returns:
        规范化后的小写文本。
    """

    s = str(text or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _extract_match_units(text: str) -> List[str]:
    """从文本中抽取通用匹配单元（中英文）。

    说明：
    - 不依赖任何业务领域词典，确保事务通用；
    - 英文按词元提取，中文按连续汉字段提取，并保留长度>=2的片段。

    Args:
        text: 输入文本。

    Returns:
        去重后的匹配单元列表。
    """

    s = _normalize_text_for_match(text)
    if not s:
        return []

    units: Set[str] = set()

    # 英文词元（长度>=2）
    for token in re.findall(r"[a-z][a-z0-9\-]{1,}", s):
        units.add(token)

    # 中文连续片段（长度>=2）
    for seg in re.findall(r"[\u4e00-\u9fff]{2,}", s):
        units.add(seg)
        # 兼容较长中文短语：加入 2~4 字滑动子串
        if len(seg) >= 4:
            max_n = min(4, len(seg))
            for n in range(2, max_n + 1):
                for i in range(0, len(seg) - n + 1):
                    units.add(seg[i:i + n])

    # 保留原始规范化短语（对多词短语有帮助）
    units.add(s)

    return _normalize_keywords(list(units))


def _collect_domain_anchors(domain_name: str, seeds: List[str]) -> List[str]:
    """构建某领域的匹配锚点（领域名词根 + 种子词）。

    Args:
        domain_name: 领域名称。
        seeds: 该领域种子词。

    Returns:
        去重后的锚点词列表。
    """

    anchors: List[str] = []
    anchors.extend(_extract_match_units(domain_name))
    for seed in (seeds or []):
        anchors.extend(_extract_match_units(seed))
    return _normalize_keywords([x for x in anchors if x])


def _score_term_against_anchors(term: str, anchors: List[str]) -> float:
    """计算关键词相对某领域锚点的相关性得分。

    计分规则（轻量、可解释）：
    - 子串命中：term 包含 anchor 或 anchor 包含 term，按词长加权；
    - 词元命中：英文词元与锚点词元交集给予额外分。

    Args:
        term: 待判定关键词。
        anchors: 领域锚点词列表。

    Returns:
        相关性得分（非负）。
    """

    t = _normalize_text_for_match(term)
    if not t:
        return 0.0

    score = 0.0
    t_tokens = set(re.findall(r"[a-z]+", t))

    for a in anchors:
        if not a:
            continue
        if a in t or t in a:
            score += min(len(a), 12) / 6.0

        a_tokens = set(re.findall(r"[a-z]+", a))
        if t_tokens and a_tokens:
            overlap = len(t_tokens & a_tokens)
            if overlap > 0:
                score += 0.5 * overlap

    return score


def _purify_domains_keywords(
        *,
        domains_map: Dict[str, List[str]],
        research_domains: Dict[str, List[str]] | None,
        margin: float,
        min_score: float,
) -> Tuple[Dict[str, List[str]], Dict[str, Any]]:
    """对按领域生成的关键词进行纯化，降低跨领域污染。

    核心策略：
    1) 先按“领域锚点得分”给每个关键词做归属判定；
    2) 仅保留对本领域有足够优势的关键词；
    3) 对跨领域重复词，按最高得分仅保留到一个领域；
    4) 种子词强制保留，避免过度清洗。

    Args:
        domains_map: 原始领域关键词映射。
        research_domains: 领域种子词映射。
        margin: 本领域得分相对次高领域的最小优势倍数。
        min_score: 本领域最小得分阈值。

    Returns:
        (纯化后的 domains_map, 调试信息)
    """

    domain_names = [d for d in domains_map.keys() if str(d).strip()]
    if len(domain_names) < 2:
        return domains_map, {"enabled": True, "note": "领域数量不足，跳过纯化"}

    seeds_map: Dict[str, List[str]] = {}
    for d in domain_names:
        seeds_map[d] = _normalize_keywords([str(x) for x in ((research_domains or {}).get(d) or [])])

    anchors_map: Dict[str, List[str]] = {
        d: _collect_domain_anchors(d, seeds_map.get(d, [])) for d in domain_names
    }

    term_best_domain: Dict[str, Tuple[str, float]] = {}
    drop_stats: Dict[str, int] = {d: 0 for d in domain_names}
    keep_stats: Dict[str, int] = {d: 0 for d in domain_names}

    purified: Dict[str, List[str]] = {d: [] for d in domain_names}

    for d in domain_names:
        kws = _normalize_keywords([str(x) for x in (domains_map.get(d) or [])])
        for kw in kws:
            kw_norm = _normalize_text_for_match(kw)
            scores = {dn: _score_term_against_anchors(kw, anchors_map[dn]) for dn in domain_names}

            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            best_domain, best_score = ranked[0]
            second_score = ranked[1][1] if len(ranked) > 1 else 0.0
            own_score = scores.get(d, 0.0)

            is_seed = kw in seeds_map.get(d, [])

            keep_here = False
            if is_seed:
                keep_here = True
            elif own_score >= float(min_score):
                denom = second_score if second_score > 1e-9 else 1e-9
                if d == best_domain and (own_score / denom) >= float(margin):
                    keep_here = True

            if keep_here:
                keep_stats[d] += 1
                prev = term_best_domain.get(kw_norm)
                if prev is None or own_score > prev[1]:
                    term_best_domain[kw_norm] = (d, own_score)
            else:
                drop_stats[d] += 1

    # 按“全局最佳归属”重建，消除跨领域重复词。
    kw_lookup: Dict[str, str] = {}
    for d in domain_names:
        for kw in _normalize_keywords([str(x) for x in (domains_map.get(d) or [])]):
            kw_lookup[_normalize_text_for_match(kw)] = kw

    for kw_norm, (d, _score) in term_best_domain.items():
        original = kw_lookup.get(kw_norm, kw_norm)
        purified[d].append(original)

    # 种子词兜底保留
    for d in domain_names:
        purified[d] = _normalize_keywords([*purified[d], *seeds_map.get(d, [])])

    debug = {
        "enabled": True,
        "margin": margin,
        "min_score": min_score,
        "keep_stats": keep_stats,
        "drop_stats": drop_stats,
        "final_counts": {d: len(purified[d]) for d in domain_names},
    }
    return purified, debug


def _safe_str_list(x: Any) -> List[str]:
    """将任意值安全转换为字符串列表（用于解析模型返回字段）。"""

    if x is None:
        return []
    if isinstance(x, list):
        return _normalize_keywords([str(v) for v in x])
    if isinstance(x, str):
        s = x.strip()
        return [s] if s else []
    return [str(x).strip()] if str(x).strip() else []


def _extract_keywords_from_obj(obj: Dict[str, Any], *, candidates: List[str]) -> List[str]:
    """从模型解析出的 JSON 对象中提取关键词列表。

    为什么需要这个函数：
    - 实际大模型输出有时会把键名写成 keywords / items / terms 等，而不是严格按提示词。
    - 为了减少“模型已输出但解析不到”的误判，这里做一层容错。

    Args:
        obj: 解析后的 JSON 对象。
        candidates: 候选键名列表，按优先级顺序。

    Returns:
        提取到的关键词列表（已去重）。
    """

    for k in candidates:
        if k in obj:
            arr = _safe_str_list(obj.get(k))
            if arr:
                return arr
    return []


def _truncate_text(text: str, *, limit: int = 1200) -> str:
    """截断文本用于调试落盘，避免 keyword_set.json 过大。

    Args:
        text: 原始文本。
        limit: 最大保留字符数。

    Returns:
        截断后的文本。
    """

    return truncate_text(text, limit=limit)


def _extract_json_obj(text: str) -> Dict[str, Any]:
    """从模型输出中提取 JSON 对象（失败则返回空 dict）。

    注意：该函数保留为“向后兼容”的薄封装。
    新代码建议直接使用 llm_parsing.parse_json_object_from_text。
    """

    try:
        obj, _ = parse_json_object_from_text(text, allow_outermost_extraction=True)
        return obj
    except Exception:
        return {}


def _fallback_parse_keywords_from_text(text: str) -> List[str]:
    """当模型未输出可解析 JSON 时，尝试从纯文本中提取关键词。

    说明：
    - 该函数在本事务中仅作为兜底；核心解析应优先走 JSON。
    - 为复用与一致性，优先使用 llm_parsing 的 response blob 抽取能力。

    Args:
        text: 原始输出文本。

    Returns:
        关键词列表（可能为空）。
    """

    s = (text or "").strip()
    if not s:
        return []

    if is_likely_sdk_response_blob(s):
        extracted = extract_output_text_from_response_like_blob(s)
        if extracted:
            s = extracted

    # 仍然沿用本地的“保守提取”策略
    out: List[str] = []
    for line in s.splitlines():
        t = line.strip()
        if not t:
            continue

        low = t.lower()
        if any(
                x in low
                for x in [
                    "status_code",
                    "request_id",
                    "finish_reason",
                    "total_tokens",
                    "input_tokens",
                    "output_tokens",
                    "prompt_tokens",
                    "cached_tokens",
                    "\"usage\"",
                    "\"choices\"",
                    "\"message\"",
                    "\"code\"",
                    "\"output\"",
                ]
        ):
            continue

        t = t.lstrip("-*• \t")
        t = re.sub(r"^\s*\d+\s*[\.)、-]\s*", "", t)
        t = t.strip()
        if not t:
            continue

        for seg in re.split(r"[\t,，、;；]", t):
            seg2 = seg.strip().strip('"')
            if seg2:
                out.append(seg2)

    return _normalize_keywords(out)


def _parse_domains(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """解析并标准化 domains 结构。"""

    domains_raw = parsed.get("domains")
    if not isinstance(domains_raw, list):
        return []

    domains: List[Dict[str, Any]] = []
    for item in domains_raw:
        if not isinstance(item, dict):
            continue
        domain_name = str(item.get("domain_name") or "").strip()
        if not domain_name:
            continue
        domains.append(
            {
                "domain_name": domain_name,
                "domain_description": str(item.get("domain_description") or "").strip(),
                "keywords": _safe_str_list(item.get("keywords")),
                "chinese_keywords": _safe_str_list(item.get("chinese_keywords")),
                "english_keywords": _safe_str_list(item.get("english_keywords")),
                "keyword_phrases": _safe_str_list(item.get("keyword_phrases")),
            }
        )
    return domains


def _domain_keywords_flat(domain: Dict[str, Any]) -> List[str]:
    """将单个领域的关键词字段合并为扁平列表。"""

    merged: List[str] = []
    merged.extend(_safe_str_list(domain.get("keywords")))
    merged.extend(_safe_str_list(domain.get("chinese_keywords")))
    merged.extend(_safe_str_list(domain.get("english_keywords")))
    merged.extend(_safe_str_list(domain.get("keyword_phrases")))
    return _normalize_keywords(merged)


def _build_cartesian_keyword_pairs(
        domains: List[Dict[str, Any]],
        *,
        max_domain_keywords: int,
        max_pairs: int,
) -> List[str]:
    """生成领域关键词集合的笛卡尔积组合。

    说明：
    - 为避免组合爆炸，本函数会对每个领域最多取前 max_domain_keywords 个关键词。
    - 组合输出为字符串列表，每条用 " | " 拼接（用于后续硬匹配/检索词）。

    Args:
        domains: 标准化后的领域列表。
        max_domain_keywords: 每个领域最多取多少关键词。
        max_pairs: 最多生成多少条组合。

    Returns:
        组合字符串列表。
    """

    # 为什么这样做：用迭代方式生成并在达到上限时提前停止，避免内存暴涨。
    sets: List[List[str]] = []
    for d in domains:
        kw = _domain_keywords_flat(d)[: max(1, int(max_domain_keywords))]
        if kw:
            sets.append(kw)

    if len(sets) < 2:
        return []

    pairs: List[str] = []

    def _dfs(idx: int, current: List[str]) -> None:
        if len(pairs) >= int(max_pairs):
            return
        if idx >= len(sets):
            pairs.append(" | ".join(current))
            return
        for term in sets[idx]:
            if len(pairs) >= int(max_pairs):
                return
            _dfs(idx + 1, [*current, term])

    _dfs(0, [])
    return pairs


def _call_llm(cfg: KeywordSetConfig) -> Tuple[List[Dict[str, Any]], List[str]]:
    """调用阿里百炼生成按领域分组的关键词集合。"""

    route_hints: Dict[str, Any] = dict(cfg.model_route or {})
    route_hints.setdefault("input_chars", len(cfg.description or ""))

    llm_cfg = load_aliyun_llm_config(
        model=cfg.model,
        env_api_key_name=cfg.env_api_key_name,
        api_key_file=cfg.api_key_file,
        base_url=cfg.base_url,
        affair_name="生成关键词集合",
        route_hints=route_hints,
    )
    client = AliyunDashScopeClient(llm_cfg)

    prompt = _build_prompt(cfg)
    raw = client.generate_text(prompt=prompt, temperature=cfg.temperature, max_tokens=2048)
    parsed = _extract_json(raw) or {}

    domains = _parse_domains(parsed)
    cross_phrases = _safe_str_list(parsed.get("cross_domain_phrases"))

    return domains, cross_phrases


def _dry_run_domains(cfg: KeywordSetConfig) -> Tuple[List[Dict[str, Any]], List[str]]:
    """dry_run 模式下生成可预测的领域结构（用于测试与演示）。"""

    if cfg.research_domains:
        domains: List[Dict[str, Any]] = []
        for name, seeds in cfg.research_domains.items():
            domains.append(
                {
                    "domain_name": name,
                    "domain_description": "dry_run 自动生成的领域",
                    "keywords": _normalize_keywords(seeds),
                    "chinese_keywords": [],
                    "english_keywords": [],
                    "keyword_phrases": [],
                }
            )
        return domains, []

    # 关键逻辑说明：不依赖外部 LLM，构造最小有效的 domains 结构。
    kw = _normalize_keywords(cfg.initial_keywords)
    mid = max(1, len(kw) // 2)
    d1 = {
        "domain_name": "领域A",
        "domain_description": "dry_run 自动生成的领域A",
        "keywords": kw[:mid],
        "chinese_keywords": [],
        "english_keywords": [],
        "keyword_phrases": [],
    }
    d2 = {
        "domain_name": "领域B",
        "domain_description": "dry_run 自动生成的领域B",
        "keywords": kw[mid:],
        "chinese_keywords": [],
        "english_keywords": [],
        "keyword_phrases": [],
    }
    domains = [d1, d2]
    cross_phrases = []
    return domains, cross_phrases


def _build_prompt_domain_chinese(*, domain_name: str, seeds: List[str], description: str, max_keywords: int) -> str:
    """构造“中文扩展阶段”的提示词。

    为什么这样拆分：
    - 你希望同一研究领域最终是一个“中英混合”的关键词集合。
    - 但生成英文关键词往往依赖一批较稳定的中文同义词/近义词集合做语义锚点。
    - 因此先扩展中文，再基于扩展后的中文集合生成英文，会更稳定。

    Args:
        domain_name: 研究领域名称。
        seeds: 该领域的种子关键词（通常为中文）。
        description: 全局研究主题描述。
        max_keywords: 该阶段允许生成的关键词数量上限（不含 seeds）。

    Returns:
        提示词字符串。
    """

    return (
        "你是一个学术检索关键词扩展助手。\n"
        "任务：针对给定研究领域，仅生成‘中文’的近义词/相关概念词/常见检索词（不需要英文）。\n\n"
        "输出必须是一个合法 JSON 对象，只输出 JSON，不要解释文字。\n"
        "JSON 格式：{\"keywords_zh\": [\"中文关键词\"]}\n\n"
        "硬性约束：\n"
        f"- 研究领域名称必须保持为：{domain_name}\n"
        f"- 仅输出中文关键词（允许少量常见缩写如CoVaR，但不要输出完整英文短语）。\n"
        f"- 生成数量不超过 {int(max_keywords)}（不含 seeds）。\n"
        "- 关键词用于学术检索，尽量覆盖同义表达、上位/下位概念、常见写法差异。\n\n"
        f"研究主题描述：{description}\n"
        f"领域种子关键词：{json.dumps(seeds, ensure_ascii=False)}\n"
    )


def _build_prompt_domain_english(*, domain_name: str, keywords_zh: List[str], description: str, max_keywords: int) -> str:
    """构造“英文扩展阶段”的提示词。

    Args:
        domain_name: 研究领域名称。
        keywords_zh: 中文关键词集合（用于语义约束与对齐）。
        description: 全局研究主题描述。
        max_keywords: 该阶段允许生成的英文关键词数量上限。

    Returns:
        提示词字符串。
    """

    return (
        "You are an academic literature search keyword expansion assistant.\n"
        "Task: given a research domain and a Chinese keyword set, produce English search keywords/phrases.\n\n"
        "Output must be a valid JSON object, output JSON only.\n"
        "JSON format: {\"keywords_en\": [\"english keyword or phrase\"]}\n\n"
        "Constraints:\n"
        f"- Research domain name must stay as: {domain_name}\n"
        f"- Only output English keywords/phrases (no Chinese).\n"
        f"- Provide up to {int(max_keywords)} items.\n"
        "- Focus on common terms used in journals / WoS / Google Scholar.\n\n"
        f"Research topic description: {description}\n"
        f"Chinese keywords (for alignment): {json.dumps(keywords_zh, ensure_ascii=False)}\n"
    )


def _call_llm_domain_two_stage(cfg: KeywordSetConfig) -> Tuple[Dict[str, List[str]], List[str], Dict[str, Any]]:
    """按研究领域执行“两阶段关键词生成”，并返回 domains_map 与 debug 信息。"""

    if not cfg.research_domains:
        raise ValueError("research_domains 不能为空：两阶段生成依赖领域种子关键词")

    route_hints: Dict[str, Any] = dict(cfg.model_route or {})
    route_hints.setdefault("input_chars", len(cfg.description or ""))

    llm_cfg = load_aliyun_llm_config(
        model=cfg.model,
        env_api_key_name=cfg.env_api_key_name,
        api_key_file=cfg.api_key_file,
        base_url=cfg.base_url,
        affair_name="生成关键词集合",
        route_hints=route_hints,
    )
    client = AliyunDashScopeClient(llm_cfg)

    domains_map: Dict[str, List[str]] = {}
    debug: Dict[str, Any] = {"by_domain": {}}

    for domain_name, seeds in cfg.research_domains.items():
        seeds_clean = _normalize_keywords([str(x).strip() for x in (seeds or []) if str(x).strip()])

        prompt_zh = _build_prompt_domain_chinese(
            domain_name=domain_name,
            seeds=seeds_clean,
            description=cfg.description,
            max_keywords=max(10, int(cfg.max_keywords) // 2),
        )
        raw_zh = client.generate_text(prompt=prompt_zh, temperature=cfg.temperature, max_tokens=2048)
        raw_zh_for_parse = extract_output_text_from_response_like_blob(raw_zh) if is_likely_sdk_response_blob(raw_zh) else None
        raw_zh_clean = raw_zh_for_parse or raw_zh

        obj_zh: Dict[str, Any] = {}
        picked_zh_key: Optional[str] = None
        try:
            obj_zh, _dbg_zh = parse_json_object_from_text(raw_zh_clean, allow_outermost_extraction=True)
            keywords_zh, picked_zh_key = pick_first_list_field(
                obj_zh,
                candidates=["keywords_zh", "keywords", "items", "terms", "list"],
            )
        except LLMOutputParseError:
            keywords_zh = []

        if not keywords_zh:
            keywords_zh = _fallback_parse_keywords_from_text(raw_zh_clean)

        stage1_zh = _normalize_keywords([*seeds_clean, *keywords_zh])

        prompt_en = _build_prompt_domain_english(
            domain_name=domain_name,
            keywords_zh=stage1_zh,
            description=cfg.description,
            max_keywords=max(10, int(cfg.max_keywords) // 2),
        )
        raw_en = client.generate_text(prompt=prompt_en, temperature=cfg.temperature, max_tokens=2048)
        raw_en_for_parse = extract_output_text_from_response_like_blob(raw_en) if is_likely_sdk_response_blob(raw_en) else None
        raw_en_clean = raw_en_for_parse or raw_en

        obj_en: Dict[str, Any] = {}
        picked_en_key: Optional[str] = None
        try:
            obj_en, _dbg_en = parse_json_object_from_text(raw_en_clean, allow_outermost_extraction=True)
            keywords_en, picked_en_key = pick_first_list_field(
                obj_en,
                candidates=["keywords_en", "keywords", "items", "terms", "list"],
            )
        except LLMOutputParseError:
            keywords_en = []

        if not keywords_en:
            keywords_en = _fallback_parse_keywords_from_text(raw_en_clean)

        stage2_mixed = _normalize_keywords([*stage1_zh, *keywords_en])

        debug["by_domain"][domain_name] = {
            "seeds_count": len(seeds_clean),
            "stage1_zh_count": len(stage1_zh),
            "stage2_mixed_count": len(stage2_mixed),
            "raw_zh": _truncate_text(raw_zh_clean),
            "raw_en": _truncate_text(raw_en_clean),
            "parsed_zh_keys": sorted(list(obj_zh.keys())),
            "parsed_en_keys": sorted(list(obj_en.keys())),
            "picked_zh_key": picked_zh_key,
            "picked_en_key": picked_en_key,
            "keywords_zh_count": len(keywords_zh),
            "keywords_en_count": len(keywords_en),
        }

        # 关键：不允许“静默退化”为 seeds，否则下游以为扩展成功但实际没有覆盖。
        if len(stage2_mixed) <= len(seeds_clean):
            msg = (
                f"领域[{domain_name}] 关键词扩展结果疑似退化：最终数量={len(stage2_mixed)}，"
                f"种子数量={len(seeds_clean)}。可能原因：模型未按 JSON 格式输出，或解析失败。"
            )
            if cfg.allow_fallback:
                # 允许退化但仍追加一条提示词，便于用户在输出文件里看到问题。
                debug["by_domain"][domain_name]["warning"] = msg
            else:
                raise ValueError(msg)

        domains_map[domain_name] = stage2_mixed

    return domains_map, [], debug


def _domains_map_to_legacy_domains_list(domains_map: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """把 domains_map 转为旧版 domains(list[dict]) 结构。

    为什么需要这个转换：
    - 本仓库历史上使用 domains(list) 结构来生成“跨域笛卡尔积组合”（keyword_pairs）。
    - 你现在采用的是更稳定的 domains(dict) 结构（领域->最终关键词集合）。
    - 为兼容旧逻辑与现有输出字段（domains_legacy），这里把 dict 视图转换成 list 视图。

    Args:
        domains_map: {domain_name: [final_keywords_mixed]}。

    Returns:
        旧版 domains(list[dict]) 结构。
    """

    out: List[Dict[str, Any]] = []
    for domain_name, kws in (domains_map or {}).items():
        out.append(
            {
                "domain_name": str(domain_name),
                "domain_description": "",
                "keywords": _normalize_keywords([str(x) for x in (kws or [])]),
                "chinese_keywords": [],
                "english_keywords": [],
                "keyword_phrases": [],
            }
        )
    return out


def execute(config_path: Path) -> List[Path]:
    """调度器入口：生成关键词集合并写出到输出目录。"""

    raw_cfg = load_json_or_py(config_path)
    affair_cfg: Dict[str, Any] = dict(raw_cfg)

    research_domains = _normalize_research_domains(affair_cfg.get("research_domains"))

    cfg = KeywordSetConfig(
        description=str(affair_cfg.get("description") or "").strip(),
        initial_keywords=_safe_list(affair_cfg.get("initial_keywords")),
        research_domains=research_domains,
        reference_materials_dir=affair_cfg.get("reference_materials_dir"),
        reference_materials_max_files=(
            int(affair_cfg["reference_materials_max_files"]) if affair_cfg.get("reference_materials_max_files") is not None else None
        ),
        reference_materials_max_chars=(
            int(affair_cfg["reference_materials_max_chars"]) if affair_cfg.get("reference_materials_max_chars") is not None else None
        ),
        output_dir=str(affair_cfg.get("output_dir") or ""),
        output_json_name=_resolve_output_filename(
            affair_cfg.get("output_json_name"),
            default_name="keyword_set.json",
        ),
        output_txt_name=_resolve_output_filename(
            affair_cfg.get("output_txt_name"),
            default_name="keyword_set.txt",
        ),
        output_pairs_name=_resolve_output_filename(
            affair_cfg.get("output_pairs_name"),
            default_name="keyword_pairs.txt",
        ),
        output_debug_name=_resolve_output_filename(
            affair_cfg.get("output_debug_name"),
            default_name="keyword_debug.json",
        ),
        output_domains_name=_resolve_output_filename(
            affair_cfg.get("output_domains_name"),
            default_name="keyword_domains.json",
        ),
        model=str(affair_cfg.get("model") or "auto"),
        temperature=float(affair_cfg.get("temperature", 0.2)),
        max_keywords=int(affair_cfg.get("max_keywords", 60)),
        include_chinese=bool(affair_cfg.get("include_chinese", True)),
        include_english=bool(affair_cfg.get("include_english", True)),
        include_phrases=bool(affair_cfg.get("include_phrases", True)),
        num_domains=int(affair_cfg.get("num_domains", 2) or 2),
        max_domain_keywords=int(affair_cfg.get("max_domain_keywords", 40) or 40),
        max_pairs=int(affair_cfg.get("max_pairs", 2000) or 2000),
        dry_run=bool(affair_cfg.get("dry_run", False)),
        env_api_key_name=str(affair_cfg.get("env_api_key_name") or "DASHSCOPE_API_KEY"),
        api_key_file=affair_cfg.get("api_key_file"),
        base_url=affair_cfg.get("base_url"),
        model_route=affair_cfg.get("model_route") if isinstance(affair_cfg.get("model_route"), dict) else None,
        allow_fallback=bool(affair_cfg.get("allow_fallback", False)),
        domain_purify_enable=bool(affair_cfg.get("domain_purify_enable", True)),
        domain_purify_margin=float(affair_cfg.get("domain_purify_margin", 1.15)),
        domain_purify_min_score=float(affair_cfg.get("domain_purify_min_score", 1.0)),
    )

    if not cfg.description:
        raise ValueError("description 不能为空")
    if not cfg.initial_keywords and not cfg.research_domains:
        raise ValueError("initial_keywords 不能为空（或提供 research_domains）")

    # 当 research_domains 提供时，以其数量为准，覆盖 num_domains
    if cfg.research_domains:
        cfg.num_domains = len(cfg.research_domains)

    if cfg.num_domains < 2:
        raise ValueError("num_domains 必须 >= 2")

    output_dir = Path(cfg.output_dir)
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={cfg.output_dir!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_debug: Dict[str, Any] = {}
    if cfg.reference_materials_dir:
        ref_dir = Path(str(cfg.reference_materials_dir))
        if not ref_dir.is_absolute():
            raise ValueError(
                "reference_materials_dir 必须为绝对路径：应由调度层提前绝对化。"
                f"当前值={cfg.reference_materials_dir!r}"
            )
        corpus = load_reference_corpus_from_dir(
            ref_dir,
            max_files=cfg.reference_materials_max_files,
            max_chars=cfg.reference_materials_max_chars,
        )
        reference_debug = {
            "reference_materials_dir": str(ref_dir),
            "reference_materials_files": [p.name for p in corpus.files],
            "reference_materials_files_abs": [str(p) for p in corpus.files],
            "reference_materials_chars": corpus.chars,
            "reference_materials_truncated": corpus.truncated,
        }

    if cfg.dry_run:
        # dry_run 时直接用 seeds 作为最终集合，保证下游流程可跑通
        domains_list, cross_phrases = _dry_run_domains(cfg)
        domains_map = {d.get("domain_name"): _domain_keywords_flat(d) for d in domains_list if d.get("domain_name")}
        debug = {"dry_run": True, **reference_debug}
    else:
        domains_map, cross_phrases, debug = _call_llm_domain_two_stage(cfg)
        if cfg.domain_purify_enable:
            domains_map, purify_debug = _purify_domains_keywords(
                domains_map=domains_map,
                research_domains=cfg.research_domains,
                margin=cfg.domain_purify_margin,
                min_score=cfg.domain_purify_min_score,
            )
            debug = dict(debug or {})
            debug["domain_purify"] = purify_debug

        if reference_debug:
            debug = dict(debug or {})
            debug.update(reference_debug)
        domains_list = _domains_map_to_legacy_domains_list(domains_map)

    # 合并生成 all_keywords（用于后续硬匹配初筛）
    all_keywords: List[str] = []
    all_keywords.extend(_normalize_keywords(cfg.initial_keywords))
    for domain_name, kws in (domains_map or {}).items():
        all_keywords.extend(kws)
    all_keywords.extend(cross_phrases)
    all_keywords = _normalize_keywords(all_keywords)

    pairs = _build_cartesian_keyword_pairs(
        domains_list,
        max_domain_keywords=cfg.max_domain_keywords,
        max_pairs=cfg.max_pairs,
    )

    result = {
        "schema_version": 1,
        "description": cfg.description,
        "initial_keywords": cfg.initial_keywords,
        "research_domains": cfg.research_domains,
        "domains": {k: {"keywords": v} for k, v in (domains_map or {}).items()},  # domains（字典），便于下游直接按领域索引
        "cross_domain_phrases": cross_phrases,
        "all_keywords": all_keywords,
        "cartesian_keyword_pairs": pairs,
        "model": cfg.model,
        "temperature": cfg.temperature,
        "max_keywords": cfg.max_keywords,
        "include_chinese": cfg.include_chinese,
        "include_english": cfg.include_english,
        "include_phrases": cfg.include_phrases,
        "num_domains": cfg.num_domains,
        "max_domain_keywords": cfg.max_domain_keywords,
        "max_pairs": cfg.max_pairs,
        "dry_run": cfg.dry_run,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "debug": debug,
    }

    json_path = output_dir / cfg.output_json_name
    txt_path = output_dir / cfg.output_txt_name
    pairs_path = output_dir / cfg.output_pairs_name
    debug_path = output_dir / cfg.output_debug_name
    domains_path = output_dir / cfg.output_domains_name

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text("\n".join(result["all_keywords"]) + "\n", encoding="utf-8")
    pairs_path.write_text("\n".join(result["cartesian_keyword_pairs"]) + "\n", encoding="utf-8")
    debug_path.write_text(json.dumps(result["debug"], ensure_ascii=False, indent=2), encoding="utf-8")
    domains_path.write_text(
        json.dumps(
            {
                "domains": result["domains"],
                "cross_domain_phrases": result["cross_domain_phrases"],
                "num_domains": result["num_domains"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return [json_path, txt_path, pairs_path, debug_path, domains_path]


def main() -> None:
    """命令行入口。"""

    import sys

    if len(sys.argv) < 2:
        raise SystemExit("用法：python 生成关键词集合.py <config_path>")

    written = execute(Path(sys.argv[1]))
    for p in written:
        print(p)


if __name__ == "__main__":
    main()

