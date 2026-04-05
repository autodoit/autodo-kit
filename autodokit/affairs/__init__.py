"""事务实现包。

说明：
- 每个事务目录位于 `autodokit/affairs/<affair_name>/`；
- 统一入口文件为 `affair.py`；
- 运行时可通过 `autodokit.tools.build_registry(...)` 动态扫描，也可通过主链入口注册表做显式解析。
"""

from __future__ import annotations

__all__: list[str] = []

