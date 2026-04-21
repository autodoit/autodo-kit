"""LaTeX subfile 合并原子工具。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple


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


def _resolve_subfile_path(parent_dir: Path, raw_subfile: str) -> Path:
    """解析 `\\subfile{...}` 引用路径。"""

    raw_clean = raw_subfile.strip()
    candidate_path = Path(raw_clean)
    if candidate_path.suffix.lower() != ".tex":
        candidate_path = candidate_path.with_suffix(".tex")
    return (parent_dir / candidate_path).resolve()


def merge_latex_subfiles(main_tex_path: Path, output_tex_path: Path) -> Tuple[Path, List[str]]:
    r"""递归展开 `\subfile{...}` 并输出合并后的 tex。"""

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
