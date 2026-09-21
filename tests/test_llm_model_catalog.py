"""LLM 模型目录、跨厂商回退链与切换审计回归测试。

覆盖范围：
1. 厂商标识推断（含 ``厂商/模型`` 前缀形式）；
2. 各成本档位的主模型选择（2026-09 百炼官方主推模型）；
3. 回退链的构成与顺序（同系列优先、跨厂商兜底）；
4. 视觉任务对跨厂商模型的过滤；
5. 模型下线映射（``deprecated_replacements``）与主模型一致；
6. 切换审计报告（未切换 / 同厂商切换 / 跨厂商切换 / 全失败）。
"""

from __future__ import annotations

import pytest

from autodokit.tools.atomic.llm.llm_clients import (
    _get_cross_vendor_fallbacks,
    _get_deprecated_replacements,
    _get_model_catalog,
    _get_model_pool,
    ModelRoutingIntent,
    _build_switching_report,
    _infer_model_vendor,
    _normalize_model_name,
    resolve_model_plan,
)


# ---------- 厂商标识 ----------


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("qwen3.8-max", "alibaba"),
        ("qwen3.7-plus", "alibaba"),
        ("qwen3.8-flash", "alibaba"),
        ("deepseek-v4-pro-0813", "deepseek"),
        ("deepseek-v4.1-flash", "deepseek"),
        ("kimi-k3", "moonshot"),
        ("kimi/kimi-k3", "moonshot"),
        ("glm-5.2", "zhipu"),
        ("ZHIPU/GLM-5.3", "zhipu"),
        ("MiniMax-M3", "minimax"),
        ("mimo-v2.5-pro", "xiaomi"),
        ("", "unknown"),
        ("brand-new-model-x", "unknown"),
    ],
)
def test_infer_model_vendor(model: str, expected: str) -> None:
    """厂商标识应正确识别千问与各第三方模型（含前缀形式）。"""

    assert _infer_model_vendor(model) == expected


def test_infer_model_vendor_is_case_insensitive() -> None:
    """厂商标识应大小写不敏感（官方文档存在 ``ZHIPU/GLM-5.3`` 这类写法）。"""

    assert _infer_model_vendor("QWEN3.8-MAX") == "alibaba"
    assert _infer_model_vendor("DeepSeek-V4-PRO-0813") == "deepseek"


# ---------- 主模型池 ----------


@pytest.mark.parametrize("task_type", sorted(_get_model_pool()))
def test_pool_models_exist_in_catalog(task_type: str) -> None:
    """模型池中的每个模型都必须能在目录中查到（否则回退链会静默丢弃）。"""

    for tier, model in _get_model_pool()[task_type].items():
        assert model in _get_model_catalog(), f"{task_type}/{tier} → {model} 不在目录中"


def test_pool_uses_2026_09_official_primary_models() -> None:
    """主模型池应与百炼 2026-09-14 官方主推保持一致。

    官方文本生成前三位：``qwen3.8-max`` / ``qwen3.7-plus`` / ``qwen3.8-flash``。
    plus 档官方尚未发布 3.8，故 balanced 仍为 ``qwen3.7-plus``。
    """

    general = _get_model_pool()["general"]
    assert general["cheap"] == "qwen3.8-flash"
    assert general["balanced"] == "qwen3.7-plus"
    assert general["premium"] == "qwen3.8-max"


def test_pool_models_are_not_deprecated() -> None:
    """模型池不应引用已下线模型。"""

    for task_type, tiers in _get_model_pool().items():
        for tier, model in tiers.items():
            assert _get_model_catalog()[model].status == "active", (
                f"{task_type}/{tier} → {model} 已下线"
            )


# ---------- 下线映射 ----------


def test_deprecated_replacements_resolve_successfully() -> None:
    """下线映射的目标必须是目录中的 active 模型（避免链式失效）。"""

    for old, new in _get_deprecated_replacements().items():
        assert new in _get_model_catalog(), f"{old} → {new} 目标不存在"
        assert _get_model_catalog()[new].status == "active", f"{old} → {new} 目标已下线"


def test_qwen37_plus_remains_active() -> None:
    """``qwen3.7-plus`` 是官方仍主推的 balanced 档模型，不得被标记下线。"""

    assert _get_model_catalog()["qwen3.7-plus"].status == "active"
    assert "qwen3.7-plus" not in _get_deprecated_replacements()


def test_normalize_keeps_37_generation() -> None:
    """3.7 代型号不得被静默改写。

    早期版本曾把 ``qwen3.7-max`` / ``qwen3.7-flash`` 映射到 3.8 同档，
    依据仅是「官网主推列表里出现了 3.8」。但官方只列每档主推款，
    **“不在主推列表”不等于“已下线”**；用户的 VS Code 配置中这两型仍可调用，
    构成了反证。因此已移除该映射（行为：显式指定则原样保留）。
    """

    for model in ("qwen3.7-max", "qwen3.7-flash", "qwen3.7-plus"):
        assert _normalize_model_name(model) == model, f"{model} 被静默改写"


@pytest.mark.parametrize(
    "model",
    [
        "qwen3.6-plus",
        "qwen3.5-plus",
        "qwen3.5-flash",
        "qwen3-coder-flash",
        "qwen3.7-max",
        "qwen3.7-flash",
    ],
)
def test_previous_generation_stays_active(model: str) -> None:
    """上一代型号不得因「不在主推列表」而被推断为下线。

    官方「选择模型」页只列每档主推款，其余历史版本仍可调用。
    将「不主推」等同于「已下线」属过度推断，会静默改写用户的显式模型选择。
    本测试守护该边界：只有「同档位确有新一代替代」或「官方公告明示下线」
    才可进入 ``deprecated_replacements``。
    """

    assert model in _get_model_catalog()
    assert _get_model_catalog()[model].status == "active", f"{model} 被无依据地下线"
    assert model not in _get_deprecated_replacements(), f"{model} 被无依据地重写"
    # 显式指定时应原样保留，不被静默改写。
    assert _normalize_model_name(model) == model


