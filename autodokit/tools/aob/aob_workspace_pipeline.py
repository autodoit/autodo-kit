"""AOB 办公区转换编译前分析与报告。

本模块在现有 AOC workspace-convert 内核之上补一层：

1. 统一解析源/目标办公区目录；
2. 生成可落盘的 canonical AOL dump；
3. 生成目标引擎 capability 校验与 downgrade 报告；
4. 复用既有 AOC 编译器执行实际写入。
"""

from __future__ import annotations

import json
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from autodokit.tools.atomic.aob_runtime.aoc_tool import (
    从引擎办公区构建_aol,
    收集_opencode阻断错误,
    校验_aol,
    编译_aol到引擎办公区,
    读取引擎办公区目录名,
)
from autodokit.tools.atomic.aob_runtime.workspace_profile_registry import 解析工作区目标配置


支持引擎集合 = {"opencode", "claude", "copilot", "gemini", "codex"}

能力分层标签: dict[str, str] = {
    "L1": "基础通用层",
    "L2": "扩展能力层",
    "L3": "引擎逃生口",
}

分层能力矩阵: dict[str, dict[str, dict[str, str]]] = {
    "opencode": {
        "L1": {
            "project_instruction": "full",
            "rules": "full",
            "skills": "full",
            "agents": "full",
            "commands": "full",
        },
        "L2": {
            "hooks": "partial",
            "mcp": "full",
            "settings": "partial",
            "policies": "full",
        },
        "L3": {
            "modes": "full",
            "plugins": "full",
            "tools": "full",
            "themes": "full",
            "plans": "full",
            "engine_overrides": "partial",
        },
    },
    "claude": {
        "L1": {
            "project_instruction": "full",
            "rules": "full",
            "skills": "full",
            "agents": "full",
            "commands": "full",
        },
        "L2": {
            "hooks": "full",
            "mcp": "full",
            "settings": "partial",
            "policies": "partial",
        },
        "L3": {
            "modes": "partial",
            "plugins": "partial",
            "tools": "partial",
            "themes": "partial",
            "plans": "partial",
            "engine_overrides": "partial",
        },
    },
    "copilot": {
        "L1": {
            "project_instruction": "full",
            "rules": "full",
            "skills": "full",
            "agents": "full",
            "commands": "partial",
        },
        "L2": {
            "hooks": "partial",
            "mcp": "partial",
            "settings": "partial",
            "policies": "partial",
        },
        "L3": {
            "modes": "partial",
            "plugins": "partial",
            "tools": "partial",
            "themes": "partial",
            "plans": "partial",
            "engine_overrides": "partial",
        },
    },
    "gemini": {
        "L1": {
            "project_instruction": "full",
            "rules": "partial",
            "skills": "full",
            "agents": "full",
            "commands": "partial",
        },
        "L2": {
            "hooks": "full",
            "mcp": "full",
            "settings": "full",
            "policies": "partial",
        },
        "L3": {
            "modes": "partial",
            "plugins": "partial",
            "tools": "partial",
            "themes": "partial",
            "plans": "partial",
            "engine_overrides": "partial",
        },
    },
    "codex": {
        "L1": {
            "project_instruction": "full",
            "rules": "partial",
            "skills": "full",
            "agents": "partial",
            "commands": "partial",
        },
        "L2": {
            "hooks": "partial",
            "mcp": "full",
            "settings": "partial",
            "policies": "full",
        },
        "L3": {
            "modes": "partial",
            "plugins": "partial",
            "tools": "partial",
            "themes": "partial",
            "plans": "partial",
            "engine_overrides": "partial",
        },
    },
}


def _normalize_asset_path(path_text: str) -> str:
    """标准化附加载体路径。"""

    return str(path_text or "").replace("\\", "/").strip("/").strip()


def _collect_asset_paths(aol: Any) -> list[str]:
    """收集 AOL 附加载体路径。"""

    assets = list(getattr(aol, "extra_assets", [])) + list(getattr(aol, "hooks", []))
    return [_normalize_asset_path(asset.relative_path) for asset in assets]


