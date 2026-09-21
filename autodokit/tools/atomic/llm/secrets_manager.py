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
from typing import Any, Dict, Iterable, List

#: 统一密钥仓库目录的可覆盖环境变量。
SECRETS_DIR_ENV = "AUTODO_SUITE_SECRETS_DIR"

#: 默认统一密钥仓库目录（autodo-suite 伞型品牌）。
DEFAULT_SECRETS_DIR = Path.home() / ".config" / "autodo-suite" / "secrets"

#: 配置档案（profile）可覆盖环境变量。
#:
#: 当同一提供方存有多个密钥文件（如测试/生产、不同项目）时，用本变量选定。
SECRET_PROFILE_ENV = "AUTODO_SUITE_SECRET_PROFILE"

#: 默认配置档案名（多档案共存且未显式指定时首选）。
DEFAULT_SECRET_PROFILE = "normal"

#: 项目专属配置档案名（次级优先）。
PROJECT_SECRET_PROFILE = "autodo-kit"

#: 逻辑密钥名归一化别名（容忍同一提供方的多种写法）。
_SECRET_NAME_ALIASES = {
    "aliyun": "bailian",
    "lm_studio": "lmstudio",
    "lm-studio": "lmstudio",
    "moonshot": "kimi",
}

#: 逻辑密钥名 -> **历史标准文件名** 映射。
#:
#: 仅用于「全部候选都不存在」时给出兜底路径与报错提示；
#: 实际查找请用 :func:`iter_secret_candidates`（支持多种命名形式）。
_SECRET_FILE_NAMES = {
    "bailian": "bailian-api-key.txt",
    "dashscope": "dashscope-api-key.txt",
    "lmstudio": "lmstudio-api-key.txt",
    "deepseek": "deepseek-api-key.txt",
    "kimi": "kimi-api-key.txt",
}


def _normalize_secret_name(name: str) -> str:
    """把逻辑密钥名归一化为小写 canonical 名。

    Args:
        name: 原始逻辑密钥名。

    Returns:
        小写 canonical 名（未知别名时原样小写）。

    Examples:
        >>> _normalize_secret_name("DeepSeek")
        'deepseek'
        >>> _normalize_secret_name("aliyun")
        'bailian'
    """

    key = str(name or "").strip().lower()
    return _SECRET_NAME_ALIASES.get(key, key)


def _scan_secret_files() -> Dict[str, Path]:
    """扫描密钥仓库，返回 ``{小写文件名: 真实路径}`` 快照。

    大小写不敏感匹配依赖真实目录项名（macOS/iCloud 的大小写实际行为
    不能只靠 ``Path.exists()`` 推断）。隐藏文件（如 ``.DS_Store``）被忽略。

    Returns:
        小写文件名到真实路径的映射；目录不存在或不可读时为空字典。
    """

    snapshot: Dict[str, Path] = {}
    try:
        for entry in secrets_dir().iterdir():
            if not entry.is_file() or entry.name.startswith("."):
                continue
            snapshot.setdefault(entry.name.lower(), entry)
    except OSError:
        return {}
    return snapshot


def _profile_order(profile: str | None) -> List[str]:
    """构造配置档案的优先级序列（去重保序）。

    Args:
        profile: 显式指定的档案名；可为空。

    Returns:
        档案名列表，优先级从高到低。
    """

    order: List[str] = []
    for candidate in (
        str(profile).strip() if profile else "",
        os.environ.get(SECRET_PROFILE_ENV, "").strip(),
        DEFAULT_SECRET_PROFILE,
        PROJECT_SECRET_PROFILE,
    ):
        if candidate and candidate not in order:
            order.append(candidate)
    return order


def list_secret_inventory() -> List[Dict[str, Any]]:
    """列出密钥仓库的文件清单（**仅元信息，绝不读取内容**）。

    Returns:
        每个文件一项，含 ``name`` / ``path`` / ``size`` / ``logical_name`` /
        ``profile``；按文件名排序。

    Examples:
        >>> isinstance(list_secret_inventory(), list)
        True
    """

    inventory: List[Dict[str, Any]] = []
    for entry in sorted(_scan_secret_files().values(), key=lambda p: p.name.lower()):
        logical, profile = _split_secret_filename(entry.name)
        try:
            size = entry.stat().st_size
        except OSError:
            size = 0
        inventory.append(
            {
                "name": entry.name,
                "path": str(entry),
                "size": size,
                "logical_name": logical,
                "profile": profile,
            }
        )
    return inventory


