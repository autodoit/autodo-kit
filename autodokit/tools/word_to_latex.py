"""Word -> LaTeX 转换原子工具。"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .pandoc_runner import PandocResult, run_pandoc


DEFAULT_XELATEX_LATEX_TEMPLATE = r"""\documentclass[11pt,a4paper]{article}
% AOK 默认 XeLaTeX 模板（兼容 Pandoc 生成的中文文档与表格）
$if(fontfamily)$\usepackage{$fontfamily$}$endif$
\usepackage{xeCJK}
\usepackage{fontspec}
\usepackage{microtype}
\usepackage{hyperref}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{caption}
\usepackage{geometry}
\geometry{a4paper,margin=2.5cm}
\setCJKmainfont{SimSun}[AutoFakeBold=2,AutoFakeSlant=0.2]
\setmainfont{Times New Roman}
\setsansfont{Arial}
\setmonofont{Courier New}

% AOK：补齐 Pandoc 生成表格所需依赖
\usepackage{longtable}
\usepackage{booktabs}
\usepackage{array}
\usepackage{calc}
\usepackage{etoolbox}
\makeatletter
\patchcmd\longtable{\par}{\if@noskipsec\mbox{}\fi\par}{}{}
\makeatother
\IfFileExists{footnotehyper.sty}{\usepackage{footnotehyper}}{\usepackage{footnote}}
\makesavenoteenv{longtable}
\providecommand{\tightlist}{%
  \setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}

\begin{document}
$if(title)$\begin{center}\LARGE\textbf{$title$}\end{center}\vspace{1em}$endif$
$if(abstract)$\begin{abstract}$abstract$\end{abstract}$endif$
$body$
\end{document}
"""


PANDOC_TABLE_SUPPORT_MARKER = "% AOK：补齐 Pandoc 生成表格所需依赖"


PANDOC_TABLE_SUPPORT_BLOCK = r"""
% AOK：补齐 Pandoc 生成表格所需依赖
\usepackage{longtable}
\usepackage{booktabs}
\usepackage{array}
\usepackage{calc}
\usepackage{etoolbox}
\makeatletter
\patchcmd\longtable{\par}{\if@noskipsec\mbox{}\fi\par}{}{}
\makeatother
\IfFileExists{footnotehyper.sty}{\usepackage{footnotehyper}}{\usepackage{footnote}}
\makesavenoteenv{longtable}
\providecommand{\tightlist}{%
  \setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}
""".strip()


def _require_absolute_file(path_str: str, *, field_name: str, must_exist: bool = True) -> Path:
    """校验文件路径为绝对路径。"""

    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError(f"{field_name} 为空")

    path_obj = Path(path_str)
    if not path_obj.is_absolute():
        raise ValueError(f"{field_name} 必须是绝对路径：{path_str!r}")

    resolved_path_obj = path_obj.resolve()
    if must_exist and not resolved_path_obj.exists():
        raise ValueError(f"{field_name} 不存在：{resolved_path_obj}")
    return resolved_path_obj


def _read_text(file_path: Path) -> str:
    """读取文本文件内容。"""

    return file_path.read_text(encoding="utf-8", errors="ignore")


def _write_temp_latex_template(template_text: str) -> Path:
    """写入临时 LaTeX 模板文件。"""

    temp_dir = Path(tempfile.mkdtemp(prefix="aok_pandoc_tpl_"))
    template_path = temp_dir / "default_xelatex_template.tex"
    template_path.write_text(template_text, encoding="utf-8")
    return template_path


def _needs_pandoc_table_support(tex_text: str) -> bool:
    """判断 tex 是否包含 Pandoc 表格依赖。"""

    markers = (
        r"\begin{longtable}",
        r"\endhead",
        r"\endlastfoot",
        r"\toprule",
        r"\midrule",
        r"\bottomrule",
        r"\arraybackslash",
        r"\real{",
    )
    return any(marker in tex_text for marker in markers)


def _ensure_pandoc_latex_table_support(output_tex_path: Path) -> None:
    """为 Pandoc 输出 tex 自动补齐 XeLaTeX 表格依赖。"""

    tex_text = _read_text(output_tex_path)
    if PANDOC_TABLE_SUPPORT_MARKER in tex_text:
        return
    if not _needs_pandoc_table_support(tex_text):
        return

    begin_document_token = r"\begin{document}"
    begin_document_index = tex_text.find(begin_document_token)
    if begin_document_index < 0:
        return

    patched_text = (
        tex_text[:begin_document_index].rstrip()
        + "\n\n"
        + PANDOC_TABLE_SUPPORT_BLOCK
        + "\n\n"
        + tex_text[begin_document_index:]
    )
    output_tex_path.write_text(patched_text, encoding="utf-8")


def convert_word_to_latex(
    input_word_path: Path,
    output_tex_path: Path,
    *,
    include_in_header: Path | None = None,
    latex_template: Path | None = None,
) -> PandocResult:
    """将 Word 转换为 LaTeX。"""

    input_word = _require_absolute_file(str(input_word_path), field_name="input_word_path", must_exist=True)
    output_tex = _require_absolute_file(str(output_tex_path), field_name="output_tex_path", must_exist=False)
    output_tex.parent.mkdir(parents=True, exist_ok=True)

    effective_template = latex_template
    temp_template_path: Path | None = None
    if effective_template is None:
        temp_template_path = _write_temp_latex_template(DEFAULT_XELATEX_LATEX_TEMPLATE)
        effective_template = temp_template_path

    command_parts: list[str] = [
        "pandoc",
        str(input_word),
        "-o",
        str(output_tex),
        "--from=docx",
        "--to=latex",
        "--standalone",
        f"--resource-path={input_word.parent.resolve()}",
    ]

    try:
        if effective_template is not None:
            template_path = _require_absolute_file(str(effective_template), field_name="latex_template", must_exist=True)
            command_parts.extend(["--template", str(template_path)])

        if include_in_header is not None:
            header_path = _require_absolute_file(str(include_in_header), field_name="include_in_header", must_exist=True)
            command_parts.extend(["--include-in-header", str(header_path)])

        result = run_pandoc(command_parts)
        if result.return_code == 0 and output_tex.exists():
            _ensure_pandoc_latex_table_support(output_tex)
        return result
    finally:
        if temp_template_path is not None:
            shutil.rmtree(temp_template_path.parent, ignore_errors=True)
