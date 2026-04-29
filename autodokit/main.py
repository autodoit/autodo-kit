"""autodokit 兼容主入口。

该模块为上层 ARK 桥接提供一个稳定的 ``autodokit.main.run`` 入口。
当前版本优先支持 config 解析、workflow 摘要构建与 dry-run 验链。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.path_compat import resolve_portable_path
from autodokit.tools import load_json_file, resolve_config_path, resolve_workspace_root, summarize_workflow


def _resolve_run_items(config: dict[str, Any], workspace_root: Path) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """解析 run 列表中的 workflow。

    Args:
        config: 全局配置字典。
        workspace_root: 工作区根目录。

    Returns:
        由原始 run 列表、workflow 摘要列表、缺失 workflow 列表组成的三元组。
    """

    run_items = [str(item) for item in config.get("run", []) if str(item).strip()]
    workflows: list[dict[str, Any]] = []
    missing_workflows: list[str] = []

    for item in run_items:
        workflow_path = resolve_portable_path(item, base=workspace_root)
        if not workflow_path.exists():
            missing_workflows.append(str(workflow_path))
            continue
        summary = summarize_workflow(workflow_path)
        if isinstance(summary, dict):
            summary = dict(summary)
            summary.setdefault("workflow_path", str(workflow_path))
        workflows.append(summary)

    return run_items, workflows, missing_workflows


def run(
    config_path: str | Path | None = None,
    dry_run: bool = False,
    parallel: bool = False,
    max_workers: int = 2,
    log_dir: str | Path | None = None,
) -> dict[str, Any]:
    """运行兼容入口。

    Args:
        config_path: 全局配置路径。
        dry_run: 是否仅做校验。
        parallel: 是否请求并行模式。
        max_workers: 最大并行数。
        log_dir: 日志目录。

    Returns:
        结构化执行摘要。

    Raises:
        RuntimeError: 当非 dry-run 执行仍未接入真实执行桥时抛出。
    """

    config_file = resolve_config_path(config_path)
    config = load_json_file(config_file)
    workspace_root = resolve_workspace_root(config_file=config_file, config=config)
    run_items, workflows, missing_workflows = _resolve_run_items(config=config, workspace_root=workspace_root)

    if not dry_run:
        raise RuntimeError(
            "autodokit.main.run 当前仅接入 dry-run 验链，真实执行桥仍待补齐。"
        )

    return {
        "config_path": str(config_file),
        "workspace_root": str(workspace_root),
        "workflow_count": len(run_items),
        "missing_workflow_count": len(missing_workflows),
        "workflows": workflows,
        "missing_workflows": missing_workflows,
        "dry_run": True,
        "execution_results": [],
        "execution_result_count": 0,
        "parallel": parallel,
        "max_workers": max_workers,
        "log_dir": str(resolve_portable_path(log_dir, base=workspace_root)) if log_dir else "",
        "engine": "autodokit.main.run",
    }


__all__ = ["run"]