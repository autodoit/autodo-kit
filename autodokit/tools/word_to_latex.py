"""Word -> LaTeX 转换原子工具。

支持双后端：
- docx2tex（默认）：专为 Word→LaTeX 设计，学术文档格式保真度更高。
- pandoc（备选）：通用文档转换器，当 docx2tex 不可用时自动降级。

编译支持：
- compile_after=True 时转换后自动运行 xelatex 编译输出文件。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .docx2tex_converter import convert_word_to_latex_via_docx2tex
from .docx2tex_runner import Docx2TexResult, check_docx2tex_available
from .pandoc_runner import PandocResult, run_pandoc

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """Word→LaTeX 转换统一返回结构。

    Args:
        backend_used: 实际使用的后端 ("docx2tex" | "pandoc")。
        return_code: 进程返回码。
        output_tex_path: 输出的 LaTeX 文件路径。
        stderr_text: 标准错误文本。
        stdout_text: 标准输出文本。
        fell_back: 是否发生了降级（docx2tex 失败后降级到 Pandoc）。
        fallback_reason: 降级原因说明。
    """

    backend_used: Literal["docx2tex", "pandoc"]
    return_code: int
    output_tex_path: Path | None
    stderr_text: str
    stdout_text: str = ""
    fell_back: bool = False
    fallback_reason: str | None = None


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
    backend: Literal["docx2tex", "pandoc"] = "docx2tex",
    include_in_header: Path | None = None,
    latex_template: Path | None = None,
    docx2tex_config: Path | None = None,
    docx2tex_table_model: str | None = None,
    fallback_on_error: bool = True,
    xelatex_postprocess: bool = True,
    bibtex_mode: bool = False,
    compile_after: bool = False,
) -> ConversionResult:
    """将 Word 转换为 LaTeX。

    使用示例:
        >>> from autodokit.tools.word_to_latex import convert_word_to_latex
        >>> from pathlib import Path
        >>>
        >>> # 基本用法（仅转换，不编译）
        >>> result = convert_word_to_latex(
        ...     Path("paper.docx"), Path("paper.tex"),
        ... )
        >>> print(result.backend_used, result.fell_back)
        >>>
        >>> # 提取引文生成 .bib + 编译
        >>> result = convert_word_to_latex(
        ...     Path("paper.docx"), Path("paper.tex"),
        ...     bibtex_mode=True, compile_after=True,
        ... )

    Args:
        input_word_path: 输入的 Word 文件绝对路径。
        output_tex_path: 输出的 LaTeX 文件绝对路径。
        backend: 转换后端，默认 "docx2tex"。可选 "pandoc"。
        include_in_header: Pandoc 专用，插入到 LaTeX 头部的文件。
        latex_template: Pandoc 专用，自定义 LaTeX 模板。
        docx2tex_config: docx2tex 专用，自定义配置文件。
        docx2tex_table_model: docx2tex 专用，表格模型（tabularx|tabular|htmltabs）。
        fallback_on_error: docx2tex 失败时是否自动降级到 Pandoc（默认 True）。
        xelatex_postprocess: 是否执行 xelatex 后处理（默认 True，仅 docx2tex 后端生效）。
        bibtex_mode: 后处理引用模式。True=提取.bib, False=保留纯文本引文。
        compile_after: 转换后运行 xelatex 编译（默认 False）。

    Returns:
        ConversionResult: 统一转换结果。
    """
    if backend == "pandoc":
        pandoc_result = _convert_via_pandoc(
            input_word_path,
            output_tex_path,
            include_in_header=include_in_header,
            latex_template=latex_template,
        )
        _compile_if_requested(output_tex_path, compile_after)
        return ConversionResult(
            backend_used="pandoc",
            return_code=pandoc_result.return_code,
            output_tex_path=output_tex_path if output_tex_path.exists() else None,
            stderr_text=pandoc_result.stderr_text,
            stdout_text=pandoc_result.stdout_text,
        )

    # 默认走 docx2tex
    if not check_docx2tex_available():
        reason = "docx2tex 不可用（缺少 Java 或 d2t 脚本）"
        logger.warning("%s，自动降级到 Pandoc", reason)
        if fallback_on_error:
            pandoc_result = _convert_via_pandoc(
                input_word_path,
                output_tex_path,
                include_in_header=include_in_header,
                latex_template=latex_template,
            )
            return ConversionResult(
                backend_used="pandoc",
                return_code=pandoc_result.return_code,
                output_tex_path=output_tex_path if output_tex_path.exists() else None,
                stderr_text=pandoc_result.stderr_text,
                stdout_text=pandoc_result.stdout_text,
                fell_back=True,
                fallback_reason=reason,
            )
        raise RuntimeError(f"docx2tex 不可用且未启用降级：{reason}")

    # 尝试 docx2tex
    try:
        d2t_result = convert_word_to_latex_via_docx2tex(
            input_word_path,
            output_tex_path,
            config_file=docx2tex_config,
            table_model=docx2tex_table_model,
            xelatex_postprocess=xelatex_postprocess,
            bibtex_mode=bibtex_mode,
        )
    except Exception as exc:
        reason = f"docx2tex 执行异常：{exc}"
        logger.warning("%s，自动降级到 Pandoc", reason)
        if not fallback_on_error:
            raise RuntimeError(reason) from exc
        pandoc_result = _convert_via_pandoc(
            input_word_path,
            output_tex_path,
            include_in_header=include_in_header,
            latex_template=latex_template,
        )
        return ConversionResult(
            backend_used="pandoc",
            return_code=pandoc_result.return_code,
            output_tex_path=output_tex_path if output_tex_path.exists() else None,
            stderr_text=pandoc_result.stderr_text,
            stdout_text=pandoc_result.stdout_text,
            fell_back=True,
            fallback_reason=reason,
        )

    if d2t_result.return_code == 0:
        _compile_if_requested(output_tex_path, compile_after)
        return ConversionResult(
            backend_used="docx2tex",
            return_code=d2t_result.return_code,
            output_tex_path=d2t_result.output_tex_path,
            stderr_text=d2t_result.stderr_text,
            stdout_text=d2t_result.stdout_text,
        )

    # docx2tex 转换失败
    reason = f"docx2tex 转换失败（返回码 {d2t_result.return_code}）：{d2t_result.stderr_text[:200]}"
    logger.warning("%s，自动降级到 Pandoc", reason)
    if not fallback_on_error:
        return ConversionResult(
            backend_used="docx2tex",
            return_code=d2t_result.return_code,
            output_tex_path=None,
            stderr_text=d2t_result.stderr_text,
            stdout_text=d2t_result.stdout_text,
        )

    pandoc_result = _convert_via_pandoc(
        input_word_path,
        output_tex_path,
        include_in_header=include_in_header,
        latex_template=latex_template,
    )
    _compile_if_requested(output_tex_path, compile_after)
    return ConversionResult(
        backend_used="pandoc",
        return_code=pandoc_result.return_code,
        output_tex_path=output_tex_path if output_tex_path.exists() else None,
        stderr_text=pandoc_result.stderr_text,
        stdout_text=pandoc_result.stdout_text,
        fell_back=True,
        fallback_reason=reason,
    )


def _compile_if_requested(tex_path: Path | None, compile_after: bool) -> None:
    """当 compile_after=True 时运行 xelatex 编译。

    xelatex 在 nonstopmode 下即使编译成功也可能返回非零退出码（例如因交叉引用
    警告），因此以 PDF 文件是否生成为编译成功标志。
    """
    if not compile_after or tex_path is None or not tex_path.exists():
        return
    pdf_path = tex_path.with_suffix(".pdf")
    logger.info("编译：xelatex %s → %s", tex_path.name, pdf_path.name)
    proc = subprocess.run(
        ["xelatex", "-interaction=nonstopmode", tex_path.name],
        cwd=str(tex_path.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if pdf_path.exists():
        logger.info("✓ xelatex 编译成功 → %s (返回码 %d)", pdf_path, proc.returncode)
    else:
        logger.warning(
            "✗ xelatex 编译失败（返回码 %d），PDF 未生成，详见 %s",
            proc.returncode, tex_path.with_suffix(".log"),
        )


def _convert_via_pandoc(
    input_word_path: Path,
    output_tex_path: Path,
    *,
    include_in_header: Path | None = None,
    latex_template: Path | None = None,
) -> PandocResult:
    """通过 Pandoc 后端执行 Word→LaTeX 转换（内部函数）。"""
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
