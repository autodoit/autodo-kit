"""文献数据库管理工具。

该模块提供文献数据库常用能力：
- 文献 `uid` 生成；
- 标题 `clean_title` 规范化；
- 空数据库初始化；
- 文献记录插入/更新（upsert）；
- 占位引文创建；
- 原文状态更新；
- 简易匹配检索。
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd
import re
import unicodedata


DEFAULT_DB_COLUMNS: List[str] = [
    "id",
    "uid",
    "entry_type",
    "title",
    "clean_title",
    "title_norm",
    "abstract_norm",
    "first_author",
    "year",
    "year_int",
    "is_placeholder",
    "source",
    "is_indexed",
    "是否有原文",
    "pdf_path",
]


@dataclass
class MatchCandidate:
    """文献匹配候选项。

    Args:
        uid: 文献唯一标识。
        score: 匹配得分（0~1）。
        title: 标题。
        first_author: 第一作者。
        year_int: 年份整数。
        row: 原始记录字典。
    """

    uid: str
    score: float
    title: str
    first_author: str
    year_int: int | None
    row: Dict[str, Any]


@dataclass
class ReferenceParseResult:
    """参考文献行文本解析结果。

    Args:
        reference_text: 原始参考文献行文本。
        first_author: 解析得到的第一作者。
        year_int: 解析得到的年份。
        title: 解析得到的标题原文。
        clean_title: 标题清洗结果。
    """

    reference_text: str
    first_author: str
    year_int: int | None
    title: str
    clean_title: str


def normalize_text_for_match(text: str) -> str:
    """将文本规范化为匹配友好的形式。

    Args:
        text: 原始文本。

    Returns:
        仅包含小写字母、数字、中文与单空格的文本。
    """

    raw = unicodedata.normalize("NFKD", str(text or ""))
    raw = "".join(ch for ch in raw if not unicodedata.category(ch).startswith("M"))
    raw = raw.lower()
    chars: List[str] = []
    for ch in raw:
        if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"):
            chars.append(ch)
        else:
            chars.append(" ")
    return " ".join("".join(chars).split())


def clean_title_text(title: str) -> str:
    """将标题转换为 clean_title。

    规则：
    - 空格与连字符统一替换为 `_`；
    - 仅保留字母、数字、中文与 `_`；
    - 合并重复 `_` 并移除首尾 `_`。

    Args:
        title: 原始标题。

    Returns:
        规范化后的 clean_title。
    """

    text = unicodedata.normalize("NFKD", str(title or ""))
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("M"))
    text = text.lower()
    text = re.sub(r"[\s\-–—]+", "_", text)
    text = re.sub(r"[^0-9a-z_\u4e00-\u9fff]", "", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def parse_year_int(year_raw: Any) -> int | None:
    """从年份原始值中提取年份整数。

    Args:
        year_raw: 原始年份字段。

    Returns:
        提取到的年份整数；若无法提取返回 None。
    """

    if year_raw is None:
        return None
    match = re.search(r"(19|20)\d{2}", str(year_raw))
    if not match:
        return None
    return int(match.group(0))


def extract_first_author(author_raw: Any) -> str:
    """从作者字段提取第一作者。

    Args:
        author_raw: 原始作者字段。

    Returns:
        第一作者文本（为空时返回空字符串）。
    """

    text = str(author_raw or "").strip()
    if not text:
        return ""
    parts = re.split(r"\s*(?:;|,|，|、|＆|/|\\|\||\sand\s)\s*", text)
    for part in parts:
        if part and part.strip():
            return part.strip()
    return ""


def parse_reference_text(reference_text: str) -> ReferenceParseResult:
    """从参考文献单行文本中提取作者、年份与标题。

    该解析为启发式策略，目标是支持“占位引文插入”流程；
    对复杂格式的参考文献并不保证百分百准确。

    Args:
        reference_text: 参考文献原始文本（通常来自论文参考文献列表的一行）。

    Returns:
        解析结果对象。
    """

    text = str(reference_text or "").strip()
    text = re.sub(r"^\s*(?:\[\d+\]|\(\d+\)|\d+[\).、])\s*", "", text)
    text = " ".join(text.split())

    year_match = re.search(r"(19|20)\d{2}", text)
    year_int = int(year_match.group(0)) if year_match else None

    if year_match:
        author_part = text[: year_match.start()].strip(" .,;:()[]")
        after_year = text[year_match.end() :].strip()
    else:
        author_part = re.split(r"\.", text, maxsplit=1)[0].strip(" .,;:()[]")
        after_year = text

    first_author = extract_first_author(author_part)

    title_candidate = ""
    quoted_match = re.search(r"[\"“](.+?)[\"”]", after_year)
    if quoted_match:
        title_candidate = quoted_match.group(1).strip()
    else:
        after_year = re.sub(r"^[\s\)\]\.,;:]+", "", after_year)
        pieces = re.split(r"\.\s+", after_year, maxsplit=1)
        title_candidate = pieces[0].strip() if pieces else ""

    if not title_candidate:
        fallback = text
        if year_match:
            fallback = text[year_match.end() :].strip(" .,;:()[]") or text
        title_candidate = fallback

    title_candidate = " ".join(title_candidate.split())
    clean_title = clean_title_text(title_candidate)
    return ReferenceParseResult(
        reference_text=text,
        first_author=first_author,
        year_int=year_int,
        title=title_candidate,
        clean_title=clean_title,
    )


def generate_uid(first_author: str | None, year_int: int | None, title_norm: str, prefix: str | None = None) -> str:
    """生成文献唯一标识 uid。

    Args:
        first_author: 第一作者。
        year_int: 年份。
        title_norm: 归一化标题。
        prefix: 可选前缀（如占位文献 `ph`）。

    Returns:
        稳定哈希形式的 uid。
    """

    author = normalize_text_for_match(first_author or "")
    year = "" if year_int is None else str(year_int)
    base = f"{author}|{year}|{normalize_text_for_match(title_norm)}"
    digest = sha1(base.encode("utf-8")).hexdigest()[:16]
    if prefix:
        return f"{prefix}-{digest}"
    return digest


def init_empty_table(columns: List[str] | None = None) -> pd.DataFrame:
    """初始化空文献数据库表。

    Args:
        columns: 自定义列名，未提供时使用默认列。

    Returns:
        空 DataFrame。
    """

    cols = columns or list(DEFAULT_DB_COLUMNS)
    return pd.DataFrame(columns=cols)


def ensure_id_column(table: pd.DataFrame) -> pd.DataFrame:
    """确保表包含连续 `id` 列。

    Args:
        table: 文献数据库表。

    Returns:
        处理后的 DataFrame。
    """

    result = table.copy()
    result = result.reset_index(drop=True)
    result["id"] = list(range(1, len(result) + 1))
    return result


def find_match(table: pd.DataFrame, first_author: str | None, year: int | None, title: str, top_n: int = 5) -> List[Dict[str, Any]]:
    """在文献库中查找候选匹配。

    Args:
        table: 文献数据库表。
        first_author: 待匹配第一作者。
        year: 待匹配年份。
        title: 待匹配标题。
        top_n: 返回候选上限。

    Returns:
        候选列表（按 score 降序）。
    """

    if table.empty:
        return []

    title_norm = normalize_text_for_match(title)
    author_norm = normalize_text_for_match(first_author or "")
    candidates: List[MatchCandidate] = []

    for _, row in table.iterrows():
        row_title = normalize_text_for_match(str(row.get("title_norm") or row.get("title") or ""))
        row_author = normalize_text_for_match(str(row.get("first_author") or ""))
        row_year = parse_year_int(row.get("year_int") if row.get("year_int") else row.get("year"))

        score = 0.0
        if row_title and row_title == title_norm:
            score += 0.7
        elif row_title and (title_norm in row_title or row_title in title_norm):
            score += 0.4

        if author_norm and row_author and author_norm == row_author:
            score += 0.2

        if year is not None and row_year is not None and int(year) == int(row_year):
            score += 0.1

        if score <= 0:
            continue

        candidates.append(
            MatchCandidate(
                uid=str(row.get("uid", "")),
                score=round(score, 4),
                title=str(row.get("title", "")),
                first_author=str(row.get("first_author", "")),
                year_int=row_year,
                row=dict(row),
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return [
        {
            "uid": c.uid,
            "score": c.score,
            "title": c.title,
            "first_author": c.first_author,
            "year_int": c.year_int,
            "row": c.row,
        }
        for c in candidates[:top_n]
    ]


def upsert_record(table: pd.DataFrame, bib_entry: Dict[str, Any], source: str = "imported", overwrite: bool = False) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """插入或更新文献记录。

    Args:
        table: 当前表。
        bib_entry: 待写入记录。
        source: 来源标签。
        overwrite: 命中时是否覆盖非空字段。

    Returns:
        (新表, 最终记录, 动作)；动作为 `inserted` 或 `updated`。
    """

    working = table.copy()
    uid = str(bib_entry.get("uid", "")).strip()
    if not uid:
        raise ValueError("upsert_record 需要提供 uid")

    entry = dict(bib_entry)
    entry["source"] = str(entry.get("source") or source)

    if "uid" not in working.columns:
        working["uid"] = ""

    matches = working.index[working["uid"].astype(str) == uid].tolist()
    if not matches:
        working = pd.concat([working, pd.DataFrame([entry])], ignore_index=True)
        working = ensure_id_column(working)
        return working, entry, "inserted"

    idx = matches[0]
    current = dict(working.loc[idx])
    merged = dict(current)
    for key, value in entry.items():
        if overwrite:
            merged[key] = value
        else:
            if key not in merged or merged[key] in (None, "", pd.NA):
                merged[key] = value
    for key, value in merged.items():
        working.at[idx, key] = value
    working = ensure_id_column(working)
    return working, merged, "updated"


def create_placeholder(table: pd.DataFrame, first_author: str, year: int | None, title: str, clean_title: str, source: str = "placeholder", extra: Dict[str, Any] | None = None) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """创建占位引文并写入文献库。

    Args:
        table: 当前表。
        first_author: 第一作者。
        year: 年份。
        title: 原始标题。
        clean_title: 干净标题。
        source: 来源标签。
        extra: 额外字段。

    Returns:
        (新表, 最终记录, 动作)。
    """

    year_val = year if isinstance(year, int) else parse_year_int(year)
    title_norm = normalize_text_for_match(title)
    uid = generate_uid(first_author, year_val, title_norm)
    entry: Dict[str, Any] = {
        "uid": uid,
        "entry_type": "placeholder",
        "title": title,
        "clean_title": clean_title,
        "title_norm": title_norm,
        "first_author": first_author,
        "year": "" if year_val is None else str(year_val),
        "year_int": year_val,
        "is_placeholder": 1,
        "source": source,
        "is_indexed": 0,
        "是否有原文": 0,
        "pdf_path": "",
    }
    if extra:
        entry.update(extra)
    return upsert_record(table=table, bib_entry=entry, source=source, overwrite=False)


def insert_placeholder_from_reference(
    table: pd.DataFrame,
    reference_text: str,
    source: str = "placeholder_from_reading",
    top_n: int = 5,
    extra: Dict[str, Any] | None = None,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """从参考文献行文本按需插入占位引文。

    流程：
    1. 解析参考文献文本获取第一作者、年份与标题；
    2. 在库中匹配是否已存在（占位或标准条目都参与匹配）；
    3. 若命中则不插入，返回 `exists`；
    4. 若未命中则插入占位条目，返回 `inserted` 或 `updated`。

    Args:
        table: 文献数据库表。
        reference_text: 参考文献单条文本。
        source: 写入来源标签。
        top_n: 匹配候选返回上限。
        extra: 插入时附加字段。

    Returns:
        (新表, 记录字典, 动作)。动作为 `exists`、`inserted` 或 `updated`。

    Raises:
        ValueError: 当参考文献文本为空或无法解析有效标题时抛出。
    """

    parsed = parse_reference_text(reference_text)
    if not parsed.reference_text:
        raise ValueError("reference_text 不能为空")
    if not parsed.title:
        raise ValueError("无法从 reference_text 中解析标题")

    matches = find_match(
        table=table,
        first_author=parsed.first_author,
        year=parsed.year_int,
        title=parsed.title,
        top_n=top_n,
    )
    if matches:
        return (
            table,
            {
                "action": "exists",
                "matched": matches[0],
                "parsed": {
                    "first_author": parsed.first_author,
                    "year_int": parsed.year_int,
                    "title": parsed.title,
                    "clean_title": parsed.clean_title,
                    "reference_text": parsed.reference_text,
                },
            },
            "exists",
        )

    merged_extra: Dict[str, Any] = {"reference_text": parsed.reference_text}
    if extra:
        merged_extra.update(extra)

    return create_placeholder(
        table=table,
        first_author=parsed.first_author,
        year=parsed.year_int,
        title=parsed.title,
        clean_title=parsed.clean_title,
        source=source,
        extra=merged_extra,
    )


def update_pdf_status(table: pd.DataFrame, uid: str, has_pdf: int, pdf_path: str = "") -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """更新文献原文状态。

    Args:
        table: 当前表。
        uid: 文献 uid。
        has_pdf: 是否有原文（0/1）。
        pdf_path: 原文路径。

    Returns:
        (新表, 更新后的记录)。
    """

    working = table.copy()
    if "uid" not in working.columns:
        raise ValueError("当前表不包含 uid 列")

    matches = working.index[working["uid"].astype(str) == str(uid)].tolist()
    if not matches:
        raise KeyError(f"未找到 uid={uid} 的记录")

    idx = matches[0]
    working.at[idx, "是否有原文"] = int(has_pdf)
    working.at[idx, "pdf_path"] = str(pdf_path or "")
    row = dict(working.loc[idx])
    return working, row
