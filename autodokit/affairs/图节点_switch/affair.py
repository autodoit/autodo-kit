"""图节点事务：switch。

本事务用于根据路由标签进行多路分支选择。
P5 阶段提供最小可运行实现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from autodokit.tools import evaluate_expression

from autodokit.core.template_affair import TemplateAffairBase

from autodokit.core.graph_node_common import write_graph_node_report


def _resolve_route_label(config: Dict[str, Any]) -> str:
    """推断 switch 路由标签。

    Args:
        config: 事务配置字典。

    Returns:
        路由标签字符串。
    """

    explicit = str(config.get("route_label") or "").strip()
    if explicit:
        return explicit

    route_expression = str(config.get("route_expression") or "").strip()
    if route_expression:
        variables = config.get("variables") if isinstance(config.get("variables"), dict) else {}
        safe_locals = dict(variables)
        safe_locals.setdefault("switch_value", config.get("switch_value"))
        expression_mode = str(config.get("expression_mode") or "safe").strip().lower() or "safe"
        allow_unsafe_eval = bool(config.get("allow_unsafe_eval", False))
        try:
            eval_result = evaluate_expression(
                expression=route_expression,
                variables=safe_locals,
                mode=expression_mode,
                allow_unsafe_eval=allow_unsafe_eval,
            )
            config["_expression_engine"] = eval_result.engine
            config["_expression_warning"] = eval_result.warning
            if isinstance(eval_result.value, str) and eval_result.value.strip():
                return eval_result.value.strip()
            config["switch_value"] = eval_result.value
        except Exception:
            pass

    switch_value = config.get("switch_value")
    cases = config.get("cases") if isinstance(config.get("cases"), dict) else {}
    for label, expected in cases.items():
        if isinstance(expected, list):
            if switch_value in expected:
                return str(label)
        else:
            if switch_value == expected:
                return str(label)

    default_label = str(config.get("default_label") or "default").strip()
    return default_label or "default"


class SwitchGraphNodeAffair(TemplateAffairBase):
    """switch 图节点模板事务实现。"""

    def __init__(self) -> None:
        """初始化 switch 图节点事务。"""

        super().__init__(affair_name="图节点_switch")

    def run_business(self, *, config: Dict[str, Any], workspace_root: Path | None) -> List[Path]:
        """执行 switch 节点核心业务。

        Args:
            config: 事务配置。
            workspace_root: 工作区根目录。

        Returns:
            产出文件路径列表。
        """

        route_label = _resolve_route_label(config)

        report = {
            "node_type": "switch",
            "route_label": route_label,
            "route_expression": config.get("route_expression"),
            "expression_mode": config.get("expression_mode", "safe"),
            "expression_engine": config.get("_expression_engine"),
            "expression_warning": config.get("_expression_warning"),
            "variables": config.get("variables"),
            "switch_value": config.get("switch_value"),
            "cases": config.get("cases"),
            "workspace_root": str(workspace_root) if workspace_root else None,
        }
        return write_graph_node_report(config=config, node_affair_name="图节点_switch", report=report)


def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """执行 switch 图节点事务。

    Args:
        config_path: 调度器传入的配置路径。
        workspace_root: 工作区根目录（预留参数）。

    Returns:
        产出文件路径列表。
    """

    affair = SwitchGraphNodeAffair()
    return affair.execute(config_path=config_path, workspace_root=workspace_root)
