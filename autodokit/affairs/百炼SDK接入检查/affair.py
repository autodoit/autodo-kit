"""百炼 SDK 接入检查事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import append_flow_trace_event, load_json_or_py, write_affair_json_result


def _mask_secret(value: str) -> str:
    """对敏感字符串做脱敏展示。

    Args:
        value: 原始敏感字符串。

    Returns:
        脱敏后的字符串。
    """

    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def run_bootstrap_check(
    key_file: str | Path,
    model: str = "auto",
    endpoint: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """执行百炼接入准备检查。

    Args:
        key_file: API Key 文件路径。
        model: 默认模型名。
        endpoint: 访问端点。
        workspace_root: 可选工作区根目录。

    Returns:
        结构化检查结果。
    """

    key_path = Path(key_file).expanduser().resolve()
    if not key_path.exists():
        raise FileNotFoundError(f"API Key 文件不存在: {key_path}")

    api_key = key_path.read_text(encoding="utf-8").strip()
    if not api_key:
        raise ValueError("API Key 文件为空")

    trace_root = Path(workspace_root).expanduser().resolve() if workspace_root else Path(".").resolve()
    append_flow_trace_event(
        workspace_root=trace_root,
        event={
            "event_type": "task",
            "command": "aok-bailian-bootstrap",
            "agent": "orchestrator",
            "skill": "aliyun-bailian-sdk-bootstrap",
            "provider": "aliyun-bailian",
            "task_uid": "",
            "transaction_uid": "",
            "status": "PASS",
            "mode": "bootstrap-check",
            "task_type": "general",
            "model": model,
            "fallback_models": [],
            "artifacts": {"key_file": str(key_path)},
        },
    )
    return {
        "status": "PASS",
        "mode": "aliyun-bailian-sdk-bootstrap",
        "result": {
            "key_file": str(key_path),
            "key_preview": _mask_secret(api_key),
            "model": model,
            "endpoint": endpoint,
            "env_var": "DASHSCOPE_API_KEY",
            "note": "已完成本地接入准备检查；实际连通性请在回归中验证。",
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = run_bootstrap_check(
        key_file=str(raw_cfg.get("key_file") or ""),
        model=str(raw_cfg.get("model") or "auto"),
        endpoint=str(raw_cfg.get("endpoint") or "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        workspace_root=raw_cfg.get("workspace_root"),
    )
    return write_affair_json_result(raw_cfg, config_path, "aliyun_bailian_sdk_bootstrap_result.json", result)
