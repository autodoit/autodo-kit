"""MonkeyOCR 统一入口测试。"""

from __future__ import annotations

import json
from pathlib import Path


def test_run_monkeyocr_single_pdf_local_mode_should_not_use_remote_transfer(monkeypatch, tmp_path: Path) -> None:
    from autodokit.tools.ocr.monkeyocr import runner

    called = {"remote_transfer": 0, "local": 0}

    def _fake_local(**kwargs):
        called["local"] += 1
        return {
            "status": "SUCCEEDED",
            "output_dir": str(tmp_path / "local_out"),
            "artifacts": {"markdown": str(tmp_path / "local_out" / "demo.md")},
        }

    def _fail_remote(*args, **kwargs):
        called["remote_transfer"] += 1
        raise AssertionError("remote_transfer should not be used in local mode")

    monkeypatch.setattr(runner, "run_monkeyocr_windows_single_pdf", _fake_local)
    monkeypatch.setattr(runner.remote_transfer, "transfer", _fail_remote)
    monkeypatch.setattr(runner.remote_transfer, "write_trigger_file", _fail_remote)
    monkeypatch.setattr(runner.remote_transfer, "trigger_via_ssh", _fail_remote)

    result = runner.run_monkeyocr_single_pdf(
        tmp_path / "input.pdf",
        tmp_path / "out",
        runtime_settings={"monkeyocr_root": str(tmp_path / "monkey")},
        execution_mode="local",
    )

    assert result["status"] == "SUCCEEDED"
    assert called["local"] == 1
    assert called["remote_transfer"] == 0


def test_run_monkeyocr_single_pdf_remote_mode_should_use_remote_transfer(monkeypatch, tmp_path: Path) -> None:
    from autodokit.tools.ocr.monkeyocr import runner

    input_pdf = tmp_path / "paper.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n%demo\n")
    output_dir = tmp_path / "out"
    mapped_root = tmp_path / "mapped"
    remote_state: dict[str, Path] = {}

    def _fake_transfer(local_path: str, remote_path: str, *, ensure_dirs: bool = True):
        del ensure_dirs
        src = Path(local_path)
        dst = Path(remote_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        remote_state["remote_input"] = dst
        return {"path": str(dst)}

    def _fake_trigger(remote_dir: str, trigger_name: str = "__run.autodokit.trigger", payload: dict | None = None):
        del trigger_name
        trigger_path = Path(remote_dir) / "__run.autodokit.trigger"
        trigger_path.parent.mkdir(parents=True, exist_ok=True)
        trigger_path.write_text(json.dumps(payload or {}, ensure_ascii=False), encoding="utf-8")
        output_root = Path((payload or {}).get("output", ""))
        stem = Path((payload or {}).get("input", "paper.pdf")).stem
        md_path = output_root / stem / f"{stem}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text("# demo", encoding="utf-8")
        (output_root / stem / "parse_record.json").write_text(json.dumps({"schema": "demo"}, ensure_ascii=False), encoding="utf-8")
        (output_root / stem / "quality_report.json").write_text(json.dumps({"status": "SUCCEEDED"}, ensure_ascii=False), encoding="utf-8")
        (output_root / stem / "linear_index.json").write_text(json.dumps({"paragraphs": []}, ensure_ascii=False), encoding="utf-8")
        (output_root / stem / "chunk_manifest.json").write_text(json.dumps([], ensure_ascii=False), encoding="utf-8")
        (output_root / stem / "chunks.jsonl").write_text("", encoding="utf-8")
        return str(trigger_path)

    def _fake_ssh(*args, **kwargs):
        del args, kwargs
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(runner.remote_transfer, "transfer", _fake_transfer)
    monkeypatch.setattr(runner.remote_transfer, "write_trigger_file", _fake_trigger)
    monkeypatch.setattr(runner.remote_transfer, "trigger_via_ssh", _fake_ssh)
    monkeypatch.setattr(runner, "run_monkeyocr_windows_single_pdf", lambda **kwargs: (_ for _ in ()).throw(AssertionError("local path should not be used")))

    result = runner.run_monkeyocr_single_pdf(
        input_pdf,
        output_dir,
        runtime_settings={
            "remote_processing": {
                "enabled": True,
                "mode": "mapped",
                "mapped_root": str(mapped_root),
                "job_id": "job-001",
                "timeout": 5,
                "poll_interval": 0,
            }
        },
        execution_mode="remote",
        timeout=5,
        poll_interval=0,
    )

    assert result["status"] == "SUCCEEDED"
    assert remote_state["remote_input"].exists()
    assert Path(result["output_dir"]).exists()
    assert Path(result["reconstructed_markdown_path"]).exists()


def test_launch_remote_tmux_command_should_delegate_to_ssh(monkeypatch) -> None:
    from autodokit.tools.ocr.monkeyocr import runner

    monkeypatch.setattr(runner, "_load_ssh_connection", lambda cfg: {"host": "dummy", "user": "dummy", **cfg})
    captured: dict[str, str] = {}

    def _fake_ssh_run(_ssh_cfg, remote_command: str, *, timeout: int):
        captured["cmd"] = remote_command
        captured["timeout"] = str(timeout)
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(runner, "_ssh_run", _fake_ssh_run)

    result = runner.launch_remote_tmux_command(
        {
            "remote_processing": {
                "enabled": True,
                "mode": "ssh",
                "ssh": {"host": "dummy", "user": "dummy"},
            }
        },
        remote_command="echo remote-only-a070",
        session_prefix="a070",
        session_name="a055_test_session",
        timeout=15,
    )

    assert result["session_name"] == "a055_test_session"
    assert "tmux new-session" in captured["cmd"]
    assert "a055_test_session" in captured["cmd"]


def test_launch_remote_tmux_command_should_quote_inline_python(monkeypatch) -> None:
    from autodokit.tools.ocr.monkeyocr import runner

    monkeypatch.setattr(runner, "_load_ssh_connection", lambda cfg: {"host": "dummy", "user": "dummy", **cfg})
    captured: dict[str, str] = {}

    def _fake_ssh_run(_ssh_cfg, remote_command: str, *, timeout: int):
        captured["cmd"] = remote_command
        captured["timeout"] = str(timeout)
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(runner, "_ssh_run", _fake_ssh_run)

    runner.launch_remote_tmux_command(
        {
            "remote_processing": {
                "enabled": True,
                "mode": "ssh",
                "ssh": {"host": "dummy", "user": "dummy"},
            }
        },
        remote_command="cd /repo && ./.venv/bin/python -c \"from pathlib import Path; print(Path('demo'))\"",
        session_prefix="a070",
        session_name="a055_python_inline",
        timeout=15,
    )

    assert 'bash -lc ' in captured["cmd"]
    assert 'tmux new-session -d -s a055_python_inline bash -lc ' in captured["cmd"]
    assert 'python -c "from pathlib import Path; print(Path(' in captured["cmd"]
    assert '"bash -lc ' not in captured["cmd"]
