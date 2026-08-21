"""autodo-suite 统一密钥仓库与脱敏工具。

本模块提供整个 autodo 系列统一的密钥安全能力：

- 统一密钥仓库目录管理（伞型品牌目录 ``~/.config/autodo-suite/secrets/``）。
- 密钥文件的路径解析与候选枚举。
- API Key 脱敏（供日志、异常、审计输出使用）。

设计原则：

- 密钥明文只允许存在于内存与密钥仓库文件中，绝不进入代码、日志、索引或文档。
- 任何需要展示密钥的场景，一律使用 :func:`mask_api_key` 脱敏。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

#: 统一密钥仓库目录的可覆盖环境变量。
SECRETS_DIR_ENV = "AUTODO_SUITE_SECRETS_DIR"

#: 默认统一密钥仓库目录（autodo-suite 伞型品牌）。
DEFAULT_SECRETS_DIR = Path.home() / ".config" / "autodo-suite" / "secrets"

#: 逻辑密钥名 -> 标准文件名 映射。
_SECRET_FILE_NAMES = {
    "bailian": "bailian-api-key.txt",
    "aliyun": "bailian-api-key.txt",
    "dashscope": "dashscope-api-key.txt",
    "lmstudio": "lmstudio-api-key.txt",
    "lm_studio": "lmstudio-api-key.txt",
    "lm-studio": "lmstudio-api-key.txt",
}


def secrets_dir() -> Path:
    """返回统一密钥仓库目录。

    Returns:
        统一密钥仓库目录绝对路径。
    """

    env = os.environ.get(SECRETS_DIR_ENV, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_SECRETS_DIR


def ensure_secrets_layout() -> Path:
    """初始化统一密钥仓库目录，并收紧权限为 ``700``。

    Returns:
        统一密钥仓库目录绝对路径。
    """

    directory = secrets_dir()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def secret_path(name: str) -> Path:
    """返回指定逻辑密钥名对应的密钥文件路径。

    Args:
        name: 逻辑密钥名（如 ``bailian``、``lmstudio``）。

    Returns:
        密钥文件路径（不保证文件存在）。
    """

    key = str(name).strip().lower()
    filename = _SECRET_FILE_NAMES.get(key, f"{key}.txt")
    return secrets_dir() / filename


def iter_secret_candidates(name: str = "bailian") -> List[Path]:
    """枚举某个逻辑密钥名在统一仓库中的候选文件路径（含别名）。

    Args:
        name: 逻辑密钥名。

    Returns:
        候选路径列表（按优先级排序，去重）。
    """

    seen: set[Path] = set()
    result: List[Path] = []
    target = _SECRET_FILE_NAMES.get(str(name).strip().lower(), f"{str(name).strip().lower()}.txt")
    # 首推标准文件名的路径。
    primary = secrets_dir() / target
    if primary not in seen:
        seen.add(primary)
        result.append(primary)
    # 追加同文件名的别名路径（仅当文件名不同，避免重复）。
    for alias, filename in _SECRET_FILE_NAMES.items():
        if filename == target:
            alias_path = secrets_dir() / filename
            if alias_path not in seen:
                seen.add(alias_path)
                result.append(alias_path)
    return result


def mask_api_key(key: str | None, *, keep_head: int = 3, keep_tail: int = 4, placeholder: str = "***") -> str:
    """对 API Key 进行脱敏。

    Args:
        key: 原始密钥。
        keep_head: 保留前几位。
        keep_tail: 保留后几位。
        placeholder: 中间占位符。

    Returns:
        脱敏后的字符串；空密钥返回空串。

    Examples:
        >>> mask_api_key("sk-abcdef1234567890")
        'sk-***7890'
        >>> mask_api_key("")
        ''
    """

    if not key:
        return ""
    text = str(key).strip()
    if len(text) <= keep_head + keep_tail:
        return placeholder
    return f"{text[:keep_head]}{placeholder}{text[-keep_tail:]}"
