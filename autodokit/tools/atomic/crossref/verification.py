from __future__ import annotations

"""CrossRef 题录匹配评分与批量验证工具。

提供单条匹配评分、单条完整验证与批量验证三种粒度，
兼容 ``bib_verification_tracker`` JSONL 格式的追踪文件。
"""

import datetime
import json
import re
import time
from pathlib import Path
from typing import Any

from autodokit.tools.atomic.crossref.crossref_client import crossref_search


# ── 辅助 ──────────────────────────────────────────────────────────────


def _clean(s: str) -> str:
    """去除非字母数字字符并小写化。"""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _extract_first_author_last(author_raw: str) -> str:
    """从 'Acemoglu D and Ozdaglar A' 格式提取第一作者姓氏。"""
    if not author_raw:
        return ""
    first_part = author_raw.split("and")[0].strip()
    return first_part.split(",")[0].split()[0] if first_part else ""


def _coerce_year(val: Any) -> str:
    """安全提取年份字符串。"""
    if not val:
        return ""
    return str(val).strip()[:4]


# ── 匹配评分 ──────────────────────────────────────────────────────────


def crossref_match_score(
    bib_title: str,
    bib_author: str,
    crossref_results: list[dict[str, Any]],
    pass_threshold: int = 50,
) -> tuple[float, dict[str, Any] | None]:
    """计算 CrossRef 返回结果与目标条目之间的匹配评分（0-100）。

    评分由三部分组成：
    - **标题词重叠**（最高 60 分）：bib 标题与候选标题的共同词比例。
    - **作者匹配**（最高 20 分）：作者姓氏前 4 字符匹配加分。
    - **API 评分归一化**（最高 20 分）：CrossRef 内置 score 归一化。

    Args:
        bib_title: 待验证文献的标题。
        bib_author: 待验证文献的作者字符串（``'Acemoglu D and Ozdaglar A'`` 格式）。
        crossref_results: ``crossref_search()`` 返回的结果列表。
        pass_threshold: 判定为 PASS 的最低评分阈值，默认 50。

    Returns:
        (best_score, best_result) 二元组：
            - best_score: 最高匹配评分（0-100）。
            - best_result: 匹配度最高的结果 dict，若无任何结果则返回 None。

    Examples:
        >>> results = crossref_search("Systemic risk", "Acemoglu")
        >>> score, best = crossref_match_score("Systemic risk", "Acemoglu", results)
        >>> score >= 50
        True
    """
    ct = _clean(bib_title)
    ca = _clean(bib_author)
    best_score: float = 0.0
    best_result: dict[str, Any] | None = None

    ct_words = set(ct.split()) if ct else set()

    for r in crossref_results:
        rt = _clean(r.get("title", ""))
        rt_words = set(rt.split()) if rt else set()

        if not ct_words:
            title_score = 0.0
        else:
            overlap = len(ct_words & rt_words) / len(ct_words)
            title_score = overlap * 60.0

        author_score = 20.0 if ca and ca[:4] in _clean(r.get("author", "")) else 0.0
        api_score = min(float(r.get("score", 0)) / 100.0, 20.0)

        total = title_score + author_score + api_score
        if total > best_score:
            best_score = total
            best_result = r

    return best_score, best_result


# ── 单条验证 ──────────────────────────────────────────────────────────


