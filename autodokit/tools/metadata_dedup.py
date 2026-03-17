"""表格/条目元数据去重工具模块。

本模块提供对“条目元数据 DataFrame/CSV”进行去重的可复用实现。

设计目标：
- 直接对上游导入/预处理得到的 CSV 表进行去重（不绑定任何特定领域或数据源）。
- 去重优先级：唯一标识（例如 DOI）> (title + authors + year) 归一化键。
- 当前版本只做去重保留一条，不做字段级合并（合并留作后续扩展）。

说明：
- 该模块可被任意事务复用调用。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, List

# pandas 作为可选依赖：仅在调用去重函数时需要。
try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore


# 常见中文姓氏（包含部分复姓）。
_COMMON_CHINESE_SURNAMES: set[str] = {
    "赵",
    "钱",
    "孙",
    "李",
    "周",
    "吴",
    "郑",
    "王",
    "冯",
    "陈",
    "褚",
    "卫",
    "蒋",
    "沈",
    "韩",
    "杨",
    "朱",
    "秦",
    "尤",
    "许",
    "何",
    "吕",
    "施",
    "张",
    "孔",
    "曹",
    "严",
    "华",
    "金",
    "魏",
    "陶",
    "姜",
    # 常见复姓
    "欧阳",
    "司马",
    "上官",
    "诸葛",
    "尉迟",
    "夏侯",
    "东方",
    "皇甫",
    "公孙",
    "令狐",
}


def _is_chinese(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def normalize_text(text: Any) -> str:
    """对标题/摘要等文本做轻量归一化。

    Args:
        text: 任意可转为字符串的对象。

    Returns:
        归一化后的字符串：小写、去标点、合并空白。
    """

    s = "" if text is None else str(text)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("M"))
    s = s.lower()

    out: List[str] = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat.startswith("P"):
            out.append(" ")
            continue
        if ch.isalnum() or _is_chinese(ch):
            out.append(ch)
            continue
        out.append(" ")

    return " ".join("".join(out).split())


def _normalize_doi(raw: Any) -> str:
    """归一化 DOI，去掉常见 URL 前缀并小写。

    Args:
        raw: 原始 DOI 字段。

    Returns:
        归一化 DOI；缺失返回空串。
    """

    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    if s.lower() in {"nan", "none", "null"}:
        return ""
    s = s.replace("https://doi.org/", "")
    s = s.replace("http://doi.org/", "")
    s = s.replace("doi:", "")
    return s.lower().strip()


def _extract_year4(value: Any) -> str:
    if value is None:
        return ""
    m = re.search(r"(\d{4})", str(value))
    return m.group(1) if m else ""


def _strip_accents(text: str) -> str:
    nkfd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nkfd if not unicodedata.combining(ch))


def _is_cjk_text(s: str) -> bool:
    return any(_is_chinese(ch) for ch in (s or ""))


def split_authors(raw: Any) -> List[str]:
    """拆分作者字段为作者列表。

    关键点：不要按逗号拆分 "Last, First"。

    Args:
        raw: 原始作者字段。

    Returns:
        作者字符串列表。
    """

    if raw is None:
        return []
    s = str(raw).strip()
    if not s:
        return []

    if re.search(r"\sand\s", s, flags=re.IGNORECASE):
        parts = re.split(r"\s+and\s+", s, flags=re.IGNORECASE)
        return [p.strip() for p in parts if p and p.strip()]

    if re.search(r"[;；、/\\|]", s):
        parts = re.split(r"\s*(?:;|；|、|/|\\\\|\|)\s*", s)
        return [p.strip() for p in parts if p and p.strip()]

    if "," in s:
        # 逗号数量很多时更像作者列表，否则更像 "Last, First"
        if s.count(",") >= 2:
            parts = [p.strip() for p in s.split(",")]
            return [p for p in parts if p]
        return [s]

    return [s]


def _normalize_latin_surname(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""

    # 两词形式认为是 First Last
    if "," not in s:
        tokens = [t for t in s.split() if t]
        if len(tokens) == 2 and all(re.fullmatch(r"[A-Za-z\-\.]+", t) for t in tokens):
            surname = tokens[1]
            surname = surname.replace(".", "")
            surname = _strip_accents(surname)
            surname = re.sub(r"[^A-Za-z\-]", "", surname)
            return surname.lower()

    s = s.replace(".", "")
    if "," in s:
        surname = s.split(",", 1)[0].strip()
    else:
        tokens = [t for t in s.split() if t]
        surname = tokens[-1] if tokens else ""

    surname = _strip_accents(surname)
    surname = re.sub(r"[^A-Za-z\-]", "", surname)
    return surname.lower()


def _normalize_chinese_surname(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""

    parts = re.split(r"[,，、;；]", s)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) >= 2:
        for p in parts:
            if p in _COMMON_CHINESE_SURNAMES:
                return p
            if len(p) >= 2 and p[:2] in _COMMON_CHINESE_SURNAMES:
                return p[:2]
            if p and p[0] in _COMMON_CHINESE_SURNAMES:
                return p[0]
        return sorted(parts, key=len)[0]

    if len(s) >= 2 and s[:2] in _COMMON_CHINESE_SURNAMES:
        return s[:2]
    return s[0]


def normalize_authors_to_surnames(authors_field: Any) -> str:
    """将作者字段归一化为“姓氏串”。

    Args:
        authors_field: 原始作者字段。

    Returns:
        姓氏串（逗号分隔，尽量保持出现顺序并去重）。
    """

    if authors_field is None:
        return ""

    raw_authors = split_authors(authors_field)
    processed: List[str] = []

    for raw in raw_authors:
        raw = raw.strip()
        if not raw:
            continue
        if _is_cjk_text(raw):
            surname = _normalize_chinese_surname(raw)
        else:
            surname = _normalize_latin_surname(raw)
        if surname:
            processed.append(surname)

    seen: set[str] = set()
    uniq: List[str] = []
    for s in processed:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return ",".join(uniq)


def dedup_metadata_df(df):
    """对条目元数据 DataFrame 进行去重。

    Args:
        df: 输入 DataFrame（需要 pandas.DataFrame）。

    Returns:
        去重后的 DataFrame。

    Raises:
        RuntimeError: 未安装 pandas。
        ValueError: df 不是 DataFrame 时抛出。
    """

    if pd is None:
        raise RuntimeError("需要安装 pandas 才能使用 metadata_dedup。建议：uv add pandas 或 pip install pandas")

    if not isinstance(df, pd.DataFrame):
        raise ValueError("df 必须是 pandas.DataFrame")
    if df.empty:
        return df.copy()

    work = df.copy()

    doi_col = "doi" if "doi" in work.columns else ("DOI" if "DOI" in work.columns else None)
    if doi_col is None:
        work["_doi_norm"] = ""
    else:
        work["_doi_norm"] = work[doi_col].fillna("").map(_normalize_doi).fillna("")

    title_col = "title" if "title" in work.columns else ("Title" if "Title" in work.columns else None)
    if "title_norm" in work.columns:
        work["_title_norm2"] = work["title_norm"].fillna("").map(normalize_text)
    elif title_col is None:
        work["_title_norm2"] = ""
    else:
        work["_title_norm2"] = work[title_col].fillna("").map(normalize_text)

    author_col = "author" if "author" in work.columns else ("authors" if "authors" in work.columns else None)
    if author_col is None:
        work["_authors_norm"] = ""
    else:
        work["_authors_norm"] = work[author_col].fillna("").map(normalize_authors_to_surnames)

    year_col = "year" if "year" in work.columns else ("YEAR" if "YEAR" in work.columns else None)
    if year_col is None:
        work["_year4"] = ""
    else:
        work["_year4"] = work[year_col].fillna("").map(_extract_year4)

    work["_norm_key"] = (
        "t:" + work["_title_norm2"].astype(str)
        + "|a:" + work["_authors_norm"].astype(str)
        + "|y:" + work["_year4"].astype(str)
    )

    non_null_score = work.replace({"": pd.NA}).notna().sum(axis=1)
    work["_non_null_score"] = non_null_score

    with_doi = work[work["_doi_norm"] != ""].copy()
    without_doi = work[work["_doi_norm"] == ""].copy()

    if not with_doi.empty:
        with_doi = with_doi.sort_values(by=["_doi_norm", "_non_null_score"], ascending=[True, False], kind="mergesort")
        with_doi = with_doi.drop_duplicates(subset=["_doi_norm"], keep="first")

    if not without_doi.empty:
        usable = without_doi[without_doi["_norm_key"] != "t:|a:|y:"].copy()
        unusable = without_doi[without_doi["_norm_key"] == "t:|a:|y:"].copy()

        if not usable.empty:
            usable = usable.sort_values(by=["_norm_key", "_non_null_score"], ascending=[True, False], kind="mergesort")
            usable = usable.drop_duplicates(subset=["_norm_key"], keep="first")
        without_doi = pd.concat([usable, unusable], axis=0)

    out = pd.concat([with_doi, without_doi], axis=0)
    out = out.drop(
        columns=[
            "_doi_norm",
            "_title_norm2",
            "_authors_norm",
            "_year4",
            "_norm_key",
            "_non_null_score",
        ],
        errors="ignore",
    )

    return out.sort_index()

