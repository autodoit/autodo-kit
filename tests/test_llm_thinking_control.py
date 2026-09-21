"""思考模式控制（``disable_thinking``）的行为测试。

**为什么需要一个专门的开关**：本工具链上大量任务是**分类 / 抽取**性质（问答对
打标、模型路由裁决前的信号提取等）。这类任务不需要长链推理，而一旦模型开启
「思考」，会产生三个真实后果：

1. **输出预算被思考吃光**——实测某批次把 ``max_tokens=2048`` 全用在思考上，
   JSON 根本没输出，导致整批解析失败（不是模型不行，是预算被挤掉）；
2. **成本上升**——思考 token 按输出计费，而输出单价通常是输入的 4～6 倍；
3. **延迟飙升**——实测百炼 qwen3.7-flash 23.4s → 1.1s（约 20 倍）。

**为什么参数名要从数据文件读**：各厂商关闭思考的参数名不同——
百炼 Qwen 系列用 ``enable_thinking=false``，DeepSeek 用
``thinking.type=disabled``。写死在代码里必然过时或写错厂商。

**本文件守护的核心回归**：``extra`` 必须包一层 ``extra_body``。
``AliyunLLMClient.generate_text(extra=...)`` 是直接 ``kwargs.update(extra)``
展开到 ``chat.completions.create()`` 的，所以传 ``{"enable_thinking": False}``
会被当成顶层关键字参数而报 ``unexpected keyword argument``。
该缺陷曾真实存在，且让 provider 的 ``extra_body`` 字段**从未生效过**。
"""

from __future__ import annotations

from autodokit.tools.atomic.llm import invoke_llm
from autodokit.tools.atomic.llm.llm_providers import (
    build_request_extra,
    get_provider,
)


# --------------------------------------------------------------------------
# build_request_extra：组装厂商私有请求字段
# --------------------------------------------------------------------------


def test_extra_must_be_wrapped_in_extra_body() -> None:
    """**核心回归**：返回值必须含 ``extra_body`` 这一层。

    缺了这一层就会被 OpenAI SDK 当成顶层参数，报 unexpected keyword argument。
    """

    extra = build_request_extra(get_provider("bailian"), disable_thinking=True)
    assert extra is not None
    assert set(extra) == {"extra_body"}, "必须包一层 extra_body，否则 SDK 展开后报错"
    assert extra["extra_body"] == {"enable_thinking": False}


def test_disable_thinking_uses_per_vendor_param_name() -> None:
    """关闭思考的参数名随厂商而异，必须来自数据文件而非硬编码。"""

    # 百炼 Qwen 系列：enable_thinking
    assert build_request_extra(get_provider("bailian"), disable_thinking=True) == {
        "extra_body": {"enable_thinking": False}
    }
    # DeepSeek 官方：thinking.type
    assert build_request_extra(get_provider("deepseek"), disable_thinking=True) == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }


def test_no_extra_when_nothing_to_send() -> None:
    """默认（不关思考）且 provider 无额外字段时返回 None，不空发请求体。"""

    assert build_request_extra(get_provider("bailian")) is None
    assert build_request_extra(get_provider("deepseek")) is None


def test_provider_without_support_returns_none() -> None:
    """provider 未提供关闭参数时返回 None（尽力而为，不报错）。

    本地 LM Studio 的关闭方式取决于所加载模型的 chat template，无法在
    provider 层统一表达。此时工具只能作罢——**代价是本地模型可能仍然思考**，
    所以选用本地模型前应实测（见 ``config/llm_preference.json`` 的说明）。
    """

    assert build_request_extra(get_provider("lmstudio"), disable_thinking=True) is None


# --------------------------------------------------------------------------
# 数据文件：no_thinking_body 字段
# --------------------------------------------------------------------------


def test_cloud_providers_declare_no_thinking_body() -> None:
    """两个云端 provider 都应声明关闭方式（否则 disable_thinking 形同虚设）。"""

    for name in ("deepseek", "bailian"):
        assert get_provider(name).no_thinking_body, f"{name} 缺少 no_thinking_body"


# --------------------------------------------------------------------------
# invoke_llm 透传与审计
# --------------------------------------------------------------------------


def _capture_within(monkeypatch) -> list[dict]:
    """把 ``_invoke_within_provider`` 换成记录参数的替身。"""

    seen: list[dict] = []

    def _fake(provider_name, **kwargs):
        seen.append({"provider": provider_name, **kwargs})
        return {
            "status": "PASS",
            "selected_model": kwargs.get("model") or "stub-model",
            "selected_vendor": "alibaba",
            "attempts": [],
            "switching": {},
            "response": {"text": "ok"},
            "error": "",
        }

    monkeypatch.setattr(
        "autodokit.tools.atomic.llm.llm_providers._invoke_within_provider", _fake
    )
    return seen


def test_invoke_llm_passes_disable_thinking_into_provider(monkeypatch) -> None:
    """``disable_thinking`` 必须一路传到 provider 内部，否则开关是摆设。"""

    seen = _capture_within(monkeypatch)
    invoke_llm(prompt="hi", provider="bailian", disable_thinking=True)
    assert seen[0]["disable_thinking"] is True


def test_disable_thinking_defaults_to_false(monkeypatch) -> None:
    """工具层默认不关思考——是否关思考取决于任务性质，由业务方声明。

    推理类任务（模型路由裁决、文献精读）需要思考，不能被工具擅自关掉。
    """

    seen = _capture_within(monkeypatch)
    invoke_llm(prompt="hi", provider="bailian")
    assert seen[0]["disable_thinking"] is False


def test_menu_mode_passes_and_records_disable_thinking(monkeypatch) -> None:
    """菜单模式同样透传，并在审计里留痕（排障时能判断思考是否已关）。"""

    seen = _capture_within(monkeypatch)
    result = invoke_llm(
        prompt="hi", model_candidates=["qwen3.7-flash"], disable_thinking=True
    )
    assert seen[0]["disable_thinking"] is True
    assert result["switching"]["disable_thinking"] is True
