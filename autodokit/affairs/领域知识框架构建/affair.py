"""A130 领域知识框架构建占位事务程序。

当前文件仅用于开发阶段的入口联调与产物占位，
不代表 A130 正式业务实现已经完成。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from autodokit.tools import build_gate_review, load_json_or_py
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.atomic.task_aok.task_instance_dir import (
    create_task_instance_dir,
    mirror_artifacts_to_legacy,
    resolve_legacy_output_dir,
)


@affair_auto_git_commit("A130")
def execute(config_path: Path) -> List[Path]:
    """执行 A130 占位事务并输出占位审计产物。

    Args:
        config_path: A130 配置文件绝对路径。

    Returns:
        List[Path]: 本次写出的占位产物路径列表。

    Raises:
        ValueError: 当 workspace_root 不是绝对路径时抛出。

    Examples:
        >>> execute(Path("C:/repo/workspace/config/affairs_config/A130.json"))
    """

    raw_cfg = load_json_or_py(config_path)
    workspace_root = Path(str(raw_cfg.get("workspace_root") or config_path.parents[2]))
    if not workspace_root.is_absolute():
        raise ValueError(f"workspace_root 必须为绝对路径: {workspace_root}")

    legacy_output_dir = resolve_legacy_output_dir(raw_cfg, config_path)
    output_dir = create_task_instance_dir(workspace_root, "A130")

    placeholder_status = {
        "node_code": "A130",
        "implemented": False,
        "message": "A130 当前仅提供占位事务程序，尚未接入正式业务实现。",
        "next_action": "pause_current",
    }
    status_path = output_dir / "placeholder_status.json"
    status_path.write_text(json.dumps(placeholder_status, ensure_ascii=False, indent=2), encoding="utf-8")

    gate_review = build_gate_review(
        node_uid="A130",
        node_name="领域知识框架构建",
        summary="A130 为占位事务程序：已生成占位产物并要求暂停当前节点。",
        checks=[
            {"name": "implemented", "value": False},
            {"name": "action", "value": "pause_current"},
        ],
        artifacts=[str(status_path)],
        recommendation="pause_current",
        score=0.0,
    )
    gate_path = output_dir / "gate_review.json"
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    mirror_artifacts_to_legacy([status_path, gate_path], legacy_output_dir, output_dir)
    return [status_path, gate_path]
