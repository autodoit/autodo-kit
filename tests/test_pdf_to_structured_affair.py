"""PDF 转结构化事务测试。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pandas as pd

from autodokit.tools.bibliodb_sqlite import get_structured_state, save_tables
from autodokit.tools.ocr.classic.pdf_structured_data_tools import build_structured_data_payload


def test_pdf_to_structured_affair_should_route_to_variant_dir_and_update_content_db(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """未显式提供输出目录时，应按四组合契约自动落盘并回写对应字段。"""

    module = importlib.import_module("autodokit.affairs.PDF文件转结构化数据文件.affair")

    workspace_root = (tmp_path / "workspace").resolve()
    content_db = workspace_root / "database" / "content" / "content.db"
    input_pdf_dir = workspace_root / "incoming_pdfs"
    input_pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = (input_pdf_dir / "demo.pdf").resolve()
    pdf_path.write_bytes(b"%PDF-1.4\n%demo\n")

    literatures_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-2026",
                "title": "Demo Document",
                "pdf_path": str(pdf_path),
                "primary_attachment_name": pdf_path.name,
                "created_at": "",
                "updated_at": "",
            }
        ]
    )
    save_tables(content_db, literatures_df=literatures_df, if_exists="replace")

    expected_output_dir = workspace_root / "references" / "structured_local_pipeline_v2_reference_context"
    expected_output_dir.mkdir(parents=True, exist_ok=True)

    def _fake_convert(
        input_pdf_path: Path,
        output_path: Path,
        *,
        extractors=None,
        task_type: str,
        uid_literature: str = "",
        cite_key: str = "",
        source_metadata=None,
    ) -> Path:
        payload = build_structured_data_payload(
            pdf_path=input_pdf_path,
            backend="local_pipeline_v2",
            backend_family="local_pipeline",
            task_type=task_type,
            full_text="demo full text",
            extract_error=None,
            uid_literature=uid_literature,
            cite_key=cite_key,
            title=str((source_metadata or {}).get("title") or ""),
            year=str((source_metadata or {}).get("year") or ""),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    monkeypatch.setattr(module, "convert_pdf_to_structured_data_file_local_v2", _fake_convert)

    config_path = (tmp_path / "pdf_to_structured_config.json").resolve()
    config_path.write_text(
        json.dumps(
            {
                "input_pdf_dir": str(input_pdf_dir),
                "output_structured_dir": "",
                "converter": "local_pipeline_v2",
                "task_type": "reference_context",
                "content_db": str(content_db),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    outputs = module.execute(config_path)
    structured_outputs = [path for path in outputs if path.name.endswith(".structured.json")]
    assert len(structured_outputs) == 1
    assert structured_outputs[0].parent == expected_output_dir

    state = get_structured_state(content_db, "lit-001")
    assert state["structured_backend"] == "local_pipeline_v2"
    assert state["structured_task_type"] == "reference_context"
    assert state["structured_path_local_pipeline_v2_reference_context"] == str(structured_outputs[0])
    assert not state["structured_path_babeldoc_reference_context"]

