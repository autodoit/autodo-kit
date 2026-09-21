"""大模型目录（LLM Catalog）：模型清单、能力、价格与调用顺序的**数据层**。

本模块是 ``autodokit/tools/atomic/llm`` 子域的**最底层**：只负责把数据文件
``catalog/llm_catalog.json`` 读成结构化对象，不涉及任何网络调用与密钥，
也不依赖 ``llm_clients`` / ``llm_providers``（避免循环导入）。

设计动机
--------

各家厂商每隔一段时间就会推出新模型、下架旧模型，且**不同模型的参数、能力、
价格都不一样**。若把这些硬编码在 Python 里，每次调整都要改代码 + 改测试 + 重新部署。
因此本模块把「有哪些模型、它们各自什么样、按什么顺序调用」外置为数据文件：

- **单一真相源**：``catalog/llm_catalog.json``。
- **可热更新**：改完 JSON 调 :func:`reload_catalog` 即生效，无需改代码。
- **读取失败可降级**：JSON 缺失或损坏时由调用方退回内置默认值，不中断运行。

对外能力
--------

1. **查询**：:func:`list_models` / :func:`get_model` / :func:`find_models`
   —— 按任务类型、能力、厂商、成本等级、上下文长度等条件筛选，便于“按需选模型”。
2. **说明**：:func:`describe_model` / :func:`format_model_table`
   —— 输出含参数、能力、价格的可读说明。
3. **路由数据**：:func:`provider_priority` / :func:`catalog_info`。

用法示例
--------

.. code-block:: python

    from autodokit.tools.atomic.llm.llm_catalog import find_models, describe_model

    # 需要视觉 + JSON 输出、成本等级不超过 2 的可用模型
    for item in find_models(needs_vision=True, needs_json=True, max_cost_level=2):
        print(item.id, item.display_name)

    # 看某个模型的全貌（含价格与能力）
    print(describe_model("deepseek-flash")["text"])
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: 目录数据文件相对于本模块的路径。
CATALOG_RELATIVE_PATH = Path("catalog") / "llm_catalog.json"

#: 模型生命周期状态。
STATUS_ACTIVE = "active"
STATUS_DEPRECATED = "deprecated"


class CatalogError(RuntimeError):
    """目录加载或校验失败。"""


@dataclass(frozen=True)
class ModelCapabilities:
    """模型的特殊能力（不同模型差异很大，需显式声明）。

    Args:
        thinking: 是否支持思考（推理）模式。
        vision: 是否支持图像输入。
        tool_calling: 是否支持工具/函数调用。
        json_output: 是否支持结构化 JSON 输出。
        streaming: 是否支持流式输出。
    """

    thinking: bool = False
    vision: bool = False
    tool_calling: bool = False
    json_output: bool = False
    streaming: bool = False


@dataclass(frozen=True)
class ModelPricing:
    """模型定价。

    注意：**不做汇率换算**。跨币种的金额不可直接相加，比较成本时应先看
    :attr:`currency` 是否一致。

    Args:
        currency: 币种（``CNY`` / ``USD``）。
        unit: 计价单位（固定为 ``per_million_tokens``）。
        input: 输入价格（标准价，可能为高峰价）。
        output: 输出价格。
        input_offpeak: 空闲时段输入价（若非分时计价则为 None）。
        output_offpeak: 空闲时段输出价。
        source: 价格来源说明（官方定价页 / 估算等）。
        verified_at: 人工核对日期；为空表示未核对（估算值）。
    """

    currency: str = "CNY"
    unit: str = "per_million_tokens"
    input: float = 0.0
    output: float = 0.0
    input_offpeak: Optional[float] = None
    output_offpeak: Optional[float] = None
    source: str = ""
    verified_at: str = ""

    @property
    def verified(self) -> bool:
        """价格是否经过人工核对（非估算）。

        Returns:
            True 表示有核对日期。
        """

        return bool(str(self.verified_at).strip())


@dataclass(frozen=True)
class CatalogModel:
    """目录中的一个模型条目。

    Args:
        id: 模型标识（调用时传给 API 的名字）。
        vendor: 厂商（alibaba / deepseek / moonshot / ...）。
        provider: 归属 provider（deepseek / bailian / lmstudio）。
        display_name: 展示名。
        family: 模型族（用于同系列回退排序）。
        status: 生命周期状态（active / deprecated）。
        replacement: 下线后的替代模型。
        task_types: 适配的任务类型。
        capabilities: 能力位。
        limits: 上下文与输出上限。
        pricing: 定价。
        cost_level: 相对成本等级（0=免费，数值越大越贵；用于粗排与筛选）。
        cn_only: 是否仅限中国内地地域。
        notes: 备注。
    """

    id: str
    vendor: str = ""
    provider: str = ""
    display_name: str = ""
    family: str = ""
    status: str = STATUS_ACTIVE
    replacement: str = ""
    task_types: Tuple[str, ...] = ()
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    limits: Dict[str, int] = field(default_factory=dict)
    pricing: ModelPricing = field(default_factory=ModelPricing)
    cost_level: int = 0
    cn_only: bool = False
    notes: str = ""

    @property
    def is_active(self) -> bool:
        """模型是否处于可用状态。

        Returns:
            True 表示 status 为 active。
        """

        return self.status == STATUS_ACTIVE

    @property
    def max_input_tokens(self) -> int:
        """最大输入 token 数（缺失时为 0）。

        Returns:
            上下文上限。
        """

        return int(self.limits.get("max_input_tokens") or 0)

    @property
    def max_output_tokens(self) -> int:
        """最大输出 token 数（缺失时为 0）。

        Returns:
            输出上限。
        """

        return int(self.limits.get("max_output_tokens") or 0)


@dataclass(frozen=True)
class CatalogProvider:
    """目录中的一个 provider 条目。

    Args:
        name: provider 唯一名。
        display_name: 展示名。
        priority: 优先级（**越小越优先**，决定 auto 路由顺序）。
        sdk_backend: 调用后端。
        base_url: 默认端点。
        default_model: 默认模型。
        fallback_models: provider 内的模型回退链。
        secret_name: 统一密钥仓库中的逻辑密钥名。
        env_api_key_name: 环境变量名。
        is_local: 是否本地服务。
        extra_body: 厂商私有请求字段（**始终随请求发送**）。
        no_thinking_body: 关闭思考模式时追加的请求字段。不同厂商参数名不同
            （百炼 Qwen 系列用 ``enable_thinking=false``，DeepSeek 用
            ``thinking.type=disabled``），故存放在数据文件而非硬编码。
        notes: 备注。
    """

    name: str
    display_name: str = ""
    priority: int = 100
    sdk_backend: str = "openai-compatible"
    base_url: str = ""
    default_model: str = ""
    fallback_models: Tuple[str, ...] = ()
    secret_name: str = ""
    env_api_key_name: str = ""
    is_local: bool = False
    extra_body: Dict[str, Any] = field(default_factory=dict)
    no_thinking_body: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class Catalog:
    """已加载的完整目录。

    Args:
        schema_version: 数据文件 schema 版本。
        catalog_version: 目录内容版本。
        updated_at: 目录更新日期。
        source_path: 数据文件路径（便于排障）。
        providers: provider 名 → 定义。
        models: 模型 id → 条目。
        task_pools: 任务类型 → 成本档位 → 主模型。
        cross_vendor_fallbacks: 跨厂商兜底链。
        deprecated_replacements: 下线模型 → 替代模型。
        cn_only_prefixes: 仅中国内地的模型名前缀。
        vendor_rules: 厂商识别规则（前缀 → 厂商）。
        region_base_urls: 地域 → 端点。
        default_region: 默认地域。
        warnings: 加载期的非致命告警（供排障）。
    """

    schema_version: int = 1
    catalog_version: str = ""
    updated_at: str = ""
    source_path: str = ""
    providers: Dict[str, CatalogProvider] = field(default_factory=dict)
    models: Dict[str, CatalogModel] = field(default_factory=dict)
    task_pools: Dict[str, Dict[str, str]] = field(default_factory=dict)
    cross_vendor_fallbacks: Tuple[str, ...] = ()
    deprecated_replacements: Dict[str, str] = field(default_factory=dict)
    cn_only_prefixes: Tuple[str, ...] = ()
    vendor_rules: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    region_base_urls: Dict[str, str] = field(default_factory=dict)
    default_region: str = "cn-beijing"
    warnings: Tuple[str, ...] = ()

    # ---- provider 相关查询 ----

    def provider_priority(self) -> Tuple[str, ...]:
        """返回按优先级升序排列的 provider 名（auto 路由的尝试顺序）。

        Returns:
            provider 名元组。
        """

        ordered = sorted(self.providers.values(), key=lambda p: (p.priority, p.name))
        return tuple(item.name for item in ordered)

    def get_provider(self, name: str) -> CatalogProvider:
        """按名取 provider。

        Args:
            name: provider 名（不区分大小写）。

        Returns:
            provider 定义。

        Raises:
            KeyError: provider 未注册。
        """

        key = str(name or "").strip().lower()
        if key not in self.providers:
            raise KeyError(
                f"未注册的 provider: {name!r}；已注册: {sorted(self.providers)}"
            )
        return self.providers[key]

    # ---- 模型相关查询 ----

    def get_model(self, model_id: str) -> CatalogModel:
        """按 id 取模型。

        Args:
            model_id: 模型 id（不区分大小写）。

        Returns:
            模型条目。

        Raises:
            KeyError: 模型不在目录中。
        """

        key = str(model_id or "").strip().lower()
        if key not in self._lower_index:
            raise KeyError(f"目录中不存在模型: {model_id!r}")
        return self.models[self._lower_index[key]]

    def has_model(self, model_id: str) -> bool:
        """判断模型是否在目录中（不区分大小写）。

        Args:
            model_id: 模型 id。

        Returns:
            True 表示存在。
        """

        return str(model_id or "").strip().lower() in self._lower_index

    def resolve_model_id(self, model_id: str) -> str:
        """把任意大小写的模型名解析为目录中的规范 id。

        Args:
            model_id: 模型 id。

        Returns:
            规范 id；不在目录中时原样返回（便于按自定义模型处理）。
        """

        key = str(model_id or "").strip().lower()
        return self._lower_index.get(key, str(model_id or "").strip())

    def infer_vendor(self, model: str) -> str:
        """按厂商识别规则推断模型所属厂商。

        Args:
            model: 模型名（可含 ``厂商/`` 前缀）。

        Returns:
            厂商标识；无法识别时返回 ``""``。
        """

        lowered = str(model or "").strip().lower()
        if not lowered:
            return ""
        head = lowered.split("/", 1)[0]
        for vendor, prefixes in self.vendor_rules:
            if any(head.startswith(prefix) for prefix in prefixes):
                return vendor
        for vendor, prefixes in self.vendor_rules:
            if any(lowered.startswith(prefix) for prefix in prefixes):
                return vendor
        return ""

    def is_cn_only(self, model: str) -> bool:
        """判断模型是否仅限中国内地地域。

        Args:
            model: 模型名。

        Returns:
            True 表示仅中国内地。
        """

        name = str(model or "").strip()
        return any(name.startswith(prefix) for prefix in self.cn_only_prefixes)

    # 内部：小写索引在 __post_init__ 后由加载器填充（frozen 故用 object.__setattr__）。
    _lower_index: Dict[str, str] = field(default_factory=dict, repr=False, compare=False)


# --------------------------------------------------------------------------
# 加载
# --------------------------------------------------------------------------

_CACHE: Dict[str, Any] = {"catalog": None, "path": None, "error": ""}
_LOCK = threading.RLock()


def default_catalog_path() -> Path:
    """返回目录数据文件的默认路径。

    Returns:
        绝对路径（不保证存在）。
    """

    return Path(__file__).resolve().parent / CATALOG_RELATIVE_PATH


def _as_bool(value: Any) -> bool:
    """把 JSON 中的值宽松地转成布尔。

    Args:
        value: 原始值。

    Returns:
        布尔值。
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _as_int(value: Any, default: int = 0) -> int:
    """把 JSON 中的值宽松地转成整数。

    Args:
        value: 原始值。
        default: 转换失败时的默认值。

    Returns:
        整数。
    """

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    """把 JSON 中的值宽松地转成浮点数。

    Args:
        value: 原始值。
        default: 转换失败时的默认值。

    Returns:
        浮点数。
    """

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_str_tuple(value: Any) -> Tuple[str, ...]:
    """把 JSON 数组转成字符串元组。

    Args:
        value: 原始值（数组或标量）。

    Returns:
        字符串元组。
    """

    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if value in (None, ""):
        return ()
    return (str(value).strip(),)


