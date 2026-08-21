"""Runner 适配层。

提供两种统一调用入口：
- run_capability: 按 tool_name 调用工具函数（通用能力调用）
- run_affair: 按 affair 名称调用事务（事务编排调用）
"""

from __future__ import annotations

from autodokit.tools.adapters.runner.run_affair import run_affair, AffairResult  # noqa: F401
from autodokit.tools.adapters.runner.run_capability import main as run_capability_main  # noqa: F401
