"""MonkeyOCR 批量 affair 测试。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path


def _load_module():
    return importlib.import_module("autodokit.affairs.MonkeyOCR批量解析PDF.affair")


def test_build_priority_file_list_should_preserve_rank_and_windows_candidates(tmp_path: Path) -> None:
    module = _load_module()
    csv_path = tmp_path / "priority.csv"
    csv_path.write_text(
        "priority_rank,pdf_path,pdf_attachment_name\n"
        "2,C:\\docs\\beta.pdf,beta.pdf\n"
        "1,C:\\docs\\alpha.pdf,alpha.pdf\n",
        encoding="utf-8-sig",
    )

    result_path = module._build_priority_file_list(
        csv_path,
        tmp_path / "runtime",
        rank_column="priority_rank",
        pdf_path_column="pdf_path",
    )

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload[0][0] == r"C:\docs\alpha.pdf"
    assert "alpha.pdf" in payload[0]
    assert payload[1][0] == r"C:\docs\beta.pdf"
    assert "beta.pdf" in payload[1]


def test_run_from_payload_foreground_should_route_through_tools(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    input_dir = tmp_path / "attachments"
    output_dir = tmp_path / "outputs"
    monkey_root = tmp_path / "MonkeyOCR-main"
    runtime_dir = tmp_path / "runtime"
    input_dir.mkdir()
    output_dir.mkdir()
    monkey_root.mkdir()
    (monkey_root / "parse.py").write_text("print('ok')\n", encoding="utf-8")
    csv_path = tmp_path / "priority.csv"
    csv_path.write_text("priority_rank,pdf_path\n1,demo.pdf\n", encoding="utf-8-sig")

    captured: dict[str, object] = {}

    def _fake_batch(**kwargs):
        captured.update(kwargs)
        return {"status": "SUCCEEDED", "files": []}

    monkeypatch.setattr(module, "run_monkeyocr_windows_batch_folder", _fake_batch)
    monkeypatch.setattr(
        module,
        "update_monkeyocr_batch_status_csv",
        lambda priority_csv, output_dir, backup=True: {
            "csv_path": str(priority_csv),
            "output_dir": str(output_dir),
            "backup": backup,
        },
    )

    result = module.run_from_payload(
        {
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "runtime_dir": str(runtime_dir),
            "monkey_root": str(monkey_root),
            "priority_csv": str(csv_path),
            "use_priority_order": True,
            "launch_mode": "foreground",
            "python_executable": str(Path(__import__("sys").executable).resolve()),
        }
    )

    assert result["status"] == "SUCCEEDED"
    assert Path(str(captured["file_list"])).exists()
    assert Path(str(captured["runtime_dir"])).resolve() == runtime_dir.resolve()
    assert result["status_sync"]["backup"] is True


def test_run_from_payload_auto_on_server_should_delegate_to_tmux(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    input_dir = tmp_path / "attachments"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    output_dir.mkdir()

    monkeypatch.setattr(module, "_is_server_runtime", lambda: True)
    monkeypatch.setattr(
        module,
        "_launch_tmux_job",
        lambda config_payload, runtime_root: {
            "status": "SUBMITTED",
            "tmux_session_name": "aok_monkeyocr_test",
            "tmux_launch_config": str(runtime_root / "tmux_launch_config.json"),
            "tmux_log_path": str(runtime_root / "tmux_launch.log"),
        },
    )

    result = module.run_from_payload(
        {
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "launch_mode": "auto",
        }
    )

    assert result["status"] == "SUBMITTED"
    assert result["launch_mode"] == "tmux"