def _parse_capabilities(payload: Any) -> ModelCapabilities:
    """解析能力位。

    Args:
        payload: ``capabilities`` 字段。

    Returns:
        能力对象。
    """

    data = payload if isinstance(payload, dict) else {}
    return ModelCapabilities(
        thinking=_as_bool(data.get("thinking")),
        vision=_as_bool(data.get("vision")),
        tool_calling=_as_bool(data.get("tool_calling")),
        json_output=_as_bool(data.get("json_output")),
        streaming=_as_bool(data.get("streaming")),
    )


def _parse_pricing(payload: Any) -> ModelPricing:
    """解析定价块。

    Args:
        payload: ``pricing`` 字段。

    Returns:
        定价对象。
    """

    data = payload if isinstance(payload, dict) else {}

    def _opt_float(key: str) -> Optional[float]:
        if data.get(key) is None:
            return None
        return _as_float(data.get(key))

    return ModelPricing(
        currency=str(data.get("currency") or "CNY").strip().upper(),
        unit=str(data.get("unit") or "per_million_tokens").strip(),
        input=_as_float(data.get("input")),
        output=_as_float(data.get("output")),
        input_offpeak=_opt_float("input_offpeak"),
        output_offpeak=_opt_float("output_offpeak"),
        source=str(data.get("source") or "").strip(),
        verified_at=str(data.get("verified_at") or "").strip(),
    )


