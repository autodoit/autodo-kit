"""图节点事务：container。

本事务用于表达可嵌套容器节点及其循环配置。
P1 阶段仅解析并回显容器循环参数。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from autodokit.core.template_affair import TemplateAffairBase

from autodokit.core.graph_node_common import write_graph_node_report



def _parse_loop_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """解析容器循环配置。

    Args:
        config: 事务配置字典。

    Returns:
        规范化后的循环配置。
    """

    loop_cfg = config.get("loop") if isinstance(config.get("loop"), dict) else {}
    enabled = bool(loop_cfg.get("enabled", False))
    max_iterations = int(loop_cfg.get("max_iterations", 1))
    stop_condition = str(loop_cfg.get("stop_condition") or "").strip()

    return {
        "enabled": enabled,
        "max_iterations": max_iterations,
        "stop_condition": stop_condition,
    }



class ContainerGraphNodeAffair(TemplateAffairBase):
    """container 图节点模板事务实现。"""

    def __init__(self) -> None:
        """初始化 container 图节点事务。"""

        super().__init__(affair_name="图节点_container")

    def run_business(self, *, config: Dict[str, Any], workspace_root: Path | None) -> List[Path]:
        """执行 container 节点核心业务。

        Args:
            config: 事务配置。
            workspace_root: 工作区根目录。

        Returns:
            产出文件路径列表。
        """

        loop_config = _parse_loop_config(config)

        report = {
            "node_type": "container",
            "container_name": str(config.get("container_name") or "container"),
            "loop": loop_config,
            "workspace_root": str(workspace_root) if workspace_root else None,
        }
        return write_graph_node_report(config=config, node_affair_name="图节点_container", report=report)


def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """执行 container 图节点事务。

    Args:
        config_path: 调度器传入的配置文件路径。
        workspace_root: 工作区根目录（预留参数）。

    Returns:
        产出文件路径列表。
    """

    affair = ContainerGraphNodeAffair()
    return affair.execute(config_path=config_path, workspace_root=workspace_root)
