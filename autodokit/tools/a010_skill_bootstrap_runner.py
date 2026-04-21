"""A010 冷启动脚本桥接 runner。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import warnings
from typing import Any


_TRUE_VALUES = {"1", "true", "yes", "y", "on", "是"}
_FALSE_VALUES = {"0", "false", "no", "n", "off", "否"}
_DEFAULT_VALUES = {"", "default", "默认", "none", "null"}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_tristate(value: Any) -> str:
    text = _to_text(value).lower()
    if text in _TRUE_VALUES:
        return "true"
    if text in _FALSE_VALUES:
        return "false"
    if text in _DEFAULT_VALUES:
        return "default"
    return "default"


def _resolve_policy(local_value: Any, global_value: Any, *, fallback: str) -> str:
    local_state = _parse_tristate(local_value)
    if local_state != "default":
        return local_state
    global_state = _parse_tristate(global_value)
    if global_state != "default":
        return global_state
    return fallback


def _extract_commit_value(cfg: dict[str, Any], key: str) -> Any:
    if key in cfg:
        return cfg.get(key)
    nested = cfg.get("git_commit")
    if isinstance(nested, dict) and key in nested:
        return nested.get(key)
    return None


def _resolve_workspace_root(config_path: Path, local_cfg: dict[str, Any]) -> Path:
    workspace_root = _to_text(local_cfg.get("workspace_root") or local_cfg.get("project_root"))
    if workspace_root:
        return Path(workspace_root).expanduser().resolve()
    if len(config_path.parents) >= 3 and config_path.parent.name == "affairs_config":
        return config_path.parents[2].resolve()
    return config_path.parent.resolve()


def _resolve_python_executable(raw_venv_path: str) -> Path:
    if raw_venv_path:
        venv_path = Path(raw_venv_path).expanduser().resolve()
        if venv_path.is_file():
            return venv_path
        for candidate in (venv_path / "Scripts" / "python.exe", venv_path / "bin" / "python"):
            if candidate.exists():
                return candidate.resolve()
    return Path(sys.executable).resolve()


def _resolve_template_workspace_root(local_cfg: dict[str, Any], global_cfg: dict[str, Any]) -> Path:
    template_root = _to_text(local_cfg.get("template_root")) or _to_text((global_cfg.get("bootstrap") or {}).get("template_root"))
    if not template_root:
        warnings.warn(
            "A010 需要显式配置 bootstrap.template_root 指向外部 skill 模板目录。",
            RuntimeWarning,
            stacklevel=3,
        )
        raise FileNotFoundError("未配置 A010 初始化模板根目录 template_root")
    template_workspace_root = Path(template_root).expanduser().resolve()
    if not template_workspace_root.exists():
        warnings.warn(
            f"A010 模板根目录不存在: {template_workspace_root}",
            RuntimeWarning,
            stacklevel=3,
        )
        raise FileNotFoundError(f"未找到 A010 模板根目录: {template_workspace_root}")
    return template_workspace_root


def _resolve_script_path(local_cfg: dict[str, Any], global_cfg: dict[str, Any]) -> Path:
    template_workspace_root = _resolve_template_workspace_root(local_cfg, global_cfg)
    candidate = template_workspace_root.parents[2] / "scripts" / "generate_config.py"
    if candidate.exists():
        return candidate.resolve()
    warnings.warn(
        f"A010 初始化脚本不存在: {candidate}",
        RuntimeWarning,
        stacklevel=3,
    )
    raise FileNotFoundError(f"未找到 A010 初始化脚本 generate_config.py: {candidate}")


def _load_a020_seed(global_cfg: dict[str, Any]) -> tuple[list[str], list[str], str]:
    node_inputs = global_cfg.get("node_inputs") or {}
    a020_config_path = _to_text(node_inputs.get("A020"))
    if not a020_config_path:
        return [], [], ""
    payload = _read_json(Path(a020_config_path).expanduser().resolve())
    raw_paths = payload.get("origin_bib_paths") or []
    origin_bib_paths = [str(Path(str(item)).expanduser().resolve()).replace("\\", "/") for item in raw_paths if str(item).strip()]
    raw_roots = payload.get("origin_attachments_roots") or []
    if isinstance(raw_roots, str):
        raw_roots = [raw_roots]
    origin_attachments_roots = [
        str(Path(str(item)).expanduser().resolve()).replace("\\", "/")
        for item in raw_roots
        if str(item).strip()
    ]
    origin_attachments_root = _to_text(payload.get("origin_attachments_root"))
    if origin_attachments_root:
        origin_attachments_root = str(Path(origin_attachments_root).expanduser().resolve()).replace("\\", "/")
    return origin_bib_paths, origin_attachments_roots, origin_attachments_root


def _build_command(config_path: Path, local_cfg: dict[str, Any], global_cfg: dict[str, Any]) -> list[str]:
    workspace_root = _resolve_workspace_root(config_path, local_cfg)
    root_path = _to_text(global_cfg.get("root_path")) or str(workspace_root.parent)
    project_cfg = global_cfg.get("project") or {}
    project_name = _to_text(project_cfg.get("project_name")) or "示例项目"
    project_goal = _to_text(project_cfg.get("project_goal")) or "完成文献工程化主链运行与审计"
    workflow_name = _to_text(global_cfg.get("workflow_name"))
    llm_cfg = global_cfg.get("llm") or {}
    llm_api_key_file = _to_text(llm_cfg.get("aliyun_api_key_file"))
    venv_path = _to_text(global_cfg.get("venv_path"))
    template_workspace_root = _resolve_template_workspace_root(local_cfg, global_cfg)
    template_root = str(template_workspace_root)
    origin_bib_paths, origin_attachments_roots, origin_attachments_root = _load_a020_seed(global_cfg)

    local_auto = _extract_commit_value(local_cfg, "is_auto_git_commit")
    global_auto = _extract_commit_value(global_cfg, "is_auto_git_commit")
    resolved_auto = _resolve_policy(local_auto, global_auto, fallback="false")
    local_ask = _extract_commit_value(local_cfg, "自动提交前是否询问人类")
    global_ask = _extract_commit_value(global_cfg, "自动提交前是否询问人类")
    resolved_ask = _resolve_policy(local_ask, global_ask, fallback="false")

    script_path = _resolve_script_path(local_cfg, global_cfg)
    python_executable = _resolve_python_executable(venv_path)
    command = [
        str(python_executable),
        str(script_path),
    ]
    if workflow_name:
        command.extend(["--workflow-name", workflow_name])
    if template_root:
        command.extend(["--template-root", template_root])
    if llm_api_key_file:
        command.extend(["--llm-api-key-file", llm_api_key_file])
    for bib_path in origin_bib_paths:
        command.extend(["--origin-bib-path", bib_path])
    for attachments_root in origin_attachments_roots:
        command.extend(["--origin-attachments-roots", attachments_root])
    if origin_attachments_root:
        command.extend(["--origin-attachments-root", origin_attachments_root])
    if _parse_tristate(local_cfg.get("dry_run")) == "true":
        command.append("--dry-run")
    if resolved_auto == "true" and resolved_ask == "false":
        command.append("--auto-snapshot")
    command.extend([root_path, project_name, project_goal, venv_path])
    return command


def _collect_outputs(workspace_root: Path) -> list[Path]:
    outputs: list[Path] = []
    config_path = workspace_root / "config" / "config.json"
    registry_path = workspace_root / "config" / "affair_entry_registry.json"
    if config_path.exists():
        outputs.append(config_path)
        global_cfg = _read_json(config_path)
        self_check_path = _to_text((global_cfg.get("bootstrap") or {}).get("self_check_report_path"))
        if self_check_path:
            candidate = Path(self_check_path).expanduser().resolve()
            if candidate.exists():
                outputs.append(candidate)
                result_path = candidate.parent / "project_initialization_result.json"
                if result_path.exists():
                    outputs.append(result_path)
    if registry_path.exists():
        outputs.append(registry_path)
    return outputs


def execute(config_path: Path) -> list[Path]:
    """执行 A010 技能脚本作为唯一初始化入口。"""

    resolved_config_path = Path(config_path).expanduser().resolve()
    local_cfg = _read_json(resolved_config_path)
    workspace_root = _resolve_workspace_root(resolved_config_path, local_cfg)
    global_cfg = _read_json(workspace_root / "config" / "config.json")
    command = _build_command(resolved_config_path, local_cfg, global_cfg)
    result = subprocess.run(
        command,
        cwd=str(_resolve_script_path(local_cfg, global_cfg).parent),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "A010 初始化脚本执行失败").strip()
        raise RuntimeError(message)
    return _collect_outputs(workspace_root)


__all__ = ["execute"]