def _is_comment_only(payload: Dict[str, Any]) -> bool:
    """判断条目是否只是分节注释（JSON 不支持注释，用只含 ``$comment`` 的对象代替）。

    Args:
        payload: JSON 对象。

    Returns:
        True 表示只含 ``$comment`` 键（或为空），应静默跳过。
    """

    keys = {key for key in payload if not str(key).startswith("$")}
    return not keys


def _parse_model(payload: Dict[str, Any]) -> Optional[CatalogModel]:
    """解析单个模型条目。

    Args:
        payload: JSON 中的模型对象。

    Returns:
        模型条目；缺少 id 时返回 None。
    """

    model_id = str(payload.get("id") or "").strip()
    if not model_id:
        return None
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    return CatalogModel(
        id=model_id,
        vendor=str(payload.get("vendor") or "").strip().lower(),
        provider=str(payload.get("provider") or "").strip().lower(),
        display_name=str(payload.get("display_name") or model_id).strip(),
        family=str(payload.get("family") or "").strip(),
        status=str(payload.get("status") or STATUS_ACTIVE).strip().lower(),
        replacement=str(payload.get("replacement") or "").strip(),
        task_types=_as_str_tuple(payload.get("task_types")),
        capabilities=_parse_capabilities(payload.get("capabilities")),
        limits={
            "max_input_tokens": _as_int(limits.get("max_input_tokens")),
            "max_output_tokens": _as_int(limits.get("max_output_tokens")),
        },
        pricing=_parse_pricing(payload.get("pricing")),
        cost_level=_as_int(payload.get("cost_level")),
        cn_only=_as_bool(payload.get("cn_only")),
        notes=str(payload.get("notes") or "").strip(),
    )


