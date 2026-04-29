"""跨平台路径兼容测试。"""

from __future__ import annotations

from pathlib import Path

from autodokit.path_compat import resolve_portable_path
from autodokit.path_compat import translate_absolute_path_to_runtime


def test_resolve_portable_path_should_map_windows_home_path_to_current_home(tmp_path: Path) -> None:
    """Linux/WSL/macOS 应把旧 Windows home 路径映射到当前 home。"""

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    result = resolve_portable_path(
        "C:/Users/LegacyUser/CoreFiles/demo.txt",
        base=workspace_root,
        runtime_family="linux",
        home_path_text="/home/ethan",
    )

    assert result == Path("/home/ethan/CoreFiles/demo.txt")


def test_resolve_portable_path_should_normalize_windows_relative_separators_on_posix(tmp_path: Path) -> None:
    """POSIX 运行时应把 Windows 风格相对路径分隔符归一化。"""

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    result = resolve_portable_path(
        r"config\affairs_config\A010.json",
        base=workspace_root,
        runtime_family="linux",
    )

    assert result == (workspace_root / "config" / "affairs_config" / "A010.json").resolve()


def test_translate_absolute_path_to_runtime_should_map_posix_home_to_windows_home() -> None:
    """Windows 运行时应能消费 Linux home 风格路径。"""

    result = translate_absolute_path_to_runtime(
        "/home/ethan/CoreFiles/demo.txt",
        runtime_family="windows",
        home_path_text="C:/Users/Ethan",
    )

    assert result == "C:\\Users\\Ethan\\CoreFiles\\demo.txt"


def test_translate_absolute_path_to_runtime_should_map_windows_drive_to_macos_home() -> None:
    """macOS 运行时应优先把旧 Windows home 路径映射到当前 home。"""

    result = translate_absolute_path_to_runtime(
        "C:/Users/Ethan/CoreFiles/demo.txt",
        runtime_family="macos",
        home_path_text="/Users/ethan",
    )

    assert result == "/Users/ethan/CoreFiles/demo.txt"