"""autodokit 脱离 autodo-engine 的本地运行时测试。"""

from __future__ import annotations

import json
from pathlib import Path

import autodokit as aok
from autodokit.tools.atomic.task_aok import postprocess_runtime


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


def test_public_api_should_accept_chinese_keyword_arguments(tmp_path: Path) -> None:
    """AOK 公共 API 应支持中文关键字参数。"""

    prepared = aok.prepare_affair_config(
        配置={"output_dir": "output/demo", "topic": "demo"},
        工作区根路径=tmp_path,
    )
    assert Path(prepared["output_dir"]).is_absolute()

    outputs = aok.run_affair(
        事务唯一标识="AOK任务数据库初始化",
        配置={
            "project_root": str(tmp_path),
            "output_dir": str(tmp_path),
        },
        工作区根路径=tmp_path,
    )
    assert len(outputs) == 1

    module = aok.import_affair_module(事务唯一标识="AOK任务数据库初始化")
    assert module.__name__.endswith("AOK任务数据库初始化.affair")

    runtime = aok.bootstrap_runtime(工作区根路径=tmp_path)
    assert runtime["status"] == "PASS"

    registered = aok.register_graph(
        流程图唯一标识="demo_graph_zh",
        流程图={
            "name": "demo_graph_zh",
            "nodes": [{"uid": "n1", "type": "start"}],
            "edges": [],
        },
        工作区根路径=tmp_path,
    )
    loaded = aok.load_graph(
        流程图唯一标识=registered["graph_uid"],
        工作区根路径=tmp_path,
    )
    assert loaded["name"] == "demo_graph_zh"


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


def test_postprocess_json_localization_should_add_chinese_aliases() -> None:
    """后处理中文镜像应保留英文键并补充中文键。"""

    payload = {
        "status": "PASS",
        "gate_action": "pass_next",
        "checks": {
            "local_hit_count": 2,
            "online_triggered": True,
        },
    }

    localized = postprocess_runtime._localize_json_payload_with_zh_alias(payload)

    assert localized["status"] == "PASS"
    assert localized["状态"] == "通过"
    assert localized["gate_action"] == "pass_next"
    assert localized["闸门动作"] == "通过到下一节点"
    assert localized["checks"]["local_hit_count"] == 2
    assert localized["checks"]["本地命中数"] == 2
