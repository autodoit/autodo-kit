"""检索治理事务。"""

from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import sqlite3
import time
from datetime import datetime
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pandas as pd

from autodokit.tools import run_online_retrieval_router
from autodokit.tools import load_json_or_py
from autodokit.tools import bibliodb_sqlite
from autodokit.tools import normalize_primary_fulltext_attachment_names
from autodokit.tools import resolve_primary_attachment_normalization_settings
from autodokit.tools.atomic.task_aok.task_instance_dir import create_task_instance_dir, mirror_artifacts_to_legacy, resolve_legacy_output_dir
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.literature_translation_tools import run_literature_translation
from autodokit.tools.old.bibliodb_csv_compat import build_cite_key, clean_title_text, extract_first_author, generate_uid, parse_year_int

ObjectType = Literal["literature", "dataset"]
SourceType = Literal["offline", "online"]
RegionType = Literal["domestic", "global"]
AccessType = Literal["open", "closed"]
PermissionStatus = Literal["approved", "manual_required", "blocked"]


@dataclass(slots=True, frozen=True)
class RetrievalRequest:
    """检索请求。"""

    request_uid: str
    object_type: ObjectType
    source_type: SourceType
    region_type: RegionType
    access_type: AccessType
    query: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RetrievalBundle:
    """检索 bundle。"""

    bundle_id: str
    object_type: ObjectType
    source_type: SourceType
    file_paths: tuple[str, ...]
    manifest_patch: dict[str, Any]
    permission_status: PermissionStatus
    result_code: str


@dataclass(slots=True)
class RetrievalGovernanceEngine:
    """检索治理引擎。"""

    def process_request(self, request: RetrievalRequest) -> RetrievalBundle:
        """按统一状态机处理检索请求。"""

        permission_status = self.evaluate_permission(request=request)
        result_code: str = "PASS"
        if permission_status in {"manual_required", "blocked"}:
            result_code = "BLOCKED"

        file_paths: tuple[str, ...] = tuple(request.metadata.get("file_paths", []))
        manifest_patch = {
            "request_uid": request.request_uid,
            "query": request.query,
            "object_type": request.object_type,
            "source_type": request.source_type,
            "region_type": request.region_type,
            "access_type": request.access_type,
        }
        return RetrievalBundle(
            bundle_id=f"bundle-{uuid4().hex}",
            object_type=request.object_type,
            source_type=request.source_type,
            file_paths=file_paths,
            manifest_patch=manifest_patch,
            permission_status=permission_status,
            result_code=result_code,
        )

    def evaluate_permission(self, request: RetrievalRequest) -> PermissionStatus:
        """评估授权状态。"""

        if request.access_type == "closed":
            return "manual_required"
        if request.metadata.get("deny", False):
            return "blocked"
        return "approved"


@dataclass(slots=True)
class RetrievalRouter:
    """检索结果路由器。"""

    def route_bundle(self, bundle: RetrievalBundle) -> str:
        """根据 bundle 决定后续流向。"""

        if bundle.result_code == "BLOCKED":
            return "manual_review_queue"
        if bundle.object_type == "literature":
            return "reference_ingestion"
        return "dataset_ingestion"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disable", "disabled"}:
        return False
    return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


_A040_SC_ZH_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass(slots=True)
class _A040SpecialItem:
    uid_literature: str
    cite_key: str
    title: str
    year: str
    doi: str
    landing_url: str


