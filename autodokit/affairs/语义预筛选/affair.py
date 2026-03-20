"""基于主题的文献语义预筛选事务（面向社会科学研究者的通俗说明）。

本事务的目标（用一句话说明）：
- 从已有的题录/元数据表中，快速筛选出“值得详细阅读”的候选文献，减少后续精读与模型调用的工作量。

为什么需要它（学术角度，通俗）：
- 在做综述或选题初期，你可能有数百条题录（题名/摘要/关键词）。这一步相当于人工阅读书名与摘要，先把看起来相关的 50~100 篇放进“要读”名单，后续才花时间精读。

本事务做什么（技术摘要，便于理解）：
- 读取由 `导入和预处理文献元数据` 产生的 `文献数据表.csv`。
- 根据配置的关键词规则、是否有本地 PDF、年份范围等做快速筛选。
- 可选启用一个“轻量语义”占位打分（基于词覆盖率），后续可替换为 embedding 相似度。

输入（必需）：
- `input_table_csv`：由导入事务生成的主表 CSV（含 title, abstract, keywords, pdf_path, year 等字段）。

输出（必需产物）：
- `review_candidates.csv`：候选清单（含 uid、title、score、reason、pdf_path）。
- `review_excluded.csv`：被排除的记录（含原因）。
- `prescreen_report.json`：运行统计与配置回显，便于审计。

在学术流程中的位置（示例）：
- 场景 A（选题）：你有 800 条题录，先运行预筛选把候选降到 80 条，再进入 PDF 抽取与精读；这样节省大量人工/API 成本。
- 场景 B（文献回顾）：老师给你一个主题说明（topic.txt），把该文本作为 `semantic_queries`，快速找到与主题最接近的文献。

何时用（简短建议）：
- 如果你的文献条目少（<20），可以跳过此步，直接做 PDF 提取与人工精读；
- 如果条目多（几十到上千），强烈建议先运行本事务以削减规模。

运行示例（项目 `workflow_010`）：
- 在 `workflows/workflow_010/workflow.json` 已配置时，直接运行：

  py main.py

- 单独运行（示例）：

  py -c "from pathlib import Path; from autodo-kit.affairs.语义预筛选 import execute; execute(Path('workflows/workflow_010/workflow.json'))"

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表（候选 CSV、排除 CSV、报告 JSON）。

Examples:
    >>> from pathlib import Path
    >>> from autodokit.affairs.语义预筛选 import execute
    >>> execute(Path('workflows/workflow_010/workflow.json'))
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from autodokit.tools import load_json_or_py


@dataclass
class PrescreenConfig:
    """预筛选配置。

    Attributes:
        input_table_csv: 文献主表 CSV 路径（由“导入和预处理文献元数据”生成）。
        output_dir: 输出目录。
        include_if_has_pdf: 是否仅保留有 PDF 的文献。
        include_keywords_any: 旧版规则：只要命中任意关键词则视为“相关”。
        exclude_keywords_any: 旧版规则：命中任意排除词则视为“排除”。
        include_domains: 新版规则：必需命中的“研究领域集合”，采用“域内 OR、域间 AND”。
            结构示例：{"研究领域A": ["kw1", "kw2"], "研究领域B": ["kw3"]}
        exclude_domain_keywords_any: 新版规则：排除域（研究领域C）关键词组；任意命中即剔除。
            该字段用于表达“(A ∩ B) 且不包含 C”。
        year_range: 年份区间 [start, end]（闭区间）；为 None 则不限制。
        top_k: 保留候选的最大数量；为 None 则不裁剪。
        top_ratio: 保留候选的比例上限（0, 1]；基于排序后的候选集裁剪；为 None 则不按比例裁剪。
        semantic_enable: 是否启用轻量“语义”打分（占位）。
        semantic_queries: 主题/示例文本（多个 query）；用于计算轻量相似度。
        output_candidates_name: 候选清单输出文件名（仅文件名，默认 review_candidates.csv）。
        output_excluded_name: 排除清单输出文件名（仅文件名，默认 review_excluded.csv）。
        output_report_name: 统计报告输出文件名（仅文件名，默认 prescreen_report.json）。
    """

    input_table_csv: str
    output_dir: str
    include_if_has_pdf: bool = True
    include_keywords_any: List[str] | None = None
    exclude_keywords_any: List[str] | None = None
    include_domains: Dict[str, List[str]] | None = None
    exclude_domain_keywords_any: List[str] | None = None
    year_range: List[int] | None = None
    top_k: int | None = 100
    top_ratio: float | None = None
    semantic_enable: bool = False
    semantic_queries: List[str] | None = None
    output_candidates_name: str = "review_candidates.csv"
    output_excluded_name: str = "review_excluded.csv"
    output_report_name: str = "prescreen_report.json"


def _apply_candidate_limit(cand_df: pd.DataFrame, *, top_k: int | None, top_ratio: float | None) -> pd.DataFrame:
    """按比例和数量上限裁剪候选结果。

    规则：
    - 若设置 top_ratio，则先根据当前候选总量计算比例上限；
    - 若同时设置 top_k，则最终取两者更严格的上限；
    - 至少保留 1 条（前提是候选非空）。

    Args:
        cand_df: 已排序的候选 DataFrame。
        top_k: 数量上限。
        top_ratio: 比例上限，要求 0 < top_ratio <= 1。

    Returns:
        裁剪后的 DataFrame。
    """

    if cand_df.empty:
        return cand_df

    limit: int | None = None

    if top_ratio is not None:
        ratio = float(top_ratio)
        if ratio <= 0 or ratio > 1:
            raise ValueError(f"top_ratio 必须位于 (0, 1]，当前值={top_ratio!r}")
        limit = max(1, int(np.ceil(len(cand_df) * ratio)))

    if top_k is not None:
        k = int(top_k)
        limit = k if limit is None else min(limit, k)

    if limit is None or len(cand_df) <= limit:
        return cand_df
    return cand_df.head(limit)


def _resolve_output_filename(raw_name: Any, *, default_name: str, field_name: str) -> str:
    """解析输出文件名（仅允许文件名本身）。"""

    name = str(raw_name or "").strip()
    if not name:
        return default_name

    p = Path(name)
    if p.name != name:
        raise ValueError(f"{field_name} 仅支持文件名，不支持路径：{name!r}")
    return name


def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x)


def _contains_any(text: str, keywords: List[str]) -> bool:
    for k in keywords:
        if k and k in text:
            return True
    return False


def _clean_keywords_any(xs: List[Any] | None) -> List[str]:
    """清洗“任意命中”关键词列表。

    Args:
        xs: 原始配置中的列表，可能包含 None/空串/非字符串。

    Returns:
        清洗后的关键词列表（均为 str，去空）。
    """

    return [str(x) for x in (xs or []) if str(x).strip()]


def _clean_domains(domains: Mapping[str, Any] | None) -> Dict[str, List[str]]:
    """清洗研究领域 domains 配置。

    Args:
        domains: 配置中的 domains，值可能是 list/tuple/str/None。

    Returns:
        规范化后的 domains：{domain_name: [kw1, kw2, ...]}。

    Raises:
        ValueError: domains 不是字典结构时抛出。
    """

    if not domains:
        return {}
    if not isinstance(domains, Mapping):
        raise ValueError(f"include_domains 必须为对象/字典结构，当前类型={type(domains)}")

    out: Dict[str, List[str]] = {}
    for k, v in domains.items():
        name = str(k).strip()
        if not name:
            continue
        if v is None:
            kws: List[str] = []
        elif isinstance(v, (list, tuple)):
            kws = [str(x).strip() for x in v if str(x).strip()]
        else:
            # 允许单个字符串，作为一个关键词
            s = str(v).strip()
            kws = [s] if s else []
        out[name] = kws
    return out


def _build_text_blob(df: pd.DataFrame, *, text_cols: List[str]) -> pd.Series:
    """构造用于匹配的合并文本列。

    关键逻辑说明：
    - 在向量化筛选中，必须把多列文本合并为一个预计算列，避免在每个域循环中做重复拼接。
    - 统一 lower() 便于中英文混杂时的大小写兼容（中文不受影响）。

    Args:
        df: 文献主表。
        text_cols: 参与匹配的列名。

    Returns:
        合并后的文本列（已 lower）。
    """

    cols = [c for c in text_cols if c in df.columns]
    if not cols:
        # 兜底：使用所有 object 列
        cols = [c for c, t in df.dtypes.items() if t == object]
    return df[cols].fillna("").agg("\n".join, axis=1).astype(str).str.lower()


def prescreen_by_domains_with_exclude(
    df: pd.DataFrame,
    *,
    include_domains: Dict[str, List[str]],
    exclude_domain_keywords_any: List[str] | None,
    text_cols: List[str] | None = None,
    max_domain_keywords: int = 40,
) -> pd.DataFrame:
    """基于 domains 的高性能预筛选（域内 OR + 域间 AND + 排除域）。

    表达式目标：
    - 必需命中：研究领域A ∩ 研究领域B（每个领域至少命中一个关键词）。
    - 排除命中：研究领域C（命中任意 C 关键词即剔除）。

    Args:
        df: 文献主表 DataFrame。
        include_domains: 必需命中的研究领域集合。
        exclude_domain_keywords_any: 排除域关键词（研究领域C），任意命中即剔除。
        text_cols: 参与匹配的列名，默认 ["title", "abstract", "keywords"]。
        max_domain_keywords: 每个域最多使用前 N 个关键词以控制正则长度。

    Returns:
        返回 df 的子集，并新增两列：
        - matched_domains: 命中的领域名（逗号分隔）。
        - include_domain_hit_count: 命中的必需域数量。

    Raises:
        ValueError: include_domains 为空时抛出（避免误用）。
    """

    if text_cols is None:
        text_cols = ["title", "abstract", "keywords"]

    include_domains = include_domains or {}
    if not include_domains:
        raise ValueError("include_domains 为空：如果想用旧版全局 OR，请配置 include_keywords_any")

    text_blob = _build_text_blob(df, text_cols=text_cols)
    n = len(df)

    # 为每个域构造一次向量化 contains（域内 OR）
    domain_names: List[str] = []
    domain_masks: List[np.ndarray] = []

    for domain_name, kws in include_domains.items():
        domain_names.append(domain_name)
        kws_clean = [str(x).strip().lower() for x in (kws or []) if str(x).strip()]
        kws_clean = kws_clean[: max(1, int(max_domain_keywords))]

        if not kws_clean:
            domain_masks.append(np.zeros(n, dtype=bool))
            continue

        # 关键逻辑说明：re.escape 防止括号、点号等字符被当作正则元字符
        pattern = "|".join(re.escape(k) for k in kws_clean)
        mask = text_blob.str.contains(pattern, regex=True, na=False).to_numpy(dtype=bool)
        domain_masks.append(mask)

    # 域间 AND：每个必需域都必须命中
    required_mask = np.logical_and.reduce(domain_masks) if domain_masks else np.ones(n, dtype=bool)

    # 排除域：任意命中即剔除
    exclude_mask = np.zeros(n, dtype=bool)
    excl = [str(x).strip().lower() for x in (exclude_domain_keywords_any or []) if str(x).strip()]
    if excl:
        excl_pattern = "|".join(re.escape(k) for k in excl)
        exclude_mask = text_blob.str.contains(excl_pattern, regex=True, na=False).to_numpy(dtype=bool)

    final_mask = required_mask & (~exclude_mask)

    # 生成命中领域与命中数量（仅对保留行计算字符串，避免全量 python 循环）
    kept_idx = np.flatnonzero(final_mask)
    stacked = np.stack(domain_masks, axis=1) if domain_masks else np.zeros((n, 0), dtype=bool)
    hit_counts = stacked.sum(axis=1) if stacked.size else np.ones(n, dtype=int)

    matched_domains_out: List[str] = []
    for i in kept_idx:
        hits = [domain_names[j] for j in range(len(domain_names)) if domain_masks[j][i]]
        matched_domains_out.append(",".join(hits))

    out = df.loc[final_mask].copy()
    out["matched_domains"] = matched_domains_out
    out["include_domain_hit_count"] = hit_counts[final_mask].astype(int)
    return out


def _light_semantic_score(text: str, queries: List[str]) -> float:
    """轻量语义打分（占位）。

    Args:
        text: 文献摘要/标题拼接文本。
        queries: 主题 query 列表。

    Returns:
        0~1 的分数，越高表示越可能相关。
    """

    q = " ".join([_safe_str(s) for s in queries]).strip()
    if not q:
        return 0.0

    # 关键逻辑说明：用词覆盖率做粗匹配，牺牲准确性换取零依赖与可立即落地。
    tokens = [t.strip() for t in q.replace("\n", " ").split() if t.strip()]
    if not tokens:
        return 0.0

    hit = 0
    for t in tokens:
        if t in text:
            hit += 1
    return hit / max(len(tokens), 1)


def _build_reason(row: pd.Series, *, include_keywords_any: List[str] | None) -> str:
    if not include_keywords_any:
        return "规则通过"
    text = _safe_str(row.get("title")) + " " + _safe_str(row.get("abstract")) + " " + _safe_str(row.get("keywords"))
    hits = [k for k in include_keywords_any if k and k in text]
    if hits:
        return "命中关键词: " + ",".join(hits[:10])
    return "规则通过"


def _load_table(table_csv: Path) -> pd.DataFrame:
    """读取文献主表。"""

    if not table_csv.exists():
        raise FileNotFoundError(f"找不到文献主表：{table_csv}")
    df = pd.read_csv(table_csv, encoding="utf-8-sig")
    if "uid" in df.columns:
        df = df.set_index("uid", drop=False)
    return df


def _load_keyword_set_domains(keyword_set_json: Path) -> Dict[str, List[str]]:
    """从 keyword_set.json 读取领域到关键词列表的映射。

    兼容结构（按优先级）：
    1) 新版：{"schema_version": 1, "domains": {"领域": {"keywords": [...]}}}
    2) 旧版：{"domains": [{"domain_name": "领域", "keywords": [...]}]}
    3) 兼容字段：{"domains_legacy": [{"domain_name": "领域", "keywords": [...]}]}

    Args:
        keyword_set_json: keyword_set.json 路径。

    Returns:
        {domain_name: [kw1, kw2, ...]}。

    Raises:
        FileNotFoundError: keyword_set.json 不存在。
        ValueError: 文件结构无法解析。
    """

    if not keyword_set_json.exists():
        raise FileNotFoundError(f"找不到 keyword_set.json：{keyword_set_json}")

    data = json.loads(keyword_set_json.read_text(encoding="utf-8"))

    # 1) 新版结构：domains 为 dict
    domains_obj = data.get("domains")
    if isinstance(domains_obj, dict):
        out: Dict[str, List[str]] = {}
        for name, payload in domains_obj.items():
            domain_name = str(name).strip()
            if not domain_name:
                continue
            kws = None
            if isinstance(payload, dict):
                kws = payload.get("keywords")
            if isinstance(kws, list):
                out[domain_name] = [str(x).strip() for x in kws if str(x).strip()]
            else:
                out[domain_name] = []
        return out

    def _load_from_list(domains_list: Any) -> Optional[Dict[str, List[str]]]:
        if not isinstance(domains_list, list):
            return None
        out2: Dict[str, List[str]] = {}
        for item in domains_list:
            if not isinstance(item, dict):
                continue
            domain_name = str(item.get("domain_name") or "").strip()
            if not domain_name:
                continue
            kws = item.get("keywords")
            if isinstance(kws, list):
                out2[domain_name] = [str(x).strip() for x in kws if str(x).strip()]
            else:
                out2[domain_name] = []
        return out2

    # 2) 旧版结构：domains 为 list
    out_old = _load_from_list(domains_obj)
    if out_old is not None:
        return out_old

    # 3) 兼容字段：domains_legacy
    out_legacy = _load_from_list(data.get("domains_legacy"))
    if out_legacy is not None:
        return out_legacy

    raise ValueError(f"keyword_set.json 的 domains 字段结构不受支持：{keyword_set_json}")


def _materialize_domain_filters_from_keyword_set(
    *,
    config_path: Path,
    include_domains: Any,
    exclude_domains: Any,
    keyword_set_json: Any,
) -> tuple[Dict[str, List[str]] | None, List[str] | None]:
    """将 include_domains/exclude_domains（域名列表）转换为可执行的关键词过滤结构。

    约定：
    - 若 include_domains 是 dict，则认为调用方已显式提供关键词列表，直接使用（兼容旧写法）。
    - 若 include_domains 是 list[str]，则从 keyword_set.json 中挑选对应域的 keywords。
    - exclude_domains 仅支持 list[str]：会把这些域的 keywords 合并成 exclude_domain_keywords_any。

    Args:
        config_path: 当前 workflow.json 路径。
        include_domains: workflow.json 配置中的 include_domains。
        exclude_domains: workflow.json 配置中的 exclude_domains。
        keyword_set_json: workflow.json 配置中的 keyword_set_json（可选）。

    Returns:
        (include_domains_dict_or_none, exclude_keywords_any_or_none)

    Raises:
        FileNotFoundError: 需要 keyword_set.json 但找不到。
        ValueError: include_domains/exclude_domains 类型不合法或域名找不到。
    """

    # 旧写法：直接给 dict
    if isinstance(include_domains, Mapping):
        include_dict = _clean_domains(include_domains)
        excl_list = _clean_keywords_any(exclude_domains) if exclude_domains is not None else None
        return include_dict, (excl_list or None)

    include_names = _clean_keywords_any(include_domains) if include_domains is not None else []
    exclude_names = _clean_keywords_any(exclude_domains) if exclude_domains is not None else []

    if not include_names and not exclude_names:
        return None, None

    # 推断/读取 keyword_set.json
    keyword_set_path: Path
    if isinstance(keyword_set_json, str) and keyword_set_json.strip():
        keyword_set_path = Path(keyword_set_json)
    else:
        raise ValueError(
            "缺少 keyword_set_json：本事务不负责推断默认路径。"
            "请在调度层/上游预处理阶段将其注入为绝对路径。"
        )

    domains_map = _load_keyword_set_domains(keyword_set_path)

    include_dict2: Dict[str, List[str]] = {}
    missing: List[str] = []
    for name in include_names:
        if name not in domains_map:
            missing.append(name)
        else:
            include_dict2[name] = domains_map.get(name) or []

    if missing:
        raise ValueError(
            "include_domains 中存在未在 keyword_set.json 找到的领域：" + ", ".join(missing)
        )

    exclude_keywords: List[str] = []
    missing_excl: List[str] = []
    for name in exclude_names:
        if name not in domains_map:
            missing_excl.append(name)
            continue
        exclude_keywords.extend(domains_map.get(name) or [])

    if missing_excl:
        raise ValueError(
            "exclude_domains 中存在未在 keyword_set.json 找到的领域：" + ", ".join(missing_excl)
        )

    return (include_dict2 or None), (exclude_keywords or None)


def execute(config_path: Path) -> List[Path]:
    """调度器入口：执行语义预筛选并写出候选清单。"""

    raw_cfg = load_json_or_py(config_path)

    # 兼容：既支持直接传入“事务 config”，也支持传入 workflow.json 容器。
    affair_cfg: Dict[str, Any]
    if isinstance(raw_cfg, dict) and "affairs" in raw_cfg:
        affairs = raw_cfg.get("affairs") or {}
        if not isinstance(affairs, dict) or not affairs:
            raise ValueError("workflow.json 缺少 affairs 配置")

        if "语义预筛选" in affairs and isinstance(affairs.get("语义预筛选"), dict):
            node = affairs.get("语义预筛选") or {}
        elif len(affairs) == 1:
            node = next(iter(affairs.values()))
        else:
            raise ValueError("workflow.json 中包含多个 affairs，无法推断语义预筛选节点")

        if not isinstance(node, dict):
            raise ValueError("workflow.json 的 affairs 节点格式不正确")
        affair_cfg = dict(node.get("config") or {})
    else:
        affair_cfg = dict(raw_cfg)

    # 兼容旧字段：input_keywords 指向目录时，自动转为 keyword_set_json。
    # 这样 demos/tests 不需要依赖 main.py 的上游注入逻辑也能运行。
    if not affair_cfg.get("keyword_set_json"):
        input_keywords = affair_cfg.get("input_keywords")
        if isinstance(input_keywords, str) and input_keywords.strip():
            candidate = (Path(input_keywords.strip()) / "keyword_set.json")
            if candidate.exists():
                affair_cfg["keyword_set_json"] = str(candidate.resolve())

    ps_cfg = PrescreenConfig(
        input_table_csv=str(affair_cfg.get("input_table_csv") or ""),
        output_dir=str(affair_cfg.get("output_dir") or ""),
        include_if_has_pdf=bool(affair_cfg.get("include_if_has_pdf", True)),
        include_keywords_any=affair_cfg.get("include_keywords_any"),
        exclude_keywords_any=affair_cfg.get("exclude_keywords_any"),
        include_domains=affair_cfg.get("include_domains"),
        exclude_domain_keywords_any=affair_cfg.get("exclude_domain_keywords_any"),
        year_range=affair_cfg.get("year_range"),
        top_k=affair_cfg.get("top_k"),
        top_ratio=affair_cfg.get("top_ratio"),
        semantic_enable=bool(affair_cfg.get("semantic_enable", False)),
        semantic_queries=affair_cfg.get("semantic_queries"),
        output_candidates_name=str(affair_cfg.get("output_candidates_name") or "review_candidates.csv"),
        output_excluded_name=str(affair_cfg.get("output_excluded_name") or "review_excluded.csv"),
        output_report_name=str(affair_cfg.get("output_report_name") or "prescreen_report.json"),
    )

    output_candidates_name = _resolve_output_filename(
        ps_cfg.output_candidates_name,
        default_name="review_candidates.csv",
        field_name="output_candidates_name",
    )
    output_excluded_name = _resolve_output_filename(
        ps_cfg.output_excluded_name,
        default_name="review_excluded.csv",
        field_name="output_excluded_name",
    )
    output_report_name = _resolve_output_filename(
        ps_cfg.output_report_name,
        default_name="prescreen_report.json",
        field_name="output_report_name",
    )

    input_table_csv = Path(ps_cfg.input_table_csv)
    if not input_table_csv.is_absolute():
        raise ValueError(
            "input_table_csv 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={ps_cfg.input_table_csv!r}"
        )

    out_dir = Path(ps_cfg.output_dir)
    if not out_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={ps_cfg.output_dir!r}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    df = _load_table(input_table_csv)

    include_keywords_any = _clean_keywords_any(ps_cfg.include_keywords_any)
    exclude_keywords_any = _clean_keywords_any(ps_cfg.exclude_keywords_any)
    queries = _clean_keywords_any(ps_cfg.semantic_queries)

    # 新增：支持 include_domains/exclude_domains 为“域名列表”，自动从 keyword_set.json 注入关键词
    include_domains_materialized, exclude_from_domains = _materialize_domain_filters_from_keyword_set(
        config_path=config_path,
        include_domains=affair_cfg.get("include_domains"),
        exclude_domains=affair_cfg.get("exclude_domains"),
        keyword_set_json=affair_cfg.get("keyword_set_json"),
    )

    include_domains = _clean_domains(include_domains_materialized or ps_cfg.include_domains)

    # exclude_domain_keywords_any 的优先级：显式配置 > exclude_domains 自动转换
    exclude_domain_keywords_any = _clean_keywords_any(ps_cfg.exclude_domain_keywords_any)
    if not exclude_domain_keywords_any and exclude_from_domains:
        exclude_domain_keywords_any = _clean_keywords_any(exclude_from_domains)

    # 先做结构化过滤（年份/PDF），再做文本规则过滤，避免对明显不合格数据做正则扫描
    base_mask = np.ones(len(df), dtype=bool)

    if ps_cfg.year_range and "year" in df.columns:
        try:
            start = int(ps_cfg.year_range[0])
            end = int(ps_cfg.year_range[1])
        except Exception:
            start, end = 0, 10**9
        year_num = pd.to_numeric(df["year"], errors="coerce")
        year_ok = year_num.isna() | ((year_num >= start) & (year_num <= end))
        base_mask &= year_ok.to_numpy(dtype=bool)

    if ps_cfg.include_if_has_pdf and "has_pdf" in df.columns:
        has_pdf_raw = df["has_pdf"]
        has_pdf_bool = has_pdf_raw
        if has_pdf_raw.dtype == object:
            has_pdf_bool = has_pdf_raw.fillna("").astype(str).str.strip().str.lower().isin(["1", "true", "yes", "y"])
        base_mask &= has_pdf_bool.fillna(False).to_numpy(dtype=bool)

    df_base = df.loc[base_mask].copy()

    # 文本筛选：优先使用新版 include_domains（域间 AND），否则回退到旧版 include_keywords_any（全局 OR）
    excluded_rows: List[Dict[str, Any]] = []

    if include_domains:
        kept_df = prescreen_by_domains_with_exclude(
            df_base,
            include_domains=include_domains,
            exclude_domain_keywords_any=exclude_domain_keywords_any,
        )

        # 旧字段 exclude_keywords_any 仍然支持：作为“额外排除词”叠加
        if exclude_keywords_any:
            text_blob = _build_text_blob(kept_df, text_cols=["title", "abstract", "keywords"])
            excl_pattern = "|".join(re.escape(str(x).strip().lower()) for x in exclude_keywords_any if str(x).strip())
            if excl_pattern:
                extra_excl = text_blob.str.contains(excl_pattern, regex=True, na=False)
                to_exclude = kept_df.loc[extra_excl]
                for _, r in to_exclude.iterrows():
                    excluded_rows.append({"uid": r.get("uid"), "title": r.get("title"), "exclude_reason": "命中额外排除词"})
                kept_df = kept_df.loc[~extra_excl].copy()

        # 用 include_domain_hit_count 做基础分，保证不启用 semantic 时也能排序稳定
        kept_df["score"] = kept_df["include_domain_hit_count"].astype(float) / max(len(include_domains), 1)
        kept_df["reason"] = "命中领域: " + kept_df["matched_domains"].astype(str)

        if ps_cfg.semantic_enable:
            text_blob = _build_text_blob(kept_df, text_cols=["title", "abstract", "keywords"])
            kept_df["score"] = [
                float(_light_semantic_score(t, queries)) for t in text_blob.tolist()
            ]

        cand_df = kept_df.copy()

        # 组装未命中/被排除列表（针对 df_base 中未进入 kept_df 的行给出原因，便于审计）
        kept_uids = set(cand_df["uid"].astype(str).tolist()) if "uid" in cand_df.columns else set()
        for _, row in df_base.iterrows():
            uid = row.get("uid")
            if str(uid) in kept_uids:
                continue
            excluded_rows.append({"uid": uid, "title": row.get("title"), "exclude_reason": "未满足领域交集或命中排除域"})

        # 加上因 base_mask 被过滤掉的原因
        filtered_out = df.loc[~base_mask]
        for _, row in filtered_out.iterrows():
            reason = "规则过滤"
            if ps_cfg.include_if_has_pdf:
                has_pdf = row.get("has_pdf")
                if isinstance(has_pdf, str):
                    has_pdf = has_pdf.strip().lower() in {"1", "true", "yes", "y"}
                if has_pdf is False:
                    reason = "无本地 PDF"
            if ps_cfg.year_range and row.get("year") is not None:
                reason = "年份不在范围内"
            excluded_rows.append({"uid": row.get("uid"), "title": row.get("title"), "exclude_reason": reason})

    else:
        # 旧实现回退：逐行扫描（保持现有行为不变）
        candidates: List[Dict[str, Any]] = []
        excluded: List[Dict[str, Any]] = []

        for _uid, row in df.iterrows():
            uid_raw = row.get("uid")
            if pd.notna(uid_raw) and str(uid_raw).strip():
                uid = str(uid_raw).strip()
            else:
                uid = str(_uid).strip()

            year_val = row.get("year")
            try:
                year = int(year_val) if pd.notna(year_val) and str(year_val).strip() else None
            except Exception:
                year = None

            if ps_cfg.year_range and year is not None:
                try:
                    start = int(ps_cfg.year_range[0])
                    end = int(ps_cfg.year_range[1])
                except Exception:
                    start, end = 0, 10**9
                if year < start or year > end:
                    excluded.append({"uid": uid, "title": row.get("title"), "exclude_reason": "年份不在范围内"})
                    continue

            if ps_cfg.include_if_has_pdf:
                has_pdf = row.get("has_pdf")
                if isinstance(has_pdf, str):
                    has_pdf = has_pdf.strip().lower() in {"1", "true", "yes", "y"}
                if has_pdf is False:
                    excluded.append({"uid": uid, "title": row.get("title"), "exclude_reason": "无本地 PDF"})
                    continue

            text = (
                _safe_str(row.get("title"))
                + "\n"
                + _safe_str(row.get("abstract"))
                + "\n"
                + _safe_str(row.get("keywords"))
            )

            if exclude_keywords_any and _contains_any(text, exclude_keywords_any):
                excluded.append({"uid": uid, "title": row.get("title"), "exclude_reason": "命中排除词"})
                continue

            if include_keywords_any and not _contains_any(text, include_keywords_any):
                excluded.append({"uid": uid, "title": row.get("title"), "exclude_reason": "未命中任何包含关键词"})
                continue

            score = 1.0
            if ps_cfg.semantic_enable:
                score = _light_semantic_score(text, queries)

            candidates.append(
                {
                    "uid": uid,
                    "title": row.get("title"),
                    "year": year,
                    "author": row.get("author"),
                    "pdf_path": row.get("pdf_path"),
                    "score": float(score),
                    "reason": _build_reason(row, include_keywords_any=include_keywords_any),
                }
            )

        cand_df = pd.DataFrame(candidates).sort_values(["score", "year"], ascending=[False, False])
        cand_df = _apply_candidate_limit(cand_df, top_k=ps_cfg.top_k, top_ratio=ps_cfg.top_ratio)

        excl_df = pd.DataFrame(excluded)

        candidates_path = out_dir / output_candidates_name
        excluded_path = out_dir / output_excluded_name
        report_path = out_dir / output_report_name

        cand_df.to_csv(candidates_path, index=False, encoding="utf-8-sig")
        excl_df.to_csv(excluded_path, index=False, encoding="utf-8-sig")

        report = {
            "input_table_csv": str(input_table_csv),
            "output_dir": str(out_dir),
            "total": int(len(df)),
            "candidates": int(len(cand_df)),
            "excluded": int(len(excl_df)),
            "semantic_enable": bool(ps_cfg.semantic_enable),
            "top_k": ps_cfg.top_k,
            "top_ratio": ps_cfg.top_ratio,
            "include_if_has_pdf": ps_cfg.include_if_has_pdf,
            "include_keywords_any": include_keywords_any,
            "exclude_keywords_any": exclude_keywords_any,
            "year_range": ps_cfg.year_range,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        return [candidates_path, excluded_path, report_path]

    # 新实现写出
    cand_df = cand_df.sort_values(["score", "year"], ascending=[False, False]) if "year" in cand_df.columns else cand_df.sort_values(["score"], ascending=[False])
    cand_df = _apply_candidate_limit(cand_df, top_k=ps_cfg.top_k, top_ratio=ps_cfg.top_ratio)

    excl_df = pd.DataFrame(excluded_rows)

    candidates_path = out_dir / output_candidates_name
    excluded_path = out_dir / output_excluded_name
    report_path = out_dir / output_report_name

    cand_df.to_csv(candidates_path, index=False, encoding="utf-8-sig")
    excl_df.to_csv(excluded_path, index=False, encoding="utf-8-sig")

    report = {
        "input_table_csv": str(input_table_csv),
        "output_dir": str(out_dir),
        "total": int(len(df)),
        "candidates": int(len(cand_df)),
        "excluded": int(len(excl_df)),
        "semantic_enable": bool(ps_cfg.semantic_enable),
        "top_k": ps_cfg.top_k,
        "top_ratio": ps_cfg.top_ratio,
        "include_if_has_pdf": ps_cfg.include_if_has_pdf,
        "include_keywords_any": include_keywords_any,
        "exclude_keywords_any": exclude_keywords_any,
        "include_domains": include_domains,
        "exclude_domain_keywords_any": exclude_domain_keywords_any,
        "year_range": ps_cfg.year_range,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return [candidates_path, excluded_path, report_path]


def main() -> None:
    """命令行入口。"""

    import sys

    if len(sys.argv) < 2:
        raise SystemExit("用法：python 语义预筛选.py <config_path>")

    written = execute(Path(sys.argv[1]))
    for p in written:
        print(p)


if __name__ == "__main__":
    main()

