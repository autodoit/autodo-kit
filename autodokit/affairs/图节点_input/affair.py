"""图节点事务：input。

本事务用于表示通用数据导入入口节点。
P1 阶段仅回显输入元信息。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from autodokit.core.template_affair import TemplateAffairBase

from autodokit.core.graph_node_common import write_graph_node_report


class InputGraphNodeAffair(TemplateAffairBase):
    """input 图节点模板事务实现。"""

    def __init__(self) -> None:
        """初始化 input 图节点事务。"""

        super().__init__(affair_name="图节点_input")

    def run_business(self, *, config: dict, workspace_root: Path | None) -> List[Path]:
        """执行 input 节点核心业务。

        Args:
            config: 事务配置字典。
            workspace_root: 工作区根目录。

        Returns:
            产出文件路径列表。
        """

        report = {
            "node_type": "input",
            "input_name": str(config.get("input_name") or "input"),
            "input_source": config.get("input_source"),
            "workspace_root": str(workspace_root) if workspace_root else None,
        }
        return write_graph_node_report(config=config, node_affair_name="图节点_input", report=report)



def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """执行 input 图节点事务。

    Args:
        config_path: 调度器传入的配置文件路径。
        workspace_root: 工作区根目录（预留参数）。

    Returns:
        产出文件路径列表。
    """

    affair = InputGraphNodeAffair()
    return affair.execute(config_path=config_path, workspace_root=workspace_root)
