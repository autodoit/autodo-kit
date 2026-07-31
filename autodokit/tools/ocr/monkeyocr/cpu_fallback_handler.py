"""CPU 回退确认交互模块。

当自动检测不到 CUDA 或 MLX 时，说明当前设备只能用 CPU 运行
MonkeyOCR。CPU 解析速度通常比 GPU 慢 10-50 倍，因此必须在
继续前暂停并获取用户人工确认。

设计原则：
- 不支持静默回退到 CPU：必须通过 input() 暂停。
- 提供清晰的性能预期信息。
- 用户可选择继续或终止。
- 提供 `--yes` / 环境变量跳过交互的工程入口（仅限 CI/脚本）。
"""

from __future__ import annotations

import os
import sys
from typing import NoReturn


def _is_non_interactive() -> bool:
    """判断当前是否为非交互环境 (CI / 重定向)。"""

    if not sys.stdin.isatty():
        return True
    if os.environ.get("CI") or os.environ.get("MONKEYOCR_CPU_AUTO_CONFIRM"):
        return True
    return False


def confirm_cpu_fallback(
    *,
    available_backends: list[str] | None = None,
    reason: str = "",
) -> bool:
    """CPU 回退前暂停，等待用户确认。

    打印告警信息，说明当前无 GPU 加速可用，即将使用纯 CPU 运行。
    然后等待用户输入 `y` 或 `yes` 确认继续，其他任何输入都将终止程序。

    Args:
        available_backends: 当前检测到的可用后端列表，用于诊断输出。
        reason: GPU 不可用的具体原因（如 "mlx-vlm 未安装"）。

    Returns:
        True 表示用户确认继续使用 CPU。

    Raises:
        SystemExit: 用户拒绝或输入超时（非交互环境直接退出）。

    Examples:
        >>> confirm_cpu_fallback(reason="未检测到 CUDA 或 MLX")
        ⚠️  ...
        是否继续使用 CPU 运行? (y/N): y
        True
    """

    backend_info = ""
    if available_backends:
        backend_info = f"当前可用后端: {', '.join(available_backends)}"

    print("\n" + "=" * 62, file=sys.stderr)
    print("⚠️  警告：即将使用 CPU 模式运行 MonkeyOCR", file=sys.stderr)
    print("=" * 62, file=sys.stderr)
    print(f"  未检测到 GPU 加速后端 (CUDA / MLX)。", file=sys.stderr)
    if reason:
        print(f"  原因: {reason}", file=sys.stderr)
    if backend_info:
        print(f"  {backend_info}", file=sys.stderr)
    print(f"  CPU 解析速度通常比 GPU 慢 10-50 倍。", file=sys.stderr)
    print(f"  对于多页 PDF，可能需要数分钟乃至更长。", file=sys.stderr)
    print("-" * 62, file=sys.stderr)

    if _is_non_interactive():
        print("  非交互环境，自动终止。", file=sys.stderr)
        print("  设置环境变量 MONKEYOCR_CPU_AUTO_CONFIRM=1 可跳过此确认。", file=sys.stderr)
        raise SystemExit(1)

    try:
        answer = input("  是否继续使用 CPU 运行? (y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  已取消。", file=sys.stderr)
        raise SystemExit(1)

    if answer in ("y", "yes"):
        print("  ✓ 已确认，继续使用 CPU 运行...\n", file=sys.stderr)
        return True

    print("  ✗ 已取消。请安装 CUDA 或 MLX 后端后重试。", file=sys.stderr)
    raise SystemExit(1)


def confirm_cpu_fallback_or_raise(
    *,
    available_backends: list[str] | None = None,
    reason: str = "",
) -> None:
    """confirm_cpu_fallback 的简化版，确认失败直接抛异常。

    Args:
        available_backends: 可用后端列表。
        reason: 回退原因。

    Raises:
        RuntimeError: 用户拒绝 CPU 回退。
        SystemExit: 非交互环境自动终止。
    """

    confirmed = confirm_cpu_fallback(
        available_backends=available_backends,
        reason=reason,
    )
    if not confirmed:
        raise RuntimeError("用户拒绝了 CPU 回退，MonkeyOCR 解析已取消")


__all__ = [
    "confirm_cpu_fallback",
    "confirm_cpu_fallback_or_raise",
]
