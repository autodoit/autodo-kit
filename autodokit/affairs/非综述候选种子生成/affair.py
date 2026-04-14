"""A075 非综述候选种子生成事务。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import append_aok_log_event, build_gate_review, load_json_or_py
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.bibliodb_sqlite import load_reading_state_df, load_review_state_df, upsert_reading_state_rows
from autodokit.tools.contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_config
from autodokit.tools.storage_backend import load_reference_tables


OUTPUT_SEED_CSV = "a075_seed_candidates.csv"
OUTPUT_SEED_MD = "a075_seed_candidates.md"
OUTPUT_GATE = "gate_review.json"
A075_SEED_COLUMNS = [
    "uid_literature",
    "cite_key",
    "title_or_hint",
    "class",
    "recommended_reason",
    "target_stage",
    "candidate_source",
    "theme_relation",
    "priority",
]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _resolve_workspace_root(config_path: Path, raw_cfg: Dict[str, Any]) -> Path:
    candidate = _stringify(raw_cfg.get("workspace_root"))
    if candidate:
        path = Path(candidate)
        if not path.is_absolute():
            raise ValueError(f"workspace_root 必须为绝对路径: {path}")
        return path
    return config_path.parents[2]


def _resolve_output_dir(config_path: Path, raw_cfg: Dict[str, Any]) -> Path:
    output_dir = Path(str(raw_cfg.get("legacy_output_dir") or raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(f"output_dir 必须为绝对路径: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _build_task_instance_dir(workspace_root: Path, node_code: str) -> Path:
    task_instance_dir = workspace_root / "tasks" / f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{node_code}"
    task_instance_dir.mkdir(parents=True, exist_ok=False)
    (task_instance_dir / "task_manifest.json").write_text(
        json.dumps(
            {
                "task_uid": task_instance_dir.name,
                "node_code": node_code,
                "workspace_root": str(workspace_root),
                "task_instance_dir": str(task_instance_dir),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return task_instance_dir


def _build_literature_lookup(literatures_df: pd.DataFrame) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_uid: Dict[str, Dict[str, Any]] = {}
    by_cite: Dict[str, Dict[str, Any]] = {}
    by_title: Dict[str, Dict[str, Any]] = {}
    if literatures_df is None or literatures_df.empty:
        return by_uid, by_cite, by_title
    for _, row in literatures_df.fillna("").iterrows():
        payload = row.to_dict()
        uid_literature = _stringify(payload.get("uid_literature"))
        cite_key = _stringify(payload.get("cite_key"))
        title = _stringify(payload.get("title"))
        if uid_literature:
            by_uid[uid_literature] = payload
        if cite_key:
            by_cite[cite_key] = payload
        if title and title not in by_title:
            by_title[title] = payload
    return by_uid, by_cite, by_title


def _classify_seed_bucket(title: str, reason: str, year: str) -> str:
    text = f"{_stringify(title)} {_stringify(reason)}".lower()
    if any(token in text for token in ("counter", "contradict", "null", "边界", "反例", "异质")):
        return "counterexample"
    if any(token in text for token in ("method", "identification", "instrument", "did", "rdd", "iv", "方法", "识别")):
        return "method_transfer"
    year_text = _stringify(year)
    if year_text.isdigit() and int(year_text) <= datetime.now().year - 5:
        return "classical_core"
    return "frontier"


def _safe_read_seed_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()


def _resolve_pdf_path(literature_row: pd.Series, attachments_df: pd.DataFrame) -> str:
    uid_literature = _stringify(literature_row.get("uid_literature"))
    attachment_rows = attachments_df[attachments_df.get("uid_literature", pd.Series(dtype=str)).astype(str) == uid_literature]
    if not attachment_rows.empty:
        attachment_rows = attachment_rows.sort_values(by=["is_primary", "attachment_name"], ascending=[False, True])
        path_text = _stringify(attachment_rows.iloc[0].get("storage_path") or attachment_rows.iloc[0].get("source_path"))
        if path_text:
            return path_text
    return _stringify(literature_row.get("pdf_path"))


def _build_seed_rows_from_a070_exports(
    *,
    workspace_root: Path,
    content_db: Path,
    literatures_df: pd.DataFrame,
    attachments_df: pd.DataFrame,
    existing_state_by_uid: Dict[str, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], pd.DataFrame, List[str]]:
    issues: List[str] = []
    review_done_df = load_review_state_df(content_db, flag_filters={"review_read_done": 1})
    if review_done_df.empty:
        return [], pd.DataFrame(columns=A075_SEED_COLUMNS), issues

    audits_dir = workspace_root / "knowledge" / "audits"
    priority_df = _safe_read_seed_csv(audits_dir / "review_priority_candidates.csv")
    reference_df = _safe_read_seed_csv(audits_dir / "review_reference_candidates.csv")
    if priority_df.empty and reference_df.empty:
        return [], pd.DataFrame(columns=A075_SEED_COLUMNS), issues

    by_uid, by_cite, by_title = _build_literature_lookup(literatures_df)
    candidate_rows: List[Dict[str, Any]] = []

    def _append_candidates(source_df: pd.DataFrame, *, source_name: str, default_reason: str, theme_relation: str, priority_base: float) -> None:
        if source_df is None or source_df.empty:
            return
        for _, row in source_df.fillna("").iterrows():
            raw_uid = _stringify(row.get("uid_literature"))
            raw_cite = _stringify(row.get("cite_key"))
            raw_title = _stringify(row.get("title") or row.get("title_or_hint"))
            matched = by_uid.get(raw_uid) if raw_uid else None
            if matched is None and raw_cite:
                matched = by_cite.get(raw_cite)
            if matched is None and raw_title:
                matched = by_title.get(raw_title)

            uid_literature = _stringify((matched or {}).get("uid_literature") or raw_uid)
            cite_key = _stringify((matched or {}).get("cite_key") or raw_cite)
            title = _stringify((matched or {}).get("title") or raw_title or cite_key or uid_literature)
            year = _stringify((matched or {}).get("year") or row.get("year"))
            reason = _stringify(row.get("reason") or row.get("source_review") or default_reason)
            bucket = _classify_seed_bucket(title, reason, year)

            if not uid_literature:
                issues.append(f"A070 seed 缺少 uid_literature: cite_key={cite_key or 'unknown'}")
                continue

            candidate_rows.append(
                {
                    "uid_literature": uid_literature,
                    "cite_key": cite_key,
                    "title_or_hint": title,
                    "class": bucket,
                    "recommended_reason": reason,
                    "target_stage": "A080",
                    "candidate_source": source_name,
                    "theme_relation": theme_relation,
                    "priority": priority_base,
                }
            )

    _append_candidates(
        priority_df,
        source_name="review_priority_candidates",
        default_reason="A070 优先候选",
        theme_relation="review_priority_candidate",
        priority_base=88.0,
    )
    _append_candidates(
        reference_df,
        source_name="review_reference_candidates",
        default_reason="A070 参考候选",
        theme_relation="review_reference_candidate",
        priority_base=66.0,
    )

    if not candidate_rows:
        return [], pd.DataFrame(columns=A075_SEED_COLUMNS), issues

    seed_df = pd.DataFrame(candidate_rows, columns=A075_SEED_COLUMNS)
    seed_df = seed_df.drop_duplicates(subset=["uid_literature", "cite_key"], keep="first").reset_index(drop=True)

    state_rows: List[Dict[str, Any]] = []
    for _, row in seed_df.fillna("").iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        literature_record = by_uid.get(uid_literature) or by_cite.get(cite_key)
        existing = existing_state_by_uid.get(uid_literature, {})

        preprocessed = int(existing.get("preprocessed") or 0)
        pending_preprocess = int(existing.get("pending_preprocess") or 0)
        pending_rough_read = int(existing.get("pending_rough_read") or 0)
        in_rough_read = int(existing.get("in_rough_read") or 0)
        rough_read_done = int(existing.get("rough_read_done") or 0)

        if rough_read_done:
            continue

        has_attachment = False
        if literature_record is not None:
            has_attachment = bool(_resolve_pdf_path(pd.Series(literature_record), attachments_df))

        if preprocessed and has_attachment:
            pending_preprocess = 0
            if not pending_rough_read and not in_rough_read:
                pending_rough_read = 1
        else:
            pending_preprocess = 1 if not pending_preprocess else pending_preprocess
            pending_rough_read = 0 if not in_rough_read else pending_rough_read

        state_row: Dict[str, Any] = {
            "uid_literature": uid_literature,
            "cite_key": cite_key,
            "source_stage": "A075_seed",
            "recommended_reason": _stringify(row.get("recommended_reason")) or "A070 seed",
            "theme_relation": _stringify(row.get("theme_relation")) or "a070_seed",
            "source_origin": "a070_export",
            "pending_preprocess": pending_preprocess,
            "preprocessed": preprocessed,
            "pending_rough_read": pending_rough_read,
            "in_rough_read": in_rough_read,
            "rough_read_done": rough_read_done,
            "pending_deep_read": int(existing.get("pending_deep_read") or 0),
            "deep_read_done": int(existing.get("deep_read_done") or 0),
            "deep_read_count": int(existing.get("deep_read_count") or 0),
            "reading_objective": _stringify(existing.get("reading_objective")),
            "manual_guidance": _stringify(existing.get("manual_guidance")),
        }
        state_rows.append(state_row)
        existing_state_by_uid[uid_literature] = state_row

    return state_rows, seed_df, issues


def _build_human_seed_state_rows(
    *,
    seed_contract: Dict[str, Any],
    literatures_df: pd.DataFrame,
    attachments_df: pd.DataFrame,
    existing_state_by_uid: Dict[str, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[str]]:
    if not bool(seed_contract.get("enabled", False)):
        return [], []

    seed_items = seed_contract.get("seed_items") or []
    if not isinstance(seed_items, list):
        return [], ["human_seed_contract.seed_items 不是数组，已跳过"]

    default_manual_guidance = _stringify(seed_contract.get("manual_guidance"))
    default_reading_objective = _stringify(seed_contract.get("reading_objective"))
    on_ambiguous = _stringify(seed_contract.get("on_ambiguous") or "manual_review") or "manual_review"
    on_missing = _stringify(seed_contract.get("on_missing") or "route_to_a040") or "route_to_a040"

    rows: List[Dict[str, Any]] = []
    issues: List[str] = []
    for item in seed_items:
        if not isinstance(item, dict):
            issues.append("human_seed_contract.seed_items 含非对象条目，已跳过")
            continue

        cite_key = _stringify(item.get("cite_key"))
        if not cite_key:
            issues.append("human_seed_contract.seed_items 存在空 cite_key，已跳过")
            continue

        matches = literatures_df[literatures_df.get("cite_key", pd.Series(dtype=str)).astype(str) == cite_key]
        if matches.empty:
            issues.append(f"{cite_key}: 未命中文献主表，策略={on_missing}")
            continue
        if len(matches) > 1:
            issues.append(f"{cite_key}: 命中多条文献，策略={on_ambiguous}")
            continue

        literature_row = matches.iloc[0]
        uid_literature = _stringify(literature_row.get("uid_literature"))
        if not uid_literature:
            issues.append(f"{cite_key}: 文献缺少 uid_literature，已跳过")
            continue

        existing = existing_state_by_uid.get(uid_literature, {})
        manual_guidance = _stringify(item.get("manual_guidance") or default_manual_guidance)
        reading_objective = _stringify(item.get("reading_objective") or default_reading_objective)
        reason = _stringify(item.get("recommended_reason") or item.get("reason") or "human seed")
        theme_relation = _stringify(item.get("theme_relation") or "human_seed")

        has_attachment = bool(_resolve_pdf_path(literature_row, attachments_df))
        preprocessed = int(existing.get("preprocessed") or 0)
        rough_done = int(existing.get("rough_read_done") or 0)

        if rough_done:
            issues.append(f"{cite_key}: 已 rough_read_done=1，跳过重复投递")
            continue

        pending_preprocess = int(existing.get("pending_preprocess") or 0)
        pending_rough_read = int(existing.get("pending_rough_read") or 0)
        if preprocessed and has_attachment:
            pending_preprocess = 0
            pending_rough_read = 1 if pending_rough_read == 0 else pending_rough_read
        else:
            pending_preprocess = 1

        row: Dict[str, Any] = {
            "uid_literature": uid_literature,
            "cite_key": cite_key,
            "source_stage": "A075_human_seed",
            "recommended_reason": reason,
            "theme_relation": theme_relation,
            "source_origin": "human",
            "manual_guidance": manual_guidance,
            "reading_objective": reading_objective,
            "pending_preprocess": pending_preprocess,
            "preprocessed": preprocessed,
            "pending_rough_read": pending_rough_read,
            "rough_read_done": rough_done,
            "pending_deep_read": int(existing.get("pending_deep_read") or 0),
            "deep_read_done": int(existing.get("deep_read_done") or 0),
            "deep_read_count": int(existing.get("deep_read_count") or 0),
        }
        rows.append(row)
        existing_state_by_uid[uid_literature] = row

    return rows, issues


def _write_seed_markdown(seed_df: pd.DataFrame, markdown_path: Path) -> None:
    lines = ["# a075_seed_candidates", ""]
    if seed_df.empty:
        lines.append("- 当前无可写回种子。")
    else:
        for _, row in seed_df.fillna("").iterrows():
            lines.append(
                "- "
                + f"{_stringify(row.get('cite_key')) or _stringify(row.get('uid_literature'))} | "
                + f"{_stringify(row.get('target_stage')) or 'A080'} | "
                + f"{_stringify(row.get('recommended_reason'))}"
            )
    markdown_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


@affair_auto_git_commit("A075")
def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)
    workspace_root = _resolve_workspace_root(config_path, raw_cfg)
    legacy_output_dir = _resolve_output_dir(config_path, raw_cfg)
    output_dir = _build_task_instance_dir(workspace_root, "A075")
    content_db, _ = resolve_content_db_config(
        raw_cfg,
        legacy_keys=("references_db",),
        default_path=workspace_root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME,
        required=True,
    )
    assert content_db is not None

    seeded_from_a070 = 0
    seeded_from_human = 0
    literatures_df, attachments_df, _ = load_reference_tables(db_path=content_db)
    existing_state_df = load_reading_state_df(content_db)
    existing_state_by_uid = {
        _stringify(row.get("uid_literature")): row.to_dict()
        for _, row in existing_state_df.fillna("").iterrows()
        if _stringify(row.get("uid_literature"))
    }

    a070_seed_rows, seed_df, a070_seed_issues = _build_seed_rows_from_a070_exports(
        workspace_root=workspace_root,
        content_db=content_db,
        literatures_df=literatures_df,
        attachments_df=attachments_df,
        existing_state_by_uid=existing_state_by_uid,
    )
    if a070_seed_rows:
        upsert_reading_state_rows(content_db, a070_seed_rows)
        seeded_from_a070 = len(a070_seed_rows)

    seed_contract = raw_cfg.get("human_seed_contract") or {}
    human_seed_rows, human_seed_issues = _build_human_seed_state_rows(
        seed_contract=seed_contract if isinstance(seed_contract, dict) else {},
        literatures_df=literatures_df,
        attachments_df=attachments_df,
        existing_state_by_uid=existing_state_by_uid,
    )
    if human_seed_rows:
        upsert_reading_state_rows(content_db, human_seed_rows)
        seeded_from_human = len(human_seed_rows)

    if human_seed_rows:
        human_df = pd.DataFrame(
            [
                {
                    "uid_literature": _stringify(row.get("uid_literature")),
                    "cite_key": _stringify(row.get("cite_key")),
                    "title_or_hint": "",
                    "class": "manual",
                    "recommended_reason": _stringify(row.get("recommended_reason")),
                    "target_stage": "A080",
                    "candidate_source": "human_seed_contract",
                    "theme_relation": _stringify(row.get("theme_relation")),
                    "priority": "99",
                }
                for row in human_seed_rows
            ]
        )
        seed_df = pd.concat([seed_df, human_df], ignore_index=True)
        seed_df = seed_df[A075_SEED_COLUMNS].drop_duplicates(subset=["uid_literature", "cite_key"], keep="first").reset_index(drop=True)

    failures: List[str] = list(a070_seed_issues) + list(human_seed_issues)
    seed_csv_path = output_dir / OUTPUT_SEED_CSV
    seed_md_path = output_dir / OUTPUT_SEED_MD
    seed_df.to_csv(seed_csv_path, index=False, encoding="utf-8-sig")
    _write_seed_markdown(seed_df, seed_md_path)

    gate_review = build_gate_review(
        node_uid="A075",
        node_name="非综述候选种子生成",
        summary=(
            f"生成非综述候选种子 {len(seed_df)} 条；"
            f"A070 导种 {seeded_from_a070} 条；"
            f"人工导种 {seeded_from_human} 条；"
            f"问题 {len(failures)} 条。"
        ),
        checks=[
            {"name": "seeded_from_a070_exports", "value": seeded_from_a070},
            {"name": "seeded_from_human_contract", "value": seeded_from_human},
            {"name": "a075_seed_candidates_count", "value": len(seed_df)},
            {"name": "failure_count", "value": len(failures)},
        ],
        artifacts=[str(seed_csv_path), str(seed_md_path)],
        recommendation="pass_next" if len(seed_df) > 0 else "retry_current",
        score=max(50.0, 96.0 - len(failures) * 8.0),
        issues=failures,
        metadata={
            "workspace_root": str(workspace_root),
            "content_db": str(content_db),
        },
    )
    gate_path = output_dir / OUTPUT_GATE
    gate_path.write_text(json.dumps(gate_review, ensure_ascii=False, indent=2), encoding="utf-8")

    if legacy_output_dir != output_dir:
        legacy_output_dir.mkdir(parents=True, exist_ok=True)
        for artifact_path in [seed_csv_path, seed_md_path, gate_path]:
            legacy_target = legacy_output_dir / artifact_path.name
            legacy_target.write_text(artifact_path.read_text(encoding="utf-8"), encoding="utf-8")

    try:
        append_aok_log_event(
            event_type="A075_NON_REVIEW_SEED_READY",
            project_root=workspace_root,
            affair_code="A075",
            handler_name="非综述候选种子生成",
            agent_names=["ar_A075_非综述候选种子生成事务智能体_v1"],
            skill_names=["ar_A075_非综述候选种子生成_v1"],
            reasoning_summary="消费 A070 导出件与人工种子，把普通文献候选写回 pending_preprocess。",
            gate_review=gate_review,
            gate_review_path=gate_path,
            artifact_paths=[seed_csv_path, seed_md_path, gate_path],
            payload={
                "seeded_from_a070_exports": seeded_from_a070,
                "seeded_from_human_contract": seeded_from_human,
                "seed_count": len(seed_df),
                "failure_count": len(failures),
            },
        )
    except Exception:
        pass

    return [seed_csv_path, seed_md_path, gate_path]