def _has_asset_prefix(asset_paths: list[str], prefix: str) -> bool:
    """判断是否存在指定前缀的附加载体。"""

    normalized_prefix = _normalize_asset_path(prefix)
    return any(path == normalized_prefix or path.startswith(f"{normalized_prefix}/") for path in asset_paths)


def _resolve_source_config_paths(*, project_root: Path, source_workspace_dir: Path, source_engine: str) -> list[Path]:
    """解析源办公区配置文件候选路径。"""

    candidates: list[Path] = [source_workspace_dir / "autodo.engine.config.json"]
    if source_engine == "opencode":
        candidates.insert(0, project_root / "opencode.json")
    elif source_engine == "claude":
        candidates.insert(0, source_workspace_dir / "settings.json")
        candidates.append(project_root / ".mcp.json")
    elif source_engine == "gemini":
        candidates.insert(0, source_workspace_dir / "settings.json")
    elif source_engine == "codex":
        candidates.insert(0, source_workspace_dir / "config.json")
        candidates.append(source_workspace_dir / "config.toml")

    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


def _load_source_configs(*, config_paths: list[Path]) -> tuple[list[str], list[dict[str, Any]]]:
    """读取存在的源配置 JSON。"""

    existing_paths: list[str] = []
    configs: list[dict[str, Any]] = []
    for path in config_paths:
        if not path.exists() or not path.is_file():
            continue
        existing_paths.append(str(path))
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix.lower() == ".json":
                payload = json.loads(text)
            elif path.suffix.lower() == ".toml":
                payload = tomllib.loads(text)
            else:
                continue
        except Exception:
            continue
        if isinstance(payload, dict):
            configs.append(payload)
    return existing_paths, configs


def _contains_any_key(payload: Any, candidate_keys: set[str]) -> bool:
    """递归检查配置中是否包含指定键。"""

    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key) in candidate_keys:
                if isinstance(value, (dict, list, str)):
                    if value:
                        return True
                elif value is not None:
                    return True
            if _contains_any_key(value, candidate_keys):
                return True
    elif isinstance(payload, list):
        for item in payload:
            if _contains_any_key(item, candidate_keys):
                return True
    return False


def _has_nontrivial_engine_overrides(aol: Any, source_engine: str) -> bool:
    """判断是否存在超出 sourcePath/sourceName 的引擎覆写。"""

    if getattr(aol, "engine_native", None):
        return True

    passthrough_keys = {"sourcePath", "sourceName"}
    for agent in list(aol.agents):
        overrides = dict(agent.engine_overrides)
        for engine_id, payload in overrides.items():
            if engine_id != source_engine:
                return True
            if set(payload.keys()) - passthrough_keys:
                return True
    return False


