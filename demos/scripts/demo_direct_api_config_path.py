"""demos 目录下的 config_path 模式事务直调示例脚本。"""

from __future__ import annotations

from pathlib import Path

import autodokit as aok
from autodokit.affairs.图节点_start.affair import execute as execute_start_affair


def build_demo_workspace_root() -> Path:
    """返回 demos 工作区根目录。

    Returns:
        demos 目录绝对路径。

    Raises:
        FileNotFoundError: 当 demos 目录不存在时抛出。
    """

    workspace_root = Path(r"C:\Users\Ethan\CoreFiles\ProjectsFile\autodo-kit\demos")
    if not workspace_root.exists():
        raise FileNotFoundError(f"未找到 demos 工作区目录：{workspace_root}")
    return workspace_root


def build_config_path(filename: str) -> Path:
    """返回 config_path 模式示例配置文件路径。

    Args:
        filename: 配置文件名。

    Returns:
        配置文件绝对路径。

    Raises:
        FileNotFoundError: 当配置文件不存在时抛出。
    """

    config_path = Path(r"C:\Users\Ethan\CoreFiles\ProjectsFile\autodo-kit\demos\settings\配置文件") / filename
    if not config_path.exists():
        raise FileNotFoundError(f"未找到 config_path 模式示例配置文件：{config_path}")
    return config_path


def run_recommended_config_path_demo(*, workspace_root: Path) -> list[Path]:
    """演示推荐的 config_path 模式事务直调。

    Args:
        workspace_root: demos 工作区根目录。

    Returns:
        事务输出文件路径列表。
    """

    config_path = build_config_path("demo_direct_api_config_path_recommended.json")
    return aok.run_affair(
        "图节点_start",
        config_path=config_path,
        workspace_root=workspace_root,
    )


def run_advanced_config_path_demo(*, workspace_root: Path) -> list[Path]:
    """演示高级的 config_path 模式事务直调。

    Args:
        workspace_root: demos 工作区根目录。

    Returns:
        事务输出文件路径列表。
    """

    config_path = build_config_path("demo_direct_api_config_path_advanced.json")
    return execute_start_affair(config_path, workspace_root=workspace_root)


def main() -> None:
    """运行 config_path 模式 direct API 演示。

    Returns:
        None

    Examples:
        >>> # 在仓库根目录执行
        >>> # python demos/scripts/demo_direct_api_config_path.py
    """

    workspace_root = build_demo_workspace_root()
    recommended_outputs = run_recommended_config_path_demo(workspace_root=workspace_root)
    advanced_outputs = run_advanced_config_path_demo(workspace_root=workspace_root)

    print("[config_path 推荐方式] 已生成文件：")
    for output_path in recommended_outputs:
        print(f"- {output_path}")

    print("[config_path 高级方式] 已生成文件：")
    for output_path in advanced_outputs:
        print(f"- {output_path}")


if __name__ == "__main__":
    main()