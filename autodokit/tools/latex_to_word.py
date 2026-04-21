"""LaTeX -> Word 转换原子工具。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Sequence

from .pandoc_runner import PandocResult, run_pandoc


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


def _normalize_resource_dirs(resource_paths: Sequence[Path]) -> List[Path]:
    """规范化 Pandoc 资源目录列表。"""

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
    """将 LaTeX 转换为 Word。"""

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
