"""MonkeyOCR 统一运行入口。

提供本地与远端两种执行模式：
- local: 直接调用 Windows 本地解析工具。
- remote: 通过 remote_transfer 与 SSH 触发远端执行。

该入口保持上层调用契约稳定，避免业务层直接依赖远端传输细节。
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Literal

from autodokit.tools import remote_transfer
from autodokit.tools.ocr.monkeyocr.monkeyocr_windows_tools import run_monkeyocr_windows_single_pdf


ExecutionMode = Literal["auto", "local", "remote"]


def _now_ts() -> str:
    return time.strftime("%Y%m%d%H%M%S", time.localtime())


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_bool(value: Any, default: bool = False) -> bool:
    text = _stringify(value).lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "on", "enabled", "是"}


def _normalize_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _first_existing(paths: list[Path]) -> str:
    for path in paths:
        if path.exists() and path.is_file():
            return str(path.resolve())
    return ""


def _build_remote_parse_result(output_dir: Path, markdown_path: Path, *, mode: str, job_id: str) -> Dict[str, Any]:
    """构造与本地 MonkeyOCR 一致的解析结果结构。"""

    output_dir = output_dir.resolve()
    default_md = output_dir / "reconstructed_content.md"
    md_path = markdown_path.resolve() if markdown_path and markdown_path.exists() else default_md.resolve()

    return {
        "status": "SUCCEEDED",
        "mode": mode,
        "job_id": job_id,
        "output_name": output_dir.name,
        "output_dir": str(output_dir),
        "reconstructed_markdown_path": str(md_path),
        "linear_index_path": str((output_dir / "linear_index.json").resolve()),
        "chunk_manifest_path": str((output_dir / "chunk_manifest.json").resolve()),
        "chunks_jsonl_path": str((output_dir / "chunks.jsonl").resolve()),
        "parse_record_path": str((output_dir / "parse_record.json").resolve()),
        "quality_report_path": str((output_dir / "quality_report.json").resolve()),
        "llm_backend": "monkeyocr_remote",
        "llm_model": "remote_monkeyocr",
    }


def _resolve_remote_output_name(input_pdf: Path, output_name: str | None) -> str:
    """解析远端输出目录名，默认使用输入文件 stem。"""

    candidate = _stringify(output_name)
    if candidate:
        return Path(candidate).stem or input_pdf.stem
    return input_pdf.stem


def _ensure_remote_compat_artifacts(parse_output_dir: Path, *, output_name: str, markdown_path: str | Path | None, job_id: str) -> None:
    """补齐远端旧格式输出，确保满足上层完整性判定。

    旧版远端输出常见为: `{output_name}.md` 与 `{output_name}_middle.json`。
    上层 A055 需要 `reconstructed_content.md`、`normalized_structured.json`
    以及 `parse_record.json`、`quality_report.json`。
    """

    parse_output_dir = parse_output_dir.resolve()
    parse_output_dir.mkdir(parents=True, exist_ok=True)

    md_candidates = [
        parse_output_dir / "reconstructed_content.md",
        parse_output_dir / f"{output_name}.md",
    ]
    chosen_md = next((p for p in md_candidates if p.exists() and p.is_file()), None)
    if chosen_md is None and markdown_path:
        candidate = Path(markdown_path)
        if candidate.exists() and candidate.is_file():
            chosen_md = candidate
    if chosen_md and chosen_md.name != "reconstructed_content.md":
        target_md = parse_output_dir / "reconstructed_content.md"
        if not target_md.exists():
            shutil.copy2(chosen_md, target_md)

    normalized_target = parse_output_dir / "normalized_structured.json"
    if not normalized_target.exists():
        normalized_candidates = [
            parse_output_dir / "normalized_structured.json",
            parse_output_dir / "normalized.structured.json",
            parse_output_dir / f"{output_name}_middle.json",
            parse_output_dir / f"{output_name}.structured.json",
        ]
        normalized_src = next((p for p in normalized_candidates if p.exists() and p.is_file()), None)
        if normalized_src is not None and normalized_src != normalized_target:
            shutil.copy2(normalized_src, normalized_target)

    parse_record_path = parse_output_dir / "parse_record.json"
    if not parse_record_path.exists():
        parse_record_payload = {
            "status": "SUCCEEDED",
            "job_id": job_id,
            "output_name": output_name,
            "source": "remote_monkeyocr_compat",
        }
        parse_record_path.write_text(json.dumps(parse_record_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    quality_report_path = parse_output_dir / "quality_report.json"
    if not quality_report_path.exists():
        quality_payload = {
            "status": "SUCCEEDED",
            "source": "remote_monkeyocr_compat",
            "message": "generated compatibility report for legacy remote output layout",
        }
        quality_report_path.write_text(json.dumps(quality_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_ssh_connection(ssh_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """从 connection_file + profile 解析 SSH 连接参数。"""

    merged = dict(ssh_cfg)
    connection_file = _stringify(ssh_cfg.get("connection_file"))
    if not connection_file:
        return merged

    payload = json.loads(Path(connection_file).expanduser().resolve().read_text(encoding="utf-8"))
    profile = _stringify(ssh_cfg.get("profile")) or "default"

    if isinstance(payload, dict) and isinstance(payload.get("profiles"), dict):
        profile_cfg = payload.get("profiles", {}).get(profile) or {}
    elif isinstance(payload, dict) and isinstance(payload.get(profile), dict):
        profile_cfg = payload.get(profile) or {}
    elif isinstance(payload, dict):
        profile_cfg = payload
    else:
        profile_cfg = {}

    resolved = dict(profile_cfg)
    resolved.update(merged)
    return resolved


def _build_ssh_base_cmd(ssh_cfg: Dict[str, Any]) -> list[str]:
    cmd = ["ssh"]
    if ssh_cfg.get("key"):
        cmd.extend(["-i", str(ssh_cfg.get("key"))])
    if ssh_cfg.get("port"):
        cmd.extend(["-p", str(ssh_cfg.get("port"))])
    extra_options = ssh_cfg.get("options")
    if isinstance(extra_options, list):
        for opt in extra_options:
            opt_text = _stringify(opt)
            if opt_text:
                cmd.extend(["-o", opt_text])
    elif _stringify(extra_options):
        cmd.extend(["-o", _stringify(extra_options)])
    return cmd


def _build_scp_base_cmd(ssh_cfg: Dict[str, Any]) -> list[str]:
    cmd = ["scp"]
    if ssh_cfg.get("key"):
        cmd.extend(["-i", str(ssh_cfg.get("key"))])
    if ssh_cfg.get("port"):
        cmd.extend(["-P", str(ssh_cfg.get("port"))])
    return cmd


def _ssh_run(ssh_cfg: Dict[str, Any], remote_command: str, *, timeout: int) -> Dict[str, Any]:
    host = _stringify(ssh_cfg.get("host"))
    user = _stringify(ssh_cfg.get("user"))
    if not host or not user:
        raise ValueError("ssh mode requires host and user")

    cmd = _build_ssh_base_cmd(ssh_cfg)
    cmd.append(f"{user}@{host}")
    cmd.append(remote_command)

    # 远端输出可能包含 UTF-8 字节；在 Windows 默认 GBK 下会触发解码异常。
    completed = subprocess.run(
        cmd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=max(int(timeout), 1),
        check=False,
    )
    return {
        "command": cmd,
        "returncode": int(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def stop_remote_monkeyocr_jobs(runtime_settings: Dict[str, Any]) -> Dict[str, Any]:
    """停止远端遗留的 MonkeyOCR 任务。"""

    remote_cfg = runtime_settings.get("remote_processing") if isinstance(runtime_settings, dict) else {}
    if not isinstance(remote_cfg, dict) or not _normalize_bool(remote_cfg.get("enabled"), False):
        return {"enabled": False, "mode": "", "killed": False, "stdout": "", "stderr": ""}

    mode = _stringify(remote_cfg.get("mode")).lower() or "ssh"
    if mode != "ssh":
        return {"enabled": True, "mode": mode, "killed": False, "stdout": "", "stderr": ""}

    ssh_cfg = _load_ssh_connection(dict(remote_cfg.get("ssh") or {}))
    remote_base = _stringify(ssh_cfg.get("remote_base")).rstrip("/")
    tmux_prefix = _stringify(ssh_cfg.get("tmux_session_prefix")) or "a055"

    tmux_prefix_quoted = shlex.quote(tmux_prefix)
    remote_base_quoted = shlex.quote(remote_base)
    remote_command = (
        f"TMUX_PREFIX={tmux_prefix_quoted}; "
        f"REMOTE_BASE={remote_base_quoted}; "
        "sessions=$(tmux ls 2>/dev/null | awk -F: '$1 ~ (\"^\" ENVIRON[\"TMUX_PREFIX\"] \"_\") {print $1}'); "
        "if [ -n \"$sessions\" ]; then for s in $sessions; do tmux kill-session -t \"$s\" 2>/dev/null || true; done; fi; "
        "pids=$(ps -ef | grep -F \"$REMOTE_BASE\" | grep -F '/parse.py' | grep -v grep | awk '{print $2}'); "
        "if [ -n \"$pids\" ]; then kill -TERM $pids 2>/dev/null || true; sleep 2; kill -KILL $pids 2>/dev/null || true; fi; "
        "printf 'sessions=%s\\n' \"$sessions\"; printf 'pids=%s\\n' \"$pids\""
    )
    result = _ssh_run(ssh_cfg, remote_command, timeout=max(_normalize_int(remote_cfg.get("timeout"), 60), 10))
    return {
        "enabled": True,
        "mode": mode,
        "killed": int(result.get("returncode", 1)) == 0,
        "stdout": _stringify(result.get("stdout")),
        "stderr": _stringify(result.get("stderr")),
    }


def launch_remote_tmux_command(
    runtime_settings: Dict[str, Any],
    *,
    remote_command: str,
    session_prefix: str = "a055",
    session_name: str = "",
    timeout: int = 60,
) -> Dict[str, Any]:
    """通过 SSH 在远端 tmux 中启动命令。

    Args:
        runtime_settings: MonkeyOCR 运行时配置（需包含 remote_processing.ssh）。
        remote_command: 远端要执行的 shell 命令。
        session_prefix: 默认 tmux session 前缀。
        session_name: 可选固定 session 名；为空时自动生成。
        timeout: SSH 命令超时时间（秒）。

    Returns:
        启动结果，包含 session_name、stdout、stderr 与 returncode。

    Raises:
        ValueError: 配置缺失或 mode 非 ssh。
        RuntimeError: 远端 tmux 启动失败。
    """

    remote_cfg = runtime_settings.get("remote_processing") if isinstance(runtime_settings, dict) else {}
    if not isinstance(remote_cfg, dict) or not _normalize_bool(remote_cfg.get("enabled"), False):
        raise ValueError("remote_processing.enabled 必须为 true")

    mode = _stringify(remote_cfg.get("mode")).lower() or "ssh"
    if mode != "ssh":
        raise ValueError("launch_remote_tmux_command 仅支持 ssh 模式")

    ssh_cfg = _load_ssh_connection(dict(remote_cfg.get("ssh") or {}))
    command_text = _stringify(remote_command)
    if not command_text:
        raise ValueError("remote_command 不能为空")

    resolved_prefix = _stringify(session_prefix) or "a055"
    resolved_session_name = _stringify(session_name)
    if not resolved_session_name:
        resolved_session_name = f"{resolved_prefix}_{_now_ts()[-8:]}"

    remote_launch = (
        f"tmux new-session -d -s {shlex.quote(resolved_session_name)} "
        f"bash -lc {shlex.quote(command_text)}; "
        f"tmux has-session -t {shlex.quote(resolved_session_name)}"
    )
    result = _ssh_run(ssh_cfg, remote_launch, timeout=max(int(timeout), 10))
    ok = int(result.get("returncode", 1)) == 0
    if not ok:
        raise RuntimeError(
            "remote tmux launch failed: "
            + (_stringify(result.get("stderr")) or _stringify(result.get("stdout")) or "unknown")
        )

    return {
        "enabled": True,
        "mode": mode,
        "session_name": resolved_session_name,
        "returncode": int(result.get("returncode", 0)),
        "stdout": _stringify(result.get("stdout")),
        "stderr": _stringify(result.get("stderr")),
    }


def _scp_upload(ssh_cfg: Dict[str, Any], local_path: Path, remote_target: str) -> None:
    host = _stringify(ssh_cfg.get("host"))
    user = _stringify(ssh_cfg.get("user"))
    if not host or not user:
        raise ValueError("ssh mode requires host and user")

    cmd = _build_scp_base_cmd(ssh_cfg)
    cmd.extend([str(local_path), f"{user}@{host}:{remote_target}"])
    subprocess.run(cmd, check=True)


def _scp_download_dir(ssh_cfg: Dict[str, Any], remote_dir: str, local_root: Path) -> None:
    host = _stringify(ssh_cfg.get("host"))
    user = _stringify(ssh_cfg.get("user"))
    if not host or not user:
        raise ValueError("ssh mode requires host and user")

    cmd = _build_scp_base_cmd(ssh_cfg)
    cmd.extend(["-r", f"{user}@{host}:{remote_dir}", str(local_root)])
    subprocess.run(cmd, check=True)


def _wait_remote_output_ready(
    ssh_cfg: Dict[str, Any],
    *,
    remote_output_dir: str,
    remote_output_name: str,
    timeout: int,
    poll_interval: int,
) -> Dict[str, Any]:
    """轮询远端输出目录，直到核心产物出现。"""

    md_a = f"{remote_output_dir}/{remote_output_name}/{remote_output_name}.md"
    md_b = f"{remote_output_dir}/{remote_output_name}/reconstructed_content.md"
    probe_cmd = f"test -f {shlex.quote(md_a)} || test -f {shlex.quote(md_b)}"

    start = time.time()
    last_result: Dict[str, Any] = {"returncode": 1, "stdout": "", "stderr": ""}
    while time.time() - start < timeout:
        last_result = _ssh_run(ssh_cfg, probe_cmd, timeout=max(poll_interval, 5))
        if int(last_result.get("returncode", 1)) == 0:
            return {"status": "ready", "probe": last_result}
        time.sleep(max(poll_interval, 1))

    return {"status": "timeout", "probe": last_result}


def _run_local_monkeyocr(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    output_name: str | None,
    runtime_settings: Dict[str, Any],
) -> Dict[str, Any]:
    """运行本地 MonkeyOCR 单篇解析。"""

    result = run_monkeyocr_windows_single_pdf(
        input_pdf=str(Path(input_pdf).expanduser().resolve()),
        output_dir=str(Path(output_dir).expanduser().resolve()),
        output_name=output_name,
        monkeyocr_root=str(runtime_settings.get("monkeyocr_root") or ""),
        models_dir=runtime_settings.get("models_dir"),
        config_path=runtime_settings.get("config_path"),
        model_name=runtime_settings.get("model_name") or runtime_settings.get("monkeyocr_model") or None,
        device=runtime_settings.get("device") or "cuda",
        gpu_visible_devices=runtime_settings.get("gpu_visible_devices") or "0",
        ensure_runtime=runtime_settings.get("ensure_runtime", True),
        auto_install_triton_windows=runtime_settings.get("auto_install_triton_windows", False),
        download_source=runtime_settings.get("download_source", "huggingface"),
        pip_index_url=runtime_settings.get("pip_index_url"),
        python_executable=runtime_settings.get("python_executable"),
        local_package_dirs=runtime_settings.get("local_package_dirs"),
        stream_output=False,
    )
    result["output_name"] = _resolve_remote_output_name(Path(input_pdf).expanduser().resolve(), output_name)
    return result


def _run_remote_monkeyocr(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    output_name: str | None,
    runtime_settings: Dict[str, Any],
    timeout: int,
    poll_interval: int,
) -> Dict[str, Any]:
    """运行远端 MonkeyOCR 单篇解析。"""

    input_pdf = Path(input_pdf).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rp = runtime_settings.get("remote_processing") or {}
    if not _normalize_bool(rp.get("enabled"), False):
        raise ValueError("remote_processing.enabled must be true for remote execution")

    mode = _stringify(rp.get("mode")).lower() or "ssh"
    job_id = _stringify(rp.get("job_id")) or f"autodokit_job_{_now_ts()}"
    remote_output_name = _resolve_remote_output_name(input_pdf, output_name)

    if mode == "mapped":
        mapped_root_raw = _stringify(rp.get("mapped_root"))
        if not mapped_root_raw:
            raise ValueError("mapped mode requires remote_processing.mapped_root")
        mapped_root = Path(mapped_root_raw).expanduser().resolve()

        job_dir = (mapped_root / job_id).resolve()
        remote_input = str((job_dir / "input" / f"{remote_output_name}{input_pdf.suffix}").resolve())
        remote_output_dir = str((job_dir / "output").resolve())

        transfer_res = remote_transfer.transfer(str(input_pdf), remote_input)
        trigger_path = remote_transfer.write_trigger_file(
            str(job_dir / "control"),
            "__run.autodokit.trigger",
            {"input": remote_input, "output": remote_output_dir, "output_name": remote_output_name},
        )

        expected_md = [
            Path(remote_output_dir) / remote_output_name / f"{remote_output_name}.md",
            Path(remote_output_dir) / remote_output_name / "reconstructed_content.md",
        ]

        start = time.time()
        while time.time() - start < timeout:
            markdown = _first_existing(expected_md)
            if markdown:
                doc_output_dir = (Path(remote_output_dir) / remote_output_name).resolve()
                return {
                    **_build_remote_parse_result(doc_output_dir, Path(markdown), mode="mapped", job_id=job_id),
                    "transfer": transfer_res,
                    "trigger": str(trigger_path),
                }
            time.sleep(max(poll_interval, 1))

        return {
            "status": "FAILED",
            "reason": "timeout_waiting_remote_result",
            "transfer": transfer_res,
            "trigger": str(trigger_path),
        }

    if mode == "ssh":
        ssh_cfg_raw = rp.get("ssh") or {}
        ssh_cfg = _load_ssh_connection(dict(ssh_cfg_raw))

        remote_base = _stringify(ssh_cfg.get("remote_base"))
        if not remote_base:
            raise ValueError("ssh mode requires ssh.remote_base")

        remote_cmd_template = _stringify(ssh_cfg.get("remote_cmd"))
        if not remote_cmd_template:
            raise ValueError("ssh.remote_cmd template required for ssh mode")

        job_dir_remote = f"{remote_base.rstrip('/')}/{job_id}"
        remote_input = f"{job_dir_remote}/input/{remote_output_name}{input_pdf.suffix}"
        remote_output_dir = f"{job_dir_remote}/output"

        mkdir_cmd = f"mkdir -p {shlex.quote(job_dir_remote + '/input')} {shlex.quote(remote_output_dir)}"
        mkdir_res = _ssh_run(ssh_cfg, mkdir_cmd, timeout=max(timeout, 30))
        if int(mkdir_res.get("returncode", 1)) != 0:
            raise RuntimeError(f"remote mkdir failed: {mkdir_res.get('stderr') or mkdir_res.get('stdout')}")

        _scp_upload(ssh_cfg, input_pdf, remote_input)

        remote_cmd = remote_cmd_template.format(
            remote_input=remote_input,
            remote_output=remote_output_dir,
            job_id=job_id,
            output_name=remote_output_name,
            remote_output_name=remote_output_name,
        )

        use_tmux = _normalize_bool(ssh_cfg.get("use_tmux"), True)
        tmux_session = ""
        ssh_result: Dict[str, Any]
        if use_tmux:
            tmux_prefix = _stringify(ssh_cfg.get("tmux_session_prefix")) or "a055"
            tmux_session = f"{tmux_prefix}_{job_id[-8:]}"
            launch_cmd = f"tmux new-session -d -s {shlex.quote(tmux_session)} {shlex.quote(remote_cmd)}"
            ssh_result = _ssh_run(ssh_cfg, launch_cmd, timeout=max(timeout, 30))
            if int(ssh_result.get("returncode", 1)) != 0:
                raise RuntimeError(f"remote tmux launch failed: {ssh_result.get('stderr') or ssh_result.get('stdout')}")

            wait_res = _wait_remote_output_ready(
                ssh_cfg,
                remote_output_dir=remote_output_dir,
                remote_output_name=remote_output_name,
                timeout=timeout,
                poll_interval=poll_interval,
            )
            if wait_res.get("status") != "ready":
                raise TimeoutError(f"timeout waiting remote output: {wait_res}")
            ssh_result = {**ssh_result, "wait": wait_res, "tmux_session": tmux_session}
        else:
            ssh_result = _ssh_run(ssh_cfg, remote_cmd, timeout=max(timeout, 30))
            if int(ssh_result.get("returncode", 1)) != 0:
                raise RuntimeError(f"remote command failed: {ssh_result.get('stderr') or ssh_result.get('stdout')}")

        fetch_output = _normalize_bool(ssh_cfg.get("fetch_output"), True)
        if not fetch_output:
            raise ValueError("ssh mode requires fetch_output=true to keep local content.db paths stable")

        _scp_download_dir(ssh_cfg, f"{remote_output_dir}/{remote_output_name}", output_dir)
        parse_output_dir = (output_dir / remote_output_name).resolve()
        markdown_path = _first_existing([
            parse_output_dir / f"{remote_output_name}.md",
            parse_output_dir / "reconstructed_content.md",
        ])
        _ensure_remote_compat_artifacts(
            parse_output_dir,
            output_name=remote_output_name,
            markdown_path=markdown_path,
            job_id=job_id,
        )
        return {
            **_build_remote_parse_result(parse_output_dir, Path(markdown_path) if markdown_path else parse_output_dir / "reconstructed_content.md", mode="ssh", job_id=job_id),
            "ssh_result": ssh_result,
            "artifacts": {
                "output_dir_local": str(parse_output_dir),
                "remote_output_dir": remote_output_dir,
                "tmux_session": tmux_session,
            },
        }

    raise ValueError(f"unsupported remote_processing mode: {mode}")


def run_monkeyocr_single_pdf(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    runtime_settings: Dict[str, Any],
    execution_mode: ExecutionMode = "auto",
    output_name: str | None = None,
    timeout: int = 3600,
    poll_interval: int = 10,
    allow_local_fallback: bool = True,
) -> Dict[str, Any]:
    """统一的 MonkeyOCR 单篇入口。

    Args:
        input_pdf: 待解析 PDF 的绝对路径。
        output_dir: 解析输出根目录。
        runtime_settings: 运行时配置。
        execution_mode: `auto`、`local` 或 `remote`。
        output_name: 可选解析输出目录名。
        timeout: 远端等待超时时间。
        poll_interval: 远端轮询间隔。
        allow_local_fallback: 当 `execution_mode='auto'` 且远端失败时是否回退本地。

    Returns:
        MonkeyOCR 解析结果字典。
    """

    normalized_mode = execution_mode.lower()
    if normalized_mode == "local":
        return _run_local_monkeyocr(
            input_pdf,
            output_dir,
            output_name=output_name,
            runtime_settings=runtime_settings,
        )
    if normalized_mode == "remote":
        return _run_remote_monkeyocr(
            input_pdf,
            output_dir,
            output_name=output_name,
            runtime_settings=runtime_settings,
            timeout=timeout,
            poll_interval=poll_interval,
        )
    if normalized_mode != "auto":
        raise ValueError(f"unsupported execution_mode: {execution_mode}")

    remote_cfg = runtime_settings.get("remote_processing") if isinstance(runtime_settings, dict) else {}
    if isinstance(remote_cfg, dict) and _normalize_bool(remote_cfg.get("enabled"), False):
        try:
            return _run_remote_monkeyocr(
                input_pdf,
                output_dir,
                output_name=output_name,
                runtime_settings=runtime_settings,
                timeout=timeout,
                poll_interval=poll_interval,
            )
        except Exception:
            if not allow_local_fallback:
                raise

    return _run_local_monkeyocr(
        input_pdf,
        output_dir,
        output_name=output_name,
        runtime_settings=runtime_settings,
    )


def run_monkeyocr_remote(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    runtime_settings: Dict[str, Any],
    output_name: str | None = None,
    timeout: int = 3600,
    poll_interval: int = 10,
) -> Dict[str, Any]:
    """兼容旧入口：显式远端运行。"""

    return run_monkeyocr_single_pdf(
        input_pdf,
        output_dir,
        runtime_settings=runtime_settings,
        execution_mode="remote",
        output_name=output_name,
        timeout=timeout,
        poll_interval=poll_interval,
        allow_local_fallback=False,
    )


__all__ = [
    "ExecutionMode",
    "run_monkeyocr_single_pdf",
    "run_monkeyocr_remote",
    "stop_remote_monkeyocr_jobs",
    "launch_remote_tmux_command",
]
