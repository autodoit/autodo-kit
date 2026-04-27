"""MonkeyOCR 清单驱动运行时与事务接入测试。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pandas as pd

from autodokit.tools.bibliodb_sqlite import (
    get_structured_state,
    load_reading_queue_df,
    load_reading_state_df,
    load_review_state_df,
    upsert_reading_state_rows,
    upsert_review_state_rows,
)
from autodokit.tools.storage_backend import persist_reference_tables


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _prepare_workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace_root = (tmp_path / "workspace").resolve()
    content_db = workspace_root / "database" / "content" / "content.db"
    pdf_path = workspace_root / "references" / "attachments" / "demo.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\n%demo\n")

    _write_json(
        workspace_root / "config" / "config.json",
        {
            "workspace_root": str(workspace_root),
            "logging": {"enabled": False},
            "paths": {
                "log_db_path": str(workspace_root / "database" / "logs" / "aok_log.db"),
                "content_db_path": str(content_db),
            },
        },
    )

    literatures_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "title": "Demo Paper",
                "year": "2024",
                "pdf_path": str(pdf_path),
                "primary_attachment_name": pdf_path.name,
            }
        ]
    )
    attachments_df = pd.DataFrame(
        [
            {
                "uid_attachment": "att-001",
                "uid_literature": "lit-001",
                "attachment_name": pdf_path.name,
                "attachment_type": "fulltext",
                "file_ext": "pdf",
                "storage_path": str(pdf_path),
                "source_path": str(pdf_path),
                "is_primary": 1,
                "status": "available",
            }
        ]
    )
    persist_reference_tables(literatures_df=literatures_df, attachments_df=attachments_df, db_path=content_db)
    return workspace_root, content_db, pdf_path


def _fake_parse_result(output_root: Path, output_name: str) -> dict:
    output_dir = output_root / output_name
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "reconstructed_content.md"
    markdown_path.write_text("Demo full text.", encoding="utf-8")
    linear_index_path = output_dir / "linear_index.json"
    linear_index_path.write_text(json.dumps({"paragraphs": [{"index": 1, "text": "Demo full text."}]}, ensure_ascii=False), encoding="utf-8")
    parse_record_path = output_dir / "parse_record.json"
    parse_record_path.write_text(
        json.dumps(
            {
                "schema": "aok.pdf_monkeyocr_parse_record.v1",
                "llm_model": "MonkeyOCR-pro-1.2B",
                "llm_backend": "monkeyocr_windows",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    quality_report_path = output_dir / "quality_report.json"
    quality_report_path.write_text(json.dumps({"status": "SUCCEEDED"}, ensure_ascii=False), encoding="utf-8")
    return {
        "output_name": output_name,
        "output_dir": str(output_dir),
        "reconstructed_markdown_path": str(markdown_path),
        "linear_index_path": str(linear_index_path),
        "chunk_manifest_path": "",
        "chunks_jsonl_path": "",
        "parse_record_path": str(parse_record_path),
        "quality_report_path": str(quality_report_path),
        "llm_model": "MonkeyOCR-pro-1.2B",
        "llm_backend": "monkeyocr_windows",
    }


def _write_runner_artifacts(output_dir: Path, manifest_df: pd.DataFrame) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "parse_manifest.csv"
    management_path = output_dir / "management_table.csv"
    batch_report_path = output_dir / "batch_report.json"
    handoff_path = output_dir / "handoff.json"
    manifest_df.to_csv(manifest_path, index=False, encoding="utf-8-sig")
    manifest_df.to_csv(management_path, index=False, encoding="utf-8-sig")
    batch_report_path.write_text(json.dumps({"total": len(manifest_df)}, ensure_ascii=False), encoding="utf-8")
    handoff_path.write_text(json.dumps({"success_count": len(manifest_df)}, ensure_ascii=False), encoding="utf-8")
    return {
        "manifest_path": manifest_path,
        "management_table_path": management_path,
        "batch_report_path": batch_report_path,
        "handoff_path": handoff_path,
    }


def test_run_parse_manifest_should_register_assets_without_gpu(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.tools.ocr.runtime.monkeyocr_manifest_runtime")
    workspace_root, content_db, _ = _prepare_workspace(tmp_path)
    output_dir = workspace_root / "tasks" / "202604110001-A080"
    output_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        module,
        "run_monkeyocr_single_pdf",
        lambda **kwargs: _fake_parse_result(Path(str(kwargs["output_dir"])), Path(str(kwargs["input_pdf"])).stem),
    )
    result = module.run_parse_manifest(
        content_db=content_db,
        source_df=pd.DataFrame([
            {"uid_literature": "lit-001", "cite_key": "demo-001", "priority_rank": 1}
        ]),
        output_dir=output_dir,
        source_stage="A080",
        upstream_stage="A070",
        downstream_stage="A090",
        parse_level="non_review_rough",
        literature_scope="non_review",
        runtime_settings={
            "monkeyocr_root": str((workspace_root / "fake-monkey").resolve()),
            "model_name": "MonkeyOCR-pro-1.2B",
            "device": "cuda",
            "gpu_visible_devices": "0",
            "runtime_root": str((workspace_root / "runtime" / "monkeyocr").resolve()),
            "lock_name": "monkeyocr_gpu",
            "acquire_gpu_lock": True,
        },
        postprocess_settings={"enabled": True},
        global_config_path=workspace_root / "config" / "config.json",
        overwrite_existing=False,
    )

    assert result["counts"]["succeeded"] == 1
    assert result["counts"]["failed"] == 0
    assert result["manifest_path"].exists()
    assert result["management_table_path"].exists()
    assert result["handoff_path"].exists()

    state = get_structured_state(content_db, "lit-001")
    assert state["structured_backend"] == "monkeyocr_windows"
    assert state["structured_task_type"] == "non_review_rough"


def test_run_parse_manifest_should_report_gpu_lock_conflict_without_running(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.tools.ocr.runtime.monkeyocr_manifest_runtime")
    workspace_root, content_db, _ = _prepare_workspace(tmp_path)
    output_dir = workspace_root / "tasks" / "202604110002-A100"
    output_dir.mkdir(parents=True, exist_ok=True)

    runtime_settings = {
        "monkeyocr_root": str((workspace_root / "fake-monkey").resolve()),
        "model_name": "MonkeyOCR-pro-1.2B",
        "device": "cuda",
        "gpu_visible_devices": "0",
        "runtime_root": str((workspace_root / "runtime" / "monkeyocr").resolve()),
        "lock_name": "monkeyocr_gpu",
        "acquire_gpu_lock": True,
    }
    lock_dir = Path(runtime_settings["runtime_root"]) / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "monkeyocr_gpu.lock").write_text("occupied", encoding="utf-8")

    called = {"parse": 0}
    monkeypatch.setattr(
        module,
        "run_monkeyocr_single_pdf",
        lambda **kwargs: called.__setitem__("parse", called["parse"] + 1) or _fake_parse_result(Path(str(kwargs["output_dir"])), Path(str(kwargs["input_pdf"])).stem),
    )

    result = module.run_parse_manifest(
        content_db=content_db,
        source_df=pd.DataFrame([
            {"uid_literature": "lit-001", "cite_key": "demo-001", "priority_rank": 1}
        ]),
        output_dir=output_dir,
        source_stage="A100",
        upstream_stage="A095",
        downstream_stage="A105",
        parse_level="non_review_deep",
        literature_scope="non_review",
        runtime_settings=runtime_settings,
        postprocess_settings={"enabled": False},
        global_config_path=workspace_root / "config" / "config.json",
        overwrite_existing=False,
    )

    assert called["parse"] == 0
    assert result["counts"]["failed"] == 1
    assert "GPU 锁已被占用" in result["lock_error"]


def test_a080_affair_should_consume_manifest_runner(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.非综述候选视图构建.affair")
    workspace_root, content_db, pdf_path = _prepare_workspace(tmp_path)
    output_dir = tmp_path / "outputs_a080"
    output_dir.mkdir(parents=True, exist_ok=True)

    upsert_reading_state_rows(
        content_db,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "pending_preprocess": 1,
                "preprocessed": 0,
                "pending_rough_read": 0,
                "rough_read_done": 0,
                "pending_deep_read": 0,
                "deep_read_done": 0,
                "deep_read_count": 0,
            }
        ],
    )

    manifest_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "title": "Demo Paper",
                "pdf_path": str(pdf_path),
                "source_stage": "A080",
                "recommended_reason": "test",
                "theme_relation": "demo",
                "source_origin": "auto",
                "reading_objective": "objective",
                "manual_guidance": "guidance",
                "manifest_status": "succeeded",
                "normalized_structured_path": str(workspace_root / "references" / "structured_monkeyocr_full" / "demo-001" / "normalized.structured.json"),
                "reconstructed_markdown_path": str(workspace_root / "references" / "structured_monkeyocr_full" / "demo-001" / "reconstructed_content.md"),
                "asset_dir": str(workspace_root / "references" / "structured_monkeyocr_full" / "demo-001"),
                "postprocess_ok": 1,
                "postprocess_llm_basic_cleanup_status": "ok",
                "postprocess_llm_structure_status": "ok",
                "postprocess_contamination_removed_block_count": 0,
                "failure_reason": "",
            }
        ]
    )
    def _fake_runner(**kwargs):
        artifacts = _write_runner_artifacts(Path(kwargs["output_dir"]), manifest_df)
        return {
            "manifest_df": manifest_df,
            **artifacts,
            "readable_manifest_path": artifacts["manifest_path"],
            "failures": [],
            "counts": {"total": 1, "succeeded": 1, "skipped": 0, "failed": 0},
            "lock_error": "",
        }

    monkeypatch.setattr(module, "run_parse_manifest", _fake_runner)

    config_path = tmp_path / "a080.json"
    _write_json(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "output_dir": str(output_dir),
        },
    )

    outputs = module.execute(config_path)
    assert any(path.name == "a080_preprocess_index.csv" for path in outputs)
    state_df = load_reading_state_df(content_db, flag_filters={"uid_literature": "lit-001"})
    row = state_df[state_df["uid_literature"].astype(str) == "lit-001"].iloc[0]
    assert int(row["pending_preprocess"]) == 0
    assert int(row["preprocessed"]) == 1
    assert int(row["pending_rough_read"]) == 1


def test_a100_affair_should_promote_parse_ready_without_gpu(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.文献研读与正式知识回写.affair")
    workspace_root, content_db, pdf_path = _prepare_workspace(tmp_path)
    output_dir = tmp_path / "outputs_a100"
    output_dir.mkdir(parents=True, exist_ok=True)

    upsert_reading_state_rows(
        content_db,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "pending_deep_read": 1,
                "deep_read_done": 0,
                "deep_read_count": 0,
            }
        ],
    )

    manifest_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "title": "Demo Paper",
                "pdf_path": str(pdf_path),
                "source_origin": "auto",
                "manifest_status": "succeeded",
                "normalized_structured_path": str(workspace_root / "references" / "structured_monkeyocr_full" / "demo-001" / "normalized.structured.json"),
                "reconstructed_markdown_path": str(workspace_root / "references" / "structured_monkeyocr_full" / "demo-001" / "reconstructed_content.md"),
                "asset_dir": str(workspace_root / "references" / "structured_monkeyocr_full" / "demo-001"),
                "postprocess_ok": 1,
                "postprocess_llm_basic_cleanup_status": "ok",
                "postprocess_llm_structure_status": "ok",
                "postprocess_contamination_removed_block_count": 0,
                "failure_reason": "",
            }
        ]
    )
    def _fake_runner(**kwargs):
        artifacts = _write_runner_artifacts(Path(kwargs["output_dir"]), manifest_df)
        return {
            "manifest_df": manifest_df,
            **artifacts,
            "readable_manifest_path": artifacts["manifest_path"],
            "failures": [],
            "counts": {"total": 1, "succeeded": 1, "skipped": 0, "failed": 0},
            "lock_error": "",
        }

    monkeypatch.setattr(module, "run_parse_manifest", _fake_runner)

    config_path = tmp_path / "a100.json"
    _write_json(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "output_dir": str(output_dir),
            "translation_policy": {"enabled": False},
        },
    )

    outputs = module.execute(config_path)
    assert any(path.name == "a100_deep_parse_index.csv" for path in outputs)
    state_df = load_reading_state_df(content_db)
    row = state_df[state_df["uid_literature"].astype(str) == "lit-001"].iloc[0]
    assert int(row["pending_deep_read"]) == 0
    assert int(row["in_deep_read"]) == 0
    assert row["deep_read_decision"] == "parse_ready"


def test_a060_affair_should_enqueue_a065_from_manifest_runner(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.综述预处理.affair")
    workspace_root, content_db, pdf_path = _prepare_workspace(tmp_path)
    output_dir = tmp_path / "outputs_a060"
    output_dir.mkdir(parents=True, exist_ok=True)

    upsert_review_state_rows(
        content_db,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "pending_review_parse": 1,
                "review_parse_ready": 0,
                "pending_reference_preprocess": 0,
            }
        ],
    )

    manifest_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "title": "Demo Paper",
                "pdf_path": str(pdf_path),
                "manifest_status": "succeeded",
                "normalized_structured_path": str(workspace_root / "references" / "structured_monkeyocr_full" / "demo-001" / "normalized.structured.json"),
                "reconstructed_markdown_path": str(workspace_root / "references" / "structured_monkeyocr_full" / "demo-001" / "reconstructed_content.md"),
                "asset_dir": str(workspace_root / "references" / "structured_monkeyocr_full" / "demo-001"),
                "postprocess_ok": 1,
                "postprocess_llm_basic_cleanup_status": "ok",
                "postprocess_llm_structure_status": "ok",
                "postprocess_contamination_removed_block_count": 0,
                "failure_reason": "",
            }
        ]
    )
    def _fake_runner(**kwargs):
        artifacts = _write_runner_artifacts(Path(kwargs["output_dir"]), manifest_df)
        return {
            "manifest_df": manifest_df,
            **artifacts,
            "readable_manifest_path": artifacts["manifest_path"],
            "failures": [],
            "counts": {"total": 1, "succeeded": 1, "skipped": 0, "failed": 0},
            "lock_error": "",
        }

    monkeypatch.setattr(module, "run_parse_manifest", _fake_runner)

    config_path = tmp_path / "a060.json"
    _write_json(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "output_dir": str(output_dir),
            "topic": "Demo Topic",
        },
    )

    outputs = module.execute(config_path)
    assert any(path.name == "parse_asset_status.csv" for path in outputs)

    review_state_df = load_review_state_df(content_db)
    review_row = review_state_df[review_state_df["uid_literature"].astype(str) == "lit-001"].iloc[0]
    assert int(review_row["pending_review_parse"]) == 0
    assert int(review_row["review_parse_ready"]) == 1
    assert int(review_row["pending_reference_preprocess"]) == 1

    queue_df = load_reading_queue_df(content_db, stage="A065", only_current=True)
    assert not queue_df.empty
    assert "demo-001" in queue_df["cite_key"].astype(str).tolist()