def _parse_provider(payload: Dict[str, Any], index: int) -> Optional[CatalogProvider]:
    """解析单个 provider 条目。

    Args:
        payload: JSON 中的 provider 对象。
        index: 在数组中的位置（无显式 priority 时按序推算）。

    Returns:
        provider 定义；缺少 name 时返回 None。
    """

    name = str(payload.get("name") or "").strip().lower()
    if not name:
        return None
    extra = payload.get("extra_body")
    no_thinking = payload.get("no_thinking_body")
    return CatalogProvider(
        name=name,
        display_name=str(payload.get("display_name") or name).strip(),
        priority=_as_int(payload.get("priority"), (index + 1) * 10),
        sdk_backend=str(payload.get("sdk_backend") or "openai-compatible").strip(),
        base_url=str(payload.get("base_url") or "").strip(),
        default_model=str(payload.get("default_model") or "").strip(),
        fallback_models=_as_str_tuple(payload.get("fallback_models")),
        secret_name=str(payload.get("secret_name") or name).strip().lower(),
        env_api_key_name=str(payload.get("env_api_key_name") or "").strip(),
        is_local=_as_bool(payload.get("is_local")),
        extra_body=dict(extra) if isinstance(extra, dict) else {},
        no_thinking_body=dict(no_thinking) if isinstance(no_thinking, dict) else {},
        notes=str(payload.get("notes") or "").strip(),
    )