def _a040_sc_safe_name(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", str(name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "unknown_cite_key"


def _a040_sc_is_english_literature(row: sqlite3.Row) -> bool:
    title = str(row["title"] or "")
    language = str(row["language"] or "").lower()
    source_lang = str(row["source_lang"] or "").lower()
    if "en" in language or "english" in language:
        return True
    if source_lang.startswith("en"):
        return True
    if title and not _A040_SC_ZH_RE.search(title):
        return True
    return False


def _a040_sc_coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _a040_sc_parse_cite_keys(payload: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    keys.extend(_a040_sc_coerce_str_list(payload.get("cite_keys")))
    file_text = _normalize_text(payload.get("cite_keys_file"))
    if file_text:
        p = Path(file_text).expanduser().resolve()
        if p.exists() and p.is_file():
            for line in p.read_text(encoding="utf-8-sig").splitlines():
                text = line.strip()
                if text:
                    keys.append(text)
    deduped: list[str] = []
    seen: set[str] = set()
    for key in keys:
        lowered = key.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(key)
    return deduped


def _a040_sc_load_english_items(db_path: Path) -> list[_A040SpecialItem]:
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                lit.uid_literature,
                lit.cite_key,
                lit.title,
                lit.year,
                lit.doi,
                lit.url,
                lit.language,
                lit.source_lang
            FROM literatures AS lit
            WHERE trim(coalesce(lit.cite_key, '')) <> ''
            ORDER BY id ASC
            """
        ).fetchall()

    items: list[_A040SpecialItem] = []
    for row in rows:
        if not _a040_sc_is_english_literature(row):
            continue
        items.append(
            _A040SpecialItem(
                uid_literature=_normalize_text(row["uid_literature"]),
                cite_key=_normalize_text(row["cite_key"]),
                title=_normalize_text(row["title"]),
                year=_normalize_text(row["year"]),
                doi=_normalize_text(row["doi"]),
                landing_url=_normalize_text(row["url"]),
            )
        )
    return items


def _a040_sc_load_items_by_cite_keys(db_path: Path, cite_keys: list[str]) -> list[_A040SpecialItem]:
    if not cite_keys:
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT uid_literature, cite_key, title, year, doi, url
            FROM literatures
            WHERE trim(coalesce(cite_key, '')) <> ''
            """
        ).fetchall()
    row_map = {_normalize_text(row["cite_key"]).lower(): row for row in rows}
    items: list[_A040SpecialItem] = []
    for cite_key in cite_keys:
        row = row_map.get(cite_key.lower())
        if row is None:
            continue
        items.append(
            _A040SpecialItem(
                uid_literature=_normalize_text(row["uid_literature"]),
                cite_key=_normalize_text(row["cite_key"]),
                title=_normalize_text(row["title"]),
                year=_normalize_text(row["year"]),
                doi=_normalize_text(row["doi"]),
                landing_url=_normalize_text(row["url"]),
            )
        )
    return items


def _a040_sc_build_attachment_uid(item: _A040SpecialItem) -> str:
    return f"att-{bibliodb_sqlite.build_stable_attachment_uid(item.uid_literature, attachment_name=f'{item.cite_key}.pdf', fallback_uid=item.cite_key)}"


def _a040_sc_build_attachment_filename(item: _A040SpecialItem, uid_attachment: str, file_ext: str = ".pdf") -> str:
    normalized_ext = file_ext if file_ext.startswith(".") else f".{file_ext}"
    return f"att-{_a040_sc_safe_name(item.cite_key)}-{uid_attachment}{normalized_ext}"


def _a040_sc_pick_saved_path(result: dict[str, Any]) -> str:
    if _normalize_text(result.get("status")) == "PASS":
        direct = _normalize_text(result.get("saved_path"))
        if direct:
            return direct
    inner = result.get("result")
    if isinstance(inner, dict) and _normalize_text(inner.get("status")) == "PASS":
        return _normalize_text(inner.get("saved_path"))
    return ""


def _a040_sc_upsert_download_to_db(
    db_path: Path,
    item: _A040SpecialItem,
    final_pdf_path: Path,
    source_type: str,
    affair_name: str,
    *,
    download_source_path: str,
    uid_attachment: str,
) -> None:
    now = _now_iso()
    literatures_df = bibliodb_sqlite.load_literatures_df(db_path).fillna("")
    attachments_df = bibliodb_sqlite.load_attachments_df(db_path).fillna("")
    tags_df = bibliodb_sqlite.load_tags_df(db_path).fillna("")

    if literatures_df.empty or "uid_literature" not in literatures_df.columns:
        raise ValueError(f"content.db 中缺少目标文献: {item.uid_literature}")
    literature_mask = literatures_df["uid_literature"].astype(str) == item.uid_literature
    if not literature_mask.any():
        raise ValueError(f"content.db 中未找到 uid_literature={item.uid_literature}")

    literatures_df.loc[literature_mask, "has_fulltext"] = 1
    literatures_df.loc[literature_mask, "pdf_path"] = str(final_pdf_path)
    literatures_df.loc[literature_mask, "primary_attachment_name"] = final_pdf_path.name
    literatures_df.loc[literature_mask, "primary_attachment_source_path"] = str(download_source_path or final_pdf_path)
    literatures_df.loc[literature_mask, "updated_at"] = now

    if attachments_df.empty:
        attachments_df = pd.DataFrame(columns=[
            "uid_attachment", "uid_literature", "attachment_name", "attachment_type", "file_ext",
            "storage_path", "source_path", "source_type", "附件来源类型", "来源事务", "checksum",
            "is_primary", "status", "created_at", "updated_at",
        ])

    attachment_type_series = attachments_df.get("attachment_type", pd.Series(dtype=str)).astype(str).str.lower()
    primary_series = pd.to_numeric(attachments_df.get("is_primary", pd.Series(dtype=int)), errors="coerce").fillna(0).astype(int)
    literature_series = attachments_df.get("uid_literature", pd.Series(dtype=str)).astype(str)
    attachments_df = attachments_df.loc[
        ~(
            (literature_series == item.uid_literature)
            & (primary_series == 1)
            & (attachment_type_series.isin(["fulltext", "full_text", "pdf"]))
        )
    ].copy()

    attachments_df = pd.concat(
        [
            attachments_df,
            pd.DataFrame(
                [
                    {
                        "uid_attachment": uid_attachment,
                        "uid_literature": item.uid_literature,
                        "attachment_name": final_pdf_path.name,
                        "attachment_type": "fulltext",
                        "file_ext": final_pdf_path.suffix.lstrip(".").lower() or "pdf",
                        "storage_path": str(final_pdf_path),
                        "source_path": str(download_source_path or final_pdf_path),
                        "source_type": source_type,
                        "附件来源类型": "在线下载附件",
                        "来源事务": affair_name,
                        "checksum": "",
                        "is_primary": 1,
                        "status": "available",
                        "created_at": now,
                        "updated_at": now,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    attachments_df = attachments_df.drop_duplicates(subset=["uid_literature", "uid_attachment"], keep="last").reset_index(drop=True)

    bibliodb_sqlite.replace_reference_tables_only(
        db_path,
        literatures_df=literatures_df,
        attachments_df=attachments_df,
        tags_df=tags_df,
    )


def _run_a040_special_channel(payload: dict[str, Any]) -> dict[str, Any]:
    workspace_root = Path(_normalize_text(payload.get("workspace_root"))).expanduser().resolve()
    if not workspace_root.exists():
        raise FileNotFoundError(f"workspace_root 不存在: {workspace_root}")

    content_db = Path(_normalize_text(payload.get("content_db") or (workspace_root / "database" / "content" / "content.db"))).expanduser().resolve()
    if not content_db.exists():
        raise FileNotFoundError(f"content_db 不存在: {content_db}")

    task_uid = _normalize_text(payload.get("task_uid") or (datetime.now().strftime("%Y%m%d%H%M%S") + "-A040-special-en-download"))
    task_dir = Path(_normalize_text(payload.get("task_dir") or (workspace_root / "tasks" / task_uid))).expanduser().resolve()
    raw_dir = task_dir / "downloads_raw"
    renamed_dir = task_dir / "downloads_renamed"
    report_dir = task_dir / "reports"
    attachments_target_dir = Path(_normalize_text(payload.get("attachments_target_dir") or (workspace_root / "references" / "attachments"))).expanduser().resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)
    renamed_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    attachments_target_dir.mkdir(parents=True, exist_ok=True)

    selected_cite_keys = _a040_sc_parse_cite_keys(payload)
    all_items_raw = _a040_sc_load_items_by_cite_keys(content_db, selected_cite_keys) if selected_cite_keys else _a040_sc_load_english_items(content_db)

    skip_existing = _coerce_bool(payload.get("skip_existing"), True)
    skipped_existing = 0
    all_items: list[_A040SpecialItem] = []
    if skip_existing:
        with sqlite3.connect(str(content_db)) as conn:
            conn.row_factory = sqlite3.Row
            existing_rows = {
                str(row["uid_literature"]): row
                for row in conn.execute(
                    """
                    SELECT lit.uid_literature, lit.has_fulltext, lit.pdf_path, lit.primary_attachment_source_path,
                           EXISTS(
                               SELECT 1 FROM literature_attachment_links AS lnk
                               WHERE lnk.uid_literature = lit.uid_literature
                                 AND CAST(coalesce(lnk.is_primary, 0) AS INTEGER) = 1
                           ) AS has_primary_link
                    FROM literatures AS lit
                    """
                ).fetchall()
            }
        for item in all_items_raw:
            info = existing_rows.get(item.uid_literature)
            if info is None:
                all_items.append(item)
                continue
            if int(info["has_fulltext"] or 0) == 1:
                skipped_existing += 1
                continue
            if bool(_normalize_text(info["pdf_path"])):
                skipped_existing += 1
                continue
            if bool(_normalize_text(info["primary_attachment_source_path"])):
                skipped_existing += 1
                continue
            if int(info["has_primary_link"] or 0) == 1:
                skipped_existing += 1
                continue
            all_items.append(item)
    else:
        all_items = all_items_raw

    offset = max(_coerce_int(payload.get("offset"), 0), 0)
    if offset > 0:
        all_items = all_items[offset:]
    max_items = _coerce_int(payload.get("max_items"), 0)
    items = all_items[:max_items] if max_items > 0 else all_items

    summary: dict[str, Any] = {
        "task_uid": task_uid,
        "started_at": _now_iso(),
        "workspace_root": str(workspace_root),
        "content_db": str(content_db),
        "total_candidates": len(items),
        "selected_cite_keys": selected_cite_keys,
        "skip_existing_enabled": bool(skip_existing),
        "skipped_existing": skipped_existing,
        "success": 0,
        "failed": 0,
        "records": [],
    }

    school_portal_url = _normalize_text(payload.get("school_portal_url"))
    summary_path = report_dir / "summary.json"

    for idx, item in enumerate(items, start=1):
        short_token = hashlib.md5(item.cite_key.encode("utf-8")).hexdigest()[:10]
        per_item_raw_dir = raw_dir / f"i{idx:05d}_{short_token}"
        per_item_raw_dir.mkdir(parents=True, exist_ok=True)

        record = {
            "source": "en_special",
            "source_id": item.cite_key,
            "title": item.title,
            "year": item.year,
            "doi": item.doi,
            "landing_url": item.landing_url,
            "pdf_url": "",
            "bibtex_key": item.cite_key,
            "raw": {},
        }
        single_payload = {
            "source": "en_open_access",
            "mode": "single",
            "action": "download",
            "request_profile": "en",
            "record": record,
            "output_dir": str(per_item_raw_dir),
            "download_request_timeout": _coerce_int(payload.get("download_timeout"), 12),
            "per_record_max_attempts": _coerce_int(payload.get("max_attempts"), 6),
            "min_request_delay_seconds": _coerce_float(payload.get("min_request_delay"), 0.35),
            "max_request_delay_seconds": _coerce_float(payload.get("max_request_delay"), 1.6),
            "enable_barrier_analysis": _coerce_bool(payload.get("enable_barrier_analysis"), False),
            "allow_manual_intervention": _coerce_bool(payload.get("allow_manual_intervention"), False),
            "keep_browser_open": _coerce_bool(payload.get("keep_browser_open"), False),
            "browser_profile_dir": _normalize_text(payload.get("browser_profile_dir")),
            "browser_cdp_port": _coerce_int(payload.get("browser_cdp_port"), 9222),
            "manual_wait_timeout_seconds": _coerce_int(payload.get("manual_wait_timeout_seconds"), 900),
        }
        try:
            single_result = run_online_retrieval_router(single_payload)
        except Exception as exc:  # noqa: BLE001
            single_result = {"status": "BLOCKED", "error_type": exc.__class__.__name__, "error": str(exc)}

        retry_result: dict[str, Any] | None = None
        saved_path = _a040_sc_pick_saved_path(single_result)
        if not saved_path and school_portal_url:
            retry_payload = {
                "source": "en_open_access",
                "mode": "retry",
                "action": "chaoxing_portal",
                "request_profile": "en",
                "failed_records": [record],
                "library_nav_url": school_portal_url,
                "subject_categories": ["经济学", "管理学", "综合"],
                "max_databases_per_record": _coerce_int(payload.get("max_databases_per_record"), 2),
                "output_dir": str(per_item_raw_dir / "portal_retry"),
                "allow_manual_intervention": _coerce_bool(payload.get("allow_manual_intervention"), False),
                "keep_browser_open": _coerce_bool(payload.get("keep_browser_open"), False),
                "browser_profile_dir": _normalize_text(payload.get("browser_profile_dir")),
                "browser_cdp_port": _coerce_int(payload.get("browser_cdp_port"), 9222),
                "manual_wait_timeout_seconds": _coerce_int(payload.get("manual_wait_timeout_seconds"), 900),
            }
            try:
                retry_result = run_online_retrieval_router(retry_payload)
            except Exception as exc:  # noqa: BLE001
                retry_result = {"status": "BLOCKED", "error_type": exc.__class__.__name__, "error": str(exc), "results": []}

            retry_results = list(retry_result.get("results") or [])
            for row in retry_results:
                candidate = dict((dict(row or {})).get("final_result") or {})
                candidate_saved = _a040_sc_pick_saved_path(candidate)
                if candidate_saved:
                    saved_path = candidate_saved
                    break

        item_result: dict[str, Any] = {
            "cite_key": item.cite_key,
            "title": item.title,
            "single_status": single_result.get("status"),
            "saved_path": saved_path,
        }
        if single_result.get("error"):
            item_result["single_error"] = str(single_result.get("error"))
        if retry_result is not None:
            item_result["retry_status"] = "PASS" if saved_path else "NO_PDF"
            if retry_result.get("error"):
                item_result["retry_error"] = str(retry_result.get("error"))

        if saved_path and Path(saved_path).exists():
            uid_attachment = _a040_sc_build_attachment_uid(item)
            target_pdf = attachments_target_dir / _a040_sc_build_attachment_filename(item, uid_attachment)
            shutil.copy2(saved_path, target_pdf)

            mirror_pdf = renamed_dir / target_pdf.name
            if not mirror_pdf.exists():
                shutil.copy2(target_pdf, mirror_pdf)

            _a040_sc_upsert_download_to_db(
                db_path=content_db,
                item=item,
                final_pdf_path=target_pdf,
                source_type="online_retrieval_en_special",
                affair_name="A040_special",
                download_source_path=saved_path,
                uid_attachment=uid_attachment,
            )
            summary["success"] += 1
            item_result["final_pdf"] = str(target_pdf)
            item_result["uid_attachment"] = uid_attachment
        else:
            summary["failed"] += 1

        summary["records"].append(item_result)
        summary["last_processed_index"] = idx
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        if idx < len(items):
            time.sleep(random.uniform(_coerce_float(payload.get("min_inter_item_delay"), 2.8), _coerce_float(payload.get("max_inter_item_delay"), 7.4)))

    summary["ended_at"] = _now_iso()
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    reading_list_arg = _normalize_text(payload.get("reading_list_path"))
    reading_list_path = (report_dir / "待研读文献清单.json") if not reading_list_arg else Path(reading_list_arg)
    if not reading_list_path.is_absolute():
        reading_list_path = (workspace_root / reading_list_path).resolve()
    reading_list_path.parent.mkdir(parents=True, exist_ok=True)
    reading_list_payload = {
        "topic": _normalize_text(payload.get("topic") or "房地产价格波动对银行系统性风险的影响"),
        "generated_at": _now_iso(),
        "task_uid": task_uid,
        "items": [
            {
                "cite_key": row.get("cite_key"),
                "title": row.get("title"),
                "final_pdf": row.get("final_pdf", ""),
                "single_status": row.get("single_status", ""),
                "retry_status": row.get("retry_status", ""),
            }
            for row in summary.get("records", [])
        ],
    }
    reading_list_path.write_text(json.dumps(reading_list_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = report_dir / "success_manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for row in summary["records"]:
            if row.get("final_pdf"):
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary["task_dir"] = str(task_dir)
    summary["summary_path"] = str(summary_path)
    summary["success_manifest_path"] = str(manifest_path)
    summary["reading_list_path"] = str(reading_list_path)
    summary["attachments_target_dir"] = str(attachments_target_dir)
    return summary


def _build_query_terms(raw_cfg: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    query = _normalize_text(raw_cfg.get("query"))
    if query:
        terms.append(query)

    for item in _coerce_list(raw_cfg.get("keyword_list")):
        text = _normalize_text(item)
        if text:
            terms.append(text)

    metadata = dict(raw_cfg.get("metadata") or {})
    for item in _coerce_list(metadata.get("keywords")):
        text = _normalize_text(item)
        if text:
            terms.append(text)

    unique_terms: list[str] = []
    seen: set[str] = set()
    for item in terms:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_terms.append(item)
    return unique_terms


def _resolve_content_db(raw_cfg: dict[str, Any], workspace_root: Path) -> Path:
    configured = _normalize_text(raw_cfg.get("content_db") or ((raw_cfg.get("released_artifacts") or {}).get("content_db") or ""))
    if configured:
        return Path(configured).expanduser().resolve()
    return (workspace_root / "database" / "content" / "content.db").resolve()


def _local_retrieval(
    content_db_path: Path,
    query_terms: list[str],
    *,
    year_start: int,
    year_end: int,
    max_local_hits: int,
) -> dict[str, Any]:
    if not content_db_path.exists():
        return {
            "status": "SKIPPED",
            "reason": "content_db_missing",
            "content_db": str(content_db_path),
            "query_terms": query_terms,
            "hit_count": 0,
            "records": [],
        }
    if not query_terms:
        return {
            "status": "SKIPPED",
            "reason": "empty_query_terms",
            "content_db": str(content_db_path),
            "query_terms": query_terms,
            "hit_count": 0,
            "records": [],
        }

    where_parts: list[str] = []
    params: list[Any] = []
    for term in query_terms:
        token = f"%{term.lower()}%"
        where_parts.append(
            "(" + " OR ".join(
                [
                    "LOWER(COALESCE(title, '')) LIKE ?",
                    "LOWER(COALESCE(abstract, '')) LIKE ?",
                    "LOWER(COALESCE(keywords, '')) LIKE ?",
                    "LOWER(COALESCE(journal, '')) LIKE ?",
                    "LOWER(COALESCE(authors, '')) LIKE ?",
                ]
            ) + ")"
        )
        params.extend([token, token, token, token, token])

    if year_start > 0:
        where_parts.append("CAST(COALESCE(year, 0) AS INTEGER) >= ?")
        params.append(year_start)
    if year_end > 0:
        where_parts.append("CAST(COALESCE(year, 0) AS INTEGER) <= ?")
        params.append(year_end)

    where_sql = " AND ".join(where_parts) if where_parts else "1=1"
    with sqlite3.connect(str(content_db_path)) as conn:
        conn.row_factory = sqlite3.Row
        column_rows = conn.execute("PRAGMA table_info(literatures)").fetchall()
        available_columns = {str(row[1]) for row in column_rows}

        base_columns = [
            "uid_literature",
            "cite_key",
            "title",
            "authors",
            "year",
            "journal",
            "abstract",
            "keywords",
        ]
        select_parts: list[str] = []
        for column_name in base_columns:
            if column_name in available_columns:
                select_parts.append(column_name)
            else:
                select_parts.append(f"'' AS {column_name}")

        for optional_name, fallback in (
            ("source_type", "''"),
            ("detail_url", "''"),
            ("pdf_path", "''"),
            ("has_fulltext", "0"),
        ):
            if optional_name in available_columns:
                select_parts.append(f"COALESCE({optional_name}, {fallback}) AS {optional_name}")
            else:
                select_parts.append(f"{fallback} AS {optional_name}")

        query_sql = (
            f"SELECT {', '.join(select_parts)} "
            "FROM literatures "
            f"WHERE {where_sql} "
            "ORDER BY CAST(COALESCE(year, 0) AS INTEGER) DESC, rowid DESC "
            "LIMIT ?"
        )
        params.append(max(1, max_local_hits))

        records: list[dict[str, Any]] = []
        rows = conn.execute(query_sql, params).fetchall()
        for row in rows:
            records.append(dict(row))

    return {
        "status": "PASS",
        "content_db": str(content_db_path),
        "query_terms": query_terms,
        "hit_count": len(records),
        "records": records,
    }


def _build_seed_items(raw_cfg: dict[str, Any], local_result: dict[str, Any], query_terms: list[str]) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    for item in _coerce_list(raw_cfg.get("seed_items")):
        if isinstance(item, dict):
            seeds.append(dict(item))
        else:
            text = _normalize_text(item)
            if text:
                seeds.append({"title": text})

    local_records = list(local_result.get("records") or [])
    for row in local_records:
        has_fulltext = _coerce_bool(row.get("has_fulltext"), False)
        if has_fulltext:
            continue
        title = _normalize_text(row.get("title"))
        cite_key = _normalize_text(row.get("cite_key"))
        detail_url = _normalize_text(row.get("detail_url"))
        seed_item = {
            "title": title,
            "cite_key": cite_key,
            "detail_url": detail_url,
        }
        if title or cite_key or detail_url:
            seeds.append(seed_item)

    if not seeds:
        for term in query_terms:
            if term:
                seeds.append({"title": term})

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in seeds:
        title = _normalize_text(item.get("title")).lower()
        cite_key = _normalize_text(item.get("cite_key")).lower()
        detail_url = _normalize_text(item.get("detail_url")).lower()
        key = "|".join([title, cite_key, detail_url])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _run_online_metadata(
    raw_cfg: dict[str, Any],
    *,
    query: str,
    query_terms: list[str],
    content_db_path: Path,
    output_dir: Path,
    seed_items: list[dict[str, Any]],
) -> dict[str, Any]:
    online_sources = [str(item).strip() for item in _coerce_list(raw_cfg.get("online_sources") or ["zh_cnki", "en_open_access"]) if str(item).strip()]
    online_max_pages = max(1, _coerce_int(raw_cfg.get("online_max_pages"), 1))
    en_per_page = max(1, _coerce_int(raw_cfg.get("en_per_page"), 20))
    results: dict[str, Any] = {}

    effective_query = query or (query_terms[0] if query_terms else "")
    for source in online_sources:
        if source == "zh_cnki":
            payload = {
                "source": "zh_cnki",
                "mode": "search",
                "action": "metadata",
                "zh_query": effective_query,
                "max_pages": online_max_pages,
                "zh_output_dir": str((output_dir / "online" / "zh_cnki").resolve()),
                "content_db": str(content_db_path),
                "seed_items": seed_items,
            }
            results[source] = run_online_retrieval_router(payload)
            continue

        if source == "en_open_access":
            payload = {
                "source": "en_open_access",
                "mode": "search",
                "action": "metadata",
                "query": effective_query,
                "max_pages": online_max_pages,
                "per_page": en_per_page,
                "output_dir": str((output_dir / "online" / "en_open_access").resolve()),
                "content_db": str(content_db_path),
                "seed_items": seed_items,
            }
            results[source] = run_online_retrieval_router(payload)

    return {
        "status": "PASS" if results else "SKIPPED",
        "query": effective_query,
        "sources": online_sources,
        "results": results,
    }


def _run_online_acquisition(
    raw_cfg: dict[str, Any],
    *,
    content_db_path: Path,
    output_dir: Path,
    seed_items: list[dict[str, Any]],
) -> dict[str, Any]:
    mode = str(raw_cfg.get("online_acquisition_mode") or "none").strip().lower()
    if mode == "none":
        return {"status": "SKIPPED", "mode": mode, "results": {}}

    online_sources = [str(item).strip() for item in _coerce_list(raw_cfg.get("online_sources") or ["zh_cnki", "en_open_access"]) if str(item).strip()]
    results: dict[str, Any] = {}

    for source in online_sources:
        source_results: dict[str, Any] = {}
        if source == "zh_cnki":
            if mode in {"download_pdf", "both"}:
                payload = {
                    "source": "zh_cnki",
                    "mode": "batch",
                    "action": "download",
                    "content_db": str(content_db_path),
                    "seed_items": seed_items,
                    "output_dir": str((output_dir / "acquisition" / "zh_cnki" / "download").resolve()),
                }
                source_results["download_pdf"] = run_online_retrieval_router(payload)
            if mode in {"html_extract", "both"}:
                payload = {
                    "source": "zh_cnki",
                    "mode": "batch",
                    "action": "html_extract",
                    "content_db": str(content_db_path),
                    "seed_items": seed_items,
                    "output_dir": str((output_dir / "acquisition" / "zh_cnki" / "html").resolve()),
                }
                source_results["html_extract"] = run_online_retrieval_router(payload)
            results[source] = source_results
            continue

        if source == "en_open_access":
            if mode in {"download_pdf", "both"}:
                payload = {
                    "source": "en_open_access",
                    "mode": "batch",
                    "action": "download",
                    "content_db": str(content_db_path),
                    "seed_items": seed_items,
                    "output_dir": str((output_dir / "acquisition" / "en_open_access" / "download").resolve()),
                }
                source_results["download_pdf"] = run_online_retrieval_router(payload)
                if _coerce_bool(raw_cfg.get("enable_en_school_portal_retry"), True):
                    failed_records = _extract_en_failed_records(dict(source_results.get("download_pdf") or {}))
                    source_results["download_pdf_retry_chaoxing_portal"] = _run_en_school_portal_retry(
                        raw_cfg,
                        output_dir=output_dir,
                        failed_records=failed_records,
                    )
            if mode in {"html_extract", "both"}:
                payload = {
                    "source": "en_open_access",
                    "mode": "batch",
                    "action": "html_extract",
                    "content_db": str(content_db_path),
                    "seed_items": seed_items,
                    "output_dir": str((output_dir / "acquisition" / "en_open_access" / "html").resolve()),
                }
                source_results["html_extract"] = run_online_retrieval_router(payload)
            results[source] = source_results

    return {
        "status": "PASS" if results else "SKIPPED",
        "mode": mode,
        "results": results,
    }


def _extract_en_failed_records(download_result: dict[str, Any]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for item in list(download_result.get("results") or []):
        item_dict = dict(item or {})
        status = _normalize_text((item_dict.get("result") or {}).get("status") or item_dict.get("status"))
        if status == "PASS":
            continue
        record = dict(item_dict.get("record") or {})
        if not record:
            continue
        title = _normalize_text(record.get("title"))
        doi = _normalize_text(record.get("doi"))
        landing_url = _normalize_text(record.get("landing_url") or record.get("detail_url"))
        if not (title or doi or landing_url):
            continue
        failed.append(record)
    return failed


def _run_en_school_portal_retry(
    raw_cfg: dict[str, Any],
    *,
    output_dir: Path,
    failed_records: list[dict[str, Any]],
) -> dict[str, Any]:
    if not failed_records:
        return {
            "status": "SKIPPED",
            "reason": "no_failed_records",
            "failed_records": 0,
        }

    payload = {
        "source": "en_open_access",
        "mode": "retry",
        "action": "chaoxing_portal",
        "failed_records": failed_records,
        "library_nav_url": _normalize_text(raw_cfg.get("school_library_nav_url") or raw_cfg.get("library_nav_url") or raw_cfg.get("portal_url")),
        "catalog_language": "英文",
        "subject_categories": _coerce_list(raw_cfg.get("school_subject_categories") or raw_cfg.get("subject_categories") or ["经济学", "管理学", "综合"]),
        "require_search_capable": _coerce_bool(raw_cfg.get("school_require_search_capable"), True),
        "max_databases": max(0, _coerce_int(raw_cfg.get("school_max_databases"), 0)),
        "max_databases_per_record": max(1, _coerce_int(raw_cfg.get("school_max_databases_per_record"), 2)),
        "min_portal_retry_delay_seconds": float(raw_cfg.get("min_portal_retry_delay_seconds") or 2.2),
        "max_portal_retry_delay_seconds": float(raw_cfg.get("max_portal_retry_delay_seconds") or 6.8),
        "min_inter_record_delay_seconds": float(raw_cfg.get("min_inter_record_retry_delay_seconds") or 2.7),
        "max_inter_record_delay_seconds": float(raw_cfg.get("max_inter_record_retry_delay_seconds") or 7.9),
        "output_dir": str((output_dir / "acquisition" / "en_open_access" / "chaoxing_portal_retry").resolve()),
    }
    return run_online_retrieval_router(payload)


def _read_json_list(path_text: str) -> list[dict[str, Any]]:
    path = Path(path_text).expanduser().resolve()
    if not path.exists() or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _extract_online_metadata_records(online_result: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    results = dict(online_result.get("results") or {})

    zh = dict(results.get("zh_cnki") or {})
    zh_paths = dict(zh.get("output_paths") or {})
    for row in _read_json_list(str(zh_paths.get("metadata_json") or "")):
        title = _normalize_text(row.get("title"))
        if not title:
            continue
        normalized.append(
            {
                "source": "zh_cnki",
                "title": title,
                "authors": "; ".join([_normalize_text(item) for item in list(row.get("authors") or []) if _normalize_text(item)]),
                "year": _normalize_text(row.get("year")),
                "journal": _normalize_text(row.get("journal")),
                "abstract": _normalize_text(row.get("abstract")),
                "keywords": "; ".join([_normalize_text(item) for item in list(row.get("keywords") or []) if _normalize_text(item)]),
                "detail_url": _normalize_text(row.get("detail_url")),
                "pdf_path": "",
            }
        )

    en = dict(results.get("en_open_access") or {})
    en_paths = dict(en.get("metadata_paths") or {})
    for row in _read_json_list(str(en_paths.get("json") or "")):
        title = _normalize_text(row.get("title"))
        if not title:
            continue
        normalized.append(
            {
                "source": "en_open_access",
                "title": title,
                "authors": "; ".join([_normalize_text(item) for item in list(row.get("authors") or []) if _normalize_text(item)]),
                "year": _normalize_text(row.get("year")),
                "journal": _normalize_text(row.get("journal")),
                "abstract": _normalize_text(row.get("abstract")),
                "keywords": _normalize_text(row.get("keywords")),
                "detail_url": _normalize_text(row.get("landing_url") or row.get("detail_url")),
                "pdf_path": "",
            }
        )

    return normalized


def _apply_download_paths(metadata_records: list[dict[str, Any]], acquisition_result: dict[str, Any]) -> list[dict[str, Any]]:
    records = [dict(item) for item in metadata_records]
    results = dict(acquisition_result.get("results") or {})
    path_by_key: dict[str, str] = {}

    zh = dict(results.get("zh_cnki") or {})
    zh_download = dict(zh.get("download_pdf") or {})
    for item in list(zh_download.get("results") or []):
        item_dict = dict(item or {})
        download = dict(item_dict.get("download") or {})
        record = dict(item_dict.get("record") or {})
        saved_path = _normalize_text(download.get("saved_path") or item_dict.get("saved_path"))
        detail_url = _normalize_text(record.get("detail_url") or item_dict.get("detail_url"))
        title = _normalize_text(record.get("title") or item_dict.get("title"))
        if saved_path:
            if detail_url:
                path_by_key[f"detail:{detail_url.lower()}"] = saved_path
            if title:
                path_by_key[f"title:{title.lower()}"] = saved_path

    en = dict(results.get("en_open_access") or {})
    en_download = dict(en.get("download_pdf") or {})
    for item in list(en_download.get("results") or []):
        item_dict = dict(item or {})
        result = dict(item_dict.get("result") or {})
        record = dict(item_dict.get("record") or {})
        saved_path = _normalize_text(result.get("saved_path") or item_dict.get("saved_path"))
        detail_url = _normalize_text(record.get("landing_url") or record.get("detail_url"))
        title = _normalize_text(record.get("title") or item_dict.get("title"))
        if saved_path:
            if detail_url:
                path_by_key[f"detail:{detail_url.lower()}"] = saved_path
            if title:
                path_by_key[f"title:{title.lower()}"] = saved_path

    en_retry = dict(en.get("download_pdf_retry_chaoxing_portal") or {})
    for item in list(en_retry.get("results") or []):
        item_dict = dict(item or {})
        final_result = dict(item_dict.get("final_result") or {})
        result = dict(final_result.get("result") or {})
        record = dict(final_result.get("record") or item_dict.get("record") or {})
        saved_path = _normalize_text(result.get("saved_path") or final_result.get("saved_path"))
        detail_url = _normalize_text(record.get("landing_url") or record.get("detail_url"))
        title = _normalize_text(record.get("title") or item_dict.get("title"))
        if saved_path:
            if detail_url:
                path_by_key[f"detail:{detail_url.lower()}"] = saved_path
            if title:
                path_by_key[f"title:{title.lower()}"] = saved_path

    for row in records:
        detail_url = _normalize_text(row.get("detail_url")).lower()
        title = _normalize_text(row.get("title")).lower()
        row["pdf_path"] = (
            path_by_key.get(f"detail:{detail_url}")
            or path_by_key.get(f"title:{title}")
            or _normalize_text(row.get("pdf_path"))
        )
    return records


def _dedupe_online_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 detail_url / cite_key / (title, year) 折叠重复在线题录。"""

    if not records:
        return []

    deduped: list[dict[str, Any]] = []
    key_to_index: dict[str, int] = {}

    def _pick_better_text(current: Any, candidate: Any) -> str:
        current_text = _normalize_text(current)
        candidate_text = _normalize_text(candidate)
        if not current_text:
            return candidate_text
        if not candidate_text:
            return current_text
        return candidate_text if len(candidate_text) > len(current_text) else current_text

    for raw_item in records:
        item = dict(raw_item)
        detail_url = _normalize_text(item.get("detail_url")).lower()
        cite_key = _normalize_text(item.get("cite_key")).lower()
        title = _normalize_text(item.get("title")).lower()
        year = _normalize_text(item.get("year"))

        if detail_url:
            dedup_key = f"detail:{detail_url}"
        elif cite_key:
            dedup_key = f"cite:{cite_key}"
        else:
            dedup_key = f"title_year:{title}|{year}"

        existing_index = key_to_index.get(dedup_key)
        if existing_index is None:
            key_to_index[dedup_key] = len(deduped)
            deduped.append(item)
            continue

        existing = deduped[existing_index]
        for field_name in ("title", "authors", "journal", "abstract", "keywords", "source", "detail_url", "year"):
            existing[field_name] = _pick_better_text(existing.get(field_name), item.get(field_name))

        existing_pdf = _normalize_text(existing.get("pdf_path"))
        candidate_pdf = _normalize_text(item.get("pdf_path"))
        if (not existing_pdf) and candidate_pdf:
            existing["pdf_path"] = candidate_pdf

    return deduped


def _normalize_source_slug(value: Any) -> str:
    text = _normalize_text(value).lower()
    if not text:
        return ""
    text = re.sub(r"[^0-9a-z]+", "_", text)
    return text.strip("_")


def _infer_online_literature_source_type(item: dict[str, Any]) -> str:
    source_slug = _normalize_source_slug(item.get("source") or item.get("source_type"))
    detail_url = _normalize_text(item.get("detail_url") or item.get("landing_url")).lower()
    if source_slug in {"zh_cnki", "cnki"} or "cnki" in detail_url:
        return "online_retrieval.zh_cnki"
    if source_slug:
        return f"online_retrieval.en_open_access.{source_slug}"
    return "online_retrieval"


def _infer_attachment_source_label(literature_source_type: str) -> str:
    if literature_source_type == "online_retrieval.zh_cnki":
        return "在线中文下载附件"
    if literature_source_type.startswith("online_retrieval.en_open_access"):
        return "在线英文开放获取下载附件"
    return "在线下载附件"


def _build_online_literatures_df(records: list[dict[str, Any]]) -> pd.DataFrame:
    now_text = _now_iso()
    rows: list[dict[str, Any]] = []
    for item in records:
        title = _normalize_text(item.get("title"))
        if not title:
            continue
        authors = _normalize_text(item.get("authors"))
        year_raw = _normalize_text(item.get("year"))
        year_int = parse_year_int(year_raw)
        year_text = str(year_int) if year_int is not None else year_raw
        first_author = extract_first_author(authors)
        clean_title = clean_title_text(title)
        detail_url = _normalize_text(item.get("detail_url") or item.get("landing_url"))
        pdf_path = _normalize_text(item.get("pdf_path"))
        literature_source_type = _infer_online_literature_source_type(item)
        cite_key = _normalize_text(item.get("cite_key")) or build_cite_key(first_author, year_text, clean_title)
        rows.append(
            {
                "uid_literature": generate_uid(first_author, year_int, clean_title),
                "cite_key": cite_key,
                "title": title,
                "clean_title": clean_title,
                "title_norm": clean_title,
                "authors": authors,
                "first_author": first_author,
                "year": year_text,
                "entry_type": _normalize_text(item.get("entry_type")) or "article",
                "abstract": _normalize_text(item.get("abstract")),
                "keywords": _normalize_text(item.get("keywords")),
                "journal": _normalize_text(item.get("journal")),
                "detail_url": detail_url,
                "landing_url": _normalize_text(item.get("landing_url")),
                "pdf_path": pdf_path,
                "has_fulltext": 1 if pdf_path else 0,
                "primary_attachment_name": Path(pdf_path).name if pdf_path else "",
                "primary_attachment_source_path": detail_url or pdf_path,
                "source_type": literature_source_type,
                "is_placeholder": 0,
                "created_at": now_text,
                "updated_at": now_text,
                "imported_at": now_text,
            }
        )
    return pd.DataFrame(rows)


def _build_online_attachments_df(literatures_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in literatures_df.iterrows():
        pdf_path = _normalize_text(row.get("pdf_path"))
        uid_literature = _normalize_text(row.get("uid_literature"))
        if not pdf_path or not uid_literature:
            continue
        literature_source_type = _normalize_text(row.get("source_type")) or "online_retrieval"
        source_ref = _normalize_text(row.get("detail_url") or row.get("landing_url") or row.get("primary_attachment_source_path") or pdf_path)
        rows.append(
            {
                "uid_attachment": bibliodb_sqlite.build_stable_attachment_uid(
                    uid_literature,
                    source_path=source_ref,
                    attachment_name=_normalize_text(row.get("primary_attachment_name")) or Path(pdf_path).name,
                    storage_path=pdf_path,
                ),
                "uid_literature": uid_literature,
                "attachment_name": _normalize_text(row.get("primary_attachment_name")) or Path(pdf_path).name,
                "attachment_type": "fulltext",
                "file_ext": Path(pdf_path).suffix.lower().lstrip("."),
                "storage_path": pdf_path,
                "source_path": source_ref,
                "source_type": f"{literature_source_type}.attachment",
                "附件来源类型": _infer_attachment_source_label(literature_source_type),
                "来源事务": "A040",
                "checksum": "",
                "is_primary": 1,
                "status": "available",
                "created_at": _normalize_text(row.get("created_at")) or _now_iso(),
                "updated_at": _normalize_text(row.get("updated_at")) or _now_iso(),
            }
        )
    return pd.DataFrame(rows)


def _upsert_literatures(content_db_path: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    records = _dedupe_online_records(records)
    if not records:
        return {"status": "SKIPPED", "inserted": 0, "updated": 0, "records": 0}
    if not content_db_path.exists():
        return {"status": "BLOCKED", "reason": "content_db_missing", "inserted": 0, "updated": 0, "records": len(records)}

    incoming_literatures_df = _build_online_literatures_df(records)
    incoming_attachments_df = _build_online_attachments_df(incoming_literatures_df)
    existing_literatures_df = bibliodb_sqlite.load_literatures_df(content_db_path)
    existing_attachments_df = bibliodb_sqlite.load_attachments_df(content_db_path)
    existing_tags_df = bibliodb_sqlite.load_tags_df(content_db_path)
    merged_literatures_df, merged_attachments_df, merged_tags_df, merge_summary = bibliodb_sqlite.merge_reference_records(
        existing_literatures_df=existing_literatures_df,
        existing_attachments_df=existing_attachments_df,
        existing_tags_df=existing_tags_df,
        incoming_literatures_df=incoming_literatures_df,
        incoming_attachments_df=incoming_attachments_df,
        incoming_tags_df=pd.DataFrame(),
    )
    bibliodb_sqlite.replace_reference_tables_only(
        content_db_path,
        literatures_df=merged_literatures_df,
        attachments_df=merged_attachments_df,
        tags_df=merged_tags_df,
    )

    return {
        "status": "PASS",
        "inserted": int(merge_summary.get("inserted_count") or 0),
        "updated": int(merge_summary.get("matched_existing_count") or 0),
        "records": len(records),
        "attachment_records": int(len(incoming_attachments_df)),
    }


def _build_gate_review(
    *,
    local_hit_count: int,
    online_record_count: int,
    acquisition_mode: str,
    upsert_summary: dict[str, Any],
    online_triggered: bool,
) -> dict[str, Any]:
    total_effective = local_hit_count + online_record_count
    gate_action = "pass_next" if total_effective > 0 else "fallback_current"
    return {
        "node_code": "A040",
        "node_name": "文献检索与入库",
        "gate_code": "G040",
        "gate_action": gate_action,
        "summary": "A040 三阶段检索执行完成" if total_effective > 0 else "A040 命中不足，建议回流 A030/A040 继续补检",
        "checks": {
            "local_hit_count": local_hit_count,
            "online_triggered": online_triggered,
            "online_record_count": online_record_count,
            "online_acquisition_mode": acquisition_mode,
            "upsert_status": _normalize_text(upsert_summary.get("status")),
            "upsert_inserted": _coerce_int(upsert_summary.get("inserted"), 0),
            "upsert_updated": _coerce_int(upsert_summary.get("updated"), 0),
        },
    }


def default_retrieval_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """默认检索处理器。"""

    request = RetrievalRequest(
        request_uid=str(payload.get("request_uid") or f"request-{uuid4().hex}"),
        object_type=payload.get("object_type", "literature"),
        source_type=payload.get("source_type", "online"),
        region_type=payload.get("region_type", "global"),
        access_type=payload.get("access_type", "open"),
        query=str(payload.get("query") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )
    engine = RetrievalGovernanceEngine()
    router = RetrievalRouter()
    bundle = engine.process_request(request=request)
    return {
        "bundle": asdict(bundle),
        "next_node": router.route_bundle(bundle=bundle),
    }


@affair_auto_git_commit("A040")
def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    workspace_root = Path(str(raw_cfg.get("workspace_root") or config_path.parents[2]))
    if not workspace_root.is_absolute():
        raise ValueError(f"workspace_root 必须为绝对路径: {workspace_root}")
    content_db_path = _resolve_content_db(raw_cfg, workspace_root)

    governance_result = default_retrieval_handler(
        {
            "request_uid": str(raw_cfg.get("request_uid") or f"request-{uuid4().hex}"),
            "query": str(raw_cfg.get("query") or ""),
            "object_type": raw_cfg.get("object_type", "literature"),
            "source_type": raw_cfg.get("source_type", "online"),
            "region_type": raw_cfg.get("region_type", "global"),
            "access_type": raw_cfg.get("access_type", "open"),
            "metadata": dict(raw_cfg.get("metadata") or {}),
        }
    )

    legacy_output_dir = resolve_legacy_output_dir(raw_cfg, config_path)
    output_dir = create_task_instance_dir(workspace_root, "A040")

    # A040 特殊渠道分支：开放源批量 -> 学校门户重试 -> 人工清单。
    special_mode = _normalize_text(raw_cfg.get("special_channel_mode") or "none").lower()
    special_enabled = _coerce_bool(raw_cfg.get("enable_special_channel"), False)
    if special_enabled and special_mode in {"en_special_download", "en_open_access_special"}:
        special_payload = {
            **dict(raw_cfg.get("special_channel") or {}),
            "workspace_root": str(workspace_root),
            "content_db": str(content_db_path),
            "task_uid": output_dir.name,
            "task_dir": str(output_dir),
            "attachments_target_dir": _normalize_text(raw_cfg.get("attachments_target_dir")) or str((workspace_root / "references" / "attachments").resolve()),
            "school_portal_url": _normalize_text(raw_cfg.get("school_library_nav_url") or raw_cfg.get("library_nav_url") or raw_cfg.get("portal_url")),
            "topic": _normalize_text(raw_cfg.get("query") or "房地产价格波动对银行系统性风险的影响"),
            "skip_existing": _coerce_bool((raw_cfg.get("special_channel") or {}).get("skip_existing"), True),
        }
        special_result = _run_a040_special_channel(special_payload)
        gate_review = {
            "node_code": "A040",
            "node_name": "文献检索与入库",
            "gate_code": "G040",
            "gate_action": "pass_next" if int(special_result.get("success") or 0) > 0 else "fallback_current",
            "summary": "A040 特殊渠道执行完成",
            "checks": {
                "special_channel_mode": special_mode,
                "success": int(special_result.get("success") or 0),
                "failed": int(special_result.get("failed") or 0),
                "total_candidates": int(special_result.get("total_candidates") or 0),
            },
        }
        result = {
            "status": "PASS",
            "governance": governance_result,
            "mode": "special_channel",
            "special_channel": special_result,
            "gate_review": gate_review,
        }
        out_path = output_dir / "retrieval_governance_result.json"
        gate_path = output_dir / "gate_review.json"
        readable_path = output_dir / "retrieval_readable.md"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
        readable_path.write_text(
            "\n".join(
                [
                    "# A040 检索执行摘要",
                    "",
                    "- mode: special_channel",
                    f"- success: {special_result.get('success', 0)}",
                    f"- failed: {special_result.get('failed', 0)}",
                    f"- total_candidates: {special_result.get('total_candidates', 0)}",
                    f"- task_dir: {special_result.get('task_dir', '')}",
                    f"- gate_action: {gate_review.get('gate_action', 'fallback_current')}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        written_files: list[Path] = [out_path, gate_path, readable_path]
        mirror_artifacts_to_legacy(written_files, legacy_output_dir, output_dir)
        return written_files

    query_terms = _build_query_terms(raw_cfg)
    query_text = _normalize_text(raw_cfg.get("query") or (query_terms[0] if query_terms else ""))
    year_start = _coerce_int(raw_cfg.get("year_start"), 0)
    year_end = _coerce_int(raw_cfg.get("year_end"), 0)
    max_local_hits = max(1, _coerce_int(raw_cfg.get("max_local_hits"), 300))
    local_hit_threshold = max(0, _coerce_int(raw_cfg.get("local_hit_threshold"), 20))

    enable_local_retrieval = _coerce_bool(raw_cfg.get("enable_local_retrieval"), True)
    enable_online_retrieval = _coerce_bool(raw_cfg.get("enable_online_retrieval"), False)
    online_trigger_policy = _normalize_text(raw_cfg.get("online_trigger_policy") or "gap_only").lower()
    online_acquisition_mode = _normalize_text(raw_cfg.get("online_acquisition_mode") or "none").lower()

    local_result = {
        "status": "SKIPPED",
        "reason": "local_retrieval_disabled",
        "hit_count": 0,
        "records": [],
    }
    if enable_local_retrieval:
        local_result = _local_retrieval(
            content_db_path,
            query_terms,
            year_start=year_start,
            year_end=year_end,
            max_local_hits=max_local_hits,
        )

    local_hit_count = _coerce_int(local_result.get("hit_count"), 0)
    gap_count = max(0, local_hit_threshold - local_hit_count)
    gap_result = {
        "status": "PASS",
        "local_hit_count": local_hit_count,
        "local_hit_threshold": local_hit_threshold,
        "gap_count": gap_count,
        "should_online_fallback": gap_count > 0,
    }

    seed_items = _build_seed_items(raw_cfg, local_result, query_terms)

    online_triggered = False
    if enable_online_retrieval:
        if online_trigger_policy == "always":
            online_triggered = True
        elif online_trigger_policy == "manual_seed_only":
            online_triggered = bool(seed_items)
        else:
            online_triggered = gap_count > 0

    online_retrieval_result = {
        "status": "SKIPPED",
        "reason": "online_retrieval_disabled_or_not_triggered",
        "results": {},
    }
    if online_triggered:
        online_retrieval_result = _run_online_metadata(
            raw_cfg,
            query=query_text,
            query_terms=query_terms,
            content_db_path=content_db_path,
            output_dir=output_dir,
            seed_items=seed_items,
        )

    online_acquisition_result = {
        "status": "SKIPPED",
        "reason": "online_acquisition_disabled",
        "mode": online_acquisition_mode,
        "results": {},
    }
    if online_acquisition_mode != "none" and (online_triggered or seed_items):
        online_acquisition_result = _run_online_acquisition(
            raw_cfg,
            content_db_path=content_db_path,
            output_dir=output_dir,
            seed_items=seed_items,
        )

    online_records = _extract_online_metadata_records(online_retrieval_result)
    online_records = _apply_download_paths(online_records, online_acquisition_result)
    upsert_summary = _upsert_literatures(content_db_path, online_records)
    normalization_settings = resolve_primary_attachment_normalization_settings(raw_cfg, workspace_root=workspace_root)
    attachment_normalization_summary = {
        "status": "SKIPPED",
        "reason": "disabled",
        "audit_path": "",
    }
    if normalization_settings.get("enabled"):
        attachment_normalization_summary = normalize_primary_fulltext_attachment_names(
            {
                "content_db": str(content_db_path),
                "workspace_root": str(workspace_root),
                "output_dir": str(output_dir),
                **normalization_settings,
            }
        )

    merged_result = {
        "status": "PASS",
        "content_db": str(content_db_path),
        "query": query_text,
        "query_terms": query_terms,
        "local_hit_count": local_hit_count,
        "online_record_count": len(online_records),
        "total_record_count": local_hit_count + len(online_records),
        "upsert_summary": upsert_summary,
        "attachment_normalization": attachment_normalization_summary,
    }

    gate_review = _build_gate_review(
        local_hit_count=local_hit_count,
        online_record_count=len(online_records),
        acquisition_mode=online_acquisition_mode,
        upsert_summary=upsert_summary,
        online_triggered=online_triggered,
    )

    result = {
        "status": "PASS",
        "governance": governance_result,
        "stage_local_retrieval": local_result,
        "stage_gap_analysis": gap_result,
        "stage_online_retrieval": online_retrieval_result,
        "stage_online_acquisition": online_acquisition_result,
        "stage_merge_and_upsert": merged_result,
        "gate_review": gate_review,
    }

    out_path = output_dir / "retrieval_governance_result.json"
    local_hits_path = output_dir / "local_hits.json"
    gap_path = output_dir / "gap_analysis.json"
    online_retrieval_path = output_dir / "online_retrieval_result.json"
    online_acquisition_path = output_dir / "online_acquisition_result.json"
    merged_path = output_dir / "merged_retrieval_result.json"
    gate_path = output_dir / "gate_review.json"
    readable_path = output_dir / "retrieval_readable.md"

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    local_hits_path.write_text(json.dumps(local_result, ensure_ascii=False, indent=2), encoding="utf-8")
    gap_path.write_text(json.dumps(gap_result, ensure_ascii=False, indent=2), encoding="utf-8")
    online_retrieval_path.write_text(json.dumps(online_retrieval_result, ensure_ascii=False, indent=2), encoding="utf-8")
    online_acquisition_path.write_text(json.dumps(online_acquisition_result, ensure_ascii=False, indent=2), encoding="utf-8")
    merged_path.write_text(json.dumps(merged_result, ensure_ascii=False, indent=2), encoding="utf-8")
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    readable_lines = [
        "# A040 检索执行摘要",
        "",
        f"- query: {query_text}",
        f"- local_hit_count: {local_hit_count}",
        f"- local_hit_threshold: {local_hit_threshold}",
        f"- online_triggered: {online_triggered}",
        f"- online_record_count: {len(online_records)}",
        f"- online_acquisition_mode: {online_acquisition_mode}",
        f"- upsert_inserted: {upsert_summary.get('inserted', 0)}",
        f"- upsert_updated: {upsert_summary.get('updated', 0)}",
        f"- attachment_normalization_status: {attachment_normalization_summary.get('status', 'SKIPPED')}",
        f"- attachment_normalization_renamed_count: {attachment_normalization_summary.get('renamed_count', 0)}",
        f"- gate_action: {gate_review.get('gate_action', 'pass_next')}",
    ]
    readable_path.write_text("\n".join(readable_lines) + "\n", encoding="utf-8")

    written_files: list[Path] = [
        out_path,
        local_hits_path,
        gap_path,
        online_retrieval_path,
        online_acquisition_path,
        merged_path,
        gate_path,
        readable_path,
    ]
    normalization_audit_path = Path(str(attachment_normalization_summary.get("audit_path") or "").strip())
    if normalization_audit_path.exists() and normalization_audit_path.is_file():
        written_files.append(normalization_audit_path)

    translation_policy = dict(raw_cfg.get("translation_policy") or {})
    if str(content_db_path) and translation_policy:
        try:
            translation_result = run_literature_translation(
                content_db=str(content_db_path),
                translation_scope="metadata",
                translation_policy=translation_policy,
                workspace_root=str(raw_cfg.get("workspace_root") or "").strip() or None,
                max_items=int(raw_cfg.get("translation_max_items") or 0),
                affair_name="A040",
                config_path=config_path,
            )
            result["metadata_translation"] = translation_result
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            audit_path = Path(str(translation_result.get("audit_path") or "").strip())
            if audit_path.exists() and audit_path.is_file():
                written_files.append(audit_path)
        except Exception as exc:
            result["metadata_translation"] = {"status": "FAIL", "error": str(exc)}
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    mirror_artifacts_to_legacy(written_files, legacy_output_dir, output_dir)
    try:
        bibliodb_sqlite.upsert_workspace_node_state_rows(
            content_db_path,
            [
                {
                    "node_code": "A040",
                    "node_name": "文献检索与入库",
                    "pending_run": 0,
                    "in_progress": 0,
                    "completed": 1,
                    "gate_status": str(gate_review.get("gate_action") or "pass_next"),
                    "summary": "A040 三阶段检索执行完成",
                    "next_node_code": "A050",
                    "failure_reason": "",
                    "retry_count": 0,
                }
            ],
        )
    except Exception:
        pass
    return written_files
