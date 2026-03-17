"""LLM 客户端封装与智能路由。

本模块用于统一封装阿里百炼（DashScope）调用，提供以下能力：
- 统一读取 API Key（不在仓库中硬编码密钥）。
- 支持 DashScope SDK 与 OpenAI 兼容 SDK 两种调用后端。
- 支持按事务类型、成本档位、输入规模进行自动模型路由。

设计目标：
- 对事务层保持最小侵入：已有 `load_aliyun_llm_config` + `AliyunDashScopeClient` 调用方式继续可用。
- 将“选模型/选后端/选地域 base_url”逻辑集中在工具层，避免散落在事务脚本中。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from autodoengine.utils.config_loader import load_api_key_from_config
from autodoengine.utils.runtime_context import get_global_config_path


class LLMConfigError(RuntimeError):
    """LLM 配置错误。

    当缺少 API Key、模型、后端配置等必要信息时抛出。
    """


TaskType = Literal["general", "vision", "long_text", "math_reasoning", "coding"]
BudgetTier = Literal["cheap", "balanced", "premium"]
SdkBackend = Literal["dashscope", "openai-compatible"]


@dataclass(frozen=True)
class ModelRouteRequest:
    """模型路由请求。

    Args:
        model: 用户显式指定的模型名；若为 auto/smart 则进入自动选模。
        affair_name: 事务名称（用于自动推断任务类型）。
        task_type: 任务类型；不提供时会根据事务名和输入规模推断。
        budget_tier: 成本档位（cheap/balanced/premium）。
        prefer_backend: 偏好后端；不提供时由任务类型推断。
        region: 地域（cn-beijing/ap-southeast-1/us-east-1）。
        input_chars: 估计输入字符数，用于触发长文本模型。
        prefer_quality: 是否偏好更高质量（会在同档位上提一档）。
        need_vision: 是否为视觉识别任务。
        need_math_reasoning: 是否为数学推理任务。
    """

    model: str = "auto"
    affair_name: Optional[str] = None
    task_type: Optional[TaskType] = None
    budget_tier: BudgetTier = "balanced"
    prefer_backend: Optional[SdkBackend] = None
    region: str = "cn-beijing"
    input_chars: Optional[int] = None
    prefer_quality: bool = False
    need_vision: bool = False
    need_math_reasoning: bool = False


@dataclass(frozen=True)
class ModelRouteResult:
    """模型路由结果。

    Args:
        model: 最终选择的模型名。
        task_type: 最终任务类型。
        sdk_backend: 最终调用后端。
        base_url: 对应地域的 OpenAI 兼容 base_url。
        budget_tier: 最终使用的成本档位。
        reason: 路由说明，便于排障与日志记录。
    """

    model: str
    task_type: TaskType
    sdk_backend: SdkBackend
    base_url: str
    budget_tier: BudgetTier
    reason: str


@dataclass(frozen=True)
class AliyunLLMConfig:
    """阿里百炼模型配置。

    Args:
        api_key: API Key（通过密钥文件加载）。
        model: 模型名称。
        base_url: OpenAI 兼容接口 base_url。
        sdk_backend: 调用后端（dashscope/openai-compatible）。
        region: 地域标识。
        routing_info: 路由结果明细（可选）。
    """

    api_key: str
    model: str = "qwen-plus"
    base_url: Optional[str] = None
    sdk_backend: SdkBackend = "dashscope"
    region: str = "cn-beijing"
    routing_info: Dict[str, Any] = field(default_factory=dict)


_AUTO_MODEL_ALIASES = {"", "auto", "smart", "auto-model", "smart-model"}

_REGION_BASE_URL_MAP: Dict[str, str] = {
    "cn-beijing": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "ap-southeast-1": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "us-east-1": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
}

#: 按阿里百炼官方文档定义的“仅中国内地部署模式”模型前缀集合。
#: 说明：这里采用“保守”策略——仅对白名单前缀做地域限制，避免误判导致不必要降级。
_CN_ONLY_MODEL_PREFIXES: tuple[str, ...] = (
    "qwen-long",
    "qwen-math-",
    "qwen-doc-",
    "qwen-deep-research",
    "tongyi-xiaomi-",
    "tongyi-intent-detect-",
    "gui-plus",
    "qwen-audio-",
)

#: 一些老型号在官方文档中已明确“后续不再更新”的替代关系。
_DEPRECATED_MODEL_REPLACEMENTS: Dict[str, str] = {
    "qwen-turbo": "qwen3.5-flash",
    "qwen-vl-max": "qwen3-vl-plus",
    "qwen-vl-plus": "qwen3-vl-plus",
    "qwen-max": "qwen3-max",
    "qwen-plus": "qwen3.5-plus",
    "qwen-flash": "qwen3.5-flash",
}

_DEFAULT_MODEL_POOL: Dict[TaskType, Dict[BudgetTier, str]] = {
    # 文本通用：优先使用官方“旗舰模型”的稳定版命名。
    "general": {
        "cheap": "qwen3.5-flash",
        "balanced": "qwen3.5-plus",
        "premium": "qwen3-max",
    },
    # 视觉理解：Flash/Plus 覆盖大多数 OCR、图像问答、图表理解。
    "vision": {
        "cheap": "qwen3-vl-flash",
        "balanced": "qwen3-vl-plus",
        "premium": "qwen3-vl-plus",
    },
    # 长文本：qwen-long 具备 10M 上下文（但常见为“仅中国内地”），无法使用时降级到 Plus/Max。
    "long_text": {
        "cheap": "qwen-long",
        "balanced": "qwen-long",
        "premium": "qwen3.5-plus",
    },
    # 数学/推理：优先路由到 QwQ 系列；低预算时允许用 Flash 做兜底。
    "math_reasoning": {
        "cheap": "qwen3.5-flash",
        "balanced": "qwq-plus",
        "premium": "qwq-plus",
    },
    # 代码：使用 Qwen3-Coder 系列。
    "coding": {
        "cheap": "qwen3-coder-flash",
        "balanced": "qwen3-coder-plus",
        "premium": "qwen3-coder-plus",
    },
}


def _read_text_if_exists(path: Path) -> Optional[str]:
    """读取文本文件（若存在）。

    Args:
        path: 文件路径。

    Returns:
        文件内容（去除首尾空白）或 None。
    """

    try:
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8-sig").strip()
            return text or None
    except Exception:
        return None
    return None


def _parse_api_key_text(text: str, *, env_api_key_name: str = "DASHSCOPE_API_KEY") -> str:
    """从文本中提取 API Key。

    支持两种格式：
    1) 纯 key（单行或首个非空非注释行）；
    2) KEY=VALUE（优先读取 env_api_key_name，对 default/api_key/key 等别名做兼容）。

    Args:
        text: 密钥文件原始文本。
        env_api_key_name: 逻辑 key 名。

    Returns:
        解析出的 API Key；若未解析到则返回空字符串。

    Examples:
        >>> _parse_api_key_text("sk-abc")
        'sk-abc'
        >>> _parse_api_key_text("DASHSCOPE_API_KEY=sk-abc")
        'sk-abc'
    """

    lines = (text or "").splitlines()
    fallback_plain_value = ""

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.lower().startswith("export "):
            line = line[7:].lstrip()

        if "=" not in line:
            if not fallback_plain_value:
                fallback_plain_value = line.strip().strip('"').strip("'")
            continue

        key_name, value = line.split("=", 1)
        key_name = key_name.strip()
        value = value.strip().strip('"').strip("'")
        if not value:
            continue

        if key_name == env_api_key_name:
            return value
        if key_name.lower() in {"default", "api_key", "apikey", "key"}:
            if not fallback_plain_value:
                fallback_plain_value = value

    return fallback_plain_value


def _iter_default_api_key_file_candidates() -> List[Path]:
    """生成默认 API Key 文件候选路径。

    Returns:
        候选路径列表（按优先级顺序）。

    Examples:
        >>> candidates = _iter_default_api_key_file_candidates()
        >>> len(candidates) >= 1
        True
    """

    repo_root = Path(__file__).resolve().parents[2]
    return [
        repo_root / "demos" / "settings" / "配置文件" / "bailian_api_key.txt",
        repo_root / "config" / "bailian_api_key.txt",
        repo_root / "demos" / "settings" / "配置文件" / "dashscope_api_key.txt",
        repo_root / "config" / "dashscope_api_key.txt",
        repo_root / "config" / "API-Keys.txt",
    ]


def _load_api_key_from_file(file_path: Path, *, env_api_key_name: str = "DASHSCOPE_API_KEY") -> str:
    """从密钥文件加载 API Key。

    Args:
        file_path: 密钥文件路径。
        env_api_key_name: 逻辑 key 名。

    Returns:
        API Key 字符串；未找到则返回空字符串。

    Examples:
        >>> _load_api_key_from_file(Path("not_exists.txt"))
        ''
    """

    text = _read_text_if_exists(file_path)
    if not text:
        return ""
    return _parse_api_key_text(text, env_api_key_name=env_api_key_name).strip()


def _normalize_region(region: str | None) -> str:
    """规范化地域名称。

    Args:
        region: 原始地域字符串。

    Returns:
        规范化后的地域值。
    """

    raw = (region or "cn-beijing").strip().lower()
    alias_map = {
        "cn": "cn-beijing",
        "beijing": "cn-beijing",
        "china": "cn-beijing",
        "mainland": "cn-beijing",
        "sg": "ap-southeast-1",
        "singapore": "ap-southeast-1",
        "intl": "ap-southeast-1",
        "international": "ap-southeast-1",
        "global": "ap-southeast-1",
        "us": "us-east-1",
        "virginia": "us-east-1",
        "america": "us-east-1",
    }
    return alias_map.get(raw, raw)


def _normalize_model_name(model: str) -> str:
    """规范化模型名称。

    主要用于：
    - 将明确“弃用/停止更新”的老型号替换为推荐型号。
    - 保持路由输出尽量使用“官方当前主推”的稳定版命名，降低维护成本。

    Args:
        model: 原始模型名。

    Returns:
        规范化后的模型名。
    """

    name = (model or "").strip()
    if not name:
        return name
    return _DEPRECATED_MODEL_REPLACEMENTS.get(name, name)


def _is_cn_only_model(model: str) -> bool:
    """判断模型是否仅支持中国内地部署模式。

    Args:
        model: 模型名称。

    Returns:
        若模型为“仅中国内地”则返回 True，否则返回 False。
    """

    name = (model or "").strip()
    if not name:
        return False
    return any(name.startswith(prefix) for prefix in _CN_ONLY_MODEL_PREFIXES)


def _infer_is_ocr_affair(affair_name: str | None) -> bool:
    """判断事务是否偏 OCR/文字抽取。

    Args:
        affair_name: 事务名称。

    Returns:
        是否为 OCR 类任务。
    """

    name = (affair_name or "").strip().lower()
    if not name:
        return False
    return any(token in name for token in ["ocr", "文字识别", "表格识别", "题录", "扫描", "票据", "抄录"])


def _infer_task_type_from_affair_name(affair_name: str | None) -> TaskType:
    """根据事务名推断任务类型。

    Args:
        affair_name: 事务名称。

    Returns:
        推断得到的任务类型。
    """

    name = (affair_name or "").strip().lower()
    if not name:
        return "general"

    if any(token in name for token in ["视觉", "图像", "ocr", "图片", "pdf文件转结构化"]):
        return "vision"
    if any(token in name for token in ["代码", "编程", "写代码", "修 bug", "debug", "单元测试", "重构", "仓库", "脚本"]):
        return "coding"
    if any(token in name for token in ["数学", "推理", "公式", "证明"]):
        return "math_reasoning"
    if any(token in name for token in ["综述", "矩阵", "长文", "长文本", "精读"]):
        return "long_text"
    return "general"


def _upgrade_budget_tier(tier: BudgetTier) -> BudgetTier:
    """提升成本档位（用于质量优先）。

    Args:
        tier: 原始档位。

    Returns:
        提升后的档位。
    """

    if tier == "cheap":
        return "balanced"
    if tier == "balanced":
        return "premium"
    return "premium"


def route_aliyun_model(
    request: ModelRouteRequest,
    *,
    model_pool: Optional[Dict[TaskType, Dict[BudgetTier, str]]] = None,
) -> ModelRouteResult:
    """执行阿里百炼模型路由。

    路由规则（简化版）：
    1) 优先使用显式 task_type；否则根据事务名推断。
    2) 若 input_chars 很大，自动提升为 long_text。
    3) vision/math 标记会强制对应任务类型。
    4) prefer_quality=True 时，预算档位上提一档。

    Args:
        request: 路由请求。
        model_pool: 可选模型池覆盖。

    Returns:
        模型路由结果。

    Examples:
        >>> req = ModelRouteRequest(model="auto", affair_name="综述草稿生成", budget_tier="cheap")
        >>> result = route_aliyun_model(req)
        >>> result.task_type in {"long_text", "general"}
        True
    """

    pool = model_pool or _DEFAULT_MODEL_POOL
    region = _normalize_region(request.region)
    base_url = _REGION_BASE_URL_MAP.get(region, _REGION_BASE_URL_MAP["cn-beijing"])

    inferred_type: TaskType = request.task_type or _infer_task_type_from_affair_name(request.affair_name)
    reasons: List[str] = [f"初始任务类型={inferred_type}"]

    if request.need_vision:
        inferred_type = "vision"
        reasons.append("need_vision=True")
    if request.need_math_reasoning:
        inferred_type = "math_reasoning"
        reasons.append("need_math_reasoning=True")

    if request.input_chars is not None and int(request.input_chars) >= 12000 and inferred_type == "general":
        inferred_type = "long_text"
        reasons.append(f"input_chars={request.input_chars} 触发长文本")

    budget_tier = request.budget_tier
    if request.prefer_quality:
        budget_tier = _upgrade_budget_tier(budget_tier)
        reasons.append(f"prefer_quality=True，提升档位为 {budget_tier}")

    model = pool.get(inferred_type, pool["general"]).get(budget_tier, "qwen3.5-plus")

    # OCR 任务尽量使用专用模型（比通用 VL 更聚焦文字提取）。
    if inferred_type == "vision" and _infer_is_ocr_affair(request.affair_name):
        model = "qwen-vl-ocr"
        reasons.append("OCR 任务：优先选择 qwen-vl-ocr")

    model = _normalize_model_name(model)

    # 若模型仅支持中国内地，但用户选择了国际/美国节点，则自动降级。
    if _is_cn_only_model(model) and region != "cn-beijing":
        fallback = pool.get("general", {}).get(budget_tier, "qwen3.5-plus")
        fallback = _normalize_model_name(fallback)
        reasons.append(f"模型 {model} 仅支持中国内地，region={region}，降级为 {fallback}")
        model = fallback

    if request.prefer_backend is not None:
        backend: SdkBackend = request.prefer_backend
        reasons.append(f"显式后端={backend}")
    else:
        backend = "openai-compatible" if inferred_type == "vision" else "dashscope"
        reasons.append(f"按任务类型选择后端={backend}")

    return ModelRouteResult(
        model=model,
        task_type=inferred_type,
        sdk_backend=backend,
        base_url=base_url,
        budget_tier=budget_tier,
        reason="; ".join(reasons),
    )


def _parse_route_hints(route_hints: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """清洗路由提示字段。

    Args:
        route_hints: 原始路由配置。

    Returns:
        规范化后的路由配置字典。
    """

    if not isinstance(route_hints, dict):
        return {}

    cleaned: Dict[str, Any] = {}
    for k, v in route_hints.items():
        cleaned[str(k).strip()] = v
    return cleaned


def _parse_backend(raw_backend: Any) -> Optional[SdkBackend]:
    """解析后端名称。

    Args:
        raw_backend: 原始后端值。

    Returns:
        解析后的后端；无法识别时返回 None。
    """

    value = (str(raw_backend or "").strip().lower() if raw_backend is not None else "")
    if not value:
        return None
    if value in {"dashscope", "ds"}:
        return "dashscope"
    if value in {"openai", "openai-compatible", "compatible", "compat"}:
        return "openai-compatible"
    return None


def _resolve_model_and_backend(
    *,
    model: str,
    sdk_backend: str | None,
    base_url: str | None,
    region: str,
    affair_name: str | None,
    route_hints: Optional[Dict[str, Any]],
) -> tuple[str, SdkBackend, str, Dict[str, Any]]:
    """解析最终模型与后端配置。

    Args:
        model: 用户传入模型名。
        sdk_backend: 用户传入后端。
        base_url: 用户传入 base_url。
        region: 用户传入地域。
        affair_name: 事务名称。
        route_hints: 路由提示。

    Returns:
        四元组：模型、后端、base_url、路由信息。
    """

    region_norm = _normalize_region(region)
    hints = _parse_route_hints(route_hints)
    backend_hint = _parse_backend(hints.get("prefer_backend"))
    backend_from_arg = _parse_backend(sdk_backend)

    model_text = (model or "").strip()
    auto_mode = (not model_text) or (model_text.lower() in _AUTO_MODEL_ALIASES)

    if auto_mode:
        req = ModelRouteRequest(
            model=model_text or "auto",
            affair_name=affair_name,
            task_type=(
                hints.get("task_type")
                if hints.get("task_type") in {"general", "vision", "long_text", "math_reasoning", "coding"}
                else None
            ),
            budget_tier=(
                hints.get("budget_tier")
                if hints.get("budget_tier") in {"cheap", "balanced", "premium"}
                else "balanced"
            ),
            prefer_backend=backend_hint or backend_from_arg,
            region=str(hints.get("region") or region_norm),
            input_chars=(int(hints["input_chars"]) if hints.get("input_chars") is not None else None),
            prefer_quality=bool(hints.get("prefer_quality", False)),
            need_vision=bool(hints.get("need_vision", False)),
            need_math_reasoning=bool(hints.get("need_math_reasoning", False)),
        )
        routed = route_aliyun_model(req)
        resolved_model = routed.model
        resolved_backend = routed.sdk_backend
        resolved_base_url = base_url or routed.base_url
        routing_info = {
            "mode": "auto",
            "task_type": routed.task_type,
            "budget_tier": routed.budget_tier,
            "reason": routed.reason,
        }
        return resolved_model, resolved_backend, resolved_base_url, routing_info

    resolved_backend = backend_from_arg or backend_hint or "dashscope"
    resolved_base_url = base_url or _REGION_BASE_URL_MAP.get(region_norm, _REGION_BASE_URL_MAP["cn-beijing"])
    routing_info = {
        "mode": "manual",
        "task_type": _infer_task_type_from_affair_name(affair_name),
        "budget_tier": (hints.get("budget_tier") if hints.get("budget_tier") in {"cheap", "balanced", "premium"} else "balanced"),
        "reason": "使用显式模型，不触发自动路由",
    }
    return model_text, resolved_backend, resolved_base_url, routing_info


def load_aliyun_llm_config(
    *,
    model: str = "qwen-plus",
    env_api_key_name: str = "DASHSCOPE_API_KEY",
    api_key_file: str | None = None,
    base_url: str | None = None,
    config_path: str | Path | None = None,
    sdk_backend: str | None = None,
    region: str = "cn-beijing",
    affair_name: str | None = None,
    route_hints: Optional[Dict[str, Any]] = None,
) -> AliyunLLMConfig:
    """加载阿里百炼 LLM 配置。

    API Key 查找优先级：
    1) 显式传入 `api_key_file`
    2) `config.json` 的 `secrets_file`
    3) 默认候选路径（优先 `bailian_api_key.txt`，并兼容旧文件名）

    模型与后端选择规则：
    - 当 model 为 `auto/smart` 时，按 route_hints + affair_name 自动路由。
    - 当 model 为显式模型名时，保持手动模式。

    Args:
        model: 模型名，支持 auto/smart 触发自动路由。
        env_api_key_name: 逻辑 key 名（默认 DASHSCOPE_API_KEY）。
        api_key_file: 可选，密钥文件路径。
        base_url: 可选，自定义 base_url。
        config_path: 全局调度配置路径。
        sdk_backend: 可选，指定调用后端。
        region: 地域，用于选择默认 base_url。
        affair_name: 事务名称。
        route_hints: 路由提示，例如 task_type/budget_tier/input_chars。

    Returns:
        `AliyunLLMConfig` 对象。

    Raises:
        LLMConfigError: 未找到可用 API Key。
    """

    api_key = ""

    if api_key_file:
        p = Path(api_key_file).expanduser()
        api_key = _load_api_key_from_file(p.resolve(), env_api_key_name=env_api_key_name)

    if not api_key:
        try:
            effective_config_path = config_path
            if effective_config_path is None:
                ctx_p = get_global_config_path()
                if ctx_p is not None:
                    effective_config_path = ctx_p

            if effective_config_path is not None:
                api_key = load_api_key_from_config(config_path=effective_config_path, env_var_name=env_api_key_name)
            else:
                api_key = load_api_key_from_config(env_var_name=env_api_key_name)
        except Exception:
            api_key = ""

    if not api_key:
        for candidate in _iter_default_api_key_file_candidates():
            api_key = _load_api_key_from_file(candidate, env_api_key_name=env_api_key_name)
            if api_key:
                break

    if not api_key:
        raise LLMConfigError(
            "未找到阿里百炼 API Key。请在 config.json 中配置 secrets_file（建议），"
            "或通过 api_key_file 传入本地密钥文件（例如 bailian_api_key.txt）。"
        )

    resolved_model, resolved_backend, resolved_base_url, routing_info = _resolve_model_and_backend(
        model=model,
        sdk_backend=sdk_backend,
        base_url=base_url,
        region=region,
        affair_name=affair_name,
        route_hints=route_hints,
    )

    return AliyunLLMConfig(
        api_key=api_key,
        model=resolved_model,
        base_url=resolved_base_url,
        sdk_backend=resolved_backend,
        region=_normalize_region(region),
        routing_info=routing_info,
    )


class AliyunLLMClient:
    """阿里百炼调用客户端（兼容两种 SDK 后端）。

    - `dashscope`：使用官方 DashScope SDK。
    - `openai-compatible`：使用 OpenAI Python SDK 调用兼容接口。
    """

    def __init__(self, config: AliyunLLMConfig):
        """初始化客户端。

        Args:
            config: 阿里百炼配置对象。
        """

        self._config = config

    @property
    def model(self) -> str:
        """返回当前模型名。

        Returns:
            当前模型名称。
        """

        return self._config.model

    @property
    def routing_info(self) -> Dict[str, Any]:
        """返回路由信息。

        Returns:
            路由信息字典。
        """

        return dict(self._config.routing_info)

    def _generate_text_with_dashscope(
        self,
        *,
        prompt: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
        extra: Optional[Dict[str, Any]],
    ) -> str:
        """使用 DashScope SDK 生成文本。

        Args:
            prompt: 用户提示词。
            system: 系统提示词。
            temperature: 温度参数。
            max_tokens: 最大生成 token。
            extra: 额外参数。

        Returns:
            模型输出文本。
        """

        try:
            import dashscope  # type: ignore
            from dashscope import Generation  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "未安装 dashscope SDK。请执行 `uv pip install dashscope`。"
            ) from exc

        try:
            dashscope.api_key = self._config.api_key  # type: ignore[attr-defined]
        except Exception:
            pass

        if self._config.base_url:
            os.environ["DASHSCOPE_BASE_URL"] = self._config.base_url

        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if extra:
            payload.update(extra)

        resp = Generation.call(**payload)

        try:
            return resp.output["choices"][0]["message"]["content"]  # type: ignore[index]
        except Exception:
            pass

        try:
            text = getattr(resp.output, "text", None)
            if isinstance(text, str) and text.strip():
                return text
        except Exception:
            pass

        try:
            if isinstance(resp.output, dict):
                text2 = resp.output.get("text")
                if isinstance(text2, str) and text2.strip():
                    return text2
        except Exception:
            pass

        return str(resp)

    def _generate_text_with_openai_compatible(
        self,
        *,
        prompt: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
        extra: Optional[Dict[str, Any]],
    ) -> str:
        """使用 OpenAI 兼容接口生成文本。

        Args:
            prompt: 用户提示词。
            system: 系统提示词。
            temperature: 温度参数。
            max_tokens: 最大生成 token。
            extra: 额外参数。

        Returns:
            模型输出文本。
        """

        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "未安装 openai SDK。请执行 `uv pip install openai`。"
            ) from exc

        if not self._config.base_url:
            raise RuntimeError("openai-compatible 后端需要提供 base_url。")

        client = OpenAI(api_key=self._config.api_key, base_url=self._config.base_url)

        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: Dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if extra:
            kwargs.update(extra)

        resp = client.chat.completions.create(**kwargs)
        if not resp.choices:
            return ""
        first = resp.choices[0]
        content = getattr(first.message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [str(x.get("text") or "") for x in content if isinstance(x, dict)]
            return "\n".join([t for t in texts if t.strip()])
        return str(content)

    def generate_text(
        self,
        *,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成文本。

        Args:
            prompt: 用户提示词。
            system: 系统提示词。
            temperature: 采样温度。
            max_tokens: 最大生成 token 数。
            extra: 额外参数透传。

        Returns:
            模型生成文本。

        Raises:
            RuntimeError: SDK 未安装或调用失败。
        """

        backend = self._config.sdk_backend
        if backend == "dashscope":
            return self._generate_text_with_dashscope(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                extra=extra,
            )

        if backend == "openai-compatible":
            return self._generate_text_with_openai_compatible(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                extra=extra,
            )

        raise RuntimeError(f"不支持的 SDK 后端：{backend}")


# 为兼容历史调用名，保留别名。
AliyunDashScopeClient = AliyunLLMClient
