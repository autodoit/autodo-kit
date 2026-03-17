"""事务： LaTeX 转 Word。

该事务用于编排 LaTeX -> Word 转换流程，支持：
- 可选的 `\\subfile` 递归合并。
- Pandoc 转换。
- 可选的 docx 后处理（标题编号、TODO/NOTE/文献标色）。
- dry-run 预览。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from autodokit.tools import load_json_or_py
from autodokit.tools.pandoc_tex_word_converter import (
    PandocResult,
    add_heading_numbering,
    convert_latex_to_word,
    highlight_tokens_in_docx,
    merge_latex_subfiles,
)


@dataclass
class LatexToWordConfig:
    """LaTeX 转 Word 事务配置。

    Args:
        input_tex_file: 输入 tex 文件绝对路径。
        output_docx_file: 输出 docx 文件绝对路径。
        merge_subfiles: 是否先进行 subfile 合并。
        merged_tex_output: 合并后 tex 输出绝对路径（merge_subfiles=true 时可选）。
        resource_path: Pandoc 资源路径（可选）。
        include_in_header: Pandoc include-in-header 文件绝对路径（可选）。
        reference_doc: Pandoc reference-doc 文件绝对路径（可选）。
        drop_tex_elements: 需要在 Pandoc 前过滤的 tex 元素标识列表（可选）。
        toc: 是否生成目录。
        add_heading_numbering: 是否执行标题编号后处理。
        highlight_tokens: 是否执行 TODO/NOTE/文献高亮后处理。
        dry_run: 是否仅输出计划执行步骤，不真正执行。
        output_log: 可选日志文件绝对路径。
    """

    input_tex_file: str
    output_docx_file: str
    merge_subfiles: bool = False
    merged_tex_output: str | None = None
    resource_path: str | None = None
    include_in_header: str | None = None
    reference_doc: str | None = None
    drop_tex_elements: List[str] | None = None
    toc: bool = True
    add_heading_numbering: bool = False
    highlight_tokens: bool = False
    dry_run: bool = False
    output_log: str | None = None


def _require_abs(path_text: str, *, field_name: str, must_exist: bool) -> Path:
    """校验绝对路径。

    Args:
        path_text: 路径字符串。
        field_name: 字段名。
        must_exist: 是否要求路径存在。

    Returns:
        Path: 绝对路径对象。

    Raises:
        ValueError: 路径不合法。
    """

    if not isinstance(path_text, str) or not path_text.strip():
        raise ValueError(f"{field_name} 为空")
    path_obj = Path(path_text)
    if not path_obj.is_absolute():
        raise ValueError(f"{field_name} 必须是绝对路径：{path_text!r}")
    resolved_path = path_obj.resolve()
    if must_exist and not resolved_path.exists():
        raise ValueError(f"{field_name} 不存在：{resolved_path}")
    return resolved_path


def _as_string_list(raw_value: Any) -> List[str]:
    """将任意输入规整为字符串列表。"""

    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        return [part.strip() for part in raw_value.split(",") if part.strip()]
    if isinstance(raw_value, list):
        normalized: List[str] = []
        for item in raw_value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized
    return []


def _norm_text(text: str) -> str:
    """用于宽松匹配的文本归一化。"""

    return re.sub(r"\s+", "", (text or "").strip()).lower()


def _strip_latex_title(text: str) -> str:
    """移除章节标题中的常见 LaTeX 包装命令，保留可读文本。"""

    unwrapped = text
    for _ in range(3):
        new_text = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^]]*])?\{([^{}]*)}", r"\1", unwrapped)
        if new_text == unwrapped:
            break
        unwrapped = new_text
    return re.sub(r"[{}\\]", "", unwrapped)


def _remove_intervals(content_text: str, intervals: List[tuple[int, int]]) -> str:
    """按区间删除文本并合并重叠区间。"""

    if not intervals:
        return content_text
    sorted_intervals = sorted(intervals, key=lambda item: item[0])
    merged: List[tuple[int, int]] = []
    for start_pos, end_pos in sorted_intervals:
        if not merged or start_pos > merged[-1][1]:
            merged.append((start_pos, end_pos))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end_pos))

    parts: List[str] = []
    cursor = 0
    for start_pos, end_pos in merged:
        parts.append(content_text[cursor:start_pos])
        cursor = end_pos
    parts.append(content_text[cursor:])
    return "".join(parts)


def _filter_tex_elements(content_text: str, drop_tokens: List[str]) -> tuple[str, Dict[str, Any]]:
    """按标签/章节名过滤 tex 片段。"""

    normalized_tokens = [_norm_text(token) for token in drop_tokens if _norm_text(token)]
    if not normalized_tokens:
        return content_text, {
            "drop_tokens": [],
            "removed_tag_blocks": 0,
            "removed_sections": 0,
            "removed_label_blocks": 0,
        }

    filtered_text = content_text
    removed_tag_blocks = 0

    # 支持注释标签块：% AOK-FILTER-START:封面 ... % AOK-FILTER-END:封面
    tag_block_pattern = re.compile(
        r"(?ms)^\s*%+\s*AOK-FILTER-START\s*:\s*(?P<tag>[^\r\n]+?)\s*$.*?^\s*%+\s*AOK-FILTER-END\s*:\s*(?P=tag)\s*$\n?"
    )

    def _replace_tag_block(match_obj: re.Match[str]) -> str:
        nonlocal removed_tag_blocks
        tag_norm = _norm_text(match_obj.group("tag"))
        if any(token in tag_norm or tag_norm in token for token in normalized_tokens):
            removed_tag_blocks += 1
            return "\n"
        return match_obj.group(0)

    filtered_text = tag_block_pattern.sub(_replace_tag_block, filtered_text)

    # 支持按 \label{...} 过滤：从命中 label 起，删除到下一个 label 或文末。
    label_pattern = re.compile(r"(?m)^\s*\\label\{(?P<label>[^}]*)}\s*$")
    labels: List[Dict[str, Any]] = []
    for match_obj in label_pattern.finditer(filtered_text):
        labels.append({"start": match_obj.start(), "label": match_obj.group("label")})

    label_intervals: List[tuple[int, int]] = []
    removed_label_blocks = 0
    for index, label_item in enumerate(labels):
        label_norm = _norm_text(label_item["label"])
        should_drop = any(token in label_norm or label_norm in token for token in normalized_tokens)
        if not should_drop:
            continue
        start_pos = int(label_item["start"])
        end_pos = int(labels[index + 1]["start"]) if index + 1 < len(labels) else len(filtered_text)
        label_intervals.append((start_pos, end_pos))
        removed_label_blocks += 1

    filtered_text = _remove_intervals(filtered_text, label_intervals)

    heading_pattern = re.compile(r"(?m)^\s*\\(?P<cmd>part|chapter|section|subsection|subsubsection)\*?\{(?P<title>[^}]*)}")
    level_map = {"part": 0, "chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4}
    headings: List[Dict[str, Any]] = []
    for match_obj in heading_pattern.finditer(filtered_text):
        headings.append(
            {
                "start": match_obj.start(),
                "level": level_map[match_obj.group("cmd")],
                "title": _strip_latex_title(match_obj.group("title")),
            }
        )

    section_intervals: List[tuple[int, int]] = []
    removed_sections = 0
    for index, heading in enumerate(headings):
        title_norm = _norm_text(heading["title"])
        should_drop = any(token in title_norm or title_norm in token for token in normalized_tokens)
        if not should_drop:
            continue

        end_pos = len(filtered_text)
        for next_heading in headings[index + 1 :]:
            if next_heading["level"] <= heading["level"]:
                end_pos = int(next_heading["start"])
                break
        section_intervals.append((int(heading["start"]), end_pos))
        removed_sections += 1

    filtered_text = _remove_intervals(filtered_text, section_intervals)
    return filtered_text, {
        "drop_tokens": drop_tokens,
        "removed_tag_blocks": removed_tag_blocks,
        "removed_sections": removed_sections,
        "removed_label_blocks": removed_label_blocks,
    }


def execute(config_path: Path) -> List[Path]:
    """事务入口。

    Args:
        config_path: 配置文件路径（json/py）。

    Returns:
        List[Path]: 产物路径列表（含 manifest 与可选日志）。

    Raises:
        ValueError: 配置不合法。
        RuntimeError: Pandoc 执行失败。
    """

    raw_cfg: Dict[str, Any] = dict(load_json_or_py(config_path))
    cfg = LatexToWordConfig(
        input_tex_file=str(raw_cfg.get("input_tex_file") or ""),
        output_docx_file=str(raw_cfg.get("output_docx_file") or ""),
        merge_subfiles=bool(raw_cfg.get("merge_subfiles", False)),
        merged_tex_output=str(raw_cfg.get("merged_tex_output") or "").strip() or None,
        resource_path=str(raw_cfg.get("resource_path") or "").strip() or None,
        include_in_header=str(raw_cfg.get("include_in_header") or "").strip() or None,
        reference_doc=str(raw_cfg.get("reference_doc") or "").strip() or None,
        drop_tex_elements=_as_string_list(raw_cfg.get("drop_tex_elements")),
        toc=bool(raw_cfg.get("toc", True)),
        add_heading_numbering=bool(raw_cfg.get("add_heading_numbering", False)),
        highlight_tokens=bool(raw_cfg.get("highlight_tokens", False)),
        dry_run=bool(raw_cfg.get("dry_run", False)),
        output_log=str(raw_cfg.get("output_log") or "").strip() or None,
    )

    input_tex = _require_abs(cfg.input_tex_file, field_name="input_tex_file", must_exist=True)
    output_docx = _require_abs(cfg.output_docx_file, field_name="output_docx_file", must_exist=False)
    output_docx.parent.mkdir(parents=True, exist_ok=True)

    merged_tex = None
    if cfg.merged_tex_output:
        merged_tex = _require_abs(cfg.merged_tex_output, field_name="merged_tex_output", must_exist=False)
    elif cfg.merge_subfiles:
        merged_tex = (output_docx.parent / f"{input_tex.stem}.merged.tex").resolve()

    resource_path_input = _require_abs(cfg.resource_path, field_name="resource_path", must_exist=True) if cfg.resource_path else None
    include_in_header = _require_abs(cfg.include_in_header, field_name="include_in_header", must_exist=True) if cfg.include_in_header else None
    reference_doc = _require_abs(cfg.reference_doc, field_name="reference_doc", must_exist=True) if cfg.reference_doc else None

    resource_dir: Path | None = None
    reference_doc_from_resource_path = False
    if resource_path_input is not None:
        if resource_path_input.is_file():
            # 兼容历史配置：用户把 .dotx/.docx 放在 resource_path 时，自动映射为 reference-doc。
            if resource_path_input.suffix.lower() in {".dotx", ".docx"} and reference_doc is None:
                reference_doc = resource_path_input
                reference_doc_from_resource_path = True
            resource_dir = resource_path_input.parent
        else:
            resource_dir = resource_path_input

    output_log_path: Path | None = None
    if cfg.output_log:
        output_log_path = _require_abs(cfg.output_log, field_name="output_log", must_exist=False)
        output_log_path.parent.mkdir(parents=True, exist_ok=True)

    def _log(line: str) -> None:
        print(line)
        if output_log_path is not None:
            with output_log_path.open("a", encoding="utf-8") as writer:
                writer.write(line.rstrip("\n") + "\n")

    input_for_pandoc = merged_tex if cfg.merge_subfiles and merged_tex is not None else input_tex
    filtered_tex_output = (output_docx.parent / f"{input_for_pandoc.stem}.filtered.tex").resolve() if cfg.drop_tex_elements else None

    if cfg.dry_run:
        _log("[DRY-RUN] 事务不会执行外部命令，仅输出计划。")
        _log(f"input_tex={input_tex}")
        _log(f"merge_subfiles={cfg.merge_subfiles}")
        if merged_tex is not None:
            _log(f"merged_tex_output={merged_tex}")
        _log(f"input_for_pandoc={input_for_pandoc}")
        _log(f"output_docx={output_docx}")
        _log(f"resource_path_input={resource_path_input}")
        _log(f"resource_dir={resource_dir}")
        _log(f"include_in_header={include_in_header}")
        _log(f"reference_doc={reference_doc}")
        _log(f"reference_doc_from_resource_path={reference_doc_from_resource_path}")
        _log(f"drop_tex_elements={cfg.drop_tex_elements}")
        if filtered_tex_output is not None:
            _log(f"filtered_tex_output={filtered_tex_output}")
        _log(f"toc={cfg.toc}")
        _log(f"add_heading_numbering={cfg.add_heading_numbering}")
        _log(f"highlight_tokens={cfg.highlight_tokens}")

        resource_paths_for_pandoc: List[Path] = []
        if resource_dir is not None:
            resource_paths_for_pandoc.append(resource_dir)
        resource_paths_for_pandoc.append(input_tex.parent)
        resource_paths_for_pandoc.append(input_for_pandoc.parent)
        if filtered_tex_output is not None:
            resource_paths_for_pandoc.append(filtered_tex_output.parent)

        manifest = {
            "dry_run": True,
            "input_tex_file": str(input_tex),
            "merge_subfiles": cfg.merge_subfiles,
            "merged_tex_output": str(merged_tex) if merged_tex is not None else None,
            "input_for_pandoc": str(input_for_pandoc),
            "filtered_tex_output": str(filtered_tex_output) if filtered_tex_output is not None else None,
            "output_docx_file": str(output_docx),
            "resource_path": str(resource_path_input) if resource_path_input is not None else None,
            "resource_paths_for_pandoc": [str(path_obj) for path_obj in resource_paths_for_pandoc],
            "include_in_header": str(include_in_header) if include_in_header is not None else None,
            "reference_doc": str(reference_doc) if reference_doc is not None else None,
            "reference_doc_from_resource_path": reference_doc_from_resource_path,
            "drop_tex_elements": cfg.drop_tex_elements,
            "toc": cfg.toc,
            "add_heading_numbering": cfg.add_heading_numbering,
            "highlight_tokens": cfg.highlight_tokens,
        }
        manifest_path = (output_docx.parent / "latex_to_word_manifest.json").resolve()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        outputs = [manifest_path]
        if output_log_path is not None:
            outputs.append(output_log_path)
        return outputs

    outputs: List[Path] = []
    merge_logs: List[str] = []
    if cfg.merge_subfiles and merged_tex is not None:
        merged_file, merge_logs = merge_latex_subfiles(input_tex, merged_tex)
        outputs.append(merged_file)

    preprocessed_input_tex = input_for_pandoc
    filter_logs: Dict[str, Any] | None = None
    if cfg.drop_tex_elements:
        if filtered_tex_output is None:
            raise RuntimeError("内部错误：filtered_tex_output 未初始化")
        source_text = preprocessed_input_tex.read_text(encoding="utf-8", errors="ignore")
        filtered_text, filter_logs = _filter_tex_elements(source_text, cfg.drop_tex_elements)
        filtered_tex_output.write_text(filtered_text, encoding="utf-8")
        preprocessed_input_tex = filtered_tex_output
        outputs.append(filtered_tex_output)

    resource_paths_for_pandoc: List[Path] = []
    if resource_dir is not None:
        resource_paths_for_pandoc.append(resource_dir)
    resource_paths_for_pandoc.append(input_tex.parent)
    resource_paths_for_pandoc.append(input_for_pandoc.parent)
    resource_paths_for_pandoc.append(preprocessed_input_tex.parent)

    pandoc_result: PandocResult = convert_latex_to_word(
        input_tex_path=preprocessed_input_tex,
        output_docx_path=output_docx,
        resource_paths=resource_paths_for_pandoc,
        include_in_header=include_in_header,
        reference_doc=reference_doc,
        toc=cfg.toc,
    )
    _log(f"pandoc_return_code={pandoc_result.return_code}")
    if pandoc_result.stdout_text.strip():
        _log(pandoc_result.stdout_text.strip())
    if pandoc_result.return_code != 0:
        if pandoc_result.stderr_text.strip():
            _log(pandoc_result.stderr_text.strip())
        raise RuntimeError("LaTeX 转 Word 失败，请检查 pandoc 输出")

    current_docx = output_docx
    if cfg.add_heading_numbering:
        numbered_docx = (output_docx.parent / f"{output_docx.stem}.numbered{output_docx.suffix}").resolve()
        current_docx = add_heading_numbering(current_docx, numbered_docx)
        outputs.append(current_docx)

    if cfg.highlight_tokens:
        highlighted_docx = (output_docx.parent / f"{output_docx.stem}.highlighted{output_docx.suffix}").resolve()
        current_docx = highlight_tokens_in_docx(current_docx, highlighted_docx)
        outputs.append(current_docx)

    manifest = {
        "dry_run": False,
        "input_tex_file": str(input_tex),
        "merge_subfiles": cfg.merge_subfiles,
        "merged_tex_output": str(merged_tex) if merged_tex is not None else None,
        "input_for_pandoc": str(preprocessed_input_tex),
        "input_for_pandoc_raw": str(input_for_pandoc),
        "output_docx_file": str(output_docx),
        "resource_path": str(resource_path_input) if resource_path_input is not None else None,
        "resource_paths_for_pandoc": [str(path_obj) for path_obj in resource_paths_for_pandoc],
        "include_in_header": str(include_in_header) if include_in_header is not None else None,
        "reference_doc": str(reference_doc) if reference_doc is not None else None,
        "reference_doc_from_resource_path": reference_doc_from_resource_path,
        "drop_tex_elements": cfg.drop_tex_elements,
        "filter_logs": filter_logs,
        "toc": cfg.toc,
        "add_heading_numbering": cfg.add_heading_numbering,
        "highlight_tokens": cfg.highlight_tokens,
        "merge_logs": merge_logs,
        "pandoc_return_code": pandoc_result.return_code,
        "pandoc_command": pandoc_result.command,
        "pandoc_stdout": pandoc_result.stdout_text,
        "pandoc_stderr": pandoc_result.stderr_text,
        "final_docx": str(current_docx),
    }

    manifest_path = (output_docx.parent / "latex_to_word_manifest.json").resolve()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    outputs.extend([output_docx, manifest_path])
    if output_log_path is not None:
        outputs.append(output_log_path)
    return outputs


def main() -> None:
    """命令行入口。

    Returns:
        None
    """

    import sys

    if len(sys.argv) < 2:
        raise SystemExit("用法：python LaTeX转Word.py <config_path>")
    for output_path in execute(Path(sys.argv[1])):
        print(output_path)


if __name__ == "__main__":
    main()

