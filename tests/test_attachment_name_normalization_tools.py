from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from autodokit.affairs.导入和预处理文献元数据.affair import execute as execute_a020
from autodokit.affairs.检索治理.affair import execute as execute_a040
from autodokit.tools import build_stable_attachment_uid
from autodokit.tools import normalize_primary_fulltext_attachment_names
from autodokit.tools.bibliodb_sqlite import load_attachments_df
from autodokit.tools.bibliodb_sqlite import load_literatures_df
from autodokit.tools.bibliodb_sqlite import load_parse_assets_df
from autodokit.tools.bibliodb_sqlite import save_tables
from autodokit.tools.bibliodb_sqlite import upsert_parse_asset_rows
from autodokit.tools.contentdb_sqlite import init_content_db


def test_attachment_name_normalization_preview_should_report_target_without_changing_disk(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    attachments_root = workspace_root / "references" / "attachments"
    attachments_root.mkdir(parents=True, exist_ok=True)
    content_db = workspace_root / "database" / "content" / "content.db"
    init_content_db(content_db)

    pdf_path = attachments_root / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-preview")

    save_tables(
        content_db,
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-001",
                    "cite_key": "demo-001",
                    "title": "Demo",
                    "pdf_path": str(pdf_path),
                    "primary_attachment_name": pdf_path.name,
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "legacy-att",
                    "uid_literature": "lit-001",
                    "attachment_name": pdf_path.name,
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": str(pdf_path),
                    "source_path": str(pdf_path),
                    "checksum": "checksum-preview",
                    "is_primary": 1,
                    "status": "available",
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        if_exists="replace",
    )

    result = normalize_primary_fulltext_attachment_names(
        {
            "content_db": str(content_db),
            "workspace_root": str(workspace_root),
            "rename_mode": "preview",
        }
    )

    expected_uid = build_stable_attachment_uid(
        "lit-001",
        checksum="checksum-preview",
        source_path=str(pdf_path),
        attachment_name="paper.pdf",
        storage_path=str(pdf_path),
        fallback_uid="legacy-att",
    )
    assert result["status"] == "PASS"
    assert result["renamed_count"] == 0
    assert result["candidate_count"] == 1
    assert pdf_path.exists()
    assert result["preview_rows"][0]["target_name"] == f"demo-001-{expected_uid}.pdf"

    attachments_df = load_attachments_df(content_db)
    assert attachments_df.iloc[0]["attachment_name"] == "paper.pdf"


def test_attachment_name_normalization_apply_should_rename_file_and_update_db(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    attachments_root = workspace_root / "references" / "attachments"
    attachments_root.mkdir(parents=True, exist_ok=True)
    content_db = workspace_root / "database" / "content" / "content.db"
    init_content_db(content_db)

    pdf_path = attachments_root / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-apply")

    save_tables(
        content_db,
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-001",
                    "cite_key": "demo-001",
                    "title": "Demo",
                    "pdf_path": str(pdf_path),
                    "primary_attachment_name": pdf_path.name,
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "legacy-att",
                    "uid_literature": "lit-001",
                    "attachment_name": pdf_path.name,
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": str(pdf_path),
                    "source_path": str(pdf_path),
                    "checksum": "checksum-apply",
                    "is_primary": 1,
                    "status": "available",
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        if_exists="replace",
    )
    upsert_parse_asset_rows(
        content_db,
        [
            {
                "asset_uid": "asset-001",
                "uid_literature": "lit-001",
                "cite_key": "demo-001",
                "uid_attachment": "legacy-att",
                "parse_level": "monkeyocr_full",
                "backend": "monkeyocr_windows",
                "normalized_structured_path": str((workspace_root / "references" / "structured" / "normalized.structured.json").resolve()),
                "parse_status": "ready",
            }
        ],
    )

    result = normalize_primary_fulltext_attachment_names(
        {
            "content_db": str(content_db),
            "workspace_root": str(workspace_root),
            "rename_mode": "apply",
        }
    )

    expected_uid = build_stable_attachment_uid(
        "lit-001",
        checksum="checksum-apply",
        source_path=str(pdf_path),
        attachment_name="paper.pdf",
        storage_path=str(pdf_path),
        fallback_uid="legacy-att",
    )
    expected_name = f"demo-001-{expected_uid}.pdf"
    expected_path = attachments_root / expected_name

    assert result["status"] == "PASS"
    assert result["renamed_count"] == 1
    assert expected_path.exists()
    assert not pdf_path.exists()

    literatures_df = load_literatures_df(content_db)
    attachments_df = load_attachments_df(content_db)
    parse_assets_df = load_parse_assets_df(content_db)

    assert literatures_df.iloc[0]["primary_attachment_name"] == expected_name
    assert literatures_df.iloc[0]["pdf_path"] == str(expected_path)
    assert attachments_df.iloc[0]["uid_attachment"] == expected_uid
    assert attachments_df.iloc[0]["attachment_name"] == expected_name
    assert attachments_df.iloc[0]["storage_path"] == str(expected_path)
    assert attachments_df.iloc[0]["source_path"] == str(pdf_path)
    assert parse_assets_df.iloc[0]["uid_attachment"] == expected_uid


def test_a020_should_call_attachment_name_normalization_tool_when_enabled(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    content_db = workspace_root / "database" / "content" / "content.db"
    config_path = tmp_path / "A020.json"
    origin_root = tmp_path / "origin"
    origin_root.mkdir(parents=True, exist_ok=True)
    attachments_root = origin_root / "attachments"
    attachments_root.mkdir(parents=True, exist_ok=True)
    pdf_path = attachments_root / "Primary Paper.pdf"
    pdf_path.write_bytes(b"%PDF-a020")
    bib_path = origin_root / "library.bib"
    bib_path.write_text(
        """
@article{paper1,
  title={Primary Paper},
  author={Zhang San},
  year={2024}
}
        """.strip(),
        encoding="utf-8",
    )

    config_path.write_text(
        json.dumps(
            {
                "workspace_root": str(workspace_root),
                "storage_backend": "sqlite",
                "sqlite_db_path": str(content_db),
                "bibtex_path": "references/bib/library.bib",
                "origin_bib_paths": [str(bib_path)],
                "origin_attachments_root": str(attachments_root),
                "pdf_dir": str(workspace_root / "references" / "attachments"),
                "primary_attachment_normalization": {
                    "enabled": True,
                    "rename_mode": "apply",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    outputs = execute_a020(config_path)

    attachments_df = load_attachments_df(content_db)
    literatures_df = load_literatures_df(content_db)
    cite_key = str(literatures_df.iloc[0]["cite_key"])
    uid_attachment = str(attachments_df.iloc[0]["uid_attachment"])
    expected_name = f"{cite_key}-{uid_attachment}.pdf"

    assert attachments_df.iloc[0]["attachment_name"] == expected_name
    assert literatures_df.iloc[0]["primary_attachment_name"] == expected_name
    assert any(path.name == "primary_attachment_name_normalization.json" for path in outputs)


def test_a040_should_call_attachment_name_normalization_tool_when_enabled(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    attachments_root = workspace_root / "references" / "attachments"
    attachments_root.mkdir(parents=True, exist_ok=True)
    content_db = workspace_root / "database" / "content" / "content.db"
    init_content_db(content_db)
    pdf_path = attachments_root / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-a040")

    save_tables(
        content_db,
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-001",
                    "cite_key": "demo-001",
                    "title": "Demo Paper",
                    "authors": "Zhang San",
                    "year": "2024",
                    "journal": "Demo Journal",
                    "abstract": "Demo abstract",
                    "keywords": "demo",
                    "detail_url": "",
                    "pdf_path": str(pdf_path),
                    "primary_attachment_name": pdf_path.name,
                    "has_fulltext": 1,
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        attachments_df=pd.DataFrame(
            [
                {
                    "uid_attachment": "legacy-a040",
                    "uid_literature": "lit-001",
                    "attachment_name": pdf_path.name,
                    "attachment_type": "fulltext",
                    "file_ext": "pdf",
                    "storage_path": str(pdf_path),
                    "source_path": str(pdf_path),
                    "checksum": "checksum-a040",
                    "is_primary": 1,
                    "status": "available",
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        ),
        if_exists="replace",
    )

    config_path = tmp_path / "A040.json"
    config_path.write_text(
        json.dumps(
            {
                "workspace_root": str(workspace_root),
                "query": "Demo Paper",
                "enable_local_retrieval": True,
                "enable_online_retrieval": False,
                "online_trigger_policy": "gap_only",
                "online_acquisition_mode": "none",
                "primary_attachment_normalization": {
                    "enabled": True,
                    "rename_mode": "apply",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    outputs = execute_a040(config_path)

    attachments_df = load_attachments_df(content_db)
    literatures_df = load_literatures_df(content_db)
    cite_key = str(literatures_df.iloc[0]["cite_key"])
    uid_attachment = str(attachments_df.iloc[0]["uid_attachment"])
    expected_name = f"{cite_key}-{uid_attachment}.pdf"

    assert attachments_df.iloc[0]["attachment_name"] == expected_name
    assert literatures_df.iloc[0]["primary_attachment_name"] == expected_name
    assert any(path.name == "primary_attachment_name_normalization.json" for path in outputs)