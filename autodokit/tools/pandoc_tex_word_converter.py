"""TeX与Word双向转换工具模块。

本模块提供 LaTeX 与 Word 双向转换相关的可复用能力，供事务层调用。

能力范围：
- 递归展开 `\\subfile{...}` 并合并 LaTeX。
- 统一封装 Pandoc 命令执行。
- LaTeX -> Word 转换。
- Word -> LaTeX 转换。
- docx 后处理（标题编号、TODO/NOTE/文献标色）。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


@dataclass
class PandocResult:
    """Pandoc 执行结果。

    Args:
        command: 实际执行的命令参数列表。
        return_code: 进程返回码。
        stdout_text: 标准输出文本。
        stderr_text: 标准错误文本。
    """

    command: List[str]
    return_code: int
    stdout_text: str
    stderr_text: str


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
    """校验文件路径为绝对路径。

    Args:
        path_str: 原始路径字符串。
        field_name: 字段名称。
        must_exist: 是否要求文件存在。

    Returns:
        解析后的绝对路径对象。

    Raises:
        ValueError: 路径为空、非绝对路径或文件不存在。
    """

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
    """读取文本文件内容。

    Args:
        file_path: 文件路径。

    Returns:
        文件文本内容。
    """

    return file_path.read_text(encoding="utf-8", errors="ignore")


def _write_temp_latex_template(template_text: str) -> Path:
    """写入临时 LaTeX 模板文件。

    Args:
        template_text: 模板文本内容。

    Returns:
        Path: 临时模板路径。
    """

    temp_dir = Path(tempfile.mkdtemp(prefix="aok_pandoc_tpl_"))
    template_path = temp_dir / "default_xelatex_template.tex"
    template_path.write_text(template_text, encoding="utf-8")
    return template_path


def _needs_pandoc_table_support(tex_text: str) -> bool:
    """判断 tex 是否包含 Pandoc 表格依赖。

    Args:
        tex_text: 待检测 tex 文本。

    Returns:
        bool: 若检测到 longtable/booktabs/array/calc 相关语法则返回 True。
    """

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
    """为 Pandoc 输出 tex 自动补齐 XeLaTeX 表格依赖。

    Args:
        output_tex_path: Pandoc 生成的 tex 文件路径。

    Returns:
        None
    """

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


def _resolve_subfile_path(parent_dir: Path, raw_subfile: str) -> Path:
    """解析 `\\subfile{...}` 引用路径。

    Args:
        parent_dir: 父级 tex 文件所在目录。
        raw_subfile: `\\subfile{...}` 中的原始字符串。

    Returns:
        子文件绝对路径。
    """

    raw_clean = raw_subfile.strip()
    candidate_path = Path(raw_clean)
    if candidate_path.suffix.lower() != ".tex":
        candidate_path = candidate_path.with_suffix(".tex")
    return (parent_dir / candidate_path).resolve()


def merge_latex_subfiles(main_tex_path: Path, output_tex_path: Path) -> Tuple[Path, List[str]]:
    r"""递归展开 `\subfile{...}` 并输出合并后的 tex。

    Args:
        main_tex_path: 主 tex 文件绝对路径。
        output_tex_path: 合并后输出 tex 绝对路径。

    Returns:
        Tuple[Path, List[str]]: `(输出文件路径, 合并日志列表)`。

    Raises:
        ValueError: 输入路径不合法。
        FileNotFoundError: 子文件不存在。
    """

    main_tex = _require_absolute_file(str(main_tex_path), field_name="main_tex_path", must_exist=True)
    output_tex = _require_absolute_file(str(output_tex_path), field_name="output_tex_path", must_exist=False)
    output_tex.parent.mkdir(parents=True, exist_ok=True)

    merged_logs: List[str] = []
    visited: set[Path] = set()

    def _strip_preamble_and_tail(content_text: str) -> str:
        head_pattern = r"(\\documentclass.*?\\begin\{document\}|\\graphicspath\{.*?\})"
        without_head = re.sub(head_pattern, "", content_text, flags=re.DOTALL)
        tail_pattern = r"\\end\{document\}"
        return re.sub(tail_pattern, "", without_head)

    def _merge_one(tex_path: Path) -> str:
        if tex_path in visited:
            merged_logs.append(f"检测到重复引用，跳过再次展开：{tex_path}")
            return ""
        visited.add(tex_path)

        if not tex_path.exists():
            raise FileNotFoundError(f"子文件不存在：{tex_path}")

        merged_logs.append(f"展开文件：{tex_path}")
        content_text = _strip_preamble_and_tail(_read_text(tex_path))

        pattern = re.compile(r"(?m)^\s*(?!%)\\subfile\{(.*?)}")
        result_parts: List[str] = []
        cursor = 0
        for match_obj in pattern.finditer(content_text):
            start_pos, end_pos = match_obj.span()
            result_parts.append(content_text[cursor:start_pos])
            sub_tex_path = _resolve_subfile_path(tex_path.parent, match_obj.group(1))
            result_parts.append(_merge_one(sub_tex_path))
            cursor = end_pos
        result_parts.append(content_text[cursor:])
        result_parts.append("\n\n")
        return "".join(result_parts)

    merged_content = _merge_one(main_tex)
    merged_content = re.sub(r"//【", "【", merged_content)
    output_tex.write_text(merged_content, encoding="utf-8")
    merged_logs.append(f"合并完成：{output_tex}")
    return output_tex, merged_logs


def run_pandoc(command: Sequence[str]) -> PandocResult:
    """执行 Pandoc 命令。

    Args:
        command: 命令参数列表。

    Returns:
        PandocResult: 执行结果。
    """

    env_map = os.environ.copy()
    env_map.setdefault("LANG", "en_US.UTF-8")
    env_map.setdefault("LC_ALL", "en_US.UTF-8")

    process = subprocess.run(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env_map,
    )
    stdout_text = (process.stdout or b"").decode("utf-8", errors="replace")
    stderr_text = (process.stderr or b"").decode("utf-8", errors="replace")
    return PandocResult(
        command=list(command),
        return_code=int(process.returncode),
        stdout_text=stdout_text,
        stderr_text=stderr_text,
    )


def _normalize_resource_dirs(resource_paths: Sequence[Path]) -> List[Path]:
    """规范化 Pandoc 资源目录列表。

    Args:
        resource_paths: 资源目录或文件路径序列。

    Returns:
        List[Path]: 去重后的目录列表（保持顺序）。
    """

    normalized_dirs: List[Path] = []
    seen: set[str] = set()
    for resource_path in resource_paths:
        candidate = resource_path.resolve()
        if candidate.is_file():
            candidate = candidate.parent
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        normalized_dirs.append(candidate)
    return normalized_dirs


def convert_latex_to_word(
    input_tex_path: Path,
    output_docx_path: Path,
    *,
    resource_path: Path | None = None,
    resource_paths: Sequence[Path] | None = None,
    include_in_header: Path | None = None,
    reference_doc: Path | None = None,
    toc: bool = True,
) -> PandocResult:
    """将 LaTeX 转换为 Word。

    Args:
        input_tex_path: 输入 tex 文件绝对路径。
        output_docx_path: 输出 docx 文件绝对路径。
        resource_path: 兼容字段，可选资源目录或文件路径。
        resource_paths: 可选资源目录列表（推荐）。
        include_in_header: 可选 header 片段。
        reference_doc: 可选参考样式文档。
        toc: 是否启用目录。

    Returns:
        PandocResult: 执行结果。
    """

    input_tex = _require_absolute_file(str(input_tex_path), field_name="input_tex_path", must_exist=True)
    output_docx = _require_absolute_file(str(output_docx_path), field_name="output_docx_path", must_exist=False)
    output_docx.parent.mkdir(parents=True, exist_ok=True)

    raw_resource_paths: List[Path] = []
    if resource_paths is not None:
        raw_resource_paths.extend(resource_paths)
    if resource_path is not None:
        raw_resource_paths.append(resource_path)
    if not raw_resource_paths:
        raw_resource_paths.append(input_tex.parent)

    resource_dirs = _normalize_resource_dirs(raw_resource_paths)
    resource_path_arg = os.pathsep.join(str(path_obj) for path_obj in resource_dirs)

    command_parts: List[str] = [
        "pandoc",
        f"--resource-path={resource_path_arg}",
        str(input_tex),
        "-o",
        str(output_docx),
    ]

    if toc:
        command_parts.append("--toc")

    if include_in_header is not None:
        header_path = _require_absolute_file(str(include_in_header), field_name="include_in_header", must_exist=True)
        command_parts.append(f"--include-in-header={header_path}")

    if reference_doc is not None:
        ref_path = _require_absolute_file(str(reference_doc), field_name="reference_doc", must_exist=True)
        command_parts.append(f"--reference-doc={ref_path}")

    return run_pandoc(command_parts)


def convert_word_to_latex(
    input_word_path: Path,
    output_tex_path: Path,
    *,
    include_in_header: Path | None = None,
    latex_template: Path | None = None,
) -> PandocResult:
    """将 Word 转换为 LaTeX。

    Args:
        input_word_path: 输入 doc/docx 文件绝对路径。
        output_tex_path: 输出 tex 文件绝对路径。
        include_in_header: 可选 header 片段路径。
        latex_template: 可选 LaTeX 模板路径。

    Returns:
        PandocResult: 执行结果。
    """

    input_word = _require_absolute_file(str(input_word_path), field_name="input_word_path", must_exist=True)
    output_tex = _require_absolute_file(str(output_tex_path), field_name="output_tex_path", must_exist=False)
    output_tex.parent.mkdir(parents=True, exist_ok=True)

    effective_template = latex_template
    temp_template_path: Path | None = None
    if effective_template is None:
        temp_template_path = _write_temp_latex_template(DEFAULT_XELATEX_LATEX_TEMPLATE)
        effective_template = temp_template_path

    command_parts: List[str] = [
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


def add_heading_numbering(input_docx_path: Path, output_docx_path: Path) -> Path:
    """为 Word 文档标题添加文本编号。

    Args:
        input_docx_path: 输入 docx 绝对路径。
        output_docx_path: 输出 docx 绝对路径。

    Returns:
        Path: 输出 docx 路径。
    """

    import importlib

    try:
        docx_module = importlib.import_module("docx")
        enum_text_module = importlib.import_module("docx.enum.text")
    except Exception as exc:
        raise RuntimeError("缺少依赖 python-docx，请先安装后再执行文档后处理。") from exc

    document_factory = getattr(docx_module, "Document")
    wd_align_paragraph = getattr(enum_text_module, "WD_ALIGN_PARAGRAPH")

    input_docx = _require_absolute_file(str(input_docx_path), field_name="input_docx_path", must_exist=True)
    output_docx = _require_absolute_file(str(output_docx_path), field_name="output_docx_path", must_exist=False)
    output_docx.parent.mkdir(parents=True, exist_ok=True)

    document = document_factory(str(input_docx))
    heading_numbers = [0] * 9

    for paragraph in document.paragraphs:
        for level_index in range(1, 10):
            if paragraph.style.name == f"Heading {level_index}":
                heading_numbers[level_index - 1] += 1
                for reset_index in range(level_index, 9):
                    heading_numbers[reset_index] = 0
                number_parts = [str(num) for num in heading_numbers[: level_index + 1] if num > 0]
                number_prefix = ".".join(number_parts)
                paragraph.text = f"{number_prefix}. {paragraph.text}"
                paragraph.alignment = wd_align_paragraph.LEFT
                break

    document.save(str(output_docx))
    return output_docx


def _iter_matches(pattern: str, full_text: str) -> Iterable[Tuple[int, int]]:
    """迭代文本匹配区间。

    Args:
        pattern: 正则表达式。
        full_text: 输入文本。

    Returns:
        Iterable[Tuple[int, int]]: `(start, end)` 区间序列。
    """

    for match_obj in re.finditer(pattern, full_text):
        yield match_obj.span()


def highlight_tokens_in_docx(input_docx_path: Path, output_docx_path: Path) -> Path:
    """对 Word 文档中的 TODO/NOTE/文献片段做高亮或标色。

    Args:
        input_docx_path: 输入 docx 绝对路径。
        output_docx_path: 输出 docx 绝对路径。

    Returns:
        Path: 输出 docx 路径。
    """

    import importlib

    try:
        docx_module = importlib.import_module("docx")
        enum_text_module = importlib.import_module("docx.enum.text")
        shared_module = importlib.import_module("docx.shared")
    except Exception as exc:
        raise RuntimeError("缺少依赖 python-docx，请先安装后再执行文档后处理。") from exc

    document_factory = getattr(docx_module, "Document")
    wd_color_index = getattr(enum_text_module, "WD_COLOR_INDEX")
    rgb_color = getattr(shared_module, "RGBColor")

    input_docx = _require_absolute_file(str(input_docx_path), field_name="input_docx_path", must_exist=True)
    output_docx = _require_absolute_file(str(output_docx_path), field_name="output_docx_path", must_exist=False)
    output_docx.parent.mkdir(parents=True, exist_ok=True)

    document = document_factory(str(input_docx))

    for paragraph in document.paragraphs:
        full_text = "".join(run.text for run in paragraph.runs)
        todo_ranges = list(_iter_matches(r"【TODO】「(.*?)」", full_text))
        note_ranges = list(_iter_matches(r"【NOTE】「(.*?)」", full_text))
        ref_ranges = list(_iter_matches(r"【文献】「(.*?)」.*?\(.*?\)", full_text))

        if not (todo_ranges or note_ranges or ref_ranges):
            continue

        current_pos = 0
        for run in paragraph.runs:
            run_length = len(run.text)
            run_start = current_pos
            run_end = current_pos + run_length

            for start_pos, end_pos in todo_ranges:
                if run_end > start_pos and run_start < end_pos:
                    run.font.highlight_color = wd_color_index.BRIGHT_GREEN
            for start_pos, end_pos in note_ranges:
                if run_end > start_pos and run_start < end_pos:
                    run.font.highlight_color = wd_color_index.TURQUOISE
            for start_pos, end_pos in ref_ranges:
                if run_end > start_pos and run_start < end_pos:
                    run.font.color.rgb = rgb_color(0, 0, 255)

            current_pos = run_end

    document.save(str(output_docx))
    return output_docx
