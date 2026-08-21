"""MonkeyOCR-based tools — multi-backend support (CUDA / MLX / CPU)."""

from .cpu_fallback_handler import confirm_cpu_fallback, confirm_cpu_fallback_or_raise
from .device_detector import (
    detect_available_backends,
    detect_cuda,
    detect_mlx,
    detect_mps,
    get_best_backend,
    get_gpu_name,
)
from .monkeyocr_mlx_tools import (
    prepare_monkeyocr_mlx_runtime,
    run_monkeyocr_mlx_single_pdf,
)
from .monkeyocr_windows_tools import (
    parse_pdf_with_monkeyocr_windows,
    prepare_monkeyocr_windows_runtime,
    run_monkeyocr_windows_batch_folder,
    run_monkeyocr_windows_single_pdf,
    update_monkeyocr_batch_status_csv,
)
from .runner import (
    launch_remote_tmux_command,
    run_monkeyocr_remote,
    run_monkeyocr_single_pdf,
    stop_remote_monkeyocr_jobs,
)
from .schemes import (
    DEFAULT_MODEL_NAME,
    MLX_APPLE_SILICON_HF_REPO,
    MLX_REQUIREMENT,
    MLX_VLM_REQUIREMENT,
    ComputeBackend,
    ExecutionMode,
)

__all__ = [
    # ── Windows / CUDA ──
    "parse_pdf_with_monkeyocr_windows",
    "prepare_monkeyocr_windows_runtime",
    "run_monkeyocr_windows_batch_folder",
    "run_monkeyocr_windows_single_pdf",
    "update_monkeyocr_batch_status_csv",
    # ── MLX / Apple Silicon ──
    "prepare_monkeyocr_mlx_runtime",
    "run_monkeyocr_mlx_single_pdf",
    # ── 统一入口 ──
    "run_monkeyocr_single_pdf",
    "run_monkeyocr_remote",
    "stop_remote_monkeyocr_jobs",
    "launch_remote_tmux_command",
    # ── 设备检测 ──
    "detect_cuda",
    "detect_mlx",
    "detect_mps",
    "detect_available_backends",
    "get_best_backend",
    "get_gpu_name",
    # ── CPU 回退 ──
    "confirm_cpu_fallback",
    "confirm_cpu_fallback_or_raise",
    # ── 类型常量 ──
    "ExecutionMode",
    "ComputeBackend",
    "DEFAULT_MODEL_NAME",
    "MLX_APPLE_SILICON_HF_REPO",
    "MLX_REQUIREMENT",
    "MLX_VLM_REQUIREMENT",
]

