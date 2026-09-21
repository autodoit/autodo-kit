"""模型候选清单（「点菜单」）的行为测试。

覆盖两个新增能力：

1. **反查**：``resolve_model_provider`` 把模型名解析到提供它的平台。
   关键点是 ``provider`` 与 ``vendor`` **不等价**——百炼是聚合平台，
   同一厂商的模型可能经百炼提供（如 ``deepseek-v4.1-flash``）。
2. **按序上菜**：``invoke_llm(model_candidates=[...])`` 按调用方给的顺序
   逐个尝试，最靠前的优先用；清单耗尽即失败，除非显式要求回落常规链。

设计意图：把「选哪个模型」从工具内部的优先级表，变成业务方自己可写的清单——
业务方比工具更清楚自己那批任务要什么（成本优先 / 质量优先 / 本地优先）。
"""

from __future__ import annotations

import pytest

from autodokit.tools.atomic.llm import invoke_llm
from autodokit.tools.atomic.llm.llm_providers import (
    model_provider_map,
    parse_model_candidates,
    resolve_model_provider,
)

# --------------------------------------------------------------------------
# 候选清单解析
# --------------------------------------------------------------------------


def test_parse_model_candidates_accepts_comma_string() -> None:
    """逗号分隔字符串应按序解析并去重。"""

    assert parse_model_candidates("deepseek-flash, qwen3.8-flash ,deepseek-flash") == [
        "deepseek-flash",
        "qwen3.8-flash",
    ]


def test_parse_model_candidates_preserves_case() -> None:
    """模型 id 大小写敏感，解析不得小写化。

    反例守护：与 provider 名不同，``MiniMax-M3``、``qwen/qwen3.5-9b``
    统一小写会得到目录里不存在的名字。
    """

    assert parse_model_candidates(["MiniMax-M3", "qwen/qwen3.5-9b"]) == [
        "MiniMax-M3",
        "qwen/qwen3.5-9b",
    ]


def test_parse_model_candidates_empty_inputs() -> None:
    """None / 空串 / 纯空白均返回空列表（表示不使用点菜单）。"""

    assert parse_model_candidates(None) == []
    assert parse_model_candidates("") == []
    assert parse_model_candidates(["", "  "]) == []


# --------------------------------------------------------------------------
# 模型 → provider 反查
# --------------------------------------------------------------------------


def test_resolve_model_provider_prefers_catalog_provider_over_vendor() -> None:
    """反查必须以目录的 ``provider`` 为准，而非按厂商推断。

    ``deepseek-v4.1-flash`` 的 vendor 是 deepseek，但服务由百炼提供。
    若按 vendor 路由到 DeepSeek 官方端点，会得到 404（该账户无此模型）。
    """

    assert resolve_model_provider("deepseek-v4.1-flash") == "bailian"
    assert resolve_model_provider("deepseek-flash") == "deepseek"
    assert resolve_model_provider("MiniMax-M3") == "bailian"
    assert resolve_model_provider("qwen/qwen3.5-9b") == "lmstudio"


def test_resolve_model_provider_is_case_insensitive() -> None:
    """目录查找不区分大小写，别名大小写应解析到同一 provider。"""

    assert resolve_model_provider("DEEPSEEK-FLASH") == "deepseek"
    assert resolve_model_provider("deepseek-Flash") == "deepseek"


def test_resolve_model_provider_returns_empty_for_unknown() -> None:
    """未知模型返回空串，交调用方决定兜底策略（不猜测）。"""

    assert resolve_model_provider("no-such-model-xyz") == ""
    assert resolve_model_provider("") == ""
    assert resolve_model_provider("   ") == ""


def test_model_provider_map_flags_unresolved() -> None:
    """预检表应标出无法判定归属的候选，便于提前发现拼写错误。"""

    table = model_provider_map(["deepseek-flash", "nope-not-real"])
    assert table[0] == {"model": "deepseek-flash", "provider": "deepseek", "registered": "True"}
    assert table[1]["registered"] == "False"
    assert table[1]["provider"] == ""


# --------------------------------------------------------------------------
# 按序上菜（菜单模式）
# --------------------------------------------------------------------------