def _requested_capabilities(
    *,
    aol: Any,
    project_root: Path,
    source_workspace_dir: Path,
    source_engine: str,
) -> tuple[dict[str, dict[str, bool]], dict[str, Any]]:
    """根据 AOL 内容与源配置推导本次转换请求的分层能力面。"""

    asset_paths = _collect_asset_paths(aol)
    source_config_paths = _resolve_source_config_paths(
        project_root=project_root,
        source_workspace_dir=source_workspace_dir,
        source_engine=source_engine,
    )
    existing_config_paths, source_configs = _load_source_configs(config_paths=source_config_paths)
    requested = {
        "L1": {
            "project_instruction": bool((aol.project_instruction or "").strip() or list(aol.instructions)),
            "rules": bool(list(aol.rules)),
            "skills": bool(list(aol.skills)),
            "agents": bool(list(aol.agents)),
            "commands": bool(list(aol.commands)),
        },
        "L2": {
            "hooks": bool(list(getattr(aol, "hooks", []))) or _has_asset_prefix(asset_paths, "hooks"),
            "mcp": bool(getattr(aol, "mcp_servers", {})) or _contains_any_key(source_configs, {"mcp", "mcpServers", "mcp_servers"}),
            "settings": bool(getattr(aol, "settings", {})) or bool(existing_config_paths),
            "policies": bool(getattr(aol, "policies", {}))
            or _contains_any_key(
                source_configs,
                {"permission", "permissions", "approval", "approval_policy", "sandbox", "sandbox_mode", "security"},
            ),
        },
        "L3": {
            "modes": _has_asset_prefix(asset_paths, "modes"),
            "plugins": _has_asset_prefix(asset_paths, "plugins"),
            "tools": _has_asset_prefix(asset_paths, "tools"),
            "themes": _has_asset_prefix(asset_paths, "themes"),
            "plans": _has_asset_prefix(asset_paths, "plans"),
            "engine_overrides": _has_nontrivial_engine_overrides(aol, source_engine),
        },
    }
    observations = {
        "source_config_paths": existing_config_paths,
        "asset_prefix_counts": {
            "hooks": sum(1 for path in asset_paths if path.startswith("hooks/")),
            "modes": sum(1 for path in asset_paths if path.startswith("modes/")),
            "plugins": sum(1 for path in asset_paths if path.startswith("plugins/")),
            "tools": sum(1 for path in asset_paths if path.startswith("tools/")),
            "themes": sum(1 for path in asset_paths if path.startswith("themes/")),
            "plans": sum(1 for path in asset_paths if path.startswith("plans/")),
        },
        "canonical_field_counts": {
            "hooks": len(list(getattr(aol, "hooks", []))),
            "mcp_servers": len(dict(getattr(aol, "mcp_servers", {}))),
            "settings": len(dict(getattr(aol, "settings", {}))),
            "policies": len(dict(getattr(aol, "policies", {}))),
            "engine_native": len(dict(getattr(aol, "engine_native", {}))),
        },
    }
    return requested, observations


def _build_capability_report(
    *,
    aol: Any,
    project_root: Path,
    source_workspace_dir: Path,
    source_engine: str,
    target_engine: str,
) -> dict[str, Any]:
    """构建目标引擎能力报告。

    Args:
        aol: AOL 对象。
        project_root: 项目根目录。
        source_workspace_dir: 源办公区目录。
        source_engine: 源引擎。
        target_engine: 目标引擎。

    Returns:
        dict[str, Any]: 能力报告。
    """

    requested, observations = _requested_capabilities(
        aol=aol,
        project_root=project_root,
        source_workspace_dir=source_workspace_dir,
        source_engine=source_engine,
    )
    support_map = 分层能力矩阵[target_engine]
    flat_items: list[dict[str, Any]] = []
    layers: list[dict[str, Any]] = []
    downgraded_requested = 0
    unsupported_requested = 0
    requested_by_layer: dict[str, int] = {}

    for layer_id, capability_flags in requested.items():
        layer_items: list[dict[str, Any]] = []
        layer_requested = 0
        layer_downgraded = 0
        layer_unsupported = 0
        layer_support_map = support_map.get(layer_id, {})
        for capability_name, requested_flag in capability_flags.items():
            support = layer_support_map.get(capability_name, "unsupported")
            effective = "kept"
            if requested_flag and support == "partial":
                effective = "downgraded"
                downgraded_requested += 1
                layer_downgraded += 1
            elif requested_flag and support == "unsupported":
                effective = "unsupported"
                unsupported_requested += 1
                layer_unsupported += 1
            if requested_flag:
                layer_requested += 1
            item = {
                "layer": layer_id,
                "capability": capability_name,
                "requested": requested_flag,
                "support": support,
                "effective": effective,
            }
            layer_items.append(item)
            flat_items.append(item)

        requested_by_layer[layer_id] = layer_requested
        layers.append(
            {
                "layer": layer_id,
                "label": 能力分层标签.get(layer_id, layer_id),
                "items": layer_items,
                "summary": {
                    "requested": layer_requested,
                    "downgraded_requested": layer_downgraded,
                    "unsupported_requested": layer_unsupported,
                },
            }
        )

    return {
        "source_engine": source_engine,
        "target_engine": target_engine,
        "layers": layers,
        "items": flat_items,
        "observations": observations,
        "summary": {
            "requested": sum(1 for item in flat_items if item["requested"]),
            "downgraded_requested": downgraded_requested,
            "unsupported_requested": unsupported_requested,
            "requested_by_layer": requested_by_layer,
        },
    }


