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
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autodokit.tools import (
    run_monkeyocr_windows_batch_folder,
    run_monkeyocr_mlx_batch_folder,
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
            REPO_ROOT / "third_party" / "MonkeyOCR-runtime",
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


def _normalize_local_package_dirs(value: Any) -> list[str]:
    if value is None:
        return [str((REPO_ROOT / "third_party").resolve())]

    raw_items: list[str]
    if isinstance(value, (list, tuple, set)):
        raw_items = [str(item or "").strip() for item in value]
    else:
        text = str(value or "").strip()
        raw_items = [segment.strip() for segment in text.replace("\r", "\n").replace(";", "\n").split("\n")]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not item:
            continue
        path = Path(item).expanduser().resolve()
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(str(path))

    if not normalized:
        normalized.append(str((REPO_ROOT / "third_party").resolve()))
    return normalized


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _load_parsed_pdf_set(content_db: Path, backend: str = "monkeyocr_mlx") -> set[str]:
    """从 content.db 加载已解析 PDF 路径集合。"""
    if not content_db or not content_db.exists():
        return set()
    try:
        conn = sqlite3.connect(str(content_db))
        cur = conn.cursor()
        cur.execute(
            "SELECT PDF路径 FROM 文献主表 WHERE 当前解析状态='success' AND 当前解析后端=?",
            (backend,),
        )
        result = {r[0] for r in cur.fetchall() if r[0]}
        conn.close()
        return result
    except Exception:
        return set()


def _update_db_after_parse(
    *,
    content_db: Path | None,
    tasks_db: Path | None,
    pdf_path: str,
    pdf_stem: str,
    result_dir: str,
    backend: str,
    success: bool,
    timing: dict[str, Any],
    task_uid: str,
    batch_uid: str,
    workspace_root: str,
    node_code: str = "A070",
) -> None:
    """解析后更新 content.db (文献主表 + 附件表) 和 tasks.db。"""
    now = _now_iso()

    # tasks.db
    if tasks_db and tasks_db.exists():
        try:
            conn_t = sqlite3.connect(str(tasks_db))
            conn_t.execute(
                """INSERT INTO 任务运行
                   (task_uid, workflow_uid, 节点编码, 运行状态, 工作区根路径,
                    输入摘要JSON, 输出摘要JSON, 开始时间, 结束时间, 操作人)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_uid, batch_uid, node_code,
                 "completed" if success else "failed",
                 workspace_root,
                 json.dumps({"pdf": pdf_path, "backend": backend}, ensure_ascii=False),
                 json.dumps(timing, ensure_ascii=False),
                 now, now, "AOK-affair"),
            )
            conn_t.commit()
            conn_t.close()
        except Exception as e:
            logging.warning(f"tasks.db update failed: {e}")

    # content.db
    if not content_db or not content_db.exists():
        return

    try:
        conn_c = sqlite3.connect(str(content_db))
        cur = conn_c.cursor()

        if success:
            md_path = f"{result_dir}/{pdf_stem}.md"
            cl_path = f"{result_dir}/{pdf_stem}_content_list.json"

            # 验证产物确实存在，否则不算 success
            if not Path(md_path).exists():
                logging.warning(f"Markdown not found at {md_path}, marking as failed")
                success = False
            elif not Path(cl_path).exists():
                logging.warning(f"content_list not found at {cl_path}")
                # content_list 缺失不致命，继续

        if success:
            cur.execute(
                """UPDATE 文献主表 SET
                    当前解析状态='success', 当前解析路径=?, 当前解析Markdown路径=?,
                    当前解析后端=?, 当前解析层级='full_fine_grained',
                    当前解析更新时间=?,
                    结构化状态='ready', 结构化正文路径=?,
                    结构化后端=?, 结构化任务类型='full_fine_grained',
                    结构化更新时间=?, 结构化Schema版本='aok.pdf_structured.v3'
                   WHERE PDF路径=?""",
                (result_dir, md_path, backend, now,
                 cl_path, backend, now, pdf_path),
            )
            lit_affected = cur.rowcount

            # 附件表
            cur.execute(
                """UPDATE 附件表 SET
                    当前解析状态='success',
                    当前解析后端=?,
                    当前解析层级='full_fine_grained',
                    当前解析路径=?,
                    当前解析Markdown路径=?,
                    当前解析更新时间=?
                   WHERE uid_附件 IN (
                       SELECT uid_附件 FROM 文献附件关联
                       WHERE uid_文献 = (SELECT uid_文献 FROM 文献主表 WHERE PDF路径=?)
                   )""",
                (backend, result_dir, md_path, now, pdf_path),
            )
            attach_affected = cur.rowcount
            logging.info(f"  DB updated: lit={lit_affected}, attach={attach_affected}")
        else:
            cur.execute(
                "UPDATE 文献主表 SET 当前解析状态='failed', 当前解析更新时间=? WHERE PDF路径=?",
                (now, pdf_path),
            )

        conn_c.commit()
        conn_c.close()
    except Exception as e:
        logging.warning(f"content.db update failed: {e}")


def _update_node_status(
    content_db: Path | None,
    node_code: str,
    status: str,
    *,
    batch_uid: str = "",
    summary: str = "",
) -> None:
    """更新 content.db 的工作区节点状态。"""
    if not content_db or not content_db.exists():
        return
    now = _now_iso()
    try:
        conn = sqlite3.connect(str(content_db))
        if status == "running":
            conn.execute(
                """UPDATE 工作区节点状态 SET 执行中=1, 已完成=0, 闸门状态='running',
                   uid_当前任务=?, 最近执行时间=?, 更新时间=?
                   WHERE 节点编码=?""",
                (batch_uid, now, now, node_code),
            )
        else:
            conn.execute(
                """UPDATE 工作区节点状态 SET 执行中=0, 已完成=1, 闸门状态='passed',
                   完成时间=?, 更新时间=?, 摘要=?
                   WHERE 节点编码=?""",
                (now, now, summary, node_code),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


def run_from_payload(raw_cfg: Mapping[str, Any]) -> dict[str, Any]:
    input_dir = Path(str(raw_cfg.get("input_dir") or "")).expanduser().resolve()
    output_dir = Path(str(raw_cfg.get("output_dir") or "")).expanduser().resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"input_dir not found or not a directory: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_root = _resolve_runtime_root(output_dir, str(raw_cfg.get("runtime_dir") or ""))
    runtime_root.mkdir(parents=True, exist_ok=True)

    # ── DB 路径 ──
    content_db_raw = str(raw_cfg.get("content_db") or "").strip()
    content_db = Path(content_db_raw).expanduser().resolve() if content_db_raw else None
    tasks_db_raw = str(raw_cfg.get("tasks_db") or "").strip()
    tasks_db = Path(tasks_db_raw).expanduser().resolve() if tasks_db_raw else None
    workspace_root = str(raw_cfg.get("workspace_root") or raw_cfg.get("workspace_root") or "")
    node_code = str(raw_cfg.get("node_code") or "A070")
    batch_uid = str(raw_cfg.get("batch_uid") or f"batch-{int(time.time())}")

    # 检测后端
    use_mlx = False
    try:
        from autodokit.tools.ocr.monkeyocr.device_detector import detect_mlx
        use_mlx = detect_mlx()
    except Exception:
        pass
    backend = "monkeyocr_mlx" if use_mlx else "monkeyocr_cuda"

    # ── 加载已解析列表（DB 优先）──
    already_parsed = _load_parsed_pdf_set(content_db, backend) if content_db else set()

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
        tmux_result.update({
            "input_dir": str(input_dir), "output_dir": str(output_dir),
            "runtime_dir": str(runtime_root),
        })
        return tmux_result

    file_list: Path | None = None
    if use_priority_order:
        if priority_csv is None or not priority_csv.exists():
            raise FileNotFoundError(f"priority csv not found: {priority_csv}")
        file_list = _build_priority_file_list(
            priority_csv, runtime_root,
            rank_column=str(raw_cfg.get("priority_rank_column") or "priority_rank"),
            pdf_path_column=str(raw_cfg.get("priority_pdf_column") or "pdf_path"),
        )

    skip_existing = _normalize_bool(raw_cfg.get("skip_existing"), default=True)
    max_retries = int(raw_cfg.get("max_retries") or 2)

    # ── 标记节点启动 ──
    _update_node_status(content_db, node_code, "running", batch_uid=batch_uid)

    # ── 过滤已解析 ──
    logging.info("Running MonkeyOCR batch via autodokit.tools route")
    logging.info(f"后端: {backend}, 已解析: {len(already_parsed)} 篇")

    # ── 运行批量解析 ──
    if use_mlx:
        logging.info("检测到 Apple Silicon MLX，使用 MLX-VLM GPU 路线")
        result = run_monkeyocr_mlx_batch_folder(
            input_dir=input_dir, output_dir=output_dir,
            monkeyocr_root=monkey_root, models_dir=models_dir,
            config_path=config_path,
            model_name=str(raw_cfg.get("model_name") or DEFAULT_MODEL_NAME),
            ensure_runtime=_normalize_bool(raw_cfg.get("ensure_runtime"), default=False),
            download_source=str(raw_cfg.get("download_source") or "huggingface"),
            pip_index_url=str(raw_cfg.get("pip_index_url") or "").strip() or None,
            python_executable=_resolve_python_executable(str(raw_cfg.get("python_executable") or "")),
            file_list=file_list, runtime_dir=runtime_root,
            stream_output=_normalize_bool(raw_cfg.get("stream_output"), default=False),
            skip_existing=skip_existing, max_retries=max_retries,
        )
    else:
        logging.info("使用 CUDA/CPU 路线（Windows 兼容）")
        result = run_monkeyocr_windows_batch_folder(
            input_dir=input_dir, output_dir=output_dir,
            monkeyocr_root=monkey_root, models_dir=models_dir,
            config_path=config_path,
            model_name=str(raw_cfg.get("model_name") or DEFAULT_MODEL_NAME),
            device=str(raw_cfg.get("device") or "cuda"),
            gpu_visible_devices=str(raw_cfg.get("gpu") or raw_cfg.get("gpu_visible_devices") or "0"),
            ensure_runtime=_normalize_bool(raw_cfg.get("ensure_runtime"), default=False),
            auto_install_triton_windows=_normalize_bool(raw_cfg.get("auto_install_triton_windows"), default=False),
            download_source=str(raw_cfg.get("download_source") or "huggingface"),
            pip_index_url=str(raw_cfg.get("pip_index_url") or "").strip() or None,
            python_executable=_resolve_python_executable(str(raw_cfg.get("python_executable") or "")),
            local_package_dirs=_normalize_local_package_dirs(raw_cfg.get("local_package_dirs")),
            file_list=file_list, runtime_dir=runtime_root,
            stream_output=_normalize_bool(raw_cfg.get("stream_output"), default=False),
            skip_existing=skip_existing, max_retries=max_retries,
        )

    # ── 更新 DB ──
    per_pdf = result.get("per_pdf_results", [])
    if per_pdf and content_db:
        for entry in per_pdf:
            pdf_stem = entry["pdf_stem"]
            pdf_path = entry["pdf_path"]
            rdir = entry.get("result", {}).get("output_dir") or str(output_dir / pdf_stem)
            task_uid = f"task-{pdf_stem[:20]}-{int(time.time())}"
            _update_db_after_parse(
                content_db=content_db, tasks_db=tasks_db,
                pdf_path=pdf_path, pdf_stem=pdf_stem,
                result_dir=str(rdir), backend=backend,
                success=(entry["status"] == "SUCCEEDED"),
                timing=entry.get("result") or {},
                task_uid=task_uid, batch_uid=batch_uid,
                workspace_root=workspace_root, node_code=node_code,
            )

    # ── 标记节点完成 ──
    succeeded = result.get("succeeded", 0)
    failed = result.get("failed", 0)
    total = result.get("total", 0)
    _update_node_status(
        content_db, node_code, "done",
        batch_uid=batch_uid,
        summary=f"MonkeyOCR批量完成: {succeeded}/{total}成功{f'/{failed}失败' if failed else ''}",
    )

    # ── CSV 同步 ──
    if priority_csv is not None:
        result["status_sync"] = update_monkeyocr_batch_status_csv(priority_csv, output_dir, backup=True)

    result.update({
        "launch_mode": "foreground",
        "input_dir": str(input_dir), "output_dir": str(output_dir),
        "runtime_dir": str(runtime_root), "monkey_root": str(monkey_root),
        "models_dir": str(models_dir), "config_path": str(config_path),
        "backend": backend, "batch_uid": batch_uid,
        "db_updated": bool(content_db and per_pdf),
    })
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
    parser.add_argument("--auto-install-triton-windows", action="store_true")
    parser.add_argument("--local-package-dir", action="append", default=None)
    parser.add_argument("--stream-output", action="store_true")
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--content-db", type=Path, default=None)
    parser.add_argument("--tasks-db", type=Path, default=None)
    parser.add_argument("--workspace-root", default="")
    parser.add_argument("--node-code", default="A070")
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
        "auto_install_triton_windows": bool(args.auto_install_triton_windows),
        "local_package_dirs": [str(Path(item).expanduser().resolve()) for item in (args.local_package_dir or [])],
        "stream_output": bool(args.stream_output),
        "skip_existing": not bool(args.no_skip_existing),
        "max_retries": int(args.max_retries),
        "content_db": str(args.content_db.expanduser().resolve()) if args.content_db else "",
        "tasks_db": str(args.tasks_db.expanduser().resolve()) if args.tasks_db else "",
        "workspace_root": args.workspace_root or "",
        "node_code": args.node_code,
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