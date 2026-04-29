"""SQLite 文献关系表工具测试。"""

from __future__ import annotations

import os
import json
from pathlib import Path
import sqlite3

import pandas as pd

from autodokit.tools import incremental_import_bib_into_content_db
from autodokit.tools.bibliodb_sqlite import (
    get_structured_state,
    load_attachments_df,
    load_chunk_sets_df,
    load_chunks_df,
    load_literatures_df,
    load_reading_state_df,
    load_tags_df,
    merge_reference_records,
    replace_reference_tables_only,
    replace_chunk_set_records,
    rebuild_reference_relation_tables_from_config,
    save_structured_state,
    save_tables,
    upsert_reading_queue_rows,
    upsert_reading_state_rows,
)
from autodokit.tools.contentdb_sqlite import init_content_db


def test_incremental_import_tool_should_merge_records_and_preserve_runtime_tables(tmp_path: Path) -> None:
    """独立增量导入入口应合并重复文献且保留运行态表。"""

    db_path = tmp_path / "content.db"
    save_tables(
        db_path,
        literatures_df=pd.DataFrame(
            [
                {
                    "id": 1,
                    "uid_literature": "lit-old-001",
                    "cite_key": "sciinfo-2024-scientometrics",
                    "title": "科学学研究方法综述",
                    "title_norm": "科学学研究方法综述",
                    "first_author": "研究者甲",
                    "year": "2024",
                    "entry_type": "article",
                    "has_fulltext": 1,
                    "primary_attachment_name": "old.pdf",
                    "pdf_path": "/tmp/papers/old.pdf",
                    "keywords": "科学学; 学术评价",
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "att-old-001",
                    "uid_literature": "lit-old-001",
                    "attachment_name": "old.pdf",
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": "/tmp/papers/old.pdf",
                    "source_path": "/tmp/papers/old.pdf",
                    "checksum": "",
                    "is_primary": 1,
                    "status": "available",
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        if_exists="replace",
    )
    upsert_reading_state_rows(
        db_path,
        [
            {
                "uid_literature": "lit-old-001",
                "cite_key": "sciinfo-2024-scientometrics",
                "source_stage": "A080",
                "pending_preprocess": 1,
                "preprocessed": 0,
                "pending_rough_read": 0,
                "rough_read_done": 0,
                "deep_read_count": 0,
            }
        ],
    )

    bib_path = tmp_path / "incoming.bib"
    bib_path.write_text(
        """
@article{dup_ref,
  title={科学学研究方法综述},
  author={研究者甲 and 研究者乙},
  year={2024},
  keywords={科学学; 学术评价}
}

@article{new_ref,
  title={学术影响力与政策工具},
  author={研究者丙 and 研究者丁},
  year={2023},
  keywords={学术影响力; 政策工具}
}
""".strip(),
        encoding="utf-8",
    )

    summary = incremental_import_bib_into_content_db(
        db_path=db_path,
        bib_paths=bib_path,
        tag_list=["科学学", "学术影响力"],
        tag_match_fields=["title", "keywords"],
        has_pdf_enable=False,
    )

    literatures_df = load_literatures_df(db_path)
    attachments_df = load_attachments_df(db_path)
    tags_df = load_tags_df(db_path)
    reading_state_df = load_reading_state_df(db_path)

    assert summary["incoming_count"] == 2
    assert summary["matched_existing_count"] == 1
    assert summary["inserted_count"] == 1
    assert summary["final_literature_count"] == 2

    uid_values = set(literatures_df["uid_literature"].tolist())
    assert "lit-old-001" in uid_values
    assert len(uid_values) == 2
    assert set(attachments_df["uid_literature"].tolist()) == {"lit-old-001"}
    assert set(tags_df["tag"].tolist()) == {"科学学", "学术影响力"}
    assert set(reading_state_df["uid_literature"].tolist()) == {"lit-old-001"}
    assert "imported_at" in literatures_df.columns
    assert literatures_df["created_at"].astype(str).str.contains("+08:00", regex=False).all()
    assert literatures_df["updated_at"].astype(str).str.contains("+08:00", regex=False).all()
    assert literatures_df["imported_at"].astype(str).str.contains("+08:00", regex=False).all()


def test_rebuild_reference_relation_tables_from_config_should_fill_attachment_and_tag_tables(tmp_path: Path) -> None:
    """应能根据主表与配置重建附件关系表和标签关系表。"""

    db_path = tmp_path / "references.db"
    literatures_df = pd.DataFrame(
        [
            {
                "id": 1,
                "uid_literature": "lit-001",
                "cite_key": "lit-001",
                "title": "科研产出与学术影响力测度",
                "abstract": "讨论科研产出与学术评价",
                "keywords": "科研评价;科学学",
                "pdf_path": "workspace/references/attachments/a.pdf",
                "primary_attachment_name": "a.pdf",
                "created_at": "",
                "updated_at": "",
            },
            {
                "id": 2,
                "uid_literature": "lit-002",
                "cite_key": "lit-002",
                "title": "普通银行研究",
                "abstract": "一般银行业务",
                "keywords": "银行",
                "pdf_path": "",
                "primary_attachment_name": "",
                "created_at": "",
                "updated_at": "",
            },
        ]
    )
    save_tables(db_path, literatures_df=literatures_df, if_exists="replace")

    config_path = tmp_path / "a02.json"
    config_path.write_text(
        json.dumps(
            {
                "tag_list": ["科研评价", "科学学"],
                "tag_match_fields": ["title", "abstract", "keywords"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = rebuild_reference_relation_tables_from_config(db_path, config_path)
    attachments_df = load_attachments_df(db_path)
    tags_df = load_tags_df(db_path)

    assert summary["literatures"] == 2
    assert summary["literature_attachments"] == 1
    assert summary["literature_tags"] == 2
    assert len(attachments_df) == 1
    assert len(tags_df) == 2
    assert set(tags_df["tag"].tolist()) == {"科研评价", "科学学"}


def test_structured_state_and_chunk_index_tables_should_roundtrip(tmp_path: Path) -> None:
    """结构化状态字段与 chunk 索引表应能写入并回读。"""

    db_path = tmp_path / "references.db"
    literatures_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "sci-2024-demo",
                "title": "科学学示例论文",
                "created_at": "",
                "updated_at": "",
            }
        ]
    )
    save_tables(db_path, literatures_df=literatures_df, if_exists="replace")

    save_structured_state(
        db_path,
        uid_literature="lit-001",
        structured_status="ready",
        structured_abs_path=str((tmp_path / "sci-2024-demo.structured.json").resolve()),
        structured_backend="local_pipeline_v2",
        structured_task_type="full_fine_grained",
        structured_updated_at="2026-04-01T10:00:00+00:00",
        structured_schema_version="aok.pdf_structured.v3",
        structured_text_length=1200,
        structured_reference_count=18,
    )

    replace_chunk_set_records(
        db_path,
        chunk_set_row={
            "chunks_uid": "chunks-001",
            "source_scope": "scope-demo",
            "chunks_abs_path": str((tmp_path / "chunk_manifest.json").resolve()),
            "source_backend": "structured_json",
            "chunk_count": 2,
            "source_doc_count": 1,
            "created_at": "2026-04-01T10:05:00+00:00",
            "status": "ready",
        },
        chunk_rows=[
            {
                "chunk_id": "chunk-001",
                "chunks_uid": "chunks-001",
                "uid_literature": "lit-001",
                "cite_key": "sci-2024-demo",
                "shard_abs_path": str((tmp_path / "chunks-001.part-001.jsonl").resolve()),
                "chunk_index": 1,
                "chunk_type": "paragraph_bundle",
                "char_start": 0,
                "char_end": 400,
                "text_length": 400,
                "created_at": "2026-04-01T10:05:00+00:00",
            },
            {
                "chunk_id": "chunk-002",
                "chunks_uid": "chunks-001",
                "uid_literature": "lit-001",
                "cite_key": "sci-2024-demo",
                "shard_abs_path": str((tmp_path / "chunks-001.part-001.jsonl").resolve()),
                "chunk_index": 2,
                "chunk_type": "paragraph_bundle",
                "char_start": 401,
                "char_end": 800,
                "text_length": 399,
                "created_at": "2026-04-01T10:05:00+00:00",
            },
        ],
    )

    state = get_structured_state(db_path, "lit-001")
    chunk_sets = load_chunk_sets_df(db_path)
    chunks = load_chunks_df(db_path)

    assert state["structured_status"] == "ready"
    assert state["structured_schema_version"] == "aok.pdf_structured.v3"
    assert int(state["structured_reference_count"]) == 18
    assert len(chunk_sets) == 1
    assert chunk_sets.iloc[0]["chunks_uid"] == "chunks-001"
    assert len(chunks) == 2
    assert set(chunks["chunk_id"].tolist()) == {"chunk-001", "chunk-002"}


def test_reading_state_table_should_roundtrip_and_ignore_queue_conflicts(tmp_path: Path) -> None:
    """阅读状态表应独立于旧队列表，且支持幂等回写。"""

    db_path = tmp_path / "references.db"

    save_tables(
        db_path,
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-001",
                    "cite_key": "state-cite",
                    "title": "State Candidate One",
                    "created_at": "",
                    "updated_at": "",
                },
                {
                    "uid_literature": "lit-002",
                    "cite_key": "state-second",
                    "title": "State Candidate Two",
                    "created_at": "",
                    "updated_at": "",
                },
            ]
        ),
        if_exists="replace",
    )

    upsert_reading_queue_rows(
        db_path,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "legacy-queue",
                "stage": "A100",
                "queue_status": "pending",
                "is_current": 1,
            }
        ],
    )
    upsert_reading_state_rows(
        db_path,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "state-cite",
                "source_stage": "A080",
                "pending_preprocess": 1,
                "preprocessed": 0,
                "pending_rough_read": 0,
                "rough_read_done": 0,
                "deep_read_count": 0,
            },
            {
                "uid_literature": "lit-002",
                "cite_key": "state-second",
                "source_stage": "A090",
                "pending_preprocess": 0,
                "preprocessed": 1,
                "pending_rough_read": 1,
                "rough_read_done": 0,
                "deep_read_count": 0,
            },
        ],
    )
    upsert_reading_state_rows(
        db_path,
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "state-cite-updated",
                "source_stage": "A080",
                "pending_preprocess": 0,
                "preprocessed": 1,
                "pending_rough_read": 1,
                "rough_read_done": 1,
                "analysis_light_synced": 1,
                "deep_read_count": 2,
            }
        ],
    )

    state_df = load_reading_state_df(db_path)
    pending_rough_df = load_reading_state_df(db_path, flag_filters={"pending_rough_read": 1})
    pending_preprocess_df = load_reading_state_df(db_path, flag_filters={"pending_preprocess": 1})

    assert set(state_df["uid_literature"].tolist()) == {"lit-001", "lit-002"}
    row = state_df[state_df["uid_literature"] == "lit-001"].iloc[0]
    assert row["cite_key"] == "state-cite-updated"
    assert int(row["preprocessed"]) == 1
    assert int(row["rough_read_done"]) == 1
    assert int(row["analysis_light_synced"]) == 1
    assert int(row["deep_read_count"]) == 2
    assert list(pending_rough_df["uid_literature"]) == ["lit-002", "lit-001"]
    assert pending_preprocess_df.empty


