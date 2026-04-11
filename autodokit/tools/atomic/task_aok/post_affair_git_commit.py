"""事务节点后置统一后处理装饰器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from autodokit.tools.atomic.task_aok.postprocess_runtime import run_unified_postprocess
from autodokit.tools.time_utils import now_iso


def affair_auto_git_commit(node_code: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """为事务 `execute` 接入统一后处理。

    Args:
        node_code: 节点代号。

    Returns:
        Callable[[Callable[..., Any]], Callable[..., Any]]: 装饰器函数。
    """

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            config_path: Path | None = None
            if args:
                candidate = args[0]
                if isinstance(candidate, Path):
                    config_path = candidate
                elif isinstance(candidate, str) and candidate.strip():
                    config_path = Path(candidate)
            if config_path is None:
                kw_value = kwargs.get("config_path")
                if isinstance(kw_value, Path):
                    config_path = kw_value
                elif isinstance(kw_value, str) and kw_value.strip():
                    config_path = Path(kw_value)

            started_at = now_iso()
            execute_error: BaseException | None = None
            result: Any = None
            try:
                result = func(*args, **kwargs)
                return result
            except BaseException as exc:  # noqa: BLE001
                execute_error = exc
                raise
            finally:
                if config_path is not None:
                    run_unified_postprocess(
                        config_path=config_path,
                        node_code=node_code,
                        execute_result=result,
                        execute_error=execute_error,
                        started_at=started_at,
                        ended_at=now_iso(),
                    )

        _wrapped._aok_postprocess_managed = True
        _wrapped._aok_postprocess_node_code = node_code

        return _wrapped

    return _decorator
