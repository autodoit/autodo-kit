"""项目初始化事务测试。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path


def test_project_initialization_should_create_pdf_structured_variant_dirs(tmp_path: Path) -> None:
    """项目初始化应在 workspace/references 下创建 PDF 四组合目录。"""

    module = importlib.import_module("autodokit.affairs.项目初始化.affair")
    config_path = (tmp_path / "project_init_config.json").resolve()
    config_path.write_text(
        json.dumps(
            {
                "project_root": str(tmp_path),
                "output_dir": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    outputs = module.execute(config_path)
    assert len(outputs) == 1

    result_payload = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert result_payload["git_init_result"]["status"] == "PASS"
    assert result_payload["snapshot_result"]["status"] == "PASS"
    assert (tmp_path / ".git").exists()
    assert (tmp_path / ".gitignore").exists()
    assert "database/logs/aok_log.db" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert (tmp_path / "database" / "tasks" / "tasks.db").exists()

    references_root = tmp_path / "references"
    assert (references_root / "structured_local_pipeline_v2_reference_context").is_dir()
    assert (references_root / "structured_local_pipeline_v2_full_fine_grained").is_dir()
    assert (references_root / "structured_babeldoc_reference_context").is_dir()
    assert (references_root / "structured_babeldoc_full_fine_grained").is_dir()
