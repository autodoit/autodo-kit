"""docx2tex Word→LaTeX 转换原子工具。

封装 docx2tex 转换逻辑，提供与 Pandoc 后端对等的 API。

使用示例:
    >>> from pathlib import Path
    >>> from autodokit.tools.docx2tex_converter import convert_word_to_latex_via_docx2tex
    >>>
    >>> result = convert_word_to_latex_via_docx2tex(
    ...     input_word_path=Path("paper.docx"),
    ...     output_tex_path=Path("paper.tex"),
    ...     table_model="tabularx",
    ... )
    >>> print(result.return_code, result.output_tex_path)
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .docx2tex_postprocess import postprocess_docx2tex_for_xelatex
from .docx2tex_runner import Docx2TexResult, check_docx2tex_available, run_docx2tex


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


def convert_word_to_latex_via_docx2tex(
    input_word_path: Path,
    output_tex_path: Path,
    *,
    output_dir: Path | None = None,
    config_file: Path | None = None,
    table_model: str | None = None,
    debug: bool = False,
    xelatex_postprocess: bool = True,
    bibtex_mode: bool = False,
) -> Docx2TexResult:
    """使用 docx2tex 将 Word 转换为 LaTeX。

    转换完成后默认执行 xelatex 后处理，将 pdflatex 输出转为可编译中文的 xelatex 格式。
    若只需原始 docx2tex 输出，设置 xelatex_postprocess=False。

    Args:
        input_word_path: 输入的 Word 文件绝对路径。
        output_tex_path: 输出的 LaTeX 文件绝对路径。
        output_dir: 自定义输出目录（可选，默认与输入文件同目录）。
        config_file: 自定义 docx2tex 配置文件（可选）。
        table_model: 表格模型（tabularx|tabular|htmltabs，可选）。
        debug: 是否启用调试模式。
        xelatex_postprocess: 是否执行 xelatex 后处理（默认 True）。
        bibtex_mode: 后处理中的引用模式（True=提取.bib, False=保留纯文本）。

    Returns:
        Docx2TexResult: 执行结果，output_tex_path 指向最终输出文件。
    """
    input_word = _require_absolute_file(str(input_word_path), field_name="input_word_path", must_exist=True)
    output_tex = _require_absolute_file(str(output_tex_path), field_name="output_tex_path", must_exist=False)
    output_tex.parent.mkdir(parents=True, exist_ok=True)

    # 构建命令参数
    command_parts: list[str] = []

    # 输出目录
    if output_dir is not None:
        out_dir = _require_absolute_file(str(output_dir), field_name="output_dir", must_exist=False)
        out_dir.mkdir(parents=True, exist_ok=True)
        command_parts.extend(["-o", str(out_dir)])

    # 配置文件
    if config_file is not None:
        conf_path = _require_absolute_file(str(config_file), field_name="config_file", must_exist=True)
        command_parts.extend(["-c", str(conf_path)])

    # 表格模型
    if table_model is not None:
        if table_model not in ("tabularx", "tabular", "htmltabs"):
            raise ValueError(f"不支持的表格模型：{table_model}，仅支持 tabularx|tabular|htmltabs")
        command_parts.extend(["-t", table_model])

    # 调试模式
    if debug:
        command_parts.append("-d")

    # 输入文件（必须放在最后）
    command_parts.append(str(input_word))

    # 执行转换
    result = run_docx2tex(command_parts)

    # docx2tex 默认输出到输入文件同目录，文件名为 input_stem.tex
    # 如果用户指定了不同的输出路径，需要移动文件
    default_output = input_word.parent / f"{input_word.stem}.tex"
    if result.return_code == 0 and default_output.exists():
        if default_output.resolve() != output_tex.resolve():
            shutil.move(str(default_output), str(output_tex))
        result.output_tex_path = output_tex
    elif result.return_code == 0 and output_tex.exists():
        result.output_tex_path = output_tex

    # ── xelatex 后处理 ──
    if result.return_code == 0 and xelatex_postprocess and output_tex.exists():
        bib_output = output_tex.with_suffix(".bib") if bibtex_mode else None
        postprocess_docx2tex_for_xelatex(
            input_tex_path=output_tex,
            output_tex_path=output_tex,
            bibtex_mode=bibtex_mode,
            bib_output_path=bib_output,
        )
        result.output_tex_path = output_tex

    return result
