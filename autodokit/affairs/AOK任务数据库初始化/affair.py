"""AOK 旧任务数据库初始化事务。

本事务仍保留在代码库中，仅用于迁移期读取旧 taskdb 结构。
新流程应改用运行基线与日志基线，不再把 taskdb 作为主契约。
"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import bootstrap_aok_taskdb, load_json_or_py, write_affair_json_result


def bootstrap_taskdb(
    project_root: str | Path = ".",
    *,
    tasks_db_root: str | Path | None = None,
    tasks_workspace_root: str | Path | None = None,
) -> dict:
    """初始化旧版 AOK taskdb 模板。

    Args:
        project_root: 项目根目录，默认当前目录。
        tasks_db_root: 自定义任务数据库目录。
        tasks_workspace_root: 自定义任务工作区目录。

    Returns:
        初始化结果字典，包含创建路径与状态信息。

    Raises:
        OSError: 当目录或文件创建失败时抛出底层异常。

    Examples:
        >>> result = bootstrap_taskdb(project_root='.')
        >>> result['status'] in {'PASS', 'BLOCKED'}
        True
    """

    return bootstrap_aok_taskdb(
        project_root=project_root,
        tasks_db_root=tasks_db_root,
        tasks_workspace_root=tasks_workspace_root,
    )


def execute(config_path: Path) -> list[Path]:
    """执行旧版 AOK taskdb 初始化事务。

    Args:
        config_path: 事务配置文件绝对路径。

    Returns:
        结果文件路径列表。

    Raises:
        FileNotFoundError: 配置文件不存在时抛出异常。
        ValueError: 配置文件内容非法时抛出异常。

    Examples:
        >>> isinstance(config_path, Path)
        True
    """

    raw_cfg = load_json_or_py(config_path)
    result = bootstrap_taskdb(
        project_root=str(raw_cfg.get("project_root") or "."),
        tasks_db_root=raw_cfg.get("tasks_db_root"),
        tasks_workspace_root=raw_cfg.get("tasks_workspace_root"),
    )
    return write_affair_json_result(raw_cfg, config_path, "aok_taskdb_bootstrap_result.json", result)
