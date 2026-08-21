"""LM Studio 模型高速下载工具（hf-mirror 镜像）。

功能：
- 支持从 hf-mirror 国内镜像批量下载模型到 LM Studio 模型目录。
- 复用已验证的下载经验：HTTP/1.1、断点续传、全错误重试、自动创建子目录。
- 模型 ID 采用 HF 仓库格式 ``作者/仓库``（与 LM Studio Discover 中复制的 Model ID 一致）。
- 支持清单文件驱动或单个模型直下。

设计原则：
- 依赖系统 curl（macOS 自带），无需额外安装 Python 包。
- 下载目标目录固定为 ``~/.lmstudio/models/{作者}/{仓库}/``，LM Studio 靠该路径识别模型。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────────────────────

DEFAULT_MIRROR = "https://hf-mirror.com"
DEFAULT_MODELS_DIR = Path.home() / ".lmstudio" / "models"

# 默认下载的扩展名（LLM 权重 + 配置）
DEFAULT_EXTS = (".safetensors", ".json", ".txt", ".model")
# Kokoro-82M 需要 .pt（语音 + 配置）
KOKORO_EXTS = (".pt", ".json", ".txt", ".md")
# 需要特殊扩展名处理的仓库
_SPECIAL_EXTS = {
    "hexgrad/Kokoro-82M": KOKORO_EXTS,
}


def _resolve_models_dir(models_dir: str | Path | None) -> Path:
    """解析模型根目录。

    Args:
        models_dir: 模型根目录；为空时使用 ``~/.lmstudio/models``。

    Returns:
        Path: 解析后的模型根目录。
    """
    return Path(models_dir).expanduser() if models_dir else DEFAULT_MODELS_DIR


def _exts_for_repo(repo: str) -> tuple[str, ...]:
    """返回指定仓库需要下载的文件扩展名集合。

    Args:
        repo: 模型仓库，格式 ``作者/仓库``。

    Returns:
        tuple[str, ...]: 需要下载的文件扩展名列表。
    """
    return _SPECIAL_EXTS.get(repo, DEFAULT_EXTS)


def _fetch_repo_files(repo: str, mirror: str) -> list[dict]:
    """从镜像 API 获取仓库文件清单。

    Args:
        repo: 模型仓库，格式 ``作者/仓库``。
        mirror: 镜像根地址。

    Returns:
        list[dict]: 文件清单，每项含 ``rfilename`` 与 ``size`` 字段。

    Raises:
        RuntimeError: API 请求失败或返回错误时抛出。
    """
    url = f"{mirror}/api/models/{repo}?blobs=true"
    proc = subprocess.run(
        ["curl", "-s", "--max-time", "30", url],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"无法请求模型元数据: {repo} ({proc.stderr.strip() or 'curl 失败'})")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"模型元数据解析失败: {repo} ({exc})") from exc
    if "error" in data:
        raise RuntimeError(f"模型仓库不可用: {repo} — {data['error']}")
    return [f for f in data.get("siblings", []) if f.get("rfilename")]


def _select_files(repo: str, files: list[dict]) -> list[str]:
    """按扩展名过滤需要下载的文件，跳过隐藏文件。

    Args:
        repo: 模型仓库。
        files: 原始文件清单。

    Returns:
        list[str]: 需要下载的文件名列表。
    """
    exts = _exts_for_repo(repo)
    return [f["rfilename"] for f in files if f["rfilename"] and not f["rfilename"].startswith(".") and f["rfilename"].endswith(exts)]


def _download_file(url: str, dest: Path) -> bool:
    """单个文件下载（断点续传 + 全错误重试）。

    Args:
        url: 文件下载地址。
        dest: 本地目标路径（父目录已存在）。

    Returns:
        bool: 下载成功返回 True。
    """
    proc = subprocess.run(
        [
            "curl", "-sS", "-C", "-", "-L", "--http1.1",
            "--retry", "5", "--retry-all-errors", "--retry-delay", "3",
            "-o", str(dest), url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def lmstudio_download_models(
    repo: str,
    *,
    models_dir: str | Path | None = None,
    mirror: str = DEFAULT_MIRROR,
    check_only: bool = False,
) -> dict:
    """下载单个 LM Studio 模型到模型目录。

    Args:
        repo: 模型 ID（HF 仓库格式 ``作者/仓库``），例如 ``mlx-community/Llama-3.3-70B-Instruct-4bit``。
        models_dir: 模型根目录；默认 ``~/.lmstudio/models``。
        mirror: 镜像根地址；默认 hf-mirror.com。
        check_only: 仅查询信息不下载（等价于 --list 单模型）。

    Returns:
        dict: 结果摘要，含 repo、dest、files、succeeded、failed 等字段。

    Examples:
        >>> lmstudio_download_models("mlx-community/Llama-3.3-70B-Instruct-4bit", check_only=True)  # noqa: E501
        {'repo': ..., 'check_only': True, ...}
    """
    if "/" not in repo:
        raise ValueError(f"模型 ID 必须是『作者/仓库』格式，例如 mlx-community/Qwen3-235B-A22B-GGUF，收到: {repo!r}")
    dest_root = _resolve_models_dir(models_dir)
    author, name = repo.split("/", 1)
    dest = dest_root / author / name

    files = _fetch_repo_files(repo, mirror)
    targets = _select_files(repo, files)
    if not targets:
        raise RuntimeError(f"仓库 {repo} 没有可下载的权重/配置文件")

    total_size = sum(f.get("size", 0) or 0 for f in files)
    summary: dict = {
        "repo": repo,
        "dest": str(dest),
        "file_count": len(targets),
        "total_bytes": total_size,
        "total_gb": round(total_size / 1024**3, 2),
    }
    if check_only:
        summary["check_only"] = True
        summary["files"] = targets
        return summary

    dest.mkdir(parents=True, exist_ok=True)
    succeeded: list[str] = []
    failed: list[str] = []

    # 并行下载（模拟 shell 后台并行，简化：按文件逐个，curl 内部已多连接）
    for fname in targets:
        fdir = Path(fname).parent
        if str(fdir) != ".":
            (dest / fdir).mkdir(parents=True, exist_ok=True)
        url = f"{mirror}/{repo}/resolve/main/{fname}"
        if _download_file(url, dest / fname):
            succeeded.append(fname)
        else:
            failed.append(fname)

    summary["succeeded"] = succeeded
    summary["failed"] = failed
    summary["success"] = not failed
    return summary


def lmstudio_download_from_list(
    *,
    models_dir: str | Path | None = None,
    mirror: str = DEFAULT_MIRROR,
    check_only: bool = False,
) -> dict:
    """按清单文件批量下载模型。

    清单文件位置：``autodokit/tools/lmstudio_download/models_list.txt``。
    每行一个模型 ID，支持 ``#`` 注释与空行。

    Args:
        models_dir: 模型根目录；默认 ``~/.lmstudio/models``。
        mirror: 镜像根地址。
        check_only: 仅列出清单与大小，不下载。

    Returns:
        dict: 批量下载结果，含 models、succeeded、failed 等字段。
    """
    list_file = Path(__file__).resolve().parent / "lmstudio_download" / "models_list.txt"
    if not list_file.exists():
        raise FileNotFoundError(f"清单文件不存在: {list_file}")
    repos = [
        line.strip()
        for line in list_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    results: list[dict] = []
    for repo in repos:
        try:
            r = lmstudio_download_models(repo, models_dir=models_dir, mirror=mirror, check_only=check_only)
            results.append(r)
        except Exception as exc:
            results.append({"repo": repo, "error": str(exc), "success": False})

    summary = {
        "list_file": str(list_file),
        "total": len(results),
        "succeeded": [r["repo"] for r in results if r.get("success")],
        "failed": [r["repo"] for r in results if not r.get("success")],
        "models": results,
    }
    return summary


def lmstudio_download_list_models(*, models_dir: str | Path | None = None, mirror: str = DEFAULT_MIRROR) -> dict:
    """列出清单中所有模型及其大小。

    Args:
        models_dir: 模型根目录。
        mirror: 镜像根地址。

    Returns:
        dict: 模型清单摘要。
    """
    return lmstudio_download_from_list(models_dir=models_dir, mirror=mirror, check_only=True)


def lmstudio_download_ensure_curl() -> bool:
    """检查系统是否可用 curl。

    Returns:
        bool: curl 可用返回 True。
    """
    return shutil.which("curl") is not None