def crossref_verify_single(
    title: str,
    author_raw: str,
    bib_year: str = "",
    pass_threshold: int = 50,
    rate_limit: float = 0.8,
) -> dict[str, Any]:
    """对单条文献执行 CrossRef 验证并返回结果摘要。

    流程：
    1. 解析作者姓氏。
    2. 调用 ``crossref_search()`` 查询。
    3. 调用 ``crossref_match_score()`` 计算匹配分数。
    4. 结合年份一致性给出 PASS / PARTIAL 判定。

    Args:
        title: 待验证文献标题。
        author_raw: 作者字符串。
        bib_year: BibTeX 中的出版年份（用于年份一致性检查）。
        pass_threshold: PASS 阈值，默认 50。
        rate_limit: 每次 API 调用间隔秒数，默认 0.8。

    Returns:
        dict 含以下键：
            - status (str): ``'PASS'`` 或 ``'PARTIAL'``。
            - score (float): 匹配评分。
            - doi (str): 最佳匹配的 DOI。
            - matched_year (str): 最佳匹配的年份。
            - notes (str): 说明文字。
            - checked_at (str): ISO 时间戳。

    Examples:
        >>> result = crossref_verify_single("Systemic risk", "Acemoglu D", "2015")
        >>> result["status"]
        'PASS'
    """
    author_last = _extract_first_author_last(author_raw)
    if not title or not author_last:
        return {
            "status": "PARTIAL",
            "score": 0.0,
            "doi": "",
            "matched_year": "",
            "notes": "标题或作者为空，跳过验证",
            "checked_at": datetime.datetime.now().isoformat(),
        }

    time.sleep(rate_limit)
    results = crossref_search(title, author_last)

    if not results:
        return {
            "status": "PARTIAL",
            "score": 0.0,
            "doi": "",
            "matched_year": "",
            "notes": "CrossRef 无返回结果",
            "checked_at": datetime.datetime.now().isoformat(),
        }

    score, best = crossref_match_score(title, author_raw, results, pass_threshold)

    if best is None:
        return {
            "status": "PARTIAL",
            "score": score,
            "doi": "",
            "matched_year": "",
            "notes": "CrossRef 无匹配",
            "checked_at": datetime.datetime.now().isoformat(),
        }

    matched_year = _coerce_year(best.get("year", ""))
    bib_year_s = _coerce_year(bib_year)
    year_ok = (not bib_year_s) or (
        matched_year and abs(int(matched_year) - int(bib_year_s)) <= 1
    )
    doi = best.get("doi", "")

    if score >= pass_threshold and year_ok:
        status = "PASS"
        notes = f"CrossRef 匹配 score={score:.0f} doi={doi}"
    else:
        status = "PARTIAL"
        notes = f"CrossRef 低匹配 score={score:.0f} doi={doi} year={matched_year}"

    return {
        "status": status,
        "score": score,
        "doi": doi,
        "matched_year": matched_year,
        "notes": notes,
        "checked_at": datetime.datetime.now().isoformat(),
    }


# ── 批量验证 ──────────────────────────────────────────────────────────


def crossref_batch_verify(
    entries: list[dict[str, Any]],
    batch_size: int = 20,
    pass_threshold: int = 50,
    rate_limit: float = 0.8,
    progress_callback: Any = None,
) -> list[dict[str, Any]]:
    """批量执行 CrossRef 题录验证。

    支持增量输出：每处理完一条即调用 ``progress_callback(已处理, 总数, 当前结果)``。

    Args:
        entries: 待验证条目列表，每条需含 ``cite_key``、``title``（或 ``bib_title``）、
            ``author``（或 ``bib_author``）、``year``（或 ``bib_year``）字段。
        batch_size: 每批数量（仅用于日志分组），默认 20。
        pass_threshold: PASS 阈值，默认 50。
        rate_limit: API 调用间隔秒数，默认 0.8。
        progress_callback: 可选进度回调函数 ``fn(processed, total, result_dict)``。

    Returns:
        验证结果列表，每条为 ``crossref_verify_single()`` 的返回再加 ``cite_key``。

    Examples:
        >>> entries = [{"cite_key": "D2015143", "title": "Systemic risk", "author": "Acemoglu D"}]
        >>> results = crossref_batch_verify(entries, rate_limit=0)
        >>> results[0]["status"]
        'PASS'  # or 'PARTIAL'
    """
    results: list[dict[str, Any]] = []
    total = len(entries)

    for i, entry in enumerate(entries):
        title = entry.get("title") or entry.get("bib_title", "")
        author = entry.get("author") or entry.get("bib_author", "")
        year = entry.get("year") or entry.get("bib_year", "")

        vr = crossref_verify_single(
            title=title,
            author_raw=author,
            bib_year=year,
            pass_threshold=pass_threshold,
            rate_limit=rate_limit,
        )
        vr["cite_key"] = entry.get("cite_key", f"entry_{i}")
        results.append(vr)

        if progress_callback:
            progress_callback(i + 1, total, vr)

    return results


# ── Tracker 级批量验证 ────────────────────────────────────────────────


