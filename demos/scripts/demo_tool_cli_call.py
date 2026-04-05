"""CLI 工具直调示例。"""

from __future__ import annotations

import json
import subprocess
import sys


def run_command(command: list[str]) -> str:
    """执行命令并返回标准输出。

    Args:
        command: 命令参数列表。

    Returns:
        str: 标准输出文本。

    Raises:
        RuntimeError: 当命令返回非零状态码时抛出。

    Examples:
        >>> isinstance(run_command([sys.executable, '-c', 'print(1)']).strip(), str)
        True
    """

    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"命令执行失败（exit={completed.returncode}）\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed.stdout


def main() -> None:
    """运行 CLI 工具示例。

    Returns:
        None

    Examples:
        在仓库根目录执行：
            python demos/scripts/demo_tool_cli_call.py
    """

    list_output = run_command(
        [
            sys.executable,
            "-m",
            "autodokit.tools.adapters.cli",
            "list",
            "--scope",
            "user",
        ]
    )
    print("[CLI list 输出]", list_output.strip())

    call_output = run_command(
        [
            sys.executable,
            "-m",
            "autodokit.tools.adapters.cli",
            "call",
            "parse_reference_text",
            "--scope",
            "user",
            "--args",
            '["Smith, 2024. Example Title from CLI."]',
        ]
    )
    print("[CLI call 输出]", call_output.strip())

    parsed = json.loads(call_output)
    parsed_text = str(parsed)
    if "clean_title=" not in parsed_text:
        raise SystemExit("CLI 调用结果异常：未获得 clean_title")

    print("[通过] CLI 工具直调示例执行成功")


if __name__ == "__main__":
    main()
