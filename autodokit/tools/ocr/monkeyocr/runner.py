"""MonkeyOCR 统一运行入口。

提供本地与远端两种执行模式：
- local: 直接调用 Windows 本地解析工具。
- remote: 通过 remote_transfer 传输并触发远端执行。

该入口保持上层调用契约稳定，避免业务层直接依赖远端传输细节。
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Literal

from autodokit.tools import remote_transfer
from autodokit.tools.ocr.monkeyocr.monkeyocr_windows_tools import run_monkeyocr_windows_single_pdf


ExecutionMode = Literal["auto", "local", "remote"]


def _now_ts() -> str:
    return time.strftime("%Y%m%d%H%M%S", time.localtime())


def _first_existing(paths: list[Path]) -> str:
    for path in paths:
        if path.exists() and path.is_file():
            return str(path.resolve())
    return ""


def _build_remote_parse_result(output_dir: Path, markdown_path: Path, *, mode: str, job_id: str) -> Dict[str, Any]:
    """构造与本地 MonkeyOCR 一致的解析结果结构。"""

    default_md = output_dir / "reconstructed_content.md"
    md_path = markdown_path.resolve() if markdown_path and markdown_path.exists() else default_md.resolve()

    return {
        "status": "SUCCEEDED",
        "mode": mode,
        "job_id": job_id,
        "output_dir": str(output_dir.resolve()),
        "reconstructed_markdown_path": str(md_path),
        "linear_index_path": str((output_dir / "linear_index.json").resolve()),
        "chunk_manifest_path": str((output_dir / "chunk_manifest.json").resolve()),
        "chunks_jsonl_path": str((output_dir / "chunks.jsonl").resolve()),
        "parse_record_path": str((output_dir / "parse_record.json").resolve()),
        "quality_report_path": str((output_dir / "quality_report.json").resolve()),
        "llm_backend": "monkeyocr_remote",
        "llm_model": "remote_monkeyocr",
    }


def _run_local_monkeyocr(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    runtime_settings: Dict[str, Any],
) -> Dict[str, Any]:
    """运行本地 MonkeyOCR 单篇解析。"""

    return run_monkeyocr_windows_single_pdf(
        input_pdf=str(Path(input_pdf).expanduser().resolve()),
        output_dir=str(Path(output_dir).expanduser().resolve()),
        monkeyocr_root=str(runtime_settings.get("monkeyocr_root") or ""),
        models_dir=runtime_settings.get("models_dir"),
        config_path=runtime_settings.get("config_path"),
        model_name=runtime_settings.get("model_name") or runtime_settings.get("monkeyocr_model") or None,
        device=runtime_settings.get("device") or "cuda",
        gpu_visible_devices=runtime_settings.get("gpu_visible_devices") or "0",
        ensure_runtime=runtime_settings.get("ensure_runtime", True),
        download_source=runtime_settings.get("download_source", "huggingface"),
        pip_index_url=runtime_settings.get("pip_index_url"),
        python_executable=runtime_settings.get("python_executable"),
        stream_output=False,
    )


def _run_remote_monkeyocr(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    runtime_settings: Dict[str, Any],
    timeout: int,
    poll_interval: int,
) -> Dict[str, Any]:
    """运行远端 MonkeyOCR 单篇解析。"""

    input_pdf = Path(input_pdf).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    rp = runtime_settings.get("remote_processing") or {}
    if not rp.get("enabled"):
        raise ValueError("remote_processing.enabled must be true for remote execution")

    mode = str(rp.get("mode") or "mapped").lower()
    job_id = rp.get("job_id") or f"autodokit_job_{_now_ts()}"
    stem = input_pdf.stem

    if mode == "mapped":
        mapped_root = Path(rp.get("mapped_root"))
        job_dir = (mapped_root / job_id).resolve()
        remote_input = str((job_dir / "input" / input_pdf.name).resolve())
        remote_output_dir = str((job_dir / "output").resolve())

        transfer_res = remote_transfer.transfer(str(input_pdf), remote_input)
        trigger_path = remote_transfer.write_trigger_file(
            str(job_dir / "control"),
            "__run.autodokit.trigger",
            {"input": remote_input, "output": remote_output_dir},
        )

        expected_md = Path(remote_output_dir) / stem / f"{stem}.md"
        start = time.time()
        while time.time() - start < timeout:
            if expected_md.exists():
                doc_output_dir = (Path(remote_output_dir) / stem).resolve()
                return {
                    **_build_remote_parse_result(doc_output_dir, expected_md, mode="mapped", job_id=job_id),
                    "transfer": transfer_res,
                    "trigger": str(trigger_path),
                }
            time.sleep(poll_interval)

        return {"status": "FAILED", "reason": "timeout_waiting_remote_result", "transfer": transfer_res, "trigger": str(trigger_path)}

    if mode == "ssh":
        ssh_cfg = rp.get("ssh") or {}
        remote_base = ssh_cfg.get("remote_base")
        if not remote_base:
            raise ValueError("ssh mode requires ssh.remote_base in remote_processing.ssh")
        job_dir_remote = f"{remote_base.rstrip('/')}/{job_id}"
        remote_input = f"{job_dir_remote}/input/{input_pdf.name}"
        remote_output_dir = f"{job_dir_remote}/output"

        try:
            transfer_res = remote_transfer.transfer(str(input_pdf), remote_input)
            used_scp = False
        except Exception:
            scp_cmd = ["scp"]
            if ssh_cfg.get("key"):
                scp_cmd += ["-i", str(ssh_cfg.get("key"))]
            scp_cmd += [str(input_pdf), f"{ssh_cfg.get('user')}@{ssh_cfg.get('host')}:{remote_input}"]
            subprocess.run(scp_cmd, check=True)
            transfer_res = {"path": remote_input}
            used_scp = True

        remote_cmd_template = ssh_cfg.get("remote_cmd")
        if not remote_cmd_template:
            raise ValueError("ssh.remote_cmd template required for ssh mode")
        cmd = remote_cmd_template.format(remote_input=remote_input, remote_output=remote_output_dir, job_id=job_id)
        ssh_result = remote_transfer.trigger_via_ssh(ssh_cfg.get("host"), ssh_cfg.get("user"), cmd, ssh_cfg.get("key"), timeout=timeout)

        artifacts: dict[str, Any] = {}
        markdown_path = Path()
        parse_output_dir = None
        if ssh_cfg.get("fetch_output"):
            local_fetch_dir = output_dir / job_id
            local_fetch_dir.mkdir(parents=True, exist_ok=True)
            scp_cmd = ["scp", "-r"]
            if ssh_cfg.get("key"):
                scp_cmd += ["-i", str(ssh_cfg.get("key"))]
            scp_cmd += [f"{ssh_cfg.get('user')}@{ssh_cfg.get('host')}:{remote_output_dir}/{stem}", str(local_fetch_dir)]
            subprocess.run(scp_cmd, check=False)
            parse_output_dir = (local_fetch_dir / stem).resolve()
            artifacts["output_dir_local"] = str(parse_output_dir)
            markdown_path = parse_output_dir / f"{stem}.md"
            if not markdown_path.exists():
                markdown_path = parse_output_dir / "reconstructed_content.md"

        status = "SUCCEEDED" if ssh_result.get("returncode") == 0 else "FAILED"
        if status != "SUCCEEDED":
            return {"status": status, "ssh_result": ssh_result, "transfer": transfer_res, "artifacts": artifacts, "used_scp": used_scp}
        if parse_output_dir is None:
            raise ValueError("ssh mode requires fetch_output=true to produce local parse assets")
        return {
            **_build_remote_parse_result(parse_output_dir, markdown_path, mode="ssh", job_id=job_id),
            "ssh_result": ssh_result,
            "transfer": transfer_res,
            "artifacts": artifacts,
            "used_scp": used_scp,
        }

    raise ValueError(f"unsupported remote_processing mode: {mode}")


def run_monkeyocr_single_pdf(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    runtime_settings: Dict[str, Any],
    execution_mode: ExecutionMode = "auto",
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
        timeout: 远端等待超时时间。
        poll_interval: 远端轮询间隔。
        allow_local_fallback: 当 `execution_mode='auto'` 且远端失败时是否回退本地。

    Returns:
        MonkeyOCR 解析结果字典。
    """

    normalized_mode = execution_mode.lower()
    if normalized_mode == "local":
        return _run_local_monkeyocr(input_pdf, output_dir, runtime_settings=runtime_settings)
    if normalized_mode == "remote":
        return _run_remote_monkeyocr(input_pdf, output_dir, runtime_settings=runtime_settings, timeout=timeout, poll_interval=poll_interval)
    if normalized_mode != "auto":
        raise ValueError(f"unsupported execution_mode: {execution_mode}")

    remote_cfg = runtime_settings.get("remote_processing") if isinstance(runtime_settings, dict) else {}
    if isinstance(remote_cfg, dict) and remote_cfg.get("enabled"):
        try:
            return _run_remote_monkeyocr(input_pdf, output_dir, runtime_settings=runtime_settings, timeout=timeout, poll_interval=poll_interval)
        except Exception:
            if not allow_local_fallback:
                raise
    return _run_local_monkeyocr(input_pdf, output_dir, runtime_settings=runtime_settings)


def run_monkeyocr_remote(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    runtime_settings: Dict[str, Any],
    timeout: int = 3600,
    poll_interval: int = 10,
) -> Dict[str, Any]:
    """兼容旧入口：显式远端运行。"""

    return run_monkeyocr_single_pdf(
        input_pdf,
        output_dir,
        runtime_settings=runtime_settings,
        execution_mode="remote",
        timeout=timeout,
        poll_interval=poll_interval,
        allow_local_fallback=False,
    )


__all__ = ["ExecutionMode", "run_monkeyocr_single_pdf", "run_monkeyocr_remote"]
