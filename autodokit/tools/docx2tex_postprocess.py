"""docx2tex 输出 xelatex 后处理工具。

将 docx2tex 默认的 pdflatex 输出转换为 xelatex 兼容格式，
支持两种引用模式：
- no-bibtex（默认）：引文保留为纯文本 `(作者,年份)`，参考文献保持原样，可直接 xelatex 编译
- bibtex：提取纯文本引文生成 .bib 文件，正文替换为 \\cite{} 命令

使用示例:
    >>> from pathlib import Path
    >>> from autodokit.tools.docx2tex_postprocess import postprocess_docx2tex_for_xelatex
    >>>
    >>> # no-bibtex 模式（纯文本引文，直接编译）
    >>> result = postprocess_docx2tex_for_xelatex(
    ...     input_tex_path=Path("paper.tex"),
    ...     output_tex_path=Path("paper_xelatex.tex"),
    ...     bibtex_mode=False,
    ... )
    >>> print(result)  # {'mode': 'no-bibtex', 'cite_count': 234, 'output': '...'}
    >>>
    >>> # bibtex 模式（提取引文生成 .bib）
    >>> result = postprocess_docx2tex_for_xelatex(
    ...     input_tex_path=Path("paper.tex"),
    ...     output_tex_path=Path("paper_xelatex.tex"),
    ...     bibtex_mode=True,
    ...     bib_output_path=Path("paper.bib"),
    ... )

后处理步骤:
    1. 替换前导区：移除 pdflatex 专用包，插入 fontspec + xeCJK
    2. 处理图片引用：注释掉 .docx.tmp/ 和 embeddings/ 下的不可用文件
    3. 处理引用：no-bibtex 模式保持原样；bibtex 模式提取并替换
"""

from __future__ import annotations

import re
from pathlib import Path


# ── xelatex 前导区替换映射 ──────────────────────────────────

_XELATEX_PREAMBLE_REPLACEMENTS: list[tuple[str, str]] = [
    # 移除 pdflatex 专用包
    (r"\\usepackage\[T1\]\{fontenc\}.*\n?", ""),
    (r"\\usepackage\[utf8\]\{inputenc\}.*\n?", ""),
    (r"\\usepackage\[english\]\{babel\}.*\n?", ""),
    # txfonts 与 fontspec 冲突
    (r"\\usepackage\{txfonts\}.*\n?", ""),
    # tipa 使用 T3 编码，与 fontspec 冲突
    (r"\\usepackage\{tipa\}.*\n?", "% AOK: tipa 已移除（T3编码与fontspec冲突）\n"),
    # wasysym 字体编码冲突
    (r"\\usepackage\{wasysym\}.*\n?", "% AOK: wasysym 已移除（字体编码冲突）\n"),
    # amsxtra 在 amsmath+amssymb 后冗余且可能冲突
    (r"\\usepackage\{amsxtra\}.*\n?", "% AOK: amsxtra 已移除（冗余）\n"),
    # enumerate 与 enumitem 冲突（保留注释）
    (r"\\usepackage\{enumerate\}.*\n?", "% AOK: enumerate 已注释（使用 enumitem）\n"),
    # color 升级为 xcolor（更兼容 xelatex）
    (r"\\usepackage\{color\}", r"\\usepackage[usenames,dvipsnames]{xcolor}"),
]

_XELATEX_PREAMBLE_INSERTION = r"""% ── AOK xelatex 后处理：中文与字体支持 ──
\usepackage{fontspec}
\usepackage{xeCJK}
\usepackage{enumitem}
\setCJKmainfont{Songti SC}[BoldFont=Heiti SC,ItalicFont=Kaiti SC]
\setmainfont{Times New Roman}
\setsansfont{Arial}
\setmonofont{Courier New}
% ── AOK xelatex 后处理结束 ──
"""

# ── scrbook 中文兼容补充 ──
_SCRBOOK_XELATEX_PATCH = r"""% ── AOK: scrbook + xelatex 中文兼容 ──
\KOMAoptions{fontsize=11pt}
\setkomafont{disposition}{\normalcolor\bfseries}
\setkomafont{descriptionlabel}{\normalcolor\bfseries}
% ── AOK: scrbook 兼容结束 ──
"""

# ── 引用格式正则 ────────────────────────────────────────────

# 匹配纯文本引用，如 (肖威,2021)、(Wang等,2020) 或 (Wang等,2020；Liu等,2024)
_PLAIN_CITE_PATTERN = re.compile(
    r"\(([^)]{3,200}?\d{4}[a-z]?)\)"
)

# 匹配单条引用 (Author, Year) 或 (Author等, Year)
_SINGLE_CITE_PATTERN = re.compile(
    r"([A-Z][a-zA-Z]+(?:\s*等)?)\s*[,，]\s*(\d{4}[a-z]?)"
)

