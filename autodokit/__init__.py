"""autodo-kit 包入口。

本包仅承载官方事务与事务侧工具；运行时执行能力由 `autodo-engine`
提供。这里保留少量懒加载桥接，方便现有脚本继续通过 `import autodokit`
调用事务直调入口。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_BRIDGED_NAMES = {
    "import_affair_module",
    "prepare_affair_config",
    "run_affair",
}


def __getattr__(name: str) -> Any:
    """按需桥接 `autodo-engine` 的公开事务接口。

    Args:
        name: 属性名。

    Returns:
        公开属性对象。

    Raises:
        AttributeError: 当属性不存在时抛出。
    """

    if name in _BRIDGED_NAMES:
        api_module = import_module("autodoengine.api")
        return getattr(api_module, name)
    raise AttributeError(f"module 'autodokit' has no attribute {name!r}")


__all__ = sorted(_BRIDGED_NAMES)