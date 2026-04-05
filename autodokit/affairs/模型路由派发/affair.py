"""模型路由派发事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import append_flow_trace_event, load_json_or_py, write_affair_json_result
from autodokit.tools.llm_clients import ModelRoutingIntent, invoke_aliyun_llm, resolve_model_plan


def _normalize_budget_tier(budget_level: str) -> str:
    """把历史预算字段映射到新路由预算档位。"""

    raw = str(budget_level or "").strip().lower()
    if raw in {"low", "cheap"}:
        return "cheap"
    if raw in {"high", "premium", "max"}:
        return "premium"
    return "balanced"


def _normalize_quality_tier(quality_tier: str) -> str:
    """把历史质量字段映射到新路由质量档位。"""

    raw = str(quality_tier or "").strip().lower()
    if raw in {"high", "max", "premium"}:
        return "high"
    return "standard"


def _normalize_latency_tier(latency_level: str) -> str:
    """把历史时延字段映射到新路由时延档位。"""

    raw = str(latency_level or "").strip().lower()
    if raw in {"low", "fast"}:
        return "low"
    if raw in {"high", "slow"}:
        return "high"
    return "medium"


def _normalize_risk_level(risk_level: str) -> str:
    """把历史风险字段映射到新路由风险档位。"""

    raw = str(risk_level or "").strip().lower()
    if raw in {"strict", "high"}:
        return "strict"
    if raw in {"low"}:
        return "low"
    return "medium"


def _build_model_routing_decision(
    task_type: str,
    quality_tier: str,
    budget_level: str,
    latency_level: str,
    risk_level: str,
    mainland_only: bool,
    region: str,
    input_chars: int,
    explicit_model: str,
) -> dict[str, Any]:
    """生成可执行的统一路由决策。"""

    normalized_region = "cn-beijing" if mainland_only else (str(region or "cn-beijing").strip() or "cn-beijing")
    intent = ModelRoutingIntent(
        task_type=(task_type if task_type in {"general", "vision", "long_text", "math_reasoning", "coding"} else "general"),
        quality_tier=_normalize_quality_tier(quality_tier),
        budget_tier=_normalize_budget_tier(budget_level),
        latency_tier=_normalize_latency_tier(latency_level),
        risk_level=_normalize_risk_level(risk_level),
        region=normalized_region,
        input_chars=max(0, int(input_chars or 0)),
        model=str(explicit_model or "").strip(),
        affair_name="模型路由派发",
    )
    plan = resolve_model_plan(intent)

    return {
        "task_type": plan.task_type,
        "quality_tier": plan.quality_tier,
        "budget_level": budget_level,
        "budget_tier": plan.budget_tier,
        "latency_level": latency_level,
        "latency_tier": plan.latency_tier,
        "risk_level": plan.risk_level,
        "mainland_only": mainland_only,
        "region": normalized_region,
        "primary_model": plan.primary_model,
        "fallback_models": list(plan.fallback_models),
        "estimated_input_tokens": plan.estimated_input_tokens,
        "estimated_cost_range": [plan.estimated_min_cost, plan.estimated_max_cost],
        "catalog_version": plan.catalog_version,
        "reason": plan.reason,
    }


def run_model_routing_affair(
    task_type: str,
    quality_tier: str,
    budget_level: str,
    latency_level: str,
    risk_level: str,
    mainland_only: bool,
    region: str = "cn-beijing",
    input_chars: int = 0,
    explicit_model: str = "",
    run_inference: bool = False,
    prompt: str = "",
    system_prompt: str = "",
    max_tokens: int = 1024,
    temperature: float = 0.2,
    env_api_key_name: str = "DASHSCOPE_API_KEY",
    api_key_file: str | None = None,
    config_path: str | Path | None = None,
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
        region=region,
        input_chars=input_chars,
        explicit_model=explicit_model,
    )

    if run_inference and not str(prompt or "").strip():
        raise ValueError("run_inference=true 时必须提供 prompt")

    invocation = {"status": "SKIPPED", "selected_model": "", "attempts": [], "response": {}}
    if run_inference:
        invocation = invoke_aliyun_llm(
            prompt=str(prompt),
            system=str(system_prompt or "") or None,
            intent=ModelRoutingIntent(
                task_type=decision["task_type"],
                quality_tier=decision["quality_tier"],
                budget_tier=decision["budget_tier"],
                latency_tier=decision["latency_tier"],
                risk_level=decision["risk_level"],
                region=decision["region"],
                input_chars=max(0, int(input_chars or 0)),
                model=str(explicit_model or "").strip(),
                affair_name="模型路由派发",
            ),
            max_tokens=int(max_tokens),
            temperature=float(temperature),
            env_api_key_name=str(env_api_key_name or "DASHSCOPE_API_KEY"),
            api_key_file=api_key_file,
            config_path=config_path,
            affair_name="模型路由派发",
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
            "estimated_cost_range": decision["estimated_cost_range"],
            "invocation_status": invocation.get("status", "SKIPPED"),
            "artifacts": {},
        },
    )
    return {
        "status": "PASS",
        "mode": "model-routing-dispatch",
        "result": {
            "decision": decision,
            "candidate_models": [decision["primary_model"], *decision["fallback_models"]],
            "invocation": invocation,
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
        region=str(raw_cfg.get("region") or "cn-beijing"),
        input_chars=int(raw_cfg.get("input_chars") or 0),
        explicit_model=str(raw_cfg.get("model") or ""),
        run_inference=bool(raw_cfg.get("run_inference", False)),
        prompt=str(raw_cfg.get("prompt") or ""),
        system_prompt=str(raw_cfg.get("system_prompt") or ""),
        max_tokens=int(raw_cfg.get("max_tokens") or 1024),
        temperature=float(raw_cfg.get("temperature") or 0.2),
        env_api_key_name=str(raw_cfg.get("env_api_key_name") or "DASHSCOPE_API_KEY"),
        api_key_file=str(raw_cfg.get("api_key_file") or "") or None,
        config_path=raw_cfg.get("config_path"),
        workspace_root=raw_cfg.get("workspace_root"),
    )
    return write_affair_json_result(raw_cfg, config_path, "model_routing_dispatch_result.json", result)
