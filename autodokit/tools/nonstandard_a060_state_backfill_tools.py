"""非标准解析导入后的 A060 状态补齐工具。"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from autodokit.tools import bibliodb_sqlite
from autodokit.tools.time_utils import now_compact, now_iso


READY_PARSE_STATUS = {"ready", "success", "succeeded", "done", "completed", "ok", "pass", "skipped"}


def _stringify(value: Any) -> str:
    """把任意值转成去空白字符串。

    Args:
        value: 原始值。

    Returns:
        规范化字符串。
    """

    if value is None:
        return ""
    return str(value).strip()


def _coerce_bool(value: Any, default: bool) -> bool:
    """把输入值转成布尔值。

    Args:
        value: 原始值。
        default: 默认值。

    Returns:
        布尔结果。
    """

    if isinstance(value, bool):
        return value
    text = _stringify(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disable", "disabled"}:
        return False
    return default


def _fetch_current_parse_rows(content_db: Path, parse_level: str) -> list[dict[str, Any]]:
    """读取当前 parse_level 的 current 解析资产行。"""

    conn = sqlite3.connect(content_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, asset_uid, uid_literature, cite_key, uid_attachment, backend,
                   asset_dir, normalized_structured_path, parse_status, updated_at
            FROM literature_parse_assets
            WHERE parse_level = ? AND is_current = 1
            ORDER BY updated_at DESC, id DESC
            """,
            (parse_level,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _mark_rows_not_current(content_db: Path, row_ids: list[int]) -> int:
    """把指定解析资产行标记为非 current。"""

    if not row_ids:
        return 0
    now = now_iso()
    conn = sqlite3.connect(content_db)
    try:
        placeholders = ",".join(["?"] * len(row_ids))
        result = conn.execute(
            f"""
            UPDATE literature_parse_assets
            SET is_current = 0,
                updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [now, *row_ids],
        )
        conn.commit()
        return int(result.rowcount or 0)
    finally:
        conn.close()


def _update_literatures_structured_fields(content_db: Path, rows: list[dict[str, Any]], structured_task_type: str) -> int:
    """回写 literatures 的结构化字段。"""

    if not rows:
        return 0

    now = now_iso()
    conn = sqlite3.connect(content_db)
    try:
        updated = 0
        for row in rows:
            uid_literature = _stringify(row.get("uid_literature"))
            structured_abs_path = _stringify(row.get("normalized_structured_path"))
            backend = _stringify(row.get("backend")) or "external_preparsed"
            if not uid_literature or not structured_abs_path:
                continue
            cursor = conn.execute(
                """
                UPDATE literatures
                SET structured_status = ?,
                    structured_abs_path = ?,
                    structured_backend = ?,
                    structured_task_type = ?,
                    structured_updated_at = ?
                WHERE uid_literature = ?
                """,
                (
                    "ready",
                    structured_abs_path,
                    backend,
                    structured_task_type,
                    now,
                    uid_literature,
                ),
            )
            updated += int(cursor.rowcount or 0)
        conn.commit()
        return updated
    finally:
        conn.close()


def backfill_a060_state_from_parse_assets(payload: dict[str, Any]) -> dict[str, Any]:
    """基于解析资产补齐 A060 之后的状态。

    Args:
        payload: 运行参数。
            - content_db: 必填，content.db 绝对路径。
            - mode: 可选，preview/apply，默认 preview。
            - parse_level: 可选，默认 monkeyocr_full。
            - structured_task_type: 可选，默认 review_deep。
            - require_existing_assets: 可选，默认 true。
            - require_parse_status_ready: 可选，默认 true。
            - disable_dangling_current: 可选，默认 true。
            - sync_review_state: 可选，默认 true。
            - sync_reading_queue: 可选，默认 true。
            - sync_literatures_structured: 可选，默认 true。

    Returns:
        执行摘要。

    Raises:
        ValueError: 当输入参数非法时抛出。

    Examples:
        >>> backfill_a060_state_from_parse_assets({
        ...   "content_db": "C:/repo/workspace/database/content/content.db",
        ...   "mode": "preview"
        ... })
    """

    content_db_raw = _stringify(payload.get("content_db"))
    if not content_db_raw:
        raise ValueError("content_db 不能为空")
    content_db = Path(content_db_raw).expanduser().resolve()
    if not content_db.exists() or not content_db.is_file():
        raise ValueError(f"content_db 不存在: {content_db}")

    mode = _stringify(payload.get("mode") or "preview").lower()
    if mode not in {"preview", "apply"}:
        mode = "preview"
    dry_run = mode != "apply"

    parse_level = _stringify(payload.get("parse_level") or "monkeyocr_full")
    structured_task_type = _stringify(payload.get("structured_task_type") or "review_deep")

    require_existing_assets = _coerce_bool(payload.get("require_existing_assets"), True)
    require_parse_status_ready = _coerce_bool(payload.get("require_parse_status_ready"), True)
    disable_dangling_current = _coerce_bool(payload.get("disable_dangling_current"), True)
    sync_review_state = _coerce_bool(payload.get("sync_review_state"), True)
    sync_reading_queue = _coerce_bool(payload.get("sync_reading_queue"), True)
    sync_literatures_structured = _coerce_bool(payload.get("sync_literatures_structured"), True)

    bibliodb_sqlite.init_db(content_db)
    all_rows = _fetch_current_parse_rows(content_db, parse_level)

    eligible_rows: list[dict[str, Any]] = []
    dangling_row_ids: list[int] = []
    skip_reason_counter: Counter[str] = Counter()
    skipped_examples: list[dict[str, Any]] = []

    for row in all_rows:
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        asset_dir = Path(_stringify(row.get("asset_dir"))) if _stringify(row.get("asset_dir")) else None
        normalized_path = (
            Path(_stringify(row.get("normalized_structured_path")))
            if _stringify(row.get("normalized_structured_path"))
            else None
        )
        parse_status = _stringify(row.get("parse_status")).lower()

        if require_parse_status_ready and parse_status and parse_status not in READY_PARSE_STATUS:
            reason = f"parse_status_not_ready:{parse_status}"
            skip_reason_counter[reason] += 1
            if len(skipped_examples) < 20:
                skipped_examples.append({"uid_literature": uid_literature, "cite_key": cite_key, "reason": reason})
            continue

        if require_existing_assets:
            missing_parts: list[str] = []
            if not asset_dir or not asset_dir.exists() or not asset_dir.is_dir():
                missing_parts.append("asset_dir")
            if not normalized_path or not normalized_path.exists() or not normalized_path.is_file():
                missing_parts.append("normalized_structured_path")
            if missing_parts:
                reason = "missing:" + ",".join(missing_parts)
                skip_reason_counter[reason] += 1
                if len(skipped_examples) < 20:
                    skipped_examples.append({"uid_literature": uid_literature, "cite_key": cite_key, "reason": reason})
                row_id = int(row.get("id") or 0)
                if row_id > 0:
                    dangling_row_ids.append(row_id)
                continue

        eligible_rows.append(row)

    run_uid = f"manual-a060-backfill-{now_compact()}"
    review_rows: list[dict[str, Any]] = []
    queue_rows: list[dict[str, Any]] = []
    for row in eligible_rows:
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        if not uid_literature and not cite_key:
            continue
        review_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "source_stage": "A060",
                "source_origin": "nonstandard_parse_migration",
                "recommended_reason": "非标准解析资产导入后补齐 A060 状态",
                "pending_review_parse": 0,
                "review_parse_ready": 1,
                "pending_reference_preprocess": 1,
                "reference_preprocessed": 0,
                "pending_review_read": 0,
                "in_review_read": 0,
                "review_read_done": 0,
                "parse_asset_uid": _stringify(row.get("asset_uid")),
                "structured_abs_path": _stringify(row.get("normalized_structured_path")),
                "updated_at": now_iso(),
            }
        )
        queue_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "stage": "A065",
                "source_affair": "A060",
                "queue_status": "queued",
                "priority": 68.0,
                "bucket": "review_parse_ready",
                "preferred_next_stage": "A080",
                "recommended_reason": "A060 状态补齐后进入 A065",
                "source_round": "manual_backfill",
                "run_uid": run_uid,
                "scope_key": "nonstandard_a060_backfill",
                "is_current": 1,
                "updated_at": now_iso(),
            }
        )

    affected = {
        "dangling_marked_not_current": 0,
        "review_state_upserted": 0,
        "reading_queue_upserted": 0,
        "literatures_structured_updated": 0,
    }

    if not dry_run:
        if disable_dangling_current and dangling_row_ids:
            affected["dangling_marked_not_current"] = _mark_rows_not_current(content_db, sorted(set(dangling_row_ids)))
        if sync_review_state and review_rows:
            bibliodb_sqlite.upsert_review_state_rows(content_db, review_rows)
            affected["review_state_upserted"] = len(review_rows)
        if sync_reading_queue and queue_rows:
            bibliodb_sqlite.upsert_reading_queue_rows(content_db, queue_rows)
            affected["reading_queue_upserted"] = len(queue_rows)
        if sync_literatures_structured and eligible_rows:
            affected["literatures_structured_updated"] = _update_literatures_structured_fields(
                content_db,
                eligible_rows,
                structured_task_type,
            )

    status = "PASS"
    if not eligible_rows:
        status = "PARTIAL_PASS" if all_rows else "PASS"

    return {
        "status": status,
        "mode": mode,
        "content_db": str(content_db),
        "parse_level": parse_level,
        "structured_task_type": structured_task_type,
        "require_existing_assets": require_existing_assets,
        "require_parse_status_ready": require_parse_status_ready,
        "disable_dangling_current": disable_dangling_current,
        "sync_review_state": sync_review_state,
        "sync_reading_queue": sync_reading_queue,
        "sync_literatures_structured": sync_literatures_structured,
        "current_parse_rows_scanned": len(all_rows),
        "eligible_rows": len(eligible_rows),
        "skipped_rows": len(all_rows) - len(eligible_rows),
        "skip_reasons": dict(skip_reason_counter),
        "affected": affected,
        "run_uid": run_uid,
        "skipped_examples": skipped_examples,
    }