def test_reading_state_views_should_expose_human_facing_live_lists(tmp_path: Path) -> None:
    """中文阅读状态视图应能实时反映底层单表状态机。"""

    db_path = tmp_path / "content.db"
    save_tables(
        db_path,
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-pre",
                    "cite_key": "pre-001",
                    "title": "预处理中的文献",
                    "first_author": "研究者甲",
                    "year": "2024",
                    "entry_type": "article",
                    "has_fulltext": 0,
                    "is_placeholder": 1,
                    "created_at": "",
                    "updated_at": "",
                },
                {
                    "uid_literature": "lit-rough",
                    "cite_key": "rough-001",
                    "title": "待泛读文献",
                    "first_author": "研究者乙",
                    "year": "2023",
                    "entry_type": "article",
                    "has_fulltext": 1,
                    "is_placeholder": 0,
                    "created_at": "",
                    "updated_at": "",
                },
                {
                    "uid_literature": "lit-parse",
                    "cite_key": "deep-001",
                    "title": "待批判性研读文献",
                    "first_author": "研究者丙",
                    "year": "2022",
                    "entry_type": "article",
                    "has_fulltext": 1,
                    "is_placeholder": 0,
                    "created_at": "",
                    "updated_at": "",
                },
            ]
        ),
        attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "att-rough",
                    "uid_literature": "lit-rough",
                    "attachment_name": "rough.pdf",
                    "attachment_type": "pdf",
                    "file_ext": ".pdf",
                    "storage_path": str((tmp_path / "rough.pdf").resolve()),
                    "source_path": "",
                    "checksum": "",
                    "is_primary": 1,
                    "status": "ready",
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        if_exists="replace",
    )
    save_structured_state(
        db_path,
        uid_literature="lit-parse",
        structured_status="ready",
        structured_abs_path=str((tmp_path / "deep-001.structured.json").resolve()),
        structured_backend="aliyun_multimodal",
        structured_task_type="non_review_deep",
        structured_updated_at="2026-04-07T10:00:00+00:00",
        structured_schema_version="aok.pdf_structured.v3",
        structured_text_length=2000,
        structured_reference_count=30,
    )
    upsert_reading_state_rows(
        db_path,
        [
            {
                "uid_literature": "lit-pre",
                "cite_key": "pre-001",
                "pending_preprocess": 1,
                "preprocessed": 0,
                "preprocess_status": "missing_attachment",
                "source_origin": "auto",
            },
            {
                "uid_literature": "lit-rough",
                "cite_key": "rough-001",
                "preprocessed": 1,
                "pending_rough_read": 1,
                "source_origin": "human",
                "manual_guidance": "重点看变量构造。",
            },
            {
                "uid_literature": "lit-parse",
                "cite_key": "deep-001",
                "preprocessed": 1,
                "pending_deep_read": 0,
                "deep_read_decision": "parse_ready",
                "deep_read_done": 0,
                "source_origin": "legacy_queue",
            },
        ],
    )

    with sqlite3.connect(db_path) as conn:
        pending_preprocess = conn.execute(
            'SELECT uid_literature, preprocess_status, current_list_name FROM "待预处理文献清单"'
        ).fetchall()
        attachment_backlog = conn.execute(
            'SELECT uid_literature FROM "补件待办文献清单"'
        ).fetchall()
        pending_rough = conn.execute(
            'SELECT uid_literature, primary_attachment_name, source_origin FROM "待泛读文献清单"'
        ).fetchall()
        pending_critical = conn.execute(
            'SELECT uid_literature, current_parse_status, deep_read_decision FROM "待批判性研读文献清单"'
        ).fetchall()
        overview_row = conn.execute(
            'SELECT uid_literature, title, current_list_name, attachment_count, current_parse_status FROM "阅读状态总视图" WHERE uid_literature = ?',
            ("lit-parse",),
        ).fetchone()

    assert pending_preprocess == [("lit-pre", "missing_attachment", "补件待办")]
    assert attachment_backlog == [("lit-pre",)]
    assert pending_rough == [("lit-rough", "rough.pdf", "human")]
    assert pending_critical == [("lit-parse", "ready", "parse_ready")]
    assert overview_row == ("lit-parse", "待批判性研读文献", "待批判性研读", 0, "ready")


