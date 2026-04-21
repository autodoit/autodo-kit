"""Pandoc 命令执行原子工具。"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import List, Sequence


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
