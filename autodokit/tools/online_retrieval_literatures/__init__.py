"""在线检索文献模块。

公开口径：请求画像层 + 路由层 + 编排层 + 执行层。
"""

from .router import route_request
from .profiles import infer_request_profile

__all__ = [
	"route_request",
	"infer_request_profile",
]
