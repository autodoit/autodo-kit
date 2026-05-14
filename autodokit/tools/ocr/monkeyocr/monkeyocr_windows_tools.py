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

import json
import os
import time
import subprocess
import sys
import threading
import shutil
import csv
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from autodokit.tools.atomic.path.windows_long_filename_tools import materialize_short_alias


DEFAULT_MODEL_NAME = "MonkeyOCR-pro-1.2B"
HUGGINGFACE_HUB_REQUIREMENT = "huggingface_hub>=0.30.0,<1.0"


def _resolve_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    return resolved


def _resolve_monkeyocr_root_dir(monkeyocr_root: str | Path) -> Path:
    root = _resolve_path(monkeyocr_root)
    if (root / "parse.py").exists():
        return root
    nested = (root / "MonkeyOCR-main").resolve()
    if (nested / "parse.py").exists():
        return nested
    raise FileNotFoundError(f"MonkeyOCR 根目录不存在或缺少 parse.py：{root}")


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

    root = _resolve_monkeyocr_root_dir(monkeyocr_root)
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

    _run_command(pip_cmd + [HUGGINGFACE_HUB_REQUIREMENT], cwd=root)
    results["steps"].append({"action": "pip_install", "package": HUGGINGFACE_HUB_REQUIREMENT})

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
    root = _resolve_monkeyocr_root_dir(monkeyocr_root)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"输入 PDF 不存在：{pdf_path}")
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
    # Prevent Windows GBK console encoding from crashing parse.py on emoji prints.
    env["PYTHONIOENCODING"] = "utf-8"
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

def _rename_output_tree_to_original_stem(result_output_dir: Path, original_stem: str, alias_stem: str) -> Path:
    """将 MonkeyOCR 产物目录从别名回写到原始文件名。"""

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


def _expected_output_artifacts(output_root: Path, stem: str) -> dict[str, Path]:
    file_output_dir = (output_root / stem).resolve()
    return {
        "output_dir": file_output_dir,
        "markdown": file_output_dir / f"{stem}.md",
        "content_list": file_output_dir / f"{stem}_content_list.json",
        "middle_json": file_output_dir / f"{stem}_middle.json",
        "images_dir": file_output_dir / "images",
    }


def _is_existing_parse_completed(output_root: Path, stem: str) -> bool:
    """判断某个 PDF 是否已完成解析，可用于中断后续跑跳过。"""

    artifacts = _expected_output_artifacts(output_root, stem)
    required_files = [
        artifacts["markdown"],
        artifacts["content_list"],
    ]
    for path in required_files:
        if not path.exists() or path.stat().st_size == 0:
            return False
    if not artifacts["images_dir"].exists():
        return False
    return True


def _is_subpath(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def _validate_runtime_path_not_in_output(output_dir: Path, runtime_path: Path, name: str) -> None:
    if output_dir == runtime_path or _is_subpath(output_dir, runtime_path):
        raise ValueError(
            f"{name} must be outside output_dir. output_dir={output_dir}, {name}={runtime_path}"
        )


def _read_file_list_candidate_rows(file_list: Path) -> list[list[str]]:
    suffix = file_list.suffix.lower()
    if suffix == ".txt":
        lines = file_list.read_text(encoding="utf-8", errors="replace").splitlines()
        return [[line.strip()] for line in lines if line.strip() and not line.strip().startswith("#")]

    if suffix == ".json":
        payload = json.loads(file_list.read_text(encoding="utf-8"))
        rows: list[list[str]] = []
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, str):
                    value = item.strip()
                    if value:
                        rows.append([value])
                elif isinstance(item, (list, tuple)):
                    row = [str(value).strip() for value in item if str(value).strip()]
                    if row:
                        rows.append(row)
                elif isinstance(item, dict):
                    row: list[str] = []
                    for key in ("pdf", "pdf_path", "path", "file", "filename", "文件", "文件名"):
                        value = item.get(key)
                        if isinstance(value, str) and value.strip():
                            row.append(value.strip())
                    if row:
                        rows.append(row)
        return rows

    rows: list[list[str]] = []
    with file_list.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            stream.seek(0)
            raw_reader = csv.reader(stream)
            for row in raw_reader:
                if not row:
                    continue
                values = [str(cell).strip() for cell in row if str(cell).strip()]
                if values:
                    rows.append(values)
            return rows

        preferred = ["pdf", "pdf_path", "path", "file", "filename", "input", "title", "name", "文件", "文件名", "文献文件", "文献标题", "标题"]
        ordered_fields: list[str] = []
        lowered = {name.lower(): name for name in reader.fieldnames if name is not None}
        for key in preferred:
            field = lowered.get(key.lower())
            if field is not None and field not in ordered_fields:
                ordered_fields.append(field)
        for field in reader.fieldnames:
            if field is not None and field not in ordered_fields:
                ordered_fields.append(field)

        for row in reader:
            values: list[str] = []
            for field in ordered_fields:
                value = str(row.get(field, "") or "").strip()
                if value:
                    values.append(value)
            if values:
                rows.append(values)
    return rows


