"""出境闸的**通用**接入点（供 AOK 的 LLM 层调用）。

## 为什么放在这里

`autodo-kit` 是**通用工具仓**，不得依赖 MLMS 专属的 `mlms_kit`。
但「调用外部 LLM 前先过闸」这件事必须发生在**调用点**上。

解法：AOK 只暴露一个**可注入的钩子**，具体策略由宿主（mlms-app）注册。

```
AOK invoke_llm  ──调用──▶  已注册的钩子  ──▶  宿主策略（查登记库）
```

未注册钩子时**不拦截** —— 通用仓保持通用，不替宿主做安全决策。

## 宿主如何注册

```python
from autodokit.tools.atomic.llm.external_guard import register_external_guard

def my_guard(*, prompt: str, system: str | None, provider: str, model: str) -> None:
    # 抛异常即阻断
    ...

register_external_guard(my_guard)
```

## 钩子的契约

- **返回 None** → 放行；
- **抛异常** → 阻断，异常消息即拒绝理由；
- 钩子**不得**修改 prompt / system（只做判定，不做改写）。

## 为什么钩子收不到「项目键」

LLM 调用层不知道内容属于哪个项目 —— 那是**调用方**的知识。
故钩子只能看到 prompt 文本本身，由宿主策略自行判断（如按关键词、按调用方传入的标记）。
需要精确到项目时，调用方应**先自行过闸**，再调用 `invoke_llm`。
"""
from __future__ import annotations

from typing import Callable, Optional

#: 钩子签名：关键字参数，返回 None 放行，抛异常阻断。
ExternalGuard = Callable[..., None]

_guard: Optional[ExternalGuard] = None


def register_external_guard(guard: Optional[ExternalGuard]) -> None:
    """注册（或清除）出境闸钩子。

    Args:
        guard: 钩子函数；传 None 表示清除。

    Returns:
        None

    Examples:
        >>> register_external_guard(None)
        >>> register_external_guard(lambda **kw: None)
    """
    global _guard
    _guard = guard
    pass  # function


def get_external_guard() -> Optional[ExternalGuard]:
    """取当前注册的钩子。

    Returns:
        ExternalGuard | None: 钩子；未注册时为 None。

    Examples:
        >>> get_external_guard() is None
        True
    """
    return _guard


def check_external_call(*, prompt: str, system: str | None, provider: str, model: str) -> None:
    """在外部 LLM 调用前过闸。

    未注册钩子时**直接放行** —— 通用仓不替宿主做安全决策。

    Args:
        prompt: 用户提示词。
        system: 系统提示词。
        provider: 目标 provider。
        model: 目标模型。

    Raises:
        Exception: 钩子抛出的任何异常（原样上抛，由调用方处理）。

    Examples:
        >>> check_external_call(prompt="hi", system=None, provider="lmstudio", model="x")
    """
    guard = _guard
    if guard is None:
        return
    guard(prompt=prompt, system=system, provider=provider, model=model)
    pass  # function


pass  # module
