"""图节点事务：calc。

本事务用于执行常见计算表达式。
P1 阶段使用受限表达式执行器实现最小可运行能力。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from autodokit.core.template_affair import TemplateAffairBase

from autodokit.core.graph_node_common import compute_simple_expression, write_graph_node_report



def _build_variable_context(config: Dict[str, Any]) -> Dict[str, Any]:
    """构造表达式计算变量上下文。

    Args:
        config: 事务配置字典。

    Returns:
        变量字典。
    """

    variables = config.get("variables")
    if isinstance(variables, dict):
        return dict(variables)
    return {}



class CalcGraphNodeAffair(TemplateAffairBase):
    """calc 图节点模板事务实现。"""

    def __init__(self) -> None:
        """初始化 calc 图节点事务。"""

        super().__init__(affair_name="图节点_calc")

    def run_business(self, *, config: Dict[str, Any], workspace_root: Path | None) -> List[Path]:
        """执行 calc 节点核心业务。

        Args:
            config: 事务配置。
            workspace_root: 工作区根目录。

        Returns:
            产出文件路径列表。
        """

        expression = str(config.get("expression") or "").strip()
        expression_mode = str(config.get("expression_mode") or "safe").strip().lower() or "safe"
        allow_unsafe_eval = bool(config.get("allow_unsafe_eval", False))
        variables = _build_variable_context(config)

        calc_result: Any = None
        calc_error: str | None = None
        expression_engine: str | None = None
        expression_warning: str | None = None
        if expression:
            try:
                calc_payload = compute_simple_expression(
                    expression=expression,
                    variables=variables,
                    mode=expression_mode,
                    allow_unsafe_eval=allow_unsafe_eval,
                )
                calc_result = calc_payload.get("value")
                expression_engine = calc_payload.get("engine")
                expression_warning = calc_payload.get("warning")
            except Exception as exc:  # noqa: BLE001
                calc_error = str(exc)

        report = {
            "node_type": "calc",
            "expression": expression,
            "expression_mode": expression_mode,
            "expression_engine": expression_engine,
            "expression_warning": expression_warning,
            "variables": variables,
            "result": calc_result,
            "error": calc_error,
            "workspace_root": str(workspace_root) if workspace_root else None,
        }
        return write_graph_node_report(config=config, node_affair_name="图节点_calc", report=report)

def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """执行 calc 图节点事务。

    Args:
        config_path: 调度器传入的配置文件路径。
        workspace_root: 工作区根目录（预留参数）。

    Returns:
        产出文件路径列表。
    """

    affair = CalcGraphNodeAffair()
    return affair.execute(config_path=config_path, workspace_root=workspace_root)