def _resolve_pdf_candidate(input_dir: Path, value: str) -> Path | None:
    cleaned = value.strip().strip('"').strip("'").strip("`")
    looks_like_windows_path = "\\" in cleaned or (":" in cleaned and not cleaned.startswith("/"))
    raw = Path(cleaned).expanduser()
    candidates = []

    if looks_like_windows_path:
        try:
            windows_path = PureWindowsPath(cleaned)
            candidates.append(input_dir / windows_path.name)
            if len(windows_path.parts) >= 2:
                candidates.append(input_dir / Path(*windows_path.parts[-2:]))
        except Exception:
            pass

    if not looks_like_windows_path:
        if raw.is_absolute():
            candidates.append(raw)
        else:
            candidates.append(input_dir / raw)

        if raw.suffix.lower() != ".pdf":
            if raw.is_absolute():
                candidates.append(raw.with_suffix(".pdf"))
            else:
                candidates.append((input_dir / raw).with_suffix(".pdf"))

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if resolved.exists() and resolved.is_file():
                return resolved
        except OSError:
            continue

    def _normalize_name(text: str) -> str:
        return "".join(ch.lower() for ch in text if ch.isalnum())

    wanted = _normalize_name(raw.stem)
    if wanted:
        for candidate in sorted(input_dir.glob("*.pdf")):
            if _normalize_name(candidate.stem) == wanted:
                return candidate.resolve()
    return None


def _move_with_suffix(src: Path, dst: Path) -> Path:
    target = dst
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        index = 1
        while True:
            candidate = target.with_name(f"{stem}_{index}{suffix}")
            if not candidate.exists():
                target = candidate
                break
            index += 1
    shutil.move(str(src), str(target))
    return target


def _migrate_legacy_output_root_artifacts(output_dir: Path, runtime_root: Path) -> list[str]:
    """迁移旧版遗留在输出根目录的中间产物，保证输出根目录纯净。"""

    migrated: list[str] = []
    legacy_root = runtime_root / "migrated_from_output_root"
    legacy_root.mkdir(parents=True, exist_ok=True)

    for child in sorted(output_dir.iterdir()):
        should_move = False
        if child.is_file():
            should_move = True
        elif child.is_dir() and child.name == "_tmp_input":
            should_move = True

        if not should_move:
            continue

        moved_to = _move_with_suffix(child, legacy_root / child.name)
        migrated.append(f"{child} -> {moved_to}")
    return migrated


