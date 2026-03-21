"""开发者侧工具直调示例。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import get_tool, list_developer_tools


def build_demo_workspace_root() -> Path:
    """构建并返回 demos 工作区根目录。

    Returns:
        Path: demos 目录绝对路径。

    Raises:
        FileNotFoundError: 当 demos 目录不存在时抛出。

    Examples:
        >>> build_demo_workspace_root().name
        'demos'
    """

    demos_root = Path(__file__).resolve().parents[1]
    if not demos_root.exists():
        raise FileNotFoundError(f"未找到 demos 目录：{demos_root}")
    return demos_root


def main() -> None:
    """运行开发者侧工具直调示例。

    Returns:
        None

    Examples:
        在仓库根目录执行：
            python demos/scripts/demo_tool_developer_get_tool_call.py
    """

    workspace_root = build_demo_workspace_root()
    developer_tools = list_developer_tools()
    print("[开发者工具数量]", len(developer_tools))
    print("[开发者工具前十项]", developer_tools[:10])

    resolver = get_tool("resolve_paths_to_absolute", scope="developer")
    resolved = resolver(
        {"output_dir": "output/demo_tool_developer_get_tool_call"},
        workspace_root=workspace_root,
    )
    print("[路径解析结果]", resolved)

    output_dir = str(resolved.get("output_dir") or "")
    if not output_dir:
        raise SystemExit("路径解析失败：output_dir 为空")
    if not Path(output_dir).is_absolute():
        raise SystemExit("路径解析失败：output_dir 不是绝对路径")

    print("[通过] 开发者侧工具直调示例执行成功")


if __name__ == "__main__":
    main()