def _stub_within_provider(outcomes: dict[str, dict], calls: list[tuple[str, str]]):
    """构造 ``_invoke_within_provider`` 的替身：按模型名返回预设结果。

    Args:
        outcomes: 模型名 → 结果体（缺省视为失败）。
        calls: 记录 ``(provider, model)`` 调用次序的列表。

    Returns:
        可替换 ``_invoke_within_provider`` 的函数。
    """

    def _fake(provider_name, *, model="", **kwargs):
        calls.append((provider_name, model))
        preset = outcomes.get(model)
        if preset is None:
            return {
                "status": "FAIL",
                "selected_model": "",
                "selected_vendor": "",
                "attempts": [],
                "switching": {},
                "response": {},
                "error": f"unsupported model {model}",
            }
        return preset

    return _fake


def _pass(model: str, vendor: str = "alibaba") -> dict:
    """构造一条成功结果。"""

    return {
        "status": "PASS",
        "selected_model": model,
        "selected_vendor": vendor,
        "attempts": [{"model": model, "vendor": vendor, "status": "PASS", "error": ""}],
        "switching": {},
        "response": {"text": "ok"},
        "error": "",
    }


def test_invoke_llm_uses_first_candidate(monkeypatch) -> None:
    """首个候选可用时就应该用它，不该越位试探后面的。"""

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider({"qwen3.7-flash": _pass("qwen3.7-flash")}, calls),
    )

    result = invoke_llm(
        prompt="hi", model_candidates=["qwen3.7-flash", "deepseek-flash"]
    )

    assert result["status"] == "PASS"
    assert result["selected_model"] == "qwen3.7-flash"
    assert result["candidate_index"] == 0
    assert result["switching"]["mode"] == "model-candidates"
    assert result["switching"]["switched"] is False
    assert calls == [("bailian", "qwen3.7-flash")]


def test_invoke_llm_advances_to_next_candidate_on_failure(monkeypatch) -> None:
    """前一道菜端不出来就上下一个，并如实记录失败原因。"""

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider({"deepseek-flash": _pass("deepseek-flash", "deepseek")}, calls),
    )

    result = invoke_llm(
        prompt="hi", model_candidates=["qwen3.7-flash", "deepseek-flash"]
    )

    assert result["status"] == "PASS"
    assert result["selected_model"] == "deepseek-flash"
    assert result["candidate_index"] == 1
    assert result["switching"]["switched"] is True
    # 跨平台切换必须被点明——产出内容已不是首选平台生成的。
    assert result["switching"]["cross_vendor"] is True
    assert "qwen3.7-flash" in result["switching"]["summary"]
    assert calls == [("bailian", "qwen3.7-flash"), ("deepseek", "deepseek-flash")]
    # 逐候选尝试记录要完整，便于事后排查为什么没用首选。
    assert [item["status"] for item in result["attempts"]] == ["FAIL", "PASS"]
    assert result["attempts"][0]["requested_model"] == "qwen3.7-flash"


def test_invoke_llm_candidates_exhausted_fails_without_widening(monkeypatch) -> None:
    """清单耗尽即失败——**不得**擅自扩大到清单之外的模型。

    「清单就是意图」：业务方没点的菜不该上，否则出问题无从归因。
    """

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider({}, calls),
    )

    result = invoke_llm(prompt="hi", model_candidates=["qwen3.7-flash", "deepseek-flash"])

    assert result["status"] == "FAIL"
    assert result["candidate_index"] == -1
    assert "qwen3.7-flash" in result["error"]
    assert calls == [("bailian", "qwen3.7-flash"), ("deepseek", "deepseek-flash")]


def test_invoke_llm_candidates_fallback_to_chain_when_requested(monkeypatch) -> None:
    """显式要求兜底时，清单耗尽后回落常规 provider 链，并保留候选失败记录。"""

    calls: list[tuple[str, str]] = []

    def _fake(provider_name, *, model="", **kwargs):
        calls.append((provider_name, model))
        if model == "qwen3.7-flash":
            return {
                "status": "FAIL",
                "selected_model": "",
                "selected_vendor": "",
                "attempts": [],
                "switching": {},
                "response": {},
                "error": "402 Insufficient Balance",
            }
        return _pass("deepseek-flash", "deepseek")

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider", _fake
    )

    result = invoke_llm(
        prompt="hi",
        model_candidates=["qwen3.7-flash"],
        fallback_to_chain=True,
    )

    assert result["status"] == "PASS"
    # 回落链后按 provider 优先级重试：deepseek 在 bailian 之前。
    # 注意链模式不指定 model（空串），交 provider 自己挑默认模型。
    assert calls == [("bailian", "qwen3.7-flash"), ("deepseek", "")]
    assert result["switching"]["fallback_to_chain"] is True
    assert result["switching"]["candidate_failures"][0]["model"] == "qwen3.7-flash"
    assert "回落常规链" in result["switching"]["summary"]