def test_attachment_normalization_tables_should_support_shared_assets(tmp_path: Path) -> None:
    """附件规范化后应允许一个附件实体关联多篇文献。"""

    db_path = tmp_path / "content.db"
    shared_pdf = str((tmp_path / "shared.pdf").resolve())
    appendix_pdf = str((tmp_path / "appendix.pdf").resolve())

    save_tables(
        db_path,
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-001",
                    "cite_key": "lit-001",
                    "title": "文献一",
                    "created_at": "",
                    "updated_at": "",
                },
                {
                    "uid_literature": "lit-002",
                    "cite_key": "lit-002",
                    "title": "文献二",
                    "created_at": "",
                    "updated_at": "",
                },
            ]
        ),
        attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "legacy-att-001",
                    "uid_literature": "lit-001",
                    "attachment_name": "shared.pdf",
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": shared_pdf,
                    "source_path": shared_pdf,
                    "checksum": "checksum-shared",
                    "is_primary": 1,
                    "status": "available",
                    "created_at": "",
                    "updated_at": "",
                },
                {
                    "uid_attachment": "legacy-att-002",
                    "uid_literature": "lit-002",
                    "attachment_name": "shared.pdf",
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": shared_pdf,
                    "source_path": shared_pdf,
                    "checksum": "checksum-shared",
                    "is_primary": 1,
                    "status": "available",
                    "created_at": "",
                    "updated_at": "",
                },
                {
                    "uid_attachment": "legacy-att-003",
                    "uid_literature": "lit-001",
                    "attachment_name": "appendix.pdf",
                    "attachment_type": "supplement",
                    "file_ext": "pdf",
                    "storage_path": appendix_pdf,
                    "source_path": appendix_pdf,
                    "checksum": "checksum-appendix",
                    "is_primary": 0,
                    "status": "available",
                    "created_at": "",
                    "updated_at": "",
                },
            ]
        ),
        if_exists="replace",
    )

    with sqlite3.connect(db_path) as conn:
        attachment_count = conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
        link_count = conn.execute("SELECT COUNT(*) FROM literature_attachment_links").fetchone()[0]
        shared_link_count = conn.execute(
            "SELECT COUNT(*) FROM literature_attachment_links WHERE uid_attachment IN (SELECT uid_attachment FROM attachments WHERE checksum = ?)",
            ("checksum-shared",),
        ).fetchone()[0]

    attachments_df = load_attachments_df(db_path)

    assert attachment_count == 2
    assert link_count == 3
    assert shared_link_count == 2
    assert len(attachments_df) == 3


