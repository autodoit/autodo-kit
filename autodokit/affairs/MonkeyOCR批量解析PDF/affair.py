"""事务：按优先级串行批量运行 MonkeyOCR。

本事务将 sandbox 中的临时批处理逻辑正式收敛到 AOK affairs，统一通过
``autodokit.tools`` 暴露的 MonkeyOCR 路由运行，而不是在事务层直接调用上游
``parse.py``。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autodokit.tools import (
    run_monkeyocr_windows_batch_folder,
    update_monkeyocr_batch_status_csv,
)


DEFAULT_MODEL_NAME = "MonkeyOCR-pro-1.2B"


def _normalize_header(name: str) -> str:
    return str(name or "").replace("\ufeff", "").strip().lower()


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "on", "enabled", "是"}


def _extract_pdf_candidates(pdf_value: str) -> list[str]:
    raw_value = str(pdf_value or "").strip()
    if not raw_value:
        return []

    candidates: list[str] = []

    def _push(value: str) -> None:
        normalized = str(value or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    _push(raw_value)

    if "\\" in raw_value or ":" in raw_value:
        try:
            windows_path = PureWindowsPath(raw_value)
            _push(windows_path.name)
            if len(windows_path.parts) >= 2:
                _push("/".join(windows_path.parts[-2:]))
        except Exception:
            pass

        slash_value = raw_value.replace("\\", "/")
        _push(Path(slash_value).name)
        slash_parts = [part for part in slash_value.split("/") if part]
        if len(slash_parts) >= 2:
            _push("/".join(slash_parts[-2:]))

    return candidates


def _discover_monkey_root() -> Path | None:
    env_candidates = [
        os.environ.get("AUTODOKIT_MONKEYOCR_ROOT", ""),
        os.environ.get("MONKEYOCR_ROOT", ""),
    ]
    candidates = [
        Path(candidate).expanduser() for candidate in env_candidates if str(candidate).strip()
    ]
    candidates.extend(
        [
            REPO_ROOT / "third_party" / "MonkeyOCR-main",
            REPO_ROOT / "sandbox" / "test monkey ocr cuda" / "MonkeyOCR-main",
            REPO_ROOT / "sandbox" / "MonkeyOCR-main",
        ]
    )

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if (resolved / "parse.py").exists():
            return resolved
        nested = resolved / "MonkeyOCR-main"
        if (nested / "parse.py").exists():
            return nested
    return None


def _is_server_runtime() -> bool:
    if _normalize_bool(os.environ.get("AOK_FORCE_SERVER_RUNTIME"), default=False):
        return True
    return any(os.environ.get(name) for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"))


def _resolve_launch_mode(requested: str) -> str:
    normalized = str(requested or "auto").strip().lower()
    if normalized in {"foreground", "direct", "local"}:
        return "foreground"
    if normalized in {"tmux", "background", "bg"}:
        return "tmux"
    if normalized != "auto":
        raise ValueError(f"不支持的 launch_mode: {requested}")
    return "tmux" if _is_server_runtime() else "foreground"


def _build_priority_file_list(
    priority_csv: Path,
    runtime_root: Path,
    *,
    rank_column: str,
    pdf_path_column: str,
) -> Path:
    if not priority_csv.exists() or not priority_csv.is_file():
        raise FileNotFoundError(f"priority csv not found: {priority_csv}")

    with priority_csv.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"priority csv has no header: {priority_csv}")

        field_map = {_normalize_header(name): name for name in reader.fieldnames if name}
        rank_field = field_map.get(_normalize_header(rank_column))
        pdf_field = field_map.get(_normalize_header(pdf_path_column))
        if rank_field is None:
            raise ValueError(f"rank column not found: {rank_column}")
        if pdf_field is None:
            raise ValueError(f"pdf path column not found: {pdf_path_column}")

        ranked_rows: list[tuple[int, list[str]]] = []
        fallback_rows: list[tuple[int, list[str]]] = []
        for index, row in enumerate(reader):
            candidate_values = _extract_pdf_candidates(str(row.get(pdf_field, "") or ""))
            attachment_name = str(row.get("pdf_attachment_name", "") or "")
            attachment_path = str(row.get("pdf_attachment_path", "") or "")
            for extra_value in (attachment_name, attachment_path):
                for candidate in _extract_pdf_candidates(extra_value):
                    if candidate not in candidate_values:
                        candidate_values.append(candidate)
            if not candidate_values:
                continue

            rank_raw = str(row.get(rank_field, "") or "").strip()
            try:
                ranked_rows.append((int(rank_raw), candidate_values))
            except Exception:
                fallback_rows.append((index, candidate_values))

    ranked_rows.sort(key=lambda item: item[0])
    ordered_values = [values for _, values in ranked_rows] + [values for _, values in fallback_rows]
    if not ordered_values:
        raise ValueError(f"no usable pdf path found in: {priority_csv}")

    deduped: list[list[str]] = []
    seen: set[str] = set()
    for group in ordered_values:
        key = "||".join(value.casefold() for value in group)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(group)

    runtime_root.mkdir(parents=True, exist_ok=True)
    temp_file = runtime_root / "priority_file_list.json"
    temp_file.write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    return temp_file


def _resolve_python_executable(value: str | None) -> str:
    python_path = Path(str(value or sys.executable)).expanduser()
    if not python_path.is_absolute():
        python_path = (Path.cwd() / python_path).absolute()
    if not python_path.exists():
        raise FileNotFoundError(f"python executable not found: {python_path}")
    return str(python_path)


def _resolve_runtime_root(output_dir: Path, raw_runtime_dir: str | None) -> Path:
    if str(raw_runtime_dir or "").strip():
        return Path(str(raw_runtime_dir)).expanduser().resolve()
    return (output_dir.parent / f"{output_dir.name}__runtime").resolve()


def _sanitize_session_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(name or "batch_monkeyocr"))
    cleaned = cleaned.strip("_") or "batch_monkeyocr"
    return cleaned[:48]


def _launch_tmux_job(config_payload: dict[str, Any], *, runtime_root: Path) -> dict[str, Any]:
    tmux_path = shutil.which("tmux")
    if not tmux_path:
        raise RuntimeError("当前环境未安装 tmux，无法在服务端后台运行 MonkeyOCR 批任务")

    runtime_root.mkdir(parents=True, exist_ok=True)
    child_config_path = runtime_root / "tmux_launch_config.json"
    child_log_path = runtime_root / "tmux_launch.log"
    child_payload = dict(config_payload)
    child_payload["launch_mode"] = "foreground"
    child_config_path.write_text(json.dumps(child_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    python_executable = _resolve_python_executable(str(config_payload.get("python_executable") or ""))
    script_path = Path(__file__).resolve()
    session_name = _sanitize_session_name(
        f"aok_monkeyocr_{Path(str(config_payload.get('output_dir') or 'outputs')).stem}_{int(time.time())}"
    )
    shell_command = " ".join(
        [
            "cd",
            shlex.quote(str(REPO_ROOT)),
            "&&",
            "export",
            "AOK_MONKEYOCR_TMUX_CHILD=1",
            "&&",
            shlex.quote(python_executable),
            shlex.quote(str(script_path)),
            "--affair-config",
            shlex.quote(str(child_config_path)),
            "--launch-mode",
            "foreground",
            ">>",
            shlex.quote(str(child_log_path)),
            "2>&1",
        ]
    )
    subprocess.run([tmux_path, "new-session", "-d", "-s", session_name, shell_command], check=True)
    return {
        "status": "SUBMITTED",
        "launch_mode": "tmux",
        "tmux_session_name": session_name,
        "tmux_command": shell_command,
        "tmux_launch_config": str(child_config_path),
        "tmux_log_path": str(child_log_path),
    }


def run_from_payload(raw_cfg: Mapping[str, Any]) -> dict[str, Any]:
    input_dir = Path(str(raw_cfg.get("input_dir") or "")).expanduser().resolve()
    output_dir = Path(str(raw_cfg.get("output_dir") or "")).expanduser().resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"input_dir not found or not a directory: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_root = _resolve_runtime_root(output_dir, str(raw_cfg.get("runtime_dir") or ""))
    runtime_root.mkdir(parents=True, exist_ok=True)

    priority_csv_raw = str(raw_cfg.get("priority_csv") or "").strip()
    priority_csv = Path(priority_csv_raw).expanduser().resolve() if priority_csv_raw else None
    use_priority_order = _normalize_bool(raw_cfg.get("use_priority_order"), default=bool(priority_csv))

    monkey_root_raw = str(raw_cfg.get("monkey_root") or "").strip()
    monkey_root = Path(monkey_root_raw).expanduser().resolve() if monkey_root_raw else _discover_monkey_root()
    if monkey_root is None:
        raise FileNotFoundError("未找到 MonkeyOCR 根目录，请显式传入 monkey_root")

    models_dir_raw = str(raw_cfg.get("models_dir") or "").strip()
    models_dir = Path(models_dir_raw).expanduser().resolve() if models_dir_raw else (monkey_root / "model_weight").resolve()
    config_path_raw = str(raw_cfg.get("config_path") or "").strip()
    config_path = Path(config_path_raw).expanduser().resolve() if config_path_raw else (runtime_root / "model_configs.local.yaml").resolve()

    launch_mode = _resolve_launch_mode(str(raw_cfg.get("launch_mode") or "auto"))
    if launch_mode == "tmux" and not _normalize_bool(os.environ.get("AOK_MONKEYOCR_TMUX_CHILD"), default=False):
        tmux_result = _launch_tmux_job(dict(raw_cfg), runtime_root=runtime_root)
        tmux_result.setdefault("launch_mode", "tmux")
        tmux_result.update(
            {
                "input_dir": str(input_dir),
                "output_dir": str(output_dir),
                "runtime_dir": str(runtime_root),
            }
        )
        return tmux_result

    file_list: Path | None = None
    if use_priority_order:
        if priority_csv is None or not priority_csv.exists():
            raise FileNotFoundError(f"priority csv not found: {priority_csv}")
        file_list = _build_priority_file_list(
            priority_csv,
            runtime_root,
            rank_column=str(raw_cfg.get("priority_rank_column") or "priority_rank"),
            pdf_path_column=str(raw_cfg.get("priority_pdf_column") or "pdf_path"),
        )

    logging.info("Running MonkeyOCR batch via autodokit.tools route")
    result = run_monkeyocr_windows_batch_folder(
        input_dir=input_dir,
        output_dir=output_dir,
        monkeyocr_root=monkey_root,
        models_dir=models_dir,
        config_path=config_path,
        model_name=str(raw_cfg.get("model_name") or DEFAULT_MODEL_NAME),
        device=str(raw_cfg.get("device") or "cuda"),
        gpu_visible_devices=str(raw_cfg.get("gpu") or raw_cfg.get("gpu_visible_devices") or "0"),
        ensure_runtime=_normalize_bool(raw_cfg.get("ensure_runtime"), default=False),
        download_source=str(raw_cfg.get("download_source") or "huggingface"),
        pip_index_url=str(raw_cfg.get("pip_index_url") or "").strip() or None,
        python_executable=_resolve_python_executable(str(raw_cfg.get("python_executable") or "")),
        file_list=file_list,
        runtime_dir=runtime_root,
        stream_output=_normalize_bool(raw_cfg.get("stream_output"), default=False),
        skip_existing=_normalize_bool(raw_cfg.get("skip_existing"), default=True),
        max_retries=int(raw_cfg.get("max_retries") or 2),
    )

    if priority_csv is not None:
        result["status_sync"] = update_monkeyocr_batch_status_csv(priority_csv, output_dir, backup=True)

    result.update(
        {
            "launch_mode": "foreground",
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "runtime_dir": str(runtime_root),
            "monkey_root": str(monkey_root),
            "models_dir": str(models_dir),
            "config_path": str(config_path),
            "priority_csv": str(priority_csv) if priority_csv is not None else "",
            "priority_file_list": str(file_list) if file_list is not None else "",
        }
    )
    return result


def execute(config_path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(config_path).expanduser().resolve().read_text(encoding="utf-8-sig"))
    return run_from_payload(payload)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AOK affair: serial MonkeyOCR batch runner")
    parser.add_argument("--affair-config", type=Path, default=None, help="affair json config path")
    parser.add_argument("--input-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--runtime-dir", type=Path, default=None)
    parser.add_argument("--models-dir", type=Path, default=None)
    parser.add_argument("--config", dest="config_path", type=Path, default=None)
    parser.add_argument("--monkey-root", type=Path, default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--gpu", default="0", help="visible GPU ids")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--python-executable", type=Path, default=None)
    parser.add_argument("--download-source", default="huggingface")
    parser.add_argument("--pip-index-url", default=None)
    parser.add_argument("--use-priority-order", action="store_true")
    parser.add_argument("--priority-csv", type=Path, default=None)
    parser.add_argument("--priority-rank-column", default="priority_rank")
    parser.add_argument("--priority-pdf-column", default="pdf_path")
    parser.add_argument("--launch-mode", default="auto", choices=["auto", "foreground", "tmux"])
    parser.add_argument("--ensure-runtime", action="store_true")
    parser.add_argument("--stream-output", action="store_true")
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument("--max-retries", type=int, default=2)
    return parser


def _cli_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.affair_config is not None:
        payload = json.loads(args.affair_config.expanduser().resolve().read_text(encoding="utf-8-sig"))
        if args.launch_mode:
            payload["launch_mode"] = args.launch_mode
        return payload

    if args.input_dir is None or args.output_dir is None:
        raise SystemExit("--input-dir and --output-dir are required when --affair-config is not provided")

    return {
        "input_dir": str(args.input_dir.expanduser().resolve()),
        "output_dir": str(args.output_dir.expanduser().resolve()),
        "runtime_dir": str(args.runtime_dir.expanduser().resolve()) if args.runtime_dir else "",
        "models_dir": str(args.models_dir.expanduser().resolve()) if args.models_dir else "",
        "config_path": str(args.config_path.expanduser().resolve()) if args.config_path else "",
        "monkey_root": str(args.monkey_root.expanduser().resolve()) if args.monkey_root else "",
        "device": args.device,
        "gpu": args.gpu,
        "model_name": args.model_name,
        "python_executable": _resolve_python_executable(str(args.python_executable)) if args.python_executable else "",
        "download_source": args.download_source,
        "pip_index_url": args.pip_index_url or "",
        "use_priority_order": bool(args.use_priority_order),
        "priority_csv": str(args.priority_csv.expanduser().resolve()) if args.priority_csv else "",
        "priority_rank_column": args.priority_rank_column,
        "priority_pdf_column": args.priority_pdf_column,
        "launch_mode": args.launch_mode,
        "ensure_runtime": bool(args.ensure_runtime),
        "stream_output": bool(args.stream_output),
        "skip_existing": not bool(args.no_skip_existing),
        "max_retries": int(args.max_retries),
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    result = run_from_payload(_cli_payload(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    status = str(result.get("status") or "")
    return 0 if status in {"SUCCEEDED", "SUBMITTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())