"""A050 统一文献预处理解析事务。

该事务作为并行独立入口，不接管固定主链。
支持按 profile 统一调度 MonkeyOCR 预处理：
1. review：优先消费 A050_REVIEW 队列；队列为空时由 review_state.pending_review_parse=1 回填，产出 review_deep 资产并推进 A065。
2. non_review：优先消费 A050_NON_REVIEW 队列；队列为空时由 literature_reading_state.pending_preprocess=1 回填，产出 non_review_rough 资产并推进 A090。
3. mixed：自动按文献类型拆分到 review/non_review 两条子链执行。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from autodokit.path_compat import resolve_portable_path
from autodokit.tools import append_aok_log_event, build_gate_review, load_json_or_py
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.atomic.task_aok.task_instance_dir import (
    create_task_instance_dir,
    mirror_artifacts_to_legacy,
    resolve_legacy_output_dir,
)
from autodokit.tools.bibliodb_sqlite import (
    load_reading_queue_df,
    load_reading_state_df,
    load_review_state_df,
    upsert_reading_queue_rows,
    upsert_reading_state_rows,
    upsert_review_state_rows,
)
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.ocr.runtime.monkeyocr_manifest_runtime import (
    resolve_parse_runtime_settings,
    resolve_postprocess_settings,
    run_parse_manifest,
)
from autodokit.tools.storage_backend import load_reference_main_table


OUTPUT_INDEX = "a050_unified_preprocess_index.csv"
OUTPUT_GATE = "gate_review.json"


def _emit_progress(message: str) -> None:
    """输出最小终端进度日志。"""

    print(f"[A050] {message}", flush=True)


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
    """确保 literatures.literature_type 字段存在，并按启发式回填。

    Args:
        content_db: content.db 路径。
        auto_fill: 是否自动回填空值。
    """

    with sqlite3.connect(content_db) as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(literatures)").fetchall()]
        if "literature_type" not in cols:
            conn.execute("ALTER TABLE literatures ADD COLUMN literature_type TEXT DEFAULT ''")
            conn.commit()

        if not auto_fill:
            return

        conn.execute(
            """
            UPDATE literatures
               SET literature_type = 'review'
             WHERE COALESCE(literature_type, '') = ''
               AND (
                    LOWER(COALESCE(entry_type, '')) IN ('review', 'survey')
                    OR LOWER(COALESCE(structured_task_type, '')) LIKE 'review%'
                    OR COALESCE(title, '') LIKE '%综述%'
                    OR COALESCE(title, '') LIKE '%系统评价%'
                    OR COALESCE(title, '') LIKE '%meta-analysis%'
                    OR COALESCE(title, '') LIKE '%meta analysis%'
               )
            """
        )
        conn.execute(
            """
            UPDATE literatures
               SET literature_type = 'non_review'
             WHERE COALESCE(literature_type, '') = ''
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


def _seed_a050_queue_rows(content_db: Path, profile: str, source_df: pd.DataFrame) -> int:
    """把现有状态表回填为 A050 队列行，便于后续统一从队列消费。"""

    if source_df is None or source_df.empty:
        return 0

    normalized_profile = _stringify(profile).lower()
    if normalized_profile not in {"review", "non_review"}:
        raise ValueError("profile 仅支持 review/non_review")

    stage = f"A050_{normalized_profile.upper()}"
    rows: List[Dict[str, Any]] = []
    for _, row in source_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        if not uid_literature and not cite_key:
            continue

        priority_value = row.get("a05_current_score") or row.get("priority")
        if pd.isna(priority_value):
            priority_value = None

        next_stage = "A065" if normalized_profile == "review" else "A090"
        bucket = "review_parse_ready" if normalized_profile == "review" else "non_review_preprocess"
        recommended_reason = _stringify(row.get("recommended_reason"))
        if not recommended_reason:
            recommended_reason = "A050 状态回填到队列"

        rows.append(
            {
                "queue_uid": f"A050:{normalized_profile}:{uid_literature or cite_key}",
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "stage": stage,
                "source_affair": "A050",
                "queue_status": "queued",
                "decision": "",
                "priority": priority_value,
                "bucket": bucket,
                "theme_bucket": bucket,
                "preferred_next_stage": next_stage,
                "recommended_reason": recommended_reason,
                "theme_relation": _stringify(row.get("theme_relation")) or f"A050_{normalized_profile}",
                "source_round": "a050",
                "source_stage": _stringify(row.get("source_stage")) or stage,
                "source_origin": _stringify(row.get("source_origin")) or "state_backfill",
                "run_uid": _stringify(row.get("run_uid")),
                "source_run_uid": _stringify(row.get("source_run_uid")) or _stringify(row.get("run_uid")),
                "scope_key": f"a050_{normalized_profile}_queue",
                "task_batch_id": _stringify(row.get("task_batch_id")),
                "decision_reason": "",
                "is_current": 1,
                "entered_at": _stringify(row.get("entered_at")),
                "completed_at": "",
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
    """优先从 A050 队列读取待处理条目，必要时由状态表回填。"""

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
        if normalized_profile == "review":
            state_df = load_review_state_df(content_db, flag_filters={"pending_review_parse": 1})
        else:
            state_df = load_reading_state_df(content_db, flag_filters={"pending_preprocess": 1})
            failed_statuses = {"missing_attachment", "parse_failed", "note_skeleton_failed"}
            if not state_df.empty and "preprocess_status" in state_df.columns:
                state_df = state_df.loc[
                    ~state_df["preprocess_status"].fillna("").astype(str).str.lower().isin(failed_statuses)
                ].copy()
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
            downstream_stage="A065",
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
        upstream_stage="A075",
        downstream_stage="A090",
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

    affected = 0
    with sqlite3.connect(content_db) as conn:
        for uid_literature, cite_key in identities:
            cursor = conn.execute(
                """
                UPDATE literature_reading_queue
                   SET is_current = 0,
                       queue_status = 'completed'
                 WHERE stage = ?
                   AND is_current = 1
                   AND COALESCE(uid_literature, '') = ?
                   AND COALESCE(cite_key, '') = ?
                """,
                (stage, uid_literature, cite_key),
            )
            if cursor.rowcount and cursor.rowcount > 0:
                affected += int(cursor.rowcount)
        conn.commit()
    return affected


def _update_review_state(content_db: Path, ready_df: pd.DataFrame) -> int:
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
                "source_stage": "A050_review",
                "pending_review_parse": 0,
                "review_parse_ready": 1,
                "pending_reference_preprocess": 1,
                "reference_preprocessed": 0,
            }
        )
    if rows:
        upsert_review_state_rows(content_db, rows)
    return len(rows)


