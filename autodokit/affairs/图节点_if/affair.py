"""图节点事务：if。

本事务用于执行布尔条件判断，并给出分支命中结果。
P1 阶段仅提供最小可运行判断能力。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from autodokit.core.template_affair import TemplateAffairBase

from autodokit.core.graph_node_common import write_graph_node_report



def _compute_condition_result(config: Dict[str, Any]) -> bool:
    """计算 if 节点条件结果。

    Args:
        config: 事务配置字典。

    Returns:
        条件是否命中。
    """

    if "condition" in config:
        return bool(config.get("condition"))
    return bool(config.get("default", False))



class IfGraphNodeAffair(TemplateAffairBase):
    """if 图节点模板事务实现。"""

    def __init__(self) -> None:
        """初始化 if 图节点事务。"""

        super().__init__(affair_name="图节点_if")

    def run_business(self, *, config: Dict[str, Any], workspace_root: Path | None) -> List[Path]:
        """执行 if 节点核心业务。

        Args:
            config: 事务配置。
            workspace_root: 工作区根目录。

        Returns:
            产出文件路径列表。
        """

        matched = _compute_condition_result(config)

        report = {
            "node_type": "if",
            "condition": config.get("condition"),
            "matched": matched,
            "next_port": "true" if matched else "false",
            "workspace_root": str(workspace_root) if workspace_root else None,
        }
        return write_graph_node_report(config=config, node_affair_name="图节点_if", report=report)


def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """执行 if 图节点事务。

    Args:
        config_path: 调度器传入的配置文件路径。
        workspace_root: 工作区根目录（预留参数）。

    Returns:
        产出文件路径列表。
    """

    affair = IfGraphNodeAffair()
    return affair.execute(config_path=config_path, workspace_root=workspace_root)
