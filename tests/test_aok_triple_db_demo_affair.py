"""AOK 三库联动示例事务测试。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path


def _write_demo_bib(path: Path) -> None:
    """写入最小 BibTeX 测试数据。

    Args:
        path: BibTeX 文件路径。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "@article{demo-1,",
                "  title={Demo Document One},",
                "  author={Alice and Bob},",
                "  year={2024}",
                "}",
                "",
                "@article{demo-2,",
                "  title={Demo Document Two},",
                "  author={Carol},",
                "  year={2023}",
                "}",
            ]
        ),
        encoding="utf-8",
    )


def _write_nested_rdf_files(root: Path) -> None:
    """写入 Zotero 风格嵌套附件结构。

    Args:
        root: `files/` 根目录。
    """

    (root / "1001").mkdir(parents=True, exist_ok=True)
    (root / "1002").mkdir(parents=True, exist_ok=True)
    (root / "1001" / "doc-a.pdf").write_text("pdf-a", encoding="utf-8")
    (root / "1002" / "doc-b.html").write_text("<html>doc-b</html>", encoding="utf-8")


def test_aok_triple_db_demo_execute_should_generate_three_db_outputs(tmp_path: Path) -> None:
    """示例事务执行后应生成三库数据与任务结果文件。"""

    module = importlib.import_module("autodokit.affairs.AOK三库联动示例.affair")

    project_root = (tmp_path / "workspace").resolve()
    output_dir = (project_root / "outputs").resolve()
    bib_path = (tmp_path / "data" / "demo.bib").resolve()
    rdf_files_root = (tmp_path / "data" / "rdf" / "files").resolve()

    _write_demo_bib(bib_path)
    _write_nested_rdf_files(rdf_files_root)

    config_path = (tmp_path / "demo_config.json").resolve()
    config_path.write_text(
        json.dumps(
            {
                "project_root": str(project_root),
                "bib_path": str(bib_path),
                "rdf_files_root": str(rdf_files_root),
                "max_bib_records": 2,
                "max_attachments": 2,
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    outputs = module.execute(config_path)
    assert len(outputs) == 1
    result = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert result["summary"]["literature_count"] >= 1
    assert result["summary"]["knowledge_count"] >= 1
    assert result["summary"]["copied_attachment_count"] >= 1

    assert (project_root / "database" / "content" / "content.db").exists()
    assert (project_root / "database" / "tasks" / "tasks.csv").exists()
    assert result["outputs"]["content_db"] == str((project_root / "database" / "content" / "content.db").resolve())
    assert result["outputs"]["generated_note_paths"]
    copied_attachments = list((project_root / "references" / "attachments").glob("*"))
    assert copied_attachments