# ---------- 回退链 ----------


@pytest.mark.parametrize("tier", ["cheap", "balanced", "premium"])
def test_fallback_chain_contains_cross_vendor(tier: str) -> None:
    """回退链必须包含跨厂商模型，以抵抗单模型族故障。"""

    plan = resolve_model_plan(
        ModelRoutingIntent(model="auto", affair_name="", budget_tier=tier)
    )
    assert "deepseek-v4.1-flash" in plan.fallback_models
    assert any(
        _infer_model_vendor(model) == "deepseek" for model in plan.fallback_models
    )


def test_fallback_chain_cross_vendor_comes_last() -> None:
    """跨厂商模型应排在**同系列**候选之后（能力差异大，宜作最后手段）。"""

    plan = resolve_model_plan(
        ModelRoutingIntent(model="auto", affair_name="", budget_tier="balanced")
    )
    chain = list(plan.fallback_models)
    first_cross = next(
        index
        for index, model in enumerate(chain)
        if _infer_model_vendor(model) != "alibaba"
    )
    # 跨厂商段之前不应混入其它厂商模型。
    assert all(
        _infer_model_vendor(model) == "alibaba" for model in chain[:first_cross]
    )


def test_fallback_chain_excludes_primary() -> None:
    """回退链不得包含主模型（否则会重复尝试同一模型）。"""

    plan = resolve_model_plan(
        ModelRoutingIntent(model="auto", affair_name="", budget_tier="balanced")
    )
    assert plan.primary_model not in plan.fallback_models


def test_fallback_chain_has_no_duplicates() -> None:
    """回退链必须去重且保序。"""

    plan = resolve_model_plan(
        ModelRoutingIntent(model="auto", affair_name="", budget_tier="cheap")
    )
    chain = list(plan.fallback_models)
    assert len(chain) == len(set(chain))


def test_vision_task_filters_cross_vendor() -> None:
    """视觉任务不得回退到无视觉能力的跨厂商模型。"""

    plan = resolve_model_plan(
        ModelRoutingIntent(
            model="auto", affair_name="", task_type="vision", budget_tier="balanced"
        )
    )
    for model in plan.fallback_models:
        entry = _get_model_catalog()[model]
        assert "vision" in entry.task_types, f"{model} 不支持视觉却进入视觉回退链"
    # 跨厂商候选均无视觉能力，故整段应被过滤掉。
    assert not any(
        model in _get_cross_vendor_fallbacks() for model in plan.fallback_models
    )


# ---------- 切换审计 ----------


def test_switching_report_no_switch() -> None:
    """未切换时应报告无切换并给出所用厂商。"""

    report = _build_switching_report(
        [{"model": "qwen3.7-plus", "vendor": "alibaba", "status": "PASS", "error": ""}],
        primary_model="qwen3.7-plus",
        selected_model="qwen3.7-plus",
    )
    assert report["switched"] is False
    assert report["cross_vendor"] is False
    assert report["selected_vendor"] == "alibaba"
    assert "无切换" in report["summary"]


def test_switching_report_same_vendor_switch() -> None:
    """同厂商回退应记录失败链与原因，但不标记跨厂商。"""

    report = _build_switching_report(
        [
            {
                "model": "qwen3.8-flash",
                "vendor": "alibaba",
                "status": "FAIL",
                "error": "429 rate limit",
            },
            {"model": "qwen3.7-plus", "vendor": "alibaba", "status": "PASS", "error": ""},
        ],
        primary_model="qwen3.8-flash",
        selected_model="qwen3.7-plus",
    )
    assert report["switched"] is True
    assert report["cross_vendor"] is False
    assert report["failed_models"][0]["model"] == "qwen3.8-flash"
    assert "429 rate limit" in report["summary"]


def test_switching_report_cross_vendor_switch() -> None:
    """跨厂商回退必须被显式标注（人工据此判断质量来源）。"""

    report = _build_switching_report(
        [
            {
                "model": "qwen3.8-flash",
                "vendor": "alibaba",
                "status": "FAIL",
                "error": "model unavailable",
            },
            {
                "model": "deepseek-v4.1-flash",
                "vendor": "deepseek",
                "status": "PASS",
                "error": "",
            },
        ],
        primary_model="qwen3.8-flash",
        selected_model="deepseek-v4.1-flash",
    )
    assert report["switched"] is True
    assert report["cross_vendor"] is True
    assert report["selected_vendor"] == "deepseek"
    assert "跨厂商切换" in report["summary"]


def test_switching_report_all_failed() -> None:
    """全失败时应列出依次尝试过的全部模型，便于定位账户级故障。"""

    report = _build_switching_report(
        [
            {
                "model": "qwen3.8-flash",
                "vendor": "alibaba",
                "status": "FAIL",
                "error": "400 Arrearage",
            },
            {
                "model": "deepseek-v4.1-flash",
                "vendor": "deepseek",
                "status": "FAIL",
                "error": "400 Arrearage",
            },
        ],
        primary_model="qwen3.8-flash",
        selected_model="",
    )
    assert report["switched"] is False
    assert report["selected_model"] == ""
    assert len(report["failed_models"]) == 2
    assert "qwen3.8-flash" in report["summary"]
    assert "deepseek-v4.1-flash" in report["summary"]
