"""LLM Provider 抽象层与密钥安全回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodokit.tools import (
    batch_read_pairs_by_llm,
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
    mask_api_key,
    secret_path,
    secrets_dir,
)


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
    """验证内置 provider 注册。"""

    names = list_providers()
    assert "bailian" in names
    assert "lmstudio" in names


def test_get_provider_definitions() -> None:
    """验证 provider 定义关键字段。"""

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


def test_resolve_provider_auto_fallback(monkeypatch) -> None:
    """验证 auto 路由：本地离线时回退 bailian。"""

    monkeypatch.setattr("autodokit.tools.atomic.llm.llm_providers.is_local_online", lambda *a, **k: False)
    assert resolve_provider("auto") == "bailian"


def test_resolve_provider_auto_local_first(monkeypatch) -> None:
    """验证 auto 路由：本地在线时优先 lmstudio。"""

    monkeypatch.setattr("autodokit.tools.atomic.llm.llm_providers.is_local_online", lambda *a, **k: True)
    assert resolve_provider("auto") == "lmstudio"


def test_resolve_provider_explicit() -> None:
    """验证显式 provider 直接返回。"""

    assert resolve_provider("bailian") == "bailian"
    assert resolve_provider("LMSTUDIO") == "lmstudio"


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


def test_invoke_llm_success_shape(monkeypatch) -> None:
    """验证 invoke_llm 返回结构与失败时错误透传。"""

    class _FakeClient:
        model = "fake-model"

        def generate_text(self, **kwargs):
            return "ok text"

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers.build_llm_client",
        lambda *a, **k: (_FakeClient(), "bailian"),
    )
    result = invoke_llm(prompt="hi", provider="bailian")
    assert result["status"] == "PASS"
    assert result["provider"] == "bailian"
    assert result["response"]["text"] == "ok text"


def test_invoke_llm_failure_shape(monkeypatch) -> None:
    """验证 invoke_llm 异常时返回 FAIL 且含错误信息。"""

    def _raise(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("autodokit.tools.atomic.llm.llm_providers.build_llm_client", _raise)
    result = invoke_llm(prompt="hi")
    assert result["status"] == "FAIL"
    assert "boom" in result["error"]


def test_is_local_online_returns_false_for_cloud() -> None:
    """验证云端 provider 在线探测恒为 False。"""

    assert is_local_online(get_provider("bailian")) is False


def test_batch_read_pairs_by_llm_resume(monkeypatch, tmp_path: Path) -> None:
    """验证逐 Pair 调用 + 断点续跑（使用 fake invoke_llm，不真实调用）。"""

    from autodokit.tools.chat_session_index_tools import ChatSessionStore

    store = ChatSessionStore(tmp_path)
    store.initialize()
    store.import_messages(
        [
            {"role": "user", "content": "问题一"},
            {"role": "assistant", "content": "回答一"},
            {"role": "user", "content": "问题二"},
            {"role": "assistant", "content": "回答二"},
        ],
        source_name="demo.md",
        tags=["测试"],
    )
    pair_ids = store.session_index_path.exists() and [
        pid
        for session in __import__("json").loads(store.session_index_path.read_text(encoding="utf-8")).values()
        for pid in session.get("all_pair_ids", [])
    ]
    assert pair_ids and len(pair_ids) == 2

    calls = {"n": 0}

    def _fake_invoke(**kwargs):
        calls["n"] += 1
        return {"status": "PASS", "provider": "lmstudio", "selected_model": "m", "response": {"text": "摘要"}}

    monkeypatch.setattr("autodokit.tools.atomic.llm.llm_providers.invoke_llm", _fake_invoke)

    first = batch_read_pairs_by_llm(tmp_path, provider="lmstudio", max_tokens=64)
    assert first["total"] == 2
    assert first["processed"] == 2
    assert first["failed"] == 0
    assert calls["n"] == 2

    second = batch_read_pairs_by_llm(tmp_path, provider="lmstudio", max_tokens=64)
    assert second["processed"] == 0
    assert second["skipped"] == 2
    assert calls["n"] == 2  # 未新增调用
