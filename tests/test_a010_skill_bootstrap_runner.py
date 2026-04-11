"""A010 技能脚本桥接 runner 测试。"""

from __future__ import annotations

import json
from pathlib import Path

from autodokit.tools.affair_entry_registry_tools import build_mainline_affair_entry_registry
from autodokit.tools.a010_skill_bootstrap_runner import execute


def test_mainline_registry_should_point_a010_to_skill_runner(tmp_path: Path) -> None:
    """主链注册表中的 A010 应指向技能脚本桥接 runner。"""

    payload = build_mainline_affair_entry_registry(workspace_root=tmp_path / "workspace")
    a010 = next(record for record in payload["records"] if record["node_code"] == "A010")
    assert a010["module"] == "autodokit.tools.a010_skill_bootstrap_runner"
    assert a010["callable"] == "execute"


def test_a010_skill_runner_should_invoke_generate_config_script(monkeypatch, tmp_path: Path) -> None:
    """A010 runner 应把配置映射为 generate_config.py 调用。"""

    workspace_root = tmp_path / "workspace"
    config_dir = workspace_root / "config"
    affairs_dir = config_dir / "affairs_config"
    affairs_dir.mkdir(parents=True, exist_ok=True)

    skill_root = tmp_path / "A010_项目初始化_v6"
    script_path = skill_root / "scripts" / "generate_config.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("print('ok')\n", encoding="utf-8")
    template_root = skill_root / "assets" / "templates" / "workspace"
    template_root.mkdir(parents=True, exist_ok=True)

    a020_config_path = affairs_dir / "A020.json"
    a020_config_path.write_text(
        json.dumps(
            {
                "origin_bib_paths": [str((tmp_path / "refs" / "library.bib").resolve())],
                "origin_attachments_root": str((tmp_path / "refs" / "attachments").resolve()),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    task_dir = workspace_root / "tasks" / "20260411172244-A010"
    task_dir.mkdir(parents=True, exist_ok=True)
    self_check_path = task_dir / "self_check.json"
    self_check_path.write_text("{}\n", encoding="utf-8")
    result_path = task_dir / "project_initialization_result.json"
    result_path.write_text("{}\n", encoding="utf-8")

    global_config_path = config_dir / "config.json"
    global_config_path.write_text(
        json.dumps(
            {
                "workflow_name": "学术科研工作流工作空间",
                "root_path": str(tmp_path.resolve()).replace("\\", "/"),
                "workspace_root": str(workspace_root.resolve()).replace("\\", "/"),
                "venv_path": str((tmp_path / ".venv").resolve()).replace("\\", "/"),
                "project": {
                    "project_name": "SystemicRiskResearch",
                    "project_goal": "你的项目研究主题",
                },
                "llm": {
                    "aliyun_api_key_file": str((tmp_path / "configs" / "bailian-api-key.txt").resolve()).replace("\\", "/"),
                },
                "bootstrap": {
                    "template_root": str(template_root.resolve()).replace("\\", "/"),
                    "self_check_report_path": str(self_check_path.resolve()).replace("\\", "/"),
                },
                "node_inputs": {
                    "A020": str(a020_config_path.resolve()).replace("\\", "/"),
                },
                "is_auto_git_commit": "是",
                "自动提交前是否询问人类": "否",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    local_config_path = affairs_dir / "A010.json"
    local_config_path.write_text(
        json.dumps(
            {
                "template_root": str(template_root.resolve()).replace("\\", "/"),
                "dry_run": False,
                "is_auto_git_commit": "是",
                "自动提交前是否询问人类": "否",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "ok"
            self.stderr = ""

    def _fake_run(command, cwd=None, check=False, capture_output=False, text=False):
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "check": check,
                "capture_output": capture_output,
                "text": text,
            }
        )
        return _Completed()

    monkeypatch.setattr("autodokit.tools.a010_skill_bootstrap_runner.subprocess.run", _fake_run)

    outputs = execute(local_config_path)
    assert calls, "应调用 generate_config.py"
    command = calls[0]["command"]
    assert str(script_path.resolve()) in command
    assert "--workflow-name" in command
    assert "--llm-api-key-file" in command
    assert "--origin-bib-path" in command
    assert "--origin-attachments-root" in command
    assert "--auto-snapshot" in command
    assert calls[0]["cwd"] == str(script_path.parent)
    assert self_check_path in outputs
    assert result_path in outputs
