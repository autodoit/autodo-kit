"""统一内容主库 SQLite 适配层。

该模块为 AOK 内容层提供统一物理主库能力：

1. 将旧的 `references.db` / `knowledge.db` 路径统一解析到 `content.db`；
2. 初始化文献域、知识域和跨域关系表；
3. 提供关系表回填与兼容字段同步能力。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
from typing import Mapping, Sequence

import pandas as pd

from autodokit.tools.time_utils import now_iso


DEFAULT_CONTENT_DB_NAME = "content.db"
CONTENT_DB_DIRECTORY_NAME = "content"
ATTACHMENT_TABLE_NAME = "attachments"
ATTACHMENT_LINK_TABLE_NAME = "literature_attachment_links"
KNOWLEDGE_LINK_TABLE_NAME = "knowledge_literature_links"
KNOWLEDGE_EVIDENCE_TABLE_NAME = "knowledge_evidence_links"
KNOWLEDGE_NOTES_TABLE_NAME = "knowledge_notes"
TRANSLATION_ASSET_TABLE_NAME = "literature_translation_assets"
READING_STATE_TABLE_NAME = "literature_reading_state"
READING_STATE_OVERVIEW_VIEW_NAME = "阅读状态总视图"
READING_STATE_FILTER_VIEWS: tuple[tuple[str, str], ...] = (
    ("待预处理文献清单", "IFNULL(pending_preprocess, 0) = 1"),
    (
        "补件待办文献清单",
        "IFNULL(pending_preprocess, 0) = 1 AND IFNULL(preprocess_status, '') = 'missing_attachment'",
    ),
    ("已预处理文献清单", "IFNULL(preprocessed, 0) = 1"),
    ("待泛读文献清单", "IFNULL(pending_rough_read, 0) = 1"),
    ("正泛读文献清单", "IFNULL(in_rough_read, 0) = 1"),
    ("已泛读文献清单", "IFNULL(rough_read_done, 0) = 1"),
    (
        "待批次汇总文献清单",
        "IFNULL(rough_read_done, 0) = 1 AND IFNULL(analysis_batch_synced, 0) = 0",
    ),
    ("待研读文献清单", "IFNULL(pending_deep_read, 0) = 1"),
    (
        "待批判性研读文献清单",
        "IFNULL(deep_read_decision, '') = 'parse_ready' AND IFNULL(deep_read_done, 0) = 0",
    ),
    ("正研读文献清单", "IFNULL(in_deep_read, 0) = 1"),
    ("已研读文献清单", "IFNULL(deep_read_done, 0) = 1"),
)
READING_QUEUE_REQUIRED_COLUMNS: dict[str, str] = {
    "queue_uid": "TEXT",
    "stage": "TEXT",
    "queue_status": "TEXT",
    "priority": "REAL",
    "theme_bucket": "TEXT",
    "recommended_reason": "TEXT",
    "source_stage": "TEXT",
    "source_run_uid": "TEXT",
    "task_batch_id": "TEXT",
    "decision": "TEXT",
    "decision_reason": "TEXT",
    "is_current": "INTEGER",
    "entered_at": "TEXT",
    "completed_at": "TEXT",
}
READING_STATE_REQUIRED_COLUMNS: dict[str, str] = {
    "cite_key": "TEXT",
    "source_stage": "TEXT",
    "source_uid_literature": "TEXT",
    "source_cite_key": "TEXT",
    "recommended_reason": "TEXT",
    "theme_relation": "TEXT",
    "source_origin": "TEXT",
    "reading_objective": "TEXT",
    "manual_guidance": "TEXT",
    "pending_preprocess": "INTEGER",
    "preprocessed": "INTEGER",
    "preprocess_status": "TEXT",
    "preprocess_note_path": "TEXT",
    "standard_note_path": "TEXT",
    "pending_rough_read": "INTEGER",
    "in_rough_read": "INTEGER",
    "rough_read_done": "INTEGER",
    "rough_read_note_path": "TEXT",
    "rough_read_decision": "TEXT",
    "rough_read_reason": "TEXT",
    "analysis_light_synced": "INTEGER",
    "analysis_batch_synced": "INTEGER",
    "pending_deep_read": "INTEGER",
    "in_deep_read": "INTEGER",
    "deep_read_done": "INTEGER",
    "deep_read_count": "INTEGER",
    "deep_read_note_path": "TEXT",
    "deep_read_decision": "TEXT",
    "deep_read_reason": "TEXT",
    "analysis_formal_synced": "INTEGER",
    "innovation_synced": "INTEGER",
    "last_batch_id": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}
PDF_STRUCTURED_VARIANT_SPECS: tuple[dict[str, str], ...] = (
    {
        "converter": "local_pipeline_v2",
        "task_type": "reference_context",
        "column": "structured_path_local_pipeline_v2_reference_context",
        "folder": "structured_local_pipeline_v2_reference_context",
    },
    {
        "converter": "local_pipeline_v2",
        "task_type": "full_fine_grained",
        "column": "structured_path_local_pipeline_v2_full_fine_grained",
        "folder": "structured_local_pipeline_v2_full_fine_grained",
    },
    {
        "converter": "babeldoc",
        "task_type": "reference_context",
        "column": "structured_path_babeldoc_reference_context",
        "folder": "structured_babeldoc_reference_context",
    },
    {
        "converter": "babeldoc",
        "task_type": "full_fine_grained",
        "column": "structured_path_babeldoc_full_fine_grained",
        "folder": "structured_babeldoc_full_fine_grained",
    },
)
PDF_STRUCTURED_VARIANT_PATH_COLUMNS: dict[str, str] = {
    spec["column"]: "TEXT"
    for spec in PDF_STRUCTURED_VARIANT_SPECS
}
LITERATURE_REQUIRED_COLUMNS: dict[str, str] = {
    "clean_title": "TEXT",
    "title_norm": "TEXT",
    "authors": "TEXT",
    "placeholder_reason": "TEXT",
    "placeholder_status": "TEXT",
    "placeholder_run_uid": "TEXT",
    "source_type": "TEXT",
    "origin_path": "TEXT",
    "a05_scope_key": "TEXT",
    "a05_is_review_candidate": "INTEGER",
    "a05_in_read_pool": "INTEGER",
    "a05_current_score": "REAL",
    "a05_current_rank": "INTEGER",
    "a05_current_status": "TEXT",
    "a05_last_run_uid": "TEXT",
    "a05_updated_at": "TEXT",
    "structured_status": "TEXT",
    "structured_abs_path": "TEXT",
    "structured_backend": "TEXT",
    "structured_task_type": "TEXT",
    "structured_updated_at": "TEXT",
    "structured_schema_version": "TEXT",
    "structured_text_length": "INTEGER",
    "structured_reference_count": "INTEGER",
    "source_lang": "TEXT",
    "title_zh": "TEXT",
    "abstract_zh": "TEXT",
    "keywords_zh": "TEXT",
    "metadata_translation_status": "TEXT",
    "metadata_translation_provider": "TEXT",
    "metadata_translation_model": "TEXT",
    "metadata_translation_updated_at": "TEXT",
    **PDF_STRUCTURED_VARIANT_PATH_COLUMNS,
}
TRANSLATION_ASSET_REQUIRED_COLUMNS: dict[str, str] = {
    "translation_uid": "TEXT",
    "uid_literature": "TEXT",
    "cite_key": "TEXT",
    "source_asset_uid": "TEXT",
    "source_kind": "TEXT",
    "target_lang": "TEXT",
    "translation_scope": "TEXT",
    "provider": "TEXT",
    "model_name": "TEXT",
    "asset_dir": "TEXT",
    "translated_markdown_path": "TEXT",
    "translated_structured_path": "TEXT",
    "translation_audit_path": "TEXT",
    "status": "TEXT",
    "is_current": "INTEGER",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}


def _utc_now_iso() -> str:
    return now_iso()


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _split_pipe_values(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    normalized = text.replace(",", "|").replace("；", "|").replace(";", "|")
    items = [segment.strip() for segment in normalized.split("|")]
    return [segment for segment in items if segment]


def resolve_content_db_path(db_path: str | Path) -> Path:
    """把旧内容库路径标准化到统一 `content.db`。"""

    path = Path(db_path).resolve()
    file_name = path.name.lower()
    parent_name = path.parent.name.lower()

    if file_name == DEFAULT_CONTENT_DB_NAME:
        return path

    if file_name in {"references.db", "knowledge.db"}:
        if parent_name == "database":
            return path.parent / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME
        return path

    return path


def resolve_content_db_config(
    raw_cfg: Mapping[str, object],
    *,
    content_key: str = "content_db",
    legacy_keys: Sequence[str] = ("references_db", "knowledge_db"),
    default_path: str | Path | None = None,
    required: bool = False,
) -> tuple[Path | None, str]:
    """从配置字典解析统一内容主库路径。

    优先读取 `content_db`，历史双库字段仅作为兼容别名。
    """

    for key in (content_key, *legacy_keys):
        raw_value = raw_cfg.get(key)
        value = str(raw_value or "").strip()
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            raise ValueError(f"{key} 必须为绝对路径：{path}")
        return resolve_content_db_path(path), key

    if default_path is not None:
        path = Path(default_path)
        if not path.is_absolute():
            raise ValueError(f"default_path 必须为绝对路径：{path}")
        return resolve_content_db_path(path), "default"

    if required:
        accepted = ", ".join([content_key, *legacy_keys])
        raise ValueError(f"必须提供统一内容主库路径，支持字段：{accepted}")

    return None, ""


def infer_workspace_root_from_content_db(db_path: str | Path) -> Path:
    """根据统一内容主库路径推导工作区根目录。"""

    resolved = resolve_content_db_path(db_path)
    if resolved.name != DEFAULT_CONTENT_DB_NAME:
        raise ValueError(f"不是受支持的内容主库文件名：{resolved}")
    if resolved.parent.name != CONTENT_DB_DIRECTORY_NAME:
        raise ValueError(f"内容主库目录结构不符合约定：{resolved}")
    if resolved.parent.parent.name != "database":
        raise ValueError(f"内容主库上级目录不符合约定：{resolved}")
    return resolved.parent.parent.parent


def get_pdf_structured_variant_spec(converter: str, task_type: str) -> dict[str, str] | None:
    """按解析工具链与任务类型获取四组合规格。"""

    normalized_converter = str(converter or "").strip().lower()
    normalized_task_type = str(task_type or "").strip().lower()
    for spec in PDF_STRUCTURED_VARIANT_SPECS:
        if spec["converter"] == normalized_converter and spec["task_type"] == normalized_task_type:
            return dict(spec)
    return None


def get_pdf_structured_variant_column(converter: str, task_type: str) -> str | None:
    """返回四组合对应的文献主表路径字段名。"""

    spec = get_pdf_structured_variant_spec(converter, task_type)
    return None if spec is None else spec["column"]


def build_pdf_structured_variant_dir_map(references_root: str | Path) -> dict[str, Path]:
    """构造 `workspace/references` 下的四组合目录映射。"""

    root = Path(references_root)
    return {spec["folder"]: root / spec["folder"] for spec in PDF_STRUCTURED_VARIANT_SPECS}


def resolve_pdf_structured_variant_output_dir(
    workspace_root: str | Path,
    *,
    converter: str,
    task_type: str,
) -> Path:
    """根据四组合契约返回固定 structured 输出目录。"""

    spec = get_pdf_structured_variant_spec(converter, task_type)
    if spec is None:
        raise ValueError(
            f"不支持的 PDF 解析组合：converter={converter!r}, task_type={task_type!r}"
        )
    return Path(workspace_root) / "references" / spec["folder"]


def connect_sqlite(db_path: str | Path) -> sqlite3.Connection:
    """创建统一内容主库连接，并开启基础 pragma。"""

    original = Path(db_path).resolve()
    resolved = resolve_content_db_path(original)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(resolved))
    _ensure_legacy_db_alias(original, resolved)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass
    return connection


def _ensure_legacy_db_alias(original: Path, resolved: Path) -> None:
    if original == resolved:
        return
    original.parent.mkdir(parents=True, exist_ok=True)
    if original.exists():
        try:
            if original.samefile(resolved):
                return
        except OSError:
            return
    try:
        os.link(resolved, original)
    except OSError:
        return


def _replace_table_rows(conn: sqlite3.Connection, table_name: str, frame: pd.DataFrame) -> None:
    if _sqlite_object_type(conn, table_name) != "table":
        return
    conn.execute(f"DELETE FROM {_quote_identifier(table_name)}")
    if frame is None or frame.empty:
        return
    working = frame.where(pd.notnull(frame), None)
    working.to_sql(table_name, conn, if_exists="append", index=False)


def _sqlite_object_type(conn: sqlite3.Connection, object_name: str) -> str:
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ? LIMIT 1",
        (object_name,),
    ).fetchone()
    return str(row[0]).strip().lower() if row and row[0] else ""


def _create_index_if_table(conn: sqlite3.Connection, table_name: str, index_sql: str) -> None:
    if _sqlite_object_type(conn, table_name) == "table":
        conn.execute(index_sql)


def _ensure_table_columns(conn: sqlite3.Connection, table_name: str, column_types: Mapping[str, str]) -> None:
    if _sqlite_object_type(conn, table_name) != "table":
        return
    existing_columns = {
        str(row[1]).strip()
        for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})")
    }
    for column_name, column_type in column_types.items():
        normalized_name = str(column_name).strip()
        if not normalized_name or normalized_name in existing_columns:
            continue
        normalized_type = str(column_type or "TEXT").strip() or "TEXT"
        conn.execute(
            f"ALTER TABLE {_quote_identifier(table_name)} ADD COLUMN {_quote_identifier(normalized_name)} {normalized_type}"
        )
        existing_columns.add(normalized_name)


def _create_or_replace_view(conn: sqlite3.Connection, view_name: str, select_sql: str) -> None:
    object_type = _sqlite_object_type(conn, view_name)
    if object_type == "table":
        raise sqlite3.OperationalError(f"对象 {view_name} 已存在且为表，无法覆盖为视图")
    if object_type == "view":
        conn.execute(f"DROP VIEW IF EXISTS {_quote_identifier(view_name)}")
    conn.execute(f"CREATE VIEW {_quote_identifier(view_name)} AS\n{select_sql.strip()}")


def _refresh_reading_state_views(conn: sqlite3.Connection) -> None:
    overview_select_sql = f"""
    WITH attachment_summary AS (
        SELECT
            lnk.uid_literature,
            COUNT(*) AS attachment_count,
            MAX(CASE WHEN COALESCE(lnk.is_primary, 0) = 1 THEN att.attachment_name ELSE '' END) AS primary_attachment_name,
            MAX(CASE WHEN COALESCE(lnk.is_primary, 0) = 1 THEN att.storage_path ELSE '' END) AS primary_attachment_path,
            MAX(CASE WHEN COALESCE(lnk.is_primary, 0) = 1 THEN att.status ELSE '' END) AS primary_attachment_status
        FROM {ATTACHMENT_LINK_TABLE_NAME} AS lnk
        LEFT JOIN {ATTACHMENT_TABLE_NAME} AS att
            ON att.uid_attachment = lnk.uid_attachment
        GROUP BY lnk.uid_literature
    ),
    parse_summary AS (
        SELECT
            uid_literature,
            MAX(CASE WHEN COALESCE(is_current, 0) = 1 THEN parse_level ELSE '' END) AS current_parse_level,
            MAX(CASE WHEN COALESCE(is_current, 0) = 1 THEN parse_status ELSE '' END) AS current_parse_status,
            MAX(CASE WHEN COALESCE(is_current, 0) = 1 THEN normalized_structured_path ELSE '' END) AS current_structured_path
        FROM literature_parse_assets
        GROUP BY uid_literature
    )
    SELECT
        rs.uid_literature,
        COALESCE(rs.cite_key, lit.cite_key) AS cite_key,
        COALESCE(lit.title, '') AS title,
        COALESCE(lit.first_author, '') AS first_author,
        COALESCE(lit.year, '') AS year,
        COALESCE(lit.entry_type, '') AS entry_type,
        COALESCE(lit.source_type, '') AS source_type,
        COALESCE(lit.has_fulltext, 0) AS has_fulltext,
        COALESCE(lit.is_placeholder, 0) AS is_placeholder,
        COALESCE(lit.placeholder_status, '') AS placeholder_status,
        COALESCE(rs.source_stage, '') AS source_stage,
        COALESCE(rs.source_origin, '') AS source_origin,
        COALESCE(rs.recommended_reason, '') AS recommended_reason,
        COALESCE(rs.theme_relation, '') AS theme_relation,
        COALESCE(rs.reading_objective, '') AS reading_objective,
        COALESCE(rs.manual_guidance, '') AS manual_guidance,
        COALESCE(rs.pending_preprocess, 0) AS pending_preprocess,
        COALESCE(rs.preprocessed, 0) AS preprocessed,
        COALESCE(rs.preprocess_status, '') AS preprocess_status,
        COALESCE(rs.preprocess_note_path, '') AS preprocess_note_path,
        COALESCE(rs.standard_note_path, '') AS standard_note_path,
        COALESCE(rs.pending_rough_read, 0) AS pending_rough_read,
        COALESCE(rs.in_rough_read, 0) AS in_rough_read,
        COALESCE(rs.rough_read_done, 0) AS rough_read_done,
        COALESCE(rs.rough_read_note_path, '') AS rough_read_note_path,
        COALESCE(rs.rough_read_decision, '') AS rough_read_decision,
        COALESCE(rs.rough_read_reason, '') AS rough_read_reason,
        COALESCE(rs.analysis_light_synced, 0) AS analysis_light_synced,
        COALESCE(rs.analysis_batch_synced, 0) AS analysis_batch_synced,
        COALESCE(rs.pending_deep_read, 0) AS pending_deep_read,
        COALESCE(rs.in_deep_read, 0) AS in_deep_read,
        COALESCE(rs.deep_read_done, 0) AS deep_read_done,
        COALESCE(rs.deep_read_count, 0) AS deep_read_count,
        COALESCE(rs.deep_read_note_path, '') AS deep_read_note_path,
        COALESCE(rs.deep_read_decision, '') AS deep_read_decision,
        COALESCE(rs.deep_read_reason, '') AS deep_read_reason,
        COALESCE(rs.analysis_formal_synced, 0) AS analysis_formal_synced,
        COALESCE(rs.innovation_synced, 0) AS innovation_synced,
        COALESCE(rs.last_batch_id, '') AS last_batch_id,
        COALESCE(att.attachment_count, 0) AS attachment_count,
        COALESCE(att.primary_attachment_name, '') AS primary_attachment_name,
        COALESCE(att.primary_attachment_path, '') AS primary_attachment_path,
        COALESCE(att.primary_attachment_status, '') AS primary_attachment_status,
        COALESCE(parse.current_parse_level, '') AS current_parse_level,
        COALESCE(parse.current_parse_status, '') AS current_parse_status,
        COALESCE(parse.current_structured_path, '') AS current_structured_path,
        CASE
            WHEN COALESCE(rs.pending_preprocess, 0) = 1 AND COALESCE(rs.preprocess_status, '') = 'missing_attachment' THEN '补件待办'
            WHEN COALESCE(rs.pending_preprocess, 0) = 1 THEN '待预处理'
            WHEN COALESCE(rs.pending_rough_read, 0) = 1 THEN '待泛读'
            WHEN COALESCE(rs.in_rough_read, 0) = 1 THEN '正泛读'
            WHEN COALESCE(rs.rough_read_done, 0) = 1 AND COALESCE(rs.analysis_batch_synced, 0) = 0 THEN '待批次汇总'
            WHEN COALESCE(rs.pending_deep_read, 0) = 1 THEN '待研读'
            WHEN COALESCE(rs.deep_read_decision, '') = 'parse_ready' AND COALESCE(rs.deep_read_done, 0) = 0 THEN '待批判性研读'
            WHEN COALESCE(rs.in_deep_read, 0) = 1 THEN '正研读'
            WHEN COALESCE(rs.deep_read_done, 0) = 1 THEN '已研读'
            WHEN COALESCE(rs.preprocessed, 0) = 1 THEN '已预处理'
            ELSE '未归类'
        END AS current_list_name,
        CASE
            WHEN COALESCE(rs.pending_preprocess, 0) = 1 AND COALESCE(rs.preprocess_status, '') = 'missing_attachment' THEN 1
            ELSE 0
        END AS is_attachment_backlog,
        COALESCE(rs.created_at, '') AS created_at,
        COALESCE(rs.updated_at, '') AS updated_at
    FROM {READING_STATE_TABLE_NAME} AS rs
    LEFT JOIN literatures AS lit
        ON lit.uid_literature = rs.uid_literature
    LEFT JOIN attachment_summary AS att
        ON att.uid_literature = rs.uid_literature
    LEFT JOIN parse_summary AS parse
        ON parse.uid_literature = rs.uid_literature
    ORDER BY COALESCE(rs.updated_at, '') DESC, COALESCE(lit.year, '') DESC, COALESCE(rs.cite_key, lit.cite_key, rs.uid_literature)
    """
    _create_or_replace_view(conn, READING_STATE_OVERVIEW_VIEW_NAME, overview_select_sql)

    quoted_overview_name = _quote_identifier(READING_STATE_OVERVIEW_VIEW_NAME)
    for view_name, where_clause in READING_STATE_FILTER_VIEWS:
        view_sql = f"""
        SELECT *
        FROM {quoted_overview_name}
        WHERE {where_clause}
        ORDER BY updated_at DESC, year DESC, cite_key, uid_literature
        """
        _create_or_replace_view(conn, view_name, view_sql)


def _attachment_entity_uid(
    *,
    checksum: str,
    storage_path: str,
    source_path: str,
    attachment_name: str,
) -> str:
    token = checksum or storage_path or source_path or attachment_name
    normalized = str(token or "").strip().lower()
    return f"att-{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def _attachment_link_uid(uid_literature: str, uid_attachment: str, legacy_uid_attachment: str) -> str:
    token = legacy_uid_attachment or f"{uid_literature}|{uid_attachment}"
    normalized = str(token or "").strip().lower()
    return f"attlnk-{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def _build_attachment_normalized_frames(legacy_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    attachment_columns = [
        "uid_attachment",
        "attachment_name",
        "attachment_type",
        "file_ext",
        "storage_path",
        "source_path",
        "checksum",
        "status",
        "created_at",
        "updated_at",
    ]
    link_columns = [
        "uid_attachment_link",
        "uid_literature",
        "uid_attachment",
        "link_role",
        "is_primary",
        "source_type",
        "legacy_uid_attachment",
        "created_at",
        "updated_at",
    ]
    if legacy_df is None or legacy_df.empty:
        return pd.DataFrame(columns=attachment_columns), pd.DataFrame(columns=link_columns)

    attachment_rows_by_uid: dict[str, dict[str, object]] = {}
    link_rows: list[dict[str, object]] = []
    now = _utc_now_iso()

    for _, row in legacy_df.fillna("").iterrows():
        uid_literature = str(row.get("uid_literature") or "").strip()
        if not uid_literature:
            continue
        checksum = str(row.get("checksum") or "").strip()
        storage_path = str(row.get("storage_path") or "").strip()
        source_path = str(row.get("source_path") or "").strip()
        attachment_name = str(row.get("attachment_name") or "").strip()
        if not any([checksum, storage_path, source_path, attachment_name]):
            continue

        uid_attachment = _attachment_entity_uid(
            checksum=checksum,
            storage_path=storage_path,
            source_path=source_path,
            attachment_name=attachment_name,
        )
        existing_attachment_row = attachment_rows_by_uid.get(uid_attachment, {})
        attachment_rows_by_uid[uid_attachment] = {
            "uid_attachment": uid_attachment,
            "attachment_name": attachment_name or str(existing_attachment_row.get("attachment_name") or ""),
            "attachment_type": str(row.get("attachment_type") or existing_attachment_row.get("attachment_type") or "").strip(),
            "file_ext": str(row.get("file_ext") or existing_attachment_row.get("file_ext") or "").strip(),
            "storage_path": storage_path or str(existing_attachment_row.get("storage_path") or ""),
            "source_path": source_path or str(existing_attachment_row.get("source_path") or ""),
            "checksum": checksum or str(existing_attachment_row.get("checksum") or ""),
            "status": str(row.get("status") or existing_attachment_row.get("status") or "available").strip() or "available",
            "created_at": str(existing_attachment_row.get("created_at") or row.get("created_at") or now).strip() or now,
            "updated_at": str(row.get("updated_at") or existing_attachment_row.get("updated_at") or now).strip() or now,
        }

        legacy_uid_attachment = str(row.get("uid_attachment") or "").strip()
        link_rows.append(
            {
                "uid_attachment_link": _attachment_link_uid(uid_literature, uid_attachment, legacy_uid_attachment),
                "uid_literature": uid_literature,
                "uid_attachment": uid_attachment,
                "link_role": str(row.get("attachment_type") or "attached").strip() or "attached",
                "is_primary": int(pd.to_numeric(row.get("is_primary"), errors="coerce") or 0),
                "source_type": "legacy_literature_attachments",
                "legacy_uid_attachment": legacy_uid_attachment,
                "created_at": str(row.get("created_at") or now).strip() or now,
                "updated_at": str(row.get("updated_at") or now).strip() or now,
            }
        )

    attachments_df = pd.DataFrame(list(attachment_rows_by_uid.values()), columns=attachment_columns)
    links_df = pd.DataFrame(link_rows, columns=link_columns)
    if not links_df.empty:
        links_df = links_df.sort_values(
            by=["uid_literature", "uid_attachment", "is_primary", "updated_at"],
            ascending=[True, True, False, False],
            na_position="last",
        )
        links_df = links_df.drop_duplicates(subset=["uid_literature", "uid_attachment"], keep="first").reset_index(drop=True)
    return attachments_df, links_df


def _build_legacy_attachment_projection(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        f"""
        SELECT
            COALESCE(lnk.legacy_uid_attachment, lnk.uid_attachment_link, att.uid_attachment) AS uid_attachment,
            lnk.uid_literature,
            att.attachment_name,
            COALESCE(NULLIF(lnk.link_role, ''), att.attachment_type) AS attachment_type,
            att.file_ext,
            att.storage_path,
            att.source_path,
            att.checksum,
            COALESCE(lnk.is_primary, 0) AS is_primary,
            att.status,
            COALESCE(lnk.created_at, att.created_at) AS created_at,
            COALESCE(lnk.updated_at, att.updated_at) AS updated_at
        FROM {ATTACHMENT_LINK_TABLE_NAME} AS lnk
        LEFT JOIN {ATTACHMENT_TABLE_NAME} AS att
            ON att.uid_attachment = lnk.uid_attachment
        ORDER BY lnk.uid_literature, COALESCE(lnk.is_primary, 0) DESC, att.attachment_name
        """,
        conn,
    )


def _sync_attachment_normalized_tables(conn: sqlite3.Connection) -> None:
    if _sqlite_object_type(conn, "literature_attachments") != "table":
        return

    attachment_count = conn.execute(f"SELECT COUNT(1) FROM {ATTACHMENT_TABLE_NAME}").fetchone()
    link_count = conn.execute(f"SELECT COUNT(1) FROM {ATTACHMENT_LINK_TABLE_NAME}").fetchone()
    attachment_total = int((attachment_count or [0])[0] or 0)
    link_total = int((link_count or [0])[0] or 0)

    # 规范化两层表优先作为真相源，旧表仅保留兼容投影。
    if attachment_total > 0 or link_total > 0:
        if link_total > 0:
            legacy_projection_df = _build_legacy_attachment_projection(conn)
            _replace_table_rows(conn, "literature_attachments", legacy_projection_df)
        return

    legacy_df = pd.read_sql_query("SELECT * FROM literature_attachments", conn)
    if legacy_df.empty:
        _replace_table_rows(conn, ATTACHMENT_LINK_TABLE_NAME, pd.DataFrame())
        _replace_table_rows(conn, ATTACHMENT_TABLE_NAME, pd.DataFrame())
        return

    attachments_df, links_df = _build_attachment_normalized_frames(legacy_df)
    _replace_table_rows(conn, ATTACHMENT_LINK_TABLE_NAME, pd.DataFrame())
    _replace_table_rows(conn, ATTACHMENT_TABLE_NAME, attachments_df)
    _replace_table_rows(conn, ATTACHMENT_LINK_TABLE_NAME, links_df)


def init_content_db(db_path: str | Path) -> Path:
    """初始化统一内容主库。"""

    resolved = resolve_content_db_path(db_path)
    with connect_sqlite(resolved) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS literatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_literature TEXT UNIQUE,
                cite_key TEXT,
                title TEXT,
                clean_title TEXT,
                title_norm TEXT,
                authors TEXT,
                first_author TEXT,
                year TEXT,
                entry_type TEXT,
                abstract TEXT,
                keywords TEXT,
                pdf_path TEXT,
                is_placeholder INTEGER,
                placeholder_reason TEXT,
                placeholder_status TEXT,
                placeholder_run_uid TEXT,
                has_fulltext INTEGER,
                primary_attachment_name TEXT,
                standard_note_uid TEXT,
                source_type TEXT,
                origin_path TEXT,
                created_at TEXT,
                updated_at TEXT,
                a05_scope_key TEXT,
                a05_is_review_candidate INTEGER,
                a05_in_read_pool INTEGER,
                a05_current_score REAL,
                a05_current_rank INTEGER,
                a05_current_status TEXT,
                a05_last_run_uid TEXT,
                a05_updated_at TEXT,
                structured_status TEXT,
                structured_abs_path TEXT,
                structured_backend TEXT,
                structured_task_type TEXT,
                structured_updated_at TEXT,
                structured_schema_version TEXT,
                structured_text_length INTEGER,
                structured_reference_count INTEGER,
                structured_path_local_pipeline_v2_reference_context TEXT,
                structured_path_local_pipeline_v2_full_fine_grained TEXT,
                structured_path_babeldoc_reference_context TEXT,
                structured_path_babeldoc_full_fine_grained TEXT
            )
            """
        )
        _ensure_table_columns(conn, "literatures", LITERATURE_REQUIRED_COLUMNS)
        _create_index_if_table(conn, "literatures", "CREATE INDEX IF NOT EXISTS idx_lit_uid ON literatures(uid_literature)")
        _create_index_if_table(conn, "literatures", "CREATE INDEX IF NOT EXISTS idx_lit_cite ON literatures(cite_key)")
        _create_index_if_table(conn, "literatures", "CREATE INDEX IF NOT EXISTS idx_lit_author_year ON literatures(first_author, year)")
        _create_index_if_table(conn, "literatures", "CREATE INDEX IF NOT EXISTS idx_lit_a05_rank ON literatures(a05_scope_key, a05_current_rank)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS literature_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_attachment TEXT UNIQUE,
                uid_literature TEXT,
                attachment_name TEXT,
                attachment_type TEXT,
                file_ext TEXT,
                storage_path TEXT,
                source_path TEXT,
                checksum TEXT,
                is_primary INTEGER,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(uid_literature) REFERENCES literatures(uid_literature)
            )
            """
        )
        _create_index_if_table(conn, "literature_attachments", "CREATE INDEX IF NOT EXISTS idx_att_lit ON literature_attachments(uid_literature)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ATTACHMENT_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_attachment TEXT UNIQUE,
                attachment_name TEXT,
                attachment_type TEXT,
                file_ext TEXT,
                storage_path TEXT,
                source_path TEXT,
                checksum TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        _create_index_if_table(conn, ATTACHMENT_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_attachment_path ON {ATTACHMENT_TABLE_NAME}(storage_path)")
        _create_index_if_table(conn, ATTACHMENT_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_attachment_checksum ON {ATTACHMENT_TABLE_NAME}(checksum)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ATTACHMENT_LINK_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_attachment_link TEXT UNIQUE,
                uid_literature TEXT,
                uid_attachment TEXT,
                link_role TEXT,
                is_primary INTEGER,
                source_type TEXT,
                legacy_uid_attachment TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(uid_literature, uid_attachment),
                FOREIGN KEY(uid_literature) REFERENCES literatures(uid_literature),
                FOREIGN KEY(uid_attachment) REFERENCES {ATTACHMENT_TABLE_NAME}(uid_attachment)
            )
            """
        )
        _create_index_if_table(conn, ATTACHMENT_LINK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_attachment_link_lit ON {ATTACHMENT_LINK_TABLE_NAME}(uid_literature)")
        _create_index_if_table(conn, ATTACHMENT_LINK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_attachment_link_attachment ON {ATTACHMENT_LINK_TABLE_NAME}(uid_attachment)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS literature_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_literature TEXT,
                cite_key TEXT,
                tag TEXT,
                tag_norm TEXT,
                source_type TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(uid_literature, tag),
                FOREIGN KEY(uid_literature) REFERENCES literatures(uid_literature)
            )
            """
        )
        _create_index_if_table(conn, "literature_tags", "CREATE INDEX IF NOT EXISTS idx_tag_lit ON literature_tags(uid_literature)")
        _create_index_if_table(conn, "literature_tags", "CREATE INDEX IF NOT EXISTS idx_tag_name ON literature_tags(tag)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS literature_parse_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_uid TEXT UNIQUE,
                uid_literature TEXT,
                cite_key TEXT,
                uid_attachment TEXT,
                parse_level TEXT,
                backend TEXT,
                model_name TEXT,
                asset_dir TEXT,
                normalized_structured_path TEXT,
                reconstructed_markdown_path TEXT,
                linear_index_path TEXT,
                elements_path TEXT,
                chunks_jsonl_path TEXT,
                parse_record_path TEXT,
                quality_report_path TEXT,
                parse_status TEXT,
                last_run_uid TEXT,
                is_current INTEGER,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(uid_literature) REFERENCES literatures(uid_literature)
            )
            """
        )
        _create_index_if_table(conn, "literature_parse_assets", "CREATE INDEX IF NOT EXISTS idx_parse_asset_lit_level ON literature_parse_assets(uid_literature, parse_level)")
        _create_index_if_table(conn, "literature_parse_assets", "CREATE INDEX IF NOT EXISTS idx_parse_asset_current ON literature_parse_assets(parse_level, is_current)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TRANSLATION_ASSET_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                translation_uid TEXT UNIQUE,
                uid_literature TEXT,
                cite_key TEXT,
                source_asset_uid TEXT,
                source_kind TEXT,
                target_lang TEXT,
                translation_scope TEXT,
                provider TEXT,
                model_name TEXT,
                asset_dir TEXT,
                translated_markdown_path TEXT,
                translated_structured_path TEXT,
                translation_audit_path TEXT,
                status TEXT,
                is_current INTEGER,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(uid_literature) REFERENCES literatures(uid_literature)
            )
            """
        )
        _ensure_table_columns(conn, TRANSLATION_ASSET_TABLE_NAME, TRANSLATION_ASSET_REQUIRED_COLUMNS)
        _create_index_if_table(
            conn,
            TRANSLATION_ASSET_TABLE_NAME,
            f"CREATE INDEX IF NOT EXISTS idx_translation_asset_lit_scope ON {TRANSLATION_ASSET_TABLE_NAME}(uid_literature, source_kind, target_lang, translation_scope)",
        )
        _create_index_if_table(
            conn,
            TRANSLATION_ASSET_TABLE_NAME,
            f"CREATE INDEX IF NOT EXISTS idx_translation_asset_current ON {TRANSLATION_ASSET_TABLE_NAME}(source_kind, target_lang, is_current)",
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS literature_reading_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue_uid TEXT UNIQUE,
                uid_literature TEXT,
                cite_key TEXT,
                stage TEXT,
                queue_status TEXT,
                priority REAL,
                theme_bucket TEXT,
                recommended_reason TEXT,
                source_stage TEXT,
                source_run_uid TEXT,
                task_batch_id TEXT,
                decision TEXT,
                decision_reason TEXT,
                is_current INTEGER,
                entered_at TEXT,
                updated_at TEXT,
                completed_at TEXT,
                FOREIGN KEY(uid_literature) REFERENCES literatures(uid_literature)
            )
            """
        )
        _ensure_table_columns(conn, "literature_reading_queue", READING_QUEUE_REQUIRED_COLUMNS)
        _create_index_if_table(conn, "literature_reading_queue", "CREATE INDEX IF NOT EXISTS idx_reading_queue_stage_current ON literature_reading_queue(stage, is_current)")
        _create_index_if_table(conn, "literature_reading_queue", "CREATE INDEX IF NOT EXISTS idx_reading_queue_item ON literature_reading_queue(stage, uid_literature, cite_key)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {READING_STATE_TABLE_NAME} (
                uid_literature TEXT PRIMARY KEY,
                cite_key TEXT,
                source_stage TEXT,
                source_uid_literature TEXT,
                source_cite_key TEXT,
                recommended_reason TEXT,
                theme_relation TEXT,
                source_origin TEXT,
                reading_objective TEXT,
                manual_guidance TEXT,
                pending_preprocess INTEGER,
                preprocessed INTEGER,
                preprocess_status TEXT,
                preprocess_note_path TEXT,
                standard_note_path TEXT,
                pending_rough_read INTEGER,
                in_rough_read INTEGER,
                rough_read_done INTEGER,
                rough_read_note_path TEXT,
                rough_read_decision TEXT,
                rough_read_reason TEXT,
                analysis_light_synced INTEGER,
                analysis_batch_synced INTEGER,
                pending_deep_read INTEGER,
                in_deep_read INTEGER,
                deep_read_done INTEGER,
                deep_read_count INTEGER,
                deep_read_note_path TEXT,
                deep_read_decision TEXT,
                deep_read_reason TEXT,
                analysis_formal_synced INTEGER,
                innovation_synced INTEGER,
                last_batch_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(uid_literature) REFERENCES literatures(uid_literature)
            )
            """
        )
        _ensure_table_columns(conn, READING_STATE_TABLE_NAME, READING_STATE_REQUIRED_COLUMNS)
        _create_index_if_table(conn, READING_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_reading_state_preprocess ON {READING_STATE_TABLE_NAME}(pending_preprocess, preprocessed)")
        _create_index_if_table(conn, READING_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_reading_state_rough ON {READING_STATE_TABLE_NAME}(pending_rough_read, rough_read_done)")
        _create_index_if_table(conn, READING_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_reading_state_deep ON {READING_STATE_TABLE_NAME}(pending_deep_read, deep_read_done)")
        _create_index_if_table(conn, READING_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_reading_state_cite ON {READING_STATE_TABLE_NAME}(cite_key)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS literature_chunk_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunks_uid TEXT UNIQUE,
                source_scope TEXT,
                chunks_abs_path TEXT,
                source_backend TEXT,
                chunk_count INTEGER,
                source_doc_count INTEGER,
                created_at TEXT,
                status TEXT
            )
            """
        )
        _create_index_if_table(conn, "literature_chunk_sets", "CREATE INDEX IF NOT EXISTS idx_chunk_set_uid ON literature_chunk_sets(chunks_uid)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS literature_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT UNIQUE,
                chunks_uid TEXT,
                uid_literature TEXT,
                cite_key TEXT,
                shard_abs_path TEXT,
                chunk_index INTEGER,
                chunk_type TEXT,
                char_start INTEGER,
                char_end INTEGER,
                text_length INTEGER,
                created_at TEXT,
                FOREIGN KEY(chunks_uid) REFERENCES literature_chunk_sets(chunks_uid),
                FOREIGN KEY(uid_literature) REFERENCES literatures(uid_literature)
            )
            """
        )
        _create_index_if_table(conn, "literature_chunks", "CREATE INDEX IF NOT EXISTS idx_chunk_uid ON literature_chunks(chunk_id)")
        _create_index_if_table(conn, "literature_chunks", "CREATE INDEX IF NOT EXISTS idx_chunk_set_ref ON literature_chunks(chunks_uid)")
        _create_index_if_table(conn, "literature_chunks", "CREATE INDEX IF NOT EXISTS idx_chunk_lit_uid ON literature_chunks(uid_literature)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_knowledge TEXT UNIQUE,
                note_name TEXT,
                note_path TEXT,
                note_type TEXT,
                title TEXT,
                status TEXT,
                tags TEXT,
                aliases TEXT,
                source_type TEXT,
                evidence_uids TEXT,
                uid_literature TEXT,
                cite_key TEXT,
                attachment_uids TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        _create_index_if_table(conn, "knowledge_index", "CREATE INDEX IF NOT EXISTS idx_know_uid ON knowledge_index(uid_knowledge)")
        _create_index_if_table(conn, "knowledge_index", "CREATE INDEX IF NOT EXISTS idx_know_type_status ON knowledge_index(note_type, status)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_attachment TEXT UNIQUE,
                uid_knowledge TEXT,
                attachment_name TEXT,
                attachment_type TEXT,
                file_ext TEXT,
                storage_path TEXT,
                source_path TEXT,
                checksum TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(uid_knowledge) REFERENCES knowledge_index(uid_knowledge)
            )
            """
        )
        _create_index_if_table(conn, "knowledge_attachments", "CREATE INDEX IF NOT EXISTS idx_katt_uid ON knowledge_attachments(uid_knowledge)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {KNOWLEDGE_NOTES_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_note TEXT UNIQUE,
                uid_literature TEXT,
                cite_key TEXT,
                note_type TEXT,
                note_path TEXT,
                title TEXT,
                status TEXT,
                source_stage TEXT,
                source_run_uid TEXT,
                content_hash TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(uid_literature) REFERENCES literatures(uid_literature)
            )
            """
        )
        _create_index_if_table(conn, KNOWLEDGE_NOTES_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_knote_lit ON {KNOWLEDGE_NOTES_TABLE_NAME}(uid_literature)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {KNOWLEDGE_LINK_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_knowledge TEXT,
                uid_literature TEXT,
                relation_type TEXT,
                is_primary INTEGER,
                cite_key TEXT,
                source_field TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(uid_knowledge, uid_literature, relation_type),
                FOREIGN KEY(uid_knowledge) REFERENCES knowledge_index(uid_knowledge),
                FOREIGN KEY(uid_literature) REFERENCES literatures(uid_literature)
            )
            """
        )
        _create_index_if_table(
            conn,
            KNOWLEDGE_LINK_TABLE_NAME,
            f"CREATE INDEX IF NOT EXISTS idx_kl_link_lit_type ON {KNOWLEDGE_LINK_TABLE_NAME}(uid_literature, relation_type)",
        )
        _create_index_if_table(
            conn,
            KNOWLEDGE_LINK_TABLE_NAME,
            f"CREATE INDEX IF NOT EXISTS idx_kl_link_kn_type ON {KNOWLEDGE_LINK_TABLE_NAME}(uid_knowledge, relation_type)",
        )
        _create_index_if_table(
            conn,
            KNOWLEDGE_LINK_TABLE_NAME,
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_kl_standard_primary ON {KNOWLEDGE_LINK_TABLE_NAME}(uid_literature) WHERE relation_type = 'standard_note' AND COALESCE(is_primary, 0) = 1",
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {KNOWLEDGE_EVIDENCE_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_knowledge TEXT,
                evidence_type TEXT,
                target_uid TEXT,
                evidence_role TEXT,
                source_field TEXT,
                created_at TEXT,
                UNIQUE(uid_knowledge, evidence_type, target_uid, evidence_role),
                FOREIGN KEY(uid_knowledge) REFERENCES knowledge_index(uid_knowledge)
            )
            """
        )
        _create_index_if_table(
            conn,
            KNOWLEDGE_EVIDENCE_TABLE_NAME,
            f"CREATE INDEX IF NOT EXISTS idx_ke_uid_type ON {KNOWLEDGE_EVIDENCE_TABLE_NAME}(uid_knowledge, evidence_type)",
        )

        _sync_attachment_normalized_tables(conn)
        _refresh_reading_state_views(conn)

        conn.commit()
    return resolved


def load_knowledge_literature_links_df(db_path: str | Path) -> pd.DataFrame:
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {KNOWLEDGE_LINK_TABLE_NAME}", conn)


def load_attachment_entities_df(db_path: str | Path) -> pd.DataFrame:
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {ATTACHMENT_TABLE_NAME}", conn)


def load_literature_attachment_links_df(db_path: str | Path) -> pd.DataFrame:
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {ATTACHMENT_LINK_TABLE_NAME}", conn)


def load_knowledge_evidence_links_df(db_path: str | Path) -> pd.DataFrame:
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {KNOWLEDGE_EVIDENCE_TABLE_NAME}", conn)


def load_translation_assets_df(
    db_path: str | Path,
    *,
    uid_literature: str = "",
    source_kind: str = "",
    target_lang: str = "",
    only_current: bool = False,
) -> pd.DataFrame:
    """读取翻译资产索引。"""

    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        frame = pd.read_sql_query(f"SELECT * FROM {TRANSLATION_ASSET_TABLE_NAME}", conn)

    if frame.empty:
        return frame

    if uid_literature:
        frame = frame[frame["uid_literature"].astype(str) == str(uid_literature)]
    if source_kind:
        frame = frame[frame["source_kind"].astype(str) == str(source_kind)]
    if target_lang:
        frame = frame[frame["target_lang"].astype(str) == str(target_lang)]
    if only_current:
        frame = frame[frame["is_current"].fillna(0).astype(int) == 1]

    return frame.reset_index(drop=True)


def upsert_translation_asset_rows(
    db_path: str | Path,
    rows: Sequence[dict[str, object]] | pd.DataFrame,
) -> None:
    """写入翻译资产索引并维护 current 标记。"""

    incoming = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows or []))
    if incoming.empty:
        return

    init_content_db(db_path)
    now = _utc_now_iso()
    with connect_sqlite(db_path) as conn:
        for _, row in incoming.fillna("").iterrows():
            uid_literature = str(row.get("uid_literature") or "").strip()
            cite_key = str(row.get("cite_key") or "").strip()
            source_asset_uid = str(row.get("source_asset_uid") or "").strip()
            source_kind = str(row.get("source_kind") or "").strip() or "metadata"
            target_lang = str(row.get("target_lang") or "").strip() or "zh-CN"
            translation_scope = str(row.get("translation_scope") or "").strip() or source_kind
            provider = str(row.get("provider") or "").strip()
            model_name = str(row.get("model_name") or "").strip()
            asset_dir = str(row.get("asset_dir") or "").strip()
            translated_markdown_path = str(row.get("translated_markdown_path") or "").strip()
            translated_structured_path = str(row.get("translated_structured_path") or "").strip()
            translation_audit_path = str(row.get("translation_audit_path") or "").strip()
            status = str(row.get("status") or "").strip() or "ready"
            is_current = int(row.get("is_current") or 1)
            created_at = str(row.get("created_at") or "").strip() or now
            updated_at = str(row.get("updated_at") or "").strip() or now
            translation_uid = str(row.get("translation_uid") or "").strip()

            if not uid_literature and not cite_key:
                continue

            if not translation_uid:
                base = "|".join(
                    [
                        uid_literature,
                        cite_key,
                        source_asset_uid,
                        source_kind,
                        target_lang,
                        translation_scope,
                        translated_markdown_path,
                        translated_structured_path,
                        updated_at,
                    ]
                )
                translation_uid = f"tr-{abs(hash(base))}"

            if is_current:
                conn.execute(
                    f"""
                    UPDATE {TRANSLATION_ASSET_TABLE_NAME}
                    SET is_current = 0, updated_at = ?
                    WHERE uid_literature = ?
                      AND source_kind = ?
                      AND target_lang = ?
                      AND translation_scope = ?
                    """,
                    (updated_at, uid_literature, source_kind, target_lang, translation_scope),
                )

            conn.execute(
                f"""
                INSERT INTO {TRANSLATION_ASSET_TABLE_NAME}
                    (translation_uid, uid_literature, cite_key, source_asset_uid, source_kind, target_lang,
                     translation_scope, provider, model_name, asset_dir, translated_markdown_path,
                     translated_structured_path, translation_audit_path, status, is_current, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(translation_uid)
                DO UPDATE SET
                    uid_literature=excluded.uid_literature,
                    cite_key=excluded.cite_key,
                    source_asset_uid=excluded.source_asset_uid,
                    source_kind=excluded.source_kind,
                    target_lang=excluded.target_lang,
                    translation_scope=excluded.translation_scope,
                    provider=excluded.provider,
                    model_name=excluded.model_name,
                    asset_dir=excluded.asset_dir,
                    translated_markdown_path=excluded.translated_markdown_path,
                    translated_structured_path=excluded.translated_structured_path,
                    translation_audit_path=excluded.translation_audit_path,
                    status=excluded.status,
                    is_current=excluded.is_current,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at
                """,
                (
                    translation_uid,
                    uid_literature,
                    cite_key,
                    source_asset_uid,
                    source_kind,
                    target_lang,
                    translation_scope,
                    provider,
                    model_name,
                    asset_dir,
                    translated_markdown_path,
                    translated_structured_path,
                    translation_audit_path,
                    status,
                    is_current,
                    created_at,
                    updated_at,
                ),
            )
        conn.commit()


def backfill_content_relationships(db_path: str | Path) -> None:
    """根据兼容字段回填跨域关系表。"""

    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        literatures = pd.read_sql_query(
            "SELECT uid_literature, cite_key, standard_note_uid FROM literatures",
            conn,
        )
        knowledge = pd.read_sql_query(
            "SELECT uid_knowledge, note_type, uid_literature, cite_key, evidence_uids FROM knowledge_index",
            conn,
        )

        literature_uid_set = {
            str(uid).strip()
            for uid in literatures.get("uid_literature", pd.Series(dtype=str)).tolist()
            if str(uid).strip()
        }
        knowledge_uid_set = {
            str(uid).strip()
            for uid in knowledge.get("uid_knowledge", pd.Series(dtype=str)).tolist()
            if str(uid).strip()
        }
        literature_cite_lookup = {
            str(row.get("uid_literature") or "").strip(): str(row.get("cite_key") or "").strip()
            for _, row in literatures.fillna("").iterrows()
            if str(row.get("uid_literature") or "").strip()
        }

        link_rows: list[dict[str, object]] = []
        now = _utc_now_iso()
        for _, row in knowledge.fillna("").iterrows():
            uid_knowledge = str(row.get("uid_knowledge") or "").strip()
            uid_literature = str(row.get("uid_literature") or "").strip()
            if uid_knowledge and uid_literature and uid_knowledge in knowledge_uid_set and uid_literature in literature_uid_set:
                note_type = str(row.get("note_type") or "").strip()
                relation_type = "standard_note" if note_type == "literature_standard_note" else "mention"
                link_rows.append(
                    {
                        "uid_knowledge": uid_knowledge,
                        "uid_literature": uid_literature,
                        "relation_type": relation_type,
                        "is_primary": 1 if relation_type == "standard_note" else 0,
                        "cite_key": str(row.get("cite_key") or literature_cite_lookup.get(uid_literature) or "").strip(),
                        "source_field": "knowledge_index",
                        "created_at": now,
                        "updated_at": now,
                    }
                )

        evidence_rows: list[dict[str, object]] = []
        for _, row in knowledge.fillna("").iterrows():
            uid_knowledge = str(row.get("uid_knowledge") or "").strip()
            if not uid_knowledge or uid_knowledge not in knowledge_uid_set:
                continue
            for evidence_uid in _split_pipe_values(row.get("evidence_uids")):
                evidence_rows.append(
                    {
                        "uid_knowledge": uid_knowledge,
                        "evidence_type": "literature" if evidence_uid in literature_uid_set else "unknown",
                        "target_uid": evidence_uid,
                        "evidence_role": "supporting",
                        "source_field": "knowledge_index.evidence_uids",
                        "created_at": now,
                    }
                )

        for _, row in literatures.fillna("").iterrows():
            uid_literature = str(row.get("uid_literature") or "").strip()
            uid_knowledge = str(row.get("standard_note_uid") or "").strip()
            if uid_literature and uid_knowledge and uid_literature in literature_uid_set and uid_knowledge in knowledge_uid_set:
                link_rows.append(
                    {
                        "uid_knowledge": uid_knowledge,
                        "uid_literature": uid_literature,
                        "relation_type": "standard_note",
                        "is_primary": 1,
                        "cite_key": str(row.get("cite_key") or "").strip(),
                        "source_field": "literatures.standard_note_uid",
                        "created_at": now,
                        "updated_at": now,
                    }
                )

        link_df = pd.DataFrame(link_rows)
        if not link_df.empty:
            link_df = link_df.drop_duplicates(subset=["uid_knowledge", "uid_literature", "relation_type"], keep="last")
        else:
            link_df = pd.DataFrame(
                columns=[
                    "uid_knowledge",
                    "uid_literature",
                    "relation_type",
                    "is_primary",
                    "cite_key",
                    "source_field",
                    "created_at",
                    "updated_at",
                ]
            )

        evidence_df = pd.DataFrame(evidence_rows)
        if not evidence_df.empty:
            evidence_df = evidence_df.drop_duplicates(
                subset=["uid_knowledge", "evidence_type", "target_uid", "evidence_role"],
                keep="last",
            )
        else:
            evidence_df = pd.DataFrame(
                columns=[
                    "uid_knowledge",
                    "evidence_type",
                    "target_uid",
                    "evidence_role",
                    "source_field",
                    "created_at",
                ]
            )

        try:
            _replace_table_rows(conn, KNOWLEDGE_LINK_TABLE_NAME, link_df)
            _replace_table_rows(conn, KNOWLEDGE_EVIDENCE_TABLE_NAME, evidence_df)
        except sqlite3.OperationalError:
            # 兼容旧库：部分工作区把关系对象保留为 view 或历史外键契约，回填失败时跳过。
            pass
        conn.commit()


def upsert_knowledge_literature_link(
    db_path: str | Path,
    *,
    uid_knowledge: str,
    uid_literature: str,
    relation_type: str = "standard_note",
    is_primary: int = 1,
    cite_key: str = "",
    source_field: str = "manual_bind",
) -> None:
    """直接写入或更新知识-文献关系。"""

    init_content_db(db_path)
    now = _utc_now_iso()
    with connect_sqlite(db_path) as conn:
        conn.execute(
            f"""
            INSERT INTO {KNOWLEDGE_LINK_TABLE_NAME}
                (uid_knowledge, uid_literature, relation_type, is_primary, cite_key, source_field, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid_knowledge, uid_literature, relation_type)
            DO UPDATE SET
                is_primary = excluded.is_primary,
                cite_key = excluded.cite_key,
                source_field = excluded.source_field,
                updated_at = excluded.updated_at
            """,
            (
                uid_knowledge,
                uid_literature,
                relation_type,
                int(is_primary or 0),
                cite_key,
                source_field,
                now,
                now,
            ),
        )
        conn.commit()


__all__ = [
    "ATTACHMENT_LINK_TABLE_NAME",
    "ATTACHMENT_TABLE_NAME",
    "CONTENT_DB_DIRECTORY_NAME",
    "DEFAULT_CONTENT_DB_NAME",
    "KNOWLEDGE_EVIDENCE_TABLE_NAME",
    "KNOWLEDGE_LINK_TABLE_NAME",
    "KNOWLEDGE_NOTES_TABLE_NAME",
    "TRANSLATION_ASSET_TABLE_NAME",
    "READING_STATE_TABLE_NAME",
    "PDF_STRUCTURED_VARIANT_SPECS",
    "PDF_STRUCTURED_VARIANT_PATH_COLUMNS",
    "backfill_content_relationships",
    "build_pdf_structured_variant_dir_map",
    "connect_sqlite",
    "get_pdf_structured_variant_column",
    "get_pdf_structured_variant_spec",
    "infer_workspace_root_from_content_db",
    "init_content_db",
    "load_attachment_entities_df",
    "load_knowledge_evidence_links_df",
    "load_knowledge_literature_links_df",
    "load_literature_attachment_links_df",
    "load_translation_assets_df",
    "resolve_content_db_config",
    "resolve_content_db_path",
    "resolve_pdf_structured_variant_output_dir",
    "upsert_knowledge_literature_link",
    "upsert_translation_asset_rows",
]