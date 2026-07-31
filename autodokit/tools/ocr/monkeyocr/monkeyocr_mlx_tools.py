"""MonkeyOCR MLX (Apple Silicon) 解析工具。

本模块把 macOS Apple Silicon 上通过 MLX-VLM 运行 MonkeyOCR 的
关键步骤封装为 AOK tools：

1. 检测 MLX 环境是否就绪；
2. 安装/验证 mlx-vlm 依赖；
3. 准备 MonkeyOCR 运行时（复用 third_party 副本）；
4. 以 MLX/Metal GPU 路线运行单篇 PDF 解析；
5. 收集日志与输出产物。

说明：
- 仅适用于 macOS ARM64 (Apple Silicon)，Intel Mac 请走 CPU 回退。
- 使用 Jimmi42/MonkeyOCR-Apple-Silicon 社区移植版的核心思路：
  以 MLX-VLM 替代 lmdeploy 作为 VLM 推理后端，直接调用 Apple GPU。
- 输出契约与 monkeyocr_windows_tools.py 保持一致。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from autodokit.tools.ocr.monkeyocr.schemes import DEFAULT_MODEL_NAME


def _resolve_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _resolve_monkeyocr_root_dir(monkeyocr_root: str | Path) -> Path:
    """查找 MonkeyOCR 运行时根目录。

    优先查找 parse.py 存在的目录，兼容 MonkeyOCR-Apple-Silicon 和
    官方 MonkeyOCR 两种目录结构。
    """

    root = _resolve_path(monkeyocr_root)
    if (root / "parse.py").exists():
        return root
    nested = (root / "MonkeyOCR-main").resolve()
    if (nested / "parse.py").exists():
        return nested
    nested_mlx = (root / "MonkeyOCR").resolve()
    if (nested_mlx / "parse.py").exists():
        return nested_mlx
    raise FileNotFoundError(f"MonkeyOCR 根目录不存在或缺少 parse.py：{root}")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _run_command(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    log_path: Path | None = None,
    stream_output: bool = True,
    env: dict[str, str] | None = None,
) -> None:
    """执行命令，可选日志输出。"""

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


def _check_mlx_available() -> dict[str, Any]:
    """检测 MLX 和 mlx-vlm 是否可用。

    Returns:
        包含 installed、version、message 等字段的诊断信息。
    """

    result: dict[str, Any] = {
        "mlx_installed": False,
        "mlx_vlm_installed": False,
        "platform": sys.platform,
        "is_apple_silicon": False,
    }

    # 检查是否为 Apple Silicon
    if sys.platform == "darwin":
        try:
            uname = subprocess.run(
                ["uname", "-m"],
                capture_output=True,
                text=True,
                check=False,
            )
            arch = uname.stdout.strip()
            result["is_apple_silicon"] = arch in ("arm64", "aarch64")
        except Exception:
            pass

    # 检查 mlx
    try:
        import mlx.core  # type: ignore[import-untyped]  # noqa: F401

        result["mlx_installed"] = True
    except ImportError:
        pass

    # 检查 mlx-vlm
    try:
        import mlx_vlm  # type: ignore[import-untyped]  # noqa: F401

        result["mlx_vlm_installed"] = True
    except ImportError:
        pass

    result["ready"] = result["mlx_installed"] and result["mlx_vlm_installed"]
    return result


def prepare_monkeyocr_mlx_runtime(
    monkeyocr_root: str | Path,
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    download_source: str = "huggingface",
    python_executable: str | Path | None = None,
    pip_index_url: str | None = None,
    models_dir: str | Path | None = None,
) -> dict[str, Any]:
    """准备 MonkeyOCR MLX 运行时。

    安装 mlx、mlx-vlm 等依赖，并下载 MonkeyOCR 模型权重。

    Args:
        monkeyocr_root: MonkeyOCR 仓库根目录。
        model_name: 模型名称，默认 `MonkeyOCR-pro-1.2B`。
        download_source: `huggingface` 或 `modelscope`。
        python_executable: 指定 Python 可执行文件。
        pip_index_url: 可选 pip 镜像地址。
        models_dir: 模型权重目录；默认 `monkeyocr_root/model_weight`。

    Returns:
        包含安装步骤与模型状态的摘要。
    """

    root = _resolve_monkeyocr_root_dir(monkeyocr_root)
    python = str(python_executable or sys.executable)
    results: dict[str, Any] = {
        "monkeyocr_root": str(root),
        "python_executable": python,
        "model_name": model_name,
        "download_source": download_source,
        "pip_index_url": pip_index_url,
        "steps": [],
    }

    target_models_dir = (
        _resolve_path(models_dir) if models_dir is not None
        else (root / "model_weight").resolve()
    )

    pip_cmd = [python, "-m", "pip", "install", "-U"]
    if pip_index_url:
        pip_cmd.extend(["-i", pip_index_url])

    # 安装 MLX 框架
    mlx_check = _check_mlx_available()
    if not mlx_check["mlx_installed"]:
        _run_command(pip_cmd + ["mlx>=0.16.0"], cwd=root)
        results["steps"].append({"action": "pip_install", "package": "mlx"})

    if not mlx_check["mlx_vlm_installed"]:
        _run_command(pip_cmd + ["mlx-vlm"], cwd=root)
        results["steps"].append({"action": "pip_install", "package": "mlx-vlm"})

    # 安装 huggingface_hub 用于下载模型
    _run_command(pip_cmd + ["huggingface_hub>=0.30.0,<1.0"], cwd=root)
    results["steps"].append({"action": "pip_install", "package": "huggingface_hub"})

    if download_source.lower() == "modelscope":
        _run_command(pip_cmd + ["modelscope"], cwd=root)
        results["steps"].append({"action": "pip_install", "package": "modelscope"})

    # 下载模型权重
    official_models_dir = (root / "model_weight").resolve()
    download_args = [python, "tools/download_model.py"]
    if download_source.lower() == "modelscope":
        download_args.extend(["-t", "modelscope"])
    download_args.extend(["-n", model_name])

    try:
        _run_command(download_args, cwd=root)
        results["steps"].append({
            "action": "download_model",
            "source": download_source,
            "model_name": model_name,
        })
    except Exception:
        # 模型可能已存在，非致命
        results["steps"].append({
            "action": "download_model_skipped",
            "source": download_source,
            "model_name": model_name,
            "note": "模型可能已存在或下载工具不可用",
        })

    # 如果 models_dir 指向不同位置，尝试复制权重
    if target_models_dir != official_models_dir:
        target_models_dir.mkdir(parents=True, exist_ok=True)
        recognition_path = target_models_dir / "Recognition"
        if not recognition_path.exists() and (official_models_dir / "Recognition").exists():
            import shutil
            for child in official_models_dir.iterdir():
                dest = target_models_dir / child.name
                if dest.exists():
                    continue
                if child.is_dir():
                    shutil.copytree(child, dest)
                else:
                    shutil.copy2(child, dest)
            results["steps"].append({
                "action": "copy_model_weight",
                "from": str(official_models_dir),
                "to": str(target_models_dir),
            })

    results["model_dir"] = str(target_models_dir)
    results["mlx_ready"] = _check_mlx_available()["ready"]
    return results


def _build_mlx_config_text(models_dir: Path) -> str:
    """生成适配 MLX 后端的配置文件内容。

    MLX 后端的关键差异：
    - device: mlx (使用 Apple Metal GPU)
    - chat_config.backend: mlx (替换 transformers/lmdeploy)
    """

    return f"""device: mlx
