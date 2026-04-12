"""文献主附件规范化命名工具。"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from autodokit.tools import bibliodb_sqlite
from autodokit.tools.time_utils import now_iso


DEFAULT_PRIMARY_ATTACHMENT_NORMALIZATION_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "rename_mode": "apply",
    "allowed_attachment_types": ["fulltext", "pdf"],
    "update_parse_assets": True,
    "filename_style": "readable_uid",
    "readable_name_max_length": 64,
}


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = _stringify(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on", "enabled", "enable"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled", "disable"}:
        return False
    return default


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def _coerce_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sanitize_filename_component(text: str) -> str:
    value = _stringify(text)
    if not value:
        return "untitled"
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = value.replace(" ", "_")
    value = re.sub(r"_+", "_", value)
    return value or "untitled"


def _truncate_filename_component(text: str, max_length: int) -> str:
    if max_length <= 0:
        return text
    truncated = text[:max_length].rstrip("._-")
    return truncated or text[:max_length] or "untitled"


def _looks_like_generated_attachment_stem(text: str) -> bool:
    normalized = _stringify(text).strip().lower()
    if not normalized:
        return False
    return re.fullmatch(r"(?:att-)?[a-f0-9]{16,}", normalized) is not None


def _select_readable_attachment_stem(attachment_row: dict[str, Any], current_path: Path) -> str:
    candidates = [
        Path(_stringify(attachment_row.get("source_path"))).stem,
        Path(_stringify(attachment_row.get("attachment_name"))).stem,
        current_path.stem,
    ]
    fallback = ""
    for candidate in candidates:
        sanitized = _sanitize_filename_component(candidate)
        if sanitized and not fallback:
            fallback = sanitized
        if sanitized and not _looks_like_generated_attachment_stem(sanitized):
            return sanitized
    return fallback or "untitled"


def _build_target_attachment_name(
    attachment_row: dict[str, Any],
    current_path: Path,
    *,
    stable_uid: str,
    file_ext: str,
    filename_style: str,
    readable_name_max_length: int,
) -> str:
    normalized_uid = _stringify(stable_uid)
    uid_suffix = normalized_uid[4:] if normalized_uid.lower().startswith("att-") else normalized_uid
    uid_suffix = _sanitize_filename_component(uid_suffix) or "attachment"
    if filename_style == "uid_only":
        return f"{uid_suffix}{file_ext}"

    readable_stem = _select_readable_attachment_stem(attachment_row, current_path)
    readable_stem = _truncate_filename_component(readable_stem, readable_name_max_length)
    short_uid = uid_suffix[:12] if len(uid_suffix) > 12 else uid_suffix
    return f"att-{readable_stem}-{short_uid}{file_ext}"


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _resolve_output_dir(payload: dict[str, Any], workspace_root: Path | None) -> Path:
    output_dir_raw = _stringify(payload.get("output_dir"))
    if output_dir_raw:
        return Path(output_dir_raw).expanduser().resolve()
    if workspace_root is not None:
        return (workspace_root / "runtime" / "attachment_name_normalization").resolve()
    return Path.cwd().resolve()


def _resolve_attachments_root(payload: dict[str, Any], workspace_root: Path | None) -> Path | None:
    attachments_root_raw = _stringify(payload.get("attachments_root"))
    if attachments_root_raw:
        return Path(attachments_root_raw).expanduser().resolve()
    if workspace_root is not None:
        return (workspace_root / "references" / "attachments").resolve()
    return None


def _parse_scope(payload: dict[str, Any]) -> tuple[set[str], set[str]]:
    scope_payload = payload.get("scope") or {}
    if not isinstance(scope_payload, dict):
        scope_payload = {}

    uid_values = set(
        _stringify(item)
        for item in [
            *_coerce_list(scope_payload.get("uid_literature")),
            *_coerce_list(scope_payload.get("uid_literatures")),
            *_coerce_list(payload.get("uid_literature_list")),
        ]
        if _stringify(item)
    )
    cite_values = set(
        _stringify(item)
        for item in [
            *_coerce_list(scope_payload.get("cite_key")),
            *_coerce_list(scope_payload.get("cite_keys")),
            *_coerce_list(payload.get("cite_key_list")),
        ]
        if _stringify(item)
    )
    return uid_values, cite_values


def resolve_primary_attachment_normalization_settings(
    raw_cfg: dict[str, Any],
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    settings = dict(DEFAULT_PRIMARY_ATTACHMENT_NORMALIZATION_SETTINGS)
    nested = raw_cfg.get("primary_attachment_normalization") or {}
    if isinstance(nested, dict):
        settings.update(nested)

    if "primary_attachment_normalization_enabled" in raw_cfg:
        settings["enabled"] = raw_cfg.get("primary_attachment_normalization_enabled")
    if "primary_attachment_normalization_mode" in raw_cfg:
        settings["rename_mode"] = raw_cfg.get("primary_attachment_normalization_mode")
    if "primary_attachment_normalization_allowed_attachment_types" in raw_cfg:
        settings["allowed_attachment_types"] = raw_cfg.get("primary_attachment_normalization_allowed_attachment_types")
    if "primary_attachment_normalization_update_parse_assets" in raw_cfg:
        settings["update_parse_assets"] = raw_cfg.get("primary_attachment_normalization_update_parse_assets")
    if "primary_attachment_normalization_attachments_root" in raw_cfg:
        settings["attachments_root"] = raw_cfg.get("primary_attachment_normalization_attachments_root")

    enabled = _coerce_bool(settings.get("enabled"), False)
    rename_mode = _stringify(settings.get("rename_mode") or settings.get("mode") or "preview").lower()
    if rename_mode not in {"preview", "apply"}:
        rename_mode = "preview"
    allowed_attachment_types = [
        _stringify(item).lower()
        for item in _coerce_list(settings.get("allowed_attachment_types"))
        if _stringify(item)
    ] or ["fulltext", "pdf"]
    filename_style = _stringify(settings.get("filename_style") or "readable_uid").lower()
    if filename_style not in {"readable_uid", "uid_only"}:
        filename_style = "readable_uid"
    readable_name_max_length = max(_coerce_int(settings.get("readable_name_max_length"), 64), 16)

    resolved = {
        "enabled": enabled,
        "rename_mode": rename_mode,
        "allowed_attachment_types": allowed_attachment_types,
        "update_parse_assets": _coerce_bool(settings.get("update_parse_assets"), True),
        "filename_style": filename_style,
        "readable_name_max_length": readable_name_max_length,
    }
    attachments_root = _resolve_attachments_root(settings, workspace_root)
    if attachments_root is not None:
        resolved["attachments_root"] = str(attachments_root)
    return resolved


def _iter_scope_literatures(
    literatures_df: pd.DataFrame,
    uid_scope: set[str],
    cite_scope: set[str],
) -> Iterable[dict[str, Any]]:
    for _, row in literatures_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        if uid_scope and uid_literature not in uid_scope:
            continue
        if cite_scope and cite_key not in cite_scope:
            continue
        yield row.to_dict()


def _is_allowed_attachment(row: dict[str, Any], allowed_attachment_types: set[str]) -> bool:
    attachment_type = _stringify(row.get("attachment_type")).lower()
    file_ext = _stringify(row.get("file_ext")).lower()
    if attachment_type in allowed_attachment_types:
        return True
    return file_ext == "pdf"


def normalize_primary_fulltext_attachment_names(payload: dict[str, Any]) -> dict[str, Any]:
    """规范化主附件文件名，并回写 content.db。"""

    content_db_raw = _stringify(payload.get("content_db"))
    workspace_root_raw = _stringify(payload.get("workspace_root"))
    workspace_root = Path(workspace_root_raw).expanduser().resolve() if workspace_root_raw else None
    output_dir = _resolve_output_dir(payload, workspace_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = output_dir / "primary_attachment_name_normalization.json"

    if not content_db_raw:
        summary = {
            "status": "SKIPPED",
            "reason": "content_db_missing",
            "candidate_count": 0,
            "renamed_count": 0,
            "skipped_count": 0,
            "conflict_count": 0,
            "updated_literature_count": 0,
            "updated_attachment_count": 0,
            "updated_parse_asset_count": 0,
            "preview_rows": [],
            "audit_path": str(audit_path),
        }
        audit_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    content_db = Path(content_db_raw).expanduser().resolve()
    if not content_db.exists():
        summary = {
            "status": "SKIPPED",
            "reason": f"content_db_not_found: {content_db}",
            "candidate_count": 0,
            "renamed_count": 0,
            "skipped_count": 0,
            "conflict_count": 0,
            "updated_literature_count": 0,
            "updated_attachment_count": 0,
            "updated_parse_asset_count": 0,
            "preview_rows": [],
            "audit_path": str(audit_path),
        }
        audit_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    rename_mode = _stringify(payload.get("rename_mode") or "preview").lower()
    if rename_mode not in {"preview", "apply"}:
        rename_mode = "preview"
    allowed_attachment_types = {
        _stringify(item).lower() for item in _coerce_list(payload.get("allowed_attachment_types")) if _stringify(item)
    } or {"fulltext", "pdf"}
    update_parse_assets = _coerce_bool(payload.get("update_parse_assets"), True)
    filename_style = _stringify(payload.get("filename_style") or "readable_uid").lower()
    if filename_style not in {"readable_uid", "uid_only"}:
        filename_style = "readable_uid"
    readable_name_max_length = max(_coerce_int(payload.get("readable_name_max_length"), 64), 16)
    attachments_root = _resolve_attachments_root(payload, workspace_root)
    uid_scope, cite_scope = _parse_scope(payload)

    literatures_df = bibliodb_sqlite.load_literatures_df(content_db).fillna("")
    attachments_df = bibliodb_sqlite.load_attachments_df(content_db).fillna("")
    tags_df = bibliodb_sqlite.load_tags_df(content_db).fillna("")
    parse_assets_df = bibliodb_sqlite.load_parse_assets_df(content_db).fillna("") if update_parse_assets else pd.DataFrame()

    preview_rows: list[dict[str, Any]] = []
    renamed_count = 0
    conflict_count = 0
    updated_literature_uids: set[str] = set()
    updated_attachment_keys: set[tuple[str, str]] = set()
    updated_parse_assets = 0
    now_text = now_iso()
    attachment_rows_by_literature: dict[str, list[dict[str, Any]]] = {}
    literature_indices_by_uid: dict[str, list[int]] = {}
    attachment_indices_by_key: dict[tuple[str, str], list[int]] = {}
    for row_index, row in literatures_df.iterrows():
        literature_indices_by_uid.setdefault(_stringify(row.get("uid_literature")), []).append(row_index)
    for _, row in attachments_df.iterrows():
        row_index = row.name
        row_dict = row.to_dict()
        uid_literature = _stringify(row_dict.get("uid_literature"))
        uid_attachment = _stringify(row_dict.get("uid_attachment"))
        attachment_rows_by_literature.setdefault(uid_literature, []).append(row_dict)
        attachment_indices_by_key.setdefault((uid_literature, uid_attachment), []).append(row_index)

    for literature_row in _iter_scope_literatures(literatures_df, uid_scope, cite_scope):
        uid_literature = _stringify(literature_row.get("uid_literature"))
        cite_key = _stringify(literature_row.get("cite_key"))
        attachment_rows = attachment_rows_by_literature.get(uid_literature, [])
        eligible_rows = [
            row
            for row in attachment_rows
            if int(pd.to_numeric(row.get("is_primary"), errors="coerce") or 0) == 1
            and _is_allowed_attachment(row, allowed_attachment_types)
            and Path(_stringify(row.get("storage_path"))).expanduser().exists()
        ]
        if len(eligible_rows) != 1:
            preview_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "status": "skipped",
                    "reason": "primary_attachment_candidate_not_unique",
                    "eligible_count": len(eligible_rows),
                }
            )
            continue
        if not cite_key:
            preview_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "status": "skipped",
                    "reason": "cite_key_missing",
                    "eligible_count": 1,
                }
            )
            continue

        attachment_row = eligible_rows[0]
        current_uid_attachment = _stringify(attachment_row.get("uid_attachment"))
        current_path = Path(_stringify(attachment_row.get("storage_path"))).expanduser().resolve()
        source_path = _stringify(attachment_row.get("source_path")) or str(current_path)
        file_ext = current_path.suffix or (f".{_stringify(attachment_row.get('file_ext')).lstrip('.')}" if _stringify(attachment_row.get("file_ext")) else "")
        stable_uid = current_uid_attachment or (
            f"att-{bibliodb_sqlite.build_stable_attachment_uid(
                uid_literature,
                checksum=attachment_row.get('checksum'),
                source_path=source_path,
                attachment_name=attachment_row.get('attachment_name'),
                storage_path=attachment_row.get('storage_path'),
                fallback_uid=current_uid_attachment,
            )}"
        )
        stable_uid = _sanitize_filename_component(stable_uid or Path(current_path).stem)
        target_name = _build_target_attachment_name(
            attachment_row,
            current_path,
            stable_uid=stable_uid,
            file_ext=file_ext,
            filename_style=filename_style,
            readable_name_max_length=readable_name_max_length,
        )
        destination_root = attachments_root or current_path.parent
        destination_root.mkdir(parents=True, exist_ok=True)
        target_path = (destination_root / target_name).resolve()

        row_summary = {
            "uid_literature": uid_literature,
            "cite_key": cite_key,
            "old_uid_attachment": current_uid_attachment,
            "uid_attachment": stable_uid,
            "current_path": str(current_path),
            "source_path": source_path,
            "target_path": str(target_path),
            "target_name": target_name,
            "rename_mode": rename_mode,
            "filename_style": filename_style,
        }

        if target_path.exists() and not _same_file(current_path, target_path):
            row_summary.update({"status": "conflict", "reason": "target_path_exists"})
            preview_rows.append(row_summary)
            conflict_count += 1
            continue

        already_normalized = _same_file(current_path, target_path)
        if rename_mode == "apply" and not already_normalized:
            shutil.move(str(current_path), str(target_path))
            renamed_count += 1

        if rename_mode == "apply" or already_normalized:
            effective_path = target_path if (rename_mode == "apply" or already_normalized) else current_path
            effective_source_path = source_path or str(current_path)
            attachment_indices = attachment_indices_by_key.get((uid_literature, current_uid_attachment), [])
            if attachment_indices:
                attachments_df.loc[attachment_indices, "uid_attachment"] = stable_uid
                attachments_df.loc[attachment_indices, "attachment_name"] = target_name
                attachments_df.loc[attachment_indices, "storage_path"] = str(effective_path)
                attachments_df.loc[attachment_indices, "source_path"] = effective_source_path
                attachments_df.loc[attachment_indices, "file_ext"] = file_ext.lstrip(".")
                attachments_df.loc[attachment_indices, "updated_at"] = now_text
                attachment_indices_by_key[(uid_literature, stable_uid)] = attachment_indices_by_key.pop(
                    (uid_literature, current_uid_attachment),
                    attachment_indices,
                )

            literature_indices = literature_indices_by_uid.get(uid_literature, [])
            if literature_indices:
                literatures_df.loc[literature_indices, "primary_attachment_name"] = target_name
                literatures_df.loc[literature_indices, "pdf_path"] = str(effective_path)
                literatures_df.loc[literature_indices, "updated_at"] = now_text

            if update_parse_assets and not parse_assets_df.empty and current_uid_attachment != stable_uid:
                parse_mask = parse_assets_df.get("uid_attachment", pd.Series(dtype=str)).astype(str) == current_uid_attachment
                if parse_mask.any():
                    parse_assets_df.loc[parse_mask, "uid_attachment"] = stable_uid
                    parse_assets_df.loc[parse_mask, "updated_at"] = now_text
                    updated_parse_assets += int(parse_mask.sum())

            updated_literature_uids.add(uid_literature)
            updated_attachment_keys.add((uid_literature, stable_uid))
            row_summary.update(
                {
                    "status": "renamed" if rename_mode == "apply" and not already_normalized else "already_normalized",
                    "reason": "",
                }
            )
        else:
            row_summary.update({"status": "preview", "reason": ""})

        preview_rows.append(row_summary)

    if rename_mode == "apply" and (updated_literature_uids or updated_attachment_keys):
        bibliodb_sqlite.replace_reference_tables_only(
            content_db,
            literatures_df=literatures_df,
            attachments_df=attachments_df,
            tags_df=tags_df,
        )
        if update_parse_assets and not parse_assets_df.empty:
            bibliodb_sqlite.upsert_parse_asset_rows(content_db, parse_assets_df)

    summary = {
        "status": "PASS",
        "rename_mode": rename_mode,
        "filename_style": filename_style,
        "candidate_count": sum(1 for row in preview_rows if row.get("status") in {"preview", "renamed", "already_normalized"}),
        "renamed_count": renamed_count,
        "skipped_count": sum(1 for row in preview_rows if row.get("status") == "skipped"),
        "conflict_count": conflict_count,
        "updated_literature_count": len(updated_literature_uids),
        "updated_attachment_count": len(updated_attachment_keys),
        "updated_parse_asset_count": updated_parse_assets,
        "preview_rows": preview_rows,
        "audit_path": str(audit_path),
    }
    audit_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary