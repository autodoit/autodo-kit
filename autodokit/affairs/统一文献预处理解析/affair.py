"""A050/A055 统一文献预处理事务。

该事务模块支持两种执行模式：
1. priority_only：用于 A050，只生成预处理优先级清单，不执行具体解析。
2. full_preprocess：用于 A055，按 profile 执行具体预处理。

full_preprocess 支持按 profile 调度 MonkeyOCR：
1. review：消费 `文献预处理` 的 A050_REVIEW 队列，产出 review_deep 资产并推进 A060。
2. non_review：消费 `文献预处理` 的 A050_NON_REVIEW 队列，产出 non_review_rough 资产并推进 A080。
3. mixed：自动按文献类型拆分到 review/non_review 两条子链执行。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from autodokit.path_compat import resolve_portable_path
from autodokit.tools import append_aok_log_event, build_gate_review, load_json_or_py
from autodokit.tools import normalize_to_legacy_contract
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.atomic.task_aok.task_instance_dir import (
    create_task_instance_dir,
    mirror_artifacts_to_legacy,
    resolve_legacy_output_dir,
)
from autodokit.tools.bibliodb_sqlite import (
    READING_QUEUE_TABLE_NAME,
    load_flow_state_df,
    load_reading_queue_df,
    upsert_parse_asset_rows,
    upsert_reading_queue_rows,
    upsert_flow_state_rows,
)
from autodokit.tools.contentdb_sqlite import (
    CONTENT_DB_DIRECTORY_NAME,
    DEFAULT_CONTENT_DB_NAME,
    LITERATURE_PARSE_STATE_COMPLETED,
    LITERATURE_PARSE_STATE_RUNNING,
    LITERATURE_TABLE_NAME,
    READING_QUEUE_TO_LITERATURE_COLUMN_MAP,
    derive_literature_parse_state,
    infer_workspace_root_from_content_db,
    resolve_content_db_config,
    resolve_content_physical_column,
)
from autodokit.tools.time_utils import now_compact
from autodokit.tools.ocr.runtime.monkeyocr_manifest_runtime import (
    _is_parse_asset_complete,
    _safe_stem,
    _update_preprocess_runtime_state,
    resolve_parse_runtime_settings,
    resolve_postprocess_settings,
    run_parse_manifest,
)
from autodokit.tools.ocr.monkeyocr.runner import launch_remote_tmux_command, stop_remote_monkeyocr_jobs
from autodokit.tools.storage_backend import load_reference_main_table


OUTPUT_GATE = "gate_review.json"
A055_DONE_MARKER_DEFAULT = "done_{timestamp}.txt"
A055_RUN_MODE_LOCAL_ONLY = "local_only"
A055_RUN_MODE_LOCAL_DISPATCH_REMOTE = "local_dispatch_remote"
A055_RUN_MODE_REMOTE_ONLY_TMUX = "remote_only_tmux"
A055_RUN_MODE_RECORD_PARSE_RESULTS = "record_parse_results"

DEFAULT_PRIORITY_FAMILY_WEIGHTS: Dict[str, float] = {
    "real_estate": 32.0,
    "systemic_risk": 32.0,
    "mechanism": 24.0,
}
DEFAULT_PRIORITY_POLICY: Dict[str, Any] = {
    "topic_name": "",
    "concept_families": {},
    "title_hit_bonus": 8.0,
    "meta_hit_bonus": 3.0,
    "multi_family_bonus": 10.0,
    "review_bonus": 15.0,
    "fulltext_bonus": 8.0,
    "recent_year_floor": 2020,
    "recent_year_bonus": 6.0,
}
COMPLETED_STATUS_TOKENS = {"completed", "done", "success", "succeeded", "successful", "已完成", "已处理", "成功"}
IN_PROGRESS_STATUS_TOKENS = {"in_progress", "running", "processing", "处理中", "执行中", "进行中"}
BLOCKED_STATUS_TOKENS = {"blocked", "阻塞", "missing_attachment", "需补件", "waiting_attachment"}
_A055_TIMESTAMP_DONE_MARKER_PATTERN = re.compile(r"^done_\d{14}\.txt$")


def _normalize_enum_value(key: str, value: Any, default: str = "") -> str:
    normalized = normalize_to_legacy_contract({key: value})
    if isinstance(normalized, dict):
        text = _stringify(normalized.get(key))
        if text:
            return text
    return _stringify(default)


def _resolve_a055_run_mode(raw_cfg: Dict[str, Any], *, parse_runtime: Dict[str, Any], execution_mode: str) -> str:
    """解析 A055 运行模式。"""

    if execution_mode == "priority_only":
        return "priority_only"

    env_override = _normalize_enum_value("run_mode", os.environ.get("A055_RUN_MODE_OVERRIDE")).lower()
    if env_override:
        return env_override

    configured = _normalize_enum_value("run_mode", raw_cfg.get("run_mode")).lower()
    if configured:
        return configured

    remote_cfg = parse_runtime.get("remote_processing") if isinstance(parse_runtime, dict) else {}
    if isinstance(remote_cfg, dict) and bool(remote_cfg.get("enabled")):
        return A055_RUN_MODE_LOCAL_DISPATCH_REMOTE
    return A055_RUN_MODE_LOCAL_ONLY


def _build_asset_probe_row(asset_dir: Path) -> Dict[str, Any]:
    normalized_structured_path = asset_dir / "normalized_structured.json"
    if not normalized_structured_path.exists():
        legacy_normalized_structured_path = asset_dir / "normalized.structured.json"
        if legacy_normalized_structured_path.exists():
            normalized_structured_path = legacy_normalized_structured_path

    return {
        "asset_dir": str(asset_dir),
        "normalized_structured_path": str(normalized_structured_path),
        "reconstructed_markdown_path": str(asset_dir / "reconstructed_content.md"),
        "parse_record_path": str(asset_dir / "parse_record.json"),
        "quality_report_path": str(asset_dir / "quality_report.json"),
    }


def _resolve_a055_asset_dir(
    workspace_root: Path,
    *,
    uid_literature: str,
    cite_key: str,
    title: str = "",
    asset_dir: str = "",
    primary_attachment_name: str = "",
    pdf_path: str = "",
    current_parse_path: str = "",
) -> Path:
    output_root = (workspace_root / "references" / "structured_monkeyocr_full").resolve()

    candidate = Path(_stringify(asset_dir)).expanduser()
    if _stringify(asset_dir):
        if not candidate.is_absolute():
            candidate = (workspace_root / candidate).resolve()
        if candidate.exists() and candidate.is_dir():
            return candidate

    current_parse_candidate = Path(_stringify(current_parse_path)).expanduser()
    if _stringify(current_parse_path):
        if not current_parse_candidate.is_absolute():
            current_parse_candidate = (workspace_root / current_parse_candidate).resolve()
        if current_parse_candidate.exists():
            if current_parse_candidate.is_dir():
                return current_parse_candidate
            return current_parse_candidate.parent

    candidate_keys = [
        _stringify(uid_literature),
        _stringify(cite_key),
        Path(_stringify(primary_attachment_name)).stem,
        Path(_stringify(pdf_path)).stem,
        _stringify(title),
    ]
    for key in candidate_keys:
        if not key:
            continue
        candidate_dir = (output_root / key).resolve()
        if candidate_dir.exists() and candidate_dir.is_dir():
            return candidate_dir

    fallback_key = next((key for key in candidate_keys if key), "")
    return (output_root / fallback_key).resolve()


def _write_a055_done_marker(asset_dir: Path, *, marker_name: str) -> str:
    marker_timestamp_text = now_compact()
    marker = asset_dir / _resolve_a055_done_marker_name(marker_name, marker_timestamp_text=marker_timestamp_text)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{marker_timestamp_text}\n", encoding="utf-8")
    return str(marker)


def _resolve_a055_done_marker_name(marker_name: str, *, marker_timestamp_text: str = "") -> str:
    resolved_name = _stringify(marker_name) or A055_DONE_MARKER_DEFAULT
    if "{timestamp}" in resolved_name:
        resolved_name = resolved_name.replace("{timestamp}", marker_timestamp_text or now_compact())
    return resolved_name


def _find_a055_done_marker(asset_dir: Path, *, marker_name: str) -> Path | None:
    if not asset_dir.exists() or not asset_dir.is_dir():
        return None

    explicit_name = _stringify(marker_name)
    if explicit_name and "{timestamp}" not in explicit_name:
        explicit_path = asset_dir / explicit_name
        if explicit_path.exists() and explicit_path.is_file():
            return explicit_path

    candidates = sorted(
        [
            path
            for path in asset_dir.iterdir()
            if path.is_file() and _A055_TIMESTAMP_DONE_MARKER_PATTERN.fullmatch(path.name)
        ],
        key=lambda item: item.name,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return None


def _collect_record_ready_rows(source_df: pd.DataFrame, *, workspace_root: Path, marker_name: str) -> pd.DataFrame:
    if source_df.empty:
        return source_df

    rows: List[Dict[str, Any]] = []
    for _, row in source_df.fillna("").iterrows():
        row_dict = dict(row.to_dict())
        uid_literature = _stringify(row_dict.get("uid_literature"))
        cite_key = _stringify(row_dict.get("cite_key"))
        asset_dir = _resolve_a055_asset_dir(
            workspace_root,
            uid_literature=uid_literature,
            cite_key=cite_key,
            title=_stringify(row_dict.get("title")) or _stringify(row_dict.get("标题")),
            asset_dir=_stringify(row_dict.get("asset_dir")),
            primary_attachment_name=_stringify(row_dict.get("primary_attachment_name")) or _stringify(row_dict.get("主附件名称")),
            pdf_path=_stringify(row_dict.get("pdf_path")) or _stringify(row_dict.get("PDF路径")),
            current_parse_path=_stringify(row_dict.get("current_parse_path")) or _stringify(row_dict.get("当前解析路径")),
        )
        marker_path = _find_a055_done_marker(asset_dir, marker_name=marker_name)
        is_complete, _ = _is_parse_asset_complete(_build_asset_probe_row(asset_dir))
        if not is_complete:
            continue

        row_dict["asset_dir"] = str(asset_dir)
        row_dict["done_marker_path"] = str(marker_path) if marker_path else ""
        rows.append(row_dict)

    return pd.DataFrame(rows)


def _apply_record_parse_results(content_db: Path, ready_df: pd.DataFrame, *, profile: str) -> None:
    if ready_df is None or ready_df.empty:
        return

    parse_level = "review_deep" if _stringify(profile).lower() == "review" else "non_review_rough"
    parse_rows: List[Dict[str, Any]] = []
    runtime_rows: List[Tuple[str, str, str, str, str]] = []

    for _, row in ready_df.fillna("").iterrows():
        row_dict = dict(row.to_dict())
        uid_literature = _stringify(row_dict.get("uid_literature"))
        cite_key = _stringify(row_dict.get("cite_key"))
        asset_dir = Path(_stringify(row_dict.get("asset_dir"))).expanduser()
        if not uid_literature and not cite_key:
            continue
        if not str(asset_dir):
            continue

        normalized_structured_path = asset_dir / "normalized_structured.json"
        if not normalized_structured_path.exists():
            normalized_structured_path = asset_dir / "normalized.structured.json"
        reconstructed_markdown_path = asset_dir / "reconstructed_content.md"
        parse_record_path = asset_dir / "parse_record.json"
        quality_report_path = asset_dir / "quality_report.json"

        parse_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "parse_level": parse_level,
                "backend": "monkeyocr_windows",
                "task_type": parse_level,
                "asset_dir": str(asset_dir),
                "normalized_structured_path": str(normalized_structured_path),
                "reconstructed_markdown_path": str(reconstructed_markdown_path),
                "parse_record_path": str(parse_record_path),
                "quality_report_path": str(quality_report_path),
                "parse_status": "ready",
                "parse_state": LITERATURE_PARSE_STATE_COMPLETED,
                "is_current": 1,
                "last_run_uid": _safe_stem(cite_key or uid_literature),
                "structured_updated_at": _stringify(row_dict.get("updated_at")),
            }
        )
        runtime_rows.append((uid_literature, cite_key, str(asset_dir), f"A050_{_stringify(profile).upper()}", _stringify(row_dict.get("updated_at"))))

    if parse_rows:
        upsert_parse_asset_rows(content_db, parse_rows)

    literature_uid_col = resolve_content_physical_column(LITERATURE_TABLE_NAME, "uid_literature")
    literature_cite_col = resolve_content_physical_column(LITERATURE_TABLE_NAME, "cite_key")
    literature_preprocess_state_col = READING_QUEUE_TO_LITERATURE_COLUMN_MAP["preprocess_state"]
    literature_preprocess_result_col = READING_QUEUE_TO_LITERATURE_COLUMN_MAP["preprocess_result_path"]
    literature_preprocess_failure_col = READING_QUEUE_TO_LITERATURE_COLUMN_MAP["preprocess_failure_reason"]
    literature_updated_col = READING_QUEUE_TO_LITERATURE_COLUMN_MAP["updated_at"]

    queue_stage_col = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "stage")
    queue_current_col = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "is_current")
    queue_uid_col = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "uid_literature")
    queue_cite_col = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "cite_key")
    queue_preprocess_state_col = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "preprocess_state")
    queue_preprocess_result_col = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "preprocess_result_path")
    queue_preprocess_failure_col = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "preprocess_failure_reason")
    queue_updated_col = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "updated_at")

    with sqlite3.connect(content_db) as conn:
        queue_object = conn.execute(
            "SELECT type FROM sqlite_master WHERE name = ? LIMIT 1",
            (READING_QUEUE_TABLE_NAME,),
        ).fetchone()
        queue_object_type = str(queue_object[0]).strip().lower() if queue_object and queue_object[0] else ""
        queue_is_table = bool(queue_object_type == "table")

        for uid_literature, cite_key, asset_dir_text, source_stage, updated_at in runtime_rows:
            effective_updated_at = updated_at or ""
            if uid_literature:
                conn.execute(
                    f'''
                    UPDATE {_quote_identifier(LITERATURE_TABLE_NAME)}
                       SET {_quote_identifier(literature_preprocess_state_col)} = ?,
                           {_quote_identifier(literature_preprocess_result_col)} = ?,
                           {_quote_identifier(literature_preprocess_failure_col)} = '',
                           {_quote_identifier(literature_updated_col)} = CASE WHEN ? <> '' THEN ? ELSE {_quote_identifier(literature_updated_col)} END
                     WHERE COALESCE({_quote_identifier(literature_uid_col)}, '') = ?
                    ''',
                    ("已处理", asset_dir_text, effective_updated_at, effective_updated_at, uid_literature),
                )
            elif cite_key:
                conn.execute(
                    f'''
                    UPDATE {_quote_identifier(LITERATURE_TABLE_NAME)}
                       SET {_quote_identifier(literature_preprocess_state_col)} = ?,
                           {_quote_identifier(literature_preprocess_result_col)} = ?,
                           {_quote_identifier(literature_preprocess_failure_col)} = '',
                           {_quote_identifier(literature_updated_col)} = CASE WHEN ? <> '' THEN ? ELSE {_quote_identifier(literature_updated_col)} END
                     WHERE COALESCE({_quote_identifier(literature_cite_col)}, '') = ?
                    ''',
                    ("已处理", asset_dir_text, effective_updated_at, effective_updated_at, cite_key),
                )

            if queue_is_table:
                conn.execute(
                    f'''
                    UPDATE {_quote_identifier(READING_QUEUE_TABLE_NAME)}
                       SET {_quote_identifier(queue_preprocess_state_col)} = ?,
                           {_quote_identifier(queue_preprocess_result_col)} = ?,
                           {_quote_identifier(queue_preprocess_failure_col)} = '',
                           {_quote_identifier(queue_updated_col)} = CASE WHEN ? <> '' THEN ? ELSE {_quote_identifier(queue_updated_col)} END
                     WHERE {_quote_identifier(queue_stage_col)} = ?
                       AND {_quote_identifier(queue_current_col)} = 1
                       AND (
                            (COALESCE({_quote_identifier(queue_uid_col)}, '') <> '' AND COALESCE({_quote_identifier(queue_uid_col)}, '') = ?)
                            OR (COALESCE({_quote_identifier(queue_uid_col)}, '') = '' AND COALESCE({_quote_identifier(queue_cite_col)}, '') = ?)
                       )
                    ''',
                    ("已处理", asset_dir_text, effective_updated_at, effective_updated_at, source_stage, uid_literature, cite_key),
                )
        conn.commit()


def _build_remote_only_command(raw_cfg: Dict[str, Any], *, config_path: Path) -> str:
    remote_only_cfg = raw_cfg.get("remote_only") if isinstance(raw_cfg.get("remote_only"), dict) else {}
    explicit_command = _stringify(remote_only_cfg.get("remote_command"))
    if explicit_command:
        return explicit_command

    remote_repo_root = _stringify(remote_only_cfg.get("remote_repo_root"))
    remote_python = _stringify(remote_only_cfg.get("remote_python_executable"))
    remote_config_path = _stringify(remote_only_cfg.get("remote_affair_config_path"))
    if not remote_config_path:
        remote_config_path = _stringify(remote_only_cfg.get("remote_config_path"))
    if not remote_repo_root or not remote_python or not remote_config_path:
        raise ValueError(
            "run_mode=remote_only_tmux 需要提供 remote_only.remote_command，或同时提供 "
            "remote_only.remote_repo_root + remote_only.remote_python_executable + remote_only.remote_affair_config_path。"
        )

    return (
        f"cd {remote_repo_root} && "
        f"A055_RUN_MODE_OVERRIDE={A055_RUN_MODE_LOCAL_ONLY} "
        f"{remote_python} -c \"from pathlib import Path; "
        f"from autodokit.affairs.统一文献预处理解析.affair import execute; "
        f"execute(Path(r'{remote_config_path}'))\""
    )


def _inspect_structured_output(workspace_root: Path, *, uid_literature: str, cite_key: str) -> tuple[str, str]:
    output_root = (workspace_root / "references" / "structured_monkeyocr_full").resolve()
    candidate_name = _stringify(uid_literature) or _stringify(cite_key)
    if not candidate_name:
        return "未处理", ""
    asset_dir = (output_root / candidate_name).resolve()
    is_complete, _ = _is_parse_asset_complete(
        {
            "asset_dir": str(asset_dir),
            "normalized_structured_path": str(asset_dir / "normalized_structured.json"),
            "reconstructed_markdown_path": str(asset_dir / "reconstructed_content.md"),
            "parse_record_path": str(asset_dir / "parse_record.json"),
            "quality_report_path": str(asset_dir / "quality_report.json"),
        }
    )
    done_marker = _find_a055_done_marker(asset_dir, marker_name=A055_DONE_MARKER_DEFAULT)
    if done_marker and is_complete:
        return "已处理", str(asset_dir)
    if is_complete:
        return "已处理", str(asset_dir)
    return "未处理", ""


def _runtime_guard_path(workspace_root: Path) -> Path:
    runtime_dir = workspace_root / "runtime" / "a055"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir / "active_run.json"


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate_local_process(pid: int) -> bool:
    if pid <= 0 or not _is_pid_alive(pid):
        return False
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        else:
            os.kill(pid, 15)
        return True
    except Exception:
        return False


def _stop_remote_a055_instances(parse_runtime: Dict[str, Any]) -> List[str]:
    result = stop_remote_monkeyocr_jobs(parse_runtime)
    if not result.get("enabled"):
        return []
    return ["remote_stopped" if result.get("killed") else "remote_stop_failed"]


def _takeover_previous_a055_run(*, workspace_root: Path, parse_runtime: Dict[str, Any], task_uid: str) -> List[str]:
    guard_path = _runtime_guard_path(workspace_root)
    actions: List[str] = []
    current_pid = os.getpid()
    previous: Dict[str, Any] = {}
    if guard_path.exists() and guard_path.is_file():
        try:
            previous = json.loads(guard_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}

    previous_pid = int(previous.get("pid") or 0)
    if previous_pid and previous_pid != current_pid and _is_pid_alive(previous_pid):
        if not _terminate_local_process(previous_pid):
            raise RuntimeError(f"A055 旧实例仍在运行，且本次接管未能终止该进程：pid={previous_pid}")
        if _is_pid_alive(previous_pid):
            raise RuntimeError(f"A055 旧实例终止后仍存活，拒绝并发启动：pid={previous_pid}")
        actions.append(f"local_killed:{previous_pid}")

    actions.extend(_stop_remote_a055_instances(parse_runtime))
    guard_path.write_text(
        json.dumps(
            {
                "pid": current_pid,
                "task_uid": task_uid,
                "workspace_root": str(workspace_root),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return actions


def _release_a055_runtime_guard(workspace_root: Path) -> None:
    guard_path = _runtime_guard_path(workspace_root)
    if not guard_path.exists() or not guard_path.is_file():
        return
    try:
        payload = json.loads(guard_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if int(payload.get("pid") or 0) == os.getpid():
        guard_path.unlink(missing_ok=True)


def _emit_progress(node_code: str, message: str) -> None:
    """输出最小终端进度日志。"""

    print(f"[{node_code}] {message}", flush=True)


def _stringify(value: Any) -> str:
    """把任意值标准化为字符串。

    Args:
        value: 任意输入值。

    Returns:
        去空白后的字符串。
    """

    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _normalize_terms(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [term for term in (_stringify(item).lower() for item in value) if term]
    text = _stringify(value)
    if not text:
        return []
    return [part for part in re.split(r"[,;；、|\n]+", text.lower()) if part]


def _resolve_priority_policy(raw_cfg: Dict[str, Any]) -> Dict[str, Any]:
    processing_settings = raw_cfg.get("processing_settings")
    if not isinstance(processing_settings, dict):
        processing_settings = raw_cfg.get("处理设置") if isinstance(raw_cfg.get("处理设置"), dict) else {}

    raw_policy = processing_settings.get("priority_policy")
    if not isinstance(raw_policy, dict):
        raw_policy = processing_settings.get("优先级策略") if isinstance(processing_settings.get("优先级策略"), dict) else {}
    if not isinstance(raw_policy, dict):
        raw_policy = raw_cfg.get("priority_policy") if isinstance(raw_cfg.get("priority_policy"), dict) else {}
    if not isinstance(raw_policy, dict):
        raw_policy = raw_cfg.get("优先级策略") if isinstance(raw_cfg.get("优先级策略"), dict) else {}
    if not isinstance(raw_policy, dict):
        raw_policy = {}

    concept_families: Dict[str, Dict[str, Any]] = {}
    raw_families = raw_policy.get("concept_families")
    if not isinstance(raw_families, dict):
        raw_families = raw_policy.get("概念家族") if isinstance(raw_policy.get("概念家族"), dict) else {}
    if isinstance(raw_families, dict):
        for family_name, spec in raw_families.items():
            if isinstance(spec, dict):
                terms = _normalize_terms(spec.get("terms") or spec.get("关键词") or [])
                weight = _safe_float(spec.get("weight") or spec.get("权重"), DEFAULT_PRIORITY_FAMILY_WEIGHTS.get(str(family_name), 20.0))
            else:
                terms = _normalize_terms(spec)
                weight = DEFAULT_PRIORITY_FAMILY_WEIGHTS.get(str(family_name), 20.0)
            if terms:
                concept_families[str(family_name)] = {"terms": terms, "weight": weight}

    if not concept_families:
        fallback_families = {
            "real_estate": raw_policy.get("real_estate_terms") or raw_policy.get("房地产关键词") or [],
            "systemic_risk": raw_policy.get("systemic_risk_terms") or raw_policy.get("系统性风险关键词") or [],
            "mechanism": raw_policy.get("mechanism_terms") or raw_policy.get("机制关键词") or [],
        }
        for family_name, terms_raw in fallback_families.items():
            terms = _normalize_terms(terms_raw)
            if terms:
                concept_families[family_name] = {
                    "terms": terms,
                    "weight": DEFAULT_PRIORITY_FAMILY_WEIGHTS.get(family_name, 20.0),
                }

    policy = dict(DEFAULT_PRIORITY_POLICY)
    policy.update(
        {
            "topic_name": _stringify(raw_policy.get("topic_name") or raw_policy.get("主题名称")),
            "concept_families": concept_families,
            "title_hit_bonus": _safe_float(raw_policy.get("title_hit_bonus") or raw_policy.get("标题命中奖励"), DEFAULT_PRIORITY_POLICY["title_hit_bonus"]),
            "meta_hit_bonus": _safe_float(raw_policy.get("meta_hit_bonus") or raw_policy.get("摘要关键词命中奖励"), DEFAULT_PRIORITY_POLICY["meta_hit_bonus"]),
            "multi_family_bonus": _safe_float(raw_policy.get("multi_family_bonus") or raw_policy.get("多家族命中奖励"), DEFAULT_PRIORITY_POLICY["multi_family_bonus"]),
            "review_bonus": _safe_float(raw_policy.get("review_bonus") or raw_policy.get("综述奖励"), DEFAULT_PRIORITY_POLICY["review_bonus"]),
            "fulltext_bonus": _safe_float(raw_policy.get("fulltext_bonus") or raw_policy.get("全文奖励"), DEFAULT_PRIORITY_POLICY["fulltext_bonus"]),
            "recent_year_floor": int(raw_policy.get("recent_year_floor") or raw_policy.get("近期年份下限") or DEFAULT_PRIORITY_POLICY["recent_year_floor"]),
            "recent_year_bonus": _safe_float(raw_policy.get("recent_year_bonus") or raw_policy.get("近期年份奖励"), DEFAULT_PRIORITY_POLICY["recent_year_bonus"]),
            "context_sources": [
                _stringify(item)
                for item in list(raw_policy.get("context_sources") or raw_policy.get("上下文来源") or [])
                if _stringify(item)
            ],
        }
    )
    return policy


def _collect_priority_texts(row: Dict[str, Any]) -> Dict[str, str]:
    title_text = " ".join(
        part for part in [
            _stringify(row.get("title")),
            _stringify(row.get("title_zh")),
            _stringify(row.get("clean_title")),
            _stringify(row.get("bib_title")),
        ] if part
    ).lower()
    meta_text = " ".join(
        part for part in [
            _stringify(row.get("keywords")),
            _stringify(row.get("keywords_zh")),
            _stringify(row.get("bib_keywords")),
            _stringify(row.get("abstract")),
            _stringify(row.get("abstract_zh")),
            _stringify(row.get("bib_abstract")),
        ] if part
    ).lower()
    full_text = " ".join(part for part in [title_text, meta_text] if part)
    return {"title": title_text, "meta": meta_text, "full": full_text}


def _extract_year_value(row: Dict[str, Any]) -> int:
    for candidate in [row.get("year"), row.get("bib_year")]:
        text = _stringify(candidate)
        if not text:
            continue
        match = re.search(r"(19|20)\d{2}", text)
        if match:
            return int(match.group(0))
    return 0


def _row_has_fulltext(row: Dict[str, Any]) -> bool:
    flag = _stringify(row.get("has_fulltext")).lower()
    if flag and flag not in {"0", "false", "none", "nan"}:
        return True
    return bool(_stringify(row.get("pdf_path")) or _stringify(row.get("PDF路径")) or _stringify(row.get("primary_attachment_name")) or _stringify(row.get("主附件名称")))


def _normalize_status_token(value: Any) -> str:
    text = _stringify(value).lower()
    return text.replace("-", "_").replace(" ", "_")


def _resolve_existing_result_path(row: Dict[str, Any], workspace_root: Path) -> str:
    for candidate in [row.get("current_parse_path"), row.get("预处理结果路径")]:
        raw = _stringify(candidate)
        if not raw:
            continue
        try:
            resolved = resolve_portable_path(raw, base=workspace_root)
        except Exception:
            resolved = Path(raw).expanduser()
        if resolved.exists():
            if resolved.is_dir():
                is_complete, _ = _is_parse_asset_complete(_build_asset_probe_row(resolved))
                if is_complete:
                    return str(resolved)
            else:
                return str(resolved)
        return raw
    return ""


def _resolve_queue_runtime_status(row: Dict[str, Any], *, workspace_root: Path) -> Tuple[str, str, str]:
    existing_queue_status = _normalize_status_token(row.get("预处理队列状态") or row.get("queue_status"))
    existing_preprocess_state = _normalize_status_token(row.get("预处理执行状态") or row.get("preprocess_state"))
    existing_parse_state = derive_literature_parse_state(
        parse_state=row.get("parse_state") or row.get("解析状态"),
        current_parse_status=row.get("current_parse_status"),
        structured_status=row.get("structured_status"),
        preprocess_state=row.get("预处理执行状态") or row.get("preprocess_state"),
        has_parse_result=bool(_resolve_existing_result_path(row, workspace_root)),
    )
    result_path = _resolve_existing_result_path(row, workspace_root)

    if existing_parse_state == LITERATURE_PARSE_STATE_RUNNING or (
        existing_queue_status in IN_PROGRESS_STATUS_TOKENS and existing_parse_state != LITERATURE_PARSE_STATE_COMPLETED
    ):
        return "in_progress", "处理中", result_path

    if existing_parse_state == LITERATURE_PARSE_STATE_COMPLETED or (
        existing_queue_status in COMPLETED_STATUS_TOKENS
        or existing_preprocess_state in COMPLETED_STATUS_TOKENS
        or bool(result_path)
    ):
        return "completed", "已处理", result_path

    if _row_has_fulltext(row):
        return "queued", "未处理", result_path

    if existing_queue_status in BLOCKED_STATUS_TOKENS or existing_preprocess_state in BLOCKED_STATUS_TOKENS:
        return "blocked", "missing_attachment", result_path
    return "blocked", "missing_attachment", result_path


def _score_priority_row(row: Dict[str, Any], *, policy: Dict[str, Any], profile: str, has_fulltext: bool) -> Tuple[float, List[str]]:
    texts = _collect_priority_texts(row)
    title_text = texts["title"]
    meta_text = texts["meta"]
    full_text = texts["full"]
    family_hits: List[str] = []
    score = 0.0

    for family_name, family_spec in (policy.get("concept_families") or {}).items():
        terms = [term for term in family_spec.get("terms", []) if term]
        if not terms:
            continue
        title_hit = any(term in title_text for term in terms)
        meta_hit_count = sum(1 for term in terms if term in meta_text)
        if not title_hit and meta_hit_count <= 0 and not any(term in full_text for term in terms):
            continue
        family_hits.append(str(family_name))
        score += _safe_float(family_spec.get("weight"), DEFAULT_PRIORITY_FAMILY_WEIGHTS.get(str(family_name), 20.0))
        if title_hit:
            score += _safe_float(policy.get("title_hit_bonus"), DEFAULT_PRIORITY_POLICY["title_hit_bonus"])
        score += min(meta_hit_count, 3) * _safe_float(policy.get("meta_hit_bonus"), DEFAULT_PRIORITY_POLICY["meta_hit_bonus"])

    if len(family_hits) >= 2:
        score += (len(family_hits) - 1) * _safe_float(policy.get("multi_family_bonus"), DEFAULT_PRIORITY_POLICY["multi_family_bonus"])
    if profile == "review":
        score += _safe_float(policy.get("review_bonus"), DEFAULT_PRIORITY_POLICY["review_bonus"])
    if has_fulltext:
        score += _safe_float(policy.get("fulltext_bonus"), DEFAULT_PRIORITY_POLICY["fulltext_bonus"])

    year_value = _extract_year_value(row)
    recent_year_floor = int(policy.get("recent_year_floor") or DEFAULT_PRIORITY_POLICY["recent_year_floor"])
    if year_value >= recent_year_floor:
        score += _safe_float(policy.get("recent_year_bonus"), DEFAULT_PRIORITY_POLICY["recent_year_bonus"])
        score += min(max(year_value - recent_year_floor, 0), 5) * 0.5

    return score, family_hits


def _bucket_from_row(*, queue_status: str, family_hits: List[str]) -> str:
    if queue_status == "completed":
        return "already_preprocessed"
    if queue_status == "blocked":
        return "missing_fulltext"
    if len(family_hits) >= 3:
        return "topic_core"
    if len(family_hits) >= 2:
        return "topic_related"
    if len(family_hits) == 1:
        return "topic_weakly_related"
    return "background"


def _build_full_library_priority_rows(
    *,
    content_db: Path,
    literature_df: pd.DataFrame,
    workspace_root: Path,
    raw_cfg: Dict[str, Any],
    run_uid: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    policy = _resolve_priority_policy(raw_cfg)
    topic_name = _stringify(policy.get("topic_name")) or "全库后台预处理"
    scope_key = f"all_library::{topic_name}"
    now_iso = pd.Timestamp.now("UTC").isoformat()

    ranking_rows: List[Dict[str, Any]] = []
    for _, row in literature_df.fillna("").iterrows():
        row_dict = dict(row.to_dict())
        uid_literature = _stringify(row_dict.get("uid_literature"))
        cite_key = _stringify(row_dict.get("cite_key")) or uid_literature
        if not uid_literature and not cite_key:
            continue

        profile = _infer_profile(row_dict)
        has_fulltext = _row_has_fulltext(row_dict)
        queue_status, preprocess_state, result_path = _resolve_queue_runtime_status(row_dict, workspace_root=workspace_root)
        score, family_hits = _score_priority_row(row_dict, policy=policy, profile=profile, has_fulltext=has_fulltext)
        status_bucket = {"in_progress": 0, "queued": 1, "blocked": 2, "completed": 3}.get(queue_status, 4)
        year_value = _extract_year_value(row_dict)

        ranking_rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "title": _stringify(row_dict.get("title")),
                "first_author": _stringify(row_dict.get("first_author")),
                "year": _stringify(row_dict.get("year")),
                "preprocess_profile": profile,
                "queue_status": queue_status,
                "preprocess_state": preprocess_state,
                "preprocess_result_path": result_path,
                "has_fulltext": 1 if has_fulltext else 0,
                "topic_score": round(score, 4),
                "family_hits": "/".join(family_hits),
                "status_bucket": status_bucket,
                "year_value": year_value,
                "recommended_reason": (
                    f"A050 全库优先级重排：{topic_name}；匹配家族={('/'.join(family_hits) or 'general')}；"
                    f"状态={queue_status}"
                ),
                "theme_relation": "/".join(family_hits) or topic_name,
            }
        )

    ranking_df = pd.DataFrame(ranking_rows)
    if ranking_df.empty:
        return pd.DataFrame(), ranking_df

    ranking_df = ranking_df.sort_values(
        by=["status_bucket", "topic_score", "year_value", "preprocess_profile", "title", "cite_key"],
        ascending=[True, False, False, True, True, True],
        na_position="last",
    ).reset_index(drop=True)
    ranking_df["priority"] = ranking_df.index + 1

    queue_rows: List[Dict[str, Any]] = []
    for _, row in ranking_df.fillna("").iterrows():
        profile = _stringify(row.get("preprocess_profile")) or "non_review"
        queue_rows.append(
            {
                "uid_literature": _stringify(row.get("uid_literature")),
                "cite_key": _stringify(row.get("cite_key")),
                "stage": f"A050_{profile.upper()}",
                "source_affair": "A050",
                "queue_status": _stringify(row.get("queue_status")) or "queued",
                "decision": "preserve_in_progress" if _stringify(row.get("queue_status")) == "in_progress" else "ranked",
                "priority": int(row.get("priority") or 0),
                "bucket": _bucket_from_row(queue_status=_stringify(row.get("queue_status")), family_hits=_stringify(row.get("family_hits")).split("/") if _stringify(row.get("family_hits")) else []),
                "preferred_next_stage": "A060" if profile == "review" else "A080",
                "recommended_reason": _stringify(row.get("recommended_reason")),
                "theme_relation": _stringify(row.get("theme_relation")),
                "preprocess_state": _stringify(row.get("preprocess_state")),
                "preprocess_result_path": _stringify(row.get("preprocess_result_path")),
                "preprocess_started_at": _stringify(row.get("预处理开始时间")) or _stringify(row.get("preprocess_started_at")),
                "preprocess_finished_at": _stringify(row.get("预处理完成时间")) or _stringify(row.get("preprocess_finished_at")),
                "preprocess_failure_reason": "缺少主 PDF 附件" if _stringify(row.get("queue_status")) == "blocked" else "",
                "source_round": "a050_all_library",
                "run_uid": run_uid,
                "scope_key": scope_key,
                "is_current": 1,
                "created_at": _stringify(row.get("预处理创建时间")) or now_iso,
                "updated_at": now_iso,
            }
        )

    queue_df = pd.DataFrame(queue_rows)
    return queue_df, ranking_df


def _priority_sort_value(value: Any) -> int:
    text = _stringify(value)
    if not text:
        return 10**12
    try:
        return int(float(text))
    except Exception:
        return 10**12


def _build_profile_execution_batches(
    *,
    review_source: pd.DataFrame,
    non_review_source: pd.DataFrame,
) -> List[Tuple[str, pd.DataFrame]]:
    tagged_frames: List[pd.DataFrame] = []
    if not review_source.empty:
        review_tagged = review_source.copy()
        review_tagged["preprocess_profile"] = "review"
        tagged_frames.append(review_tagged)
    if not non_review_source.empty:
        non_review_tagged = non_review_source.copy()
        non_review_tagged["preprocess_profile"] = "non_review"
        tagged_frames.append(non_review_tagged)
    if not tagged_frames:
        return []
    if len(tagged_frames) == 1:
        frame = tagged_frames[0].copy().reset_index(drop=True)
        return [(_stringify(frame.iloc[0].get("preprocess_profile")) or "non_review", frame.drop(columns=["preprocess_profile"], errors="ignore"))]

    combined = pd.concat(tagged_frames, ignore_index=True, sort=False).fillna("")
    combined["_priority_sort_value"] = combined.get("priority", pd.Series(dtype=object)).apply(_priority_sort_value)
    combined = combined.sort_values(
        by=["_priority_sort_value", "updated_at", "cite_key", "uid_literature"],
        ascending=[True, True, True, True],
        na_position="last",
    ).reset_index(drop=True)

    batches: List[Tuple[str, pd.DataFrame]] = []
    current_profile = ""
    current_rows: List[Dict[str, Any]] = []
    for _, row in combined.iterrows():
        row_dict = dict(row.to_dict())
        row_profile = _stringify(row_dict.pop("preprocess_profile")) or "non_review"
        row_dict.pop("_priority_sort_value", None)
        if current_profile and row_profile != current_profile:
            batches.append((current_profile, pd.DataFrame(current_rows)))
            current_rows = []
        current_profile = row_profile
        current_rows.append(row_dict)

    if current_rows:
        batches.append((current_profile or "non_review", pd.DataFrame(current_rows)))
    return batches


def _resolve_workspace_root(config_path: Path, raw_cfg: Dict[str, Any]) -> Path:
    """解析 workspace_root。

    Args:
        config_path: 配置文件路径。
        raw_cfg: 事务配置。

    Returns:
        工作区根目录绝对路径。

    Raises:
        ValueError: 当 workspace_root 不是绝对路径时抛出。
    """

    config_path = Path(config_path)
    candidate = _stringify(raw_cfg.get("workspace_root"))
    if candidate:
        return resolve_portable_path(candidate, base=config_path.parent)
    return config_path.parents[2]


def _resolve_global_config_path(workspace_root: Path) -> Path | None:
    candidate = workspace_root / "config" / "config.json"
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _ensure_literature_type_column(content_db: Path, *, auto_fill: bool) -> None:
    """确保文献主表的文献类型字段存在，并按启发式回填。

    Args:
        content_db: content.db 路径。
        auto_fill: 是否自动回填空值。
    """

    with sqlite3.connect(content_db) as conn:
        cols = [row[1] for row in conn.execute(f'PRAGMA table_info("{LITERATURE_TABLE_NAME}")').fetchall()]
        literature_type_column = resolve_content_physical_column(LITERATURE_TABLE_NAME, "literature_type")
        entry_type_column = resolve_content_physical_column(LITERATURE_TABLE_NAME, "entry_type")
        structured_task_type_column = resolve_content_physical_column(LITERATURE_TABLE_NAME, "structured_task_type")
        title_column = resolve_content_physical_column(LITERATURE_TABLE_NAME, "title")

        if literature_type_column not in cols:
            conn.execute(f'ALTER TABLE "{LITERATURE_TABLE_NAME}" ADD COLUMN "{literature_type_column}" TEXT DEFAULT ""')
            conn.commit()

        if not auto_fill:
            return

        review_conditions: List[str] = []
        if entry_type_column in cols:
            review_conditions.append(f"LOWER(COALESCE(\"{entry_type_column}\", '')) IN ('review', 'survey')")
        if structured_task_type_column in cols:
            review_conditions.append(f"LOWER(COALESCE(\"{structured_task_type_column}\", '')) LIKE 'review%'")
        if title_column in cols:
            review_conditions.extend(
                [
                    f"COALESCE(\"{title_column}\", '') LIKE '%综述%'",
                    f"COALESCE(\"{title_column}\", '') LIKE '%系统评价%'",
                    f"COALESCE(\"{title_column}\", '') LIKE '%meta-analysis%'",
                    f"COALESCE(\"{title_column}\", '') LIKE '%meta analysis%'",
                ]
            )

        if review_conditions:
            conn.execute(
                f"""
                    UPDATE "文献主表"
                       SET "{literature_type_column}" = 'review'
                     WHERE COALESCE("{literature_type_column}", '') = ''
                       AND (
                            {' OR '.join(review_conditions)}
                       )
                """
            )
        conn.execute(
            f"""
                UPDATE "文献主表"
                   SET "{literature_type_column}" = 'non_review'
                 WHERE COALESCE("{literature_type_column}", '') = ''
            """
        )
        conn.commit()


def _merge_with_literatures(state_df: pd.DataFrame, literature_df: pd.DataFrame) -> pd.DataFrame:
    if state_df.empty:
        return pd.DataFrame()
    merged = state_df.copy()
    merged["uid_literature"] = merged.get("uid_literature", pd.Series(dtype=str)).astype(str)
    if not literature_df.empty and "uid_literature" in literature_df.columns:
        table = literature_df.copy()
        table["uid_literature"] = table.get("uid_literature", pd.Series(dtype=str)).astype(str)
        merged = merged.merge(table, on="uid_literature", how="left", suffixes=("_state", ""))
    merged["cite_key"] = merged.get("cite_key", merged.get("cite_key_state", pd.Series(dtype=str))).fillna("")
    return merged.fillna("")


def _load_flow_seed_source_df(content_db: Path, *, profile: str) -> pd.DataFrame:
    """从统一流程状态表装载 A050 可执行输入，并补齐队列字段名。"""

    normalized_profile = _stringify(profile).lower()
    if normalized_profile == "review":
        flow_df = load_flow_state_df(
            content_db,
            flag_filters={
                "流程轨道": "综述主链",
                "当前阶段": "综述正文解析",
                "当前状态": "待处理",
            },
        )
    elif normalized_profile == "non_review":
        flow_df = load_flow_state_df(
            content_db,
            flag_filters={
                "流程轨道": "普通主链",
                "当前阶段": "普通文献预处理",
                "当前状态": "待处理",
            },
        )
    else:
        raise ValueError("profile 仅支持 review/non_review")

    if flow_df.empty:
        return flow_df

    queue_columns = {
        "来源阶段": "source_stage",
        "来源类型": "source_origin",
        "推荐原因": "recommended_reason",
        "主题关系": "theme_relation",
        "阅读目标": "reading_objective",
        "人工提示": "manual_guidance",
        "最近任务UID": "run_uid",
        "uid_最近任务": "run_uid",
        "最近批次ID": "task_batch_id",
        "uid_最近批次": "task_batch_id",
        "更新时间": "updated_at",
        "创建时间": "created_at",
    }
    working = flow_df.copy()
    for source_column, target_column in queue_columns.items():
        if target_column not in working.columns and source_column in working.columns:
            working[target_column] = working[source_column]
    return working


def _seed_a050_queue_rows(content_db: Path, profile: str, source_df: pd.DataFrame) -> int:
    """把现有状态表回填为 A050 队列行，便于后续统一从队列消费。"""

    if source_df is None or source_df.empty:
        return 0

    normalized_profile = _stringify(profile).lower()
    if normalized_profile not in {"review", "non_review"}:
        raise ValueError("profile 仅支持 review/non_review")

    stage = f"A050_{normalized_profile.upper()}"
    workspace_root = infer_workspace_root_from_content_db(content_db)
    rows: List[Dict[str, Any]] = []
    for _, row in source_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        if not uid_literature and not cite_key:
            continue

        preprocess_state, preprocess_result_path = _inspect_structured_output(
            workspace_root,
            uid_literature=uid_literature,
            cite_key=cite_key,
        )

        priority_value = row.get("a05_current_score") or row.get("priority")
        if pd.isna(priority_value):
            priority_value = None

        next_stage = "A060" if normalized_profile == "review" else "A080"
        bucket = "review_parse_ready" if normalized_profile == "review" else "non_review_preprocess"
        recommended_reason = _stringify(row.get("recommended_reason"))
        if not recommended_reason:
            recommended_reason = "A050 状态回填到队列"

        rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "stage": stage,
                "source_affair": "A050",
                "queue_status": "queued",
                "decision": "",
                "priority": priority_value,
                "bucket": bucket,
                "preferred_next_stage": next_stage,
                "recommended_reason": recommended_reason,
                "theme_relation": _stringify(row.get("theme_relation")) or f"A050_{normalized_profile}",
                "preprocess_state": preprocess_state,
                "preprocess_result_path": preprocess_result_path,
                "preprocess_started_at": "",
                "preprocess_finished_at": "",
                "preprocess_failure_reason": "",
                "source_round": "a050",
                "run_uid": _stringify(row.get("run_uid")),
                "scope_key": f"a050_{normalized_profile}_queue",
                "is_current": 1,
                "updated_at": _stringify(row.get("updated_at")),
            }
        )

    if rows:
        upsert_reading_queue_rows(content_db, rows)
    return len(rows)


def _load_a050_queue_source_df(
    content_db: Path,
    literature_df: pd.DataFrame,
    *,
    profile: str,
) -> pd.DataFrame:
    """从 A050 队列读取待处理条目；队列为空时仅用正式流程状态生成队列。"""

    normalized_profile = _stringify(profile).lower()
    if normalized_profile not in {"review", "non_review"}:
        raise ValueError("profile 仅支持 review/non_review")

    stage = f"A050_{normalized_profile.upper()}"
    queue_df = load_reading_queue_df(
        content_db,
        stage=stage,
        only_current=True,
        queue_statuses=["queued", "candidate", "in_progress"],
    )
    if queue_df.empty:
        state_df = _load_flow_seed_source_df(content_db, profile=normalized_profile)
        seeded_source = _merge_with_literatures(state_df, literature_df)
        if not seeded_source.empty:
            _seed_a050_queue_rows(content_db, normalized_profile, seeded_source)
            queue_df = load_reading_queue_df(
                content_db,
                stage=stage,
                only_current=True,
                queue_statuses=["queued", "candidate", "in_progress"],
            )

    merged = _merge_with_literatures(queue_df, literature_df)
    if merged.empty:
        return merged
    merged["preprocess_profile"] = normalized_profile
    return merged


def _load_review_pending_df(content_db: Path, literature_df: pd.DataFrame) -> pd.DataFrame:
    return _load_a050_queue_source_df(content_db, literature_df, profile="review")


def _load_non_review_pending_df(content_db: Path, literature_df: pd.DataFrame) -> pd.DataFrame:
    return _load_a050_queue_source_df(content_db, literature_df, profile="non_review")


def _load_record_parse_source_df(literature_df: pd.DataFrame, *, profile: str) -> pd.DataFrame:
    if literature_df.empty:
        return pd.DataFrame()
    normalized_profile = _stringify(profile).lower()
    if normalized_profile not in {"review", "non_review"}:
        raise ValueError("profile 仅支持 review/non_review")

    working = literature_df.fillna("").copy()
    records: List[Dict[str, Any]] = []
    for _, row in working.iterrows():
        row_dict = dict(row.to_dict())
        inferred_profile = _infer_profile(row_dict)
        if inferred_profile != normalized_profile:
            continue
        row_dict["preprocess_profile"] = normalized_profile
        row_dict.setdefault("stage", f"A050_{normalized_profile.upper()}")
        records.append(row_dict)
    return pd.DataFrame(records)


def _infer_profile(row: Dict[str, Any]) -> str:
    """在 mixed 模式下推断条目应走 review 还是 non_review。"""

    literature_type = _stringify(row.get("literature_type")).lower()
    structured_task_type = _stringify(row.get("structured_task_type")).lower()
    title = _stringify(row.get("title")).lower()

    if literature_type in {"review", "综述"}:
        return "review"
    if structured_task_type.startswith("review"):
        return "review"
    if any(token in title for token in ["综述", "系统评价", "meta-analysis", "meta analysis"]):
        return "review"
    return "non_review"


def _split_sources_by_profile(
    *,
    profile: str,
    review_df: pd.DataFrame,
    non_review_df: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """按 profile 输出可执行的数据源。"""

    if profile == "review":
        return {"review": review_df}
    if profile == "non_review":
        return {"non_review": non_review_df}

    mixed_df = pd.concat([review_df, non_review_df], ignore_index=True, sort=False)
    if mixed_df.empty:
        return {"review": pd.DataFrame(), "non_review": pd.DataFrame()}

    mixed_df = mixed_df.fillna("")
    mixed_df["uid_literature"] = mixed_df.get("uid_literature", pd.Series(dtype=str)).astype(str)
    mixed_df["cite_key"] = mixed_df.get("cite_key", pd.Series(dtype=str)).astype(str)
    mixed_df["identity"] = mixed_df["uid_literature"] + "::" + mixed_df["cite_key"]
    mixed_df = mixed_df.drop_duplicates(subset=["identity"], keep="first")

    review_rows: List[Dict[str, Any]] = []
    non_review_rows: List[Dict[str, Any]] = []
    for _, row in mixed_df.iterrows():
        row_dict = dict(row.to_dict())
        if _infer_profile(row_dict) == "review":
            row_dict["preprocess_profile"] = "review"
            review_rows.append(row_dict)
        else:
            row_dict["preprocess_profile"] = "non_review"
            non_review_rows.append(row_dict)

    return {
        "review": pd.DataFrame(review_rows),
        "non_review": pd.DataFrame(non_review_rows),
    }


def _run_profile_parse(
    *,
    profile: str,
    source_df: pd.DataFrame,
    content_db: Path,
    output_dir: Path,
    parse_runtime: Dict[str, Any],
    postprocess_settings: Dict[str, Any],
    global_config_path: Path | None,
    max_items: int,
) -> Dict[str, Any]:
    """执行单 profile 解析。"""

    if profile == "review":
        return run_parse_manifest(
            content_db=content_db,
            source_df=source_df,
            output_dir=output_dir,
            source_stage="A050_REVIEW",
            upstream_stage="A050",
            downstream_stage="A060",
            parse_level="review_deep",
            literature_scope="review",
            runtime_settings=parse_runtime,
            postprocess_settings=postprocess_settings,
            global_config_path=global_config_path,
            overwrite_existing=False,
            max_items=max_items,
        )

    return run_parse_manifest(
        content_db=content_db,
        source_df=source_df,
        output_dir=output_dir,
        source_stage="A050_NON_REVIEW",
        upstream_stage="A050",
        downstream_stage="A080",
        parse_level="non_review_rough",
        literature_scope="non_review",
        runtime_settings=parse_runtime,
        postprocess_settings=postprocess_settings,
        global_config_path=global_config_path,
        overwrite_existing=False,
        max_items=max_items,
    )


def _consume_current_stage_queue_rows(content_db: Path, *, stage: str, ready_df: pd.DataFrame) -> int:
    if ready_df is None or ready_df.empty:
        return 0

    identities: List[Tuple[str, str]] = []
    for _, row in ready_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        if not uid_literature and not cite_key:
            continue
        identities.append((uid_literature, cite_key))

    if not identities:
        return 0

    with sqlite3.connect(content_db) as conn:
        queue_object = conn.execute(
            "SELECT type FROM sqlite_master WHERE name = ? LIMIT 1",
            (READING_QUEUE_TABLE_NAME,),
        ).fetchone()

    queue_object_type = str(queue_object[0]).strip().lower() if queue_object and queue_object[0] else ""
    if queue_object_type and queue_object_type != "table":
        fallback_rows: List[Dict[str, Any]] = []
        for _, row in ready_df.fillna("").iterrows():
            uid_literature = _stringify(row.get("uid_literature"))
            cite_key = _stringify(row.get("cite_key"))
            if not uid_literature and not cite_key:
                continue
            fallback_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "stage": stage,
                    "queue_status": "completed",
                    "decision": "consumed",
                    "updated_at": row.get("updated_at") or "",
                }
            )
        if fallback_rows:
            upsert_reading_queue_rows(content_db, fallback_rows)
        return len(fallback_rows)

    affected = 0
    with sqlite3.connect(content_db) as conn:
        stage_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "stage")
        current_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "is_current")
        status_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "queue_status")
        uid_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "uid_literature")
        cite_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "cite_key")
        for uid_literature, cite_key in identities:
            cursor = conn.execute(
                f"""
                UPDATE {_quote_identifier(READING_QUEUE_TABLE_NAME)}
                   SET {_quote_identifier(current_column)} = 0,
                       {_quote_identifier(status_column)} = 'completed'
                 WHERE {_quote_identifier(stage_column)} = ?
                   AND {_quote_identifier(current_column)} = 1
                   AND COALESCE({_quote_identifier(uid_column)}, '') = ?
                   AND COALESCE({_quote_identifier(cite_column)}, '') = ?
                """,
                (stage, uid_literature, cite_key),
            )
            if cursor.rowcount and cursor.rowcount > 0:
                affected += int(cursor.rowcount)
        conn.commit()
    return affected


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _ensure_queue_preprocess_defaults(content_db: Path) -> None:
    """为 A050 队列补齐预处理状态默认值。"""

    stage_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "stage")
    current_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "is_current")
    state_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "preprocess_state")
    result_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "preprocess_result_path")
    started_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "preprocess_started_at")
    finished_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "preprocess_finished_at")
    failure_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "preprocess_failure_reason")
    updated_column = resolve_content_physical_column(READING_QUEUE_TABLE_NAME, "updated_at")

    with sqlite3.connect(content_db) as conn:
        queue_object = conn.execute(
            "SELECT type FROM sqlite_master WHERE name = ? LIMIT 1",
            (READING_QUEUE_TABLE_NAME,),
        ).fetchone()
        if not queue_object:
            return
        if str(queue_object[0]).strip().lower() != "table":
            return
        conn.execute(
            f"""
            UPDATE {_quote_identifier(READING_QUEUE_TABLE_NAME)}
               SET {_quote_identifier(state_column)} = '未处理',
                   {_quote_identifier(result_column)} = COALESCE({_quote_identifier(result_column)}, ''),
                   {_quote_identifier(started_column)} = COALESCE({_quote_identifier(started_column)}, ''),
                   {_quote_identifier(finished_column)} = COALESCE({_quote_identifier(finished_column)}, ''),
                   {_quote_identifier(failure_column)} = COALESCE({_quote_identifier(failure_column)}, ''),
                   {_quote_identifier(updated_column)} = datetime('now', 'localtime')
             WHERE {_quote_identifier(current_column)} = 1
               AND {_quote_identifier(stage_column)} IN ('A050_REVIEW', 'A050_NON_REVIEW')
               AND COALESCE({_quote_identifier(state_column)}, '') = ''
            """
        )
        conn.commit()


def _update_flow_state_after_preprocess(
    content_db: Path,
    ready_df: pd.DataFrame,
    *,
    profile: str,
    source_stage: str,
) -> int:
    rows: List[Dict[str, Any]] = []
    for _, row in ready_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        if not uid_literature and not cite_key:
            continue
        if profile == "review":
            rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "stage_code": "review_candidate",
                    "node_code": "A060",
                    "文献角色": "综述文献",
                    "流程轨道": "综述主链",
                    "当前阶段": "综述候选构建",
                    "当前阶段组": "综述导读",
                    "当前状态": "待处理",
                    "下一阶段": "综述参考扩展",
                    "来源阶段": source_stage,
                    "来源类型": "A055_unified_preprocess",
                    "推荐原因": "A055 统一预处理完成，进入 A060 综述文献研读",
                    "主题关系": _stringify(row.get("theme_relation")) or "A055_review",
                    "是否当前有效": 1,
                    "是否可执行": 1,
                }
            )
        else:
            rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "stage_code": "rough_read",
                    "node_code": "A080",
                    "文献角色": "普通候选文献",
                    "流程轨道": "普通主链",
                    "当前阶段": "普通阅读链处理",
                    "当前阶段组": "普通阅读链",
                    "当前状态": "待处理",
                    "下一阶段": "深度解析准备",
                    "来源阶段": source_stage,
                    "来源类型": "A055_unified_preprocess",
                    "推荐原因": "A055 统一预处理完成，进入 A080 普通文献泛读",
                    "主题关系": _stringify(row.get("theme_relation")) or "A055_non_review",
                    "是否当前有效": 1,
                    "是否可执行": 1,
                }
            )

    if rows:
        upsert_flow_state_rows(content_db, rows)
    return len(rows)


def _upsert_a080_queue(content_db: Path, ready_df: pd.DataFrame, *, source_affair: str) -> int:
    rows: List[Dict[str, Any]] = []
    for _, row in ready_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        if not uid_literature and not cite_key:
            continue
        rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "stage": "A080",
                "source_affair": source_affair,
                "queue_status": "queued",
                "priority": row.get("priority") or row.get("priority_rank") or 60.0,
                "bucket": "non_review_reading_chain",
                "preferred_next_stage": "A100",
                "recommended_reason": f"{source_affair} 统一预处理完成，进入 A080",
                "theme_relation": _stringify(row.get("theme_relation")) or f"{source_affair}_non_review",
                "preprocess_state": _stringify(row.get("preprocess_state")) or "已处理",
                "preprocess_result_path": _stringify(row.get("preprocess_result_path")) or _stringify(row.get("asset_dir")),
                "preprocess_failure_reason": "",
                "preprocess_finished_at": _stringify(row.get("preprocess_finished_at")),
                "source_round": source_affair.lower(),
                "scope_key": f"{source_affair.lower()}_to_a080",
                "is_current": 1,
            }
        )
    if rows:
        upsert_reading_queue_rows(content_db, rows)
    return len(rows)


def _upsert_a065_queue(content_db: Path, ready_df: pd.DataFrame, *, source_affair: str) -> int:
    rows: List[Dict[str, Any]] = []
    for _, row in ready_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        if not uid_literature and not cite_key:
            continue
        rows.append(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "stage": "A065",
                "source_affair": source_affair,
                "queue_status": "queued",
                "priority": row.get("score") or row.get("priority") or 68.0,
                "bucket": "review_parse_ready",
                "preferred_next_stage": "A080",
                "recommended_reason": f"{source_affair} 统一预处理完成，进入 A065",
                "theme_relation": _stringify(row.get("theme_relation")) or f"{source_affair}_unified",
                "preprocess_state": _stringify(row.get("preprocess_state")) or "已处理",
                "preprocess_result_path": _stringify(row.get("preprocess_result_path")) or _stringify(row.get("asset_dir")),
                "preprocess_failure_reason": "",
                "preprocess_finished_at": _stringify(row.get("preprocess_finished_at")),
                "source_round": source_affair.lower(),
                "scope_key": f"{source_affair.lower()}_to_a065",
                "is_current": 1,
            }
        )
    if rows:
        upsert_reading_queue_rows(content_db, rows)
    return len(rows)


@affair_auto_git_commit("A050")
def execute(config_path: Path) -> List[Path]:
    """执行 A050/A055 统一文献预处理。

    Args:
        config_path: 节点配置路径。

    Returns:
        本次产物路径列表。

    Raises:
        ValueError: 配置非法时抛出。
        FileNotFoundError: 无待处理数据时抛出。

    Examples:
        >>> execute(Path("workspace/config/affairs_config/A050.json"))
    """

    config_path = Path(config_path)
    raw_cfg = normalize_to_legacy_contract(load_json_or_py(config_path))
    if not isinstance(raw_cfg, dict):
        raise ValueError("A050/A055 配置必须是字典")

    node_code = _stringify(raw_cfg.get("node_code") or "A050").upper()
    if node_code not in {"A050", "A055"}:
        raise ValueError("node_code 仅支持 A050/A055")

    execution_mode = _normalize_enum_value("execution_mode", raw_cfg.get("execution_mode") or "执行完整预处理", default="full_preprocess").lower()
    if execution_mode not in {"full_preprocess", "priority_only"}:
        raise ValueError("execution_mode 仅支持 执行完整预处理/仅生成优先级（兼容 full_preprocess/priority_only）")

    default_node_name = "预处理优先级生成" if execution_mode == "priority_only" else "统一文献预处理执行"
    node_name = _stringify(raw_cfg.get("node_name") or default_node_name)

    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    default_task_dir = f"{node_code}_unified_preprocess" if execution_mode == "full_preprocess" else f"{node_code}_preprocess_priority"
    legacy_output_dir = resolve_legacy_output_dir(
        raw_cfg,
        config_path,
        default_path=workspace_root / "tasks" / default_task_dir,
    )
    output_dir = create_task_instance_dir(workspace_root, node_code)

    default_agent_name = "ar_A055_统一文献预处理执行事务智能体_v1" if node_code == "A055" else "ar_A050_统一文献预处理解析事务智能体_v1"
    default_skill_name = "ar_A055_统一文献预处理执行_v1" if node_code == "A055" else "ar_A050_统一文献预处理解析_v1"
    agent_names = [_stringify(item) for item in list(raw_cfg.get("agent_names") or []) if _stringify(item)] or [default_agent_name]
    skill_names = [_stringify(item) for item in list(raw_cfg.get("skill_names") or []) if _stringify(item)] or [default_skill_name]

    content_db, _ = resolve_content_db_config(
        raw_cfg,
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None
    _emit_progress(node_code, f"启动事务。workspace_root={workspace_root}")
    _emit_progress(node_code, f"content_db={content_db}")
    _emit_progress(node_code, f"任务输出目录={output_dir}")

    literature_df = load_reference_main_table(content_db)

    auto_fill_literature_type = bool(raw_cfg.get("auto_fill_literature_type", True))
    profile = _normalize_enum_value("profile", raw_cfg.get("profile") or "混合", default="mixed").lower()
    if profile not in {"review", "non_review", "mixed"}:
        raise ValueError("profile 仅支持 综述/非综述/混合（兼容 review/non_review/mixed）")

    if execution_mode == "priority_only":
        queue_df, ranking_df = _build_full_library_priority_rows(
            content_db=content_db,
            literature_df=literature_df,
            workspace_root=workspace_root,
            raw_cfg=raw_cfg,
            run_uid=output_dir.name,
        )
        if not queue_df.empty:
            upsert_reading_queue_rows(content_db, queue_df)

        index_df = ranking_df.copy()
        index_path = output_dir / _stringify(raw_cfg.get("output_index_name") or f"{node_code.lower()}_preprocess_priority_index.csv")
        index_df.to_csv(index_path, index=False, encoding="utf-8-sig")

        total_input_count = len(index_df)
        review_input_count = int((index_df.get("preprocess_profile", pd.Series(dtype=str)).astype(str) == "review").sum()) if not index_df.empty else 0
        non_review_input_count = int((index_df.get("preprocess_profile", pd.Series(dtype=str)).astype(str) == "non_review").sum()) if not index_df.empty else 0
        queued_count = int((index_df.get("queue_status", pd.Series(dtype=str)).astype(str) == "queued").sum()) if not index_df.empty else 0
        in_progress_count = int((index_df.get("queue_status", pd.Series(dtype=str)).astype(str) == "in_progress").sum()) if not index_df.empty else 0
        blocked_count = int((index_df.get("queue_status", pd.Series(dtype=str)).astype(str) == "blocked").sum()) if not index_df.empty else 0
        completed_count = int((index_df.get("queue_status", pd.Series(dtype=str)).astype(str) == "completed").sum()) if not index_df.empty else 0

        gate_review = build_gate_review(
            node_uid=node_code,
            node_name=node_name,
            summary=(
                f"{node_code} 全库优先级生成完成：全库 {total_input_count} 条，"
                f"review {review_input_count} 条，non_review {non_review_input_count} 条，"
                f"queued {queued_count} 条，in_progress {in_progress_count} 条，"
                f"blocked {blocked_count} 条，completed {completed_count} 条。"
            ),
            checks=[
                {"name": "input_total", "value": total_input_count},
                {"name": "review_input", "value": review_input_count},
                {"name": "non_review_input", "value": non_review_input_count},
                {"name": "queued_count", "value": queued_count},
                {"name": "in_progress_count", "value": in_progress_count},
                {"name": "blocked_count", "value": blocked_count},
                {"name": "completed_count", "value": completed_count},
                {"name": "execution_mode", "value": execution_mode},
            ],
            artifacts=[str(index_path)],
            recommendation="pass_next" if total_input_count > 0 else "retry_current",
            score=92.0 if total_input_count > 0 else 70.0,
            issues=[],
            metadata={
                "workspace_root": str(workspace_root),
                "content_db": str(content_db),
                "profile": profile,
                "execution_mode": execution_mode,
                "auto_fill_literature_type": auto_fill_literature_type,
                "priority_policy": _resolve_priority_policy(raw_cfg),
            },
        )
        gate_path = output_dir / OUTPUT_GATE
        gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

        try:
            append_aok_log_event(
                event_type=f"{node_code}_PREPROCESS_PRIORITY_GENERATED",
                project_root=workspace_root,
                affair_code=node_code,
                handler_name=node_name,
                agent_names=agent_names,
                skill_names=skill_names,
                reasoning_summary="按全库文献重排优先级，并回写主文献表预处理摘要列。",
                gate_review=gate_review,
                gate_review_path=gate_path,
                artifact_paths=[index_path, gate_path],
                payload={
                    "profile": profile,
                    "execution_mode": execution_mode,
                    "input_total": total_input_count,
                    "review_input": review_input_count,
                    "non_review_input": non_review_input_count,
                    "queued_count": queued_count,
                    "blocked_count": blocked_count,
                    "completed_count": completed_count,
                },
            )
        except Exception:
            pass

        final_artifacts = [index_path, gate_path]
        mirror_artifacts_to_legacy(final_artifacts, legacy_output_dir, output_dir)
        _emit_progress(node_code, f"全库优先级生成完成。input_total={total_input_count}，queued={queued_count}，gate={gate_path}")
        return final_artifacts

    review_df = _load_review_pending_df(content_db, literature_df)
    non_review_df = _load_non_review_pending_df(content_db, literature_df)

    source_frames = _split_sources_by_profile(profile=profile, review_df=review_df, non_review_df=non_review_df)
    review_source = source_frames.get("review", pd.DataFrame())
    non_review_source = source_frames.get("non_review", pd.DataFrame())
    _ensure_queue_preprocess_defaults(content_db)

    _emit_progress(
        node_code,
        "已装载输入。profile={profile}，review={review_count} 条，non_review={non_review_count} 条。".format(
            profile=profile,
            review_count=len(review_source),
            non_review_count=len(non_review_source),
        )
    )

    global_config_path = _resolve_global_config_path(workspace_root)
    parse_runtime = resolve_parse_runtime_settings(
        raw_cfg,
        workspace_root=workspace_root,
        global_config_path=global_config_path,
    )
    run_mode = _resolve_a055_run_mode(raw_cfg, parse_runtime=parse_runtime, execution_mode=execution_mode)
    if execution_mode == "full_preprocess" and run_mode not in {
        A055_RUN_MODE_LOCAL_ONLY,
        A055_RUN_MODE_LOCAL_DISPATCH_REMOTE,
        A055_RUN_MODE_REMOTE_ONLY_TMUX,
        A055_RUN_MODE_RECORD_PARSE_RESULTS,
    }:
        raise ValueError(
            "run_mode 仅支持 仅本地/本地分发远端/仅远端tmux/仅登记解析结果（兼容 local_only/local_dispatch_remote/remote_only_tmux/record_parse_results）"
        )

    if execution_mode == "full_preprocess" and run_mode == A055_RUN_MODE_RECORD_PARSE_RESULTS:
        review_source = _load_record_parse_source_df(literature_df, profile="review")
        non_review_source = _load_record_parse_source_df(literature_df, profile="non_review")
        source_frames = _split_sources_by_profile(profile=profile, review_df=review_source, non_review_df=non_review_source)
        review_source = source_frames.get("review", pd.DataFrame())
        non_review_source = source_frames.get("non_review", pd.DataFrame())

    max_items = int(raw_cfg.get("max_items") or 0)
    if max_items > 0 and not (execution_mode == "full_preprocess" and run_mode == A055_RUN_MODE_RECORD_PARSE_RESULTS):
        if not review_source.empty:
            review_source = review_source.head(max_items).reset_index(drop=True)
        if not non_review_source.empty:
            non_review_source = non_review_source.head(max_items).reset_index(drop=True)

    if execution_mode == "full_preprocess" and review_source.empty and non_review_source.empty:
        bootstrap_queue_df, _ = _build_full_library_priority_rows(
            content_db=content_db,
            literature_df=literature_df,
            workspace_root=workspace_root,
            raw_cfg=raw_cfg,
            run_uid=output_dir.name,
        )
        if not bootstrap_queue_df.empty:
            upsert_reading_queue_rows(content_db, bootstrap_queue_df)
            review_source = _load_review_pending_df(content_db, literature_df)
            non_review_source = _load_non_review_pending_df(content_db, literature_df)
            _emit_progress(
                node_code,
                "A055 检测到当前队列为空，已按 A050 全库优先级规则回填队列：review={review_count}，non_review={non_review_count}".format(
                    review_count=len(review_source),
                    non_review_count=len(non_review_source),
                ),
            )

    if review_source.empty and non_review_source.empty:
        if execution_mode == "full_preprocess" and run_mode in {
            A055_RUN_MODE_LOCAL_ONLY,
            A055_RUN_MODE_LOCAL_DISPATCH_REMOTE,
        }:
            gate_review = build_gate_review(
                node_uid=node_code,
                node_name=node_name,
                summary=(
                    f"{node_code} 未找到可执行条目：review {len(review_source)} 条，"
                    f"non_review {len(non_review_source)} 条，未启动 {run_mode}。"
                ),
                checks=[
                    {"name": "run_mode", "value": run_mode},
                    {"name": "review_input", "value": len(review_source)},
                    {"name": "non_review_input", "value": len(non_review_source)},
                ],
                artifacts=[],
                recommendation="retry_current",
                score=75.0,
                issues=[],
                metadata={
                    "workspace_root": str(workspace_root),
                    "content_db": str(content_db),
                    "profile": profile,
                    "execution_mode": execution_mode,
                    "run_mode": run_mode,
                },
            )
            gate_path = output_dir / OUTPUT_GATE
            gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
            final_artifacts = [gate_path]
            mirror_artifacts_to_legacy(final_artifacts, legacy_output_dir, output_dir)
            _emit_progress(
                node_code,
                f"未找到可执行条目，已输出 gate_review。run_mode={run_mode}，gate={gate_path}",
            )
            return final_artifacts

    marker_name = _stringify(raw_cfg.get("parse_done_marker_name") or A055_DONE_MARKER_DEFAULT)
    write_done_marker = bool(raw_cfg.get("write_parse_done_marker", True))

    restart_actions: List[str] = []
    if node_code == "A055":
        restart_actions = _takeover_previous_a055_run(
            workspace_root=workspace_root,
            parse_runtime=parse_runtime,
            task_uid=output_dir.name,
        )

    if execution_mode == "full_preprocess" and run_mode == A055_RUN_MODE_REMOTE_ONLY_TMUX:
        remote_only_cfg = raw_cfg.get("remote_only") if isinstance(raw_cfg.get("remote_only"), dict) else {}
        remote_command = _build_remote_only_command(raw_cfg, config_path=config_path)
        session_prefix = _stringify(
            remote_only_cfg.get("tmux_session_prefix")
            or ((parse_runtime.get("remote_processing") or {}).get("ssh") or {}).get("tmux_session_prefix")
            or "a055"
        )
        requested_session_name = _stringify(remote_only_cfg.get("tmux_session_name"))
        if requested_session_name:
            session_name = requested_session_name
        else:
            session_name = f"{session_prefix}_{output_dir.name[-8:]}"
        launch_timeout = int(remote_only_cfg.get("launch_timeout") or 60)

        launch_result = launch_remote_tmux_command(
            parse_runtime,
            remote_command=remote_command,
            session_prefix=session_prefix,
            session_name=session_name,
            timeout=launch_timeout,
        )

        dispatch_payload = {
            "run_mode": run_mode,
            "session_name": _stringify(launch_result.get("session_name")),
            "restart_actions": restart_actions,
            "marker_name": marker_name,
            "write_done_marker": write_done_marker,
            "remote_command": remote_command,
        }
        dispatch_path = output_dir / "a055_remote_dispatch.json"
        dispatch_path.write_text(json.dumps(dispatch_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        gate_review = build_gate_review(
            node_uid=node_code,
            node_name=node_name,
            summary=f"A055 remote_only_tmux 已提交远端会话 {dispatch_payload['session_name']}，本地不执行解析。",
            checks=[
                {"name": "run_mode", "value": run_mode},
                {"name": "session_name", "value": dispatch_payload["session_name"]},
            ],
            artifacts=[str(dispatch_path)],
            recommendation="pass_next",
            score=90.0,
            issues=[],
            metadata={
                "workspace_root": str(workspace_root),
                "content_db": str(content_db),
                "run_mode": run_mode,
                "marker_name": marker_name,
                "restart_actions": restart_actions,
            },
        )
        gate_path = output_dir / OUTPUT_GATE
        gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
        final_artifacts = [dispatch_path, gate_path]
        mirror_artifacts_to_legacy(final_artifacts, legacy_output_dir, output_dir)
        if node_code == "A055":
            _release_a055_runtime_guard(workspace_root)
        return final_artifacts

    if execution_mode == "full_preprocess" and run_mode == A055_RUN_MODE_RECORD_PARSE_RESULTS:
        review_record_df = _collect_record_ready_rows(review_source, workspace_root=workspace_root, marker_name=marker_name)
        non_review_record_df = _collect_record_ready_rows(non_review_source, workspace_root=workspace_root, marker_name=marker_name)

        review_ready_count = len(review_record_df)
        non_review_ready_count = len(non_review_record_df)
        _apply_record_parse_results(content_db, review_record_df, profile="review")
        _apply_record_parse_results(content_db, non_review_record_df, profile="non_review")

        consumed_review = _consume_current_stage_queue_rows(content_db, stage="A050_REVIEW", ready_df=review_record_df)
        consumed_non_review = _consume_current_stage_queue_rows(content_db, stage="A050_NON_REVIEW", ready_df=non_review_record_df)
        _update_flow_state_after_preprocess(content_db, review_record_df, profile="review", source_stage=f"{node_code}_record")
        _update_flow_state_after_preprocess(content_db, non_review_record_df, profile="non_review", source_stage=f"{node_code}_record")
        a090_queue_count = _upsert_a080_queue(content_db, non_review_record_df, source_affair=node_code)

        record_rows: List[Dict[str, Any]] = []
        for current_profile, current_df in [("review", review_record_df), ("non_review", non_review_record_df)]:
            for _, row in current_df.fillna("").iterrows():
                row_dict = dict(row.to_dict())
                record_rows.append(
                    {
                        "uid_literature": _stringify(row_dict.get("uid_literature")),
                        "cite_key": _stringify(row_dict.get("cite_key")),
                        "preprocess_profile": current_profile,
                        "manifest_status": "recorded",
                        "asset_dir": _stringify(row_dict.get("asset_dir")),
                        "done_marker_path": _stringify(row_dict.get("done_marker_path")),
                    }
                )

        record_df = pd.DataFrame(record_rows)
        index_path = output_dir / _stringify(raw_cfg.get("output_index_name") or f"{node_code.lower()}_record_parse_results_index.csv")
        record_df.to_csv(index_path, index=False, encoding="utf-8-sig")

        gate_review = build_gate_review(
            node_uid=node_code,
            node_name=node_name,
            summary=(
                f"A055 record_parse_results 完成：review 记录 {review_ready_count} 条，"
                f"non_review 记录 {non_review_ready_count} 条。"
            ),
            checks=[
                {"name": "run_mode", "value": run_mode},
                {"name": "review_recorded", "value": review_ready_count},
                {"name": "non_review_recorded", "value": non_review_ready_count},
                {"name": "a090_queue_count", "value": a090_queue_count},
                {"name": "consumed_review_queue", "value": consumed_review},
                {"name": "consumed_non_review_queue", "value": consumed_non_review},
            ],
            artifacts=[str(index_path)],
            recommendation="pass_next" if (review_ready_count + non_review_ready_count) > 0 else "retry_current",
            score=90.0 if (review_ready_count + non_review_ready_count) > 0 else 70.0,
            issues=[],
            metadata={
                "workspace_root": str(workspace_root),
                "content_db": str(content_db),
                "run_mode": run_mode,
                "marker_name": marker_name,
                "restart_actions": restart_actions,
            },
        )
        gate_path = output_dir / OUTPUT_GATE
        gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
        final_artifacts = [index_path, gate_path]
        mirror_artifacts_to_legacy(final_artifacts, legacy_output_dir, output_dir)
        if node_code == "A055":
            _release_a055_runtime_guard(workspace_root)
        return final_artifacts

    if execution_mode == "full_preprocess" and run_mode == A055_RUN_MODE_LOCAL_ONLY:
        parse_runtime = dict(parse_runtime)
        remote_cfg = parse_runtime.get("remote_processing") if isinstance(parse_runtime.get("remote_processing"), dict) else {}
        remote_cfg = dict(remote_cfg)
        remote_cfg["enabled"] = False
        parse_runtime["remote_processing"] = remote_cfg

    postprocess_settings = resolve_postprocess_settings(raw_cfg, workspace_root=workspace_root)
    _emit_progress(
        node_code,
        "运行时已就绪。backend={backend}，device={device}，device_requested={device_requested}".format(
            backend=_stringify(parse_runtime.get("backend")),
            device=_stringify(parse_runtime.get("device")),
            device_requested=_stringify(parse_runtime.get("device_requested")),
        )
    )
    if restart_actions:
        _emit_progress(node_code, f"A055 启动前已清理旧实例：{';'.join(restart_actions)}")

    result_rows: List[Dict[str, Any]] = []
    artifact_paths: List[Path] = []
    failures: List[str] = []
    review_ready_count = 0
    non_review_ready_count = 0
    review_failed_count = 0
    non_review_failed_count = 0
    postprocess_success_count = 0
    a090_queue_count = 0
    consumed_a050_queue_count = 0
    done_marker_count = 0

    profile_inputs = _build_profile_execution_batches(review_source=review_source, non_review_source=non_review_source)

    for batch_index, (current_profile, source_df) in enumerate(profile_inputs, start=1):
        profile_output_dir = output_dir / f"{batch_index:03d}_{current_profile}"
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        _emit_progress(
            node_code,
            "开始处理 batch={batch_index} profile={profile}，条目数={count}，输出目录={output_dir}".format(
                batch_index=batch_index,
                profile=current_profile,
                count=len(source_df),
                output_dir=profile_output_dir,
            )
        )
        manifest_result = _run_profile_parse(
            profile=current_profile,
            source_df=source_df,
            content_db=content_db,
            output_dir=profile_output_dir,
            parse_runtime=parse_runtime,
            postprocess_settings=postprocess_settings,
            global_config_path=global_config_path,
            max_items=max_items,
        )
        manifest_df = manifest_result["manifest_df"].fillna("")

        ready_df = manifest_df.loc[
            manifest_df.get("manifest_status", pd.Series(dtype=str)).astype(str).str.lower().isin(["succeeded", "skipped"])
        ].copy() if not manifest_df.empty else pd.DataFrame()
        failed_df = manifest_df.loc[
            manifest_df.get("manifest_status", pd.Series(dtype=str)).astype(str).str.lower().isin(["failed"])
        ].copy() if not manifest_df.empty else pd.DataFrame()

        _emit_progress(
            node_code,
            "batch={batch_index} profile={profile} 处理完成。succeeded_or_skipped={ready_count}，failed={failed_count}，manifest={manifest_path}".format(
                batch_index=batch_index,
                profile=current_profile,
                ready_count=len(ready_df),
                failed_count=len(failed_df),
                manifest_path=manifest_result["manifest_path"],
            )
        )

        if node_code == "A055" and write_done_marker and not ready_df.empty:
            for _, ready_row in ready_df.fillna("").iterrows():
                ready_payload = dict(ready_row.to_dict())
                asset_dir = _resolve_a055_asset_dir(
                    workspace_root,
                    uid_literature=_stringify(ready_payload.get("uid_literature")),
                    cite_key=_stringify(ready_payload.get("cite_key")),
                    asset_dir=_stringify(ready_payload.get("asset_dir")),
                )
                is_complete, _ = _is_parse_asset_complete(_build_asset_probe_row(asset_dir))
                if not is_complete:
                    continue
                _write_a055_done_marker(asset_dir, marker_name=marker_name)
                done_marker_count += 1

        if current_profile == "review":
            review_ready_count += len(ready_df)
            review_failed_count += len(failed_df)
            _update_flow_state_after_preprocess(content_db, ready_df, profile="review", source_stage=f"{node_code}_review")
            consumed_a050_queue_count += _consume_current_stage_queue_rows(content_db, stage="A050_REVIEW", ready_df=ready_df)
        else:
            non_review_ready_count += len(ready_df)
            non_review_failed_count += len(failed_df)
            a090_queue_count += _upsert_a080_queue(content_db, ready_df, source_affair=node_code)
            _update_flow_state_after_preprocess(content_db, ready_df, profile="non_review", source_stage=f"{node_code}_non_review")
            consumed_a050_queue_count += _consume_current_stage_queue_rows(content_db, stage="A050_NON_REVIEW", ready_df=ready_df)

        postprocess_success_count += int(manifest_df.get("postprocess_ok", pd.Series(dtype=int)).fillna(0).astype(int).sum())
        failures.extend(list(manifest_result.get("failures") or []))

        for _, row in manifest_df.iterrows():
            row_dict = dict(row.to_dict())
            row_dict["preprocess_profile"] = current_profile
            result_rows.append(row_dict)

        artifact_paths.extend(
            [
                Path(manifest_result["manifest_path"]),
                Path(manifest_result["management_table_path"]),
                Path(manifest_result["handoff_path"]),
                Path(manifest_result["batch_report_path"]),
            ]
        )

    index_df = pd.DataFrame(result_rows)
    index_path = output_dir / _stringify(raw_cfg.get("output_index_name") or f"{node_code.lower()}_unified_preprocess_index.csv")
    index_df.to_csv(index_path, index=False, encoding="utf-8-sig")

    total_input_count = len(review_source) + len(non_review_source)
    total_ready_count = review_ready_count + non_review_ready_count
    total_failed_count = review_failed_count + non_review_failed_count

    gate_review = build_gate_review(
        node_uid=node_code,
        node_name=node_name,
        summary=(
            f"{node_code} 统一预处理完成：输入 {total_input_count} 条，"
            f"review 就绪 {review_ready_count} 条，non_review 就绪 {non_review_ready_count} 条，"
            f"失败 {total_failed_count} 条，后处理成功 {postprocess_success_count} 条。"
        ),
        checks=[
            {"name": "input_total", "value": total_input_count},
            {"name": "review_input", "value": len(review_source)},
            {"name": "non_review_input", "value": len(non_review_source)},
            {"name": "review_ready", "value": review_ready_count},
            {"name": "non_review_ready", "value": non_review_ready_count},
            {"name": "failed_total", "value": total_failed_count},
            {"name": "postprocess_success_count", "value": postprocess_success_count},
            {"name": "a090_queue_count", "value": a090_queue_count},
            {"name": "consumed_a050_queue_count", "value": consumed_a050_queue_count},
            {"name": "done_marker_count", "value": done_marker_count},
        ],
        artifacts=[str(index_path)] + [str(path) for path in artifact_paths],
        recommendation="pass_next" if total_ready_count > 0 else "retry_current",
        score=max(50.0, 95.0 - total_failed_count * 4.0),
        issues=failures,
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
            "profile": profile,
            "auto_fill_literature_type": auto_fill_literature_type,
            "a090_queue_count": a090_queue_count,
            "consumed_a050_queue_count": consumed_a050_queue_count,
            "done_marker_count": done_marker_count,
            "parse_runtime": parse_runtime,
            "postprocess_enabled": bool(postprocess_settings.get("enabled", True)),
            "run_mode": run_mode,
            "write_done_marker": write_done_marker,
            "marker_name": marker_name,
        },
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
    _emit_progress(
        node_code,
        "事务完成。input_total={input_total}，ready_total={ready_total}，failed_total={failed_total}，gate={gate_path}".format(
            input_total=total_input_count,
            ready_total=total_ready_count,
            failed_total=total_failed_count,
            gate_path=gate_path,
        )
    )

    try:
        append_aok_log_event(
            event_type=f"{node_code}_UNIFIED_PREPROCESS_COMPLETED",
            project_root=workspace_root,
            affair_code=node_code,
            handler_name=node_name,
            agent_names=agent_names,
            skill_names=skill_names,
            reasoning_summary="按 execution_mode 执行统一预处理入口。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=[index_path, gate_path] + artifact_paths,
            payload={
                "profile": profile,
                "execution_mode": execution_mode,
                "input_total": total_input_count,
                "ready_total": total_ready_count,
                "failed_total": total_failed_count,
                "review_ready": review_ready_count,
                "non_review_ready": non_review_ready_count,
            },
        )
    except Exception:
        pass

    final_artifacts = [index_path, gate_path] + artifact_paths
    mirror_artifacts_to_legacy(final_artifacts, legacy_output_dir, output_dir)
    if node_code == "A055":
        _release_a055_runtime_guard(workspace_root)
    return final_artifacts
