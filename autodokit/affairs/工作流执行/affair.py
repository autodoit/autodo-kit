"""工作流执行事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, summarize_workflow, write_affair_json_result


def run_workflow_affair(workflow_path: str | Path, dry_run: bool = False) -> dict[str, Any]:
    """执行或摘要化工作流。

    Args:
        workflow_path: 工作流文件路径。
        dry_run: 是否只做摘要。

    Returns:
        结构化工作流结果。
    """

    resolved_path = Path(workflow_path).expanduser().resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"工作流文件不存在: {resolved_path}")

    summary = summarize_workflow(resolved_path)
    return {
        "status": "PASS",
        "mode": "ark-workflow-executor",
        "result": {
            "workflow_path": str(resolved_path),
            "dry_run": dry_run,
            "summary": summary,
            "execution_status": "summarized" if dry_run else "planned",
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = run_workflow_affair(
        workflow_path=str(raw_cfg.get("workflow_path") or raw_cfg.get("config_path") or ""),
        dry_run=bool(raw_cfg.get("dry_run") or False),
    )
    return write_affair_json_result(raw_cfg, config_path, "ark_workflow_executor_result.json", result)
