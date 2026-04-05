"""AOK 旧任务数据库校验事务。

本事务仍保留在代码库中，仅用于迁移期读取旧 taskdb 结构。
新流程应改用运行基线与日志基线，不再把 taskdb 作为主契约。
"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import load_json_or_py, validate_aok_taskdb, write_affair_json_result


def validate_taskdb(
    project_root: str | Path = ".",
    *,
    tasks_db_root: str | Path | None = None,
    tasks_workspace_root: str | Path | None = None,
    content_db: str | Path | None = None,
) -> dict:
    """校验旧版 AOK taskdb 关键文件和一致性。

    Args:
        project_root: 项目根目录，默认当前目录。
        tasks_db_root: 自定义任务数据库目录。
        tasks_workspace_root: 自定义任务工作区目录。
        content_db: 自定义统一内容主库路径。

    Returns:
        校验结果字典，包含错误、告警和状态信息。

    Raises:
        OSError: 当读取文件失败时抛出底层异常。

    Examples:
        >>> result = validate_taskdb(project_root='.')
        >>> 'status' in result
        True
    """

    return validate_aok_taskdb(
        project_root=project_root,
        tasks_db_root=tasks_db_root,
        tasks_workspace_root=tasks_workspace_root,
        references_db=content_db,
        knowledge_db=content_db,
    )


def execute(config_path: Path) -> list[Path]:
    """执行旧版 AOK taskdb 校验事务。

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
    result = validate_taskdb(
        project_root=str(raw_cfg.get("project_root") or "."),
        tasks_db_root=raw_cfg.get("tasks_db_root"),
        tasks_workspace_root=raw_cfg.get("tasks_workspace_root"),
        content_db=raw_cfg.get("content_db") or raw_cfg.get("references_db") or raw_cfg.get("knowledge_db"),
    )
    return write_affair_json_result(raw_cfg, config_path, "aok_taskdb_validate_result.json", result)
