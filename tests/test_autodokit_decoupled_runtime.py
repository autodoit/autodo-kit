"""autodokit 脱离 autodo-engine 的本地运行时测试。"""

from __future__ import annotations

import json
from pathlib import Path

import autodokit as aok


def test_run_affair_should_work_without_engine_runtime(tmp_path: Path) -> None:
    """未安装引擎时应可直接运行 AOK 事务。"""

    outputs = aok.run_affair(
        "AOK任务数据库初始化",
        config={
            "project_root": str(tmp_path),
            "output_dir": str(tmp_path),
        },
        workspace_root=tmp_path,
    )

    assert len(outputs) == 1
    payload = json.loads(Path(outputs[0]).read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"


def test_prepare_affair_config_should_resolve_absolute_paths(tmp_path: Path) -> None:
    """事务配置预处理应执行路径绝对化。"""

    prepared = aok.prepare_affair_config(
        config={"output_dir": "output/demo", "topic": "demo"},
        workspace_root=tmp_path,
    )

    assert Path(prepared["output_dir"]).is_absolute()


def test_import_affair_module_should_load_builtin_affair() -> None:
    """应可按事务 UID 导入官方事务模块。"""

    module = aok.import_affair_module("AOK任务数据库初始化")
    assert module.__name__.endswith("AOK任务数据库初始化.affair")


def test_bootstrap_runtime_should_create_runtime_layout(tmp_path: Path) -> None:
    """运行时引导应创建本地目录与注册表。"""

    result = aok.bootstrap_runtime(workspace_root=tmp_path)
    assert result["status"] == "PASS"
    assert (tmp_path / ".autodokit" / "affairs").exists()
    assert (tmp_path / ".autodokit" / "graphs").exists()
    assert (tmp_path / ".autodokit" / "affair_registry.json").exists()
    assert (tmp_path / ".autodokit" / "graph_registry.json").exists()


def test_import_user_affair_should_register_and_execute(tmp_path: Path) -> None:
    """导入用户事务后应可被 run_affair 直接执行。"""

    source = tmp_path / "my_user_affair.py"
    source.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import json",
                "",
                "def execute(config_path: Path):",
                "    cfg = json.loads(Path(config_path).read_text(encoding='utf-8'))",
                "    out = Path(cfg.get('output_dir') or Path(config_path).parent) / 'user_result.json'",
                "    out.parent.mkdir(parents=True, exist_ok=True)",
                "    out.write_text(json.dumps({'status':'PASS'}, ensure_ascii=False), encoding='utf-8')",
                "    return [out]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    imported = aok.import_user_affair(
        source=source,
        affair_uid="用户测试事务",
        workspace_root=tmp_path,
        config_template={"output_dir": "output/user_affair"},
    )
    assert imported["status"] == "PASS"

    outputs = aok.run_affair(
        imported["affair_uid"],
        config={"output_dir": str(tmp_path / "output" / "user_affair")},
        workspace_root=tmp_path,
    )
    assert len(outputs) == 1
    payload = json.loads(Path(outputs[0]).read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"


def test_register_and_load_graph_should_work(tmp_path: Path) -> None:
    """图注册后应可按 UID 回读。"""

    registered = aok.register_graph(
        "demo_graph",
        graph={
            "name": "demo_graph",
            "nodes": [{"uid": "n1", "type": "start"}],
            "edges": [],
        },
        workspace_root=tmp_path,
    )
    assert registered["status"] == "PASS"

    loaded = aok.load_graph(registered["graph_uid"], workspace_root=tmp_path)
    assert loaded["name"] == "demo_graph"
    assert len(loaded["nodes"]) == 1
