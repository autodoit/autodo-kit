"""在线检索路由入口。"""

from __future__ import annotations

from typing import Any, Callable

from ..orchestrators import dispatch_request

DebugHandler = Callable[[dict[str, Any]], dict[str, Any]]


def route_request(payload: dict[str, Any], *, debug_handler: DebugHandler | None = None) -> dict[str, Any]:
    return dispatch_request(payload, debug_handler=debug_handler)