def _write_json_if_needed(*, output_path: Path | None, payload: Any) -> str | None:
    """按需写出 JSON 报告。

    Args:
        output_path: 输出路径；为空则跳过。
        payload: 待写对象。

    Returns:
        str | None: 实际写出的绝对路径。
    """

    if output_path is None:
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(output_path)


def _resolve_report_path(*, explicit_path: str, report_output_dir: str, default_name: str) -> Path | None:
    """解析报告输出路径。

    Args:
        explicit_path: 显式传入的输出路径。
        report_output_dir: 报告输出目录。
        default_name: 默认文件名。

    Returns:
        Path | None: 报告路径；未配置时返回 `None`。
    """

    if str(explicit_path).strip():
        return Path(str(explicit_path).strip()).expanduser().resolve()
    if str(report_output_dir).strip():
        return Path(str(report_output_dir).strip()).expanduser().resolve() / default_name
    return None


def execute_workspace_conversion_pipeline(
    *,
    project_dir: str,
    source_engine: str,
    target_engine: str,
    source_ide: str = "",
    target_ide: str = "",
    source_os: str = "",
    target_os: str = "",
    title: str = "",
    dry_run: bool = False,
    canonical_dump_path: str = "",
    validation_report_path: str = "",
    report_output_dir: str = "",
    allow_downgrade: bool = True,
    target_capability_mode: str = "balanced",
    repo_root: str = "",
) -> dict[str, Any]:
    """执行带报告的办公区跨引擎转换。

    Args:
        project_dir: 项目目录。
        source_engine: 来源引擎。
        target_engine: 目标引擎。
        title: 转换标题。
        dry_run: 是否试运行。
        canonical_dump_path: canonical AOL dump 输出路径。
        validation_report_path: capability 校验报告输出路径。
        report_output_dir: 报告输出目录。
        allow_downgrade: 是否允许降级输出。
        target_capability_mode: 目标能力模式，支持 `balanced`、`strict`。

    Returns:
        dict[str, Any]: 转换执行结果。
    """

    normalized_source = str(source_engine).strip().lower()
    normalized_target = str(target_engine).strip().lower()
    if normalized_source not in 支持引擎集合:
        raise ValueError(f"不支持的 source_engine：{source_engine}")
    if normalized_target not in 支持引擎集合:
        raise ValueError(f"不支持的 target_engine：{target_engine}")
    if normalized_source == normalized_target:
        raise ValueError("source_engine 与 target_engine 不能相同")

    capability_mode = str(target_capability_mode or "balanced").strip().lower() or "balanced"
    if capability_mode not in {"balanced", "strict"}:
        raise ValueError("target_capability_mode 仅支持 balanced 或 strict")

    project_root = Path(str(project_dir).strip()).expanduser().resolve()
    if not project_root.exists() or not project_root.is_dir():
        raise ValueError(f"project_dir 不存在：{project_root}")

    source_profile = 解析工作区目标配置(
        engine_vendor=normalized_source,
        ide_vendor=source_ide,
        os_family=source_os,
        repo_root=repo_root,
    )
    target_profile = 解析工作区目标配置(
        engine_vendor=normalized_target,
        ide_vendor=target_ide,
        os_family=target_os,
        repo_root=repo_root,
    )

    source_workspace_dir = project_root / str(source_profile.get("workspace_dir_name") or 读取引擎办公区目录名(engine=normalized_source))
    target_workspace_dir = project_root / str(target_profile.get("workspace_dir_name") or 读取引擎办公区目录名(engine=normalized_target))
    conversion_title = str(title).strip() or f"{project_root.name} 办公区跨引擎转换"

    aol, stats = 从引擎办公区构建_aol(
        source_workspace_dir=source_workspace_dir,
        source_engine=normalized_source,
        title=conversion_title,
    )
    warnings = 校验_aol(aol)
    blocking_errors = 收集_opencode阻断错误(aol) if normalized_target == "opencode" else []
    capability_report = _build_capability_report(
        aol=aol,
        project_root=project_root,
        source_workspace_dir=source_workspace_dir,
        source_engine=normalized_source,
        target_engine=normalized_target,
    )

    gating_errors: list[str] = []
    if blocking_errors:
        gating_errors.extend(blocking_errors)
    if capability_mode == "strict" and capability_report["summary"]["downgraded_requested"]:
        gating_errors.append("target_capability_mode=strict，存在被降级的请求能力")
    if capability_report["summary"]["unsupported_requested"]:
        gating_errors.append("目标引擎不支持当前 AOL 请求的全部能力")
    if not allow_downgrade and capability_report["summary"]["downgraded_requested"]:
        gating_errors.append("allow_downgrade=false，目标引擎存在能力降级")

    canonical_payload = {
        "source_engine": normalized_source,
        "target_engine": normalized_target,
        "source_profile": source_profile,
        "target_profile": target_profile,
        "title": conversion_title,
        "stats": stats,
        "aol": asdict(aol),
    }
    validation_payload = {
        "source_engine": normalized_source,
        "target_engine": normalized_target,
        "source_profile": source_profile,
        "target_profile": target_profile,
        "title": conversion_title,
        "warnings": warnings,
        "blocking_errors": blocking_errors,
        "gating_errors": gating_errors,
        "capability_report": capability_report,
    }

    canonical_path = _write_json_if_needed(
        output_path=_resolve_report_path(
            explicit_path=canonical_dump_path,
            report_output_dir=report_output_dir,
            default_name="aob_workspace_canonical_dump.json",
        ),
        payload=canonical_payload,
    )
    validation_path = _write_json_if_needed(
        output_path=_resolve_report_path(
            explicit_path=validation_report_path,
            report_output_dir=report_output_dir,
            default_name="aob_workspace_validation_report.json",
        ),
        payload=validation_payload,
    )

    if gating_errors:
        return {
            "status": "FAIL",
            "code": 2,
            "mode": "convert_workspace",
            "dry_run": dry_run,
            "project_dir": str(project_root),
            "source_engine": normalized_source,
            "target_engine": normalized_target,
            "source_profile": source_profile,
            "target_profile": target_profile,
            "source_workspace_dir": str(source_workspace_dir),
            "target_workspace_dir": str(target_workspace_dir),
            "title": conversion_title,
            "stats": stats,
            "warnings": warnings,
            "blocking_errors": blocking_errors,
            "gating_errors": gating_errors,
            "capability_report": capability_report,
            "canonical_dump_path": canonical_path,
            "validation_report_path": validation_path,
        }

    if not dry_run:
        编译_aol到引擎办公区(
            aol=aol,
            target_workspace_dir=target_workspace_dir,
            target_engine=normalized_target,
        )

    return {
        "status": "PASS",
        "code": 0,
        "mode": "convert_workspace",
        "dry_run": dry_run,
        "project_dir": str(project_root),
        "source_engine": normalized_source,
        "target_engine": normalized_target,
        "source_profile": source_profile,
        "target_profile": target_profile,
        "source_workspace_dir": str(source_workspace_dir),
        "target_workspace_dir": str(target_workspace_dir),
        "title": conversion_title,
        "stats": stats,
        "warnings": warnings,
        "blocking_errors": blocking_errors,
        "gating_errors": [],
        "capability_report": capability_report,
        "canonical_dump_path": canonical_path,
        "validation_report_path": validation_path,
    }