def parse_catalog(payload: Dict[str, Any], *, source_path: str = "") -> Catalog:
    """把已解析的 JSON 字典转成 :class:`Catalog`。

    与 :func:`load_catalog` 分离，便于测试直接喂入内存数据。

    Args:
        payload: 目录字典。
        source_path: 数据来源路径（用于排障）。

    Returns:
        Catalog 对象。

    Raises:
        CatalogError: 顶层结构不是对象，或模型/ provider 全部解析失败。
    """

    if not isinstance(payload, dict):
        raise CatalogError("目录顶层必须是 JSON 对象")

    warnings: List[str] = []

    providers: Dict[str, CatalogProvider] = {}
    for index, raw in enumerate(payload.get("providers") or []):
        if not isinstance(raw, dict):
            continue
        if _is_comment_only(raw):
            continue
        item = _parse_provider(raw, index)
        if item is None:
            warnings.append(f"providers[{index}] 缺少 name，已跳过")
            continue
        if item.name in providers:
            warnings.append(f"provider 重复定义: {item.name}（后者覆盖前者）")
        providers[item.name] = item

    models: Dict[str, CatalogModel] = {}
    for index, raw in enumerate(payload.get("models") or []):
        if not isinstance(raw, dict):
            continue
        # JSON 不允许注释，数据文件里用只含 $comment 的对象做分节标题，静默跳过。
        if _is_comment_only(raw):
            continue
        item = _parse_model(raw)
        if item is None:
            warnings.append(f"models[{index}] 缺少 id，已跳过")
            continue
        if item.id in models:
            warnings.append(f"模型重复定义: {item.id}（后者覆盖前者）")
        models[item.id] = item

    if not models:
        raise CatalogError("目录中没有任何有效模型条目")

    pools: Dict[str, Dict[str, str]] = {}
    for task_type, tiers in (payload.get("task_pools") or {}).items():
        if not isinstance(tiers, dict):
            continue
        pools[str(task_type)] = {
            str(tier): str(model).strip() for tier, model in tiers.items() if model
        }

    cross_block = payload.get("cross_vendor_fallbacks")
    if isinstance(cross_block, dict):
        cross = _as_str_tuple(cross_block.get("models"))
    else:
        cross = _as_str_tuple(cross_block)

    regions: Dict[str, str] = {}
    default_region = "cn-beijing"
    for region, spec in (payload.get("regions") or {}).items():
        if isinstance(spec, dict):
            regions[str(region)] = str(spec.get("base_url") or "").strip()
            if _as_bool(spec.get("default")):
                default_region = str(region)
        else:
            regions[str(region)] = str(spec).strip()

    vendor_rules: List[Tuple[str, Tuple[str, ...]]] = []
    for raw in payload.get("vendor_rules") or []:
        if isinstance(raw, dict) and raw.get("vendor"):
            vendor_rules.append(
                (str(raw["vendor"]).strip().lower(), _as_str_tuple(raw.get("prefixes")))
            )

    deprecated_raw = payload.get("deprecated_replacements")
    deprecated = {
        str(key): str(value)
        for key, value in (deprecated_raw or {}).items()
        if not str(key).startswith("$") and value
    }

    catalog = Catalog(
        schema_version=_as_int(payload.get("schema_version"), 1),
        catalog_version=str(payload.get("catalog_version") or "").strip(),
        updated_at=str(payload.get("updated_at") or "").strip(),
        source_path=source_path,
        providers=providers,
        models=models,
        task_pools=pools,
        cross_vendor_fallbacks=cross,
        deprecated_replacements=deprecated,
        cn_only_prefixes=_as_str_tuple(payload.get("cn_only_prefixes")),
        vendor_rules=tuple(vendor_rules),
        region_base_urls=regions,
        default_region=default_region,
        warnings=tuple(warnings),
    )
    # frozen dataclass：填充小写索引以支持大小写不敏感查找。
    object.__setattr__(
        catalog,
        "_lower_index",
        {model_id.lower(): model_id for model_id in models},
    )
    return catalog


def load_catalog(path: Optional[str | Path] = None, *, force: bool = False) -> Catalog:
    """加载目录（带进程内缓存）。

    Args:
        path: 数据文件路径；为空时用 :func:`default_catalog_path`。
        force: 为 True 时忽略缓存重新读取。

    Returns:
        Catalog 对象。

    Raises:
        CatalogError: 文件不存在、JSON 解析失败或结构非法。
    """

    target = Path(path).expanduser().resolve() if path else default_catalog_path()
    cache_key = str(target)
    with _LOCK:
        cached = _CACHE.get("catalog")
        if cached is not None and _CACHE.get("path") == cache_key and not force:
            return cached

    if not target.is_file():
        raise CatalogError(f"目录数据文件不存在: {target}")

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"目录数据文件 JSON 解析失败: {target}；{exc}") from exc
    except OSError as exc:
        raise CatalogError(f"目录数据文件读取失败: {target}；{exc}") from exc

    catalog = parse_catalog(payload, source_path=str(target))
    with _LOCK:
        _CACHE.update({"catalog": catalog, "path": cache_key, "error": ""})
    return catalog


