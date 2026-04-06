"""SQLite 文献关系表工具测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from autodokit.tools.bibliodb_sqlite import (
    get_structured_state,
    load_attachments_df,
    load_chunk_sets_df,
    load_chunks_df,
    load_reading_state_df,
    load_tags_df,
    replace_chunk_set_records,
    rebuild_reference_relation_tables_from_config,
    save_structured_state,
    save_tables,
    upsert_reading_queue_rows,
    upsert_reading_state_rows,
)


def test_rebuild_reference_relation_tables_from_config_should_fill_attachment_and_tag_tables(tmp_path: Path) -> None:
    """应能根据主表与配置重建附件关系表和标签关系表。"""

    db_path = tmp_path / "references.db"
    literatures_df = pd.DataFrame(
        [
            {
                "id": 1,
                "uid_literature": "lit-001",
                "cite_key": "lit-001",
                "title": "房地产价格波动与银行系统性风险",
                "abstract": "讨论房价波动和金融稳定",
                "keywords": "房地产;系统性风险",
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
                "tag_list": ["房地产", "系统性风险"],
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
    assert set(tags_df["tag"].tolist()) == {"房地产", "系统性风险"}


def test_structured_state_and_chunk_index_tables_should_roundtrip(tmp_path: Path) -> None:
    """结构化状态字段与 chunk 索引表应能写入并回读。"""

    db_path = tmp_path / "references.db"
    literatures_df = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "wang-2024-demo",
                "title": "Demo Paper",
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
        structured_abs_path=str((tmp_path / "wang-2024-demo.structured.json").resolve()),
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
                "cite_key": "wang-2024-demo",
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
                "cite_key": "wang-2024-demo",
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