"""autodokit 本地事务运行时 API。

本模块用于在未安装 autodo-engine 时，依然支持最小可用的事务直调能力。
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
from types import ModuleType
from typing import Any

from autodokit.path_compat import resolve_portable_path
from autodokit.tools.config_contract_utils import normalize_to_legacy_contract
from autodokit.tools import load_json_or_py, resolve_paths_to_absolute
from autodokit.tools.atomic.task_aok.postprocess_runtime import run_unified_postprocess
from autodokit.tools.time_utils import now_iso


def _build_affair_uid_alias_map() -> dict[str, str]:
    """构建 ar_Axxx 命名层到真实模块路径的别名映射。"""

    try:
        from autodokit.tools.affair_entry_registry_tools import MAINLINE_AFFAIR_ENTRY_MAP
    except Exception:
        return {}

    alias_map: dict[str, str] = {}
    for node_code, base in MAINLINE_AFFAIR_ENTRY_MAP.items():
        affair_uid = str(base.get("affair_uid") or "").strip()
        module_name = str(base.get("module") or "").strip()
        if not affair_uid or not module_name:
            continue
        alias_map[affair_uid] = module_name
        if not affair_uid.startswith("ar_A"):
            alias_map[f"ar_{node_code}_{affair_uid}"] = module_name
    return alias_map


def _get_runtime_context_module() -> Any:
    """按需加载运行时上下文模块。

    Returns:
        运行时上下文模块；若不可用则返回 None。
    """

    try:
        from autodoengine.utils import runtime_context as runtime_context_module
    except Exception:
        return None
    return runtime_context_module


@contextmanager
def _set_runtime_context(
    *,
    global_config_path: Path | None,
    current_affair_uid: str,
    current_affair_config_path: Path,
):
    """临时注入运行时上下文并在退出时恢复。"""

    runtime_context_module = _get_runtime_context_module()
    if runtime_context_module is None:
        yield
        return

    previous_context = runtime_context_module.get_runtime_context()
    runtime_context_module.set_runtime_context(
        global_config_path=global_config_path,
        current_affair_uid=current_affair_uid,
        current_affair_config_path=current_affair_config_path,
    )
    try:
        yield
    finally:
        runtime_context_module.set_runtime_context(
            global_config_path=previous_context.global_config_path,
            current_affair_uid=previous_context.current_affair_uid,
            current_affair_config_path=previous_context.current_affair_config_path,
        )


def _runtime_root(workspace_root: str | Path | None) -> Path:
    return _resolve_workspace_root(workspace_root) / ".autodokit"


def _affair_registry_path(workspace_root: str | Path | None) -> Path:
    return _runtime_root(workspace_root) / "affair_registry.json"


def _graph_registry_path(workspace_root: str | Path | None) -> Path:
    return _runtime_root(workspace_root) / "graph_registry.json"


def _sanitize_uid(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "_", str(text or "").strip())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "user_affair"


def _next_available_name(base_name: str, existing: set[str]) -> str:
    if base_name not in existing:
        return base_name
    index = 1
    while True:
        candidate = f"{base_name}_v{index}"
        if candidate not in existing:
            return candidate
        index += 1


def _load_registry(path: Path, default_payload: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default_payload)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return dict(default_payload)
    normalized = normalize_to_legacy_contract(payload)
    return normalized if isinstance(normalized, dict) else dict(default_payload)


def _save_registry(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_workspace_root(workspace_root: str | Path | None) -> Path:
    """解析工作区根目录。"""

    if workspace_root is None:
        return Path.cwd().resolve()
    return resolve_portable_path(workspace_root, base=Path.cwd())


def _resolve_public_argument(*pairs: tuple[str, Any], required: bool = False) -> Any:
    """解析公开 API 的中英文别名形参。

    Args:
        *pairs: `(参数名, 参数值)` 对。
        required: 是否要求至少提供一个非空值。

    Returns:
        首个非空参数值。

    Raises:
        ValueError: 当中英文别名同时传入且值不一致时抛出。
    """

    selected_name = ""
    selected_value: Any = None
    has_value = False

    for name, value in pairs:
        if value is None:
            continue
        if has_value and value != selected_value:
            raise ValueError(f"{selected_name} 与 {name} 不能同时传入不同值")
        if not has_value:
            selected_name = name
            selected_value = value
            has_value = True

    if required and not has_value:
        names = " / ".join(name for name, _ in pairs)
        raise ValueError(f"{names} 不能为空")
    return selected_value


def import_affair_module(
    事务唯一标识: str | None = None,
    工作区根路径: str | Path | None = None,
    *,
    affair_uid: str | None = None,
    workspace_root: str | Path | None = None,
) -> ModuleType:
    """按事务 UID 导入事务模块。"""

    uid = str(
        _resolve_public_argument(("事务唯一标识", 事务唯一标识), ("affair_uid", affair_uid), required=True)
        or ""
    ).strip()
    if not uid:
        raise ValueError("affair_uid 不能为空")

    alias_module_name = _build_affair_uid_alias_map().get(uid)
    if alias_module_name:
        return importlib.import_module(alias_module_name)

    official_module_name = f"autodokit.affairs.{uid}.affair"
    try:
        return importlib.import_module(official_module_name)
    except ModuleNotFoundError:
        pass

    root = _resolve_workspace_root(
        _resolve_public_argument(("工作区根路径", 工作区根路径), ("workspace_root", workspace_root))
    )
    user_module_path = root / ".autodokit" / "affairs" / uid / "affair.py"
    if not user_module_path.exists():
        raise ModuleNotFoundError(f"未找到事务模块: {uid}")

    spec = importlib.util.spec_from_file_location(f"autodokit.user_affairs.{uid}.affair", user_module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载事务模块: {user_module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_affair_config(
    配置: dict[str, Any] | None = None,
    *,
    config: dict[str, Any] | None = None,
    配置路径: str | Path | None = None,
    config_path: str | Path | None = None,
    工作区根路径: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """准备事务配置，统一绝对路径。"""

    resolved_config = _resolve_public_argument(("配置", 配置), ("config", config))
    resolved_config_path = _resolve_public_argument(("配置路径", 配置路径), ("config_path", config_path))
    resolved_workspace_root = _resolve_public_argument(("工作区根路径", 工作区根路径), ("workspace_root", workspace_root))

    if resolved_config is not None and resolved_config_path is not None:
        raise ValueError("config 与 config_path 只能传入一个")

    if resolved_config_path is not None:
        raw_config = load_json_or_py(resolved_config_path)
        if not isinstance(raw_config, dict):
            raise ValueError("配置文件必须解析为字典")
    else:
        raw_config = normalize_to_legacy_contract(dict(resolved_config or {}))

    root = _resolve_workspace_root(resolved_workspace_root)
    return resolve_paths_to_absolute(raw_config, workspace_root=root)


def run_affair(
    事务唯一标识: str | None = None,
    *,
    affair_uid: str | None = None,
    配置: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    配置路径: str | Path | None = None,
    config_path: str | Path | None = None,
    工作区根路径: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> list[Path]:
    """执行事务并返回产物路径。

    该入口会在事务执行结束后执行统一后处理。
    对于已通过装饰器托管后处理的事务，不重复执行。
    """

    resolved_affair_uid = _resolve_public_argument(("事务唯一标识", 事务唯一标识), ("affair_uid", affair_uid), required=True)
    resolved_config = _resolve_public_argument(("配置", 配置), ("config", config))
    resolved_config_path = _resolve_public_argument(("配置路径", 配置路径), ("config_path", config_path))
    resolved_workspace_root = _resolve_public_argument(("工作区根路径", 工作区根路径), ("workspace_root", workspace_root))

    prepared = prepare_affair_config(
        配置=resolved_config,
        配置路径=resolved_config_path,
        工作区根路径=resolved_workspace_root,
    )
    module = import_affair_module(事务唯一标识=resolved_affair_uid, 工作区根路径=resolved_workspace_root)
    execute = getattr(module, "execute", None)
    if not callable(execute):
        raise AttributeError(f"事务模块缺少 execute(config_path) 入口: {module.__name__}")

    root = _resolve_workspace_root(resolved_workspace_root)
    global_config_path = root / "config" / "config.json"
    if not global_config_path.exists():
        global_config_path = None
    temp_file_path: Path | None = None

    if resolved_config_path is not None:
        resolved_config_path_obj = resolve_portable_path(resolved_config_path, base=root)
    else:
        root.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8", dir=str(root)) as temp_file:
            json.dump(prepared, temp_file, ensure_ascii=False, indent=2)
            temp_file_path = Path(temp_file.name)
        resolved_config_path_obj = temp_file_path

    started_at = now_iso()
    execute_error: BaseException | None = None
    outputs: Any = []
    try:
        with _set_runtime_context(
            global_config_path=global_config_path,
            current_affair_uid=str(resolved_affair_uid),
            current_affair_config_path=resolved_config_path_obj,
        ):
            try:
                outputs = execute(resolved_config_path_obj, workspace_root=root)
            except TypeError:
                outputs = execute(resolved_config_path_obj)
    except BaseException as exc:  # noqa: BLE001
        execute_error = exc
        raise
    finally:
        postprocess_managed = bool(getattr(execute, "_aok_postprocess_managed", False))
        if not postprocess_managed:
            run_unified_postprocess(
                config_path=resolved_config_path_obj,
                node_code=str(resolved_affair_uid),
                execute_result=outputs,
                execute_error=execute_error,
                workspace_root=root,
                started_at=started_at,
                ended_at=now_iso(),
            )
        if temp_file_path is not None and temp_file_path.exists():
            temp_file_path.unlink(missing_ok=True)

    return [Path(path) for path in outputs]


def import_user_affair(
    源文件: str | Path | None = None,
    *,
    source: str | Path | None = None,
    事务唯一标识: str | None = None,
    affair_uid: str | None = None,
    工作区根路径: str | Path | None = None,
    workspace_root: str | Path | None = None,
    配置模板: dict[str, Any] | None = None,
    config_template: dict[str, Any] | None = None,
    文档标题: str | None = None,
    doc_title: str | None = None,
    是否覆盖: bool | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """导入用户事务为标准三件套并更新注册表。"""

    resolved_source = _resolve_public_argument(("源文件", 源文件), ("source", source), required=True)
    resolved_affair_uid = _resolve_public_argument(("事务唯一标识", 事务唯一标识), ("affair_uid", affair_uid))
    resolved_workspace_root = _resolve_public_argument(("工作区根路径", 工作区根路径), ("workspace_root", workspace_root))
    resolved_config_template = _resolve_public_argument(("配置模板", 配置模板), ("config_template", config_template))
    resolved_doc_title = _resolve_public_argument(("文档标题", 文档标题), ("doc_title", doc_title))
    resolved_overwrite = _resolve_public_argument(("是否覆盖", 是否覆盖), ("overwrite", overwrite))
    runtime = bootstrap_runtime(工作区根路径=resolved_workspace_root)
    source_path = resolve_portable_path(resolved_source, base=Path(runtime["workspace_root"]))
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"source 不存在或不是文件: {source_path}")

    desired_uid = _sanitize_uid(resolved_affair_uid or source_path.stem)
    affairs_root = Path(runtime["affairs_root"])
    existing = {p.name for p in affairs_root.iterdir() if p.is_dir()}
    final_uid = desired_uid if bool(resolved_overwrite) else _next_available_name(desired_uid, existing)

    target_dir = affairs_root / final_uid
    target_dir.mkdir(parents=True, exist_ok=True)

    target_affair = target_dir / "affair.py"
    if target_affair.exists() and not bool(resolved_overwrite):
        raise FileExistsError(f"事务已存在且 overwrite=False: {target_affair}")

    shutil.copy2(source_path, target_affair)

    config_payload = dict(resolved_config_template or {})
    (target_dir / "affair.json").write_text(json.dumps(config_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    doc_name = resolved_doc_title or final_uid
    (target_dir / "affair.md").write_text(
        "\n".join(
            [
                f"# {doc_name}",
                "",
                "## 概述",
                "用户导入事务。",
                "",
                "## 配置",
                "见同目录 affair.json。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    registry_path = Path(runtime["affair_registry_path"])
    default_registry = {
        "schema_version": "2026-03-29",
        "generated_at": "",
        "records": [],
        "stats": {"aok_graph": 0, "aok_business": 0, "user_business": 0, "invalid": 0},
        "dirty_report": {"error_count": 0, "warning_count": 0, "errors": [], "warnings": []},
    }
    registry = _load_registry(registry_path, default_registry)
    records = [item for item in registry.get("records", []) if item.get("affair_uid") != final_uid]
    records.append(
        {
            "affair_uid": final_uid,
            "domain": "user_business",
            "runner": {"module": f"autodokit.user_affairs.{final_uid}.affair", "callable": "execute"},
            "source_py_path": str(target_affair),
            "params_json_path": str(target_dir / "affair.json"),
            "doc_md_path": str(target_dir / "affair.md"),
        }
    )
    registry["records"] = records
    registry["generated_at"] = now_iso()
    stats = registry.get("stats", {})
    stats["user_business"] = sum(1 for item in records if item.get("domain") == "user_business")
    registry["stats"] = stats
    _save_registry(registry_path, registry)

    return {
        "status": "PASS",
        "affair_uid": final_uid,
        "affair_dir": str(target_dir),
        "affair_py": str(target_affair),
        "affair_json": str(target_dir / "affair.json"),
        "affair_md": str(target_dir / "affair.md"),
        "affair_registry": str(registry_path),
    }


def bootstrap_runtime(工作区根路径: str | Path | None = None, *, workspace_root: str | Path | None = None) -> dict[str, Any]:
    """初始化本地运行时目录与注册表。"""

    root = _resolve_workspace_root(
        _resolve_public_argument(("工作区根路径", 工作区根路径), ("workspace_root", workspace_root))
    )
    runtime = _runtime_root(root)
    affairs_root = runtime / "affairs"
    graphs_root = runtime / "graphs"

    runtime.mkdir(parents=True, exist_ok=True)
    affairs_root.mkdir(parents=True, exist_ok=True)
    graphs_root.mkdir(parents=True, exist_ok=True)

    affair_registry = _affair_registry_path(root)
    graph_registry = _graph_registry_path(root)

    if not affair_registry.exists():
        _save_registry(
            affair_registry,
            {
                "schema_version": "2026-03-29",
                "generated_at": "",
                "records": [],
                "stats": {"aok_graph": 0, "aok_business": 0, "user_business": 0, "invalid": 0},
                "dirty_report": {"error_count": 0, "warning_count": 0, "errors": [], "warnings": []},
            },
        )

    if not graph_registry.exists():
        _save_registry(
            graph_registry,
            {
                "schema_version": "2026-03-29",
                "generated_at": "",
                "records": [],
            },
        )

    return {
        "status": "PASS",
        "workspace_root": str(root),
        "runtime_root": str(runtime),
        "affairs_root": str(affairs_root),
        "graphs_root": str(graphs_root),
        "affair_registry_path": str(affair_registry),
        "graph_registry_path": str(graph_registry),
    }


def create_task(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("create_task 暂未在 autodokit 内置运行时实现")


def run_task_step(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("run_task_step 暂未在 autodokit 内置运行时实现")


def run_task_until_terminal(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("run_task_until_terminal 暂未在 autodokit 内置运行时实现")


def run_task_until_wait(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("run_task_until_wait 暂未在 autodokit 内置运行时实现")


def load_graph(
    流程图唯一标识: str | None = None,
    *,
    graph_uid: str | None = None,
    工作区根路径: str | Path | None = None,
    workspace_root: str | Path | None = None,
    流程图路径: str | Path | None = None,
    graph_path: str | Path | None = None,
) -> dict[str, Any]:
    """加载图配置。"""

    resolved_graph_path = _resolve_public_argument(("流程图路径", 流程图路径), ("graph_path", graph_path))
    resolved_graph_uid = _resolve_public_argument(("流程图唯一标识", 流程图唯一标识), ("graph_uid", graph_uid))
    resolved_workspace_root = _resolve_public_argument(("工作区根路径", 工作区根路径), ("workspace_root", workspace_root))

    if resolved_graph_path is not None:
        data = load_json_or_py(resolved_graph_path)
        if not isinstance(data, dict):
            raise ValueError("graph_path 解析结果必须是字典")
        return data

    uid = str(resolved_graph_uid or "").strip()
    if not uid:
        raise ValueError("graph_uid 与 graph_path 不能同时为空")

    runtime = bootstrap_runtime(工作区根路径=resolved_workspace_root)
    registry = _load_registry(Path(runtime["graph_registry_path"]), {"records": []})
    records = registry.get("records", [])
    record = next((item for item in records if str(item.get("graph_uid")) == uid), None)
    if record is None:
        raise KeyError(f"未找到图配置: {uid}")

    target = resolve_portable_path(str(record.get("graph_path") or ""), base=Path(runtime["workspace_root"]))
    if not target.exists():
        raise FileNotFoundError(f"图配置文件不存在: {target}")
    data = load_json_or_py(target)
    if not isinstance(data, dict):
        raise ValueError("图配置必须解析为字典")
    return data


def register_graph(
    流程图唯一标识: str | None = None,
    *,
    graph_uid: str | None = None,
    流程图: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    流程图路径: str | Path | None = None,
    graph_path: str | Path | None = None,
    工作区根路径: str | Path | None = None,
    workspace_root: str | Path | None = None,
    是否覆盖: bool | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """注册图配置到本地运行时。"""

    resolved_graph_uid = _resolve_public_argument(("流程图唯一标识", 流程图唯一标识), ("graph_uid", graph_uid), required=True)
    resolved_graph = _resolve_public_argument(("流程图", 流程图), ("graph", graph))
    resolved_graph_path = _resolve_public_argument(("流程图路径", 流程图路径), ("graph_path", graph_path))
    resolved_workspace_root = _resolve_public_argument(("工作区根路径", 工作区根路径), ("workspace_root", workspace_root))
    resolved_overwrite = _resolve_public_argument(("是否覆盖", 是否覆盖), ("overwrite", overwrite))

    if resolved_graph is None and resolved_graph_path is None:
        raise ValueError("graph 与 graph_path 至少传入一个")
    if resolved_graph is not None and resolved_graph_path is not None:
        raise ValueError("graph 与 graph_path 只能传入一个")

    runtime = bootstrap_runtime(工作区根路径=resolved_workspace_root)
    uid_seed = _sanitize_uid(str(resolved_graph_uid))

    registry_path = Path(runtime["graph_registry_path"])
    registry = _load_registry(registry_path, {"schema_version": "2026-03-29", "generated_at": "", "records": []})
    records: list[dict[str, Any]] = list(registry.get("records", []))
    existing = {str(item.get("graph_uid")) for item in records}
    final_uid = uid_seed if bool(resolved_overwrite) else _next_available_name(uid_seed, existing)

    graphs_root = Path(runtime["graphs_root"])
    target_path = graphs_root / f"{final_uid}.json"

    if resolved_graph_path is not None:
        payload = load_json_or_py(resolved_graph_path)
        if not isinstance(payload, dict):
            raise ValueError("graph_path 解析结果必须是字典")
    else:
        payload = dict(resolved_graph or {})

    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    filtered = [item for item in records if str(item.get("graph_uid")) != final_uid]
    filtered.append({"graph_uid": final_uid, "graph_path": str(target_path)})
    registry["records"] = filtered
    _save_registry(registry_path, registry)

    return {
        "status": "PASS",
        "graph_uid": final_uid,
        "graph_path": str(target_path),
        "graph_registry": str(registry_path),
    }
