"""阿里百炼统一路由最小回归测试。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools.llm_clients import ModelRoutingIntent, load_aliyun_llm_config, resolve_model_plan
from autodokit.tools import open_access_literature_retrieval as retrieval


def test_resolve_model_plan_general_auto() -> None:
    """验证基础文本任务可产出主模型与回退链。"""

    plan = resolve_model_plan(
        ModelRoutingIntent(
            task_type="general",
            quality_tier="standard",
            budget_tier="balanced",
            latency_tier="medium",
            risk_level="medium",
            region="cn-beijing",
            input_chars=1200,
            affair_name="routing_minimal_test",
        )
    )
    assert isinstance(plan.primary_model, str) and plan.primary_model
    assert isinstance(plan.fallback_models, (list, tuple))
    assert isinstance(plan.reason, str) and plan.reason


def test_load_config_auto_route_without_network(tmp_path: Path, monkeypatch) -> None:
    """验证 auto 配置可在无网络下完成路由解析。"""

    api_key_file = tmp_path / "api_key.txt"
    api_key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    cfg = load_aliyun_llm_config(
        model="auto",
        api_key_file=str(api_key_file),
        affair_name="routing_minimal_test",
        route_hints={"task_type": "general", "budget_tier": "cheap", "input_chars": 800},
    )
    assert cfg.model
    assert cfg.routing_info.get("mode") in {"auto", "manual"}


def test_open_access_barrier_analysis_uses_unified_invoke(monkeypatch) -> None:
    """验证开放源工具的障碍分析已走统一路由入口。"""

    called = {"count": 0, "payload": None}

    def _fake_invoke(**kwargs):
        called["count"] += 1
        called["payload"] = kwargs
        return {"status": "PASS", "selected_model": "auto", "attempts": [], "response": {"text": "ok"}}

    monkeypatch.setattr(retrieval, "invoke_aliyun_llm", _fake_invoke)

    result = retrieval.analyze_barrier_with_bailian("please login to continue", "dummy-key-file")
    assert called["count"] == 1
    assert called["payload"]["route_hints"]["budget_tier"] == "cheap"
    assert result["status"] == "PASS"
