"""多后端大模型调用抽象层（LLMProvider）。

本模块把「大模型调用」抽象为独立维度：``LLMProvider`` 是一级概念，
阿里百炼只是 provider 之一，LM Studio 是第二个内置 provider。

设计目标：

- 复用 ``llm_clients.AliyunLLMClient``（无需新建客户端类）。
- 提供 ``invoke_llm`` 统一调用入口，返回结构与 ``invoke_aliyun_llm`` 对齐。
- ``auto`` 路由：本地 provider（LM Studio）在线则优先，否则回退云端（百炼）。
- 密钥统一走 ``secrets_manager``（``~/.config/autodo-suite/secrets/``），
  任何 provider 的密钥均不落代码、文档、日志。
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from autodokit.tools.atomic.llm.llm_clients import (
    AliyunLLMClient,
    AliyunLLMConfig,
    ModelRoutingIntent,
    load_aliyun_llm_config,
)
from autodokit.tools.atomic.llm.secrets_manager import mask_api_key, secret_path

SdkBackend = Literal["dashscope", "openai-compatible"]
ProviderName = Literal["bailian", "lmstudio"]


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


#: 内置 provider 注册表（单一真相源）。
_BUILTIN_PROVIDERS: Dict[str, LLMProvider] = {
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

    return list(_BUILTIN_PROVIDERS.keys())


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
    provider = _BUILTIN_PROVIDERS.get(key)
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


def resolve_provider(name: str = "auto") -> str:
    """解析 provider 选择（支持 auto）。

    规则：
    - 显式名称：直接返回（未注册则抛 KeyError）。
    - ``auto``：本地 provider（lmstudio）在线则优先，否则回退 bailian。

    Args:
        name: provider 名或 ``auto``。

    Returns:
        解析后的 provider 名称。
    """

    value = str(name or "auto").strip().lower()
    if value == "auto":
        try:
            local = get_provider("lmstudio")
            if is_local_online(local):
                return "lmstudio"
        except Exception:
            pass
        return "bailian"
    return get_provider(value).name


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

    if provider_def.is_local and effective_backend == "openai-compatible":
        # 本地 provider：直接使用 openai-compatible + base_url + secrets 密钥。
        cfg = load_aliyun_llm_config(
            model=effective_model,
            api_key_file=str(secret_path(provider_def.secret_name)),
            base_url=effective_base_url,
            sdk_backend="openai-compatible",
            config_path=config_path,
            affair_name="llm-provider",
            route_hints=route_hints,
        )
    else:
        cfg = load_aliyun_llm_config(
            model=effective_model,
            env_api_key_name=env_api_key_name,
            base_url=effective_base_url,
            sdk_backend=effective_backend,
            config_path=config_path,
            affair_name="llm-provider",
            route_hints=route_hints,
        )
    return AliyunLLMClient(cfg), resolved


def invoke_llm(
    *,
    prompt: str,
    system: str | None = None,
    provider: str = "auto",
    model: str = "",
    base_url: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.2,
    config_path: str | Path | None = None,
    route_hints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """统一调用入口（支持任意 provider）。

    Args:
        prompt: 用户提示词。
        system: 系统提示词。
        provider: provider 名或 auto。
        model: 显式模型名。
        base_url: 显式 base_url。
        max_tokens: 最大输出 token。
        temperature: 采样温度。
        config_path: 全局调度配置路径。
        route_hints: 路由提示。

    Returns:
        统一返回结构：``status``、``selected_model``、``provider``、``response``。
    """

    try:
        client, resolved_provider = build_llm_client(
            provider,
            model=model,
            base_url=base_url,
            config_path=config_path,
            route_hints=route_hints,
        )
        text = client.generate_text(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return {
            "status": "PASS",
            "provider": resolved_provider,
            "selected_model": client.model,
            "response": {"text": text},
            "error": "",
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "provider": str(provider or "auto"),
            "selected_model": model or "",
            "response": {},
            "error": str(exc),
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
