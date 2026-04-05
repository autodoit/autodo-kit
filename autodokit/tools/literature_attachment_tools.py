"""文献与附件关系构建工具。"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd


def build_literature_attachment_inverted_index(table: pd.DataFrame) -> Dict[str, List[int]]:
    """构建附件到文献 id 的反向索引。

    Args:
        table: 主表 DataFrame（索引为 id）。

    Returns:
        键为附件路径，值为命中文献 id 列表。
    """
    inv: Dict[str, List[int]] = {}
    for rid, row in table.iterrows():
        path = str(row.get("pdf_path", "")).strip()
        if not path:
            continue
        inv.setdefault(path, []).append(int(rid))

    for key in list(inv.keys()):
        inv[key] = sorted(set(inv[key]))
    return inv
