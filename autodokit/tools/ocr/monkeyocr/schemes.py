"""MonkeyOCR 工具包共享类型定义与常量。

本模块提供 ExecutionMode、ComputeBackend 等枚举字面量类型，
以及默认模型名等共享常量，供 runner、device_detector、各后端工具统一引用。
"""

from __future__ import annotations

from typing import Literal

# ── 执行模式 ──────────────────────────────────────────
# auto: 自动判断（有远端配置优先远端，否则本地）
# local: 强制本机运行
# remote: 强制远端运行
ExecutionMode = Literal["auto", "local", "remote"]

# ── 计算后端 ──────────────────────────────────────────
# auto: 自动检测最佳后端
# cuda: NVIDIA CUDA GPU
# mlx: Apple Silicon MLX (Metal GPU)
# cpu: 纯 CPU
ComputeBackend = Literal["auto", "cuda", "mlx", "cpu"]

# ── 默认常量 ──────────────────────────────────────────
DEFAULT_MODEL_NAME = "MonkeyOCR-pro-1.2B"

# ── MLX 相关常量 ──────────────────────────────────────
MLX_APPLE_SILICON_HF_REPO = "Jimmi42/MonkeyOCR-Apple-Silicon"
MLX_VLM_REQUIREMENT = "mlx-vlm>=0.1.0"
MLX_REQUIREMENT = "mlx>=0.16.0"

# ── MonkeyOCR 运行时根目录标识 ────────────────────────
# 查找 monkeyocr_root 时按此顺序检查目录下的特征文件
RUNTIME_ENTRY_FILES = ("parse.py", "setup.py")

__all__ = [
    "ExecutionMode",
    "ComputeBackend",
    "DEFAULT_MODEL_NAME",
    "MLX_APPLE_SILICON_HF_REPO",
    "MLX_VLM_REQUIREMENT",
    "MLX_REQUIREMENT",
    "RUNTIME_ENTRY_FILES",
]