def reload_catalog(path: Optional[str | Path] = None) -> Catalog:
    """强制重新加载目录（改完 JSON 后调用即生效）。

    Args:
        path: 数据文件路径；为空时沿用默认路径。

    Returns:
        Catalog 对象。

    Examples:
        >>> from autodokit.tools.atomic.llm.llm_catalog import reload_catalog
        >>> reload_catalog().catalog_version  # doctest: +SKIP
        '2026-09-15'
    """

    return load_catalog(path, force=True)


def try_load_catalog(path: Optional[str | Path] = None) -> Tuple[Optional[Catalog], str]:
    """尝试加载目录，失败时返回错误说明而不抛异常。

    供「数据文件优先、内置默认兜底」的调用方使用。

    Args:
        path: 数据文件路径。

    Returns:
        二元组 ``(catalog, error)``；成功时 error 为空串。
    """

    try:
        return load_catalog(path), ""
    except CatalogError as exc:
        return None, str(exc)


def catalog_info() -> Dict[str, Any]:
    """返回目录的概览信息（不含密钥，供排障与自检）。

    Returns:
        含 ``available`` / ``error`` / ``path`` / 版本与各类计数的字典。

    Examples:
        >>> info = catalog_info()
        >>> "available" in info
        True
    """

    catalog, error = try_load_catalog()
    if catalog is None:
        return {
            "available": False,
            "error": error,
            "path": str(default_catalog_path()),
            "fallback": "将退回内置默认目录",
        }

    active = [m for m in catalog.models.values() if m.is_active]
    return {
        "available": True,
        "error": "",
        "path": catalog.source_path,
        "schema_version": catalog.schema_version,
        "catalog_version": catalog.catalog_version,
        "updated_at": catalog.updated_at,
        "models_total": len(catalog.models),
        "models_active": len(active),
        "models_deprecated": len(catalog.models) - len(active),
        "providers": list(catalog.provider_priority()),
        "task_pools": {key: dict(value) for key, value in sorted(catalog.task_pools.items())},
        "cross_vendor_fallbacks": list(catalog.cross_vendor_fallbacks),
        "currencies": sorted(
            {item.pricing.currency for item in catalog.models.values() if item.pricing.currency}
        ),
        "warnings": list(catalog.warnings),
    }


# --------------------------------------------------------------------------
# 按需查询（用户据此选模型）
# --------------------------------------------------------------------------


def list_models(
    *,
    provider: Optional[str] = None,
    vendor: Optional[str] = None,
    status: Optional[str] = STATUS_ACTIVE,
    task_type: Optional[str] = None,
) -> List[CatalogModel]:
    """列出目录中的模型（按成本等级、再按 id 排序）。

    Args:
        provider: 仅返回归属该 provider 的模型。
        vendor: 仅返回该厂商的模型。
        status: 生命周期状态过滤；传 ``None`` 表示不过滤，传 ``"*"`` 表示全部。
        task_type: 仅返回适配该任务类型的模型。

    Returns:
        模型列表（按成本等级、再按 id 排序）。

    Examples:
        >>> [m.id for m in list_models(provider="deepseek")][:1]
        ['deepseek-flash']
    """

    catalog, _ = try_load_catalog()
    if catalog is None:
        return []
    found = _filter_models(
        catalog.models.values(),
        provider=provider,
        vendor=vendor,
        status=status,
        task_type=task_type,
    )
    found.sort(key=lambda m: (m.cost_level, m.id))
    return found


