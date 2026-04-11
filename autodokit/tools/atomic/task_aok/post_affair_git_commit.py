"""事务节点后置统一后处理装饰器。"""

from __future__ import annotations

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
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        _wrapped._aok_postprocess_managed = False
        _wrapped._aok_postprocess_node_code = node_code

        return _wrapped

    return _decorator
