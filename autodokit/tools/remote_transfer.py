"""通用远程传输与触发工具。

功能：
- 支持将本地文件或目录原子复制到远端映射盘符（Windows 映射盘符或网络共享路径）。
- 支持通过 SSH 触发远端命令（使用系统 ssh 客户端）。
- 提供组合接口 `run_remote_task`：拷贝 -> 触发 -> 可选校验。

设计原则：保持无外部依赖（使用标准库 subprocess/ssh），尽量原子写入并返回校验信息。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def transfer(local_path: str, remote_path: str, *, ensure_dirs: bool = True) -> Dict:
    """把 local_path 原子复制到 remote_path。

    - local_path: 文件或目录
    - remote_path: 目标文件或目标目录路径
    返回包含 path/size/sha256（若为文件）的元信息字典
    """
    src = Path(local_path)
    dst = Path(remote_path)

    if not src.exists():
        raise FileNotFoundError(f"source not found: {src}")

    if ensure_dirs:
        dst_parent = dst if dst.is_dir() else dst.parent
        dst_parent.mkdir(parents=True, exist_ok=True)

    if src.is_file():
        # 先复制到临时文件再替换，保证原子性
        tmp = dst.with_suffix(dst.suffix + ".autodokit_tmp")
        shutil.copy2(src, tmp)
        tmp.replace(dst)
        checksum = _sha256(dst)
        return {"path": str(dst), "size": dst.stat().st_size, "sha256": checksum}

    # src is a directory: 使用复制目录（覆盖目标同名目录）
    if dst.exists() and dst.is_file():
        raise IsADirectoryError(f"destination exists as file: {dst}")

    # 复制到一个临时目录然后重命名
    tmpdir = Path(tempfile.mkdtemp(prefix="autodokit_remote_transfer_", dir=str(dst.parent)))
    try:
        # copytree into tmpdir/<src_name>
        target = tmpdir / src.name
        shutil.copytree(src, target)
        final_target = dst
        # 如果目标已存在，先删除再替换
        if final_target.exists():
            shutil.rmtree(final_target)
        target.replace(final_target)
    except Exception:
        # 清理 tmpdir 并抛出
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    finally:
        # 若 tmpdir 仍存在，尝试移除
        if tmpdir.exists():
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                pass

    return {"path": str(final_target)}


def write_trigger_file(remote_dir: str, trigger_name: str = "__run.autodokit.trigger", payload: Optional[dict] = None) -> str:
    """在远端目录写入触发文件（原子写入）。"""
    p_dir = Path(remote_dir)
    p_dir.mkdir(parents=True, exist_ok=True)
    p = p_dir / trigger_name
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload or {"triggered_by": "autodokit"}, fh, ensure_ascii=False)
    tmp.replace(p)
    return str(p)


def trigger_via_ssh(ssh_host: str, ssh_user: str, cmd: str, ssh_key: Optional[str] = None, timeout: int = 3600) -> Dict:
    """通过系统 ssh 客户端在远端执行命令。

    依赖：本机必须能运行 `ssh` 命令并能以指定 key 或已配置 agent 免交互登录。
    返回包含 returncode/stdout/stderr。
    """
    ssh_cmd = ["ssh", "-o", "BatchMode=yes"]
    if ssh_key:
        ssh_cmd += ["-i", ssh_key]
    ssh_cmd += [f"{ssh_user}@{ssh_host}", cmd]
    proc = subprocess.run(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def run_remote_task(
    local_input: str,
    remote_input_path: str,
    *,
    mode: str = "mapped",
    ssh_cfg: Optional[dict] = None,
    remote_cmd: Optional[str] = None,
    verify: bool = True,
):
    """组合接口：传输 -> 触发 -> 返回结果信息。

    mode: 'mapped' 或 'ssh'
    - mapped: 直接把文件/目录复制到 `remote_input_path`，并在其父目录写入 trigger 文件
    - ssh: 复制后通过 ssh 在远端执行 `remote_cmd`（remote_cmd 可以包含 {remote_input} 占位）
    """
    transfer_res = transfer(local_input, remote_input_path)

    trigger_res = None
    if mode == "mapped":
        trigger_res = {"mode": "mapped", "trigger_file": write_trigger_file(Path(remote_input_path).parent, "__run.autodokit.trigger", {"input": remote_input_path})}
    elif mode == "ssh":
        if not ssh_cfg or not remote_cmd:
            raise ValueError("ssh mode requires ssh_cfg and remote_cmd")
        cmd = remote_cmd.format(remote_input=remote_input_path)
        trigger_res = {"mode": "ssh", "ssh_result": trigger_via_ssh(ssh_cfg["host"], ssh_cfg["user"], cmd, ssh_cfg.get("key"))}
    else:
        raise ValueError(f"unknown mode: {mode}")

    result = {"transfer": transfer_res, "trigger": trigger_res}

    if verify and transfer_res.get("path") and Path(transfer_res["path"]).exists():
        # 如果是文件，返回 sha256；如果目录仅返回存在
        p = Path(transfer_res["path"])
        if p.is_file():
            result["verify"] = {"exists": True, "sha256": _sha256(p)}
        else:
            result["verify"] = {"exists": True}
    else:
        result["verify"] = {"exists": False}

    return result


__all__ = ["transfer", "write_trigger_file", "trigger_via_ssh", "run_remote_task"]
