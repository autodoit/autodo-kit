"""模型路由派发事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import append_flow_trace_event, load_json_or_py, write_affair_json_result


def _build_model_routing_decision(
    task_type: str,
    quality_tier: str,
    budget_level: str,
    latency_level: str,
    risk_level: str,
    mainland_only: bool,
) -> dict[str, Any]:
    """生成最小可用的模型路由决策。"""

    if mainland_only or risk_level in {"high", "strict"}:
        primary = "qwen-plus"
        fallbacks = ["qwen-turbo", "qwen-max"]
    elif budget_level == "low":
        primary = "qwen-turbo"
        fallbacks = ["qwen-plus"]
    elif quality_tier in {"high", "max"}:
        primary = "qwen-max"
        fallbacks = ["qwen-plus", "qwen-turbo"]
    else:
        primary = "qwen-plus"
        fallbacks = ["qwen-turbo"]
    return {
        "task_type": task_type,
        "quality_tier": quality_tier,
        "budget_level": budget_level,
        "latency_level": latency_level,
        "risk_level": risk_level,
        "mainland_only": mainland_only,
        "primary_model": primary,
        "fallback_models": fallbacks,
    }


def run_model_routing_affair(
    task_type: str,
    quality_tier: str,
    budget_level: str,
    latency_level: str,
    risk_level: str,
    mainland_only: bool,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """执行模型路由决策。"""

    decision = _build_model_routing_decision(
        task_type=task_type,
        quality_tier=quality_tier,
        budget_level=budget_level,
        latency_level=latency_level,
        risk_level=risk_level,
        mainland_only=mainland_only,
    )
    trace_root = Path(workspace_root).expanduser().resolve() if workspace_root else Path(".").resolve()
    append_flow_trace_event(
        workspace_root=trace_root,
        event={
            "event_type": "transaction",
            "command": "aok-model-routing",
            "agent": "orchestrator",
            "skill": "model-routing-dispatch",
            "provider": "aliyun-bailian",
            "task_uid": "",
            "transaction_uid": "",
            "status": "PASS",
            "mode": "decision-only",
            "task_type": task_type,
            "model": decision["primary_model"],
            "fallback_models": decision["fallback_models"],
            "artifacts": {},
        },
    )
    return {
        "status": "PASS",
        "mode": "model-routing-dispatch",
        "result": {
            "decision": decision,
            "candidate_models": [decision["primary_model"], *decision["fallback_models"]],
            "invocation": {"status": "SKIPPED", "selected_model": "", "attempts": [], "response": {}},
            "artifacts": {},
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = run_model_routing_affair(
        task_type=str(raw_cfg.get("task_type") or "general"),
        quality_tier=str(raw_cfg.get("quality_tier") or "standard"),
        budget_level=str(raw_cfg.get("budget_level") or "medium"),
        latency_level=str(raw_cfg.get("latency_level") or "medium"),
        risk_level=str(raw_cfg.get("risk_level") or "medium"),
        mainland_only=bool(raw_cfg.get("mainland_only") if "mainland_only" in raw_cfg else True),
        workspace_root=raw_cfg.get("workspace_root"),
    )
    return write_affair_json_result(raw_cfg, config_path, "model_routing_dispatch_result.json", result)
