"""A050 文献下载与主附件入库事务封装。"""

from __future__ import annotations

from pathlib import Path

from autodokit.affairs.检索治理.affair import _execute_impl
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit


@affair_auto_git_commit("A050")
def execute(config_path: Path) -> list[Path]:
    """A050 官方事务入口。"""

    return _execute_impl(config_path)