def _update_non_review_state(content_db: Path, ready_df: pd.DataFrame) -> int:
    existing_df = load_reading_state_df(content_db)
    existing_map = {
        _stringify(row.get("uid_literature")): dict(row.to_dict())
        for _, row in existing_df.fillna("").iterrows()
        if _stringify(row.get("uid_literature"))
    }

    rows: List[Dict[str, Any]] = []
    for _, row in ready_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key")) or uid_literature
        if not uid_literature and not cite_key:
            continue
        base = dict(existing_map.get(uid_literature, {}))
        base.update(
            {
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "source_stage": "A050_non_review",
                "pending_preprocess": 0,
                "preprocessed": 1,
                "preprocess_status": "ready",
                "pending_rough_read": 1 if int(base.get("rough_read_done") or 0) == 0 else int(base.get("pending_rough_read") or 0),
            }
        )
        rows.append(base)

    if rows:
        upsert_reading_state_rows(content_db, rows)
    return len(rows)


def _upsert_a065_queue(content_db: Path, ready_df: pd.DataFrame) -> int:
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
                "source_affair": "A050",
                "queue_status": "queued",
                "priority": row.get("score") or row.get("priority") or 68.0,
                "bucket": "review_parse_ready",
                "preferred_next_stage": "A080",
                "recommended_reason": "A050 统一预处理完成，进入 A065",
                "theme_relation": _stringify(row.get("theme_relation")) or "A050_unified",
                "source_round": "a050",
                "scope_key": "a050_to_a065",
                "is_current": 1,
            }
        )
    if rows:
        upsert_reading_queue_rows(content_db, rows)
    return len(rows)


