"""文档按“单元”切分工具。

你提出的核心约束是：
- 切分必须以“可分析的语义单元”为粒度。
- 截断/预算控制时，不能把一个单元切成两半（例如把同一个公式环境切成两段）。

本模块提供统一入口 `split_document_to_units(path)`：
- 输入：单个文档文件路径（必须为绝对路径）。
- 输出：DocumentUnit 列表。每个单元具有 `unit_type` 与 `text`。

当前支持的单元类型（最小可用集合）：
- paragraph：自然段落
- code_block：代码块（Markdown 三引号、reStructuredText literal block/::）
- math：公式（LaTeX 的 $$..$$、\\[ .. \\]、equation/align 等环境）
- figure：图环境（LaTeX figure）
- table：表环境（LaTeX table/tabular）
- image：图片引用（LaTeX includegraphics、Markdown ![]()）
- citation_item：引用条目（LaTeX thebibliography/bibitem；Markdown/RST 的参考列表会尽量按条目切分）

注意：
- 这里不是“完整解析器”，而是面向可复用工程的规则切分器；重点是稳定、可测试、可解释。
- 清洗策略以“降噪但不伤语义”为原则，避免过度删除。

"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal


UnitType = Literal[
    "heading",  # 章节/标题
    "paragraph",
    "code_block",
    "math",
    "figure",
    "table",
    "image",
    "citation_item",
    "footnote",  # 脚注
    "endnote",  # 尾注（预留）
    "other",
]


@dataclass(frozen=True)
class DocumentUnit:
    """一个不可再拆的文档单元。

    Attributes:
        unit_type: 单元类型。
        text: 单元文本（已做适度清洗，可直接用于拼接/检索）。
        source_path: 源文件绝对路径。
        meta: 单元元信息（例如 heading_level、context_heading_text 等）。
    """

    unit_type: UnitType
    text: str
    source_path: Path
    meta: Dict[str, Any] = field(default_factory=dict)


_TEX_COMMENT_RE = re.compile(r"(^|[^\\])%.*?$", re.MULTILINE)


def _read_text_with_fallback(path: Path) -> str:
    """读取文本文件并在常见编码间兜底。"""

    for enc in ("utf-8", "utf-8-sig", "gbk", "cp1252"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8")


def _split_plaintext_paragraphs(text: str) -> List[str]:
    """按空行切分自然段落。"""

    out = [u.strip() for u in re.split(r"\n\s*\n+", text or "")]
    return [u for u in out if u]


def _split_markdown_units(text: str) -> List[tuple[UnitType, str, Dict[str, Any]]]:
    """Markdown 按单元切分：标题/代码块/图片/段落/参考列表条目。

    Returns:
        三元组列表 (unit_type, text, meta)。
    """

    lines = (text or "").splitlines()
    units: List[tuple[UnitType, str, Dict[str, Any]]] = []

    i = 0
    buf: List[str] = []

    def flush_paragraph() -> None:
        nonlocal buf
        s = "\n".join(buf).strip()
        buf = []
        if not s:
            return

        if _MD_IMAGE_RE.fullmatch(s.strip()):
            units.append(("image", s, {}))
            return

        units.append(("paragraph", s, {}))

    while i < len(lines):
        ln = lines[i]
        stripped = ln.strip()

        # Markdown 标题：独立 heading 单元
        m_head = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m_head:
            flush_paragraph()
            level = len(m_head.group(1))
            title = m_head.group(2).strip()
            if title:
                units.append(("heading", title, {"heading_level": level}))
            i += 1
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            block = [ln]
            i += 1
            while i < len(lines):
                block.append(lines[i])
                if lines[i].strip().startswith("```"):
                    i += 1
                    break
                i += 1
            units.append(("code_block", "\n".join(block).strip(), {}))
            continue

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        if re.fullmatch(r"!\[[^\]]*]\([^)]*\)", stripped):
            flush_paragraph()
            units.append(("image", stripped, {}))
            i += 1
            continue

        buf.append(ln)
        i += 1

    flush_paragraph()

    # 引文条目弱规则拆分
    refined: List[tuple[UnitType, str, Dict[str, Any]]] = []
    for t, u, meta in units:
        if t != "paragraph":
            refined.append((t, u, meta))
            continue

        lines2 = u.splitlines()
        items: List[str] = []
        cur: List[str] = []
        for ln2 in lines2:
            if re.match(r"^\s*(\[\d+]|\d+\.|-\s)", ln2.strip()):
                if cur:
                    items.append("\n".join(cur).strip())
                    cur = []
            cur.append(ln2)
        if cur:
            items.append("\n".join(cur).strip())

        if len(items) >= 2:
            for it in items:
                if it:
                    refined.append(("citation_item", it, {}))
        else:
            refined.append((t, u, meta))

    return _attach_context_heading(refined)


def _split_rst_units(text: str) -> List[tuple[UnitType, str]]:
    """reStructuredText 的基本单元切分（最小可用）。

    说明：
    - 当前项目主线以 md/tex 为主；rst 作为兼容入口，仅提供段落/代码块的保守切分。

    Args:
        text: 原始文本。

    Returns:
        (unit_type, text) 列表。
    """

    paragraphs = _split_plaintext_paragraphs(text)
    units: List[tuple[UnitType, str]] = []
    for p in paragraphs:
        if p.rstrip().endswith("::"):
            units.append(("code_block", p))
        else:
            units.append(("paragraph", p))
    return units


# 将 Markdown 图片正则改为不触发冗余转义告警的等价写法
# 原：r"!\[[^\]]*]\([^)]*\)"
_MD_IMAGE_RE = re.compile(r"!\[[^]]*]\([^)]*\)")

# section 命令：去掉对 } 的冗余转义
_SECTION_CMD_RE = re.compile(r"^\\(section|subsection|subsubsection|paragraph|subparagraph)\*?\{(.+?)\}\s*$")


def _split_tex_units(text: str) -> List[tuple[UnitType, str, Dict[str, Any]]]:
    """LaTeX 按单元切分（标题/段落/公式/图表/图片/引文条目）。"""

    if not text:
        return []

    text = _strip_latex_preamble(text)

    cleaned = _TEX_COMMENT_RE.sub("\\1", text)
    lines = cleaned.splitlines()
    units: List[tuple[UnitType, str, Dict[str, Any]]] = []
    buf: List[str] = []

    def flush_paragraph() -> None:
        nonlocal buf
        s = "\n".join(buf).strip()
        buf = []
        if s:
            units.append(("paragraph", s, {}))

    i = 0
    while i < len(lines):
        ln = lines[i]
        stripped = ln.strip()

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        # section 等标题命令：独立 heading 单元
        m_sec = _SECTION_CMD_RE.match(stripped)
        if m_sec:
            flush_paragraph()
            cmd = m_sec.group(1)
            title = m_sec.group(2).strip()
            level_map = {
                "section": 1,
                "subsection": 2,
                "subsubsection": 3,
                "paragraph": 4,
                "subparagraph": 5,
            }
            level = level_map.get(cmd, 1)
            if title:
                units.append(("heading", title, {"heading_level": level}))
            i += 1
            continue

        # $$ ... $$
        if stripped.startswith("$$"):
            flush_paragraph()
            block = [ln]
            i += 1
            while i < len(lines) and "$$" not in lines[i]:
                block.append(lines[i])
                i += 1
            if i < len(lines):
                block.append(lines[i])
                i += 1
            units.append(("math", "\n".join(block).strip(), {}))
            continue

        # \\[ ... \\]
        if stripped.startswith("\\["):
            flush_paragraph()
            block = [ln]
            i += 1
            while i < len(lines) and not re.search(r"\\\\]", lines[i]):
                # 关键：必须匹配 LaTeX 的结束标记 "\\]"，不能用普通 ']' 作为终止符。
                block.append(lines[i])
                i += 1
            if i < len(lines):
                block.append(lines[i])
                i += 1
            units.append(("math", "\n".join(block).strip(), {}))
            continue

        # \begin{...}
        m_begin = re.match(r"\\begin\{([^}]+)}", stripped)
        if m_begin:
            env_raw = m_begin.group(1)
            env = env_raw.strip().lower()
            flush_paragraph()

            block = [ln]
            i += 1
            end_pat = re.compile(r"\\end\{" + re.escape(env_raw) + r"}")
            while i < len(lines) and not end_pat.search(lines[i]):
                block.append(lines[i])
                i += 1
            if i < len(lines):
                block.append(lines[i])
                i += 1

            if env in {"equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*"}:
                units.append(("math", "\n".join(block).strip(), {}))
            elif env in {"figure", "figure*"}:
                units.append(("figure", "\n".join(block).strip(), {}))
            elif env in {"table", "table*", "tabular", "tabular*"}:
                units.append(("table", "\n".join(block).strip(), {}))
            elif env in {"thebibliography"}:
                units.append(("other", "\n".join(block).strip(), {"env": "thebibliography"}))
            else:
                units.append(("other", "\n".join(block).strip(), {"env": env}))
            continue

        if "\\includegraphics" in stripped:
            flush_paragraph()
            units.append(("image", stripped, {}))
            i += 1
            continue

        buf.append(ln)
        i += 1

    flush_paragraph()

    # 拆 bibitem 条目
    refined: List[tuple[UnitType, str, Dict[str, Any]]] = []
    for t, u, meta in units:
        if "\\bibitem" not in u:
            refined.append((t, u, meta))
            continue

        items = re.split(r"(?=\\bibitem\{)", u)
        wrote = False
        for it in items:
            it = it.strip()
            if it.startswith("\\bibitem"):
                refined.append(("citation_item", it, {}))
                wrote = True
        if not wrote:
            refined.append((t, u, meta))

    # 抽取 footnote 为独立单元（保持顺序：段落 -> footnote 单元在其后）
    out: List[tuple[UnitType, str, Dict[str, Any]]] = []
    for t, u, meta in refined:
        if t != "paragraph":
            out.append((t, u, meta))
            continue

        # 提取脚注内容（不做嵌套大括号完整解析，v1 够用）
        notes = re.findall(r"\\footnote\{([^}]*)}", u)
        cleaned_para = re.sub(r"\\footnote\{[^}]*\}", " ", u)
        out.append(("paragraph", cleaned_para.strip(), meta))
        for note in notes:
            note = note.strip()
            if note:
                out.append(("footnote", note, {}))

    return _attach_context_heading(out)


def _attach_context_heading(
    units: List[tuple[UnitType, str, Dict[str, Any]]],
) -> List[tuple[UnitType, str, Dict[str, Any]]]:
    """为每个非 heading 单元附加最近 heading 的上下文信息。

    Args:
        units: (unit_type, text, meta) 列表，必须保持原文顺序。

    Returns:
        增强后的 units 列表。
    """

    current_title = ""
    current_level: int | None = None

    out: List[tuple[UnitType, str, Dict[str, Any]]] = []
    for t, u, meta in units:
        meta2 = dict(meta or {})
        if t == "heading":
            current_title = u.strip()
            level = meta2.get("heading_level")
            current_level = int(level) if isinstance(level, int) else current_level
            out.append((t, u, meta2))
            continue

        if current_title:
            meta2.setdefault("context_heading_text", current_title)
        if current_level is not None:
            meta2.setdefault("context_heading_level", current_level)

        out.append((t, u, meta2))

    return out


def split_document_to_units(path: Path) -> List[DocumentUnit]:
    """把单个文档切分为不可再拆的“单元”。

    Args:
        path: 文档路径（必须为绝对路径）。

    Returns:
        单元列表。

    Raises:
        ValueError: path 不是绝对路径或文件不存在。
    """

    if not path.is_absolute():
        raise ValueError(f"文档路径必须为绝对路径（应由调度层绝对化）：{path}")
    if not path.exists() or not path.is_file():
        raise ValueError(f"文档路径不存在或不是文件：{path}")

    suffix = path.suffix.lower()
    raw = _read_text_with_fallback(path)

    units_raw: List[tuple[UnitType, str, Dict[str, Any]]]
    if suffix == ".tex":
        units_raw = _split_tex_units(raw)
        units_raw2: List[tuple[UnitType, str, Dict[str, Any]]] = []
        for t, u, meta in units_raw:
            cleaned = _clean_tex_block_text(t, u)
            if cleaned.strip():
                units_raw2.append((t, cleaned, meta))
        units_raw = units_raw2
    elif suffix in {".md", ".markdown"}:
        units_raw = _split_markdown_units(raw)
    else:
        # 说明：当前版本先聚焦 md/tex；rst/txt 等格式后续再按需求解禁。
        units_raw = [("paragraph", u, {}) for u in _split_plaintext_paragraphs(raw)]

    return [
        DocumentUnit(unit_type=t, text=u.strip(), source_path=path, meta=(meta or {}))
        for t, u, meta in units_raw
        if u.strip()
    ]


def _strip_latex_preamble(text: str) -> str:
    """删除 LaTeX preamble 与 document 结束后的内容。

    为什么这样做：
    - preamble（documentclass/usepackage/title 等）通常是格式控制噪声，不利于后续检索与关键词。
    - 截取 \\begin{document}..\\end{document} 可以快速聚焦正文。

    Args:
        text: 原始 LaTeX 文本。

    Returns:
        尽量只包含 document 环境内部的 LaTeX 文本。
    """

    if not text:
        return ""

    m_start = re.search(r"\\begin\{document\}", text)
    if m_start:
        text = text[m_start.end() :]

    m_end = re.search(r"\\end\{document\}", text)
    if m_end:
        text = text[: m_end.start()]

    return text


def _clean_tex_block_text(unit_type: UnitType, raw: str) -> str:
    """对 LaTeX 单元做去噪，保留可用于检索/关键词/口径一致的文本。

    关键策略：
    - 不拆单元：保持公式/图表/表格/图片的完整性；
    - 对 math/figure/table/image 以“标签+caption/label”方式摘要，避免预算被格式吞噬；
    - 对 paragraph/heading/citation_item/footnote 等，尽量提取可读文本并去掉控制命令。

    Args:
        unit_type: 单元类型。
        raw: 原始 LaTeX 片段。

    Returns:
        清洗后的文本（可能为空字符串，表示该单元应被丢弃）。
    """

    s = (raw or "").strip()
    if not s:
        return ""

    if unit_type in {"math", "figure", "table", "image"}:
        caption = ""
        m_cap = re.search(r"\\caption\{([^}]*)\}", s)
        if m_cap:
            caption = m_cap.group(1).strip()
        label = ""
        m_lab = re.search(r"\\label\{([^}]*)\}", s)
        if m_lab:
            label = m_lab.group(1).strip()
        summary = " | ".join([x for x in [caption and f"caption={caption}", label and f"label={label}"] if x])
        return f"[{unit_type}] {summary}".strip() if summary else f"[{unit_type}]"

    # heading：去除 \section{...} 之类的命令包装（通常 raw 已只取 title，但这里兜底）
    if unit_type == "heading":
        m = re.search(r"\{(.+?)\}", s)
        if m:
            s = m.group(1).strip()

    # 过滤常见控制命令行
    if re.match(
        r"^\\(documentclass|usepackage|title|author|date|maketitle|tableofcontents|newcommand|renewcommand)\b",
        s,
    ):
        return ""

    s = s.replace("~", " ")
    s = re.sub(r"\\(cite|ref|eqref|label)\{[^}]*\}", " ", s)
    s = re.sub(r"\\(textbf|textit|emph|underline|mathrm|mathbf)\{([^}]*)\}", r"\2", s)

    # footnote 在 split 阶段已抽取；这里再保守删除残余
    s = re.sub(r"\\footnote\{[^}]*\}", " ", s)

    # 删除简单命令（保守）
    s = re.sub(r"\\[a-zA-Z@]+\*?(\[[^]]*\])?", " ", s)

    s = re.sub(r"[{}]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
