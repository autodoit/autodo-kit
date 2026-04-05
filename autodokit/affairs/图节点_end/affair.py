"""图节点事务：end。

本事务用于表示流程的结束节点。
P1 阶段仅提供可调度与可观测占位实现。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from autodokit.core.template_affair import TemplateAffairBase

from autodokit.core.graph_node_common import write_graph_node_report


class EndGraphNodeAffair(TemplateAffairBase):
    """end 图节点模板事务实现。"""

    def __init__(self) -> None:
        """初始化 end 图节点事务。"""

        super().__init__(affair_name="图节点_end")

    def run_business(self, *, config: dict, workspace_root: Path | None) -> List[Path]:
        """执行 end 节点核心业务。

        Args:
            config: 事务配置字典。
            workspace_root: 工作区根目录。

        Returns:
            产出文件路径列表。
        """

        report = {
            "node_type": "end",
            "message": "流程结束节点已触发。",
            "workspace_root": str(workspace_root) if workspace_root else None,
        }
        return write_graph_node_report(config=config, node_affair_name="图节点_end", report=report)



def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """执行 end 图节点事务。

    Args:
        config_path: 调度器传入的配置文件路径。
        workspace_root: 工作区根目录（预留参数）。

    Returns:
        产出文件路径列表。
    """

    affair = EndGraphNodeAffair()
    return affair.execute(config_path=config_path, workspace_root=workspace_root)
