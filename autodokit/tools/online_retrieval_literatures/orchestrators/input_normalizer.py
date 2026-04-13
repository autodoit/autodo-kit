"""输入规范化编排组件。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def resolve_path(raw_path: str | Path | None) -> str:
    text = normalize_text(raw_path)
    if not text:
        return ""
    return str(Path(text).expanduser().resolve())


def _guess_title_from_pdf_path(pdf_path: str) -> str:
    if not pdf_path:
        return ""
    return Path(pdf_path).stem


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def derive_content_db_path(payload: dict[str, Any]) -> str:
    explicit = resolve_path(payload.get("content_db") or payload.get("content_db_path"))
    if explicit:
        return explicit
    workspace_root = resolve_path(payload.get("workspace_root"))
    if not workspace_root:
        return ""
    candidate = Path(workspace_root) / "database" / "content" / "content.db"
    return str(candidate.resolve())


def _fetch_literature_rows(content_db_path: str, *, cite_keys: list[str], pdf_paths: list[str]) -> list[dict[str, str]]:
    if not content_db_path:
        return []
    db_path = Path(content_db_path)
    if not db_path.exists():
        return []

    rows: list[dict[str, str]] = []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if cite_keys:
            placeholders = ",".join("?" for _ in cite_keys)
            query = f"""
                SELECT cite_key, title, pdf_path
                FROM literatures
                WHERE cite_key IN ({placeholders})
            """
            for row in cursor.execute(query, cite_keys):
                rows.append(
                    {
                        "cite_key": normalize_text(row["cite_key"]),
                        "title": normalize_text(row["title"]),
                        "pdf_path": normalize_text(row["pdf_path"]),
                    }
                )

        if pdf_paths:
            placeholders = ",".join("?" for _ in pdf_paths)
            query = f"""
                SELECT cite_key, title, pdf_path
                FROM literatures
                WHERE pdf_path IN ({placeholders})
            """
            for row in cursor.execute(query, pdf_paths):
                rows.append(
                    {
                        "cite_key": normalize_text(row["cite_key"]),
                        "title": normalize_text(row["title"]),
                        "pdf_path": normalize_text(row["pdf_path"]),
                    }
                )

    return rows


def _build_seed_pool(payload: dict[str, Any]) -> list[dict[str, str]]:
    seeds: list[dict[str, str]] = []
    for item in list(payload.get("seed_items") or []):
        seed = _safe_dict(item)
        if not seed:
            continue
        seeds.append(
            {
                "cite_key": normalize_text(seed.get("cite_key")),
                "title": normalize_text(seed.get("title")),
                "detail_url": normalize_text(seed.get("detail_url")),
                "pdf_path": resolve_path(seed.get("pdf_path")),
            }
        )

    for cite_key in list(payload.get("cite_keys") or []):
        text = normalize_text(cite_key)
        if text:
            seeds.append({"cite_key": text, "title": "", "detail_url": "", "pdf_path": ""})

    for pdf_path in list(payload.get("pdf_paths") or []):
        text = resolve_path(pdf_path)
        if text:
            seeds.append({"cite_key": "", "title": "", "detail_url": "", "pdf_path": text})

    return seeds


def _merge_seed_with_db_rows(seeds: list[dict[str, str]], db_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_cite: dict[str, dict[str, str]] = {}
    by_pdf: dict[str, dict[str, str]] = {}
    for row in db_rows:
        cite_key = normalize_text(row.get("cite_key"))
        pdf_path = resolve_path(row.get("pdf_path"))
        if cite_key:
            by_cite[cite_key] = row
        if pdf_path:
            by_pdf[pdf_path] = row

    merged: list[dict[str, str]] = []
    for seed in seeds:
        cite_key = normalize_text(seed.get("cite_key"))
        pdf_path = resolve_path(seed.get("pdf_path"))
        hit = by_cite.get(cite_key) if cite_key else by_pdf.get(pdf_path)
        title = normalize_text(seed.get("title"))
        detail_url = normalize_text(seed.get("detail_url"))
        if hit:
            title = title or normalize_text(hit.get("title"))
            pdf_path = pdf_path or resolve_path(hit.get("pdf_path"))
        title = title or _guess_title_from_pdf_path(pdf_path)
        merged.append(
            {
                "cite_key": cite_key,
                "title": title,
                "detail_url": detail_url,
                "pdf_path": pdf_path,
            }
        )
    return merged


def resolve_content_portal_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    direct_entries = list(payload.get("entries") or [])
    if direct_entries:
        return [dict(item) for item in direct_entries if isinstance(item, dict)]

    seeds = _build_seed_pool(payload)
    if not seeds:
        return []

    cite_keys = [item["cite_key"] for item in seeds if item.get("cite_key")]
    pdf_paths = [item["pdf_path"] for item in seeds if item.get("pdf_path")]
    content_db_path = derive_content_db_path(payload)
    db_rows = _fetch_literature_rows(content_db_path, cite_keys=cite_keys, pdf_paths=pdf_paths)
    merged = _merge_seed_with_db_rows(seeds, db_rows)

    entries: list[dict[str, Any]] = []
    for item in merged:
        title = normalize_text(item.get("title"))
        detail_url = normalize_text(item.get("detail_url"))
        if not title and not detail_url:
            continue
        entries.append(
            {
                "enabled": True,
                "title": title,
                "detail_url": detail_url,
                "cite_key": normalize_text(item.get("cite_key")),
                "pdf_path": resolve_path(item.get("pdf_path")),
            }
        )
    return entries


def resolve_content_single_payload(payload: dict[str, Any], *, query_field: str) -> dict[str, Any]:
    merged = dict(payload)
    existing_query = normalize_text(merged.get(query_field))
    existing_detail_url = normalize_text(merged.get("detail_url"))
    if existing_query or existing_detail_url:
        return merged

    entries = resolve_content_portal_entries(payload)
    if not entries:
        return merged

    first = entries[0]
    if not existing_query:
        merged[query_field] = normalize_text(first.get("title"))
    if not existing_detail_url:
        merged["detail_url"] = normalize_text(first.get("detail_url"))
    return merged


def resolve_en_single_record(payload: dict[str, Any]) -> dict[str, Any] | None:
    record_payload = payload.get("record")
    if isinstance(record_payload, dict):
        return dict(record_payload)

    entries = resolve_content_portal_entries(payload)
    if not entries:
        return None

    first = entries[0]
    title = normalize_text(first.get("title")) or _guess_title_from_pdf_path(resolve_path(first.get("pdf_path")))
    return {
        "source": "seed",
        "source_id": normalize_text(first.get("cite_key")),
        "title": title or "untitled",
        "year": "",
        "doi": "",
        "journal": "",
        "authors": [],
        "abstract": "",
        "landing_url": normalize_text(first.get("detail_url")),
        "pdf_url": "",
        "bibtex_key": normalize_text(first.get("cite_key")),
        "raw": {
            "seed_pdf_path": resolve_path(first.get("pdf_path")),
            "seed_cite_key": normalize_text(first.get("cite_key")),
        },
    }


def resolve_en_batch_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    direct = list(payload.get("records") or [])
    if direct:
        return [dict(item) for item in direct if isinstance(item, dict)]

    entries = resolve_content_portal_entries(payload)
    records: list[dict[str, Any]] = []
    for item in entries:
        title = normalize_text(item.get("title")) or _guess_title_from_pdf_path(resolve_path(item.get("pdf_path")))
        if not title and not normalize_text(item.get("detail_url")):
            continue
        records.append(
            {
                "source": "seed",
                "source_id": normalize_text(item.get("cite_key")),
                "title": title or "untitled",
                "year": "",
                "doi": "",
                "journal": "",
                "authors": [],
                "abstract": "",
                "landing_url": normalize_text(item.get("detail_url")),
                "pdf_url": "",
                "bibtex_key": normalize_text(item.get("cite_key")),
                "raw": {
                    "seed_pdf_path": resolve_path(item.get("pdf_path")),
                    "seed_cite_key": normalize_text(item.get("cite_key")),
                },
            }
        )
    return records
