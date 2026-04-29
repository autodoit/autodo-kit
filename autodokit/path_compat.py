"""跨平台路径兼容工具。"""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path
from pathlib import PurePosixPath
from pathlib import PureWindowsPath


_WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:[/\\]")
_UNC_PATTERN = re.compile(r"^\\\\")
_POSIX_ABSOLUTE_PATTERN = re.compile(r"^/")
_PSEUDO_POSIX_BACKSLASH_PATTERN = re.compile(r"^\\(home|Users|mnt)(?:\\|/)")


def detect_runtime_family() -> str:
    """检测当前运行时所属平台族。"""

    if os.name == "nt":
        return "windows"
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return "wsl"
    if platform.system().lower() == "darwin":
        return "macos"
    return "linux"


def _normalize_pseudo_posix_backslashes(path_text: str) -> str:
    raw = str(path_text or "").strip()
    if not raw:
        return ""
    if _PSEUDO_POSIX_BACKSLASH_PATTERN.match(raw):
        return raw.replace("\\", "/")
    return raw


def _normalize_home_text(home_path_text: str | Path | None, runtime_family: str) -> str:
    if home_path_text is None:
        default_home = Path.home()
        if runtime_family == "windows":
            return str(PureWindowsPath(str(default_home)))
        return str(PurePosixPath(str(default_home).replace("\\", "/")))
    if runtime_family == "windows":
        return str(PureWindowsPath(str(home_path_text)))
    return str(PurePosixPath(str(home_path_text).replace("\\", "/")))


def _join_home_suffix(home_path_text: str, suffix_parts: list[str], runtime_family: str) -> str:
    if runtime_family == "windows":
        return str(PureWindowsPath(home_path_text).joinpath(*suffix_parts))
    return str(PurePosixPath(home_path_text).joinpath(*suffix_parts))


def _translate_windows_absolute_path(
    path_text: str,
    *,
    runtime_family: str,
    home_path_text: str,
) -> str | None:
    normalized = path_text.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return None

    drive = parts[0].rstrip(":").lower()
    if len(parts) >= 3 and parts[1].lower() == "users":
        suffix_parts = parts[3:]
        return _join_home_suffix(home_path_text, suffix_parts, runtime_family)

    if runtime_family == "wsl":
        return str(PurePosixPath("/mnt", drive, *parts[1:]))

    return None


def _translate_posix_absolute_path(
    path_text: str,
    *,
    runtime_family: str,
    home_path_text: str,
) -> str | None:
    normalized = path_text.replace("\\", "/")
    parts = normalized.split("/")

    if len(parts) >= 4 and parts[1].lower() == "mnt" and len(parts[2]) == 1 and runtime_family == "windows":
        drive = parts[2].upper()
        return str(PureWindowsPath(f"{drive}:/").joinpath(*[part for part in parts[3:] if part]))

    if len(parts) >= 4 and parts[1].lower() in {"home", "users"} and runtime_family == "windows":
        suffix_parts = [part for part in parts[3:] if part]
        return _join_home_suffix(home_path_text, suffix_parts, runtime_family)

    return None


def translate_absolute_path_to_runtime(
    path_text: str | Path,
    *,
    runtime_family: str | None = None,
    home_path_text: str | Path | None = None,
) -> str | None:
    """把跨平台绝对路径翻译为当前运行时可解析的路径文本。"""

    resolved_runtime = runtime_family or detect_runtime_family()
    normalized_text = _normalize_pseudo_posix_backslashes(str(path_text or ""))
    if not normalized_text:
        return None

    normalized_home = _normalize_home_text(home_path_text, resolved_runtime)

    if _WINDOWS_ABSOLUTE_PATTERN.match(normalized_text) or _UNC_PATTERN.match(normalized_text):
        if resolved_runtime == "windows":
            return str(PureWindowsPath(normalized_text))
        return _translate_windows_absolute_path(
            normalized_text,
            runtime_family=resolved_runtime,
            home_path_text=normalized_home,
        )

    if _POSIX_ABSOLUTE_PATTERN.match(normalized_text):
        if resolved_runtime != "windows":
            return str(PurePosixPath(normalized_text))
        return _translate_posix_absolute_path(
            normalized_text,
            runtime_family=resolved_runtime,
            home_path_text=normalized_home,
        )

    return None


def normalize_relative_path_for_runtime(path_text: str | Path, *, runtime_family: str | None = None) -> str:
    """统一相对路径的分隔符风格。"""

    resolved_runtime = runtime_family or detect_runtime_family()
    normalized_text = _normalize_pseudo_posix_backslashes(str(path_text or ""))
    if resolved_runtime == "windows":
        return normalized_text
    return normalized_text.replace("\\", "/")


def resolve_portable_path(
    raw_path: str | Path,
    *,
    base: str | Path | None = None,
    runtime_family: str | None = None,
    home_path_text: str | Path | None = None,
) -> Path:
    """按当前运行时解析跨平台路径。"""

    resolved_runtime = runtime_family or detect_runtime_family()
    resolved_base = Path(base if base is not None else Path.cwd()).expanduser().resolve()
    normalized_text = _normalize_pseudo_posix_backslashes(str(raw_path or "").strip())
    if not normalized_text:
        return resolved_base

    translated_absolute = translate_absolute_path_to_runtime(
        normalized_text,
        runtime_family=resolved_runtime,
        home_path_text=home_path_text or Path.home(),
    )
    if translated_absolute is not None:
        return Path(translated_absolute).expanduser().resolve()

    if _WINDOWS_ABSOLUTE_PATTERN.match(normalized_text) or _UNC_PATTERN.match(normalized_text) or _POSIX_ABSOLUTE_PATTERN.match(normalized_text):
        raise ValueError(f"当前系统无法解析绝对路径: {normalized_text}")

    normalized_relative = normalize_relative_path_for_runtime(normalized_text, runtime_family=resolved_runtime)
    candidate = Path(normalized_relative).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (resolved_base / candidate).resolve()


__all__ = [
    "detect_runtime_family",
    "normalize_relative_path_for_runtime",
    "resolve_portable_path",
    "translate_absolute_path_to_runtime",
]