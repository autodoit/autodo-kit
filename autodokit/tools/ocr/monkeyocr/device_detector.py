"""MonkeyOCR 设备检测模块。

自动识别当前运行环境可用的计算后端：
- CUDA: NVIDIA GPU 通过 PyTorch CUDA
- MLX: Apple Silicon 通过 MLX 框架 (Metal GPU)
- CPU: 无 GPU 加速时的兜底方案

检测结果按优先级排序：CUDA > MLX > CPU。
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from autodokit.tools.ocr.monkeyocr.schemes import ComputeBackend

logger = logging.getLogger(__name__)


def detect_cuda() -> bool:
    """检测 PyTorch CUDA 是否可用。

    Returns:
        True 表示 CUDA GPU 可用且至少有一张卡。

    Examples:
        >>> detect_cuda()
        False  # 在 macOS / Apple Silicon 上
    """

    try:
        import torch  # type: ignore[import-untyped]

        return bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
    except ImportError:
        logger.debug("torch not installed, CUDA unavailable")
        return False
    except Exception:
        logger.debug("CUDA detection failed", exc_info=True)
        return False


def detect_mlx() -> bool:
    """检测 Apple MLX 是否可用。

    MLX 是 Apple 官方为 Apple Silicon 设计的机器学习框架，
    可直接调用 Metal GPU。仅在 macOS ARM64 上有意义。

    Returns:
        True 表示 mlx.core 可正常导入。

    Examples:
        >>> detect_mlx()
        True  # 在 M 系列芯片 Mac 上安装了 mlx 时
    """

    if not sys.platform.startswith("darwin"):
        return False

    try:
        import mlx.core  # type: ignore[import-untyped]  # noqa: F401

        return True
    except ImportError:
        logger.debug("mlx not installed, MLX unavailable")
        return False
    except Exception:
        logger.debug("MLX detection failed", exc_info=True)
        return False


def detect_mps() -> bool:
    """检测 PyTorch MPS (Metal Performance Shaders) 是否可用。

    这是 PyTorch 在 macOS 上的 GPU 后端。MLX 优先级高于 MPS，
    此检测主要用于提供更详细的诊断信息。

    Returns:
        True 表示 torch.mps 可用。

    Examples:
        >>> detect_mps()
        True
    """

    try:
        import torch  # type: ignore[import-untyped]

        return bool(torch.backends.mps.is_available())
    except ImportError:
        return False
    except Exception:
        return False


def detect_available_backends() -> list[ComputeBackend]:
    """按优先级检测所有可用计算后端。

    识别顺序及规则：
    1. CUDA — NVIDIA GPU (Windows/Linux)
    2. MLX  — Apple Silicon GPU (macOS ARM64)
    3. CPU  — 始终可用，但排在最后作为兜底

    Returns:
        按优先级排列的可用后端列表，至少包含 "cpu"。

    Examples:
        >>> detect_available_backends()
        ['mlx', 'cpu']  # 在 M5 Max MacBook Pro 上
        >>> detect_available_backends()
        ['cuda', 'cpu']  # 在 NVIDIA GPU 机器上
    """

    backends: list[ComputeBackend] = []

    if detect_cuda():
        backends.append("cuda")

    if detect_mlx():
        backends.append("mlx")

    # CPU 始终作为最后兜底
    backends.append("cpu")

    return backends


def get_best_backend() -> ComputeBackend:
    """返回当前设备上最优的计算后端。

    按 CUDA → MLX → CPU 优先级选择第一个可用后端。

    Returns:
        最优后端标识。

    Examples:
        >>> get_best_backend()
        'mlx'  # 在 M5 Max 上
    """

    backends = detect_available_backends()

    # CUDA 优先
    if "cuda" in backends:
        return "cuda"

    # MLX 次之
    if "mlx" in backends:
        return "mlx"

    # CPU 兜底
    return "cpu"


def get_gpu_name() -> Optional[str]:
    """获取当前 GPU 名称（用于诊断日志）。

    Returns:
        GPU 名称字符串，若不可获取则返回 None。

    Examples:
        >>> get_gpu_name()
        'Apple M5 Max'
    """

    if detect_cuda():
        try:
            import torch  # type: ignore[import-untyped]

            return str(torch.cuda.get_device_name(0))
        except Exception:
            return None

    if detect_mlx():
        try:
            import mlx.core  # type: ignore[import-untyped]

            # mlx 目前没有直接获取 GPU 名称的 API，
            # 回退到 system_profiler 或默认标识
            return "Apple Silicon (MLX)"
        except Exception:
            return None

    return None


__all__ = [
    "detect_cuda",
    "detect_mlx",
    "detect_mps",
    "detect_available_backends",
    "get_best_backend",
    "get_gpu_name",
]
