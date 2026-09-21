"""大模型目录（LLM Catalog）回归测试。

覆盖范围：
1. 数据文件加载与结构校验（模型、provider、任务池、回退链）；
2. **按需筛选** API（``find_models`` 的各维度条件）；
3. 说明输出（``describe_model`` / ``format_model_table``）；
4. **兜底路径**——数据文件缺失或损坏时必须退回内置默认值而不中断；
5. 数据文件与代码访问器的**一致性**（防止两边漂移）；
6. provider 顺序的三种来源（数据文件 / 环境变量 / 按次参数）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodokit.tools.atomic.llm import llm_catalog
from autodokit.tools.atomic.llm.llm_catalog import (
    CatalogError,
    catalog_info,
    default_catalog_path,
    describe_model,
    find_models,
    format_model_table,
    get_model,
    list_models,
    load_catalog,
    parse_catalog,
    provider_priority,
    reload_catalog,
    try_load_catalog,
)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    """每个用例前后清掉目录缓存，避免相互污染。"""

    llm_catalog._CACHE.update({"catalog": None, "path": None, "error": ""})
    yield
    llm_catalog._CACHE.update({"catalog": None, "path": None, "error": ""})


# ---------- 数据文件本体 ----------


def test_data_file_exists_and_is_valid_json() -> None:
    """数据文件必须存在且是合法 JSON。"""

    path = default_catalog_path()
    assert path.is_file(), f"缺少目录数据文件: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)


def test_catalog_loads_core_sections() -> None:
    """核心分节必须齐全：providers / models / task_pools / 回退链。"""

    catalog = load_catalog()
    assert catalog.providers, "缺少 providers"
    assert catalog.models, "缺少 models"
    assert catalog.task_pools, "缺少 task_pools"
    assert catalog.cross_vendor_fallbacks, "缺少跨厂商回退链"
    assert catalog.region_base_urls, "缺少地域端点"
    assert catalog.vendor_rules, "缺少厂商识别规则"
    assert catalog.catalog_version, "缺少 catalog_version"


def test_provider_priority_from_data_file() -> None:
    """auto 路由顺序取自数据文件的 priority 字段。"""

    assert provider_priority() == ("deepseek", "bailian", "lmstudio")


def test_every_pool_model_exists_and_active() -> None:
    """任务池引用的模型必须存在且为 active（防止配置漂移）。"""

    catalog = load_catalog()
    for task_type, tiers in catalog.task_pools.items():
        for tier, model in tiers.items():
            assert catalog.has_model(model), f"{task_type}/{tier} → {model} 不在目录"
            assert catalog.get_model(model).is_active, f"{task_type}/{tier} → {model} 已下线"


def test_fallback_chain_models_exist() -> None:
    """回退链中的模型必须在目录中（否则会被静默丢弃）。"""

    catalog = load_catalog()
    for model in catalog.cross_vendor_fallbacks:
        assert catalog.has_model(model), f"回退链模型不存在: {model}"


def test_deprecated_replacement_targets_exist() -> None:
    """下线映射的目标必须是目录中的 active 模型（避免链式失效）。"""

    catalog = load_catalog()
    for old, new in catalog.deprecated_replacements.items():
        assert catalog.has_model(new), f"{old} → {new} 目标不存在"
        assert catalog.get_model(new).is_active, f"{old} → {new} 目标已下线"


def test_model_pricing_has_currency_and_source() -> None:
    """每个模型都要有明确的币种与价格来源（价格不可无出处）。"""

    for item in load_catalog().models.values():
        assert item.pricing.currency, f"{item.id} 缺 currency"
        assert item.pricing.unit == "per_million_tokens", f"{item.id} 计价单位异常"
        assert item.pricing.source, f"{item.id} 缺价格来源说明"


def test_model_limits_present() -> None:
    """每个模型都要声明上下文上限。"""

    for item in load_catalog().models.values():
        assert item.max_input_tokens > 0, f"{item.id} 缺 max_input_tokens"


def test_comment_only_entries_are_skipped_silently() -> None:
    """JSON 里的分节注释（只含 $comment 的对象）应被静默跳过，不产生告警。"""

    catalog = load_catalog()
    assert not catalog.warnings, f"存在多余告警: {catalog.warnings}"


# ---------- 按需筛选 ----------


def test_find_models_no_filter_returns_all_active() -> None:
    """无过滤条件时返回全部 active 模型（不含 deprecated）。"""

    found = find_models()
    assert found
    assert all(item.is_active for item in found)
    assert "qwen-long" not in {item.id for item in found}  # 已下线


def test_find_models_sorted_by_cost_then_id() -> None:
    """结果按 (cost_level, id) 升序，便于从便宜到贵挑选。"""

    found = find_models()
    keys = [(item.cost_level, item.id) for item in found]
    assert keys == sorted(keys)


def test_find_models_by_capability_vision_and_json() -> None:
    """能力筛选是 AND 关系。"""

    found = find_models(needs_vision=True, needs_json=True)
    assert found
    for item in found:
        assert item.capabilities.vision
        assert item.capabilities.json_output


def test_find_models_excludes_non_matching_capability() -> None:
    """不满足能力的模型必须被排除（用反例验证而非只查正例）。"""

    found = find_models(needs_vision=True, provider="lmstudio")
    assert found == [], "本地模型均无视觉能力，不应命中"


def test_find_models_by_cost_ceiling() -> None:
    """成本上限过滤生效。"""

    found = find_models(max_cost_level=1)
    assert found
    assert all(item.cost_level <= 1 for item in found)
    # 高档模型必须被排除。
    assert "qwen3.8-max" not in {item.id for item in found}


def test_find_models_by_min_input_tokens() -> None:
    """上下文下限过滤生效。"""

    found = find_models(min_input_tokens=1_000_000)
    assert found
    assert all(item.max_input_tokens >= 1_000_000 for item in found)


def test_find_models_by_currency() -> None:
    """币种过滤生效（用于区分计费来源）。"""

    usd = find_models(currency="USD")
    assert usd
    assert all(item.pricing.currency == "USD" for item in usd)


def test_find_models_verified_pricing_only() -> None:
    """可只挑价格经人工核对的模型。"""

    found = find_models(verified_pricing_only=True)
    assert found
    assert all(item.pricing.verified for item in found)


def test_find_models_status_all_includes_deprecated() -> None:
    """``status="*"`` 时包含已下线模型。"""

    all_models = find_models(status="*")
    ids = {item.id for item in all_models}
    assert "qwen-long" in ids
    assert len(all_models) > len(find_models())


def test_list_models_by_provider() -> None:
    """按 provider 列模型。"""

    deepseek = list_models(provider="deepseek")
    assert deepseek
    assert all(item.provider == "deepseek" for item in deepseek)
    # 排序与 find_models 一致：(cost_level, id) 升序。
    keys = [(item.cost_level, item.id) for item in deepseek]
    assert keys == sorted(keys)


def test_list_models_by_task_type() -> None:
    """按任务类型列模型。"""

    vision = list_models(task_type="vision")
    assert vision
    assert all("vision" in item.task_types for item in vision)


# ---------- 说明输出 ----------


def test_get_model_case_insensitive() -> None:
    """模型查找大小写不敏感。"""

    assert get_model("DeepSeek-Flash") is not None
    assert get_model("DEEPSEEK-FLASH").id == "deepseek-flash"


def test_get_model_missing_returns_none() -> None:
    """不存在的模型返回 None 而非抛异常。"""

    assert get_model("不存在-xyz") is None


def test_describe_model_reports_params_and_pricing() -> None:
    """说明必须包含用户决策所需的参数、能力与价格。"""

    info = describe_model("deepseek-flash")
    assert info["found"] is True
    assert info["pricing"]["currency"] == "USD"
    assert info["pricing"]["input"] > 0
    assert info["pricing"]["verified"] is True
    assert info["limits"]["max_input_tokens"] == 1_000_000
    assert info["capabilities"]["vision"] is True
    # 可读文本必须点出价格与币种，便于人工核对。
    assert "USD" in info["text"]
    assert "1,000,000" in info["text"]


def test_describe_model_missing() -> None:
    """说明不存在的模型时返回 found=False。"""

    info = describe_model("不存在-xyz")
    assert info["found"] is False
    assert "error" in info


def test_format_model_table_renders_rows() -> None:
    """表格渲染包含标题与模型行。"""

    table = format_model_table(find_models(provider="deepseek"))
    assert "模型" in table
    assert "deepseek-flash" in table


def test_format_model_table_honours_limit() -> None:
    """行数上限生效并给出省略提示。"""

    table = format_model_table(find_models(), limit=2)
    assert "另有" in table


def test_catalog_info_shape() -> None:
    """概览信息含版本、计数与 provider 顺序。"""

    info = catalog_info()
    assert info["available"] is True
    assert info["models_total"] > 0
    assert info["providers"] == ["deepseek", "bailian", "lmstudio"]
    assert info["cross_vendor_fallbacks"]


# ---------- 兜底路径（关键健壮性） ----------


def test_missing_file_raises_catalog_error(tmp_path: Path, monkeypatch) -> None:
    """数据文件不存在时抛 CatalogError（由调用方决定是否降级）。"""

    monkeypatch.setenv("AUTODO_SUITE_SECRETS_DIR", str(tmp_path))
    with pytest.raises(CatalogError):
        load_catalog(tmp_path / "缺失.json")


def test_broken_json_raises_catalog_error(tmp_path: Path) -> None:
    """JSON 损坏时抛 CatalogError 且错误信息含路径。"""

    broken = tmp_path / "broken.json"
    broken.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(CatalogError) as excinfo:
        load_catalog(broken)
    assert "broken.json" in str(excinfo.value)


def test_try_load_returns_error_instead_of_raising(tmp_path: Path) -> None:
    """``try_load_catalog`` 以返回值报告失败，不抛异常。"""

    catalog, error = try_load_catalog(tmp_path / "缺失.json")
    assert catalog is None
    assert error


def test_clients_fall_back_when_catalog_missing(tmp_path: Path, monkeypatch) -> None:
    """**关键**：数据文件不可用时，路由必须退回内置兜底，功能不中断。"""

    from autodokit.tools.atomic.llm import llm_clients

    monkeypatch.setattr(llm_catalog, "default_catalog_path", lambda: tmp_path / "无.json")
    monkeypatch.setattr(llm_catalog, "_CACHE", {"catalog": None, "path": None, "error": ""})

    catalog = llm_clients._get_model_catalog()
    assert catalog, "兜底目录不应为空"
    assert llm_clients._get_model_pool().get("general")
    assert llm_clients._get_cross_vendor_fallbacks()
    # 兜底时也要有告警可查。
    assert llm_clients.catalog_warnings()


def test_providers_fall_back_when_catalog_missing(tmp_path: Path, monkeypatch) -> None:
    """**关键**：数据文件不可用时，provider 注册表必须退回内置兜底。"""

    from autodokit.tools.atomic.llm import llm_providers

    monkeypatch.setattr(llm_catalog, "default_catalog_path", lambda: tmp_path / "无.json")
    monkeypatch.setattr(llm_catalog, "_CACHE", {"catalog": None, "path": None, "error": ""})

    names = llm_providers.list_providers()
    assert "deepseek" in names and "bailian" in names and "lmstudio" in names


# ---------- 内存解析（不经文件） ----------


def test_parse_catalog_minimal_payload() -> None:
    """最小合法负载应可解析。"""

    catalog = parse_catalog(
        {
            "catalog_version": "test-1",
            "providers": [{"name": "only", "priority": 1, "default_model": "m1"}],
            "models": [
                {
                    "id": "m1",
                    "vendor": "alibaba",
                    "provider": "only",
                    "pricing": {"currency": "CNY", "input": 1, "output": 2},
                }
            ],
        },
        source_path="memory",
    )
    assert catalog.catalog_version == "test-1"
    assert catalog.provider_priority() == ("only",)
    assert catalog.get_model("M1").id == "m1"


def test_parse_catalog_rejects_empty_models() -> None:
    """没有任何模型时应报错（避免路由拿到空目录后静默失效）。"""

    with pytest.raises(CatalogError):
        parse_catalog({"providers": [], "models": []})


def test_parse_catalog_warns_on_duplicate_model() -> None:
    """重复定义同一模型时给出告警（后者覆盖前者）。"""

    catalog = parse_catalog(
        {
            "models": [
                {"id": "dup", "vendor": "a", "pricing": {"currency": "CNY"}},
                {"id": "dup", "vendor": "b", "pricing": {"currency": "CNY"}},
            ]
        }
    )
    assert any("重复" in item for item in catalog.warnings)
    assert catalog.get_model("dup").vendor == "b"


def test_parse_catalog_ignores_comment_only_objects() -> None:
    """只含 $comment 的分节对象不产生告警。"""

    catalog = parse_catalog(
        {
            "models": [
                {"$comment": "=== 分节 ==="},
                {"id": "real", "pricing": {"currency": "CNY"}},
            ]
        }
    )
    assert not catalog.warnings
    assert catalog.get_model("real") is not None


def test_infer_vendor_from_rules() -> None:
    """厂商识别支持前缀与 ``厂商/`` 形式。"""

    catalog = load_catalog()
    assert catalog.infer_vendor("qwen3.8-max") == "alibaba"
    assert catalog.infer_vendor("ZHIPU/GLM-5.3") == "zhipu"
    assert catalog.infer_vendor("kimi/kimi-k3") == "moonshot"
    assert catalog.infer_vendor("未知模型-x") == ""


def test_is_cn_only_uses_data_file_prefixes() -> None:
    """仅中国内地的判定取自数据文件。"""

    catalog = load_catalog()
    assert catalog.is_cn_only("qwen-long") is True
    assert catalog.is_cn_only("qwen3.8-max") is False


def test_reload_reflects_file_changes(tmp_path: Path) -> None:
    """**热更新能力**：改完 JSON 调 reload 即生效，无需改代码。"""

    data = tmp_path / "c.json"
    data.write_text(
        json.dumps(
            {
                "catalog_version": "v1",
                "providers": [{"name": "p", "priority": 1}],
                "models": [{"id": "m1", "pricing": {"currency": "CNY"}}],
            }
        ),
        encoding="utf-8",
    )
    assert load_catalog(data).catalog_version == "v1"

    data.write_text(
        json.dumps(
            {
                "catalog_version": "v2",
                "providers": [{"name": "p", "priority": 1}],
                "models": [
                    {"id": "m1", "pricing": {"currency": "CNY"}},
                    {"id": "m2", "pricing": {"currency": "CNY"}},
                ],
            }
        ),
        encoding="utf-8",
    )
    # 未刷新前仍是缓存值。
    assert load_catalog(data).catalog_version == "v1"
    # 强制刷新后生效。
    refreshed = reload_catalog(data)
    assert refreshed.catalog_version == "v2"
    assert refreshed.get_model("m2") is not None