def _split_secret_filename(filename: str) -> tuple[str, str]:
    """从文件名解析出逻辑密钥名与配置档案名。

    支持两种形式：``{名}_api-key_{档案}.txt``（新）与 ``{名}-api-key.txt``（旧）。

    Args:
        filename: 文件名。

    Returns:
        二元组 ``(逻辑名, 档案名)``；旧命名或无档案时档案为空串。

    Examples:
        >>> _split_secret_filename("bailian_api-key_autodo-kit.txt")
        ('bailian', 'autodo-kit')
        >>> _split_secret_filename("bailian-api-key.txt")
        ('bailian', '')
    """

    stem = str(filename or "")
    if stem.lower().endswith(".txt"):
        stem = stem[:-4]
    lowered = stem.lower()
    marker = "_api-key_"
    if marker in lowered:
        index = lowered.index(marker)
        return stem[:index].lower(), stem[index + len(marker):]
    legacy = "-api-key"
    if lowered.endswith(legacy):
        return stem[: -len(legacy)].lower(), ""
    return lowered, ""


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


def secret_path(name: str, *, profile: str | None = None) -> Path:
    """返回指定逻辑密钥名的**最优先可用**文件路径。

    与 :func:`iter_secret_candidates` 的分工：本函数只返回一个路径——
    优先返回实际存在的最高优先候选；全部不存在时返回历史标准路径
    （供报错提示与初始化写入用）。

    Args:
        name: 逻辑密钥名（如 ``bailian``、``deepseek``）。
        profile: 显式指定的配置档案名；为空时按默认优先级挑选。

    Returns:
        密钥文件路径。

    Examples:
        >>> secret_path("bailian").name.endswith(".txt")
        True
    """

    for candidate in iter_secret_candidates(name, profile=profile):
        if candidate.is_file():
            return candidate
    canon = _normalize_secret_name(name)
    filename = _SECRET_FILE_NAMES.get(canon, f"{canon}.txt")
    return secrets_dir() / filename


def iter_secret_candidates(name: str = "bailian", *, profile: str | None = None) -> List[Path]:
    """枚举某逻辑密钥名的候选文件路径（按优先级，存在者在前）。

    支持的命名形式（**大小写不敏感**）：

    1. ``{名}_api-key_{档案}.txt`` —— 当前推荐（档案可区分项目/环境）；
    2. ``{名}-api-key.txt``        —— 历史命名；
    3. ``{名}.txt``                —— 最简命名。

    档案优先级：显式 ``profile`` 参数 → 环境变量
    ``AUTODO_SUITE_SECRET_PROFILE`` → ``normal`` → ``autodo-kit`` → 其余按名排序。

    同一提供方存在多个档案文件时**全部返回**（按优先级），调用方可自行挑选，
    避免“静默选中一个而调用方不知情”。

    Args:
        name: 逻辑密钥名。
        profile: 显式指定的配置档案名。

    Returns:
        候选路径列表（去重保序；末尾附标准默认路径作兜底，可能不存在）。
    """

    canon = _normalize_secret_name(name)
    listing = _scan_secret_files()
    ordered: List[Path] = []
    seen: set[str] = set()

    def _append(path: Path) -> None:
        key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        ordered.append(path)

    # 1) 配置档案精确命中（显式 → 环境变量 → normal → autodo-kit）
    for profile_name in _profile_order(profile):
        matched = listing.get(f"{canon}_api-key_{profile_name}.txt")
        if matched is not None:
            _append(matched)

    # 2) 其余同提供方的档案文件（按文件名排序，保证确定性）
    prefix = f"{canon}_api-key_"
    for lowered in sorted(listing):
        if lowered.startswith(prefix) and lowered.endswith(".txt"):
            _append(listing[lowered])

    # 3) 历史命名与最简命名
    for legacy in (f"{canon}-api-key.txt", f"{canon}.txt"):
        matched = listing.get(legacy)
        if matched is not None:
            _append(matched)

    # 4) 兜底：标准默认路径（可能不存在，供报错与初始化用）
    _append(secrets_dir() / _SECRET_FILE_NAMES.get(canon, f"{canon}.txt"))
    _append(secrets_dir() / f"{canon}_api-key_{DEFAULT_SECRET_PROFILE}.txt")
    return ordered


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
