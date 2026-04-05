"""文献数据库兼容包装模块。

当前运行时主库为 SQLite。
本模块仅作为向后兼容入口，具体的 DataFrame/CSV 兼容实现已迁移至
`autodokit.tools.old.bibliodb_csv_compat`。

新代码应优先使用：
- `autodokit.tools.bibliodb_sqlite`
- `autodokit.tools.storage_backend`
"""

from __future__ import annotations

from autodokit.tools.old.bibliodb_csv_compat import *  # noqa: F401,F403