def _build_batch_items(input_dir: Path, file_list: Path | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if file_list is None:
        for path in sorted(input_dir.iterdir()):
            if path.is_file() and path.suffix.lower() == ".pdf":
                items.append(
                    {
                        "source_type": "input_scan",
                        "source_value": str(path.name),
                        "input_pdf": path.resolve(),
                        "input_missing_reason": "",
                    }
                )
        return items

    resolved_file_list = _resolve_path(file_list)
    if not resolved_file_list.exists():
        raise FileNotFoundError(f"文件清单不存在：{resolved_file_list}")

    candidate_rows = _read_file_list_candidate_rows(resolved_file_list)
    for candidates in candidate_rows:
        resolved_pdf = None
        chosen_value = ""
        for candidate in candidates:
            resolved_pdf = _resolve_pdf_candidate(input_dir, candidate)
            chosen_value = candidate
            if resolved_pdf is not None:
                break

        if not chosen_value and candidates:
            chosen_value = candidates[0]

        items.append(
            {
                "source_type": "file_list",
                "source_value": chosen_value,
                "input_pdf": resolved_pdf,
                "input_missing_reason": "input_pdf_not_found" if resolved_pdf is None else "",
            }
        )
    return items


def _write_management_tables(records: list[dict[str, Any]], json_path: Path, csv_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    fieldnames = [
        "record_id",
        "source_type",
        "source_value",
        "input_pdf_path",
        "input_missing_reason",
        "file_name",
        "stem",
        "output_dir",
        "state",
        "attempts",
        "max_retries",
        "should_run",
        "artifacts_ok",
        "last_error",
        "last_exception_type",
        "last_result_status",
        "last_log_path",
        "last_duration_seconds",
        "round_index",
        "first_created_at",
        "last_updated_at",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def run_monkeyocr_windows_batch_folder(
    input_dir: str | Path,
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
    file_list: str | Path | None = None,
    intermediate_dir: str | Path | None = None,
    runtime_dir: str | Path | None = None,
    max_retries: int = 2,
    log_path: str | Path | None = None,
    log_dir: str | Path | None = None,
    stream_output: bool = False,
    alias_dir: str | Path | None = None,
    skip_existing: bool = True,
) -> dict[str, Any]:
    """批量解析文件夹中的全部 PDF，并在完成后将产物回写为原始文件名。

    Args:
        input_dir: 输入文件夹，只处理直接子文件，不递归。
        output_dir: 输出根目录。
        monkeyocr_root: MonkeyOCR 仓库根目录。
        models_dir: 模型权重目录。
        config_path: 本地配置文件路径。
        model_name: 模型名称。
        device: `cuda` / `cpu` / `mps`。
        gpu_visible_devices: CUDA 可见设备号。
        ensure_runtime: 是否自动准备运行时。
        download_source: 权重下载来源。
        pip_index_url: 可选 pip 镜像。
        python_executable: Python 可执行文件。
        file_list: 文件清单路径，支持 csv/txt/json。
        intermediate_dir: 中间产物目录（日志、报告、管理表、临时别名）。
        runtime_dir: 运行时目录（日志、报告、临时别名）；默认 `output_dir.parent/<output_dir.name>__runtime`。
        max_retries: 单文件最大尝试次数（包含首次执行）。
        log_path: 批处理总日志路径。
        log_dir: 单文件日志输出目录；默认 `runtime_dir/logs`。
        stream_output: 是否流式输出单篇解析日志。
        alias_dir: 临时别名文件目录；默认使用 `runtime_dir/_tmp_input`。
        skip_existing: 是否跳过已完成解析的文件；默认 `True`。

    Returns:
        dict[str, Any]: 批处理摘要，包含每个文件的状态、耗时与最终产物路径。
    """

    source_dir = Path(input_dir).expanduser().resolve()
    target_dir = Path(output_dir).expanduser().resolve()
    if max_retries < 1:
        raise ValueError(f"max_retries must be >= 1, got {max_retries}")
    if not source_dir.exists():
        raise FileNotFoundError(f"输入文件夹不存在：{source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"输入路径不是文件夹：{source_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)

    if intermediate_dir is not None and runtime_dir is not None:
        left = _resolve_path(intermediate_dir)
        right = _resolve_path(runtime_dir)
        if left != right:
            raise ValueError(f"intermediate_dir and runtime_dir point to different paths: {left} != {right}")

    runtime_value = intermediate_dir if intermediate_dir is not None else runtime_dir
    runtime_root = _resolve_path(runtime_value) if runtime_value is not None else (target_dir.parent / f"{target_dir.name}__runtime").resolve()
    _validate_runtime_path_not_in_output(target_dir, runtime_root, "runtime_root")

    runtime_root.mkdir(parents=True, exist_ok=True)

    migrated_output_artifacts = _migrate_legacy_output_root_artifacts(target_dir, runtime_root)

    alias_root = Path(alias_dir).expanduser().resolve() if alias_dir is not None else (runtime_root / "_tmp_input").resolve()
    logs_root = Path(log_dir).expanduser().resolve() if log_dir is not None else (runtime_root / "logs").resolve()
    _validate_runtime_path_not_in_output(target_dir, alias_root, "alias_root")
    _validate_runtime_path_not_in_output(target_dir, logs_root, "logs_root")
    logs_root.mkdir(parents=True, exist_ok=True)
    batch_log_path = Path(log_path).expanduser().resolve() if log_path is not None else (logs_root / "batch_monkeyocr.log").resolve()
    _validate_runtime_path_not_in_output(target_dir, batch_log_path.parent, "batch_log_parent")

    reports_root = runtime_root / "reports"
    _validate_runtime_path_not_in_output(target_dir, reports_root, "reports_root")
    reports_root.mkdir(parents=True, exist_ok=True)
    report_json = reports_root / "batch_report.json"
    report_csv = reports_root / "batch_report.csv"
    management_json = reports_root / "management_table.json"
    management_csv = reports_root / "management_table.csv"
    final_report_json = reports_root / "final_run_report.json"

    items = _build_batch_items(source_dir, Path(file_list) if file_list is not None else None)
    if not items:
        return {
            "status": "SUCCEEDED",
            "input_dir": str(source_dir),
            "output_dir": str(target_dir),
            "runtime_dir": str(runtime_root),
            "intermediate_dir": str(runtime_root),
            "total_duration_seconds": 0.0,
            "files": [],
            "report_json": str(report_json),
            "report_csv": str(report_csv),
            "management_json": str(management_json),
            "management_csv": str(management_csv),
            "final_report_json": str(final_report_json),
            "migrated_output_artifacts": migrated_output_artifacts,
            "log_path": str(batch_log_path),
        }

    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    management_records: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        pdf_path = item.get("input_pdf")
        if isinstance(pdf_path, Path):
            stem = pdf_path.stem
            file_name = pdf_path.name
            resolved_input = str(pdf_path)
        else:
            source_value = str(item.get("source_value", ""))
            pseudo_name = Path(source_value).name if source_value else f"entry_{index}"
            stem = Path(pseudo_name).stem or f"entry_{index}"
            file_name = pseudo_name
            resolved_input = ""

        output_path = str((target_dir / stem).resolve())
        missing_reason = str(item.get("input_missing_reason", "") or "")
        state = "pending" if resolved_input else "failed_final"
        should_run = bool(resolved_input)
        artifacts_ok = _is_existing_parse_completed(target_dir, stem) if should_run else False
        if should_run and skip_existing and artifacts_ok:
            state = "skipped_existing"
            should_run = False

        record: dict[str, Any] = {
            "record_id": index,
            "source_type": str(item.get("source_type", "input_scan")),
            "source_value": str(item.get("source_value", "")),
            "input_pdf_path": resolved_input,
            "input_missing_reason": missing_reason,
            "file_name": file_name,
            "stem": stem,
            "output_dir": output_path,
            "state": state,
            "attempts": 0,
            "max_retries": max_retries,
            "should_run": should_run,
            "artifacts_ok": artifacts_ok,
            "last_error": missing_reason,
            "last_exception_type": "",
            "last_result_status": "SKIPPED_ALREADY_PARSED" if state == "skipped_existing" else "NOT_STARTED",
            "last_log_path": "",
            "last_duration_seconds": 0.0,
            "round_index": 0,
            "first_created_at": now,
            "last_updated_at": now,
        }
        management_records.append(record)

    _write_management_tables(management_records, management_json, management_csv)

    total_start = time.perf_counter()
    round_index = 0

    while True:
        runnable = [
            record
            for record in management_records
            if bool(record.get("should_run"))
            and int(record.get("attempts", 0)) < int(record.get("max_retries", max_retries))
            and str(record.get("state")) in {"pending", "retryable_failed"}
        ]
        if not runnable:
            break

        round_index += 1
        for record in runnable:
            input_pdf_value = str(record.get("input_pdf_path", ""))
            if not input_pdf_value:
                record["state"] = "failed_final"
                record["should_run"] = False
                record["last_error"] = str(record.get("last_error") or "input_pdf_not_found")
                record["last_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
                _write_management_tables(management_records, management_json, management_csv)
                continue

            file_path = Path(input_pdf_value)
            record["state"] = "running"
            record["round_index"] = round_index
            record["attempts"] = int(record.get("attempts", 0)) + 1
            attempt_start = time.perf_counter()

            alias_result = materialize_short_alias(
                file_path,
                alias_root,
                prefix="doc",
                max_path_chars=200,
                max_name_chars=60,
            )
            single_log_path = logs_root / f"{alias_result.stem_to_use}.log"
            record["last_log_path"] = str(single_log_path)

            try:
                result = run_monkeyocr_windows_single_pdf(
                    input_pdf=alias_result.path_to_use,
                    output_dir=target_dir,
                    monkeyocr_root=monkeyocr_root,
                    models_dir=models_dir,
                    config_path=config_path,
                    model_name=model_name,
                    device=device,
                    gpu_visible_devices=gpu_visible_devices,
                    ensure_runtime=ensure_runtime,
                    download_source=download_source,
                    pip_index_url=pip_index_url,
                    python_executable=python_executable,
                    log_path=single_log_path,
                    stream_output=stream_output,
                )
                final_output_dir = _rename_output_tree_to_original_stem(
                    Path(result["output_dir"]),
                    file_path.stem,
                    alias_result.stem_to_use,
                )
                result["output_dir"] = str(final_output_dir)
                artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
                if artifacts:
                    artifacts["markdown"] = str(final_output_dir / f"{file_path.stem}.md")
                    artifacts["content_list"] = str(final_output_dir / f"{file_path.stem}_content_list.json")
                    artifacts["middle_json"] = str(final_output_dir / f"{file_path.stem}_middle.json")
                    artifacts["model_pdf"] = str(final_output_dir / f"{file_path.stem}_model.pdf")
                    artifacts["layout_pdf"] = str(final_output_dir / f"{file_path.stem}_layout.pdf")
                    artifacts["spans_pdf"] = str(final_output_dir / f"{file_path.stem}_spans.pdf")
                    artifacts["images_dir"] = str(final_output_dir / "images")
                    artifacts["log_path"] = str(single_log_path)

                artifacts_ok = _is_existing_parse_completed(target_dir, file_path.stem)
                record["artifacts_ok"] = artifacts_ok
                if artifacts_ok:
                    record["state"] = "success"
                    record["should_run"] = False
                    record["last_error"] = ""
                    record["last_exception_type"] = ""
                    record["last_result_status"] = str(result.get("status", "SUCCEEDED"))
                else:
                    record["last_result_status"] = str(result.get("status", "SUCCEEDED_MISSING_ARTIFACTS"))
                    record["last_error"] = "artifacts_missing_after_run"
                    record["last_exception_type"] = ""
                    if int(record["attempts"]) >= int(record["max_retries"]):
                        record["state"] = "failed_final"
                        record["should_run"] = False
                    else:
                        record["state"] = "retryable_failed"
                        record["should_run"] = True

            except Exception as exc:  # noqa: BLE001 - batch needs to continue after per-file failures
                artifacts_ok = _is_existing_parse_completed(target_dir, file_path.stem)
                record["artifacts_ok"] = artifacts_ok
                if artifacts_ok:
                    record["state"] = "success"
                    record["should_run"] = False
                    record["last_result_status"] = "SUCCEEDED_WITH_NONZERO_EXIT"
                    record["last_error"] = f"nonzero_exit_but_artifacts_exist: {exc}"
                    record["last_exception_type"] = exc.__class__.__name__
                else:
                    record["last_result_status"] = "FAILED"
                    record["last_error"] = str(exc)
                    record["last_exception_type"] = exc.__class__.__name__
                    if int(record["attempts"]) >= int(record["max_retries"]):
                        record["state"] = "failed_final"
                        record["should_run"] = False
                    else:
                        record["state"] = "retryable_failed"
                        record["should_run"] = True

            record["last_duration_seconds"] = time.perf_counter() - attempt_start
            record["last_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            _write_management_tables(management_records, management_json, management_csv)

    total_duration = time.perf_counter() - total_start

    batch_records: list[dict[str, Any]] = []
    failure_reasons: dict[str, int] = {}
    for record in management_records:
        state = str(record.get("state", ""))
        if state == "success":
            status = "ok"
            error = ""
        elif state == "skipped_existing":
            status = "skipped"
            error = "already_parsed"
        elif state == "failed_final":
            status = "error"
            error = str(record.get("last_error", "failed"))
            failure_reasons[error] = failure_reasons.get(error, 0) + 1
        else:
            status = "error"
            error = str(record.get("last_error", f"unexpected_state:{state}"))
            failure_reasons[error] = failure_reasons.get(error, 0) + 1

        batch_records.append(
            {
                "index": int(record.get("record_id", 0)),
                "input": str(record.get("input_pdf_path") or record.get("source_value") or ""),
                "used_input": str(record.get("input_pdf_path") or ""),
                "used_alias": False,
                "output_dir": str(record.get("output_dir", "")),
                "status": status,
                "error": error,
                "duration_seconds": float(record.get("last_duration_seconds", 0.0) or 0.0),
                "result": {
                    "status": str(record.get("last_result_status", "NOT_STARTED")),
                    "state": state,
                    "attempts": int(record.get("attempts", 0)),
                    "max_retries": int(record.get("max_retries", max_retries)),
                    "artifacts_ok": bool(record.get("artifacts_ok", False)),
                    "last_log_path": str(record.get("last_log_path", "")),
                },
            }
        )

    report_json.write_text(
        json.dumps(
            {
                "input_dir": str(source_dir),
                "output_dir": str(target_dir),
                "runtime_dir": str(runtime_root),
                "intermediate_dir": str(runtime_root),
                "rounds": round_index,
                "total_duration_seconds": total_duration,
                "files": batch_records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with report_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["index", "input", "used_input", "used_alias", "output_dir", "status", "duration_seconds", "error"])
        for record in batch_records:
            writer.writerow([
                record.get("index"),
                record.get("input"),
                record.get("used_input"),
                record.get("used_alias"),
                record.get("output_dir"),
                record.get("status"),
                f"{record.get('duration_seconds'):.3f}",
                record.get("error"),
            ])

    final_report = {
        "input_dir": str(source_dir),
        "output_dir": str(target_dir),
        "runtime_dir": str(runtime_root),
        "intermediate_dir": str(runtime_root),
        "rounds": round_index,
        "total_duration_seconds": total_duration,
        "total_entries": len(management_records),
        "success_count": sum(1 for r in management_records if str(r.get("state")) == "success"),
        "skipped_count": sum(1 for r in management_records if str(r.get("state")) == "skipped_existing"),
        "failed_final_count": sum(1 for r in management_records if str(r.get("state")) == "failed_final"),
        "failure_reasons": failure_reasons,
        "management_json": str(management_json),
        "management_csv": str(management_csv),
        "batch_report_json": str(report_json),
        "batch_report_csv": str(report_csv),
        "batch_log_path": str(batch_log_path),
        "migrated_output_artifacts": migrated_output_artifacts,
    }
    final_report_json.write_text(json.dumps(final_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    _write_management_tables(management_records, management_json, management_csv)

    has_error = any(str(record.get("state")) == "failed_final" for record in management_records)

    return {
        "status": "FAILED" if has_error else "SUCCEEDED",
        "input_dir": str(source_dir),
        "output_dir": str(target_dir),
        "runtime_dir": str(runtime_root),
        "intermediate_dir": str(runtime_root),
        "log_dir": str(logs_root),
        "rounds": round_index,
        "total_duration_seconds": total_duration,
        "files": batch_records,
        "report_json": str(report_json),
        "report_csv": str(report_csv),
        "management_json": str(management_json),
        "management_csv": str(management_csv),
        "final_report_json": str(final_report_json),
        "migrated_output_artifacts": migrated_output_artifacts,
        "log_path": str(batch_log_path),
    }


def parse_pdf_with_monkeyocr_windows(
    *,
    pdf_path: str | Path,
    output_root: str | Path,
    output_name: str | None = None,
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
    **_: Any,
) -> dict[str, Any]:
    """运行 MonkeyOCR Windows 单篇 PDF 解析并输出 AOK 兼容结果。"""

    resolved_output_root = _resolve_path(output_root)

    raw_result = run_monkeyocr_windows_single_pdf(
        input_pdf=pdf_path,
        output_dir=resolved_output_root,
        monkeyocr_root=monkeyocr_root,
        models_dir=models_dir,
        config_path=config_path,
        model_name=model_name,
        device=device,
        gpu_visible_devices=gpu_visible_devices,
        ensure_runtime=ensure_runtime,
        download_source=download_source,
        pip_index_url=pip_index_url,
        python_executable=python_executable,
        log_path=log_path,
        stream_output=stream_output,
    )

    result_output_dir = Path(str(raw_result.get("output_dir") or resolved_output_root)).resolve()
    artifacts = raw_result.get("artifacts") if isinstance(raw_result.get("artifacts"), dict) else {}
    markdown_path = Path(str(artifacts.get("markdown") or result_output_dir / f"{Path(pdf_path).stem}.md")).resolve()
    content_list_path = Path(str(artifacts.get("content_list") or result_output_dir / f"{Path(pdf_path).stem}_content_list.json")).resolve()
    middle_json_path = Path(str(artifacts.get("middle_json") or result_output_dir / f"{Path(pdf_path).stem}_middle.json")).resolve()
    images_dir = Path(str(artifacts.get("images_dir") or result_output_dir / "images")).resolve()

    content_items: list[Any] = []
    if content_list_path.exists() and content_list_path.is_file():
        try:
            loaded = json.loads(content_list_path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, list):
                content_items = loaded
        except Exception:
            content_items = []

    image_count = 0
    if images_dir.exists() and images_dir.is_dir():
        image_count = sum(
            1
            for item in images_dir.iterdir()
            if item.is_file() and item.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )

    parse_record = {
        "schema": "aok.pdf_monkeyocr_parse_record.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tool": "run_monkeyocr_windows_single_pdf",
        "status": str(raw_result.get("status") or "SUCCEEDED"),
        "input_pdf": str(_resolve_path(pdf_path)),
        "output_dir": str(result_output_dir),
        "device": str(raw_result.get("device") or device),
        "gpu_name": _detect_gpu_name() or "",
        "model_name": str(raw_result.get("model_name") or model_name),
        "page_count": image_count,
        "element_count": len(content_items),
        "markdown_path": str(markdown_path),
        "content_list_path": str(content_list_path),
        "middle_json_path": str(middle_json_path),
    }
    parse_record_path = (result_output_dir / "parse_record.json").resolve()
    parse_record_path.write_text(json.dumps(parse_record, ensure_ascii=False, indent=2), encoding="utf-8")

    quality_report = {
        "schema": "aok.pdf_monkeyocr_quality_report.v1",
        "created_at": parse_record["created_at"],
        "status": parse_record["status"],
        "page_count": image_count,
        "element_count": len(content_items),
        "input_pdf": parse_record["input_pdf"],
        "output_dir": parse_record["output_dir"],
        "tool": parse_record["tool"],
    }
    quality_report_path = (result_output_dir / "quality_report.json").resolve()
    quality_report_path.write_text(json.dumps(quality_report, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "output_name": str(Path(pdf_path).stem),
        "output_dir": str(result_output_dir),
        "structured_tree_path": str(middle_json_path) if middle_json_path.exists() else "",
        "elements_path": str(content_list_path) if content_list_path.exists() else "",
        "attachments_manifest_path": "",
        "linear_index_path": str(content_list_path) if content_list_path.exists() else "",
        "chunk_manifest_path": str(middle_json_path) if middle_json_path.exists() else "",
        "chunks_jsonl_path": "",
        "reconstructed_markdown_path": str(markdown_path) if markdown_path.exists() else "",
        "parse_record_path": str(parse_record_path),
        "quality_report_path": str(quality_report_path),
        "llm_model": str(raw_result.get("model_name") or model_name),
        "llm_backend": "monkeyocr_windows",
        "device": str(raw_result.get("device") or device),
        "status": str(raw_result.get("status") or "SUCCEEDED"),
        "artifacts": raw_result.get("artifacts") or {},
    }


def update_monkeyocr_batch_status_csv(
    csv_path: str | Path,
    outputs_dir: str | Path,
    *,
    backup: bool = True,
) -> dict[str, Any]:
    """根据 MonkeyOCR 输出目录回写 CSV 的 monkeyocr_status 列。"""

    csv_file = _resolve_path(csv_path)
    output_root = _resolve_path(outputs_dir)

    if not csv_file.exists():
        raise FileNotFoundError(f"CSV not found: {csv_file}")
    if not output_root.exists():
        print(f"[WARN] outputs dir not found (treated as empty): {output_root}")

    backup_path = csv_file.with_suffix(csv_file.suffix + ".bak")
    if backup:
        shutil.copy2(csv_file, backup_path)
        print(f"[INFO] backup saved to {backup_path}")

    output_stems = [path.stem for path in output_root.iterdir()] if output_root.exists() else []

    def _status_for_row(row: dict[str, Any]) -> str:
        candidate = ""
        for key_name in ("pdf_attachment_name", "input_pdf_path", "file_name", "source_value", "input"):
            value = row.get(key_name)
            if isinstance(value, str) and value.strip():
                candidate = value.strip()
                break

        if not candidate:
            return "UNKNOWN"

        try:
            stem = Path(candidate).stem
        except Exception:
            stem = candidate

        norm_key = str(stem).lower()
        for out_stem in output_stems:
            if not out_stem:
                continue
            out_norm = out_stem.lower()
            if out_norm == norm_key or norm_key in out_norm or out_norm in norm_key:
                return "SUCCEEDED"
        return "MISSING"

    rows: list[dict[str, Any]] = []
    with csv_file.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            row["monkeyocr_status"] = _status_for_row(row)
            rows.append(row)

    if "monkeyocr_status" not in fieldnames:
        fieldnames.append("monkeyocr_status")

    with csv_file.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    counts = {"SUCCEEDED": 0, "MISSING": 0, "UNKNOWN": 0}
    for row in rows:
        status = str(row.get("monkeyocr_status", "MISSING"))
        counts.setdefault(status, 0)
        counts[status] += 1

    print(
        f"[INFO] Updated CSV {csv_file} — SUCCEEDED={counts['SUCCEEDED']} "
        f"MISSING={counts['MISSING']} UNKNOWN={counts['UNKNOWN']}"
    )
    return {
        "csv_path": str(csv_file),
        "backup_path": str(backup_path) if backup else "",
        "outputs_dir": str(output_root),
        "counts": counts,
        "total_rows": len(rows),
    }
