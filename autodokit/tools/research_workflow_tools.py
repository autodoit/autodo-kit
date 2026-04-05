"""研究流程支持工具。

本模块为论文文献工程化流程提供 M1-M3 所需的最小公开工具：

1. 候选文献视图构建；
2. 阅读批次分发；
3. 综述候选抽取与研究脉络整理；
4. 闸门审计报告构造；
5. 创新点池维护与可行性评分。
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha1
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd


REVIEW_KEYWORDS: tuple[str, ...] = (
    "review",
    "survey",
    "综述",
    "述评",
    "评介",
    "研究进展",
    "研究现状",
    "进展",
    "回顾",
    "展望",
    "meta-analysis",
    "systematic",
    "systematic review",
)

DEFAULT_REVIEW_DETECTION_FIELDS: tuple[str, ...] = ("title", "keywords", "entry_type")
DEFAULT_TOPIC_RELEVANCE_FIELDS: tuple[str, ...] = ("title", "keywords", "abstract")


DEFAULT_CANDIDATE_VIEW_COLUMNS: List[str] = [
    "uid_literature",
    "cite_key",
    "view_note",
    "score",
    "source_round",
    "source_affair",
    "status",
    "updated_at",
]

DEFAULT_READING_BATCH_COLUMNS: List[str] = [
    "batch_id",
    "uid_literature",
    "priority",
    "read_stage",
    "assigned_reason",
    "batch_rank",
]

DEFAULT_INNOVATION_POOL_COLUMNS: List[str] = [
    "innovation_uid",
    "title",
    "source_gap",
    "method_family",
    "scenario",
    "data_source",
    "output_form",
    "novelty_type",
    "score_total",
    "status",
    "evidence_refs",
    "created_at",
    "updated_at",
]


def _utc_now_iso() -> str:
    """返回 UTC ISO 时间字符串。"""

    return datetime.now(tz=UTC).isoformat()


def _stringify(value: Any) -> str:
    """把任意值安全转换为字符串。"""

    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _ensure_columns(table: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    """确保表包含目标字段。"""

    result = table.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = ""
    return result


def _row_text(row: pd.Series, columns: Iterable[str]) -> str:
    """拼接多列文本，供规则筛选使用。"""

    parts: List[str] = []
    for column in columns:
        parts.append(_stringify(row.get(column)))
    return " ".join(part for part in parts if part).lower()


def _estimate_candidate_score(row: pd.Series) -> float:
    """为候选条目估算默认分值。"""

    raw_score = _stringify(row.get("score"))
    if raw_score:
        try:
            return float(raw_score)
        except ValueError:
            pass

    score = 50.0
    year_text = _stringify(row.get("year"))
    if year_text.isdigit():
        year = int(year_text)
        current_year = datetime.now(tz=UTC).year
        if year >= current_year - 3:
            score += 15.0
        elif year <= current_year - 10:
            score += 8.0

    literature_type = _stringify(row.get("literature_type")).lower()
    if literature_type == "review":
        score += 10.0

    run_read_decision = _stringify(row.get("run_read_decision")).lower()
    if run_read_decision == "read":
        score += 8.0
    elif run_read_decision == "skip":
        score -= 20.0

    run_read_status = _stringify(row.get("run_read_status")).lower()
    if run_read_status in {"read", "completed"}:
        score -= 10.0

    standardization_status = _stringify(row.get("standardization_status")).lower()
    if standardization_status == "standardized":
        score += 5.0

    topic_relevance_score = _stringify(row.get("topic_relevance_score"))
    if topic_relevance_score:
        try:
            score += min(float(topic_relevance_score), 30.0)
        except ValueError:
            pass

    return round(score, 4)


def _normalize_year(value: Any) -> int | None:
    """把年份字段归一化为整数。"""

    text = _stringify(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _normalize_term_list(values: Iterable[Any] | None) -> List[str]:
    """规范化主题词列表。"""

    result: List[str] = []
    for value in values or []:
        text = _stringify(value).lower()
        if text and text not in result:
            result.append(text)
    return result


def _normalize_term_groups(groups: Iterable[Iterable[Any]] | None) -> List[List[str]]:
    """规范化主题词组。"""

    normalized: List[List[str]] = []
    for group in groups or []:
        items = _normalize_term_list(group)
        if items:
            normalized.append(items)
    return normalized


def _matches_review_signal(
    row: pd.Series,
    *,
    text_columns: Iterable[str] | None = None,
) -> bool:
    """判断单条记录是否具有综述信号。"""

    detection_columns = list(text_columns or DEFAULT_REVIEW_DETECTION_FIELDS)
    text = _row_text(row, detection_columns)
    literature_type = _stringify(row.get("literature_type")).lower()
    if literature_type == "review":
        return True
    return any(keyword in text for keyword in REVIEW_KEYWORDS)


def filter_literature_for_topic(
    literature_table: pd.DataFrame,
    *,
    research_topic: str = "",
    topic_terms: Iterable[Any] | None = None,
    topic_keyword_groups: Iterable[Iterable[Any]] | None = None,
    required_topic_group_indices: Iterable[Any] | None = None,
    min_topic_group_matches: int | None = None,
    min_year: int | None = None,
    max_year: int | None = None,
    recent_years: int | None = None,
    relevance_text_fields: Iterable[str] | None = None,
) -> pd.DataFrame:
    """按研究主题与年份窗口过滤文献主表。"""

    if literature_table.empty:
        return literature_table.copy()

    normalized_terms = _normalize_term_list(topic_terms)
    normalized_groups = _normalize_term_groups(topic_keyword_groups)
    if recent_years is not None and max_year is None:
        max_year = datetime.now(tz=UTC).year
    if recent_years is not None and min_year is None and max_year is not None:
        min_year = max_year - max(int(recent_years), 0)

    fields = list(relevance_text_fields or DEFAULT_TOPIC_RELEVANCE_FIELDS)
    primary_fields = [field for field in ("title", "keywords") if field in fields]
    if not primary_fields:
        primary_fields = [field for field in ("title", "keywords") if field in literature_table.columns]
    all_fields = [field for field in fields if field in literature_table.columns]
    required_group_matches = int(min_topic_group_matches) if min_topic_group_matches is not None else (len(normalized_groups) if normalized_groups else 0)
    required_group_indexes = {
        int(item)
        for item in (required_topic_group_indices or [])
        if str(item).strip() != ""
    }

    kept_rows: List[Dict[str, Any]] = []
    for _, row in literature_table.iterrows():
        year_value = _normalize_year(row.get("year"))
        if min_year is not None and (year_value is None or year_value < min_year):
            continue
        if max_year is not None and (year_value is None or year_value > max_year):
            continue

        primary_text = _row_text(row, primary_fields or all_fields)
        all_text = _row_text(row, all_fields or primary_fields)

        matched_groups = 0
        matched_group_indexes: List[int] = []
        matched_group_terms: List[str] = []
        for group_index, group in enumerate(normalized_groups):
            hit_terms = [term for term in group if term in all_text]
            if hit_terms:
                matched_groups += 1
                matched_group_indexes.append(group_index)
                matched_group_terms.extend(hit_terms)

        matched_terms = [term for term in normalized_terms if term in all_text]
        if normalized_groups:
            passes_topic = matched_groups >= max(required_group_matches, 1)
        elif normalized_terms:
            passes_topic = bool(matched_terms)
        else:
            passes_topic = True

        if required_group_indexes and not required_group_indexes.issubset(set(matched_group_indexes)):
            passes_topic = False

        if not passes_topic:
            continue

        title_hits = sum(1 for term in matched_terms if term in primary_text)
        abstract_hits = sum(1 for term in matched_terms if term in all_text and term not in primary_text)
        group_bonus = matched_groups * 8.0
        relevance_score = group_bonus + title_hits * 6.0 + abstract_hits * 2.0

        row_dict = dict(row)
        row_dict["topic_relevance_score"] = round(relevance_score, 4)
        row_dict["topic_group_match_count"] = matched_groups
        row_dict["topic_group_match_indexes"] = "; ".join(str(item) for item in matched_group_indexes)
        row_dict["topic_matched_terms"] = "; ".join(sorted(set(matched_terms + matched_group_terms)))
        row_dict["research_topic"] = research_topic
        kept_rows.append(row_dict)

    if not kept_rows:
        empty = literature_table.iloc[0:0].copy()
        empty["topic_relevance_score"] = pd.Series(dtype=float)
        empty["topic_group_match_count"] = pd.Series(dtype=int)
        empty["topic_group_match_indexes"] = pd.Series(dtype=str)
        empty["topic_matched_terms"] = pd.Series(dtype=str)
        empty["research_topic"] = pd.Series(dtype=str)
        return empty
    return pd.DataFrame(kept_rows)


def _select_candidate_records(
    literature_table: pd.DataFrame,
    *,
    literature_kind: str,
    source_round: str,
    source_affair: str,
    require_standardized: bool = True,
    review_detection_fields: Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    """从文献主表中提取候选记录。"""

    if literature_table.empty:
        return []

    rows: List[Dict[str, Any]] = []
    for _, row in literature_table.iterrows():
        standardization_status = _stringify(row.get("standardization_status")).lower()
        if require_standardized and standardization_status and standardization_status != "standardized":
            continue

        is_review = _matches_review_signal(row, text_columns=review_detection_fields)
        if literature_kind == "review" and not is_review:
            continue
        if literature_kind == "non_review" and is_review:
            continue

        rows.append(
            {
                "uid_literature": _stringify(row.get("uid_literature") or row.get("uid")),
                "cite_key": _stringify(row.get("cite_key")),
                "view_note": _stringify(row.get("view_note") or row.get("title") or row.get("keywords")),
                "score": _estimate_candidate_score(row),
                "status": _stringify(row.get("status") or row.get("run_read_status") or "candidate"),
                "source_round": source_round,
                "source_affair": source_affair,
            }
        )
    return rows


def _filter_by_uid(index_table: pd.DataFrame, uid_list: Iterable[str]) -> pd.DataFrame:
    """按 uid 过滤索引表。"""

    uid_set = {_stringify(uid) for uid in uid_list if _stringify(uid)}
    if index_table.empty or not uid_set:
        return index_table.iloc[0:0].copy()
    return index_table[index_table["uid_literature"].astype(str).isin(uid_set)].reset_index(drop=True)


def _split_read_status(table: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """拆分未读池与已读退出视图。"""

    if table.empty:
        return table.copy(), table.copy()
    unread_mask = []
    for _, row in table.iterrows():
        run_read_status = _stringify(row.get("run_read_status")).lower()
        unread_mask.append(run_read_status not in {"read", "completed"})
    unread_table = table.loc[unread_mask].reset_index(drop=True)
    exit_table = table.loc[[not flag for flag in unread_mask]].reset_index(drop=True)
    return unread_table, exit_table


def build_review_candidate_views(
    literature_table: pd.DataFrame,
    *,
    source_round: str,
    source_affair: str = "review_candidate_views",
    min_score: float = 0.0,
    top_k: int | None = None,
    batch_size: int = 10,
    extra_fields: Iterable[str] | None = None,
    research_topic: str = "",
    topic_terms: Iterable[Any] | None = None,
    topic_keyword_groups: Iterable[Iterable[Any]] | None = None,
    required_topic_group_indices: Iterable[Any] | None = None,
    min_topic_group_matches: int | None = None,
    min_year: int | None = None,
    max_year: int | None = None,
    recent_years: int | None = None,
    review_detection_fields: Iterable[str] | None = None,
    relevance_text_fields: Iterable[str] | None = None,
) -> Dict[str, pd.DataFrame]:
    """构建 A05 所需的综述候选视图集合。"""

    scoped_table = filter_literature_for_topic(
        literature_table,
        research_topic=research_topic,
        topic_terms=topic_terms,
        topic_keyword_groups=topic_keyword_groups,
        required_topic_group_indices=required_topic_group_indices,
        min_topic_group_matches=min_topic_group_matches,
        min_year=min_year,
        max_year=max_year,
        recent_years=recent_years,
        relevance_text_fields=relevance_text_fields,
    )
    records = _select_candidate_records(
        scoped_table,
        literature_kind="review",
        source_round=source_round,
        source_affair=source_affair,
        review_detection_fields=review_detection_fields,
    )
    index_table = build_candidate_view_index(
        records,
        source_round=source_round,
        source_affair=source_affair,
        min_score=min_score,
        top_k=top_k,
    )
    readable_table = build_candidate_readable_view(index_table, scoped_table, extra_fields=extra_fields)
    review_priority_view = readable_table.sort_values(by=["score", "year"], ascending=[False, False], na_position="last").reset_index(drop=True) if not readable_table.empty else readable_table.copy()
    review_read_pool, review_already_read_exit_view = _split_read_status(review_priority_view)
    review_deep_read_queue_seed = review_read_pool.head(min(max(batch_size, 1), 5)).reset_index(drop=True)
    reading_batches = allocate_reading_batches(
        index_table,
        batch_size=batch_size,
        review_uid_set=index_table.get("uid_literature", pd.Series(dtype=str)).tolist(),
    )
    return {
        "review_candidate_pool_index": index_table,
        "review_candidate_pool_readable": readable_table,
        "review_priority_view": review_priority_view,
        "review_deep_read_queue_seed": review_deep_read_queue_seed,
        "review_read_pool": review_read_pool,
        "review_already_read_exit_view": review_already_read_exit_view,
        "review_reading_batches": reading_batches,
    }


def build_non_review_candidate_views(
    literature_table: pd.DataFrame,
    *,
    source_round: str,
    source_affair: str = "A07",
    min_score: float = 0.0,
    top_k: int | None = None,
    batch_size: int = 10,
    extra_fields: Iterable[str] | None = None,
) -> Dict[str, pd.DataFrame]:
    """构建 A07 所需的非综述候选视图集合。"""

    records = _select_candidate_records(
        literature_table,
        literature_kind="non_review",
        source_round=source_round,
        source_affair=source_affair,
    )
    index_table = build_candidate_view_index(
        records,
        source_round=source_round,
        source_affair=source_affair,
        min_score=min_score,
        top_k=top_k,
    )
    readable_table = build_candidate_readable_view(index_table, literature_table, extra_fields=extra_fields)
    current_year = datetime.now(tz=UTC).year
    classical_uid: List[str] = []
    frontier_uid: List[str] = []
    counterexample_uid: List[str] = []
    method_transfer_uid: List[str] = []
    counterexample_keywords = ("counter", "contradict", "null", "边界", "异质", "反例")
    method_keywords = ("method", "identification", "instrument", "did", "rdd", "iv", "方法", "识别")
    for _, row in readable_table.iterrows():
        uid_literature = _stringify(row.get("uid_literature"))
        year_text = _stringify(row.get("year"))
        text = _row_text(row, ["title", "keywords", "abstract"])
        if year_text.isdigit() and int(year_text) <= current_year - 5:
            classical_uid.append(uid_literature)
        if year_text.isdigit() and int(year_text) >= current_year - 3:
            frontier_uid.append(uid_literature)
        if any(keyword in text for keyword in counterexample_keywords):
            counterexample_uid.append(uid_literature)
        if any(keyword in text for keyword in method_keywords):
            method_transfer_uid.append(uid_literature)

    non_review_rough_read_pool, already_read_exit_view = _split_read_status(readable_table)
    deep_mask = []
    for _, row in non_review_rough_read_pool.iterrows():
        stage = _stringify(row.get("reading_stage")).lower()
        deep_mask.append(stage in {"deep_read", "deep", "deep_queue"})
    non_review_deep_read_pool = non_review_rough_read_pool.loc[deep_mask].reset_index(drop=True)
    if non_review_deep_read_pool.empty:
        non_review_deep_read_pool = non_review_rough_read_pool.head(min(max(batch_size // 2, 1), 10)).reset_index(drop=True)

    reading_batches = allocate_reading_batches(index_table, batch_size=batch_size)
    return {
        "non_review_candidate_pool_index": index_table,
        "non_review_candidate_pool_readable": readable_table,
        "classical_core_view": _filter_by_uid(readable_table, classical_uid),
        "frontier_view": _filter_by_uid(readable_table, frontier_uid),
        "counterexample_view": _filter_by_uid(readable_table, counterexample_uid),
        "method_transfer_view": _filter_by_uid(readable_table, method_transfer_uid),
        "non_review_rough_read_pool": non_review_rough_read_pool,
        "non_review_deep_read_pool": non_review_deep_read_pool,
        "already_read_exit_view": already_read_exit_view,
        "non_review_reading_batches": reading_batches,
    }


def init_empty_candidate_view_table() -> pd.DataFrame:
    """初始化空候选视图主表。"""

    return pd.DataFrame(columns=list(DEFAULT_CANDIDATE_VIEW_COLUMNS))


def init_empty_reading_batch_table() -> pd.DataFrame:
    """初始化空阅读批次表。"""

    return pd.DataFrame(columns=list(DEFAULT_READING_BATCH_COLUMNS))


def init_empty_innovation_pool_table() -> pd.DataFrame:
    """初始化空创新点池表。"""

    return pd.DataFrame(columns=list(DEFAULT_INNOVATION_POOL_COLUMNS))


def build_candidate_view_index(
    records: Iterable[Dict[str, Any]],
    *,
    source_round: str,
    source_affair: str,
    min_score: float = 0.0,
    top_k: int | None = None,
    default_status: str = "candidate",
) -> pd.DataFrame:
    """构建轻量候选视图主索引。

    Args:
        records: 原始候选记录集合。
        source_round: 来源轮次。
        source_affair: 来源事务。
        min_score: 最低分阈值。
        top_k: 可选保留前 K 条。
        default_status: 默认状态。

    Returns:
        规范化后的候选视图 DataFrame。
    """

    normalized_rows: List[Dict[str, Any]] = []
    for record in records:
        score = float(record.get("score") or 0.0)
        if score < min_score:
            continue
        normalized_rows.append(
            {
                "uid_literature": _stringify(record.get("uid_literature") or record.get("uid")),
                "cite_key": _stringify(record.get("cite_key")),
                "view_note": _stringify(record.get("view_note") or record.get("reason") or record.get("title")),
                "score": round(score, 4),
                "source_round": source_round,
                "source_affair": source_affair,
                "status": _stringify(record.get("status")) or default_status,
                "updated_at": _utc_now_iso(),
            }
        )
    table = pd.DataFrame(normalized_rows)
    table = _ensure_columns(table, list(DEFAULT_CANDIDATE_VIEW_COLUMNS))
    if not table.empty:
        table = table.sort_values(by=["score", "uid_literature"], ascending=[False, True]).reset_index(drop=True)
    if top_k is not None:
        table = table.head(top_k).reset_index(drop=True)
    return table


def build_candidate_readable_view(
    index_table: pd.DataFrame,
    literature_table: pd.DataFrame,
    *,
    extra_fields: Iterable[str] | None = None,
) -> pd.DataFrame:
    """把轻量视图索引 join 到文献表，生成人类可读展开表。

    Args:
        index_table: 轻量视图索引表。
        literature_table: 文献主表。
        extra_fields: 需要追加的文献字段。

    Returns:
        可读展开表。
    """

    working_index = _ensure_columns(index_table, list(DEFAULT_CANDIDATE_VIEW_COLUMNS))
    working_literature = literature_table.copy()
    if "uid_literature" not in working_literature.columns:
        return working_index
    fields = [
        "uid_literature",
        "title",
        "first_author",
        "year",
        "keywords",
        "abstract",
        "entry_type",
        "source",
    ]
    for field in extra_fields or []:
        if field not in fields:
            fields.append(field)
    selected_fields = [field for field in fields if field in working_literature.columns]
    return working_index.merge(
        working_literature[selected_fields],
        how="left",
        on="uid_literature",
    )


def extract_review_candidates(readable_table: pd.DataFrame) -> pd.DataFrame:
    """从可读视图中抽取综述候选。

    Args:
        readable_table: 可读视图表。

    Returns:
        命中综述特征的子表。
    """

    if readable_table.empty:
        return readable_table.copy()
    mask = []
    for _, row in readable_table.iterrows():
        mask.append(_matches_review_signal(row))
    return readable_table.loc[mask].reset_index(drop=True)


def allocate_reading_batches(
    index_table: pd.DataFrame,
    *,
    batch_size: int = 10,
    review_uid_set: Iterable[str] | None = None,
) -> pd.DataFrame:
    """按照优先级生成阅读批次。

    Args:
        index_table: 候选视图索引表。
        batch_size: 每批数量。
        review_uid_set: 综述优先 UID 集合。

    Returns:
        阅读批次表。
    """

    working = _ensure_columns(index_table, list(DEFAULT_CANDIDATE_VIEW_COLUMNS))
    review_set = {item for item in (review_uid_set or []) if _stringify(item)}
    rows: List[Dict[str, Any]] = []
    if working.empty:
        return init_empty_reading_batch_table()
    ordered = working.sort_values(by=["score", "uid_literature"], ascending=[False, True]).reset_index(drop=True)
    for order, (_, row) in enumerate(ordered.iterrows(), start=1):
        batch_number = ((order - 1) // max(batch_size, 1)) + 1
        uid_literature = _stringify(row.get("uid_literature"))
        is_review = uid_literature in review_set
        rows.append(
            {
                "batch_id": f"batch_{batch_number:02d}",
                "uid_literature": uid_literature,
                "priority": "high" if order <= 3 or is_review else ("medium" if order <= batch_size else "low"),
                "read_stage": "review" if is_review else ("rough" if order <= batch_size else "deep_queue"),
                "assigned_reason": "综述优先" if is_review else ("高分候选" if order <= batch_size else "后续补读"),
                "batch_rank": str(order),
            }
        )
    return pd.DataFrame(rows, columns=list(DEFAULT_READING_BATCH_COLUMNS))


def build_research_trajectory(items: Iterable[Dict[str, Any]], *, topic: str) -> Dict[str, Any]:
    """根据候选条目构造研究脉络摘要。

    Args:
        items: 条目集合。
        topic: 研究主题。

    Returns:
        研究脉络摘要字典。
    """

    normalized_items = [dict(item) for item in items]
    normalized_items.sort(key=lambda item: (_stringify(item.get("year")) or "9999", _stringify(item.get("title"))))
    timeline: List[Dict[str, Any]] = []
    for item in normalized_items:
        timeline.append(
            {
                "year": _stringify(item.get("year")) or "未知年份",
                "title": _stringify(item.get("title")),
                "uid_literature": _stringify(item.get("uid_literature")),
                "signal": _stringify(item.get("view_note") or item.get("keywords") or item.get("abstract"))[:160],
            }
        )
    return {
        "topic": topic,
        "timeline": timeline,
        "item_count": len(timeline),
        "summary": f"围绕主题“{topic}”整理出 {len(timeline)} 条可追踪研究脉络。",
    }


def build_gate_review(
    *,
    node_uid: str,
    node_name: str,
    summary: str,
    checks: Iterable[Dict[str, Any]] | None = None,
    artifacts: Iterable[str] | None = None,
    recommendation: str = "pass",
    score: float = 0.0,
    issues: Iterable[str] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """构造统一闸门审计报告。

    Args:
        node_uid: 节点编号。
        node_name: 节点名称。
        summary: 审计摘要。
        checks: 检查项列表。
        artifacts: 关联产物列表。
        recommendation: 建议动作。
        score: 审计评分。
        issues: 问题列表。
        metadata: 额外元数据。

    Returns:
        统一结构的闸门审计报告。
    """

    return {
        "gate_uid": f"G_{node_uid}",
        "node_uid": node_uid,
        "node_name": node_name,
        "summary": summary,
        "checks": list(checks or []),
        "artifacts": list(artifacts or []),
        "recommendation": recommendation,
        "score": round(float(score), 2),
        "issues": list(issues or []),
        "metadata": dict(metadata or {}),
        "created_at": _utc_now_iso(),
    }


def score_gate_review(review: Dict[str, Any], *, pass_threshold: float = 80.0) -> Dict[str, Any]:
    """根据闸门审计报告补充建议结论。

    Args:
        review: 闸门审计报告。
        pass_threshold: 通过阈值。

    Returns:
        附带建议动作的报告副本。
    """

    result = dict(review)
    score = float(result.get("score") or 0.0)
    issue_count = len(result.get("issues") or [])
    if score >= pass_threshold and issue_count == 0:
        result["recommendation"] = "pass"
    elif score >= max(pass_threshold - 15, 0):
        result["recommendation"] = "revise"
    else:
        result["recommendation"] = "fallback"
    return result


def merge_human_gate_decision(
    review: Dict[str, Any],
    *,
    human_decision: str,
    note: str = "",
    next_step: str = "",
    next_task_action: str = "",
) -> Dict[str, Any]:
    """将人类决策并入闸门审计报告。

    Args:
        review: 闸门审计报告。
        human_decision: 人类决策。
        note: 决策备注。
        next_step: 下一步骤。
        next_task_action: 下一任务动作。

    Returns:
        合并后的报告字典。
    """

    result = dict(review)
    result["human_decision"] = human_decision
    result["decision_note"] = note
    result["next_step"] = next_step
    result["next_task_action"] = next_task_action
    result["decision_at"] = _utc_now_iso()
    return result


def innovation_pool_upsert(
    pool_table: pd.DataFrame,
    innovation_item: Dict[str, Any],
    *,
    overwrite: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """插入或更新创新点池记录。

    Args:
        pool_table: 创新点池表。
        innovation_item: 创新点记录。
        overwrite: 是否覆盖旧值。

    Returns:
        `(更新后的表, 规范化记录, 动作)`。
    """

    working = _ensure_columns(pool_table, list(DEFAULT_INNOVATION_POOL_COLUMNS))
    title = _stringify(innovation_item.get("title"))
    innovation_uid = _stringify(innovation_item.get("innovation_uid")) or f"inn-{sha1(title.encode('utf-8')).hexdigest()[:16]}"
    now = _utc_now_iso()
    normalized = {
        "innovation_uid": innovation_uid,
        "title": title,
        "source_gap": _stringify(innovation_item.get("source_gap")),
        "method_family": _stringify(innovation_item.get("method_family")),
        "scenario": _stringify(innovation_item.get("scenario")),
        "data_source": _stringify(innovation_item.get("data_source")),
        "output_form": _stringify(innovation_item.get("output_form")),
        "novelty_type": _stringify(innovation_item.get("novelty_type")),
        "score_total": _stringify(innovation_item.get("score_total")),
        "status": _stringify(innovation_item.get("status")) or "candidate",
        "evidence_refs": _stringify(innovation_item.get("evidence_refs")),
        "created_at": _stringify(innovation_item.get("created_at")) or now,
        "updated_at": now,
    }
    matches = working.index[working["innovation_uid"].astype(str) == innovation_uid].tolist()
    if not matches:
        return pd.concat([working, pd.DataFrame([normalized])], ignore_index=True), normalized, "inserted"
    idx = matches[0]
    current = dict(working.loc[idx])
    merged: Dict[str, Any] = {}
    for column in DEFAULT_INNOVATION_POOL_COLUMNS:
        current_value = _stringify(current.get(column))
        incoming_value = _stringify(normalized.get(column))
        merged[column] = incoming_value if (overwrite and incoming_value) else (current_value or incoming_value)
    for column, value in merged.items():
        working.at[idx, column] = value
    return working, merged, "updated"


def innovation_feasibility_score(innovation_item: Dict[str, Any]) -> Dict[str, Any]:
    """对创新点做四维可行性评分。

    Args:
        innovation_item: 创新点记录。

    Returns:
        含总分与建议的评分结果。
    """

    dimensions = {
        "data_availability": 25.0 if _stringify(innovation_item.get("data_source")) else 5.0,
        "method_readiness": 25.0 if _stringify(innovation_item.get("method_family")) else 5.0,
        "scenario_specificity": 25.0 if _stringify(innovation_item.get("scenario")) else 5.0,
        "output_specificity": 25.0 if _stringify(innovation_item.get("output_form")) else 5.0,
    }
    total_score = round(sum(dimensions.values()), 2)
    if total_score >= 85:
        recommendation = "promote"
    elif total_score >= 65:
        recommendation = "revise"
    else:
        recommendation = "fallback"
    return {
        "innovation_uid": _stringify(innovation_item.get("innovation_uid")),
        "title": _stringify(innovation_item.get("title")),
        "dimensions": dimensions,
        "score_total": total_score,
        "recommendation": recommendation,
    }