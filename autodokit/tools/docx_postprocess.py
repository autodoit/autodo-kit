"""docx 后处理原子工具。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Tuple


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


def add_heading_numbering(input_docx_path: Path, output_docx_path: Path) -> Path:
    """为 Word 文档标题添加文本编号。"""

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
    """迭代文本匹配区间。"""

    for match_obj in re.finditer(pattern, full_text):
        yield match_obj.span()


def highlight_tokens_in_docx(input_docx_path: Path, output_docx_path: Path) -> Path:
    """对 Word 文档中的 TODO/NOTE/文献片段做高亮或标色。"""

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