weights:
    doclayout_yolo: Structure/doclayout_yolo_docstructbench_imgsz1280_2501.pt
  layoutreader: Relation
models_dir: {models_dir.as_posix()}
layout_config:
    model: doclayout_yolo
  reader:
    name: layoutreader
chat_config:
  weight_path: Recognition
  backend: mlx
  batch_size: 1
"""


def _write_mlx_config(config_path: Path, models_dir: Path) -> Path:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_build_mlx_config_text(models_dir), encoding="utf-8")
    return config_path


def run_monkeyocr_mlx_single_pdf(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    output_name: str | None = None,
    monkeyocr_root: str | Path,
    models_dir: str | Path | None = None,
    config_path: str | Path | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    ensure_runtime: bool = True,
    download_source: str = "huggingface",
    pip_index_url: str | None = None,
    python_executable: str | Path | None = None,
    log_path: str | Path | None = None,
    stream_output: bool = True,
) -> dict[str, Any]:
    """以 MLX (Apple Silicon GPU) 路线解析单篇 PDF。

    Args:
        input_pdf: 待解析 PDF 的绝对路径。
        output_dir: 解析输出根目录。
        output_name: 可选输出目录名；默认使用输入 PDF 的 stem。
        monkeyocr_root: MonkeyOCR 仓库根目录。
        models_dir: 模型权重目录；默认 `monkeyocr_root/model_weight`。
        config_path: 本地配置文件路径。
        model_name: 模型名称。
        ensure_runtime: 是否自动执行运行时准备。
        download_source: `huggingface` 或 `modelscope`。
        pip_index_url: 可选 pip 镜像。
        python_executable: 指定 Python 可执行文件。
        log_path: 运行日志文件路径。
        stream_output: 是否流式输出 parse.py 日志。

    Returns:
        dict[str, Any]: 运行结果摘要，包含状态、产物与配置文件路径。

    Raises:
        RuntimeError: MLX 环境未就绪。
        FileNotFoundError: 输入 PDF 不存在。
    """

    python = str(python_executable or sys.executable)
    pdf_path = _resolve_path(input_pdf)
    out_dir = _resolve_path(output_dir)
    root = _resolve_monkeyocr_root_dir(monkeyocr_root)

    # 前置检测：MLX 环境
    mlx_check = _check_mlx_available()
    if not mlx_check["ready"]:
        missing = []
        if not mlx_check["mlx_installed"]:
            missing.append("mlx")
        if not mlx_check["mlx_vlm_installed"]:
            missing.append("mlx-vlm")
        raise RuntimeError(
            f"MLX 环境未就绪：缺少 {', '.join(missing)}。"
            " 请运行 prepare_monkeyocr_mlx_runtime() 初始化。"
        )
    if not mlx_check["is_apple_silicon"]:
        raise RuntimeError(
            "MLX 后端仅适用于 Apple Silicon (ARM64) Mac。"
            " 当前设备不支持，请使用 CPU 回退。"
        )

    if not pdf_path.is_file():
        raise FileNotFoundError(f"输入 PDF 不存在：{pdf_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    target_models_dir = _resolve_path(models_dir or (root / "model_weight"))
    target_config_path = _resolve_path(config_path or (out_dir.parent / "model_configs.mlx.local.yaml"))
    target_log_path = _resolve_path(log_path or (out_dir.parent / "parse_mlx_run.log"))

    if ensure_runtime:
        prepare_monkeyocr_mlx_runtime(
            root,
            model_name=model_name,
            download_source=download_source,
            python_executable=python,
            pip_index_url=pip_index_url,
            models_dir=target_models_dir,
        )

    # 生成 MLX 配置
    _write_mlx_config(target_config_path, target_models_dir)

    # 设置环境变量
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["MONKEYOCR_DEVICE"] = "mlx"
    env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    # MLX 不需要 CUDA_VISIBLE_DEVICES
    env.pop("CUDA_VISIBLE_DEVICES", None)

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

    # 进度监控（复用 Windows 工具的逻辑）
    images_dir = (out_dir / pdf_path.stem / "images").resolve()
    images_dir.mkdir(parents=True, exist_ok=True)

    stop_event = threading.Event()

    def _monitor_progress() -> None:
        last_count = -1
        while not stop_event.is_set():
            try:
                count = len(list(images_dir.glob("*.jpg"))) + len(list(images_dir.glob("*.png")))
                if count != last_count:
                    print(f"[MLX PROGRESS] Exported page images: {count}")
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

    # 收集产物
    result_output_dir = (out_dir / pdf_path.stem).resolve()
    output_stem = result_output_dir.name

    # 如果有显式 output_name，重命名产物树
    requested_output_name = _stringify(output_name)
    if requested_output_name:
        requested_output_stem = Path(requested_output_name).stem.strip()
        if requested_output_stem and requested_output_stem != pdf_path.stem:
            result_output_dir = _rename_output_tree_to_original_stem(
                result_output_dir,
                requested_output_stem,
                pdf_path.stem,
            )
            output_stem = result_output_dir.name

    artifacts: dict[str, Any] = {
        "markdown": str(result_output_dir / f"{output_stem}.md"),
        "content_list": str(result_output_dir / f"{output_stem}_content_list.json"),
        "middle_json": str(result_output_dir / f"{output_stem}_middle.json"),
        "model_pdf": str(result_output_dir / f"{output_stem}_model.pdf"),
        "layout_pdf": str(result_output_dir / f"{output_stem}_layout.pdf"),
        "spans_pdf": str(result_output_dir / f"{output_stem}_spans.pdf"),
        "images_dir": str(result_output_dir / "images"),
        "log_path": str(target_log_path),
        "config_path": str(target_config_path),
        "models_dir": str(target_models_dir),
    }

    return {
        "status": "SUCCEEDED",
        "device": "mlx",
        "gpu_name": "Apple Silicon (MLX)",
        "model_name": model_name,
        "backend": "mlx",
        "input_pdf": str(pdf_path),
        "output_dir": str(result_output_dir),
        "artifacts": artifacts,
    }


def _rename_output_tree_to_original_stem(
    result_output_dir: Path,
    original_stem: str,
    alias_stem: str,
) -> Path:
    """将 MonkeyOCR 产物目录从别名回写到原始文件名。

    与 monkeyocr_windows_tools 中的同名函数保持逻辑一致。
    """

    import shutil

    result_output_dir = result_output_dir.resolve()
    original_output_dir = (result_output_dir.parent / original_stem).resolve()

    if alias_stem == original_stem:
        return result_output_dir

    if original_output_dir.exists() and original_output_dir != result_output_dir:
        if original_output_dir.is_dir():
            shutil.rmtree(original_output_dir)
        else:
            original_output_dir.unlink()

    if result_output_dir.exists() and result_output_dir != original_output_dir:
        result_output_dir.rename(original_output_dir)
    else:
        original_output_dir.mkdir(parents=True, exist_ok=True)

    if not original_output_dir.exists():
        return original_output_dir

    for path in sorted(original_output_dir.rglob("*"), reverse=True):
        if not path.is_file():
            continue
        name = path.name
        if alias_stem not in name:
            continue
        new_name = name.replace(alias_stem, original_stem)
        if new_name == name:
            continue
        target = path.with_name(new_name)
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        path.rename(target)

    return original_output_dir


__all__ = [
    "prepare_monkeyocr_mlx_runtime",
    "run_monkeyocr_mlx_single_pdf",
    "_check_mlx_available",
]
