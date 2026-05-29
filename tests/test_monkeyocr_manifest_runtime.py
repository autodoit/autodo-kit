"""MonkeyOCR 清单驱动运行时与事务接入测试。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
import sqlite3
import types

import pandas as pd
import pytest

from autodokit.tools.bibliodb_sqlite import (
    init_db,
    get_structured_state,
    load_flow_state_df,
    load_reading_queue_df,
    load_reading_state_df,
    load_review_state_df,
    replace_reference_tables_only,
    upsert_flow_state_rows,
    upsert_reading_queue_rows,
    upsert_reading_state_rows,
    upsert_review_state_rows,
)
from autodokit.tools.contentdb_sqlite import (
    LITERATURE_TABLE_NAME,
    READING_QUEUE_TO_LITERATURE_COLUMN_MAP,
    resolve_content_physical_column,
)


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
    replace_reference_tables_only(db_path=content_db, literatures_df=literatures_df, attachments_df=attachments_df)
    return workspace_root, content_db, pdf_path


def test_init_db_should_backfill_parse_runtime_columns_for_legacy_tables(tmp_path: Path) -> None:
    content_db = tmp_path / "legacy_content.db"
    with sqlite3.connect(content_db) as conn:
        conn.executescript(
            '''
            CREATE TABLE "文献主表" (
                "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_literature TEXT,
                cite_key TEXT,
                "标题" TEXT
            );
            CREATE TABLE "附件表" (
                "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_attachment TEXT,
                "附件名称" TEXT,
                "存储路径" TEXT
            );
            INSERT INTO "文献主表" (uid_literature, cite_key, "标题") VALUES ('lit-001', 'demo-001', 'Demo');
            INSERT INTO "附件表" (uid_attachment, "附件名称", "存储路径") VALUES ('att-001', 'demo.pdf', 'demo.pdf');
            '''
        )

    init_db(content_db)

    with sqlite3.connect(content_db) as conn:
        literature_columns = {row[1] for row in conn.execute('PRAGMA table_info("文献主表")').fetchall()}
        attachment_columns = {row[1] for row in conn.execute('PRAGMA table_info("附件表")').fetchall()}

    assert "current_parse_asset_uid" in literature_columns
    assert "current_parse_status" in literature_columns
    assert "current_parse_path" in literature_columns
    assert "current_parse_asset_uid" in attachment_columns
    assert "current_parse_status" in attachment_columns
    assert "current_parse_path" in attachment_columns


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
        downstream_stage="A080",
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
        upstream_stage="A080",
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


def test_run_parse_manifest_should_cleanup_incomplete_asset_before_rerun(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.tools.ocr.runtime.monkeyocr_manifest_runtime")
    workspace_root, content_db, pdf_path = _prepare_workspace(tmp_path)
    output_dir = workspace_root / "tasks" / "202604110003-A055"
    output_dir.mkdir(parents=True, exist_ok=True)

    partial_dir = workspace_root / "references" / "structured_monkeyocr_full" / "lit-001"
    partial_dir.mkdir(parents=True, exist_ok=True)
    stale_file = partial_dir / "stale.tmp"
    stale_file.write_text("partial", encoding="utf-8")

    def _fake_runner(**kwargs):
        assert not stale_file.exists()
        return _fake_parse_result(Path(str(kwargs["output_dir"])), str(kwargs.get("output_name") or "lit-001"))

    monkeypatch.setattr(module, "run_monkeyocr_single_pdf", _fake_runner)

    result = module.run_parse_manifest(
        content_db=content_db,
        source_df=pd.DataFrame([
            {"uid_literature": "lit-001", "cite_key": "demo-001", "priority_rank": 1}
        ]),
        output_dir=output_dir,
        source_stage="A055",
        upstream_stage="A050",
        downstream_stage="A080",
        parse_level="non_review_rough",
        literature_scope="non_review",
        runtime_settings={
            "monkeyocr_root": str((workspace_root / "fake-monkey").resolve()),
            "model_name": "MonkeyOCR-pro-1.2B",
            "device": "cuda",
            "runtime_root": str((workspace_root / "runtime" / "monkeyocr").resolve()),
            "acquire_gpu_lock": False,
        },
        postprocess_settings={"enabled": True},
        global_config_path=workspace_root / "config" / "config.json",
        overwrite_existing=False,
    )

    assert result["counts"]["succeeded"] == 1
    assert not stale_file.exists()


def test_a080_affair_should_consume_manifest_runner(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.非综述候选视图构建.affair")
    workspace_root, content_db, pdf_path = _prepare_workspace(tmp_path)
    output_dir = tmp_path / "outputs_a080"
    output_dir.mkdir(parents=True, exist_ok=True)

    upsert_reading_queue_rows(
        content_db,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "stage": "A080",
                "queue_status": "queued",
                "priority": 80,
                "source_affair": "A075",
                "preferred_next_stage": "A100",
                "recommended_reason": "test",
                "theme_relation": "demo",
                "is_current": 1,
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


def test_a100_affair_should_promote_parse_ready_without_gpu(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.文献研读与正式知识回写.affair")
    workspace_root, content_db, pdf_path = _prepare_workspace(tmp_path)
    output_dir = tmp_path / "outputs_a100"
    output_dir.mkdir(parents=True, exist_ok=True)

    upsert_reading_queue_rows(
        content_db,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "stage": "A100",
                "queue_status": "queued",
                "priority": 80,
                "source_affair": "A080",
                "preferred_next_stage": "A105",
                "recommended_reason": "test",
                "theme_relation": "demo",
                "is_current": 1,
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


def test_a060_merged_followups_should_build_internal_phase_configs(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.候选文献视图构建.affair")
    workspace_root, content_db, _ = _prepare_workspace(tmp_path)
    output_dir = tmp_path / "outputs_a060"
    output_dir.mkdir(parents=True, exist_ok=True)

    captured_payloads: dict[str, dict] = {}

    def _fake_execute(module_path: str, config_path: Path) -> List[Path]:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
        captured_payloads[module_path] = payload
        marker_path = Path(config_path).with_suffix(".done")
        marker_path.write_text(module_path, encoding="utf-8")
        return [marker_path]

    monkeypatch.setattr(
        module,
        "import_module",
        lambda module_path: types.SimpleNamespace(
            execute=lambda config_path, module_path=module_path: _fake_execute(module_path, Path(config_path))
        ),
    )

    outputs = module._run_merged_followup_affairs(
        workspace_root=workspace_root,
        raw_cfg={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "research_topic": "Demo Topic",
            "merged_phase_configs": {
                "A065": {"api_key_file": "demo-key.txt"},
                "A070": {"review_state_max_chars": 12345},
                "A075": {
                    "human_seed_contract": {
                        "enabled": True,
                        "seed_items": [{"cite_key": "seed-001", "recommended_reason": "demo"}],
                    }
                },
            },
        },
        output_dir=output_dir,
    )

    merged_config_dir = output_dir / "merged_phase_configs"
    assert (merged_config_dir / "A065.json").exists()
    assert (merged_config_dir / "A070.json").exists()
    assert (merged_config_dir / "A075.json").exists()
    assert not (workspace_root / "config" / "affairs_config" / "A065.json").exists()
    assert captured_payloads["autodokit.affairs.候选文献视图构建.phase_a065"]["api_key_file"] == "demo-key.txt"
    assert captured_payloads["autodokit.affairs.候选文献视图构建.phase_a070"]["review_state_max_chars"] == 12345
    assert captured_payloads["autodokit.affairs.候选文献视图构建.phase_a075"]["human_seed_contract"]["seed_items"][0]["cite_key"] == "seed-001"
    assert any(path.name == "A065.json" for path in outputs)
    assert any(path.name == "A070.json" for path in outputs)
    assert any(path.name == "A075.json" for path in outputs)


def test_a070_review_reading_followups_should_allow_selected_nodes(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.候选文献视图构建.affair")
    workspace_root, content_db, _ = _prepare_workspace(tmp_path)
    output_dir = tmp_path / "outputs_a070"
    output_dir.mkdir(parents=True, exist_ok=True)

    captured_payloads: dict[str, dict] = {}

    def _fake_execute(module_path: str, config_path: Path) -> List[Path]:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
        captured_payloads[module_path] = payload
        marker_path = Path(config_path).with_suffix(".done")
        marker_path.write_text(module_path, encoding="utf-8")
        return [marker_path]

    monkeypatch.setattr(
        module,
        "import_module",
        lambda module_path: types.SimpleNamespace(
            execute=lambda config_path, module_path=module_path: _fake_execute(module_path, Path(config_path))
        ),
    )

    outputs = module._run_merged_followup_affairs(
        workspace_root=workspace_root,
        raw_cfg={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "research_topic": "Demo Topic",
            "merged_phase_configs": {
                "A065": {"downstream_stage": "A075"},
                "A070": {"review_state_max_chars": 12345},
                "A075": {"human_seed_contract": {"enabled": True}},
            },
        },
        output_dir=output_dir,
        selected_nodes=("A065", "A070"),
    )

    merged_config_dir = output_dir / "merged_phase_configs"
    assert (merged_config_dir / "A065.json").exists()
    assert (merged_config_dir / "A070.json").exists()
    assert not (merged_config_dir / "A075.json").exists()
    assert captured_payloads["autodokit.affairs.候选文献视图构建.phase_a065"]["downstream_stage"] == "A075"
    assert captured_payloads["autodokit.affairs.候选文献视图构建.phase_a070"]["review_state_max_chars"] == 12345
    assert "autodokit.affairs.候选文献视图构建.phase_a075" not in captured_payloads
    assert any(path.name == "A065.json" for path in outputs)
    assert any(path.name == "A070.json" for path in outputs)


def test_a050_affair_should_consume_flow_state_when_legacy_flags_missing(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    workspace_root, content_db, pdf_path = _prepare_workspace(tmp_path)
    output_dir = tmp_path / "outputs_a050"
    output_dir.mkdir(parents=True, exist_ok=True)

    upsert_flow_state_rows(
        content_db,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "文献角色": "普通候选文献",
                "流程轨道": "普通主链",
                "当前阶段": "普通文献预处理",
                "当前阶段组": "预处理",
                "当前状态": "待处理",
                "下一阶段": "普通文献泛读",
                "来源阶段": "A075",
                "来源类型": "review_export",
                "推荐原因": "flow seeded",
                "主题关系": "demo-theme",
                "阅读目标": "demo objective",
                "人工提示": "demo guidance",
                "是否当前有效": 1,
                "是否可执行": 1,
                "stage_code": "non_review_preprocess",
                "node_code": "A050",
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
                "source_stage": "A050_NON_REVIEW",
                "recommended_reason": "flow seeded",
                "theme_relation": "demo-theme",
                "source_origin": "review_export",
                "reading_objective": "demo objective",
                "manual_guidance": "demo guidance",
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

    config_path = tmp_path / "a050.json"
    _write_json(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "output_dir": str(output_dir),
            "profile": "non_review",
        },
    )

    outputs = module.execute(config_path)
    assert any(path.name == "a050_unified_preprocess_index.csv" for path in outputs)

    queue_df = load_reading_queue_df(content_db, stage="A050_NON_REVIEW", only_current=False)
    assert not queue_df.empty
    assert "demo-001" in queue_df["cite_key"].astype(str).tolist()

    flow_df = load_flow_state_df(content_db, flag_filters={"uid_literature": "lit-001"})
    assert not flow_df.empty


def test_a050_priority_only_should_rank_full_library_and_write_main_table_summary(tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    workspace_root = (tmp_path / "workspace").resolve()
    content_db = workspace_root / "database" / "content" / "content.db"
    attachment_dir = workspace_root / "references" / "attachments"
    attachment_dir.mkdir(parents=True, exist_ok=True)

    review_pdf = attachment_dir / "review.pdf"
    non_review_pdf = attachment_dir / "non_review.pdf"
    review_pdf.write_bytes(b"%PDF-1.4\n%review\n")
    non_review_pdf.write_bytes(b"%PDF-1.4\n%non-review\n")

    literatures_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-review",
                "cite_key": "review-001",
                "title": "房地产价格波动对银行系统性风险影响研究综述",
                "year": "2024",
                "abstract": "聚焦房地产价格波动、银行系统性风险与银行间网络传染机制的综述。",
                "keywords": "房地产价格波动;银行系统性风险;银行间网络;综述",
                "entry_type": "article",
                "literature_type": "review",
                "pdf_path": str(review_pdf),
                "primary_attachment_name": review_pdf.name,
            },
            {
                "uid_literature": "lit-non-review",
                "cite_key": "paper-001",
                "title": "房地产下行压力、资产负债表重估与银行风险共振",
                "year": "2023",
                "abstract": "研究房地产冲击经资产负债表渠道和共同资产渠道影响银行系统性风险。",
                "keywords": "房地产下行压力;资产负债表;共同资产;银行系统性风险",
                "entry_type": "article",
                "literature_type": "non_review",
                "pdf_path": str(non_review_pdf),
                "primary_attachment_name": non_review_pdf.name,
            },
            {
                "uid_literature": "lit-background",
                "cite_key": "paper-999",
                "title": "制造业数字化转型与出口绩效",
                "year": "2021",
                "abstract": "与当前主题弱相关。",
                "keywords": "制造业;出口",
                "entry_type": "article",
                "literature_type": "non_review",
                "pdf_path": "",
                "primary_attachment_name": "",
            },
        ]
    )
    attachments_df = pd.DataFrame(
        [
            {
                "uid_attachment": "att-review",
                "uid_literature": "lit-review",
                "attachment_name": review_pdf.name,
                "attachment_type": "fulltext",
                "file_ext": "pdf",
                "storage_path": str(review_pdf),
                "source_path": str(review_pdf),
                "is_primary": 1,
                "status": "available",
            },
            {
                "uid_attachment": "att-non-review",
                "uid_literature": "lit-non-review",
                "attachment_name": non_review_pdf.name,
                "attachment_type": "fulltext",
                "file_ext": "pdf",
                "storage_path": str(non_review_pdf),
                "source_path": str(non_review_pdf),
                "is_primary": 1,
                "status": "available",
            },
        ]
    )
    replace_reference_tables_only(db_path=content_db, literatures_df=literatures_df, attachments_df=attachments_df)

    config_path = tmp_path / "a050_priority_only.json"
    _write_json(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "node_code": "A050",
            "execution_mode": "priority_only",
            "processing_settings": {
                "priority_policy": {
                    "topic_name": "房地产价格波动对银行系统性风险",
                    "concept_families": {
                        "real_estate": ["房地产价格波动", "房地产下行压力", "房地产冲击"],
                        "systemic_risk": ["银行系统性风险", "系统性风险"],
                        "mechanism": ["银行间网络", "资产负债表", "共同资产", "网络传染"],
                    },
                }
            },
        },
    )

    outputs = module.execute(config_path)
    assert any(path.name == "a050_preprocess_priority_index.csv" for path in outputs)

    review_queue = load_reading_queue_df(content_db, stage="A050_REVIEW", only_current=True)
    non_review_queue = load_reading_queue_df(content_db, stage="A050_NON_REVIEW", only_current=True)
    combined = pd.concat([review_queue, non_review_queue], ignore_index=True, sort=False)
    assert len(combined) == 3

    combined = combined.sort_values(by=["priority"], ascending=[True]).reset_index(drop=True)
    assert combined.iloc[0]["cite_key"] == "review-001"
    assert combined.iloc[0]["queue_status"] == "queued"
    assert combined.iloc[1]["cite_key"] == "paper-001"
    assert combined.iloc[1]["queue_status"] == "queued"

    blocked_row = combined.loc[combined["cite_key"].astype(str) == "paper-999"].iloc[0]
    assert blocked_row["queue_status"] == "blocked"

    with sqlite3.connect(content_db) as conn:
        cite_key_column = resolve_content_physical_column(LITERATURE_TABLE_NAME, "cite_key")
        priority_column = READING_QUEUE_TO_LITERATURE_COLUMN_MAP["priority"]
        queue_status_column = READING_QUEUE_TO_LITERATURE_COLUMN_MAP["queue_status"]
        rows = conn.execute(
            f'SELECT "{cite_key_column}", "{priority_column}", "{queue_status_column}" FROM "{LITERATURE_TABLE_NAME}" ORDER BY "{priority_column}" ASC'
        ).fetchall()
    assert rows[0][0] == "review-001"
    assert rows[1][0] == "paper-001"
    assert rows[2][0] == "paper-999"


def test_a055_should_consume_queue_in_ascending_priority_order(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    workspace_root, content_db, pdf_path = _prepare_workspace(tmp_path)

    second_pdf = workspace_root / "references" / "attachments" / "demo-2.pdf"
    second_pdf.parent.mkdir(parents=True, exist_ok=True)
    second_pdf.write_bytes(b"%PDF-1.4\n%demo-2\n")

    replace_reference_tables_only(
        db_path=content_db,
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-001",
                    "cite_key": "demo-001",
                    "title": "Demo Paper 1",
                    "year": "2024",
                    "pdf_path": str(pdf_path),
                    "primary_attachment_name": pdf_path.name,
                },
                {
                    "uid_literature": "lit-002",
                    "cite_key": "demo-002",
                    "title": "Demo Paper 2",
                    "year": "2023",
                    "pdf_path": str(second_pdf),
                    "primary_attachment_name": second_pdf.name,
                },
            ]
        ),
        attachments_df=pd.DataFrame(
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
                },
                {
                    "uid_attachment": "att-002",
                    "uid_literature": "lit-002",
                    "attachment_name": second_pdf.name,
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": str(second_pdf),
                    "source_path": str(second_pdf),
                    "is_primary": 1,
                    "status": "available",
                },
            ]
        ),
    )

    upsert_reading_queue_rows(
        content_db,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "stage": "A050_NON_REVIEW",
                "queue_status": "queued",
                "priority": 9,
                "source_affair": "A050",
                "preferred_next_stage": "A080",
                "recommended_reason": "later",
                "theme_relation": "demo",
                "is_current": 1,
            },
            {
                "uid_literature": "lit-002",
                "cite_key": "demo-002",
                "stage": "A050_NON_REVIEW",
                "queue_status": "queued",
                "priority": 2,
                "source_affair": "A050",
                "preferred_next_stage": "A080",
                "recommended_reason": "earlier",
                "theme_relation": "demo",
                "is_current": 1,
            },
        ],
    )

    captured_order: list[str] = []
    monkeypatch.setattr(module, "_takeover_previous_a055_run", lambda **kwargs: [])

    def _fake_runner(**kwargs):
        source_df = kwargs["source_df"].copy().reset_index(drop=True)
        captured_order.extend(source_df["cite_key"].astype(str).tolist())
        manifest_df = pd.DataFrame(
            [
                {
                    "uid_literature": row["uid_literature"],
                    "cite_key": row["cite_key"],
                    "title": row.get("title", ""),
                    "pdf_path": row.get("pdf_path", ""),
                    "source_stage": "A050_NON_REVIEW",
                    "recommended_reason": row.get("recommended_reason", ""),
                    "theme_relation": row.get("theme_relation", ""),
                    "source_origin": "auto",
                    "reading_objective": "",
                    "manual_guidance": "",
                    "manifest_status": "succeeded",
                    "normalized_structured_path": str(workspace_root / "references" / "structured_monkeyocr_full" / row["uid_literature"] / "normalized_structured.json"),
                    "reconstructed_markdown_path": str(workspace_root / "references" / "structured_monkeyocr_full" / row["uid_literature"] / "reconstructed_content.md"),
                    "asset_dir": str(workspace_root / "references" / "structured_monkeyocr_full" / row["uid_literature"]),
                    "postprocess_ok": 1,
                    "postprocess_llm_basic_cleanup_status": "ok",
                    "postprocess_llm_structure_status": "ok",
                    "postprocess_contamination_removed_block_count": 0,
                    "failure_reason": "",
                }
                for _, row in source_df.iterrows()
            ]
        )
        for _, row in source_df.iterrows():
            asset_dir = workspace_root / "references" / "structured_monkeyocr_full" / row["uid_literature"]
            _ensure_complete_asset(asset_dir)
        artifacts = _write_runner_artifacts(Path(kwargs["output_dir"]), manifest_df)
        return {
            "manifest_df": manifest_df,
            **artifacts,
            "readable_manifest_path": artifacts["manifest_path"],
            "failures": [],
            "counts": {"total": len(manifest_df), "succeeded": len(manifest_df), "skipped": 0, "failed": 0},
            "lock_error": "",
        }

    monkeypatch.setattr(module, "run_parse_manifest", _fake_runner)

    config_path = tmp_path / "a055_priority_order.json"
    _write_json(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "node_code": "A055",
            "execution_mode": "full_preprocess",
            "profile": "non_review",
            "run_mode": "local_only",
        },
    )

    module.execute(config_path)
    assert captured_order == ["demo-002", "demo-001"]


def test_a055_mixed_should_start_from_global_min_priority_batch(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    workspace_root, content_db, pdf_path = _prepare_workspace(tmp_path)

    review_pdf = workspace_root / "references" / "attachments" / "review.pdf"
    review_pdf.parent.mkdir(parents=True, exist_ok=True)
    review_pdf.write_bytes(b"%PDF-1.4\n%review\n")

    replace_reference_tables_only(
        db_path=content_db,
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-001",
                    "cite_key": "demo-001",
                    "title": "Review Paper",
                    "year": "2024",
                    "literature_type": "review",
                    "pdf_path": str(review_pdf),
                    "primary_attachment_name": review_pdf.name,
                },
                {
                    "uid_literature": "lit-002",
                    "cite_key": "demo-002",
                    "title": "Non Review Paper",
                    "year": "2024",
                    "literature_type": "non_review",
                    "pdf_path": str(pdf_path),
                    "primary_attachment_name": pdf_path.name,
                },
            ]
        ),
        attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "att-001",
                    "uid_literature": "lit-001",
                    "attachment_name": review_pdf.name,
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": str(review_pdf),
                    "source_path": str(review_pdf),
                    "is_primary": 1,
                    "status": "available",
                },
                {
                    "uid_attachment": "att-002",
                    "uid_literature": "lit-002",
                    "attachment_name": pdf_path.name,
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": str(pdf_path),
                    "source_path": str(pdf_path),
                    "is_primary": 1,
                    "status": "available",
                },
            ]
        ),
    )

    upsert_reading_queue_rows(
        content_db,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "stage": "A050_REVIEW",
                "queue_status": "queued",
                "priority": 8,
                "source_affair": "A050",
                "preferred_next_stage": "A060",
                "recommended_reason": "review later",
                "theme_relation": "demo",
                "is_current": 1,
            },
            {
                "uid_literature": "lit-002",
                "cite_key": "demo-002",
                "stage": "A050_NON_REVIEW",
                "queue_status": "queued",
                "priority": 1,
                "source_affair": "A050",
                "preferred_next_stage": "A080",
                "recommended_reason": "non-review first",
                "theme_relation": "demo",
                "is_current": 1,
            },
        ],
    )

    batch_profiles: list[str] = []
    batch_orders: list[list[str]] = []
    monkeypatch.setattr(module, "_takeover_previous_a055_run", lambda **kwargs: [])

    def _fake_runner(**kwargs):
        source_df = kwargs["source_df"].copy().reset_index(drop=True)
        profile = kwargs.get("literature_scope") or kwargs.get("profile") or ""
        batch_profiles.append(str(profile))
        batch_orders.append(source_df["cite_key"].astype(str).tolist())
        manifest_df = pd.DataFrame(
            [
                {
                    "uid_literature": row["uid_literature"],
                    "cite_key": row["cite_key"],
                    "title": row.get("title", ""),
                    "pdf_path": row.get("pdf_path", ""),
                    "source_stage": row.get("stage", ""),
                    "recommended_reason": row.get("recommended_reason", ""),
                    "theme_relation": row.get("theme_relation", ""),
                    "source_origin": "auto",
                    "reading_objective": "",
                    "manual_guidance": "",
                    "manifest_status": "succeeded",
                    "normalized_structured_path": str(workspace_root / "references" / "structured_monkeyocr_full" / row["uid_literature"] / "normalized_structured.json"),
                    "reconstructed_markdown_path": str(workspace_root / "references" / "structured_monkeyocr_full" / row["uid_literature"] / "reconstructed_content.md"),
                    "asset_dir": str(workspace_root / "references" / "structured_monkeyocr_full" / row["uid_literature"]),
                    "postprocess_ok": 1,
                    "postprocess_llm_basic_cleanup_status": "ok",
                    "postprocess_llm_structure_status": "ok",
                    "postprocess_contamination_removed_block_count": 0,
                    "failure_reason": "",
                }
                for _, row in source_df.iterrows()
            ]
        )
        for _, row in source_df.iterrows():
            _ensure_complete_asset(workspace_root / "references" / "structured_monkeyocr_full" / row["uid_literature"])
        artifacts = _write_runner_artifacts(Path(kwargs["output_dir"]), manifest_df)
        return {
            "manifest_df": manifest_df,
            **artifacts,
            "readable_manifest_path": artifacts["manifest_path"],
            "failures": [],
            "counts": {"total": len(manifest_df), "succeeded": len(manifest_df), "skipped": 0, "failed": 0},
            "lock_error": "",
        }

    monkeypatch.setattr(module, "run_parse_manifest", _fake_runner)

    config_path = tmp_path / "a055_mixed_priority_order.json"
    _write_json(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "node_code": "A055",
            "execution_mode": "full_preprocess",
            "profile": "mixed",
            "run_mode": "local_only",
        },
    )

    module.execute(config_path)
    assert batch_profiles[0] == "non_review"
    assert batch_orders[0] == ["demo-002"]

def test_a055_takeover_should_stop_previous_local_and_remote(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    workspace_root = (tmp_path / "workspace").resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    guard_path = module._runtime_guard_path(workspace_root)
    guard_path.write_text(json.dumps({"pid": 4242, "task_uid": "old-run"}, ensure_ascii=False), encoding="utf-8")

    alive_pids = {4242}
    monkeypatch.setattr(module, "_is_pid_alive", lambda pid: pid in alive_pids)
    killed: list[int] = []
    monkeypatch.setattr(module, "_terminate_local_process", lambda pid: killed.append(pid) or alive_pids.discard(pid) is None or True)
    monkeypatch.setattr(module, "stop_remote_monkeyocr_jobs", lambda runtime: {"enabled": True, "killed": True})

    actions = module._takeover_previous_a055_run(
        workspace_root=workspace_root,
        parse_runtime={"remote_processing": {"enabled": True, "mode": "ssh"}},
        task_uid="new-run",
    )

    assert killed == [4242]
    assert "local_killed:4242" in actions
    assert "remote_stopped" in actions


def test_a055_takeover_should_refuse_parallel_start_when_previous_process_cannot_exit(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    workspace_root = (tmp_path / "workspace").resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    guard_path = module._runtime_guard_path(workspace_root)
    guard_path.write_text(json.dumps({"pid": 9898, "task_uid": "old-run"}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(module, "_is_pid_alive", lambda pid: pid == 9898)
    monkeypatch.setattr(module, "_terminate_local_process", lambda pid: False)

    with pytest.raises(RuntimeError, match="旧实例仍在运行"):
        module._takeover_previous_a055_run(
            workspace_root=workspace_root,
            parse_runtime={"remote_processing": {"enabled": True, "mode": "ssh"}},
            task_uid="new-run",
        )


def _ensure_complete_asset(asset_dir: Path) -> None:
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "normalized_structured.json").write_text("{}", encoding="utf-8")
    (asset_dir / "reconstructed_content.md").write_text("demo", encoding="utf-8")
    (asset_dir / "parse_record.json").write_text("{}", encoding="utf-8")
    (asset_dir / "quality_report.json").write_text("{}", encoding="utf-8")


def test_a055_remote_only_tmux_should_dispatch_without_local_parse(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    workspace_root, content_db, _ = _prepare_workspace(tmp_path)

    monkeypatch.setattr(module, "_takeover_previous_a055_run", lambda **kwargs: [])
    monkeypatch.setattr(module, "run_parse_manifest", lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not run local parse")))

    launch_calls: list[dict] = []

    def _fake_launch(runtime_settings, **kwargs):
        launch_calls.append({"runtime_settings": runtime_settings, **kwargs})
        return {"enabled": True, "mode": "ssh", "session_name": "a055_remote_0001", "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(module, "launch_remote_tmux_command", _fake_launch)

    config_path = tmp_path / "a055_remote_only.json"
    _write_json(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "node_code": "A055",
            "execution_mode": "full_preprocess",
            "run_mode": "remote_only_tmux",
            "remote_only": {
                "remote_command": "echo remote-only-a055",
                "tmux_session_prefix": "a055",
            },
            "pdf_parse_runtime": {
                "remote_processing": {
                    "enabled": True,
                    "mode": "ssh",
                    "ssh": {"host": "dummy", "user": "dummy"},
                }
            },
        },
    )

    outputs = module.execute(config_path)
    assert launch_calls
    assert any(path.name == "a055_remote_dispatch.json" for path in outputs)
    dispatch_path = next(path for path in outputs if path.name == "a055_remote_dispatch.json")
    dispatch_payload = json.loads(dispatch_path.read_text(encoding="utf-8"))
    assert dispatch_payload["run_mode"] == "remote_only_tmux"
    assert dispatch_payload["session_name"] == "a055_remote_0001"


def test_a055_local_only_should_return_gate_when_queue_empty(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    workspace_root, content_db, _ = _prepare_workspace(tmp_path)

    monkeypatch.setattr(module, "_takeover_previous_a055_run", lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not takeover previous run")))
    monkeypatch.setattr(module, "run_parse_manifest", lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not run local parse")))

    config_path = tmp_path / "a055_local_only_empty.json"
    _write_json(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "node_code": "A055",
            "execution_mode": "full_preprocess",
            "run_mode": "local_only",
        },
    )

    outputs = module.execute(config_path)

    assert len(outputs) == 1
    gate_path = outputs[0]
    gate_payload = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate_path.name == "gate_review.json"
    assert gate_payload["recommendation"] == "retry_current"
    assert "未找到可执行条目" in gate_payload["summary"]


def test_a055_record_parse_results_should_sync_from_done_marker(tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    workspace_root, content_db, _ = _prepare_workspace(tmp_path)

    upsert_reading_queue_rows(
        content_db,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "stage": "A050_NON_REVIEW",
                "queue_status": "queued",
                "priority": 80,
                "source_affair": "A050",
                "preferred_next_stage": "A080",
                "recommended_reason": "test",
                "theme_relation": "demo",
                "is_current": 1,
            }
        ],
    )

    asset_dir = workspace_root / "references" / "structured_monkeyocr_full" / "lit-001"
    _ensure_complete_asset(asset_dir)
    marker_name = "a055_parse_done.done.txt"
    (asset_dir / marker_name).touch(exist_ok=True)

    config_path = tmp_path / "a055_record.json"
    _write_json(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "node_code": "A055",
            "execution_mode": "full_preprocess",
            "run_mode": "record_parse_results",
            "parse_done_marker_name": marker_name,
            "pdf_parse_runtime": {
                "remote_processing": {
                    "enabled": False,
                }
            },
        },
    )

    outputs = module.execute(config_path)
    assert any(path.name == "a055_record_parse_results_index.csv" for path in outputs)

    queue_df = load_reading_queue_df(content_db, stage="A050_NON_REVIEW", only_current=True)
    assert queue_df.empty

    a080_queue = load_reading_queue_df(content_db, stage="A080", only_current=True)
    assert not a080_queue.empty

    with sqlite3.connect(content_db) as conn:
        uid_column = resolve_content_physical_column(LITERATURE_TABLE_NAME, "uid_literature")
        row = conn.execute(
            f'SELECT "预处理执行状态", "预处理结果路径", "解析状态", "当前解析状态", "当前解析路径", "结构化状态", "结构化正文路径" FROM "文献主表" WHERE "{uid_column}" = ?',
            ("lit-001",),
        ).fetchone()

    assert row is not None
    assert row[0] == "已处理"
    assert row[1] == str(asset_dir)
    assert row[2] == "已完成"
    assert row[3] == "ready"
    assert row[4] != ""
    assert row[5] == "ready"
    assert row[6] != ""


def test_a055_record_parse_results_should_resolve_attachment_stem_without_marker(tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    workspace_root, _, pdf_path = _prepare_workspace(tmp_path)

    asset_dir = workspace_root / "references" / "structured_monkeyocr_full" / pdf_path.stem
    _ensure_complete_asset(asset_dir)

    source_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "primary_attachment_name": pdf_path.name,
                "pdf_path": str(pdf_path),
            }
        ]
    )

    ready_df = module._collect_record_ready_rows(
        source_df,
        workspace_root=workspace_root,
        marker_name="a055_parse_done.done.txt",
    )

    assert len(ready_df) == 1
    assert ready_df.iloc[0]["asset_dir"] == str(asset_dir)
    assert ready_df.iloc[0]["done_marker_path"] == ""


def test_a055_should_pick_latest_timestamp_done_marker(tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    asset_dir = tmp_path / "lit-001"
    asset_dir.mkdir(parents=True, exist_ok=True)
    older = asset_dir / "done_20260528010101.txt"
    newer = asset_dir / "done_20260529020202.txt"
    older.write_text("", encoding="utf-8")
    newer.write_text("", encoding="utf-8")

    resolved = module._find_a055_done_marker(asset_dir, marker_name=module.A055_DONE_MARKER_DEFAULT)

    assert resolved == newer


def test_a055_local_only_should_disable_remote_and_write_done_marker(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("autodokit.affairs.统一文献预处理解析.affair")
    workspace_root, content_db, pdf_path = _prepare_workspace(tmp_path)
    output_dir = tmp_path / "outputs_a055"
    output_dir.mkdir(parents=True, exist_ok=True)

    upsert_reading_queue_rows(
        content_db,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "stage": "A050_NON_REVIEW",
                "queue_status": "queued",
                "priority": 80,
                "source_affair": "A050",
                "preferred_next_stage": "A080",
                "recommended_reason": "test",
                "theme_relation": "demo",
                "is_current": 1,
            }
        ],
    )

    asset_dir = workspace_root / "references" / "structured_monkeyocr_full" / "lit-001"
    _ensure_complete_asset(asset_dir)

    manifest_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "title": "Demo Paper",
                "pdf_path": str(pdf_path),
                "source_stage": "A050_NON_REVIEW",
                "recommended_reason": "test",
                "theme_relation": "demo",
                "source_origin": "auto",
                "reading_objective": "objective",
                "manual_guidance": "guidance",
                "manifest_status": "succeeded",
                "normalized_structured_path": str(asset_dir / "normalized_structured.json"),
                "reconstructed_markdown_path": str(asset_dir / "reconstructed_content.md"),
                "asset_dir": str(asset_dir),
                "postprocess_ok": 1,
                "postprocess_llm_basic_cleanup_status": "ok",
                "postprocess_llm_structure_status": "ok",
                "postprocess_contamination_removed_block_count": 0,
                "failure_reason": "",
            }
        ]
    )

    runtime_captured: dict = {}
    monkeypatch.setattr(module, "_takeover_previous_a055_run", lambda **kwargs: [])

    def _fake_runner(**kwargs):
        runtime_captured["runtime"] = kwargs.get("runtime_settings")
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

    config_path = tmp_path / "a055_local_only.json"
    _write_json(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "output_dir": str(output_dir),
            "node_code": "A055",
            "execution_mode": "full_preprocess",
            "profile": "non_review",
            "run_mode": "local_only",
            "pdf_parse_runtime": {
                "remote_processing": {
                    "enabled": True,
                    "mode": "ssh",
                    "ssh": {"host": "dummy", "user": "dummy"},
                }
            },
        },
    )

    outputs = module.execute(config_path)
    assert any(path.name == "a055_unified_preprocess_index.csv" for path in outputs)
    assert isinstance(runtime_captured.get("runtime"), dict)
    assert not bool((runtime_captured["runtime"].get("remote_processing") or {}).get("enabled"))
    done_markers = sorted(asset_dir.glob("done_*.txt"))
    assert len(done_markers) == 1
    marker_name = done_markers[0].name
    assert marker_name.startswith("done_") and marker_name.endswith(".txt")
    marker_stamp = marker_name[len("done_"):-len(".txt")]
    assert re.fullmatch(r"\d{14}", marker_stamp)
    marker_text = done_markers[0].read_text(encoding="utf-8").strip()
    assert marker_text == marker_stamp