def test_invoke_llm_explicit_provider_applies_to_all_candidates(monkeypatch) -> None:
    """显式指定 provider 时，清单上所有模型都交给这一家。

    用途：候选都想在同一个平台上试（如都在百炼，只是挑型号），
    不希望工具按模型名自动分流。
    """

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider({"deepseek-flash": _pass("deepseek-flash", "deepseek")}, calls),
    )

    result = invoke_llm(
        prompt="hi", provider="bailian", model_candidates=["qwen3.7-flash", "deepseek-flash"]
    )

    assert result["status"] == "PASS"
    assert calls == [("bailian", "qwen3.7-flash"), ("bailian", "deepseek-flash")]
    assert result["selected_provider"] == "bailian"


def test_invoke_llm_locked_model_overrides_candidates(monkeypatch) -> None:
    """锁定单模型的语义强于清单，同时给出时以 ``model`` 为准。"""

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider({"qwen3.8-max": _pass("qwen3.8-max")}, calls),
    )

    result = invoke_llm(
        prompt="hi",
        model="qwen3.8-max",
        model_candidates=["qwen3.7-flash", "deepseek-flash"],
    )

    assert result["status"] == "PASS"
    assert result["selected_model"] == "qwen3.8-max"
    # 走的不是候选路径，而是常规 provider 链；且未尝试任何候选。
    assert result["switching"]["mode"] == "provider-chain"
    assert ("bailian", "qwen3.7-flash") not in calls
    assert calls == [("deepseek", "qwen3.8-max")]


def test_invoke_llm_unknown_candidate_falls_back_to_chain_head(monkeypatch) -> None:
    """候选无法判定归属平台时，退回 auto 链首位尝试（而非直接报错）。"""

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider({"deepseek-flash": _pass("deepseek-flash", "deepseek")}, calls),
    )

    result = invoke_llm(
        prompt="hi", model_candidates=["totally-unknown-model", "deepseek-flash"]
    )

    assert result["status"] == "PASS"
    assert calls[0] == ("deepseek", "totally-unknown-model")


def test_invoke_llm_chain_mode_keeps_candidate_index_shape(monkeypatch) -> None:
    """两种模式的返回体形状必须一致：链模式的 ``candidate_index`` 为 -1。

    形状稳定才能让调用方免于 ``None`` 分支判断。
    """

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider(
            # 链模式不指定模型（空串），交 provider 自己挑默认。
            {"": _pass("deepseek-flash", "deepseek")},
            [],
        ),
    )

    result = invoke_llm(prompt="hi", provider="auto")

    assert result["status"] == "PASS"
    assert result["candidate_index"] == -1


def test_invoke_llm_rejects_unregistered_explicit_provider(monkeypatch) -> None:
    """显式 provider 未注册时应立即报错，而不是静默换一家。"""

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider({}, []),
    )

    with pytest.raises(KeyError):
        invoke_llm(prompt="hi", provider="not-a-provider", model_candidates=["deepseek-flash"])


# --------------------------------------------------------------------------
# 输出校验：API 成功 ≠ 输出可用
# --------------------------------------------------------------------------


def _pass_with_text(model: str, text: str, vendor: str = "alibaba") -> dict:
    """构造一条「API 成功但内容由测试指定」的结果。"""

    result = _pass(model, vendor)
    result["response"] = {"text": text}
    return result