def find_models(
    *,
    task_type: Optional[str] = None,
    needs_vision: Optional[bool] = None,
    needs_thinking: Optional[bool] = None,
    needs_tool_calling: Optional[bool] = None,
    needs_json: Optional[bool] = None,
    needs_streaming: Optional[bool] = None,
    provider: Optional[str] = None,
    vendor: Optional[str] = None,
    status: Optional[str] = STATUS_ACTIVE,
    max_cost_level: Optional[int] = None,
    min_cost_level: Optional[int] = None,
    min_input_tokens: Optional[int] = None,
    currency: Optional[str] = None,
    verified_pricing_only: bool = False,
) -> List[CatalogModel]:
    """**按需筛选模型**——用户的“我要什么样的模型”入口。

    所有条件之间是 AND 关系；`None` 表示不限制。结果按
    ``(cost_level, id)`` 升序，便于从便宜到贵挑选。

    Args:
        task_type: 任务类型（vision / coding / long_text / math_reasoning / general）。
        needs_vision: 是否必须支持图像输入。
        needs_thinking: 是否必须支持思考模式。
        needs_tool_calling: 是否必须支持工具调用。
        needs_json: 是否必须支持结构化 JSON 输出。
        needs_streaming: 是否必须支持流式输出。
        provider: 归属 provider 过滤。
        vendor: 厂商过滤。
        status: 生命周期状态（默认只看 active；传 ``"*"`` 看全部）。
        max_cost_level: 成本等级上限。
        min_cost_level: 成本等级下限。
        min_input_tokens: 最小上下文长度。
        currency: 定价币种过滤（``CNY`` / ``USD``）。
        verified_pricing_only: 仅返回价格经人工核对的模型。

    Returns:
        命中条件的模型列表。

    Examples:
        >>> [m.id for m in find_models(needs_vision=True, max_cost_level=0)]
        []
        >>> [m.id for m in find_models(needs_json=True, max_cost_level=1) if m.vendor == "deepseek"]
        ['deepseek-flash', 'deepseek-v4-flash']
        >>> all(m.provider == "lmstudio" for m in find_models(provider="lmstudio"))
        True

    注：断言刻意用「性质」而非具体清单。目录是会演进的数据文件，
    把清单写进期望值会让本地模型一增改就误报失败；需要精确校验收录
    内容时，请用 ``tests/test_llm_catalog.py`` 的显式用例。
    """

    catalog, _ = try_load_catalog()
    if catalog is None:
        return []

    candidates = _filter_models(
        catalog.models.values(),
        provider=provider,
        vendor=vendor,
        status=status,
        task_type=task_type,
    )

    checks: List[Tuple[str, Optional[bool]]] = [
        ("vision", needs_vision),
        ("thinking", needs_thinking),
        ("tool_calling", needs_tool_calling),
        ("json_output", needs_json),
        ("streaming", needs_streaming),
    ]
    result: List[CatalogModel] = []
    for item in candidates:
        if any(
            required is not None
            and bool(getattr(item.capabilities, flag)) is not bool(required)
            for flag, required in checks
        ):
            continue
        if max_cost_level is not None and item.cost_level > max_cost_level:
            continue
        if min_cost_level is not None and item.cost_level < min_cost_level:
            continue
        if min_input_tokens is not None and item.max_input_tokens < min_input_tokens:
            continue
        if currency is not None and item.pricing.currency.upper() != currency.upper():
            continue
        if verified_pricing_only and not item.pricing.verified:
            continue
        result.append(item)

    result.sort(key=lambda m: (m.cost_level, m.id))
    return result


def _filter_models(
    models: Iterable[CatalogModel],
    *,
    provider: Optional[str],
    vendor: Optional[str],
    status: Optional[str],
    task_type: Optional[str],
) -> List[CatalogModel]:
    """执行字段级过滤（供 list/find 共用）。

    Args:
        models: 待过滤模型。
        provider: provider 过滤。
        vendor: 厂商过滤。
        status: 状态过滤。
        task_type: 任务类型过滤。

    Returns:
        过滤后的列表（不排序）。
    """

    want_provider = str(provider).strip().lower() if provider else ""
    want_vendor = str(vendor).strip().lower() if vendor else ""
    want_status = str(status).strip().lower() if status is not None else ""

    result: List[CatalogModel] = []
    for item in models:
        if want_status and want_status != "*" and item.status != want_status:
            continue
        if want_provider and item.provider != want_provider:
            continue
        if want_vendor and item.vendor != want_vendor:
            continue
        if task_type and task_type not in item.task_types:
            continue
        result.append(item)
    return result


def get_model(model_id: str) -> Optional[CatalogModel]:
    """按 id 取模型（不区分大小写），不存在时返回 None。

    Args:
        model_id: 模型 id。

    Returns:
        模型条目或 None。

    Examples:
        >>> get_model("deepseek-flash").display_name.startswith("DeepSeek")
        True
        >>> get_model("不存在的模型") is None
        True
    """

    catalog, _ = try_load_catalog()
    if catalog is None or not catalog.has_model(model_id):
        return None
    return catalog.get_model(model_id)