def crossref_verify_tracker(
    tracker_path: str | Path,
    pass_threshold: int = 50,
    rate_limit: float = 0.8,
    filter_is_chinese: bool | None = False,
    inplace: bool = True,
) -> dict[str, Any]:
    """读取 ``bib_verification_tracker.jsonl`` 并对其中的待验证条目执行 CrossRef 验证。

    Args:
        tracker_path: JSONL 追踪文件路径。
        pass_threshold: PASS 阈值，默认 50。
        rate_limit: API 调用间隔，默认 0.8 秒。
        filter_is_chinese: 过滤条件：
            - ``False``（默认）：仅验证非中文条目。
            - ``True``：仅验证中文条目。
            - ``None``：验证所有待验证条目。
        inplace: 是否直接修改追踪文件；否则仅返回结果摘要。

    Returns:
        运行摘要 dict：
            - total (int): 尝试验证的条目总数。
            - pass_count (int): PASS 数。
            - partial_count (int): PARTIAL 数。
            - status_summary (dict): 全部条目的状态分布。
            - tracker_path (str): 追踪文件路径。

    Raises:
        FileNotFoundError: 追踪文件不存在。
        ValueError: 追踪文件格式错误。

    Examples:
        >>> summary = crossref_verify_tracker("bib_verification_tracker.jsonl")
        >>> summary["pass_count"] >= 0
        True
    """
    tpath = Path(tracker_path).expanduser().resolve()
    if not tpath.exists():
        raise FileNotFoundError(f"追踪文件不存在：{tpath}")

    with tpath.open("r", encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    if not lines:
        raise ValueError(f"追踪文件为空：{tpath}")

    tracker_list: list[dict[str, Any]] = [json.loads(l) for l in lines]
    tracker_map: dict[str, dict[str, Any]] = {
        t["cite_key"]: t for t in tracker_list
    }

    # 筛选待验证条目
    pending: list[dict[str, Any]] = []
    for t in tracker_list:
        if t.get("status", "").upper() != "PENDING":
            continue
        is_cn = t.get("is_chinese", False)
        if filter_is_chinese is None:
            pending.append(t)
        elif filter_is_chinese and is_cn:
            pending.append(t)
        elif not filter_is_chinese and not is_cn:
            pending.append(t)

    if not pending:
        return {
            "total": 0,
            "pass_count": 0,
            "partial_count": 0,
            "status_summary": _status_distribution(tracker_list),
            "tracker_path": str(tpath),
            "notes": "没有待验证条目满足过滤条件",
        }

    now_ts = datetime.datetime.now().isoformat()

    def _progress(processed: int, total: int, result: dict[str, Any]) -> None:
        pass  # 非 CLI 环境下静默进展

    # 逐条验证
    verified_count = 0
    for t in pending:
        key = t["cite_key"]
        title = t.get("bib_title", "")
        author = t.get("bib_author", "")
        year = t.get("bib_year", "")

        vr = crossref_verify_single(
            title=title,
            author_raw=author,
            bib_year=year,
            pass_threshold=pass_threshold,
            rate_limit=rate_limit,
        )

        if key in tracker_map:
            tracker_map[key]["status"] = vr["status"]
            tracker_map[key]["checked_at"] = now_ts
            tracker_map[key]["source"] = "CrossRef"
            tracker_map[key]["notes"] = vr.get("notes", "")
        verified_count += 1

    # 写回
    if inplace:
        with tpath.open("w", encoding="utf-8") as f:
            for k in sorted(tracker_map.keys(), key=lambda x: tracker_map[x].get("index", 0)):
                f.write(json.dumps(tracker_map[k], ensure_ascii=False) + "\n")

    pass_count = sum(1 for v in tracker_map.values() if v.get("status") == "PASS")
    partial_count = sum(
        1 for v in tracker_map.values() if v.get("status") == "PARTIAL"
    )

    return {
        "total": verified_count,
        "pass_count": pass_count,
        "partial_count": partial_count,
        "status_summary": _status_distribution(list(tracker_map.values())),
        "tracker_path": str(tpath),
        "inplace_updated": inplace,
        "checked_at": now_ts,
    }


def _status_distribution(trackers: list[dict[str, Any]]) -> dict[str, int]:
    """统计追踪列表中的状态分布。"""
    dist: dict[str, int] = {}
    for t in trackers:
        s = t.get("status", "UNKNOWN")
        dist[s] = dist.get(s, 0) + 1
    return dist
