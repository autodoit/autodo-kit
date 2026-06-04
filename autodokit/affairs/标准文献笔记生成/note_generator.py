# -*- coding: utf-8 -*-
"""
A090 标准文献笔记生成器

负责：
1. 读取 MonkeyOCR 结构化产物（normalized_structured.json）
2. 调用 LLM 生成标准文献笔记
3. 保存笔记到 workspace/knowledge/notes/<cite_key>.md
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def generate_standard_note(
    item: Dict,
    structured_dir: Path,
    knowledge_dir: Path,
    llm_config: Dict,
    note_template: Dict,
    research_topic: str,
    topic_terms: List[str],
    workspace_root: Path,
) -> Dict:
    """
    为单篇文献生成标准笔记。

    Args:
        item: 文献记录字典（含 uid_文献, cite_key, bib_title 等）
        structured_dir: MonkeyOCR 结构化产物根目录
        knowledge_dir: 笔记输出目录
        llm_config: LLM 配置
        note_template: 笔记模板配置
        research_topic: 研究主题
        topic_terms: 主题词列表
        workspace_root: 工作区根目录

    Returns:
        {"status": "success"/"error", "note_path": str, "message": str}
    """
    uid = item["uid_文献"]
    cite_key = item.get("cite_key", uid)

    # 1. 读取结构化内容
    structured_content = _read_structured_content(uid, structured_dir, item)
    if structured_content is None:
        return {
            "status": "error",
            "message": f"无法读取结构化产物（uid={uid}）",
            "note_path": ""
        }

    # 2. 构建笔记
    note_md = _build_note_markdown(
        item=item,
        structured_content=structured_content,
        research_topic=research_topic,
        topic_terms=topic_terms,
        note_template=note_template,
    )

    # 3. 保存笔记文件
    # 使用 cite_key 作为文件名（去除不安全字符）
    safe_name = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in cite_key)
    note_path = knowledge_dir / f"{safe_name}.md"
    note_path.write_text(note_md, encoding="utf-8")
    logger.info(f"笔记已保存: {note_path}")

    return {
        "status": "success",
        "note_path": str(note_path),
        "message": f"成功生成笔记: {cite_key}",
        "content_length": len(note_md)
    }


def _read_structured_content(uid: str, structured_dir: Path, item: Dict) -> Optional[Dict]:
    """
    从 MonkeyOCR 结构化产物中读取内容。

    优先级（与 A130 reading_packet 对齐）：
    1. normalized_structured.json
    2. reconstructed_content.md
    3. 当前解析路径（如果有）

    Args:
        uid: 文献 UID
        structured_dir: 结构化产物根目录
        item: 文献记录

    Returns:
        解析后的内容字典，或 None
    """
    uid_dir = structured_dir / uid

    # 1. 尝试 normalized_structured.json
    norm_json_path = uid_dir / "normalized_structured.json"
    if norm_json_path.exists():
        try:
            with open(norm_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"读取 normalized_structured.json: {norm_json_path}")
            return data
        except Exception as e:
            logger.warning(f"读取 normalized_structured.json 失败: {e}")

    # 2. 尝试 reconstructed_content.md
    md_path = uid_dir / "reconstructed_content.md"
    if md_path.exists():
        try:
            md_text = md_path.read_text(encoding="utf-8")
            logger.info(f"读取 reconstructed_content.md: {md_path}")
            return {"full_text": md_text, "source": "reconstructed_md"}
        except Exception as e:
            logger.warning(f"读取 reconstructed_content.md 失败: {e}")

    # 3. 尝试 item 中的当前解析路径
    parse_path = item.get("当前解析路径", "")
    if parse_path and Path(parse_path).exists():
        try:
            with open(parse_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"读取当前解析路径: {parse_path}")
            return data
        except Exception as e:
            logger.warning(f"读取当前解析路径失败: {e}")

    logger.error(f"无法找到任何结构化产物（uid={uid}，目录={uid_dir}）")
    return None


def _build_note_markdown(
    item: Dict,
    structured_content: Dict,
    research_topic: str,
    topic_terms: List[str],
    note_template: Dict,
) -> str:
    """
    从结构化内容构建标准文献笔记 Markdown。

    当前使用结构化模板方式；LLM 深度阅读版本可在后续迭代中接入。

    Args:
        item: 文献记录
        structured_content: 结构化内容
        research_topic: 研究主题
        topic_terms: 主题词列表
        note_template: 笔记模板配置

    Returns:
        Markdown 格式的笔记
    """
    cite_key = item.get("cite_key", item["uid_文献"])
    title = item.get("bib_title") or item.get("标题译文", "未知标题")
    year = item.get("bib_year", "")
    authors = item.get("bib_collaborator", "")
    journal = item.get("bib_journal", "")

    # 提取正文内容
    full_text = _extract_text(structured_content)

    # 按章节拆分内容（如果有章节结构）
    sections = _extract_sections(structured_content)

    # 构建笔记
    required_sections = note_template.get("required_sections", [
        "文献信息", "研究问题", "核心论点", "研究方法",
        "关键发现", "创新点", "局限性", "与我研究的关联"
    ])

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# {title}",
        "",
        f"> cite_key: `{cite_key}`",
        f"> 生成时间: {now}",
        f"> 生成方式: A090 标准文献笔记（结构化模板）",
        "",
        "---",
        "",
    ]

    # 文献信息
    lines.extend([
        "## 文献信息",
        "",
        f"- **标题**: {title}",
        f"- **作者**: {authors or '未知'}",
        f"- **年份**: {year or '未知'}",
        f"- **期刊/会议**: {journal or '未知'}",
        f"- **cite_key**: `{cite_key}`",
        "",
    ])

    # 摘要/研究问题
    abstract = _get_section_text(sections, ["abstract", "摘要", "Abstract"]) or full_text[:500]
    lines.extend([
        "## 研究问题",
        "",
        abstract.strip() if abstract else "（摘要未提取到，请人工补充）",
        "",
    ])

    # 核心论点
    intro = _get_section_text(sections, ["introduction", "引言", "Introduction", "1.", "1 "])
    lines.extend([
        "## 核心论点",
        "",
        _summarize_text(intro, 400) if intro else "（引言部分未提取到，请参考原文）",
        "",
    ])

    # 研究方法
    methods = _get_section_text(sections, ["method", "methodology", "方法", "Method", "model", "模型"])
    lines.extend([
        "## 研究方法",
        "",
        _summarize_text(methods, 400) if methods else "（方法部分未提取到，请参考原文）",
        "",
    ])

    # 关键发现
    findings = _get_section_text(sections, ["result", "finding", "结果", "发现", "Result", "conclusion", "结论"])
    lines.extend([
        "## 关键发现",
        "",
        _summarize_text(findings, 400) if findings else "（结果部分未提取到，请参考原文）",
        "",
    ])

    # 创新点
    contributions = _get_section_text(sections, ["contribution", "novel", "创新", "贡献"])
    lines.extend([
        "## 创新点",
        "",
        _summarize_text(contributions, 300) if contributions else "（创新点需从全文综合判断，建议人工补充）",
        "",
    ])

    # 局限性
    limitations = _get_section_text(sections, ["limitation", "局限", "Limitation", "future work"])
    lines.extend([
        "## 局限性",
        "",
        _summarize_text(limitations, 300) if limitations else "（局限性部分需从结论/讨论中提取，建议人工补充）",
        "",
    ])

    # 与我研究的关联
    lines.extend([
        "## 与我研究的关联",
        "",
        f"**研究主题**: {research_topic or '（未配置）'}",
        "",
        "（此部分建议人工补充：该文献与当前研究课题的具体关联、可借鉴之处、"
        "对变量定义/方法选择/理论框架的启发）",
        "",
    ])

    # 原文引用入口
    lines.extend([
        "---",
        "",
        f"**引用**: [[{cite_key}]]",
        "",
    ])

    return "\n".join(lines)


def _extract_text(structured_content: Dict) -> str:
    """从结构化内容中提取全文文本。"""
    if isinstance(structured_content, str):
        return structured_content

    # 优先 full_text
    if "full_text" in structured_content:
        return structured_content["full_text"]

    # 尝试从 sections/blocks 中拼接
    text_parts = []
    for key in ("sections", "blocks", "elements", "paragraphs"):
        items = structured_content.get(key, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content") or item.get("value", "")
                    if text:
                        text_parts.append(text)
                elif isinstance(item, str):
                    text_parts.append(item)

    return "\n".join(text_parts) if text_parts else json.dumps(structured_content, ensure_ascii=False)[:2000]


def _extract_sections(structured_content: Dict) -> Dict[str, str]:
    """从结构化内容中提取章节映射。"""
    sections = {}
    if not isinstance(structured_content, dict):
        return sections

    # 尝试从 sections/blocks 中提取
    for key in ("sections", "blocks", "elements"):
        items = structured_content.get(key, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    heading = item.get("heading") or item.get("title") or item.get("section", "")
                    text = item.get("text") or item.get("content") or item.get("value", "")
                    if heading and text:
                        sections[heading.lower().strip()] = text

    return sections


def _get_section_text(sections: Dict[str, str], keywords: List[str]) -> Optional[str]:
    """按关键词从章节字典中匹配内容。"""
    for kw in keywords:
        kw_lower = kw.lower().strip()
        for heading, text in sections.items():
            if kw_lower in heading:
                return text
    return None


def _summarize_text(text: str, max_chars: int = 400) -> str:
    """
    简单截取文本前 max_chars 字符。
    后续可接入 LLM 做真正的摘要生成。
    """
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    # 在句号处截断
    truncated = text[:max_chars]
    last_period = max(truncated.rfind("。"), truncated.rfind("."))
    if last_period > max_chars * 0.5:
        truncated = truncated[:last_period + 1]
    return truncated + "..."
