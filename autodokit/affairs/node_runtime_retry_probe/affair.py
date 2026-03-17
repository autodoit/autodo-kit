"""Node Runtime 重试探针事务。

该事务用于 S7 回归 demo：
- 在前 N 次执行时抛出可重试异常（TimeoutError/ConnectionError）；
- 超过阈值后成功并输出报告文件。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


_RESET_DONE_STATE_FILES: set[str] = set()


@dataclass(frozen=True, slots=True)
class RetryProbeConfig:
    """重试探针配置。

    Args:
        output_dir: 输出目录。
        state_file: 状态文件路径（记录尝试次数）。
        fail_times: 失败次数阈值（小于等于该次数时抛异常）。
        exception_type: 异常类型，支持 `timeout` 与 `connection`。
        reset_state_on_start: 是否在一次进程运行的首次调用时重置状态文件。

    Examples:
        >>> RetryProbeConfig(output_dir="output/demo", state_file="output/demo/state.json")
        RetryProbeConfig(output_dir='output/demo', state_file='output/demo/state.json', fail_times=1, exception_type='timeout')
    """

    output_dir: str
    state_file: str
    fail_times: int = 1
    exception_type: str = "timeout"
    reset_state_on_start: bool = False


def _load_config(config_path: Path) -> RetryProbeConfig:
    """加载探针配置。

    Args:
        config_path: 调度层下发的临时配置文件路径。

    Returns:
        RetryProbeConfig: 规范化配置。

    Raises:
        ValueError: 配置字段缺失或非法时抛出。
    """

    data = json.loads(config_path.read_text(encoding="utf-8"))
    output_dir = str(data.get("output_dir") or "").strip()
    if not output_dir:
        raise ValueError("node_runtime_retry_probe 缺少 output_dir")

    state_file = str(data.get("state_file") or "").strip()
    if not state_file:
        state_file = str((Path(output_dir) / "retry_probe_state.json").resolve())

    fail_times = max(0, int(data.get("fail_times") or 1))
    exception_type = str(data.get("exception_type") or "timeout").strip().lower() or "timeout"
    reset_state_on_start = bool(data.get("reset_state_on_start", False))
    return RetryProbeConfig(
        output_dir=output_dir,
        state_file=state_file,
        fail_times=fail_times,
        exception_type=exception_type,
        reset_state_on_start=reset_state_on_start,
    )


def _read_attempts(state_path: Path) -> int:
    """读取历史尝试次数。

    Args:
        state_path: 状态文件路径。

    Returns:
        int: 已记录的尝试次数。
    """

    if not state_path.exists():
        return 0
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    return max(0, int(data.get("attempts") or 0))


def _write_state(state_path: Path, *, attempts: int) -> None:
    """写入状态文件。

    Args:
        state_path: 状态文件路径。
        attempts: 当前尝试次数。
    """

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"attempts": int(attempts)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _raise_retryable(exception_type: str, message: str) -> None:
    """抛出可重试异常。

    Args:
        exception_type: 异常类型。
        message: 异常消息。

    Raises:
        TimeoutError: 当 exception_type=timeout。
        ConnectionError: 当 exception_type=connection。
    """

    if exception_type == "connection":
        raise ConnectionError(message)
    raise TimeoutError(message)


def execute(config_path: Path) -> List[Path]:
    """执行重试探针事务。

    Args:
        config_path: 调度层生成的临时配置路径。

    Returns:
        List[Path]: 输出文件路径列表。

    Raises:
        TimeoutError: 触发超时型可重试失败。
        ConnectionError: 触发连接型可重试失败。
        ValueError: 配置非法。

    Examples:
        >>> # execute(Path('.tmp/probe.json'))
        >>> # 首次可按配置抛出可重试异常
        >>> True
        True
    """

    cfg = _load_config(Path(config_path))
    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    state_path = Path(cfg.state_file)
    state_key = str(state_path.resolve())
    if cfg.reset_state_on_start and state_key not in _RESET_DONE_STATE_FILES:
        if state_path.exists():
            state_path.unlink()
        _RESET_DONE_STATE_FILES.add(state_key)

    attempts = _read_attempts(state_path) + 1
    _write_state(state_path, attempts=attempts)

    if attempts <= cfg.fail_times:
        _raise_retryable(
            cfg.exception_type,
            f"retry_probe planned failure: attempt={attempts}, fail_times={cfg.fail_times}",
        )

    report_path = (output_dir / "retry_probe_report.json").resolve()
    report_payload: Dict[str, Any] = {
        "status": "ok",
        "attempts": attempts,
        "fail_times": cfg.fail_times,
        "exception_type": cfg.exception_type,
    }
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return [report_path]