@affair_auto_git_commit("A050")
def execute(config_path: Path) -> List[Path]:
    """执行 A050 统一文献预处理解析。

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

    raw_cfg = load_json_or_py(config_path)
    if not isinstance(raw_cfg, dict):
        raise ValueError("A050 配置必须是字典")

    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    legacy_output_dir = resolve_legacy_output_dir(
        raw_cfg,
        config_path,
        default_path=workspace_root / "tasks" / "A050_unified_preprocess",
    )
    output_dir = create_task_instance_dir(workspace_root, "A050")

    content_db, _ = resolve_content_db_config(
        raw_cfg,
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None
    _emit_progress(f"启动事务。workspace_root={workspace_root}")
    _emit_progress(f"content_db={content_db}")
    _emit_progress(f"任务输出目录={output_dir}")

    auto_fill_literature_type = bool(raw_cfg.get("auto_fill_literature_type", True))
    _ensure_literature_type_column(content_db, auto_fill=auto_fill_literature_type)

    literature_df = load_reference_main_table(content_db)
    review_df = _load_review_pending_df(content_db, literature_df)
    non_review_df = _load_non_review_pending_df(content_db, literature_df)

    profile = _stringify(raw_cfg.get("profile") or "mixed").lower()
    if profile not in {"review", "non_review", "mixed"}:
        raise ValueError("profile 仅支持 review/non_review/mixed")

    source_frames = _split_sources_by_profile(profile=profile, review_df=review_df, non_review_df=non_review_df)
    review_source = source_frames.get("review", pd.DataFrame())
    non_review_source = source_frames.get("non_review", pd.DataFrame())

    if review_source.empty and non_review_source.empty:
        raise FileNotFoundError("A050 未找到可执行条目（review/non_review 均为空）。")

    _emit_progress(
        "已装载输入。profile={profile}，review={review_count} 条，non_review={non_review_count} 条。".format(
            profile=profile,
            review_count=len(review_source),
            non_review_count=len(non_review_source),
        )
    )

    max_items = int(raw_cfg.get("max_items") or 0)
    if max_items > 0:
        if not review_source.empty:
            review_source = review_source.head(max_items).reset_index(drop=True)
        if not non_review_source.empty:
            non_review_source = non_review_source.head(max_items).reset_index(drop=True)

    global_config_path = _resolve_global_config_path(workspace_root)
    parse_runtime = resolve_parse_runtime_settings(
        raw_cfg,
        workspace_root=workspace_root,
        global_config_path=global_config_path,
    )
    postprocess_settings = resolve_postprocess_settings(raw_cfg, workspace_root=workspace_root)
    _emit_progress(
        "运行时已就绪。backend={backend}，device={device}，device_requested={device_requested}".format(
            backend=_stringify(parse_runtime.get("backend")),
            device=_stringify(parse_runtime.get("device")),
            device_requested=_stringify(parse_runtime.get("device_requested")),
        )
    )

    result_rows: List[Dict[str, Any]] = []
    artifact_paths: List[Path] = []
    failures: List[str] = []
    review_ready_count = 0
    non_review_ready_count = 0
    review_failed_count = 0
    non_review_failed_count = 0
    postprocess_success_count = 0
    a065_queue_count = 0
    consumed_a060_queue_count = 0
    consumed_a080_queue_count = 0

    profile_inputs: List[Tuple[str, pd.DataFrame]] = []
    if not review_source.empty:
        profile_inputs.append(("review", review_source))
    if not non_review_source.empty:
        profile_inputs.append(("non_review", non_review_source))

    for current_profile, source_df in profile_inputs:
        profile_output_dir = output_dir / current_profile
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        _emit_progress(
            "开始处理 profile={profile}，条目数={count}，输出目录={output_dir}".format(
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
            "profile={profile} 处理完成。succeeded_or_skipped={ready_count}，failed={failed_count}，manifest={manifest_path}".format(
                profile=current_profile,
                ready_count=len(ready_df),
                failed_count=len(failed_df),
                manifest_path=manifest_result["manifest_path"],
            )
        )

        if current_profile == "review":
            review_ready_count += len(ready_df)
            review_failed_count += len(failed_df)
            a065_queue_count += _upsert_a065_queue(content_db, ready_df)
            _update_review_state(content_db, ready_df)
            consumed_a060_queue_count += _consume_current_stage_queue_rows(content_db, stage="A060", ready_df=ready_df)
        else:
            non_review_ready_count += len(ready_df)
            non_review_failed_count += len(failed_df)
            _update_non_review_state(content_db, ready_df)
            consumed_a080_queue_count += _consume_current_stage_queue_rows(content_db, stage="A080", ready_df=ready_df)

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
    index_path = output_dir / OUTPUT_INDEX
    index_df.to_csv(index_path, index=False, encoding="utf-8-sig")

    total_input_count = len(review_source) + len(non_review_source)
    total_ready_count = review_ready_count + non_review_ready_count
    total_failed_count = review_failed_count + non_review_failed_count

    gate_review = build_gate_review(
        node_uid="A050",
        node_name="统一文献预处理解析",
        summary=(
            f"A050 统一预处理完成：输入 {total_input_count} 条，"
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
            {"name": "a065_queue_count", "value": a065_queue_count},
            {"name": "consumed_a060_queue_count", "value": consumed_a060_queue_count},
            {"name": "consumed_a080_queue_count", "value": consumed_a080_queue_count},
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
            "a065_queue_count": a065_queue_count,
            "consumed_a060_queue_count": consumed_a060_queue_count,
            "consumed_a080_queue_count": consumed_a080_queue_count,
            "parse_runtime": parse_runtime,
            "postprocess_enabled": bool(postprocess_settings.get("enabled", True)),
        },
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")
    _emit_progress(
        "事务完成。input_total={input_total}，ready_total={ready_total}，failed_total={failed_total}，gate={gate_path}".format(
            input_total=total_input_count,
            ready_total=total_ready_count,
            failed_total=total_failed_count,
            gate_path=gate_path,
        )
    )

    try:
        append_aok_log_event(
            event_type="A050_UNIFIED_PREPROCESS_COMPLETED",
            project_root=workspace_root,
            affair_code="A050",
            handler_name="统一文献预处理解析",
            agent_names=["ar_A050_统一文献预处理解析事务智能体_v1"],
            skill_names=["ar_A050_统一文献预处理解析_v1"],
            reasoning_summary="并行统一 A060/A080 预处理入口，不接管固定主链。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=[index_path, gate_path] + artifact_paths,
            payload={
                "profile": profile,
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
    return final_artifacts
