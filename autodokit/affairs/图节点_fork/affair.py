"""图节点事务：fork。

本事务用于将流程分发到多个并发分支。
P1 阶段仅输出分支规划信息，不直接调度并发执行。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from autodokit.core.template_affair import TemplateAffairBase

from autodokit.core.graph_node_common import write_graph_node_report


class ForkGraphNodeAffair(TemplateAffairBase):
    """fork 图节点模板事务实现。"""

    def __init__(self) -> None:
        """初始化 fork 图节点事务。"""

        super().__init__(affair_name="图节点_fork")

    def run_business(self, *, config: dict, workspace_root: Path | None) -> List[Path]:
        """执行 fork 节点核心业务。

        Args:
            config: 事务配置字典。
            workspace_root: 工作区根目录。

        Returns:
            产出文件路径列表。
        """

        branches = config.get("branches")
        if not isinstance(branches, list) or not branches:
            branches = ["branch_1", "branch_2"]

        report = {
            "node_type": "fork",
            "branch_count": len(branches),
            "branches": branches,
            "workspace_root": str(workspace_root) if workspace_root else None,
        }
        return write_graph_node_report(config=config, node_affair_name="图节点_fork", report=report)



def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """执行 fork 图节点事务。

    Args:
        config_path: 调度器传入的配置文件路径。
        workspace_root: 工作区根目录（预留参数）。

    Returns:
        产出文件路径列表。
    """

    affair = ForkGraphNodeAffair()
    return affair.execute(config_path=config_path, workspace_root=workspace_root)