# 分隔符
_CITE_SEP_PATTERN = re.compile(r"[；;]\s*")


def _generate_cite_key(author: str, year: str) -> str:
    """根据作者和年份生成 cite_key。"""
    # 去掉"等"后缀
    author_clean = author.rstrip("等").strip()
    # 取姓氏
    surname = author_clean.split()[-1] if " " in author_clean else author_clean
    return f"{surname}{year}"


def postprocess_docx2tex_for_xelatex(
    input_tex_path: Path,
    output_tex_path: Path,
    *,
    bibtex_mode: bool = False,
    bib_output_path: Path | None = None,
) -> dict:
    """将 docx2tex 输出后处理为 xelatex 可编译格式。

    Args:
        input_tex_path: docx2tex 原始输出 .tex 文件
        output_tex_path: 后处理输出 .tex 文件
        bibtex_mode: True=提取引文生成.bib并替换为\\cite；False=保持纯文本
        bib_output_path: bibtex 模式下的 .bib 输出路径（可选）

    Returns:
        dict: {'mode': str, 'cite_count': int, 'output': str}
    """
    text = input_tex_path.read_text(encoding="utf-8", errors="ignore")

    # ── 1. 替换前导区 ──
    for pattern, replacement in _XELATEX_PREAMBLE_REPLACEMENTS:
        text = re.sub(pattern, replacement, text)

    # ── 1.5 scrbook 中文兼容补丁 ──
    if "scrbook" in text.split("\n")[0] if text else False:
        if r"\begin{document}" in text:
            text = text.replace(
                r"\begin{document}",
                _SCRBOOK_XELATEX_PATCH + "\n" + r"\begin{document}",
            )

    # 在 \begin{document} 之前插入 xelatex 包
    doc_begin = r"\begin{document}"
    if doc_begin in text:
        text = text.replace(doc_begin, _XELATEX_PREAMBLE_INSERTION + "\n" + doc_begin)

    # ── 2. 处理图片引用：注释掉不存在的图片路径 ──
    text = re.sub(
        r"(\\includegraphics\[.*?\]\{[^}]*\.docx\.tmp[^}]*\})",
        r"% AOK: 图片文件不可用，已注释\n% \1",
        text,
    )
    text = re.sub(
        r"(\\includegraphics\[.*?\]\{embeddings/[^}]*\})",
        r"% AOK: OLE嵌入对象不可用，已注释\n% \1",
        text,
    )

    # ── 3. 处理引用 ──
    cite_count = 0
    cite_keys: set[str] = set()
    bib_entries: list[str] = []

    if bibtex_mode:
        # 收集所有纯文本引用，替换为 \cite{key}
        def replace_cites(match: re.Match) -> str:
            nonlocal cite_count
            inner = match.group(1)
            keys: list[str] = []
            for part in _CITE_SEP_PATTERN.split(inner):
                part = part.strip()
                sm = _SINGLE_CITE_PATTERN.match(part)
                if sm:
                    author, year = sm.group(1), sm.group(2)
                    key = _generate_cite_key(author, year)
                    if key not in cite_keys:
                        cite_keys.add(key)
                        bib_entries.append(
                            f"@article{{{key},\n"
                            f"  author = {{{author}}},\n"
                            f"  year = {{{year}}},\n"
                            f"  title = {{[待补充]}},\n"
                            f"}}"
                        )
                    keys.append(key)
                else:
                    keys.append(part)
            cite_count += len(keys)
            if keys:
                return "\\cite{" + ",".join(keys) + "}"
            return match.group(0)

        text = _PLAIN_CITE_PATTERN.sub(replace_cites, text)

        # 在 \end{document} 之前插入参考文献
        bib_cmd = (
            "\n% ── AOK: 自动生成的参考文献 ──\n"
            + "\\bibliographystyle{plain}\n"
        )
        if bib_output_path:
            bib_cmd += f"\\bibliography{{{bib_output_path.stem}}}\n"
            bib_output_path.write_text("\n\n".join(bib_entries), encoding="utf-8")
        else:
            bib_cmd += (
                "\\begin{thebibliography}{99}\n"
                + "\n".join(
                    f"\\bibitem{{{k}}} {b.split('title = {')[0].strip()}\n  title = {{[原始文档引用]}}"
                    for k, b in zip(cite_keys, bib_entries)
                )
                + "\n\\end{thebibliography}\n"
            )
        end_doc = r"\end{document}"
        if end_doc in text:
            text = text.replace(end_doc, bib_cmd + "\n" + end_doc)
    else:
        # no-bibtex 模式：统计引用数量，不做替换
        cite_count = len(_PLAIN_CITE_PATTERN.findall(text))

    output_tex_path.write_text(text, encoding="utf-8")
    return {
        "mode": "bibtex" if bibtex_mode else "no-bibtex",
        "cite_count": cite_count,
        "output": str(output_tex_path),
    }