def describe_model(model_id: str) -> Dict[str, Any]:
    """输出单个模型的**完整说明**（参数 / 能力 / 价格），含可读文本。

    Args:
        model_id: 模型 id。

    Returns:
        含 ``found`` / 各字段 与 ``text`` 的字典；未找到时 ``found`` 为 False。
    """

    item = get_model(model_id)
    if item is None:
        return {"found": False, "id": model_id, "error": "目录中不存在该模型"}

    caps = item.capabilities
    enabled = [
        label
        for label, flag in (
            ("思考", caps.thinking),
            ("视觉", caps.vision),
            ("工具调用", caps.tool_calling),
            ("JSON", caps.json_output),
            ("流式", caps.streaming),
        )
        if flag
    ]
    pricing_note = "已核对" if item.pricing.verified else "估算值（未核对）"
    lines = [
        f"{item.id} — {item.display_name}",
        f"  厂商 / Provider : {item.vendor or '-'} / {item.provider or '-'}",
        f"  状态            : {item.status}"
        + (f"（替代：{item.replacement}）" if item.replacement else ""),
        f"  适配任务        : {', '.join(item.task_types) or '-'}",
        f"  能力            : {', '.join(enabled) or '无'}"
        + ("（仅中国内地）" if item.cn_only else ""),
        f"  上限            : 输入 {item.max_input_tokens:,} / 输出 {item.max_output_tokens:,} tokens",
        f"  价格            : 输入 {item.pricing.input} / 输出 {item.pricing.output} "
        f"{item.pricing.currency}（每百万 token；{pricing_note}）",
        f"  成本等级        : {item.cost_level}",
    ]
    if item.notes:
        lines.append(f"  备注            : {item.notes}")

    return {
        "found": True,
        "id": item.id,
        "display_name": item.display_name,
        "vendor": item.vendor,
        "provider": item.provider,
        "family": item.family,
        "status": item.status,
        "replacement": item.replacement,
        "task_types": list(item.task_types),
        "capabilities": {
            "thinking": caps.thinking,
            "vision": caps.vision,
            "tool_calling": caps.tool_calling,
            "json_output": caps.json_output,
            "streaming": caps.streaming,
        },
        "limits": dict(item.limits),
        "pricing": {
            "currency": item.pricing.currency,
            "unit": item.pricing.unit,
            "input": item.pricing.input,
            "output": item.pricing.output,
            "input_offpeak": item.pricing.input_offpeak,
            "output_offpeak": item.pricing.output_offpeak,
            "source": item.pricing.source,
            "verified_at": item.pricing.verified_at,
            "verified": item.pricing.verified,
        },
        "cost_level": item.cost_level,
        "cn_only": item.cn_only,
        "notes": item.notes,
        "text": "\n".join(lines),
    }


def format_model_table(models: Sequence[CatalogModel], *, limit: int = 50) -> str:
    """把模型列表渲染成可读表格（供 CLI 与人工挑选）。

    Args:
        models: 模型列表。
        limit: 最多渲染的行数。

    Returns:
        文本表格。

    Examples:
        >>> print(format_model_table(find_models(provider="deepseek")))  # doctest: +SKIP
    """

    header = (
        f"{'模型':<26}{'厂商':<10}{'成本':>4}  {'能力':<22}"
        f"{'输入上限':>10}  {'价格(输入/输出)':<20}"
    )
    lines = [header, "-" * len(header)]
    for item in list(models)[:limit]:
        caps = item.capabilities
        flags = "".join(
            letter
            for letter, flag in (
                ("思", caps.thinking),
                ("视", caps.vision),
                ("工", caps.tool_calling),
                ("J", caps.json_output),
            )
            if flag
        )
        price = f"{item.pricing.input}/{item.pricing.output} {item.pricing.currency}"
        lines.append(
            f"{item.id:<26}{item.vendor:<10}{item.cost_level:>4}  {flags:<22}"
            f"{item.max_input_tokens:>10,}  {price:<20}"
            + ("" if item.is_active else "  [已下线]")
        )
    if len(models) > limit:
        lines.append(f"... 另有 {len(models) - limit} 个，已省略")
    return "\n".join(lines)


def provider_priority() -> Tuple[str, ...]:
    """返回 auto 路由的 provider 顺序（按优先级升序）。

    Returns:
        provider 名元组；目录不可用时返回空元组。

    Examples:
        >>> list(provider_priority())[:1]
        ['deepseek']
    """

    catalog, _ = try_load_catalog()
    return catalog.provider_priority() if catalog is not None else ()
