"""demos 目录下的事务直调与工具直调示例脚本。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import autodokit as aok


def build_demo_workspace_root() -> Path:
    """返回 demos 工作区根目录。

    Returns:
        demos 目录绝对路径。

    Raises:
        FileNotFoundError: 当 demos 目录不存在时抛出。

    Examples:
        >>> build_demo_workspace_root().name
        'demos'
    """

    workspace_root = Path("/home/ethan/CoreFiles/ProjectsFile/autodo-kit/demos")
    if not workspace_root.exists():
        raise FileNotFoundError(f"未找到 demos 工作区目录：{workspace_root}")
    return workspace_root


def run_affair_demo(*, workspace_root: Path) -> list[Path]:
    """演示推荐的事务直调方式。

    Args:
        workspace_root: demos 工作区根目录。

    Returns:
        事务输出文件路径列表。

    Examples:
        >>> root = build_demo_workspace_root()
        >>> isinstance(run_affair_demo(workspace_root=root), list)
        True
    """

    return aok.run_affair(
        "图节点_start",
        config={"output_dir": "output/demo_direct_api/run_affair"},
        workspace_root=workspace_root,
    )


def run_tools_demo(*, workspace_root: Path) -> Dict[str, Any]:
    """演示工具直调与高级事务调用准备过程。

    Args:
        workspace_root: demos 工作区根目录。

    Returns:
        包含工具导出名、已解析配置与事务模块名的结果字典。

    Examples:
        >>> root = build_demo_workspace_root()
        >>> result = run_tools_demo(workspace_root=root)
        >>> "tool_count" in result
        True
    """

    path_resolver = aok.get_tool("resolve_paths_to_absolute")
    prepared_config = aok.prepare_affair_config(
        config={"output_dir": "output/demo_direct_api/prepared_config"},
        workspace_root=workspace_root,
    )
    resolved_preview = path_resolver(
        {"output_dir": "output/demo_direct_api/tool_preview"},
        workspace_root=workspace_root,
    )
    affair_module = aok.import_affair_module("图节点_start")

    return {
        "tool_count": len(aok.list_tools()),
        "first_tools": aok.list_tools()[:5],
        "prepared_output_dir": prepared_config.get("output_dir"),
        "resolved_preview_output_dir": resolved_preview.get("output_dir"),
        "affair_module": affair_module.__name__,
    }


def main() -> None:
    """运行 direct API 演示。

    Returns:
        None

    Examples:
        >>> # 在仓库根目录执行
        >>> # python demos/scripts/demo_direct_api.py
    """

    workspace_root = build_demo_workspace_root()
    affair_outputs = run_affair_demo(workspace_root=workspace_root)
    tools_result = run_tools_demo(workspace_root=workspace_root)

    print("[事务直调] 已生成文件：")
    for output_path in affair_outputs:
        print(f"- {output_path}")

    print("[tools 直调] 结果预览：")
    for key, value in tools_result.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()