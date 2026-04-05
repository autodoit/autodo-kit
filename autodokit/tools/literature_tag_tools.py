"""文献与标签关系构建工具。"""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

import pandas as pd


def build_literature_tag_inverted_index(
    table: pd.DataFrame,
    tag_list: List[str],
    tag_match_fields: List[str],
    *,
    normalize_text_fn: Callable[[str], str],
) -> Dict[str, List[int]]:
    """基于文本包含关系构建标签到文献 id 的反向索引。

    Args:
        table: 主表 DataFrame（索引为 id）。
        tag_list: 标签候选列表。
        tag_match_fields: 参与匹配的文本字段。
        normalize_text_fn: 文本归一化函数。

    Returns:
        键为标签，值为命中文献 id 列表。
    """
    normalized_tags: List[Tuple[str, str]] = []
    for tag in tag_list:
        t = str(tag).strip()
        if not t:
            continue
        t_norm = normalize_text_fn(t)
        if t_norm:
            normalized_tags.append((t, t_norm))

    inv: Dict[str, List[int]] = {raw_tag: [] for raw_tag, _ in normalized_tags}
    for rid, row in table.iterrows():
        chunks: List[str] = []
        for field_name in tag_match_fields:
            chunks.append(str(row.get(field_name, "")))
        combined_norm = normalize_text_fn(" ".join(chunks))
        if not combined_norm:
            continue
        for raw_tag, norm_tag in normalized_tags:
            if norm_tag in combined_norm:
                inv[raw_tag].append(int(rid))

    for key in list(inv.keys()):
        inv[key] = sorted(set(inv[key]))
    return inv
