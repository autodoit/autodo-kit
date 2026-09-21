"""多后端大模型调用抽象层（LLMProvider）。

本模块把「大模型调用」抽象为独立维度：``LLMProvider`` 是一级概念，
阿里百炼只是 provider 之一，DeepSeek 官方与 LM Studio 是另两个内置 provider。

设计目标：

- 复用 ``llm_clients.AliyunLLMClient``（客户端实现与 provider 解耦）。
- 提供 ``invoke_llm`` 统一调用入口，返回结构与 ``invoke_aliyun_llm`` 对齐。
- **两级容灾**：provider 级回退（抗平台故障）+ 模型级回退（抗单模型故障）。
- ``auto`` 路由按 ``_AUTO_PROVIDER_PRIORITY`` 顺序挑选可用 provider。
- 密钥统一走 ``secrets_manager``（``~/.config/autodo-suite/secrets/``），
  任何 provider 的密钥均不落代码、文档、日志。
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence

from autodokit.tools.atomic.llm.llm_clients import (
    AliyunLLMClient,
    AliyunLLMConfig,
    ModelRoutingIntent,
    _build_switching_report,
    _infer_model_vendor,
    _masked_text,
    invoke_aliyun_llm,
    load_aliyun_llm_config,
)
from autodokit.tools.atomic.llm.secrets_manager import mask_api_key, secret_path

SdkBackend = Literal["dashscope", "openai-compatible"]
ProviderName = Literal["deepseek", "bailian", "lmstudio"]

#: ``auto`` 路由的 provider 优先级环境变量（临时覆盖，无需改数据文件）。
_AUTO_PROVIDER_PRIORITY_ENV = "AUTODO_LLM_PROVIDER_PRIORITY"

#: 兜底优先级（数据文件不可用时使用）。
_FALLBACK_AUTO_PROVIDER_PRIORITY: tuple[str, ...] = ("deepseek", "bailian", "lmstudio")

#: ``vendor`` → 默认 ``provider`` 的兜底映射。
#:
#: 仅在目录未登记该模型、且未命中任何 provider 的默认/回退模型时使用。
#: 注意这里**只在厂商有专属 provider 时**映射：百炼是聚合平台（同一厂商的模型
#: 可能经百炼提供），因此不做反向映射，交由目录的 ``provider`` 字段决定。
_VENDOR_DEFAULT_PROVIDER: Dict[str, str] = {
    "deepseek": "deepseek",
}


def _get_providers() -> Dict[str, LLMProvider]:
    """取得 provider 注册表（**数据文件优先，内置兜底**）。

    Returns:
        provider 名 → 定义。
    """

    try:
        from autodokit.tools.atomic.llm.llm_catalog import try_load_catalog

        catalog, _ = try_load_catalog()
    except Exception:  # noqa: BLE001 - 目录不可用不应中断调用
        catalog = None

    if catalog is None or not catalog.providers:
        return dict(_FALLBACK_PROVIDERS)

    resolved: Dict[str, LLMProvider] = {}
    for item in catalog.providers.values():
        resolved[item.name] = LLMProvider(
            name=item.name,
            display_name=item.display_name or item.name,
            sdk_backend=item.sdk_backend,  # type: ignore[arg-type]
            default_base_url=item.base_url,
            default_model=item.default_model,
            secret_name=item.secret_name or item.name,
            env_api_key_name=item.env_api_key_name,
            is_local=item.is_local,
            placeholder_key_ok=False,
            fallback_models=tuple(item.fallback_models),
            extra_body=dict(item.extra_body),
            no_thinking_body=dict(item.no_thinking_body),
        )
    return resolved or dict(_FALLBACK_PROVIDERS)


def _parse_provider_order(raw: str) -> List[str]:
    """解析逗号分隔的 provider 顺序串。

    Args:
        raw: 形如 ``"lmstudio,bailian,deepseek"`` 的字符串。

    Returns:
        provider 名列表（保序、去重、小写化）。
    """

    result: List[str] = []
    for item in str(raw or "").split(","):
        name = item.strip().lower()
        if name and name not in result:
            result.append(name)
    return result


def parse_model_candidates(raw: Optional[Sequence[str] | str]) -> List[str]:
    """解析模型候选清单（支持序列或逗号分隔字符串）。

    与 :func:`_parse_provider_order` 的差别：**不做小写化**——模型 id 大小写敏感
    （如 ``MiniMax-M3``、``qwen/qwen3.5-9b``），统一小写会改变语义。

    Args:
        raw: 模型名序列，或形如 ``"deepseek-flash,qwen3.8-flash"`` 的字符串。

    Returns:
        模型名列表（保序、去重、去首尾空白）。

    Examples:
        >>> parse_model_candidates("deepseek-flash, qwen3.8-flash ,deepseek-flash")
        ['deepseek-flash', 'qwen3.8-flash']
        >>> parse_model_candidates(["MiniMax-M3", ""])[0]
        'MiniMax-M3'
        >>> parse_model_candidates(None)
        []
    """

    if raw is None:
        return []
    items = raw.split(",") if isinstance(raw, str) else [str(item) for item in raw]

    result: List[str] = []
    for item in items:
        name = str(item).strip()
        if name and name not in result:
            result.append(name)
    return result


def resolve_model_provider(model: str) -> str:
    """反查模型归属的 provider（**菜单模式下按菜品挑厨房**）。

    判定顺序（先精确后兜底）：

    1. 目录 ``llm_catalog.json`` 中该模型的 ``provider`` 字段；
    2. 已注册 provider 的 ``default_model`` / ``fallback_models`` 命中；
    3. vendor 兜底映射（见 ``_VENDOR_DEFAULT_PROVIDER``）。

    **为什么要用目录的 ``provider`` 而不是 ``vendor``**：两者不等价。
    例如 ``deepseek-v4.1-flash`` 的 vendor 是 ``deepseek``，但经百炼平台提供
    服务，其 ``provider`` 为 ``bailian``。若按 vendor 路由到 DeepSeek 官方
    端点，会得到 404（该账户无此模型）。

    Args:
        model: 模型名（大小写不敏感，按目录规则解析别名）。

    Returns:
        已注册的 provider 名；无法判定时返回空串（交调用方按 ``provider``
        实参或 auto 链决定）。

    Examples:
        >>> resolve_model_provider("deepseek-flash")
        'deepseek'
        >>> resolve_model_provider("deepseek-v4.1-flash")
        'bailian'
        >>> resolve_model_provider("")
        ''
    """

    name = str(model or "").strip()
    if not name:
        return ""

    registered = _get_providers()

    try:
        from autodokit.tools.atomic.llm.llm_catalog import try_load_catalog

        catalog, _ = try_load_catalog()
    except Exception:  # noqa: BLE001 - 目录不可用不应中断反查
        catalog = None

    if catalog is not None:
        try:
            resolved = catalog.resolve_model_id(name)
        except Exception:  # noqa: BLE001
            resolved = name
        for key in (resolved, name):
            if not key or not catalog.has_model(key):
                continue
            item = catalog.get_model(key)
            provider_name = str(item.provider or "").strip().lower()
            if provider_name and provider_name in registered:
                return provider_name

    for provider_name, provider_def in registered.items():
        if name in (provider_def.default_model, *provider_def.fallback_models):
            return provider_name

    fallback = _VENDOR_DEFAULT_PROVIDER.get(_infer_model_vendor(name), "")
    return fallback if fallback in registered else ""


def model_provider_map(models: Sequence[str]) -> List[Dict[str, str]]:
    """把候选模型清单解析成「模型 → provider」对照表（供调用前预检/展示）。

    Args:
        models: 模型候选清单。

    Returns:
        每项含 ``model`` / ``provider`` / ``registered``（provider 未注册时为
        ``"False"``，便于调用方在真正发起请求前发现配置笔误）。

    Examples:
        >>> model_provider_map(["deepseek-flash"])[0]["provider"]
        'deepseek'
        >>> model_provider_map(["no-such-model"])[0]["registered"]
        'False'
    """

    registered = set(_get_providers())
    resolved: List[Dict[str, str]] = []
    for item in parse_model_candidates(models):
        provider_name = resolve_model_provider(item)
        resolved.append(
            {
                "model": item,
                "provider": provider_name,
                "registered": str(bool(provider_name) and provider_name in registered),
            }
        )
    return resolved


def _auto_provider_priority(order: Optional[Sequence[str]] = None) -> tuple[str, ...]:
    """返回 ``auto`` 路由的 provider 优先级序列。

    优先级来源（从高到低）：

    1. 调用方显式传入的 ``order``（如 CLI 的 ``--provider-order``）；
    2. 环境变量 ``AUTODO_LLM_PROVIDER_PRIORITY``；
    3. 数据文件 ``llm_catalog.json`` 中 provider 的 ``priority`` 字段；
    4. 内置兜底顺序。

    Args:
        order: 显式指定的顺序（可为 provider 名序列或逗号分隔字符串）。

    Returns:
        provider 名称元组（仅保留已注册者；全部无效时回退内置顺序）。

    Examples:
        >>> _auto_provider_priority("bailian,deepseek")[0]
        'bailian'
    """

    registered = _get_providers()

    if isinstance(order, str):
        candidates: List[str] = _parse_provider_order(order)
    elif order is None:
        raw = os.environ.get(_AUTO_PROVIDER_PRIORITY_ENV, "").strip()
        candidates = _parse_provider_order(raw) if raw else []
    else:
        candidates = [str(item).strip().lower() for item in order if str(item).strip()]

    if not candidates:
        candidates = _catalog_provider_order(registered) or list(
            _FALLBACK_AUTO_PROVIDER_PRIORITY
        )

    result: List[str] = []
    for name in candidates:
        if name in registered and name not in result:
            result.append(name)
    # 未在顺序中出现的 provider 追加在后，保证不会因漏写而彻底不可达。
    for name in registered:
        if name not in result:
            result.append(name)
    return tuple(result) or _FALLBACK_AUTO_PROVIDER_PRIORITY


def _catalog_provider_order(registered: Dict[str, LLMProvider]) -> List[str]:
    """按数据文件的 ``priority`` 得到 provider 顺序。

    Args:
        registered: 已注册 provider 映射。

    Returns:
        provider 名列表（按 priority 升序）；取值失败时为空列表。
    """

    try:
        from autodokit.tools.atomic.llm.llm_catalog import try_load_catalog

        catalog, _ = try_load_catalog()
        if catalog is None or not catalog.providers:
            return []
        ordered = catalog.provider_priority()
        return [name for name in ordered if name in registered]
    except Exception:  # noqa: BLE001
        return []


@dataclass(frozen=True)
class LLMProvider:
    """大模型提供方定义。

    Args:
        name: 提供方唯一名（bailian/lmstudio/...）。
        display_name: 展示名。
        sdk_backend: 调用后端（dashscope/openai-compatible）。
        default_base_url: 默认 OpenAI 兼容 base_url（本地服务或地域端点）。
        default_model: 默认模型名。
        secret_name: 统一密钥仓库中的逻辑密钥名。
        env_api_key_name: 环境变量名（云端 provider 优先）。
        is_local: 是否为本地服务（无外网依赖）。
        placeholder_key_ok: 是否允许占位密钥（LM Studio 旧版不校验；新版需真实 token）。
        fallback_models: 本 provider 内的模型回退链（provider 层不代管模型级路由时使用）。
        extra_body: 厂商私有请求字段（**始终随请求发送**）。
        no_thinking_body: 关闭思考模式时追加的请求字段。不同厂商参数名不同——
            百炼 Qwen 系列用 ``enable_thinking=false``，DeepSeek 用
            ``thinking.type=disabled``，故由数据文件提供而非硬编码。
    """

    name: str
    display_name: str
    sdk_backend: SdkBackend
    default_base_url: str
    default_model: str
    secret_name: str
    env_api_key_name: str = ""
    is_local: bool = False
    placeholder_key_ok: bool = False
    fallback_models: tuple[str, ...] = ()
    extra_body: Dict[str, Any] = field(default_factory=dict)
    no_thinking_body: Dict[str, Any] = field(default_factory=dict)


#: 内置 provider 注册表**兜底快照**（数据文件不可用时使用）。
#: 主数据在 ``catalog/llm_catalog.json``；调整 provider 请改 JSON。
_FALLBACK_PROVIDERS: Dict[str, LLMProvider] = {
    # DeepSeek 官方：独立账户，与百炼互为平台级容灾。
    "deepseek": LLMProvider(
        name="deepseek",
        display_name="DeepSeek 官方",
        sdk_backend="openai-compatible",
        default_base_url="https://api.deepseek.com/v1",
        default_model="deepseek-flash",
        fallback_models=("deepseek-v4-pro",),
        secret_name="deepseek",
        env_api_key_name="DEEPSEEK_API_KEY",
        is_local=False,
        placeholder_key_ok=False,
    ),
    "bailian": LLMProvider(
        name="bailian",
        display_name="阿里百炼",
        sdk_backend="openai-compatible",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.7-plus",
        secret_name="bailian",
        env_api_key_name="DASHSCOPE_API_KEY",
        is_local=False,
        placeholder_key_ok=False,
    ),
    "lmstudio": LLMProvider(
        name="lmstudio",
        display_name="LM Studio 本地",
        sdk_backend="openai-compatible",
        default_base_url="http://127.0.0.1:1234/v1",
        default_model="qwen/qwen3.5-9b",
        secret_name="lmstudio",
        env_api_key_name="",
        is_local=True,
        placeholder_key_ok=False,
    ),
}


def list_providers() -> List[str]:
    """返回已注册的 provider 名称列表。

    Returns:
        provider 名称列表。

    Examples:
        >>> "bailian" in list_providers()
        True
        >>> "lmstudio" in list_providers()
        True
    """

    return list(_get_providers().keys())


def get_provider(name: str) -> LLMProvider:
    """按名称获取 provider 定义。

    Args:
        name: provider 名称（不区分大小写）。

    Returns:
        provider 定义。

    Raises:
        KeyError: provider 不存在。
    """

    key = str(name or "").strip().lower()
    provider = _get_providers().get(key)
    if provider is None:
        raise KeyError(f"未注册的 LLMProvider: {name!r}；可用: {list_providers()}")
    return provider


def is_local_online(provider: LLMProvider, *, timeout: float = 1.5) -> bool:
    """探测本地 provider 是否在线（GET /v1/models）。

    Args:
        provider: 本地 provider 定义。
        timeout: 超时秒数。

    Returns:
        True 表示服务在线。
    """

    if not provider.is_local:
        return False
    try:
        key = _load_secret(provider)
        req = urllib.request.Request(
            f"{provider.default_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {key}"} if key else {},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return isinstance(payload, dict) and "data" in payload
    except Exception:
        return False


def resolve_provider(name: str = "auto", *, order: Optional[Sequence[str] | str] = None) -> str:
    """解析 provider 选择（支持 auto）——返回**首个可用**的 provider。

    规则：

    - 显式名称：直接返回（未注册则抛 KeyError）。
    - ``auto``：按优先级（默认 DeepSeek → 百炼 → 本地，可经 ``order`` 覆盖）
      返回首个可用者；均不可用时返回首位，使报错指向最高优先级 provider。

    可用性判定：本地 provider 探活（``/v1/models``）；云端 provider 看密钥是否存在。

    Args:
        name: provider 名或 ``auto``。
        order: 本次调用的顺序覆盖（仅 ``auto`` 时生效）。

    Returns:
        解析后的 provider 名称。
    """

    value = str(name or "auto").strip().lower()
    if value != "auto":
        return get_provider(value).name
    priority = _auto_provider_priority(order)
    for candidate in priority:
        try:
            if _provider_available(get_provider(candidate)):
                return candidate
        except Exception:  # noqa: BLE001 - 单个 provider 探测失败不应中断挑选
            continue
    return priority[0] if priority else "bailian"


def _provider_available(provider: LLMProvider) -> bool:
    """判断 provider 当前是否可用。

    Args:
        provider: provider 定义。

    Returns:
        本地 provider 返回探活结果；云端 provider 返回密钥是否就绪。
    """

    if provider.is_local:
        return is_local_online(provider)
    try:
        _load_secret(provider)
        return True
    except Exception:  # noqa: BLE001 - 缺密钥即视为不可用，不抛异常
        return False


def iter_provider_chain(
    name: str = "auto", *, order: Optional[Sequence[str] | str] = None
) -> tuple[str, ...]:
    """返回**依次尝试**的 provider 序列（provider 级容灾）。

    - 显式名称：只返回该 provider（尊重显式选择，不静默换厂）。
    - ``auto``：按优先级返回**全部**候选，由调用方逐个尝试。

    优先级可通过 ``order`` 按次覆盖，用于“临时换一下顺序”而不用改数据文件或
    环境变量，例如本地优先：``order="lmstudio,bailian,deepseek"``。

    Args:
        name: provider 名或 ``auto``。
        order: 本次调用的 provider 顺序（序列或逗号分隔字符串）；仅当
            ``name="auto"`` 时生效。

    Returns:
        provider 名称元组（尝试顺序）。

    Examples:
        >>> iter_provider_chain("bailian")
        ('bailian',)
        >>> iter_provider_chain("auto")[0]
        'deepseek'
        >>> iter_provider_chain("auto", order="lmstudio,bailian,deepseek")[0]
        'lmstudio'
    """

    value = str(name or "auto").strip().lower()
    if value != "auto":
        return (get_provider(value).name,)
    return _auto_provider_priority(order)


def _load_secret(provider: LLMProvider) -> str:
    """读取 provider 密钥（统一走 secrets 仓库）。

    Args:
        provider: provider 定义。

    Returns:
        密钥字符串（可能为空）。

    Raises:
        RuntimeError: 密钥文件缺失且不允许占位。
    """

    path = secret_path(provider.secret_name)
    if path.exists() and path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    if provider.placeholder_key_ok:
        return "lm-studio-placeholder"
    raise RuntimeError(
        f"未找到 provider {provider.name!r} 的密钥文件：{path}；"
        f"请通过统一密钥仓库 {mask_api_key('') or '~/.config/autodo-suite/secrets/'} 初始化。"
    )


def build_llm_client(
    provider: str = "auto",
    *,
    model: str = "",
    base_url: str = "",
    config_path: str | Path | None = None,
    route_hints: Optional[Dict[str, Any]] = None,
) -> tuple[AliyunLLMClient, str]:
    """按 provider 构造 LLM 客户端。

    Args:
        provider: provider 名或 auto。
        model: 显式模型名；为空用 provider 默认。
        base_url: 显式 base_url；为空用 provider 默认。
        config_path: 全局调度配置路径。
        route_hints: 路由提示（透传给 load_aliyun_llm_config）。

    Returns:
        二元组：客户端、解析后的 provider 名称。
    """

    resolved = resolve_provider(provider)
    provider_def = get_provider(resolved)

    effective_model = (model or "").strip() or provider_def.default_model
    effective_base_url = (base_url or "").strip() or provider_def.default_base_url
    effective_backend = provider_def.sdk_backend
    env_api_key_name = provider_def.env_api_key_name or "DASHSCOPE_API_KEY"

    # 密钥解析：**必须**优先使用本 provider 自己的密钥文件，并传入 secret_name。
    #
    # 若只传 env_api_key_name，``load_aliyun_llm_config`` 会落到默认候选，
    # 而默认候选的厂商范围由 secret_name 决定（历史实现硬编码为
    # bailian/dashscope）——结果是“把百炼凭据发给别的厂商”。
    # 该缺陷曾真实发生：DeepSeek 收到百炼 key，服务端返回 401。
    # 安全含义：跨厂商误送凭据属凭据泄露风险，因此不做“跨厂商兼容”。
    secret_file = secret_path(provider_def.secret_name)
    api_key_file = str(secret_file) if secret_file.is_file() else ""

    cfg = load_aliyun_llm_config(
        model=effective_model,
        env_api_key_name=env_api_key_name,
        api_key_file=api_key_file or None,
        base_url=effective_base_url,
        sdk_backend=effective_backend,
        config_path=config_path,
        affair_name="llm-provider",
        route_hints=route_hints,
        secret_name=provider_def.secret_name,
    )
    return AliyunLLMClient(cfg), resolved


def build_request_extra(
    provider: LLMProvider,
    *,
    disable_thinking: bool = False,
) -> Optional[Dict[str, Any]]:
    """组装 OpenAI SDK 的 ``extra`` 参数（厂商私有请求字段）。

    **返回值必须包一层 ``extra_body``**：``AliyunLLMClient.generate_text`` 的
    ``extra`` 是直接 ``kwargs.update(extra)`` 展开到 ``chat.completions.create()``
    的，所以想让请求体里出现 ``enable_thinking``，就必须传
    ``{"extra_body": {"enable_thinking": False}}``。

    > 历史缺陷：早期实现直接传 ``{"enable_thinking": False}``，被展开成顶层
    > 关键字参数，导致 SDK 报 ``unexpected keyword argument``；provider 的
    > ``extra_body`` 字段因此**从未真正生效过**。

    为何要关思考：打标这类**分类 / 抽取**任务不需要长链推理，而思考输出会
    ① 挤占 ``max_tokens`` 预算（实测会把 JSON 截断导致整批解析失败）、
    ② 推高输出 token 成本、③ 显著拉长延迟（实测百炼 3.0s → 0.6s）。

    Args:
        provider: provider 定义。
        disable_thinking: 是否追加该 provider 的「关闭思考」请求字段。

    Returns:
        传给 ``generate_text(extra=...)`` 的字典；无字段可传时返回 None。

    Examples:
        >>> from autodokit.tools.atomic.llm.llm_providers import get_provider
        >>> build_request_extra(get_provider("deepseek"), disable_thinking=True)
        {'extra_body': {'thinking': {'type': 'disabled'}}}
        >>> build_request_extra(get_provider("lmstudio"), disable_thinking=True)
    """

    body: Dict[str, Any] = dict(provider.extra_body)
    if disable_thinking:
        body.update(provider.no_thinking_body)
    return {"extra_body": body} if body else None


def _invoke_within_provider(
    provider_name: str,
    *,
    prompt: str,
    system: str | None,
    model: str,
    models: Optional[Sequence[str]] = None,
    base_url: str,
    max_tokens: int,
    temperature: float,
    config_path: str | Path | None,
    route_hints: Optional[Dict[str, Any]],
    disable_thinking: bool = False,
) -> Dict[str, Any]:
    """在**单个 provider 内**完成一次调用（含该 provider 的模型级回退）。

    provider 分工：

    - ``bailian``：委托 ``invoke_aliyun_llm``，享受地域/档位感知的模型路由与
      「同系列 → 跨厂商」回退链；
    - 其余 provider（DeepSeek / LM Studio）：按 ``default_model`` →
      ``fallback_models`` 顺序尝试，实现 provider 内的模型级容灾。

    模型候选的三个来源（优先级从高到低）：

    1. ``model``：锁定单模型（语义为「只能用这个」）；
    2. ``models``：显式候选链（语义为「按这个顺序试」）；
    3. 都不传：provider 自带的 ``default_model`` → ``fallback_models``。

    当传入 ``models`` 时**不再委托** ``invoke_aliyun_llm``：该函数内部自带
    一套模型路由，会覆盖调用方给的显式顺序。此时改为逐个模型直连百炼的
    OpenAI 兼容端点，使调用方顺序受到完全尊重。

    Args:
        provider_name: 已注册的 provider 名。
        prompt: 用户提示词。
        system: 系统提示词。
        model: 显式模型名（最高优先级，锁定语义）。
        models: 显式模型候选链（按序尝试）。
        base_url: 显式端点（覆盖 provider 默认）。
        max_tokens: 最大输出 token。
        temperature: 采样温度。
        config_path: 全局调度配置路径。
        route_hints: 路由提示。
        disable_thinking: 是否关闭思考模式（分类/抽取类任务建议开）。

    Returns:
        归一化结果：``status`` / ``selected_model`` / ``selected_vendor`` /
        ``attempts`` / ``switching`` / ``response`` / ``error``。
    """

    provider_def = get_provider(provider_name)
    explicit_model = (model or "").strip()
    chain_override = parse_model_candidates(models)
    extra = build_request_extra(provider_def, disable_thinking=disable_thinking)

    if provider_name == "bailian" and not base_url and not chain_override:
        result = invoke_aliyun_llm(
            prompt=prompt,
            system=system,
            intent=ModelRoutingIntent(
                model=(model or "auto"),
                affair_name="llm-provider",
                # 百炼必须走 OpenAI 兼容端点；dashscope 原生 SDK 会报 url error。
                prefer_backend=provider_def.sdk_backend,
            ),
            max_tokens=max_tokens,
            temperature=temperature,
            extra=extra,
            config_path=config_path,
            route_hints=route_hints,
        )
        switching = dict(result.get("switching") or {})
        switching.setdefault("mode", "routed")
        return {
            "status": result.get("status", "FAIL"),
            "selected_model": result.get("selected_model", ""),
            "selected_vendor": result.get("selected_vendor", ""),
            "attempts": result.get("attempts", []),
            "switching": switching,
            "response": result.get("response", {}),
            "error": result.get("error", ""),
        }

    if explicit_model:
        model_candidates: List[str] = [explicit_model]
    elif chain_override:
        model_candidates = chain_override
    else:
        model_candidates = [provider_def.default_model, *provider_def.fallback_models]
    primary_model = model_candidates[0] if model_candidates else ""

    attempts: List[Dict[str, Any]] = []
    last_error = ""
    for candidate_model in model_candidates:
        if not candidate_model:
            continue
        client: Any = None
        try:
            client, _ = build_llm_client(
                provider_name,
                model=candidate_model,
                base_url=base_url,
                config_path=config_path,
                route_hints=route_hints,
            )
            text = client.generate_text(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                extra=extra,
            )
            # 以**实际配置生效**的模型名为准：请求名可能被规范化
            # （如 ``_normalize_model_name`` 把下线型号映射到替代型号）。
            effective_model = str(getattr(client, "model", "") or candidate_model)
            attempts.append(
                {
                    "model": effective_model,
                    "vendor": _infer_model_vendor(effective_model),
                    "status": "PASS",
                    "error": "",
                }
            )
            switching = _build_switching_report(
                attempts,
                primary_model=primary_model,
                selected_model=effective_model,
            )
            switching["mode"] = "provider-internal"
            return {
                "status": "PASS",
                "selected_model": effective_model,
                "selected_vendor": _infer_model_vendor(effective_model),
                "attempts": attempts,
                "switching": switching,
                "response": {"text": text},
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001 - 单模型失败应继续回退下一模型
            message = str(exc)
            if client is not None:
                message = _masked_text(message, getattr(client, "api_key", "") or "")
            last_error = message
            attempts.append(
                {
                    "model": candidate_model,
                    "vendor": _infer_model_vendor(candidate_model),
                    "status": "FAIL",
                    "error": message,
                }
            )

    switching = _build_switching_report(
        attempts,
        primary_model=primary_model,
        selected_model="",
    )
    switching["mode"] = "provider-internal"
    return {
        "status": "FAIL",
        "selected_model": "",
        "selected_vendor": "",
        "attempts": attempts,
        "switching": switching,
        "response": {},
        "error": last_error or "provider_all_models_failed",
    }


def _build_provider_switching_report(
    provider_attempts: List[Dict[str, Any]],
    *,
    primary_provider: str,
    selected_provider: str,
) -> Dict[str, Any]:
    """构造 **provider 级**切换审计（与模型级审计互补）。

    Args:
        provider_attempts: 逐 provider 尝试记录（``provider`` / ``status`` / ``error``）。
        primary_provider: 链首 provider（首选）。
        selected_provider: 最终成功产出内容的 provider（全失败时为空串）。

    Returns:
        含 ``switched`` / ``primary_provider`` / ``selected_provider`` /
        ``failed_providers`` / ``summary`` 的审计字典。

    Examples:
        >>> _build_provider_switching_report(
        ...     [{"provider": "deepseek", "status": "FAIL", "error": "401"},
        ...      {"provider": "bailian", "status": "PASS", "error": ""}],
        ...     primary_provider="deepseek", selected_provider="bailian",
        ... )["switched"]
        True
    """

    failed = [item for item in provider_attempts if item.get("status") == "FAIL"]
    attempted = [str(item.get("provider") or "") for item in provider_attempts if item.get("provider")]
    switched = bool(selected_provider) and selected_provider != primary_provider
    tried_text = "、".join(attempted)

    if not selected_provider:
        summary = (
            f"全部 provider 失败（首选 {primary_provider}）；"
            f"依次尝试并失败：{tried_text or '无'}"
        )
    elif not switched:
        summary = f"使用 provider {selected_provider}，无 provider 级切换"
    else:
        summary = f"provider {primary_provider} 失败 → 已切换至 {selected_provider}"

    if switched and failed:
        summary = f"{summary}；前序失败原因：{str(failed[0].get('error') or '')[:200]}"

    return {
        "switched": switched,
        "primary_provider": primary_provider,
        "selected_provider": selected_provider,
        "attempted_providers": attempted,
        "failed_providers": [
            {"provider": item.get("provider"), "error": item.get("error", "")} for item in failed
        ],
        "summary": summary,
    }


def _invoke_candidate_models(
    candidates: Sequence[str],
    *,
    provider: str,
    prompt: str,
    system: str | None,
    base_url: str,
    max_tokens: int,
    temperature: float,
    config_path: str | Path | None,
    route_hints: Optional[Dict[str, Any]],
    disable_thinking: bool = False,
    response_validator: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """按**调用方给定的模型顺序**逐个尝试（菜单模式「按序上菜」）。

    与常规 provider 链的差别：provider 链是「一层厂商、一层模型」的两级回退，
    而这里是**一维的显式清单**——调用方说先上哪道菜就先上哪道。

    路由规则：

    - ``provider`` 为显式名（如 ``"bailian"``）：该清单上的**所有**模型都交给
      这一家（适用于「都在百炼上，我只要挑型号」）；
    - ``provider="auto"``：逐个模型反查其归属 provider（见
      :func:`resolve_model_provider`），无法判定时交 auto 链首位。

    某个模型失败后**继续下一个**；全部失败时返回 FAIL，由调用方决定是否回落
    常规链。

    **“失败”包含内容不可用**：若调用方提供了 ``response_validator``，
    API 返回 200 但内容未通过校验也会被计为失败并继续下一个候选。
    这是必要的——LLM 调用成功不等于输出可用（格式错、被截断、答非所问都是
    常态），只按 HTTP 状态判断会让“换个模型再试”的能力形同虚设。

    Args:
        candidates: 模型候选清单（保序）。
        provider: provider 名或 ``auto``。
        prompt: 用户提示词。
        system: 系统提示词。
        base_url: 显式端点（覆盖 provider 默认）。
        max_tokens: 最大输出 token。
        temperature: 采样温度。
        config_path: 全局调度配置路径。
        route_hints: 路由提示。
        disable_thinking: 是否关闭思考模式。
        response_validator: 可选的输出校验函数，接收模型输出的文本，
            **返回空串表示通过**，返回非空字符串则为失败原因。

    Returns:
        归一化结果，额外含 ``provider``、``candidate_index`` 与两层审计。
    """

    explicit_provider = str(provider or "auto").strip().lower()
    auto_chain = iter_provider_chain("auto")
    registered = _get_providers()

    attempts: List[Dict[str, Any]] = []
    provider_attempts: List[Dict[str, Any]] = []
    seen_provider: Dict[str, Dict[str, Any]] = {}
    primary_provider = ""

    def _remember_provider(name: str, ok: bool, error: str) -> None:
        """按首次出现顺序记录 provider 级结果（同一 provider 只留一条）。"""

        if not name:
            return
        if name not in seen_provider:
            entry = {"provider": name, "status": "PASS" if ok else "FAIL", "error": "" if ok else error}
            seen_provider[name] = entry
            provider_attempts.append(entry)
        elif ok:
            seen_provider[name]["status"] = "PASS"
            seen_provider[name]["error"] = ""

    for candidate in candidates:
        if explicit_provider != "auto":
            target_provider = explicit_provider
            if target_provider not in registered:
                raise KeyError(
                    f"未注册的 LLMProvider: {provider!r}；可用: {list(registered)}"
                )
        else:
            target_provider = resolve_model_provider(candidate)
            if target_provider not in registered:
                target_provider = auto_chain[0] if auto_chain else "bailian"

        if not primary_provider:
            primary_provider = target_provider

        try:
            result = _invoke_within_provider(
                target_provider,
                prompt=prompt,
                system=system,
                model=candidate,
                base_url=base_url,
                max_tokens=max_tokens,
                temperature=temperature,
                config_path=config_path,
                route_hints=route_hints,
                disable_thinking=disable_thinking,
            )
        except Exception as exc:  # noqa: BLE001 - 单条候选失败应继续下一条
            result = {
                "status": "FAIL",
                "selected_model": "",
                "selected_vendor": "",
                "attempts": [],
                "switching": {},
                "response": {},
                "error": str(exc),
            }

        ok = result.get("status") == "PASS"
        error = "" if ok else str(result.get("error") or "")

        # API 成功 ≠ 输出可用：交给调用方的校验函数判定。
        if ok and response_validator is not None:
            text = str((result.get("response") or {}).get("text") or "")
            try:
                reason = str(response_validator(text) or "")
            except Exception as exc:  # noqa: BLE001 - 校验器异常视为校验失败
                reason = f"校验器异常: {type(exc).__name__}: {exc}"
            if reason:
                ok = False
                error = f"输出校验未通过：{reason}"

        _remember_provider(target_provider, ok, error)

        # 以**实际生效**的模型名为准（请求名可能被规范化）。
        effective_model = str(result.get("selected_model") or candidate)
        attempts.append(
            {
                "model": effective_model,
                "requested_model": candidate,
                "provider": target_provider,
                "vendor": str(result.get("selected_vendor") or _infer_model_vendor(effective_model)),
                "status": "PASS" if ok else "FAIL",
                "error": error,
            }
        )

        if not ok:
            continue

        switching = _build_switching_report(
            attempts, primary_model=candidates[0], selected_model=effective_model
        )
        switching["mode"] = "model-candidates"
        switching["candidate_index"] = len(attempts) - 1
        switching["candidates"] = list(candidates)
        switching["disable_thinking"] = bool(disable_thinking)
        provider_switching = _build_provider_switching_report(
            provider_attempts,
            primary_provider=primary_provider,
            selected_provider=target_provider,
        )
        switching["provider"] = provider_switching
        switching["selected_provider"] = target_provider
        if provider_switching["switched"]:
            switching["summary"] = f"{provider_switching['summary']}；{switching['summary']}"

        return {
            "status": "PASS",
            "provider": target_provider,
            "selected_provider": target_provider,
            "selected_model": effective_model,
            "selected_vendor": attempts[-1]["vendor"],
            "candidate_index": len(attempts) - 1,
            "attempts": attempts,
            "provider_attempts": provider_attempts,
            "switching": switching,
            "provider_switching": provider_switching,
            "response": result.get("response", {}),
            "error": "",
        }

    switching = _build_switching_report(
        attempts, primary_model=candidates[0], selected_model=""
    )
    switching["mode"] = "model-candidates"
    switching["candidate_index"] = -1
    switching["candidates"] = list(candidates)
    switching["disable_thinking"] = bool(disable_thinking)
    provider_switching = _build_provider_switching_report(
        provider_attempts,
        primary_provider=primary_provider or (auto_chain[0] if auto_chain else "bailian"),
        selected_provider="",
    )
    switching["provider"] = provider_switching
    switching["selected_provider"] = ""

    return {
        "status": "FAIL",
        "provider": explicit_provider if explicit_provider != "auto" else "auto",
        "selected_provider": "",
        "selected_model": "",
        "selected_vendor": "",
        "candidate_index": -1,
        "attempts": attempts,
        "provider_attempts": provider_attempts,
        "switching": switching,
        "provider_switching": provider_switching,
        "response": {},
        "error": f"all_candidate_models_failed: {'、'.join(candidates)}",
    }


def invoke_llm(
    *,
    prompt: str,
    system: str | None = None,
    provider: str = "auto",
    model: str = "",
    model_candidates: Optional[Sequence[str] | str] = None,
    base_url: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.2,
    config_path: str | Path | None = None,
    route_hints: Optional[Dict[str, Any]] = None,
    provider_order: Optional[Sequence[str] | str] = None,
    fallback_to_chain: bool = False,
    disable_thinking: bool = False,
    response_validator: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """统一调用入口（支持任意 provider，含 provider 级回退）。

    **两级容灾**（互相补充，不可替代）：

    ============== ============================================ ==========================
    层级           抵抗的故障                                    实现
    ============== ============================================ ==========================
    provider 层    平台级：某厂商账户欠费 / 服务不可用            ``iter_provider_chain``
    模型层         模型级：单模型限流 / 下线 / 临时不可用         各 provider 内部回退链
    ============== ============================================ ==========================

    行为：

    - ``provider="auto"``：按 ``_AUTO_PROVIDER_PRIORITY``（默认
      **DeepSeek → 百炼 → LM Studio**）逐个尝试，**上一家失败自动换下一家**；
    - ``provider="<名>"``：只试该家（尊重显式选择，不静默换厂）。

    **三种选模型方式**（对应「餐厅点菜」的三个层次）：

    ==================== ================================ ==========================
    方式                 含义                             适用
    ==================== ================================ ==========================
    （都不传）           由 provider 决定默认 → 回退链     没主意，交给工具决定
    ``model="x"``        **锁定**单个模型，失败即失败      调试、复现、强制某一型号
    ``model_candidates`` **按序尝试**清单，前面的优先    业务方有自己的点菜顺序
    ==================== ================================ ==========================

    ``model_candidates`` 与 ``provider_order`` 是**两个正交维度**：前者排模型
    （细），后者排厂商（粗）。同时给出时，``model_candidates`` 优先——因为它是
    更精确的表达（每个模型自带归属 provider，见 :func:`resolve_model_provider`）。

    返回体包含 **两层审计**：

    - ``switching``：模型级切换（``switched`` / ``cross_vendor`` / ``summary``），
      并内嵌 ``provider`` 子块给出 provider 级切换情况；
    - ``provider_switching``：provider 级切换（``switched`` / ``failed_providers`` / ``summary``）。

    **调用方必须把 ``switching["summary"]`` 向上汇报**——回退一旦生效，
    产出内容可能已非首选厂商/模型，不汇报则无从判断质量来源。

    Args:
        prompt: 用户提示词。
        system: 系统提示词。
        provider: provider 名或 auto。
        model: 显式模型名（一旦指定，provider 内不再回退）。与
            ``model_candidates`` 互斥，同时给出时以本参数为准（锁定语义更强）。
        model_candidates: **模型候选清单**（序列或逗号分隔字符串），按序尝试，
            最靠前的优先。清单耗尽即失败——**不会**擅自扩大到清单之外的模型，
            除非显式传 ``fallback_to_chain=True``。
        base_url: 显式 base_url（覆盖 provider 默认端点）。
        max_tokens: 最大输出 token。
        temperature: 采样温度。
        config_path: 全局调度配置路径。
        route_hints: 路由提示。
        provider_order: provider 尝试顺序覆盖（仅 ``provider="auto"`` 且
            **未传** ``model_candidates`` 时生效）；如
            ``"lmstudio,bailian,deepseek"`` 表示本地优先。
        fallback_to_chain: 菜单模式专用开关。``False``（默认）表示「清单就是
            意图」——清单内的模型全部失败即报错；``True`` 表示清单耗尽后继续
            回落到常规 provider 链兜底。
        disable_thinking: 是否关闭模型的思考模式。

            - ``False``（默认）：保留模型自身默认行为，适用于**推理类**任务
              （模型路由裁决、文献精读等）；
            - ``True``：适用于**分类 / 抽取 / 标注类**任务。思考输出会挤占
              ``max_tokens`` 预算（实测会把 JSON 截断导致整批失败）、推高
              输出成本、并显著拉长延迟。

            实际参数由数据文件 ``no_thinking_body`` 提供——百炼与 DeepSeek
            的参数名不同，不能写死。
        response_validator: 可选的**输出校验函数**，仅作用于菜单模式。接收模型
            输出的文本，**返回空串表示通过**，返回非空字符串则为失败原因。

            用途：LLM 调用成功不等于输出可用。当调用方对输出有硬性要求
            （如“必须是可解析的 JSON”）时，应用本函数把关，让不合格的候选
            被计为失败并自动尝试下一个。

    Returns:
        统一返回结构：``status``、``provider``、``selected_provider``、
        ``selected_model``、``selected_vendor``、``attempts``、
        ``provider_attempts``、``switching``、``provider_switching``、
        ``response``、``error``；菜单模式下另含 ``candidate_index``（命中第几个）。

    Examples:
        >>> import autodokit.tools.atomic.llm.llm_providers as p
        >>> p.parse_model_candidates("deepseek-flash,qwen3.8-flash")[0]
        'deepseek-flash'
    """

    candidates = parse_model_candidates(model_candidates)
    # 锁定语义强于清单语义：同时给出时以 ``model`` 为准，避免「点了菜又锁了一道」歧义。
    if (model or "").strip():
        candidates = []

    if candidates:
        menu_result = _invoke_candidate_models(
            candidates,
            provider=provider,
            prompt=prompt,
            system=system,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=temperature,
            config_path=config_path,
            route_hints=route_hints,
            disable_thinking=disable_thinking,
            response_validator=response_validator,
        )
        if menu_result.get("status") == "PASS" or not fallback_to_chain:
            menu_result["switching"]["fallback_to_chain"] = bool(fallback_to_chain)
            return menu_result

        # 清单耗尽 + 显式要求兜底：继续走常规 provider 链，
        # 并把菜单模式的失败记录并入最终审计，避免丢失排查线索。
        chain_result = invoke_llm(
            prompt=prompt,
            system=system,
            provider=provider,
            model=model,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=temperature,
            config_path=config_path,
            route_hints=route_hints,
            provider_order=provider_order,
            disable_thinking=disable_thinking,
            response_validator=response_validator,
        )
        switching = dict(chain_result.get("switching") or {})
        switching["candidates"] = list(candidates)
        switching["candidate_failures"] = [
            {"model": item["model"], "provider": item["provider"], "error": item["error"]}
            for item in menu_result.get("attempts", [])
            if item.get("status") == "FAIL"
        ]
        switching["fallback_to_chain"] = True
        switching["mode"] = f"{switching.get('mode', 'provider-chain')}+candidates-exhausted"
        switching["summary"] = (
            f"点菜单候选全部失败（{'、'.join(candidates)}）→ 已回落常规链："
            f"{switching.get('summary', '')}"
        )
        chain_result["switching"] = switching
        if chain_result.get("status") != "PASS":
            chain_result["error"] = str(chain_result.get("error") or "") or str(
                menu_result.get("error") or ""
            )
        return chain_result

    chain = iter_provider_chain(provider, order=provider_order)
    primary_provider = chain[0] if chain else "bailian"
    provider_attempts: List[Dict[str, Any]] = []

    for candidate_provider in chain:
        try:
            result = _invoke_within_provider(
                candidate_provider,
                prompt=prompt,
                system=system,
                model=model,
                base_url=base_url,
                max_tokens=max_tokens,
                temperature=temperature,
                config_path=config_path,
                route_hints=route_hints,
                disable_thinking=disable_thinking,
            )
        except Exception as exc:  # noqa: BLE001 - 单 provider 失败应继续下一家
            result = {
                "status": "FAIL",
                "selected_model": "",
                "selected_vendor": "",
                "attempts": [],
                "switching": {},
                "response": {},
                "error": str(exc),
            }

        if result.get("status") == "PASS":
            provider_attempts.append(
                {"provider": candidate_provider, "status": "PASS", "error": ""}
            )
            provider_switching = _build_provider_switching_report(
                provider_attempts,
                primary_provider=primary_provider,
                selected_provider=candidate_provider,
            )
            combined = dict(result.get("switching") or {})
            combined["provider"] = provider_switching
            combined["selected_provider"] = candidate_provider
            if provider_switching["switched"]:
                base_summary = str(combined.get("summary") or "")
                combined["summary"] = (
                    f"{provider_switching['summary']}；{base_summary}"
                    if base_summary
                    else provider_switching["summary"]
                )
            combined.setdefault("mode", "provider-chain")
            return {
                "status": "PASS",
                "provider": candidate_provider,
                "selected_provider": candidate_provider,
                "selected_model": result.get("selected_model", ""),
                "selected_vendor": result.get("selected_vendor", ""),
                # 链模式无候选清单概念，固定 -1 以保持返回体形状稳定
                # （调用方无需为本字段做 None 分支）。
                "candidate_index": -1,
                "attempts": result.get("attempts", []),
                "provider_attempts": provider_attempts,
                "switching": combined,
                "provider_switching": provider_switching,
                "response": result.get("response", {}),
                "error": "",
            }

        provider_attempts.append(
            {
                "provider": candidate_provider,
                "status": "FAIL",
                "error": str(result.get("error") or ""),
            }
        )

    provider_switching = _build_provider_switching_report(
        provider_attempts,
        primary_provider=primary_provider,
        selected_provider="",
    )
    return {
        "status": "FAIL",
        "provider": str(provider or "auto"),
        "selected_provider": "",
        "selected_model": "",
        "selected_vendor": "",
        "candidate_index": -1,
        "attempts": [],
        "provider_attempts": provider_attempts,
        "switching": {
            "switched": False,
            "cross_vendor": False,
            "primary_model": model or "",
            "selected_model": "",
            "selected_vendor": "",
            "failed_models": [],
            "selected_provider": "",
            "provider": provider_switching,
            "mode": "provider-chain",
            "summary": provider_switching["summary"],
        },
        "provider_switching": provider_switching,
        "response": {},
        "error": "all_providers_failed",
    }


def load_provider_config(config_path: str | Path | None) -> Dict[str, Any]:
    """从 config.json 读取 ``llm.providers`` 覆盖配置（兼容老配置）。

    Args:
        config_path: 全局调度配置路径。

    Returns:
        providers 覆盖字典（空字典表示无覆盖）。
    """

    if config_path is None:
        return {}
    path = Path(config_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    llm_payload = payload.get("llm") if isinstance(payload, dict) else {}
    providers = llm_payload.get("providers") if isinstance(llm_payload, dict) else {}
    return providers if isinstance(providers, dict) else {}
