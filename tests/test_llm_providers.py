"""LLM Provider 抽象层与密钥安全回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodokit.tools import (
    build_llm_client,
    get_provider,
    invoke_llm,
    is_local_online,
    list_providers,
    resolve_provider,
)
from autodokit.tools.atomic.llm import (
    ensure_secrets_layout,
    iter_secret_candidates,
    list_secret_inventory,
    mask_api_key,
    secret_path,
    secrets_dir,
)
from autodokit.tools.atomic.llm.llm_providers import iter_provider_chain


def test_mask_api_key_basic() -> None:
    """验证脱敏函数保留头尾并隐藏中间。"""

    assert mask_api_key("sk-abcdef1234567890") == "sk-***7890"
    assert mask_api_key("") == ""
    assert mask_api_key(None) == ""


def test_secrets_dir_points_to_autodo_suite(tmp_path: Path, monkeypatch) -> None:
    """验证统一密钥仓库目录默认指向 ~/.config/autodo-suite/secrets。"""

    monkeypatch.delenv("AUTODO_SUITE_SECRETS_DIR", raising=False)
    assert secrets_dir().name == "secrets"
    assert ".config" in secrets_dir().parts and "autodo-suite" in secrets_dir().parts


def test_secret_path_and_candidates(tmp_path: Path, monkeypatch) -> None:
    """验证逻辑密钥名映射到标准文件名。"""

    monkeypatch.setenv("AUTODO_SUITE_SECRETS_DIR", str(tmp_path))
    assert secret_path("bailian").name == "bailian-api-key.txt"
    assert secret_path("lmstudio").name == "lmstudio-api-key.txt"
    candidates = iter_secret_candidates("bailian")
    assert any(p.name == "bailian-api-key.txt" for p in candidates)


def test_ensure_secrets_layout_creates_dir(tmp_path: Path, monkeypatch) -> None:
    """验证初始化创建目录。"""

    monkeypatch.setenv("AUTODO_SUITE_SECRETS_DIR", str(tmp_path / "sub"))
    created = ensure_secrets_layout()
    assert created.exists() and created.is_dir()


def test_list_providers_includes_builtin() -> None:
    """验证内置 provider 注册（含 DeepSeek）。"""

    names = list_providers()
    assert "deepseek" in names
    assert "bailian" in names
    assert "lmstudio" in names


def test_get_provider_definitions() -> None:
    """验证 provider 定义关键字段。"""

    deepseek = get_provider("deepseek")
    assert deepseek.sdk_backend == "openai-compatible"
    assert deepseek.secret_name == "deepseek"
    assert deepseek.default_base_url.startswith("https://api.deepseek.com")
    assert not deepseek.is_local

    bailian = get_provider("bailian")
    assert bailian.sdk_backend == "openai-compatible"
    assert bailian.secret_name == "bailian"
    assert not bailian.is_local

    lmstudio = get_provider("lmstudio")
    assert lmstudio.sdk_backend == "openai-compatible"
    assert lmstudio.default_base_url.startswith("http://127.0.0.1")
    assert lmstudio.secret_name == "lmstudio"
    assert lmstudio.is_local


def test_get_provider_unknown_raises() -> None:
    """验证未知 provider 抛 KeyError。"""

    with pytest.raises(KeyError):
        get_provider("unknown-provider")


def test_iter_provider_chain_default_order(monkeypatch) -> None:
    """验证 auto 路由的 provider 顺序：DeepSeek → 百炼 → 本地。

    本地模型排在最后（用户指定），与早期「本地优先」相反。
    """

    monkeypatch.delenv("AUTODO_LLM_PROVIDER_PRIORITY", raising=False)
    assert iter_provider_chain("auto") == ("deepseek", "bailian", "lmstudio")
    # 显式指定 provider 时不跨厂回退，尊重调用方选择。
    assert iter_provider_chain("bailian") == ("bailian",)


def test_iter_provider_chain_env_override(monkeypatch) -> None:
    """验证可用环境变量临时改变 auto 优先级（无需改数据文件）。

    语义：``order`` / 环境变量指定的是**顺序**，不是白名单——
    未被列出的 provider 会被**追加到末尾**，避免因漏写而彻底不可达。
    """

    monkeypatch.setenv("AUTODO_LLM_PROVIDER_PRIORITY", "bailian,deepseek")
    assert iter_provider_chain("auto") == ("bailian", "deepseek", "lmstudio")


def test_iter_provider_chain_explicit_order(monkeypatch) -> None:
    """验证可**按次**指定顺序（本地优先），不改数据文件也不改环境变量。"""

    monkeypatch.delenv("AUTODO_LLM_PROVIDER_PRIORITY", raising=False)
    assert iter_provider_chain("auto", order="lmstudio,bailian,deepseek") == (
        "lmstudio",
        "bailian",
        "deepseek",
    )
    # 序列形式同样支持。
    assert iter_provider_chain("auto", order=["bailian", "lmstudio"])[0] == "bailian"
    # 显式 provider 不受 order 影响（单元素，不跨厂回退）。
    assert iter_provider_chain("bailian", order="lmstudio,deepseek") == ("bailian",)


def test_provider_order_ignores_unknown_names(monkeypatch) -> None:
    """顺序里出现未注册名时应忽略，而不是报错中断。"""

    monkeypatch.delenv("AUTODO_LLM_PROVIDER_PRIORITY", raising=False)
    chain = iter_provider_chain("auto", order="nonexistent,bailian")
    assert chain[0] == "bailian"
    assert "nonexistent" not in chain


def test_resolve_provider_auto_falls_back_to_priority_head(tmp_path: Path, monkeypatch) -> None:
    """验证 auto 路由：所有 provider 都不可用时返回优先级首位。

    返回首位而非任意项，是为了让报错指向用户最关心的 provider。
    """

    monkeypatch.setenv("AUTODO_SUITE_SECRETS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers.is_local_online", lambda *a, **k: False
    )
    assert resolve_provider("auto") == "deepseek"


def test_resolve_provider_auto_skips_unavailable_cloud(tmp_path: Path, monkeypatch) -> None:
    """验证 auto 路由：云端缺密钥时跳到本地（本地是最后兜底）。"""

    monkeypatch.setenv("AUTODO_SUITE_SECRETS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers.is_local_online", lambda *a, **k: True
    )
    assert resolve_provider("auto") == "lmstudio"


def test_resolve_provider_auto_prefers_deepseek_when_key_present(
    tmp_path: Path, monkeypatch
) -> None:
    """验证 auto 路由：凭据齐备时优先 DeepSeek（即使本地在线）。"""

    monkeypatch.setenv("AUTODO_SUITE_SECRETS_DIR", str(tmp_path))
    for name in ("deepseek", "bailian", "lmstudio"):
        (tmp_path / f"{name}-api-key.txt").write_text("k", encoding="utf-8")
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers.is_local_online", lambda *a, **k: True
    )
    assert resolve_provider("auto") == "deepseek"


def test_resolve_provider_explicit() -> None:
    """验证显式 provider 直接返回。"""

    assert resolve_provider("bailian") == "bailian"
    assert resolve_provider("deepseek") == "deepseek"
    assert resolve_provider("LMSTUDIO") == "lmstudio"


def test_secret_discovery_supports_profile_naming(tmp_path: Path, monkeypatch) -> None:
    """验证密钥发现支持 ``{名}_api-key_{档案}.txt`` 命名与大小写不敏感。

    真实仓库使用形如 ``DeepSeek_api-key_autodo-kit.txt`` 的文件名，
    早期实现只认 ``{名}-api-key.txt``，导致重命名后密钥“集体失联”。
    """

    monkeypatch.setenv("AUTODO_SUITE_SECRETS_DIR", str(tmp_path))
    (tmp_path / "DeepSeek_api-key_autodo-kit.txt").write_text("k", encoding="utf-8")

    assert secret_path("deepseek").name == "DeepSeek_api-key_autodo-kit.txt"
    assert secret_path("DEEPSEEK").name == "DeepSeek_api-key_autodo-kit.txt"
    # 旧命名仍应被识别（向后兼容）。
    (tmp_path / "kimi-api-key.txt").write_text("k", encoding="utf-8")
    assert secret_path("kimi").name == "kimi-api-key.txt"


def test_secret_inventory_reports_profile(tmp_path: Path, monkeypatch) -> None:
    """验证清单能解析出逻辑名与配置档案（仅元信息）。"""

    monkeypatch.setenv("AUTODO_SUITE_SECRETS_DIR", str(tmp_path))
    (tmp_path / "bailian_api-key_autodo-kit.txt").write_text("k", encoding="utf-8")
    (tmp_path / ".DS_Store").write_text("noise", encoding="utf-8")

    items = list_secret_inventory()
    assert len(items) == 1  # 隐藏文件被忽略
    assert items[0]["logical_name"] == "bailian"
    assert items[0]["profile"] == "autodo-kit"


def test_build_llm_client_uses_own_secret_only(tmp_path: Path, monkeypatch) -> None:
    """验证**凭据隔离**：每个 provider 只用自己的密钥，不串用他厂凭据。

    历史缺陷：``build_llm_client`` 对非本地 provider 不传 ``api_key_file``，
    于是回落到硬编码为 bailian/dashscope 的默认候选——导致把**百炼的凭据
    发给 DeepSeek**（服务端返回 401）。跨厂商误送凭据属凭据泄露风险，
    本测试守护该边界。
    """

    monkeypatch.setenv("AUTODO_SUITE_SECRETS_DIR", str(tmp_path))
    (tmp_path / "bailian_api-key_normal.txt").write_text("bailian-key-AAAA", encoding="utf-8")
    (tmp_path / "DeepSeek_api-key_normal.txt").write_text("deepseek-key-BBBB", encoding="utf-8")

    deepseek_client, _ = build_llm_client("deepseek")
    bailian_client, _ = build_llm_client("bailian")

    assert deepseek_client.api_key == "deepseek-key-BBBB"
    assert bailian_client.api_key == "bailian-key-AAAA"


def test_build_llm_client_local_uses_openai_compatible(tmp_path: Path, monkeypatch) -> None:
    """验证本地 provider 客户端走 openai-compatible + 统一密钥仓库。"""

    monkeypatch.setenv("AUTODO_SUITE_SECRETS_DIR", str(tmp_path))
    key_file = secret_path("lmstudio")
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text("local-token", encoding="utf-8")

    client, resolved = build_llm_client("lmstudio")
    assert resolved == "lmstudio"
    assert client.sdk_backend == "openai-compatible"
    assert client.base_url.startswith("http://127.0.0.1")
    assert client.model  # 默认模型非空


def test_invoke_llm_bailian_routed_shape(monkeypatch) -> None:
    """验证 ``invoke_llm(provider="bailian")`` 走模型级路由并透出切换审计。

    架构变更说明：bailian 分支不再直接调用 ``build_llm_client``，
    而是委托 ``invoke_aliyun_llm`` 以获得模型级回退链（同系列 → 跨厂商）。
    因此注入口相应变为 ``invoke_aliyun_llm``。
    """

    def _fake_invoke_aliyun_llm(**kwargs):
        return {
            "status": "PASS",
            "selected_model": "qwen3.7-plus",
            "selected_vendor": "alibaba",
            "attempts": [
                {"model": "qwen3.7-plus", "vendor": "alibaba", "status": "PASS", "error": ""}
            ],
            "switching": {
                "switched": False,
                "cross_vendor": False,
                "summary": "使用 qwen3.7-plus（alibaba），无切换",
            },
            "response": {"text": "ok text"},
            "error": "",
        }

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers.invoke_aliyun_llm",
        _fake_invoke_aliyun_llm,
    )
    result = invoke_llm(prompt="hi", provider="bailian")
    assert result["status"] == "PASS"
    assert result["provider"] == "bailian"
    assert result["selected_model"] == "qwen3.7-plus"
    assert result["selected_vendor"] == "alibaba"
    assert result["response"]["text"] == "ok text"
    # 切换审计必须存在且带 mode，供上层汇报。
    assert result["switching"]["mode"] == "routed"
    assert result["switching"]["summary"]


def test_invoke_llm_failure_shape(monkeypatch) -> None:
    """验证 invoke_llm 在 provider 内部异常时返回 FAIL 且保留原始错误。"""

    def _raise(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers.invoke_aliyun_llm", _raise
    )
    result = invoke_llm(prompt="hi", provider="bailian")
    assert result["status"] == "FAIL"
    assert result["error"] == "all_providers_failed"
    # 原始错误不应丢失，而是下沉到逐 provider 审计中。
    assert "boom" in result["provider_attempts"][0]["error"]
    assert result["provider_switching"]["failed_providers"][0]["provider"] == "bailian"


def test_invoke_llm_local_provider_shape(monkeypatch) -> None:
    """验证本地 provider 在 provider 内按模型链调用，并标记自身审计模式。"""

    class _FakeClient:
        api_key = "k"

        def __init__(self, model: str) -> None:
            # 真实客户端会把**配置生效的模型名**回显在 .model 上。
            self.model = model

        def generate_text(self, **kwargs):
            return "local text"

    def _fake_build(provider, *, model="", **kwargs):
        return (_FakeClient(model or "qwen/qwen3.5-9b"), "lmstudio")

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers.build_llm_client", _fake_build
    )
    result = invoke_llm(prompt="hi", provider="lmstudio")
    assert result["status"] == "PASS"
    assert result["provider"] == "lmstudio"
    assert result["selected_model"] == "qwen/qwen3.5-9b"
    assert result["response"]["text"] == "local text"
    assert result["switching"]["mode"] == "provider-internal"
    # 首模型即成功，不应被记为“已切换”。
    assert result["switching"]["switched"] is False


def test_invoke_llm_bailian_with_custom_base_url(monkeypatch) -> None:
    """验证显式 base_url 时走 provider 内直连（不套用百炼地域路由）。"""

    class _FakeClient:
        api_key = "k"

        def __init__(self, model: str) -> None:
            self.model = model

        def generate_text(self, **kwargs):
            return "custom text"

    def _fake_build(provider, *, model="", **kwargs):
        return (_FakeClient(model or "custom-endpoint-model"), "bailian")

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers.build_llm_client", _fake_build
    )
    result = invoke_llm(
        prompt="hi", provider="bailian", base_url="https://example.invalid/v1"
    )
    assert result["status"] == "PASS"
    assert result["switching"]["mode"] == "provider-internal"
    assert result["selected_model"] == "qwen3.7-plus"


def test_invoke_llm_falls_back_across_providers(monkeypatch) -> None:
    """验证 **provider 级回退**：首选失败自动换下一家，并给出切换审计。

    这是抗“平台级故障”（如账户欠费、服务不可用）的关键能力——
    模型级回退救不了同账户全模型同时失败的情况。
    """

    called: list[str] = []

    def _fake_within(provider_name, **kwargs):
        called.append(provider_name)
        if provider_name == "deepseek":
            return {
                "status": "FAIL",
                "selected_model": "",
                "selected_vendor": "",
                "attempts": [],
                "switching": {},
                "response": {},
                "error": "402 Insufficient Balance",
            }
        return {
            "status": "PASS",
            "selected_model": "qwen3.7-plus",
            "selected_vendor": "alibaba",
            "attempts": [
                {"model": "qwen3.7-plus", "vendor": "alibaba", "status": "PASS", "error": ""}
            ],
            "switching": {
                "switched": False,
                "cross_vendor": False,
                "selected_model": "qwen3.7-plus",
                "summary": "使用 qwen3.7-plus（alibaba），无切换",
            },
            "response": {"text": "ok"},
            "error": "",
        }

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider", _fake_within
    )
    result = invoke_llm(prompt="hi", provider="auto")

    assert called == ["deepseek", "bailian"]  # 失败后立即换下一家，未试本地
    assert result["status"] == "PASS"
    assert result["provider"] == "bailian"
    assert result["provider_switching"]["switched"] is True
    assert result["provider_switching"]["primary_provider"] == "deepseek"
    assert result["provider_switching"]["selected_provider"] == "bailian"
    # 汇总必须显式说明「换了哪一家」，供人工判断产出质量来源。
    assert "deepseek" in result["switching"]["summary"]
    assert "bailian" in result["switching"]["summary"]


def test_invoke_llm_all_providers_failed(monkeypatch) -> None:
    """验证全链失败时列出依次尝试过的全部 provider。"""

    def _fail(provider_name, **kwargs):
        return {
            "status": "FAIL",
            "selected_model": "",
            "selected_vendor": "",
            "attempts": [],
            "switching": {},
            "response": {},
            "error": f"{provider_name} unavailable",
        }

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider", _fail
    )
    result = invoke_llm(prompt="hi", provider="auto")

    assert result["status"] == "FAIL"
    assert result["error"] == "all_providers_failed"
    assert result["provider_switching"]["attempted_providers"] == [
        "deepseek",
        "bailian",
        "lmstudio",
    ]
    assert len(result["provider_switching"]["failed_providers"]) == 3


def test_is_local_online_returns_false_for_cloud() -> None:
    """验证云端 provider 在线探测恒为 False。"""

    assert is_local_online(get_provider("bailian")) is False


