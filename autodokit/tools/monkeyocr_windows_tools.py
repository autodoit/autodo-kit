"""MonkeyOCR Windows GPU 解析工具。

本模块把 Windows 原生运行 MonkeyOCR 的关键步骤封装为 AOK tools：

1. 准备运行时依赖；
2. 下载或复用模型权重；
3. 生成本地配置文件；
4. 以 CUDA/GPU 路线运行单篇 PDF 解析；
5. 实时收集日志与输出产物。

说明：
- 所有路径参数都要求最终解析为绝对路径。
- 模块只做工具编排，不在导入阶段执行重依赖初始化。
- 对 Windows + Python 3.13 场景，MonkeyOCR 主仓库当前已加上 FlashAttention2 不可用时的 SDPA 回退。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import shutil
from pathlib import Path
from typing import Any


DEFAULT_MODEL_NAME = "MonkeyOCR-pro-1.2B"


def _resolve_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    return resolved


def _run_command(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    log_path: Path | None = None,
    stream_output: bool = True,
    env: dict[str, str] | None = None,
) -> None:
    if stream_output:
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        log_file = None
        try:
            if log_path is not None:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_file = log_path.open("a", encoding="utf-8")

            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="")
                if log_file is not None:
                    log_file.write(line)

            return_code = process.wait()
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, cmd)
        finally:
            if log_file is not None:
                log_file.close()
    else:
        subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True, env=env)


def _detect_gpu_name() -> str | None:
    try:
        import torch  # type: ignore

        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            return str(torch.cuda.get_device_name(0))
    except Exception:
        return None
    return None


def _build_local_config_text(models_dir: Path, device: str) -> str:
    return f"""device: {device}
weights:
  PP-DocLayoutV2: Structure/PP-DocLayoutV2
  layoutreader: Relation
models_dir: {models_dir.as_posix()}
layout_config:
  model: PP-DocLayoutV2
  reader:
    name: layoutreader
chat_config:
  weight_path: Recognition
  backend: transformers
  batch_size: 2