def test_response_validator_accepts_good_output(monkeypatch) -> None:
    """校验通过时正常结束，不做多余尝试。"""

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider(
            {"qwen/qwen3.6-35b-a3b": _pass_with_text("qwen/qwen3.6-35b-a3b", '{"p": ["内容/x"]}')},
            calls,
        ),
    )

    result = invoke_llm(
        prompt="hi",
        model_candidates=["qwen/qwen3.6-35b-a3b", "qwen3.7-flash"],
        response_validator=lambda text: "" if "{" in text else "非法输出",
    )

    assert result["status"] == "PASS"
    assert result["candidate_index"] == 0
    assert calls == [("lmstudio", "qwen/qwen3.6-35b-a3b")]


def test_response_validator_rejection_advances_to_next_candidate(monkeypatch) -> None:
    """**核心行为**：API 成功但输出不可用时，必须继续尝试下一个候选。

    这是「换个模型再试」真正生效的前提。实测本地模型会间歇性产生不可用
    输出（把预算花在思考或解释上），只按 HTTP 状态判断会让候选链形同虚设。
    """

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider(
            {
                "qwen/qwen3.6-35b-a3b": _pass_with_text(
                    "qwen/qwen3.6-35b-a3b", "Thinking Process: 让我先分析一下……"
                ),
                "qwen3.7-flash": _pass_with_text("qwen3.7-flash", '{"p": ["内容/x"]}'),
            },
            calls,
        ),
    )

    result = invoke_llm(
        prompt="hi",
        model_candidates=["qwen/qwen3.6-35b-a3b", "qwen3.7-flash"],
        response_validator=lambda text: "" if text.strip().startswith("{") else "非法输出",
    )

    assert result["status"] == "PASS"
    assert result["candidate_index"] == 1
    assert result["selected_model"] == "qwen3.7-flash"
    assert calls == [
        ("lmstudio", "qwen/qwen3.6-35b-a3b"),
        ("bailian", "qwen3.7-flash"),
    ]
    # 被拒的候选要留下降级原因，便于事后判断“是不是模型不行”。
    rejected = result["attempts"][0]
    assert rejected["status"] == "FAIL"
    assert "校验未通过" in rejected["error"]


def test_response_validator_all_rejected_fails(monkeypatch) -> None:
    """所有候选都输出不可用时，整体判定为失败（而不是假装成功）。"""

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider(
            {
                "qwen3.7-flash": _pass_with_text("qwen3.7-flash", "不是 JSON"),
                "deepseek-flash": _pass_with_text("deepseek-flash", "也不是", "deepseek"),
            },
            [],
        ),
    )

    result = invoke_llm(
        prompt="hi",
        model_candidates=["qwen3.7-flash", "deepseek-flash"],
        response_validator=lambda text: "非法输出",
    )

    assert result["status"] == "FAIL"
    assert result["candidate_index"] == -1
    assert all(item["status"] == "FAIL" for item in result["attempts"])


def test_response_validator_exception_counts_as_failure(monkeypatch) -> None:
    """校验器自身抛异常时按校验失败处理，不得让整条链崩掉。"""

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider",
        _stub_within_provider(
            {
                "qwen3.7-flash": _pass_with_text("qwen3.7-flash", "x"),
                "deepseek-flash": _pass_with_text("deepseek-flash", "y", "deepseek"),
            },
            calls,
        ),
    )

    def _boom(text: str) -> str:
        raise ValueError("validator exploded")

    result = invoke_llm(
        prompt="hi",
        model_candidates=["qwen3.7-flash", "deepseek-flash"],
        response_validator=_boom,
    )

    assert len(calls) == 2, "校验器异常也要继续尝试下一个候选"
    assert result["status"] == "FAIL"
    assert "校验器异常" in result["attempts"][0]["error"]


def test_validator_only_affects_menu_mode(monkeypatch) -> None:
    """链模式不传校验器（其语义是「按 provider 优先级兜底」，不涉及内容判定）。"""

    seen = _capture_within_provider_args(monkeypatch)
    invoke_llm(prompt="hi", provider="bailian")
    # 链模式压根不会把 response_validator 传进 provider 内部。
    assert "response_validator" not in seen[0] or seen[0].get("response_validator") is None


def _capture_within_provider_args(monkeypatch) -> list[dict]:
    """记录传入 ``_invoke_within_provider`` 的关键字参数。"""

    seen: list[dict] = []

    def _fake(provider_name, **kwargs):
        seen.append(kwargs)
        return _pass("stub-model")

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider", _fake
    )
    return seen
