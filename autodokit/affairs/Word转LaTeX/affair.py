"""事务： Word 转 LaTeX。

该事务用于编排 Word -> LaTeX 转换流程，支持：
- Pandoc 反向转换。
- 可选 LaTeX 模板。
- 可选 include-in-header。
- dry-run 预览。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from autodokit.tools import load_json_or_py
from autodokit.tools.pandoc_tex_word_converter import PandocResult, convert_word_to_latex


@dataclass
class WordToLatexConfig:
    """Word 转 LaTeX 事务配置。

    Args:
        input_word_file: 输入 word 文件绝对路径。
        output_tex_file: 输出 tex 文件绝对路径。
        latex_template: Pandoc LaTeX 模板绝对路径（可选）。
        include_in_header: Pandoc include-in-header 文件绝对路径（可选）。
        dry_run: 是否仅输出执行计划。
        output_log: 可选日志文件绝对路径。
    """

    input_word_file: str
    output_tex_file: str
    latex_template: str | None = None
    include_in_header: str | None = None
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
    cfg = WordToLatexConfig(
        input_word_file=str(raw_cfg.get("input_word_file") or ""),
        output_tex_file=str(raw_cfg.get("output_tex_file") or ""),
        latex_template=str(raw_cfg.get("latex_template") or "").strip() or None,
        include_in_header=str(raw_cfg.get("include_in_header") or "").strip() or None,
        dry_run=bool(raw_cfg.get("dry_run", False)),
        output_log=str(raw_cfg.get("output_log") or "").strip() or None,
    )

    input_word = _require_abs(cfg.input_word_file, field_name="input_word_file", must_exist=True)
    output_tex = _require_abs(cfg.output_tex_file, field_name="output_tex_file", must_exist=False)
    output_tex.parent.mkdir(parents=True, exist_ok=True)

    latex_template = _require_abs(cfg.latex_template, field_name="latex_template", must_exist=True) if cfg.latex_template else None
    include_in_header = _require_abs(cfg.include_in_header, field_name="include_in_header", must_exist=True) if cfg.include_in_header else None
    effective_latex_template = str(latex_template) if latex_template is not None else "__AOK_DEFAULT_XELATEX_TEMPLATE__"

    output_log_path: Path | None = None
    if cfg.output_log:
        output_log_path = _require_abs(cfg.output_log, field_name="output_log", must_exist=False)
        output_log_path.parent.mkdir(parents=True, exist_ok=True)

    def _log(line: str) -> None:
        print(line)
        if output_log_path is not None:
            with output_log_path.open("a", encoding="utf-8") as writer:
                writer.write(line.rstrip("\n") + "\n")

    if cfg.dry_run:
        _log("[DRY-RUN] 事务不会执行外部命令，仅输出计划。")
        _log(f"input_word_file={input_word}")
        _log(f"output_tex_file={output_tex}")
        _log(f"latex_template={latex_template}")
        if latex_template is None:
            _log("effective_latex_template=__AOK_DEFAULT_XELATEX_TEMPLATE__")
            _log("note=未提供 latex_template；AOK 将使用内置 XeLaTeX 模板，并为 Pandoc 表格自动补齐 longtable/booktabs/array/calc 支持。")
        else:
            _log(f"effective_latex_template={latex_template}")
        _log(f"include_in_header={include_in_header}")

        manifest = {
            "dry_run": True,
            "input_word_file": str(input_word),
            "output_tex_file": str(output_tex),
            "latex_template": str(latex_template) if latex_template is not None else None,
            "effective_latex_template": effective_latex_template,
            "include_in_header": str(include_in_header) if include_in_header is not None else None,
        }
        manifest_path = (output_tex.parent / "word_to_latex_manifest.json").resolve()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        outputs = [manifest_path]
        if output_log_path is not None:
            outputs.append(output_log_path)
        return outputs

    _log(f"effective_latex_template={effective_latex_template}")
    if latex_template is None:
        _log("note=未提供 latex_template；AOK 将使用内置 XeLaTeX 模板，并为 Pandoc 表格自动补齐 longtable/booktabs/array/calc 支持。")

    pandoc_result: PandocResult = convert_word_to_latex(
        input_word_path=input_word,
        output_tex_path=output_tex,
        include_in_header=include_in_header,
        latex_template=latex_template,
    )
    _log(f"pandoc_return_code={pandoc_result.return_code}")
    if pandoc_result.stdout_text.strip():
        _log(pandoc_result.stdout_text.strip())
    if pandoc_result.return_code != 0:
        if pandoc_result.stderr_text.strip():
            _log(pandoc_result.stderr_text.strip())
        raise RuntimeError("Word 转 LaTeX 失败，请检查 pandoc 输出")

    manifest = {
        "dry_run": False,
        "input_word_file": str(input_word),
        "output_tex_file": str(output_tex),
        "latex_template": str(latex_template) if latex_template is not None else None,
        "effective_latex_template": effective_latex_template,
        "include_in_header": str(include_in_header) if include_in_header is not None else None,
        "pandoc_return_code": pandoc_result.return_code,
        "pandoc_command": pandoc_result.command,
        "pandoc_stdout": pandoc_result.stdout_text,
        "pandoc_stderr": pandoc_result.stderr_text,
    }
    manifest_path = (output_tex.parent / "word_to_latex_manifest.json").resolve()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    outputs = [output_tex, manifest_path]
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
        raise SystemExit("用法：python Word转LaTeX.py <config_path>")
    for output_path in execute(Path(sys.argv[1])):
        print(output_path)


if __name__ == "__main__":
    main()

