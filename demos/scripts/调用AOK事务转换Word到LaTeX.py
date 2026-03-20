from __future__ import annotations

import datetime
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from autodokit.affairs.Word转LaTeX.affair import execute


"""通过 AOK 的 Word转LaTeX 事务执行 Word -> LaTeX 转换。

该脚本借鉴旧脚本的参数风格（root_path/input/output 等），
但实际转换由 `autodokit.affairs.Word转LaTeX.affair.execute` 完成。
"""


def _resolve_to_abs(root_path: Path, path_text: str | None, *, field_name: str) -> str | None:
    """将输入路径预处理为内部统一绝对路径。

    Args:
        root_path: 工作目录根路径。
        path_text: 用户输入路径，可为相对路径或绝对路径。
        field_name: 字段名，用于错误提示。

    Returns:
        str | None: 绝对路径字符串；若输入为空则返回 None。

    Raises:
        ValueError: 路径类型非法或为空白字符串。

    Examples:
        >>> _resolve_to_abs(Path("C:/repo"), "docs/a.docx", field_name="input")
        'C:/repo/docs/a.docx'
    """

    if path_text is None:
        return None
    if not isinstance(path_text, str):
        raise ValueError(f"{field_name} 必须是字符串")
    cleaned = path_text.strip()
    if not cleaned:
        return None
    raw_path = Path(cleaned)
    final_path = raw_path if raw_path.is_absolute() else (root_path / raw_path)
    return str(final_path.resolve())


def _build_affair_payload(config: dict[str, Any]) -> dict[str, Any]:
    """将旧脚本风格配置映射为事务配置。

    Args:
        config: 运行配置字典。

    Returns:
        dict[str, Any]: 可直接写入 `affair.py` 的配置字段。

    Raises:
        ValueError: 必填字段缺失。

    Examples:
        >>> _build_affair_payload({"root_path": "C:/repo", "input_word_file": "a.docx"})
        {'input_word_file': 'C:/repo/a.docx', ...}
    """

    root_path = Path(config.get("root_path") or Path(__file__).resolve().parent).resolve()

    input_word_file = config.get("input_word_file")
    if not input_word_file:
        raise ValueError("input_word_file 不能为空")

    output_tex_file = config.get("output_tex_file")
    if not output_tex_file:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = Path(str(input_word_file)).stem
        output_tex_file = f"{base_name}_{ts}.tex"

    payload = {
        "input_word_file": _resolve_to_abs(root_path, str(input_word_file), field_name="input_word_file"),
        "output_tex_file": _resolve_to_abs(root_path, str(output_tex_file), field_name="output_tex_file"),
        "latex_template": _resolve_to_abs(root_path, config.get("latex_template"), field_name="latex_template"),
        "include_in_header": _resolve_to_abs(root_path, config.get("include_in_header"), field_name="include_in_header"),
        "dry_run": bool(config.get("dry_run", False)),
        "output_log": _resolve_to_abs(root_path, config.get("output_log"), field_name="output_log"),
    }

    # user_word_template 仅做兼容展示，事务本身不消费该字段。
    user_word_template = config.get("user_word_template")
    if user_word_template:
        print("提示：user_word_template 仅保留兼容，不会传入事务执行。")
        print("user_word_template=", _resolve_to_abs(root_path, user_word_template, field_name="user_word_template"))

    return payload


def run_with_config(config: dict[str, Any]) -> bool:
    """使用配置字典执行转换事务。

    Args:
        config: 运行配置。

    Returns:
        bool: 执行成功返回 True，失败返回 False。

    Raises:
        无。函数内部会捕获异常并返回 False。

    Examples:
        >>> run_with_config({"root_path": ".", "input_word_file": "a.docx"})
        True
    """

    verbose = bool(config.get("verbose", True))
    try:
        payload = _build_affair_payload(config)
        if verbose:
            print("=" * 80)
            print("Word -> LaTeX (AOK affair) 开始")
            print("input_word_file:", payload["input_word_file"])
            print("output_tex_file:", payload["output_tex_file"])
            print("latex_template:", payload["latex_template"])
            print("include_in_header:", payload["include_in_header"])
            print("dry_run:", payload["dry_run"])
            print("output_log:", payload["output_log"])

        temp_file_path: Path | None = None
        try:
            fd, temp_name = tempfile.mkstemp(prefix="word_to_latex_affair_", suffix=".json")
            temp_file_path = Path(temp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as writer:
                writer.write(json.dumps(payload, ensure_ascii=False, indent=2))

            outputs = execute(temp_file_path)
            print("转换是否成功: 是")
            for item in outputs:
                print("输出文件:", str(item))
            return True
        finally:
            if temp_file_path is not None and temp_file_path.exists():
                temp_file_path.unlink(missing_ok=True)
    except Exception as exc:
        print("转换是否成功: 否")
        print("错误:", repr(exc))
        return False
    finally:
        if verbose:
            print("Word -> LaTeX (AOK affair) 结束")
            print("=" * 80)


def main() -> None:
    """主入口：修改 config 后可直接运行。

    Returns:
        None

    Raises:
        SystemExit: 转换失败时抛出退出码 1。

    Examples:
        >>> main()
    """

    script_dir = Path(__file__).resolve().parent
    config = {
        "root_path": script_dir,
        "input_word_file": "10.9 ZTX-博士学位论文（调整格式版）.docx",
        "output_tex_file": "output/10.9 ZTX-博士学位论文（调整格式版）/正文.tex",
        "user_word_template": None,
        "latex_template": None,
        "include_in_header": None,
        "dry_run": False,
        "output_log": None,
        "verbose": True,
    }

    ok = run_with_config(config)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

