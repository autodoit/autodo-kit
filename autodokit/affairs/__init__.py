"""事务实现包。

说明：
- 每个事务目录位于 `autodokit/affairs/<affair_name>/`；
- 统一入口文件为 `affair.py`；
- 运行时通过 `autodokit/tools/affair_registry.py` 动态发现与加载。
"""

from __future__ import annotations

__all__: list[str] = []

