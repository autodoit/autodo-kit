"""LLM 工具统一入口（多后端大模型调用 + 模型目录）。

本子域统一收口所有大模型相关工具，是对外唯一入口：

- ``llm_catalog``：**模型目录数据层**。读取 ``catalog/llm_catalog.json``，
  提供模型清单/能力/价格的查询（``find_models`` / ``describe_model`` 等）。
- ``llm_clients``：客户端 + 模型路由 + 阿里百炼调用。
- ``llm_providers``：多后端抽象（deepseek / bailian / lmstudio）。
- ``llm_parsing``：LLM 输出解析。
- ``secrets_manager``：统一密钥仓库与脱敏。

**数据文件是单一真相源**：可用的模型、它们各自的参数与价格、provider 的调用顺序
都定义在 ``catalog/llm_catalog.json``。调整模型或顺序只需改这个 JSON，
无需改动 Python 代码；改完调 :func:`reload_catalog` 即生效。
JSON 读取失败时会自动退回内置兜底快照（不会中断运行）。

对外统一从本模块导入，例如：

    from autodokit.tools.atomic.llm import invoke_llm, find_models, describe_model

按需选模型的例子：

    # 需要视觉 + JSON 输出、成本等级不超过 2 的可用模型
    for item in find_models(needs_vision=True, needs_json=True, max_cost_level=2):
        print(item.id, item.display_name)

    # 查看某模型的全貌（含价格与能力）
    print(describe_model("deepseek-flash")["text"])
"""

from __future__ import annotations

# 目录层必须先导入（其他模块依赖它的数据）。
from autodokit.tools.atomic.llm.llm_catalog import *  # noqa: F401,F403
from autodokit.tools.atomic.llm.llm_clients import *  # noqa: F401,F403
from autodokit.tools.atomic.llm.llm_parsing import *  # noqa: F401,F403
from autodokit.tools.atomic.llm.llm_providers import *  # noqa: F401,F403
from autodokit.tools.atomic.llm.secrets_manager import *  # noqa: F401,F403
