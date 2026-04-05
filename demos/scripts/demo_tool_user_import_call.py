"""用户侧工具直调示例。"""

from __future__ import annotations

from autodokit.tools import list_user_tools, parse_reference_text


def main() -> None:
    """运行用户侧工具直调示例。

    Returns:
        None

    Examples:
        在仓库根目录执行：
            python demos/scripts/demo_tool_user_import_call.py
    """

    tools = list_user_tools()
    print("[用户工具清单]", tools)

    reference_text = "Smith, 2024. Example Title for Tool Demo."
    parsed = parse_reference_text(reference_text)
    print("[解析结果]", parsed)

    clean_title = getattr(parsed, "clean_title", "")
    if not str(clean_title).strip():
        raise SystemExit("解析结果异常：未获得 clean_title")

    print("[通过] 用户侧工具直调示例执行成功")


if __name__ == "__main__":
    main()
