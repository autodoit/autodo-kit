"""图节点事务：compare。

本事务用于执行比较判断（含不等号判断）。
P1 阶段提供最小比较能力并输出分支方向。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from autodokit.core.template_affair import TemplateAffairBase

from autodokit.core.graph_node_common import compute_compare_result, write_graph_node_report


class CompareGraphNodeAffair(TemplateAffairBase):
    """compare 图节点模板事务实现。"""

    def __init__(self) -> None:
        """初始化 compare 图节点事务。"""

        super().__init__(affair_name="图节点_compare")

    def run_business(self, *, config: dict, workspace_root: Path | None) -> List[Path]:
        """执行 compare 节点核心业务。

        Args:
            config: 事务配置字典。
            workspace_root: 工作区根目录。

        Returns:
            产出文件路径列表。
        """

        left_value = config.get("left")
        right_value = config.get("right")
        operator = str(config.get("operator") or "!=").strip()

        matched = False
        compare_error: str | None = None
        try:
            matched = compute_compare_result(left=left_value, operator=operator, right=right_value)
        except Exception as exc:  # noqa: BLE001
            compare_error = str(exc)

        report = {
            "node_type": "compare",
            "left": left_value,
            "operator": operator,
            "right": right_value,
            "matched": matched,
            "next_port": "true" if matched else "false",
            "error": compare_error,
            "workspace_root": str(workspace_root) if workspace_root else None,
        }
        return write_graph_node_report(config=config, node_affair_name="图节点_compare", report=report)



def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """执行 compare 图节点事务。

    Args:
        config_path: 调度器传入的配置文件路径。
        workspace_root: 工作区根目录（预留参数）。

    Returns:
        产出文件路径列表。
    """

    affair = CompareGraphNodeAffair()
    return affair.execute(config_path=config_path, workspace_root=workspace_root)