"""


def _write_local_config(config_path: Path, models_dir: Path, device: str) -> Path:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_build_local_config_text(models_dir, device), encoding="utf-8")
    return config_path


def _has_required_weights(models_dir: Path) -> bool:
    required = [
        models_dir / "Recognition",
        models_dir / "Relation",
        models_dir / "Structure" / "PP-DocLayoutV2",
    ]
    return all(path.exists() for path in required)


def prepare_monkeyocr_windows_runtime(
    monkeyocr_root: str | Path,
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    download_source: str = "huggingface",
    python_executable: str | Path | None = None,
    pip_index_url: str | None = None,
    install_triton_windows: bool = True,
    models_dir: str | Path | None = None,
) -> dict[str, Any]:
    """准备 MonkeyOCR Windows 运行时。

    Args:
        monkeyocr_root: MonkeyOCR 仓库根目录。
        model_name: 模型名称，默认 `MonkeyOCR-pro-1.2B`。
        download_source: `huggingface` 或 `modelscope`。
        python_executable: 指定 Python 可执行文件；默认使用当前解释器。
        pip_index_url: 可选 pip 镜像地址，例如清华源。
        install_triton_windows: 是否安装 `triton-windows<3.4`。

    Returns:
        dict[str, Any]: 包含安装命令与模型下载状态的摘要。
    """

    root = _resolve_path(monkeyocr_root)
    python = str(python_executable or sys.executable)
    results: dict[str, Any] = {
        "monkeyocr_root": str(root),
        "python_executable": python,
        "model_name": model_name,
        "download_source": download_source,
        "pip_index_url": pip_index_url,
        "install_triton_windows": bool(install_triton_windows),
        "steps": [],
    }
    target_models_dir = _resolve_path(models_dir) if models_dir is not None else (root / "model_weight").resolve()
    official_models_dir = (root / "model_weight").resolve()

    pip_cmd = [python, "-m", "pip", "install", "-U"]
    if pip_index_url:
        pip_cmd.extend(["-i", pip_index_url])

    _run_command(pip_cmd + ["huggingface_hub"], cwd=root)
    results["steps"].append({"action": "pip_install", "package": "huggingface_hub"})

    if download_source.lower() == "modelscope":
        _run_command(pip_cmd + ["modelscope"], cwd=root)
        results["steps"].append({"action": "pip_install", "package": "modelscope"})

    if install_triton_windows:
        _run_command(pip_cmd + ["triton-windows<3.4"], cwd=root)
        results["steps"].append({"action": "pip_install", "package": 'triton-windows<3.4'})

    download_args = [python, "tools/download_model.py"]
    if download_source.lower() == "modelscope":
        download_args.extend(["-t", "modelscope"])
    download_args.extend(["-n", model_name])
    _run_command(download_args, cwd=root)
    results["steps"].append({"action": "download_model", "source": download_source, "model_name": model_name})

    if target_models_dir != official_models_dir:
        target_models_dir.mkdir(parents=True, exist_ok=True)
        if not _has_required_weights(target_models_dir) and _has_required_weights(official_models_dir):
            for child in official_models_dir.iterdir():
                dest = target_models_dir / child.name
                if dest.exists():
                    continue
                if child.is_dir():
                    shutil.copytree(child, dest)
                else:
                    shutil.copy2(child, dest)
            results["steps"].append({"action": "copy_model_weight", "from": str(official_models_dir), "to": str(target_models_dir)})

    results["model_dir"] = str(target_models_dir)
    results["official_model_dir"] = str(official_models_dir)
    results["weights_ready"] = _has_required_weights(target_models_dir)
    return results


def run_monkeyocr_windows_single_pdf(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    monkeyocr_root: str | Path,
    models_dir: str | Path | None = None,
    config_path: str | Path | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    device: str = "cuda",
    gpu_visible_devices: str = "0",
    ensure_runtime: bool = True,
    download_source: str = "huggingface",
    pip_index_url: str | None = None,
    python_executable: str | Path | None = None,
    log_path: str | Path | None = None,
    stream_output: bool = True,
) -> dict[str, Any]:
    """运行 MonkeyOCR Windows 单篇 PDF 解析。

    Args:
        input_pdf: 待解析 PDF 的绝对路径。
        output_dir: 解析输出根目录。
        monkeyocr_root: MonkeyOCR 仓库根目录。
        models_dir: 模型权重目录；默认使用 `monkeyocr_root/model_weight`。
        config_path: 本地配置文件路径；默认使用 `output_dir.parent/model_configs.local.yaml`。
        model_name: 模型名称。
        device: `cuda` / `cpu` / `mps`。
        gpu_visible_devices: CUDA 可见设备号，默认 `0`。
        ensure_runtime: 是否自动执行运行时准备（pip + model download）。
        download_source: `huggingface` 或 `modelscope`。
        pip_index_url: 可选 pip 镜像。
        python_executable: 指定 Python 可执行文件。
        log_path: 运行日志文件路径；默认 `output_dir.parent/parse_direct_run.log`。
        stream_output: 是否流式输出 parse.py 日志。

    Returns:
        dict[str, Any]: 运行结果摘要，包含状态、产物与配置文件路径。
    """

    python = str(python_executable or sys.executable)
    pdf_path = _resolve_path(input_pdf)
    out_dir = _resolve_path(output_dir)
    root = _resolve_path(monkeyocr_root)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"输入 PDF 不存在：{pdf_path}")
    if not root.exists():
        raise FileNotFoundError(f"MonkeyOCR 根目录不存在：{root}")
    out_dir.mkdir(parents=True, exist_ok=True)

    target_models_dir = _resolve_path(models_dir or (root / "model_weight"))
    target_config_path = _resolve_path(config_path or (out_dir.parent / "model_configs.local.yaml"))
    target_log_path = _resolve_path(log_path or (out_dir.parent / "parse_direct_run.log"))

    if ensure_runtime:
        prepare_monkeyocr_windows_runtime(
            root,
            model_name=model_name,
            download_source=download_source,
            python_executable=python,
            pip_index_url=pip_index_url,
            install_triton_windows=True,
            models_dir=target_models_dir,
        )

    _write_local_config(target_config_path, target_models_dir, device)

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["MONKEYOCR_DEVICE"] = device
    env["CUDA_VISIBLE_DEVICES"] = gpu_visible_devices
    env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

    cmd = [
        python,
        "-u",
        "parse.py",
        str(pdf_path),
        "-o",
        str(out_dir),
        "-c",
        str(target_config_path),
    ]

    images_dir = (out_dir / pdf_path.stem / "images").resolve()
    images_dir.mkdir(parents=True, exist_ok=True)

    stop_event = threading.Event()

    def _monitor_progress() -> None:
        last_count = -1
        while not stop_event.is_set():
            try:
                count = len(list(images_dir.glob("*.jpg"))) + len(list(images_dir.glob("*.png")))
                if count != last_count:
                    print(f"[PROGRESS] Exported page images: {count}")
                    last_count = count
            except Exception:
                pass
            stop_event.wait(3.0)

    monitor_thread = threading.Thread(target=_monitor_progress, daemon=True)
    monitor_thread.start()

    try:
        _run_command(cmd, cwd=root, log_path=target_log_path, stream_output=stream_output)
    finally:
        stop_event.set()
        monitor_thread.join(timeout=2.0)

    result_output_dir = (out_dir / pdf_path.stem).resolve()
    artifacts: dict[str, Any] = {
        "markdown": str(result_output_dir / f"{pdf_path.stem}.md"),
        "content_list": str(result_output_dir / f"{pdf_path.stem}_content_list.json"),
        "middle_json": str(result_output_dir / f"{pdf_path.stem}_middle.json"),
        "model_pdf": str(result_output_dir / f"{pdf_path.stem}_model.pdf"),
        "layout_pdf": str(result_output_dir / f"{pdf_path.stem}_layout.pdf"),
        "spans_pdf": str(result_output_dir / f"{pdf_path.stem}_spans.pdf"),
        "images_dir": str(result_output_dir / "images"),
        "log_path": str(target_log_path),
        "config_path": str(target_config_path),
        "models_dir": str(target_models_dir),
    }

    return {
        "status": "SUCCEEDED",
        "device": device,
        "gpu_name": _detect_gpu_name(),
        "model_name": model_name,
        "input_pdf": str(pdf_path),
        "output_dir": str(result_output_dir),
        "artifacts": artifacts,
    }
