"""Windows 长文件名临时规避工具。

用于把过长的输入文件名复制成一个更短的别名，避免 Windows 子进程或
下游工具在路径较长时失败。这个模块只处理“临时别名化”，不修改系统
级长路径设置。
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WindowsShortPathAlias:
    """Windows 短路径别名结果。"""

    original_path: Path
    alias_path: Path
    used_alias: bool

    @property
    def path_to_use(self) -> Path:
        return self.alias_path if self.used_alias else self.original_path

    @property
    def stem_to_use(self) -> str:
        return self.path_to_use.stem


def needs_short_alias(path: str | Path, *, max_path_chars: int = 200, max_name_chars: int = 60) -> bool:
    """判断给定路径是否建议转成短别名。

    Args:
        path: 待检查路径。
        max_path_chars: 触发别名化的整条路径长度阈值。
        max_name_chars: 触发别名化的单个文件名长度阈值。
    """

    source = Path(path)
    return len(str(source)) > max_path_chars or len(source.stem) > max_name_chars


def build_short_alias_name(path: str | Path, *, prefix: str = "doc", digest_chars: int = 10) -> str:
    """为源文件构造短别名文件名。"""

    source = Path(path)
    digest = hashlib.md5(str(source).encode("utf-8")).hexdigest()[:digest_chars]
    suffix = source.suffix or ".pdf"
    return f"{prefix}_{digest}{suffix}"


def materialize_short_alias(
    source_path: str | Path,
    alias_dir: str | Path,
    *,
    prefix: str = "doc",
    max_path_chars: int = 200,
    max_name_chars: int = 60,
    digest_chars: int = 10,
) -> WindowsShortPathAlias:
    """必要时把源文件复制成短别名。

    Args:
        source_path: 原始文件路径。
        alias_dir: 别名文件存放目录。
        prefix: 别名前缀。
        max_path_chars: 路径长度阈值。
        max_name_chars: 文件名长度阈值。
        digest_chars: 摘要长度。

    Returns:
        WindowsShortPathAlias: 包含原始路径、别名路径以及是否启用别名。
    """

    source = Path(source_path).expanduser().resolve()
    alias_root = Path(alias_dir).expanduser().resolve()
    alias_root.mkdir(parents=True, exist_ok=True)

    if not needs_short_alias(source, max_path_chars=max_path_chars, max_name_chars=max_name_chars):
        return WindowsShortPathAlias(original_path=source, alias_path=source, used_alias=False)

    alias_name = build_short_alias_name(source, prefix=prefix, digest_chars=digest_chars)
    alias_path = alias_root / alias_name
    if not alias_path.exists():
        shutil.copy2(source, alias_path)
    return WindowsShortPathAlias(original_path=source, alias_path=alias_path, used_alias=True)


__all__ = [
    "WindowsShortPathAlias",
    "needs_short_alias",
    "build_short_alias_name",
    "materialize_short_alias",
]
