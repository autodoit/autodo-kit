"""事务节点后置 Git 自动提交工具。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Iterable, List, Sequence

from autodokit.tools.atomic.task_aok.git_snapshot_ledger import git_create_snapshot_for_task
from autodokit.tools.time_utils import now_compact

_TRUE_VALUES = {"1", "true", "yes", "y", "on", "是"}
_FALSE_VALUES = {"0", "false", "no", "n", "off", "否"}
_DEFAULT_VALUES = {"", "default", "默认", "none", "null"}


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


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


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


def _collect_artifact_lines(workspace_root: Path, artifact_paths: Sequence[Path]) -> List[str]:
    lines: List[str] = []
    for item in artifact_paths:
        try:
            resolved = item.resolve()
        except OSError:
            continue
        if not resolved.exists():
            continue
        try:
            relative = resolved.relative_to(workspace_root)
            lines.append(str(relative).replace("\\", "/"))
        except ValueError:
            lines.append(str(resolved).replace("\\", "/"))
        if len(lines) >= 30:
            break
    return lines


def _read_git_status_lines(workspace_root: Path) -> List[str]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=str(workspace_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _build_commit_message(
    *,
    node_code: str,
    title: str,
    workspace_root: Path,
    artifact_paths: Sequence[Path],
    auto_commit_policy: str,
    ask_human_policy: str,
) -> str:
    artifact_lines = _collect_artifact_lines(workspace_root, artifact_paths)
    status_lines = _read_git_status_lines(workspace_root)
    body_lines: List[str] = [
        "事务产物自动提交",
        "",
        f"- 事务节点: {node_code}",
        f"- 自动提交: {auto_commit_policy}",
        f"- 提交前询问人类: {ask_human_policy}",
        f"- 产物数量: {len(artifact_lines)}",
    ]
    if artifact_lines:
        body_lines.append("- 产物清单:")
        body_lines.extend([f"  - {line}" for line in artifact_lines])
    if status_lines:
        body_lines.append("- 变更摘要:")
        body_lines.extend([f"  - {line}" for line in status_lines[:50]])
    return f"{title}\n\n" + "\n".join(body_lines)


def _confirm_from_human(node_code: str, title: str) -> tuple[bool, str]:
    if not sys.stdin or not sys.stdin.isatty():
        return False, "manual_confirmation_required_non_tty"
    prompt = f"[{node_code}] 检测到自动提交策略且要求人工确认，是否提交 {title}? [y/N]: "
    try:
        answer = input(prompt)
    except EOFError:
        return False, "manual_confirmation_required_eof"
    normalized = _to_text(answer).lower()
    if normalized in _TRUE_VALUES:
        return True, "confirmed"
    return False, "declined"


def _normalize_artifact_paths(result: Any) -> List[Path]:
    if isinstance(result, Path):
        return [result]
    if not isinstance(result, Iterable) or isinstance(result, (str, bytes)):
        return []
    normalized: List[Path] = []
    for item in result:
        if isinstance(item, Path):
            normalized.append(item)
        elif isinstance(item, str) and item.strip():
            normalized.append(Path(item.strip()))
    return normalized


def _run_post_affair_auto_commit(config_path: Path, *, node_code: str, execute_result: Any) -> None:
    local_cfg = _read_json_file(config_path)
    workspace_root = _resolve_workspace_root(config_path, local_cfg)
    global_cfg_path = workspace_root / "config" / "config.json"
    global_cfg = _read_json_file(global_cfg_path)

    local_auto = _extract_commit_value(local_cfg, "is_auto_git_commit")
    global_auto = _extract_commit_value(global_cfg, "is_auto_git_commit")
    resolved_auto = _resolve_policy(local_auto, global_auto, fallback="false")
    if resolved_auto != "true":
        return

    local_ask = _extract_commit_value(local_cfg, "自动提交前是否询问人类")
    global_ask = _extract_commit_value(global_cfg, "自动提交前是否询问人类")
    resolved_ask = _resolve_policy(local_ask, global_ask, fallback="false")

    timestamp = now_compact()
    title = f"{node_code}-{timestamp}"
    if resolved_ask == "true":
        confirmed, _ = _confirm_from_human(node_code, title)
        if not confirmed:
            return

    artifact_paths = _normalize_artifact_paths(execute_result)
    commit_message = _build_commit_message(
        node_code=node_code,
        title=title,
        workspace_root=workspace_root,
        artifact_paths=artifact_paths,
        auto_commit_policy="是",
        ask_human_policy="是" if resolved_ask == "true" else "否",
    )
    workflow_uid = _to_text(global_cfg.get("workflow_name")) or "academic-workflow"

    git_create_snapshot_for_task(
        workspace_root=workspace_root,
        task_uid=title,
        workflow_uid=workflow_uid,
        node_code=node_code,
        gate_code="POST_RUN",
        commit_message=commit_message,
        tag_name=f"aok/task/{title}",
        includes_attachments=True,
        ledger_db_path=_to_text((global_cfg.get("paths") or {}).get("tasks_db_path")) or None,
    )


def affair_auto_git_commit(node_code: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """在事务 `execute` 成功结束后按配置执行 Git 自动提交。"""

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            config_path: Path | None = None
            if args:
                candidate = args[0]
                if isinstance(candidate, Path):
                    config_path = candidate
                elif isinstance(candidate, str) and candidate.strip():
                    config_path = Path(candidate)
            if config_path is None:
                kw_value = kwargs.get("config_path")
                if isinstance(kw_value, Path):
                    config_path = kw_value
                elif isinstance(kw_value, str) and kw_value.strip():
                    config_path = Path(kw_value)

            result = func(*args, **kwargs)
            if config_path is not None:
                _run_post_affair_auto_commit(config_path=config_path, node_code=node_code, execute_result=result)
            return result

        return _wrapped

    return _decorator
