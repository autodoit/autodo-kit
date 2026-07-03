"""docx2tex 命令执行原子工具。

docx2tex 是专门为 Word→LaTeX 设计的开源工具，基于 XSLT 转换链，
在学术文档场景下格式保真度更高。

依赖：
- Java 运行时（1.7+，推荐 1.8 或 13+，避免 Java 11）
- docx2tex 工具链（已内置于 third_party/docx2tex）
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence


# docx2tex 工具链根目录（相对于 autodo-kit 仓库）
_DOCX2TEX_ROOT = Path(__file__).parent.parent.parent / "third_party" / "docx2tex"


@dataclass
class Docx2TexResult:
    """docx2tex 执行结果。

    Args:
        command: 实际执行的命令参数列表。
        return_code: 进程返回码。
        stdout_text: 标准输出文本。
        stderr_text: 标准错误文本。
        output_tex_path: 输出的 LaTeX 文件路径（仅当转换成功时存在）。
    """

    command: List[str]
    return_code: int
    stdout_text: str
    stderr_text: str
    output_tex_path: Path | None = None


def get_docx2tex_root() -> Path:
    """获取 docx2tex 工具链根目录。"""
    return _DOCX2TEX_ROOT


def get_d2t_script() -> Path:
    """获取 d2t 脚本路径。"""
    d2t_path = _DOCX2TEX_ROOT / "d2t"
    if not d2t_path.exists():
        raise FileNotFoundError(
            f"docx2tex d2t 脚本不存在：{d2t_path}\n"
            f"请确认 third_party/docx2tex 目录已正确部署。"
        )
    return d2t_path


def check_docx2tex_available() -> bool:
    """检查 docx2tex 是否可用。

    检查项：
    1. Java 运行时是否已安装
    2. d2t 脚本是否存在且可执行

    Returns:
        bool: docx2tex 可用返回 True，否则返回 False。
    """
    # 检查 Java
    if not shutil.which("java"):
        return False

    # 检查 d2t 脚本
    d2t_path = _DOCX2TEX_ROOT / "d2t"
    if not d2t_path.exists():
        return False

    # 检查 d2t 是否可执行
    if not os.access(d2t_path, os.X_OK):
        return False

    return True


def run_docx2tex(command: Sequence[str]) -> Docx2TexResult:
    """执行 docx2tex 命令。

    Args:
        command: 命令参数列表（不包含 d2t 脚本本身）。

    Returns:
        Docx2TexResult: 执行结果。
    """
    d2t_script = get_d2t_script()
    full_command = [str(d2t_script)] + list(command)

    env_map = os.environ.copy()
    env_map.setdefault("LANG", "en_US.UTF-8")
    env_map.setdefault("LC_ALL", "en_US.UTF-8")

    process = subprocess.run(
        full_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env_map,
        cwd=str(_DOCX2TEX_ROOT),
    )
    stdout_text = (process.stdout or b"").decode("utf-8", errors="replace")
    stderr_text = (process.stderr or b"").decode("utf-8", errors="replace")

    return Docx2TexResult(
        command=full_command,
        return_code=int(process.returncode),
        stdout_text=stdout_text,
        stderr_text=stderr_text,
    )