def test_normalized_attachments_should_be_source_of_truth_for_legacy_projection(tmp_path: Path) -> None:
    """规范化附件表存在时，旧扁平表应由其投影生成，不应反向污染。"""

    db_path = tmp_path / "content.db"
    storage_path = str((tmp_path / "paper.pdf").resolve())

    save_tables(
        db_path,
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-001",
                    "cite_key": "lit-001",
                    "title": "文献一",
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "legacy-att-001",
                    "uid_literature": "lit-001",
                    "attachment_name": "paper.pdf",
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": storage_path,
                    "source_path": storage_path,
                    "checksum": "checksum-paper",
                    "is_primary": 1,
                    "status": "available",
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        if_exists="replace",
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM literature_attachments")
        conn.execute(
            """
            INSERT INTO literature_attachments
            (uid_attachment, uid_literature, attachment_name, attachment_type, file_ext, storage_path, source_path, checksum, is_primary, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-stale",
                "lit-001",
                "stale.pdf",
                "fulltext",
                "pdf",
                "/tmp/stale/stale.pdf",
                "/tmp/stale/stale.pdf",
                "checksum-stale",
                1,
                "available",
                "",
                "",
            ),
        )
        conn.commit()

    init_content_db(db_path)

    with sqlite3.connect(db_path) as conn:
        legacy_rows = conn.execute(
            "SELECT uid_attachment, attachment_name, checksum FROM literature_attachments ORDER BY uid_attachment"
        ).fetchall()
        normalized_link_count = conn.execute("SELECT COUNT(*) FROM literature_attachment_links").fetchone()[0]

    assert normalized_link_count == 1
    assert len(legacy_rows) == 1
    assert legacy_rows[0][1] == "paper.pdf"
    assert legacy_rows[0][2] == "checksum-paper"


def test_merge_reference_records_should_keep_existing_uid_and_runtime_tables(tmp_path: Path) -> None:
    """增量并库应复用旧 UID、合并附件，并保留阅读状态表。"""

    db_path = tmp_path / "content.db"
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    old_pdf = old_dir / "paper.pdf"
    new_pdf = new_dir / "paper.pdf"
    supplement_pdf = new_dir / "supplement.pdf"
    old_pdf.write_text("old", encoding="utf-8")
    new_pdf.write_text("new", encoding="utf-8")
    supplement_pdf.write_text("supplement", encoding="utf-8")
    os.utime(old_pdf, (1_700_000_000, 1_700_000_000))
    os.utime(new_pdf, (1_800_000_000, 1_800_000_000))
    os.utime(supplement_pdf, (1_800_000_100, 1_800_000_100))

    save_tables(
        db_path,
        literatures_df=pd.DataFrame(
            [
                {
                    "id": 1,
                    "uid_literature": "lit-existing",
                    "cite_key": "sci2024demo",
                    "title": "科学学案例研究",
                    "title_norm": "科学学案例研究",
                    "clean_title": "科学学案例研究",
                    "first_author": "研究者甲",
                    "year": "2024",
                    "abstract": "旧摘要（科学学方向）",
                    "keywords": "科学学",
                    "has_fulltext": 1,
                    "primary_attachment_name": "paper.pdf",
                    "pdf_path": str(old_pdf),
                    "created_at": "2026-04-01T00:00:00+00:00",
                    "updated_at": "2026-04-01T00:00:00+00:00",
                }
            ]
        ),
        attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "att-old",
                    "uid_literature": "lit-existing",
                    "attachment_name": "paper.pdf",
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": str(old_pdf),
                    "source_path": str(old_pdf),
                    "checksum": "",
                    "is_primary": 1,
                    "status": "available",
                    "created_at": "2026-04-01T00:00:00+00:00",
                    "updated_at": "2026-04-01T00:00:00+00:00",
                }
            ]
        ),
        tags_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-existing",
                    "cite_key": "sci2024demo",
                    "tag": "历史标签",
                    "tag_norm": "历史标签",
                    "source_type": "seed",
                    "created_at": "2026-04-01T00:00:00+00:00",
                    "updated_at": "2026-04-01T00:00:00+00:00",
                }
            ]
        ),
        if_exists="replace",
    )
    upsert_reading_state_rows(
        db_path,
        [
                {
                    "uid_literature": "lit-existing",
                    "cite_key": "sci2024demo",
                    "pending_preprocess": 0,
                    "preprocessed": 1,
                    "pending_rough_read": 1,
                }
        ],
    )

    merged_literatures_df, merged_attachments_df, merged_tags_df, summary = merge_reference_records(
        existing_literatures_df=load_literatures_df(db_path),
        existing_attachments_df=load_attachments_df(db_path),
        existing_tags_df=load_tags_df(db_path),
        incoming_literatures_df=pd.DataFrame(
            [
                {
                    "id": 1,
                    "uid_literature": "lit-incoming-dup",
                        "cite_key": "sci2024demo",
                        "title": "科学学案例研究",
                        "title_norm": "科学学案例研究",
                        "clean_title": "科学学案例研究",
                        "first_author": "研究者甲",
                        "year": "2024",
                        "abstract": "更新后的更长摘要内容（科学学）",
                        "keywords": "科学学;研究方法",
                    "has_fulltext": 1,
                    "primary_attachment_name": "paper.pdf",
                    "pdf_path": str(new_pdf),
                    "created_at": "2026-04-09T00:00:00+00:00",
                    "updated_at": "2026-04-09T00:00:00+00:00",
                },
                {
                    "id": 2,
                    "uid_literature": "lit-fresh",
                    "cite_key": "li2025fresh",
                    "title": "新增论文（科学学）",
                    "title_norm": "新增论文（科学学）",
                    "clean_title": "新增论文（科学学）",
                    "first_author": "研究者乙",
                    "year": "2025",
                    "abstract": "新增摘要（科学学方向）",
                    "keywords": "新增",
                    "has_fulltext": 0,
                    "primary_attachment_name": "",
                    "pdf_path": "",
                    "created_at": "2026-04-09T00:00:00+00:00",
                    "updated_at": "2026-04-09T00:00:00+00:00",
                },
            ]
        ),
        incoming_attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "att-new-main",
                    "uid_literature": "lit-incoming-dup",
                    "attachment_name": "paper.pdf",
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": str(new_pdf),
                    "source_path": str(new_pdf),
                    "checksum": "",
                    "is_primary": 1,
                    "status": "available",
                    "created_at": "2026-04-09T00:00:00+00:00",
                    "updated_at": "2026-04-09T00:00:00+00:00",
                },
                {
                    "uid_attachment": "att-new-supplement",
                    "uid_literature": "lit-incoming-dup",
                    "attachment_name": "supplement.pdf",
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": str(supplement_pdf),
                    "source_path": str(supplement_pdf),
                    "checksum": "",
                    "is_primary": 0,
                    "status": "available",
                    "created_at": "2026-04-09T00:00:00+00:00",
                    "updated_at": "2026-04-09T00:00:00+00:00",
                },
            ]
        ),
        incoming_tags_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-incoming-dup",
                    "cite_key": "sci2024demo",
                    "tag": "引用分析",
                    "tag_norm": "引用分析",
                    "source_type": "a020",
                    "created_at": "2026-04-09T00:00:00+00:00",
                    "updated_at": "2026-04-09T00:00:00+00:00",
                }
            ]
        ),
    )

    assert summary["matched_existing_count"] == 1
    assert summary["inserted_count"] == 1
    assert set(merged_literatures_df["uid_literature"].tolist()) == {"lit-existing", "lit-fresh"}
    merged_existing = merged_literatures_df[merged_literatures_df["uid_literature"] == "lit-existing"].iloc[0]
    assert merged_existing["abstract"] == "更新后的更长摘要内容（科学学）"
    assert merged_existing["pdf_path"] == str(new_pdf)

    merged_existing_attachments = merged_attachments_df[
        merged_attachments_df["uid_literature"] == "lit-existing"
    ].copy()
    assert set(merged_existing_attachments["attachment_name"].tolist()) == {"paper.pdf", "supplement.pdf"}
    paper_row = merged_existing_attachments[merged_existing_attachments["attachment_name"] == "paper.pdf"].iloc[0]
    assert paper_row["storage_path"] == str(new_pdf)
    assert set(merged_tags_df[merged_tags_df["uid_literature"] == "lit-existing"]["tag"].tolist()) == {"历史标签", "引用分析"}

    replace_reference_tables_only(
        db_path,
        literatures_df=merged_literatures_df,
        attachments_df=merged_attachments_df,
        tags_df=merged_tags_df,
    )

    roundtrip_literatures = load_literatures_df(db_path)
    roundtrip_attachments = load_attachments_df(db_path)
    roundtrip_state = load_reading_state_df(db_path)

    assert set(roundtrip_literatures["uid_literature"].tolist()) == {"lit-existing", "lit-fresh"}
    assert set(roundtrip_attachments[roundtrip_attachments["uid_literature"] == "lit-existing"]["attachment_name"].tolist()) == {"paper.pdf", "supplement.pdf"}
    assert list(roundtrip_state["uid_literature"]) == ["lit-existing"]