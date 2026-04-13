"""通用流程事务最小样例测试。"""

from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

import pandas as pd

from autodokit.tools.bibliodb_sqlite import load_chunk_sets_df, load_chunks_df, load_reading_queue_df, upsert_reading_queue_rows
from autodokit.tools.ocr.classic.pdf_structured_data_tools import build_structured_data_payload
from autodokit.tools.storage_backend import persist_reference_main_table, persist_reference_tables


def _write_json_config(config_path: Path, payload: dict) -> None:
    """写入测试事务配置文件。

    Args:
        config_path: 配置文件路径。
        payload: 配置内容。

    Returns:
        None
    """

    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_placeholder_note(note_path: Path, title: str) -> None:
    """写入最小占位笔记，供事务回填使用。"""

    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                f'title: "{title}"',
                "updated: \"\"",
                "---",
                "",
                f"# {title}",
                "",
                "## 核心问题",
                "- 待补充",
                "",
                "## 方法与证据",
                "- 待补充",
                "",
                "## 核心发现",
                "- 待补充",
                "",
                "## 未来方向",
                "- 待补充",
                "",
                "## 共识与争议",
                "- 待补充",
                "",
                "## 参考文献列表",
                "- 待补充",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_structured_json(path: Path, *, uid_literature: str, cite_key: str, text: str) -> Path:
    """写入最小 structured.json 测试样例。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_structured_data_payload(
        pdf_path=(path.parent / f"{cite_key}.pdf").resolve(),
        backend="local_pipeline_v2",
        backend_family="local",
        task_type="full_fine_grained",
        full_text=text,
        extract_error=None,
        text_meta={"backend": "pypdf"},
        uid_literature=uid_literature,
        cite_key=cite_key,
        title=cite_key,
        year="2024",
        references=[{"raw_text": "Li. 2022. Original Study One."}],
        capabilities={"text": {"enabled": True, "disabled_reason": None}},
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _prepare_review_synthesis_workspace(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    """准备 A06 事务所需的最小工作区资产。"""

    workspace_root = tmp_path / "workspace"
    references_db = workspace_root / "database" / "references" / "references.db"
    knowledge_db = workspace_root / "database" / "knowledge" / "knowledge.db"
    output_dir = tmp_path / "outputs"
    review_read_pool_csv = workspace_root / "views" / "review_candidates" / "review_read_pool.csv"
    dummy_pdf = workspace_root / "references" / "attachments" / "review-001.pdf"

    (workspace_root / "config").mkdir(parents=True, exist_ok=True)
    (workspace_root / "knowledge" / "review_summaries").mkdir(parents=True, exist_ok=True)
    (workspace_root / "knowledge" / "trajectories").mkdir(parents=True, exist_ok=True)
    (workspace_root / "knowledge" / "frameworks").mkdir(parents=True, exist_ok=True)
    (workspace_root / "knowledge" / "audits").mkdir(parents=True, exist_ok=True)
    (workspace_root / "knowledge" / "standard_notes").mkdir(parents=True, exist_ok=True)
    (workspace_root / "batches" / "review_candidates").mkdir(parents=True, exist_ok=True)
    review_read_pool_csv.parent.mkdir(parents=True, exist_ok=True)
    dummy_pdf.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    dummy_pdf.write_bytes(b"%PDF-1.4\n%placeholder\n")

    (workspace_root / "config" / "config.json").write_text(
        json.dumps(
            {
                "workspace_root": str(workspace_root),
                "paths": {"log_db_path": str(workspace_root / "database" / "logs" / "aok_log.db")},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    literature_table = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "review-001",
                "title": "Topic Document",
                "first_author": "Wang",
                "year": "2024",
                "entry_type": "journal",
                "abstract": "A structured summary of the target topic.",
                "keywords": "summary; topic",
                "pdf_path": str(dummy_pdf),
                "primary_attachment_name": dummy_pdf.name,
            },
            {
                "uid_literature": "lit-002",
                "cite_key": "origin-001",
                "title": "Original Document One",
                "first_author": "Li",
                "year": "2022",
                "entry_type": "journal",
                "abstract": "An original document used for back-reference generation.",
                "keywords": "topic; evidence",
                "pdf_path": "",
                "primary_attachment_name": "",
            },
        ]
    )
    attachment_table = pd.DataFrame(
        [
            {
                "uid_attachment": "att-001",
                "uid_literature": "lit-001",
                "attachment_name": dummy_pdf.name,
                "attachment_type": "fulltext",
                "file_ext": "pdf",
                "storage_path": str(dummy_pdf),
                "source_path": str(dummy_pdf),
                "checksum": "",
                "is_primary": 1,
                "status": "available",
                "created_at": "",
                "updated_at": "",
            }
        ]
    )
    persist_reference_tables(
        literatures_df=literature_table,
        attachments_df=attachment_table,
        db_path=references_db,
    )

    pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "review-001",
                "title": "Topic Document",
                "year": "2024",
            }
        ]
    ).to_csv(review_read_pool_csv, index=False, encoding="utf-8-sig")

    pd.DataFrame(
        [
            {
                "batch_id": "batch-001",
                "uid_literature": "lit-001",
                "cite_key": "doc-001",
                "status": "pending",
            }
        ]
    ).to_csv(
        workspace_root / "batches" / "review_candidates" / "review_reading_batches.csv",
        index=False,
        encoding="utf-8-sig",
    )

    for relative_path in [
        Path("knowledge/review_summaries/核心成果.md"),
        Path("knowledge/review_summaries/共识点.md"),
        Path("knowledge/review_summaries/争议点.md"),
        Path("knowledge/review_summaries/未来方向.md"),
        Path("knowledge/trajectories/领域研究脉络.md"),
        Path("knowledge/frameworks/领域知识框架.md"),
        Path("knowledge/innovation_pool/创新点补写.md"),
        Path("knowledge/matrices/综述矩阵.md"),
    ]:
        _write_placeholder_note(workspace_root / relative_path, relative_path.stem)

    _write_placeholder_note(
        workspace_root / "knowledge" / "standard_notes" / "review-001.md",
        "review-001",
    )

    for csv_name in [
        "consensus_list.csv",
        "controversy_list.csv",
        "future_directions.csv",
        "must_read_originals.csv",
        "review_general_reading_list.csv",
        "reference_citation_mapping.csv",
    ]:
        (workspace_root / "knowledge" / "audits" / csv_name).write_text("", encoding="utf-8")
    (workspace_root / "knowledge" / "audits" / "引文识别原文.txt").write_text("", encoding="utf-8")
    (workspace_root / "knowledge" / "audits" / "reference_citation_quality_summary.json").write_text("{}", encoding="utf-8")

    return workspace_root, references_db, knowledge_db, review_read_pool_csv, output_dir


def test_candidate_view_affair_execute_should_work(tmp_path: Path) -> None:
    """候选文献视图构建事务应输出 4 个视图文件与 1 个闸门文件。"""

    module = importlib.import_module("autodokit.affairs.候选文献视图构建.affair")
    references_db = tmp_path / "references.db"
    literature_table = pd.DataFrame(
        [
            {"uid_literature": "lit-001", "title": "Topic Review", "keywords": "review", "abstract": "survey", "first_author": "Wang", "year": "2024", "entry_type": "journal", "source": "CNKI"},
            {"uid_literature": "lit-002", "title": "Process Innovation", "keywords": "innovation", "abstract": "empirical", "first_author": "Li", "year": "2023", "entry_type": "journal", "source": "CNKI"},
        ]
    )
    persist_reference_main_table(literature_table, references_db)

    config_path = tmp_path / "candidate_config.json"
    _write_json_config(
        config_path,
        {
            "references_db": str(references_db),
            "output_dir": str(tmp_path),
            "source_round": "round_01",
            "source_affair": "review_candidate_views",
            "batch_size": 1,
            "candidates": [
                {"uid_literature": "lit-001", "score": 95, "reason": "综述优先"},
                {"uid_literature": "lit-002", "score": 80, "reason": "主题相关"},
            ],
        },
    )

    outputs = module.execute(config_path)
    assert len(outputs) == 5
    assert all(path.exists() for path in outputs)

    gate_payload = json.loads((tmp_path / "gate_review.json").read_text(encoding="utf-8"))
    assert gate_payload["node_uid"] == "A05"

    with sqlite3.connect(references_db) as conn:
        tables = {
            row[0]
            for row in conn.execute("select name from sqlite_master where type='table'")
        }
        views = {
            row[0]
            for row in conn.execute("select name from sqlite_master where type='view'")
        }
        assert "review_candidate_pool_index" not in tables
        assert "review_candidate_pool_readable" not in tables
        assert "review_priority_view" not in tables
        assert "review_reading_batches" not in tables
        assert "review_gate_reviews" in tables
        assert "review_candidate_current_view" in views
        assert "review_read_pool_current_view" in views
        assert "review_priority_current_view" in views

        literature_columns = {
            row[1]
            for row in conn.execute("pragma table_info(literatures)")
        }
        for column in [
            "a05_scope_key",
            "a05_is_review_candidate",
            "a05_in_read_pool",
            "a05_current_score",
            "a05_current_rank",
            "a05_current_status",
            "a05_last_run_uid",
            "a05_updated_at",
        ]:
            assert column in literature_columns

        review_count = conn.execute("select count(*) from review_candidate_current_view").fetchone()[0]
        read_pool_count = conn.execute("select count(*) from review_read_pool_current_view").fetchone()[0]
        gate_count = conn.execute("select count(*) from review_gate_reviews").fetchone()[0]
        lit_row = conn.execute(
            "select a05_scope_key, a05_is_review_candidate, a05_in_read_pool, a05_current_rank, a05_current_status, a05_last_run_uid from literatures where uid_literature = ?",
            ("lit-001",),
        ).fetchone()
        assert review_count == 1
        assert read_pool_count == 1
        assert gate_count == 1
        assert lit_row is not None
        assert lit_row[0] == gate_payload["metadata"]["scope_key"]
        assert int(lit_row[1]) == 1
        assert int(lit_row[2]) == 1
        assert int(lit_row[3]) == 1
        assert lit_row[4] == "candidate"
        assert lit_row[5] == gate_payload["metadata"]["run_uid"]


def test_a090_discovered_rows_should_only_use_current_item_mappings() -> None:
    """A090 新候选回流只能基于当前文献自己的参考映射结果。"""

    module = importlib.import_module("autodokit.affairs.文献泛读与粗读.affair")

    discovered_rows = module._build_discovered_rows_from_mappings(
        item_mapping_rows=[
            {
                "matched_uid_literature": "lit-101",
                "matched_cite_key": "cite-101",
            },
            {
                "matched_uid_literature": "",
                "matched_cite_key": "",
            },
            {
                "matched_uid_literature": "lit-101",
                "matched_cite_key": "cite-101",
            },
            {
                "matched_uid_literature": "lit-001",
                "matched_cite_key": "self-cite",
            },
        ],
        uid_literature="lit-001",
        cite_key="source-cite",
    )

    assert len(discovered_rows) == 1
    assert discovered_rows[0]["uid_literature"] == "lit-101"
    assert discovered_rows[0]["cite_key"] == "cite-101"
    assert discovered_rows[0]["source_stage"] == "A090"
    assert discovered_rows[0]["source_uid_literature"] == "lit-001"
    assert discovered_rows[0]["source_cite_key"] == "source-cite"
    assert discovered_rows[0]["recommended_reason"] == "A090 从 source-cite 参考文献发现候选"
    assert discovered_rows[0]["theme_relation"] == "a090_reference_discovery"
    assert discovered_rows[0]["pending_preprocess"] == 1


def test_followup_candidate_should_route_to_pending_rough_read_when_already_preprocessed() -> None:
    """已预处理但未泛读的新候选，应直接进入待泛读而不是重新待预处理。"""

    module = importlib.import_module("autodokit.tools.reading_state_tools")

    routed = module.build_followup_candidate_state_row(
        uid_literature="lit-201",
        cite_key="cite-201",
        source_stage="A100",
        source_uid_literature="lit-001",
        source_cite_key="source-cite",
        recommended_reason="from deep read",
        theme_relation="a100_reference_discovery",
        existing_state={
            "uid_literature": "lit-201",
            "cite_key": "cite-201",
            "preprocessed": 1,
            "pending_preprocess": 1,
            "pending_rough_read": 0,
            "in_rough_read": 0,
            "rough_read_done": 0,
        },
    )

    assert routed is not None
    assert int(routed["preprocessed"]) == 1
    assert int(routed["pending_preprocess"]) == 0
    assert int(routed["pending_rough_read"]) == 1


def test_followup_candidate_should_not_requeue_when_already_rough_read_done() -> None:
    """已泛读文献不应因为引用回流再次进入待泛读。"""

    module = importlib.import_module("autodokit.tools.reading_state_tools")

    routed = module.build_followup_candidate_state_row(
        uid_literature="lit-301",
        cite_key="cite-301",
        source_stage="A090",
        source_uid_literature="lit-001",
        source_cite_key="source-cite",
        recommended_reason="from rough read",
        theme_relation="a090_reference_discovery",
        existing_state={
            "uid_literature": "lit-301",
            "cite_key": "cite-301",
            "preprocessed": 1,
            "pending_rough_read": 0,
            "in_rough_read": 0,
            "rough_read_done": 1,
        },
    )

    assert routed is None


def test_candidate_view_affair_should_use_reference_tools_for_mapping(monkeypatch, tmp_path: Path) -> None:
    """A05 事务应通过工具层处理参考文献映射。"""

    module = importlib.import_module("autodokit.affairs.候选文献视图构建.affair")
    references_db = tmp_path / "references.db"
    literature_table = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "title": "Topic Review",
                "keywords": "review; topic",
                "abstract": "survey",
                "first_author": "Guo",
                "year": "2025",
                "entry_type": "journal",
                "source": "CNKI",
                "cite_key": "guo-2025-topic_review",
                "pdf_path": "review.pdf",
            }
        ]
    )
    persist_reference_main_table(literature_table, references_db)
    workspace_root = tmp_path / "workspace"
    (workspace_root / "config").mkdir(parents=True, exist_ok=True)
    (workspace_root / "config" / "config.json").write_text(
        json.dumps(
            {
                "workspace_root": str(workspace_root),
                "llm": {"aliyun_api_key_file": str(tmp_path / "fake-key.txt"), "reference_parse_model": "qwen-flash"},
                "paths": {"log_db_path": str(workspace_root / "database" / "logs" / "aok_log.db")},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "extract_reference_lines_from_attachment",
        lambda *args, **kwargs: {
            "attachment_path": str(tmp_path / "review.pdf"),
            "attachment_type": "pdf",
            "extract_status": "ok",
            "extract_method": "pypdf",
            "reference_lines": ["Wang. 2024. Topic Review."],
            "reference_line_details": [
                {
                    "reference_text": "Wang. 2024. Topic Review.",
                    "suspicious_merged": 0,
                    "noise_trimmed": 0,
                }
            ],
            "full_text": "",
            "pending_reason": "",
        },
    )
    monkeypatch.setattr(
        module,
        "extract_reference_lines_from_structured_data",
        lambda *args, **kwargs: {
            "attachment_path": str(tmp_path / "review.pdf"),
            "attachment_type": "pdf",
            "extract_status": "ok",
            "extract_method": "structured",
            "reference_lines": ["Wang. 2024. Topic Review."],
            "reference_line_details": [
                {
                    "reference_text": "Wang. 2024. Topic Review.",
                    "suspicious_merged": 0,
                    "noise_trimmed": 0,
                }
            ],
            "full_text": "",
            "pending_reason": "",
        },
    )
    monkeypatch.setattr(
        module,
        "process_reference_citation",
        lambda table, reference_text, **kwargs: (
            table,
            {
                "reference_text": reference_text,
                "matched_uid_literature": "lit-777",
                "matched_cite_key": "wang-2024-topic_review",
                "action": "inserted",
                "parse_method": "aliyun_llm",
                "llm_invoked": 1,
                "parse_failed": 0,
                "parse_failure_reason": "",
            },
        ),
    )

    config_path = tmp_path / "candidate_config.json"
    _write_json_config(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "references_db": str(references_db),
            "output_dir": str(tmp_path),
            "source_round": "round_01",
            "source_affair": "review_candidate_views",
            "batch_size": 1,
            "research_topic": "主题波动",
        },
    )

    outputs = module.execute(config_path)
    assert all(path.exists() for path in outputs)
    mapping_csv = workspace_root / "knowledge" / "audits" / "reference_citation_mapping.csv"
    mapping_df = pd.read_csv(mapping_csv, dtype=str, keep_default_na=False)
    assert len(mapping_df) == 1
    assert mapping_df.iloc[0]["matched_cite_key"] == "wang-2024-topic_review"
    assert mapping_df.iloc[0]["parse_method"] == "aliyun_llm"
    quality_summary_path = workspace_root / "knowledge" / "audits" / "reference_citation_quality_summary.json"
    quality_summary = json.loads(quality_summary_path.read_text(encoding="utf-8"))
    assert quality_summary["total_reference_count"] == 1
    assert quality_summary["llm_recognized_count"] == 1
    assert quality_summary["placeholder_count"] == 1
    assert quality_summary["suspicious_merged_count"] == 0


def test_a080_human_seed_should_route_unique_cite_key() -> None:
    """A080 人工 seed 在 cite_key 唯一命中时应写入状态行。"""

    module = importlib.import_module("autodokit.affairs.非综述候选视图构建.affair")
    literatures_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "wang-2024-a",
                "pdf_path": "C:/tmp/a.pdf",
            }
        ]
    )
    attachments_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "storage_path": "C:/tmp/a.pdf",
                "is_primary": 1,
                "attachment_name": "a.pdf",
            }
        ]
    )

    rows, issues = module._build_human_seed_state_rows(
        seed_contract={
            "enabled": True,
            "default_target_stage": "rough_read",
            "seed_items": [
                {
                    "cite_key": "wang-2024-a",
                    "target_stage": "rough_read",
                    "manual_guidance": "重点看方法",
                    "reading_objective": "方法借鉴",
                }
            ],
        },
        literatures_df=literatures_df,
        attachments_df=attachments_df,
        existing_state_by_uid={
            "lit-001": {
                "uid_literature": "lit-001",
                "preprocessed": 1,
                "pending_preprocess": 0,
                "pending_rough_read": 0,
                "rough_read_done": 0,
                "pending_deep_read": 0,
                "deep_read_done": 0,
                "deep_read_count": 0,
            }
        },
    )

    assert issues == []
    assert len(rows) == 1
    assert rows[0]["uid_literature"] == "lit-001"
    assert rows[0]["source_origin"] == "human"
    assert rows[0]["manual_guidance"] == "重点看方法"
    assert rows[0]["reading_objective"] == "方法借鉴"
    assert int(rows[0]["pending_preprocess"]) == 0
    assert int(rows[0]["pending_rough_read"]) == 1


def test_a080_human_seed_should_report_ambiguous_cite_key() -> None:
    """A080 人工 seed 在 cite_key 多重命中时应进入问题列表。"""

    module = importlib.import_module("autodokit.affairs.非综述候选视图构建.affair")
    literatures_df = pd.DataFrame(
        [
            {"uid_literature": "lit-001", "cite_key": "dup-key", "pdf_path": "C:/tmp/a.pdf"},
            {"uid_literature": "lit-002", "cite_key": "dup-key", "pdf_path": "C:/tmp/b.pdf"},
        ]
    )
    attachments_df = pd.DataFrame()

    rows, issues = module._build_human_seed_state_rows(
        seed_contract={
            "enabled": True,
            "on_ambiguous": "manual_review",
            "seed_items": [{"cite_key": "dup-key"}],
        },
        literatures_df=literatures_df,
        attachments_df=attachments_df,
        existing_state_by_uid={},
    )

    assert rows == []
    assert any("命中多条文献" in issue for issue in issues)


def test_review_map_affair_execute_should_work(monkeypatch, tmp_path: Path) -> None:
    """综述研读与研究地图生成事务应回填 A05 资产并输出闸门文件。"""

    module = importlib.import_module("autodokit.affairs.综述研读与研究地图生成.affair")
    workspace_root, references_db, knowledge_db, review_read_pool_csv, output_dir = _prepare_review_synthesis_workspace(tmp_path)

    monkeypatch.setattr(
        module,
        "extract_review_state_from_attachment",
        lambda *args, **kwargs: {
            "uid_literature": "lit-001",
            "cite_key": "review-001",
            "title": "Topic Review",
            "year": "2024",
            "full_text": "第一句说明研究问题。第二句描述方法设计。第三句总结关键发现。第四句提出后续方向。",
            "sentences": [
                {"index": 1, "sentence": "本文梳理了目标主题中的关键问题。"},
                {"index": 2, "sentence": "文章基于已有资料总结了常见分析路径。"},
                {"index": 3, "sentence": "结果表明核心变量之间存在稳定关联。"},
                {"index": 4, "sentence": "未来需要进一步扩展样本范围和验证条件。"},
            ],
            "research_problem": [{"index": 1, "sentence": "本文梳理了目标主题中的关键问题。"}],
            "research_method": [{"index": 2, "sentence": "文章基于已有资料总结了常见分析路径。"}],
            "core_findings": [{"index": 3, "sentence": "结果表明核心变量之间存在稳定关联。"}],
            "future_directions": [{"index": 4, "sentence": "未来需要进一步扩展样本范围和验证条件。"}],
            "reference_lines": ["Li. 2022. Original Study One."],
        },
    )
    monkeypatch.setattr(
        module,
        "process_reference_citation",
        lambda table, reference_text, **kwargs: (
            table,
            {
                "reference_text": reference_text,
                "matched_uid_literature": "lit-002",
                "matched_cite_key": "origin-001",
                "action": "matched",
                "parse_method": "rule",
                "llm_invoked": 0,
                "parse_failed": 0,
                "parse_failure_reason": "",
                "match_score": 0.95,
                "suspicious_mismatch": 0,
            },
        ),
    )
    monkeypatch.setattr(module, "_sync_note", lambda knowledge_index, **kwargs: (knowledge_index, "note-001"))
    monkeypatch.setattr(module, "literature_bind_standard_note", lambda table, uid_literature, note_uid: (table, {}))

    config_path = tmp_path / "review_map_config.json"
    _write_json_config(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "references_db": str(references_db),
            "knowledge_db": str(knowledge_db),
            "review_read_pool_csv": str(review_read_pool_csv),
            "output_dir": str(output_dir),
            "topic": "目标主题",
        },
    )

    outputs = module.execute(config_path)
    gate_path = output_dir / "gate_review.json"
    assert gate_path in outputs
    assert gate_path.exists()


def test_review_map_affair_should_ensure_parse_asset_on_entry(monkeypatch, tmp_path: Path) -> None:
    """A06 缺少 structured 时应优先补齐 review_deep parse asset。"""

    module = importlib.import_module("autodokit.affairs.综述研读与研究地图生成.affair")
    workspace_root, content_db, review_read_pool_csv, output_dir = _prepare_review_synthesis_workspace(tmp_path)
    normalized_path = _write_structured_json(
        tmp_path / "structured" / "review-001.normalized.structured.json",
        uid_literature="lit-001",
        cite_key="review-001",
        text="本文梳理了目标主题中的关键问题。文章基于已有资料总结了常见分析路径。结果表明核心变量之间存在稳定关联。未来需要进一步扩展样本范围和验证条件。",
    )

    called: dict[str, str] = {}

    def _fake_ensure(**kwargs):
        called["parse_level"] = str(kwargs.get("parse_level", ""))
        called["source_stage"] = str(kwargs.get("source_stage", ""))
        return {
            "normalized_structured_path": str(normalized_path),
            "parse_level": "review_deep",
            "backend": "aliyun_multimodal",
        }

    monkeypatch.setattr(module, "ensure_multimodal_parse_asset", _fake_ensure)
    monkeypatch.setattr(
        module,
        "extract_review_state_from_structured_file",
        lambda *args, **kwargs: {
            "uid_literature": "lit-001",
            "cite_key": "review-001",
            "title": "Topic Review",
            "year": "2024",
            "full_text": "结构化缓存全文。",
            "sentences": [
                {"index": 1, "sentence": "本文梳理了目标主题中的关键问题。"},
                {"index": 2, "sentence": "文章基于已有资料总结了常见分析路径。"},
                {"index": 3, "sentence": "结果表明核心变量之间存在稳定关联。"},
                {"index": 4, "sentence": "未来需要进一步扩展样本范围和验证条件。"},
            ],
            "research_problem": [{"index": 1, "sentence": "本文梳理了目标主题中的关键问题。"}],
            "research_method": [{"index": 2, "sentence": "文章基于已有资料总结了常见分析路径。"}],
            "core_findings": [{"index": 3, "sentence": "结果表明核心变量之间存在稳定关联。"}],
            "future_directions": [{"index": 4, "sentence": "未来需要进一步扩展样本范围和验证条件。"}],
            "reference_lines": ["Li. 2022. Original Study One."],
        },
    )
    monkeypatch.setattr(
        module,
        "extract_review_state_from_attachment",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应回退到附件抽取")),
    )
    monkeypatch.setattr(
        module,
        "process_reference_citation",
        lambda table, reference_text, **kwargs: (
            table,
            {
                "reference_text": reference_text,
                "matched_uid_literature": "lit-002",
                "matched_cite_key": "origin-001",
                "action": "matched",
                "parse_method": "rule",
                "llm_invoked": 0,
                "parse_failed": 0,
                "parse_failure_reason": "",
                "match_score": 0.95,
                "suspicious_mismatch": 0,
            },
        ),
    )
    monkeypatch.setattr(module, "_sync_note", lambda knowledge_index, **kwargs: (knowledge_index, "note-001"))
    monkeypatch.setattr(module, "literature_bind_standard_note", lambda table, uid_literature, note_uid: (table, {}))

    config_path = tmp_path / "review_map_ensure_parse_config.json"
    _write_json_config(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "review_read_pool_csv": str(review_read_pool_csv),
            "output_dir": str(output_dir),
            "topic": "目标主题",
            "ensure_parse_on_entry": True,
        },
    )

    outputs = module.execute(config_path)
    gate_path = output_dir / "gate_review.json"
    assert gate_path in outputs
    assert gate_path.exists()
    assert called["parse_level"] == "review_deep"
    assert called["source_stage"] == "A06"

    payload = json.loads(gate_path.read_text(encoding="utf-8"))
    assert payload["node_uid"] == "A070"
    assert payload["recommendation"] == "pass"
    assert payload["metadata"]["processed_review_cite_keys"] == ["review-001"]

    must_read_df = pd.read_csv(
        workspace_root / "knowledge" / "audits" / "must_read_originals.csv",
        dtype=str,
        keep_default_na=False,
    )
    assert len(must_read_df) == 1
    assert must_read_df.iloc[0]["cite_key"] == "origin-001"

    downstream_df = pd.read_csv(
        workspace_root / "steps" / "A070_review_synthesis" / "downstream_non_review_candidates.csv",
        dtype=str,
        keep_default_na=False,
    )
    assert not downstream_df.empty
    assert set(downstream_df["target_stage"].tolist()) == {"A080"}

    queue_a080 = load_reading_queue_df(content_db, stage="A080", only_current=True)
    assert not queue_a080.empty
    assert "origin-001" in queue_a080["cite_key"].astype(str).tolist()

    batch_df = pd.read_csv(
        workspace_root / "batches" / "review_candidates" / "review_reading_batches.csv",
        dtype=str,
        keep_default_na=False,
    )
    assert batch_df.iloc[0]["a070_status"] == "completed"


def test_review_map_affair_should_fallback_to_current_view(monkeypatch, tmp_path: Path) -> None:
    """A06 在缺少 review_read_pool.csv 时应优先读取当前视图。"""

    module = importlib.import_module("autodokit.affairs.综述研读与研究地图生成.affair")
    workspace_root, references_db, knowledge_db, review_read_pool_csv, output_dir = _prepare_review_synthesis_workspace(tmp_path)
    review_read_pool_csv.unlink()

    with sqlite3.connect(references_db) as conn:
        conn.execute(
            """
            UPDATE literatures
            SET
                a05_scope_key = 'topic=目标主题|window=year:any',
                a05_is_review_candidate = 1,
                a05_in_read_pool = 1,
                a05_current_score = 95,
                a05_current_rank = 1,
                a05_current_status = 'candidate',
                a05_last_run_uid = 'a05-test-run',
                a05_updated_at = '2026-04-01T00:00:00+00:00'
            WHERE uid_literature = 'lit-001'
            """
        )
        conn.execute("DROP VIEW IF EXISTS review_read_pool_current_view")
        conn.execute(
            """
            CREATE VIEW review_read_pool_current_view AS
            SELECT
                uid_literature,
                cite_key,
                title,
                year,
                pdf_path,
                '' AS standard_note_uid,
                a05_current_status AS status,
                a05_current_score AS score
            FROM literatures
            WHERE CAST(COALESCE(a05_in_read_pool, 0) AS INTEGER) = 1
            """
        )
        conn.commit()

    monkeypatch.setattr(
        module,
        "extract_review_state_from_attachment",
        lambda *args, **kwargs: {
            "uid_literature": "lit-001",
            "cite_key": "review-001",
            "title": "Topic Review",
            "year": "2024",
            "full_text": "第一句说明研究问题。第二句描述方法设计。第三句总结关键发现。第四句提出后续方向。",
            "sentences": [
                {"index": 1, "sentence": "本文梳理了目标主题中的关键问题。"},
                {"index": 2, "sentence": "文章基于已有资料总结了常见分析路径。"},
                {"index": 3, "sentence": "结果表明核心变量之间存在稳定关联。"},
                {"index": 4, "sentence": "未来需要进一步扩展样本范围和验证条件。"},
            ],
            "research_problem": [{"index": 1, "sentence": "本文梳理了目标主题中的关键问题。"}],
            "research_method": [{"index": 2, "sentence": "文章基于已有资料总结了常见分析路径。"}],
            "core_findings": [{"index": 3, "sentence": "结果表明核心变量之间存在稳定关联。"}],
            "future_directions": [{"index": 4, "sentence": "未来需要进一步扩展样本范围和验证条件。"}],
            "reference_lines": ["Li. 2022. Original Study One."],
        },
    )
    monkeypatch.setattr(
        module,
        "process_reference_citation",
        lambda table, reference_text, **kwargs: (
            table,
            {
                "reference_text": reference_text,
                "matched_uid_literature": "lit-002",
                "matched_cite_key": "origin-001",
                "action": "matched",
                "parse_method": "rule",
                "llm_invoked": 0,
                "parse_failed": 0,
                "parse_failure_reason": "",
                "match_score": 0.95,
                "suspicious_mismatch": 0,
            },
        ),
    )
    monkeypatch.setattr(module, "_sync_note", lambda knowledge_index, **kwargs: (knowledge_index, "note-001"))
    monkeypatch.setattr(module, "literature_bind_standard_note", lambda table, uid_literature, note_uid: (table, {}))

    config_path = tmp_path / "review_map_view_config.json"
    _write_json_config(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "references_db": str(references_db),
            "knowledge_db": str(knowledge_db),
            "output_dir": str(output_dir),
            "topic": "目标主题",
        },
    )

    outputs = module.execute(config_path)
    gate_path = output_dir / "gate_review.json"
    assert gate_path in outputs
    assert gate_path.exists()


def test_research_trajectory_affair_execute_should_work(tmp_path: Path) -> None:
    """研究脉络梳理事务应输出时间线 JSON。"""

    module = importlib.import_module("autodokit.affairs.研究脉络梳理.affair")
    config_path = tmp_path / "trajectory_config.json"
    _write_json_config(
        config_path,
        {
            "output_dir": str(tmp_path),
            "topic": "主题演进",
            "items": [
                {"uid_literature": "lit-001", "title": "Paper A", "year": "2022", "keywords": "digital"},
                {"uid_literature": "lit-002", "title": "Paper B", "year": "2024", "keywords": "finance"},
            ],
        },
    )

    outputs = module.execute(config_path)
    assert len(outputs) == 2
    payload = json.loads((tmp_path / "research_trajectory.json").read_text(encoding="utf-8"))
    assert payload["item_count"] == 2


def test_innovation_affairs_should_work_as_chain(tmp_path: Path) -> None:
    """创新点池构建与可行性验证事务应可串联运行。"""

    pool_module = importlib.import_module("autodokit.affairs.创新点池构建.affair")
    score_module = importlib.import_module("autodokit.affairs.创新点可行性验证.affair")

    pool_config = tmp_path / "innovation_pool_config.json"
    _write_json_config(
        pool_config,
        {
            "output_dir": str(tmp_path),
            "topic": "目标主题",
            "gaps": ["缺少关键机制解释"],
            "scenario": "目标对象样本",
            "data_source": "结构化面板数据",
            "method_family": "对照组比较",
            "output_form": "机制分析结果",
        },
    )
    pool_outputs = pool_module.execute(pool_config)
    assert len(pool_outputs) == 2
    pool_csv = tmp_path / "innovation_pool.csv"
    assert pool_csv.exists()

    score_config = tmp_path / "innovation_score_config.json"
    _write_json_config(
        score_config,
        {
            "output_dir": str(tmp_path),
            "innovation_pool_csv": str(pool_csv),
        },
    )
    score_outputs = score_module.execute(score_config)
    assert len(score_outputs) == 2

    scored_table = pd.read_csv(tmp_path / "innovation_feasibility_scores.csv", dtype=str, keep_default_na=False)
    assert len(scored_table) == 5
    assert set(scored_table["recommendation"]) == {"promote"}


def test_parse_and_chunk_affair_should_index_structured_chunks_to_sqlite(tmp_path: Path) -> None:
    """解析与分块事务应支持 structured.json 主链并写回 chunk 索引。"""

    module = importlib.import_module("autodokit.affairs.解析与分块.affair")
    workspace_root = tmp_path / "workspace"
    references_db = workspace_root / "database" / "references" / "references.db"
    output_dir = tmp_path / "outputs"
    structured_dir = tmp_path / "structured"
    structured_path = _write_structured_json(
        structured_dir / "review-001.structured.json",
        uid_literature="lit-001",
        cite_key="review-001",
        text="第一段说明研究问题。第二段描述方法。第三段给出结果。第四段提出未来方向。",
    )

    persist_reference_tables(
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-001",
                    "cite_key": "review-001",
                    "title": "Review 001",
                    "structured_abs_path": str(structured_path),
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        attachments_df=pd.DataFrame(),
        db_path=references_db,
    )

    config_path = tmp_path / "parse_chunk_config.json"
    _write_json_config(
        config_path,
        {
            "references_db": str(references_db),
            "output_dir": str(output_dir),
            "chunk_size": 120,
            "min_chunk_size": 20,
            "chunk_shard_size": 1,
            "write_legacy_chunks_jsonl": True,
        },
    )

    outputs = module.execute(config_path)
    manifest_path = output_dir / "chunk_manifest.json"
    assert manifest_path in outputs
    assert manifest_path.exists()

    chunk_sets = load_chunk_sets_df(references_db)
    chunks = load_chunks_df(references_db)
    assert len(chunk_sets) == 1
    assert int(chunk_sets.iloc[0]["chunk_count"]) >= 1
    assert len(chunks) >= 1
    assert set(chunks["uid_literature"].astype(str).tolist()) == {"lit-001"}


def test_review_map_affair_should_prefer_structured_cache(monkeypatch, tmp_path: Path) -> None:
    """A06 命中结构化缓存时不应再回退原始附件抽取。"""

    module = importlib.import_module("autodokit.affairs.综述研读与研究地图生成.affair")
    workspace_root, references_db, knowledge_db, review_read_pool_csv, output_dir = _prepare_review_synthesis_workspace(tmp_path)
    structured_path = _write_structured_json(
        tmp_path / "structured" / "review-001.structured.json",
        uid_literature="lit-001",
        cite_key="review-001",
        text="本文梳理了目标主题中的关键问题。文章基于已有资料总结了常见分析路径。结果表明核心变量之间存在稳定关联。未来需要进一步扩展样本范围和验证条件。",
    )

    with sqlite3.connect(references_db) as conn:
        conn.execute(
            """
            UPDATE literatures
            SET structured_status = ?, structured_abs_path = ?, structured_backend = ?, structured_task_type = ?, structured_schema_version = ?
            WHERE uid_literature = ?
            """,
            ("ready", str(structured_path), "local_pipeline_v2", "full_fine_grained", "aok.pdf_structured.v3", "lit-001"),
        )
        conn.commit()

    monkeypatch.setattr(
        module,
        "extract_review_state_from_structured_file",
        lambda *args, **kwargs: {
            "uid_literature": "lit-001",
            "cite_key": "review-001",
            "title": "Topic Review",
            "year": "2024",
            "full_text": "结构化缓存全文。",
            "sentences": [
                {"index": 1, "sentence": "本文梳理了目标主题中的关键问题。"},
                {"index": 2, "sentence": "文章基于已有资料总结了常见分析路径。"},
                {"index": 3, "sentence": "结果表明核心变量之间存在稳定关联。"},
                {"index": 4, "sentence": "未来需要进一步扩展样本范围和验证条件。"},
            ],
            "research_problem": [{"index": 1, "sentence": "本文梳理了目标主题中的关键问题。"}],
            "research_method": [{"index": 2, "sentence": "文章基于已有资料总结了常见分析路径。"}],
            "core_findings": [{"index": 3, "sentence": "结果表明核心变量之间存在稳定关联。"}],
            "future_directions": [{"index": 4, "sentence": "未来需要进一步扩展样本范围和验证条件。"}],
            "reference_lines": ["Li. 2022. Original Study One."],
        },
    )
    monkeypatch.setattr(
        module,
        "extract_review_state_from_attachment",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应回退到附件抽取")),
    )
    monkeypatch.setattr(
        module,
        "process_reference_citation",
        lambda table, reference_text, **kwargs: (
            table,
            {
                "reference_text": reference_text,
                "matched_uid_literature": "lit-002",
                "matched_cite_key": "origin-001",
                "action": "matched",
                "parse_method": "rule",
                "llm_invoked": 0,
                "parse_failed": 0,
                "parse_failure_reason": "",
                "match_score": 0.95,
                "suspicious_mismatch": 0,
            },
        ),
    )
    monkeypatch.setattr(module, "_sync_note", lambda knowledge_index, **kwargs: (knowledge_index, "note-001"))
    monkeypatch.setattr(module, "literature_bind_standard_note", lambda table, uid_literature, note_uid: (table, {}))

    config_path = tmp_path / "review_map_structured_config.json"
    _write_json_config(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "references_db": str(references_db),
            "knowledge_db": str(knowledge_db),
            "review_read_pool_csv": str(review_read_pool_csv),
            "output_dir": str(output_dir),
            "topic": "目标主题",
        },
    )

    outputs = module.execute(config_path)
    gate_path = output_dir / "gate_review.json"
    assert gate_path in outputs
    payload = json.loads(gate_path.read_text(encoding="utf-8"))
    assert payload["recommendation"] == "pass"


def test_a07_should_prefer_a06_queue_and_seed_a08_queue(tmp_path: Path) -> None:
    """A07 应优先消费 A06 写入的队列，并同步生成 A08 当前队列。"""

    module = importlib.import_module("autodokit.affairs.非综述候选视图构建.affair")
    workspace_root = tmp_path / "workspace"
    content_db = workspace_root / "database" / "content" / "content.db"
    output_dir = tmp_path / "a07_outputs"
    dummy_pdf = workspace_root / "references" / "attachments" / "origin-001.pdf"
    dummy_pdf.parent.mkdir(parents=True, exist_ok=True)
    dummy_pdf.write_bytes(b"%PDF-1.4\n%placeholder\n")

    persist_reference_tables(
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-101",
                    "cite_key": "origin-001",
                    "title": "Original Study One",
                    "first_author": "Li",
                    "year": "2022",
                    "entry_type": "journal",
                    "abstract": "An original study used for downstream reading.",
                    "keywords": "evidence; topic",
                    "pdf_path": str(dummy_pdf),
                    "primary_attachment_name": dummy_pdf.name,
                    "standardization_status": "standardized",
                }
            ]
        ),
        attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "att-101",
                    "uid_literature": "lit-101",
                    "attachment_name": dummy_pdf.name,
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": str(dummy_pdf),
                    "source_path": str(dummy_pdf),
                    "checksum": "",
                    "is_primary": 1,
                    "status": "available",
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        db_path=content_db,
    )
    upsert_reading_queue_rows(
        content_db,
        [
            {
                "uid_literature": "lit-101",
                "cite_key": "origin-001",
                "stage": "A07",
                "source_affair": "A06",
                "queue_status": "queued",
                "priority": 90.0,
                "bucket": "classical_core",
                "preferred_next_stage": "A07",
                "recommended_reason": "综述高置信引用推荐",
                "theme_relation": "review_must_read",
            }
        ],
    )

    config_path = tmp_path / "a07_config.json"
    _write_json_config(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "output_dir": str(output_dir),
            "require_fulltext": False,
            "batch_size": 1,
        },
    )

    outputs = module.execute(config_path)
    assert (output_dir / "gate_review.json") in outputs

    candidate_df = pd.read_csv(output_dir / "non_review_candidate_pool_index.csv", dtype=str, keep_default_na=False)
    assert len(candidate_df) == 1
    assert candidate_df.iloc[0]["cite_key"] == "origin-001"

    queue_a08 = load_reading_queue_df(content_db, stage="A08", only_current=True)
    assert not queue_a08.empty
    assert "origin-001" in queue_a08["cite_key"].astype(str).tolist()


def test_a08_should_consume_queue_and_write_back_completion(monkeypatch, tmp_path: Path) -> None:
    """A08 应优先消费 A08 队列，并把粗读结果回写到当前状态。"""

    module = importlib.import_module("autodokit.affairs.文献泛读与粗读.affair")
    workspace_root = tmp_path / "workspace"
    content_db = workspace_root / "database" / "content" / "content.db"
    output_dir = tmp_path / "a08_outputs"
    dummy_pdf = workspace_root / "references" / "attachments" / "origin-rough.pdf"
    dummy_pdf.parent.mkdir(parents=True, exist_ok=True)
    dummy_pdf.write_bytes(b"%PDF-1.4\n%placeholder\n")

    persist_reference_tables(
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-201",
                    "cite_key": "origin-rough",
                    "title": "Original Rough Study",
                    "first_author": "Chen",
                    "year": "2023",
                    "entry_type": "journal",
                    "abstract": "A paper for rough reading.",
                    "keywords": "bank; risk",
                    "pdf_path": str(dummy_pdf),
                    "primary_attachment_name": dummy_pdf.name,
                    "standardization_status": "standardized",
                }
            ]
        ),
        attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "att-201",
                    "uid_literature": "lit-201",
                    "attachment_name": dummy_pdf.name,
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": str(dummy_pdf),
                    "source_path": str(dummy_pdf),
                    "checksum": "",
                    "is_primary": 1,
                    "status": "available",
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        db_path=content_db,
    )
    upsert_reading_queue_rows(
        content_db,
        [
            {
                "uid_literature": "lit-201",
                "cite_key": "origin-rough",
                "stage": "A08",
                "source_affair": "A07",
                "queue_status": "queued",
                "priority": 72.0,
                "bucket": "rough_read",
                "preferred_next_stage": "A08",
                "recommended_reason": "进入粗读池",
                "theme_relation": "A07_non_review_pool",
            }
        ],
    )

    monkeypatch.setattr(
        module,
        "extract_reference_lines_from_attachment",
        lambda *args, **kwargs: {
            "attachment_path": str(dummy_pdf),
            "attachment_type": "pdf",
            "extract_status": "ok",
            "extract_method": "pypdf",
            "reference_lines": ["Li. 2022. Original Study One."],
            "reference_line_details": [],
            "full_text": "本文研究银行风险。文章基于实证设计说明识别策略。结果表明核心变量存在稳定关系。",
            "pending_reason": "",
        },
    )
    monkeypatch.setattr(
        module,
        "process_reference_citation",
        lambda table, reference_text, **kwargs: (
            table,
            {
                "matched_uid_literature": "lit-999",
                "matched_cite_key": "origin-999",
                "action": "matched",
                "parse_method": "rule",
                "llm_invoked": 0,
                "parse_failed": 0,
                "parse_failure_reason": "",
                "suspicious_merged": 0,
                "noise_trimmed": 0,
                "match_score": 0.9,
                "suspicious_mismatch": 0,
            },
        ),
    )

    config_path = tmp_path / "a08_config.json"
    _write_json_config(
        config_path,
        {
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "output_dir": str(output_dir),
            "max_items": 1,
        },
    )

    outputs = module.execute(config_path)
    assert (output_dir / "gate_review.json") in outputs

    queue_a08 = load_reading_queue_df(content_db, stage="A08", only_current=True)
    current_row = queue_a08[queue_a08["cite_key"].astype(str) == "origin-rough"].iloc[0].to_dict()
    assert current_row["queue_status"] == "completed"
    assert current_row["decision"] in {"promote_a09", "hold"}


def test_single_rough_reading_should_accept_structured_json(tmp_path: Path) -> None:
    """单篇粗读事务应可直接消费 structured.json。"""

    module = importlib.import_module("autodokit.affairs.单篇粗读.affair")
    structured_path = _write_structured_json(
        tmp_path / "demo.structured.json",
        uid_literature="lit-001",
        cite_key="demo-001",
        text="摘要部分。References Li. 2022. Original Study One.",
    )
    output_dir = tmp_path / "rough_outputs"
    config_path = tmp_path / "rough_structured_config.json"
    _write_json_config(
        config_path,
        {
            "input_structured_json": str(structured_path),
            "output_dir": str(output_dir),
            "uid_literature": "lit-001",
        },
    )

    outputs = module.execute(config_path)
    note_path = output_dir / "rough_reading_lit-001.md"
    assert note_path in outputs
    assert "单篇粗读笔记" in note_path.read_text(encoding="utf-8")


def test_single_reading_should_accept_structured_json_without_llm(tmp_path: Path) -> None:
    """单篇精读事务在 use_llm=false 时应可直接消费 structured.json。"""

    module = importlib.import_module("autodokit.affairs.单篇精读.affair")
    structured_path = _write_structured_json(
        tmp_path / "demo-reading.structured.json",
        uid_literature="lit-001",
        cite_key="demo-reading-001",
        text="第一句。第二句。第三句。第四句。",
    )
    output_dir = tmp_path / "reading_outputs"
    config_path = tmp_path / "reading_structured_config.json"
    _write_json_config(
        config_path,
        {
            "input_structured_json": str(structured_path),
            "output_dir": str(output_dir),
            "uid_literature": "lit-001",
            "use_llm": False,
        },
    )

    outputs = module.execute(config_path)
    note_path = output_dir / "single_reading_lit-001.md"
    assert note_path in outputs
    assert "核心内容速记" in note_path.read_text(encoding="utf-8")

