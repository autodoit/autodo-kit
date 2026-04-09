"""项目初始化事务测试。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path


def test_project_initialization_should_create_pdf_structured_variant_dirs(tmp_path: Path) -> None:
    """项目初始化应在 workspace/references 下创建 PDF 四组合目录。"""

    module = importlib.import_module("autodokit.affairs.项目初始化.affair")
    workspace_root = tmp_path / "workspace"
    config_path = (workspace_root / "config" / "affairs_config" / "A010.json").resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "output_dir": str(workspace_root / "steps" / "A010_project_bootstrap"),
                "self_check_output_path": str(workspace_root / "steps" / "A010_project_bootstrap" / "self_check.json"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    outputs = module.execute(config_path)
    assert len(outputs) >= 1

    result_path = next(path for path in outputs if path.name == "project_initialization_result.json")
    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert result_payload["git_init_result"]["status"] == "PASS"
    assert result_payload["snapshot_result"]["status"] == "PASS"
    assert (workspace_root / ".git").exists()
    assert (workspace_root / ".gitignore").exists()
    assert "database/logs/aok_log.db" in (workspace_root / ".gitignore").read_text(encoding="utf-8")
    assert (workspace_root / "database" / "tasks" / "tasks.db").exists()
    assert (workspace_root / "config" / "affair_entry_registry.json").exists()
    assert (workspace_root / "steps" / "A010_project_bootstrap" / "self_check.json").exists()

    registry_payload = json.loads((workspace_root / "config" / "affair_entry_registry.json").read_text(encoding="utf-8"))
    assert any(record["node_code"] == "A105" for record in registry_payload["records"])

    references_root = workspace_root / "references"
    assert (references_root / "structured_local_pipeline_v2_reference_context").is_dir()
    assert (references_root / "structured_local_pipeline_v2_full_fine_grained").is_dir()
    assert (references_root / "structured_babeldoc_reference_context").is_dir()
    assert (references_root / "structured_babeldoc_full_fine_grained").is_dir()
