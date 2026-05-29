"""事务节点后置统一后处理装饰器。"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Callable


def affair_auto_git_commit(node_code: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """事务装饰器兼容壳。

    Args:
        node_code: 节点代号。

    Returns:
        Callable[[Callable[..., Any]], Callable[..., Any]]: 装饰器函数。

    Notes:
        统一后处理由 PA 编排层或 `run_affair(...)` 统一触发。
        该装饰器不再在事务内部执行任何后处理，仅保留历史装饰接口兼容。
    """

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(func)
        parameter_names = list(signature.parameters)
        first_parameter_name = parameter_names[0] if parameter_names else ""

        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            normalized_args = list(args)
            normalized_kwargs = dict(kwargs)

            if first_parameter_name == "config_path" and normalized_args and isinstance(normalized_args[0], str):
                normalized_args[0] = Path(normalized_args[0])
            if isinstance(normalized_kwargs.get("config_path"), str):
                normalized_kwargs["config_path"] = Path(normalized_kwargs["config_path"])

            return func(*normalized_args, **normalized_kwargs)

        _wrapped._aok_postprocess_managed = False
        _wrapped._aok_postprocess_node_code = node_code

        return _wrapped

    return _decorator
