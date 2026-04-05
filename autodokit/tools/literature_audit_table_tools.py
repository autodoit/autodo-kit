"""文献关系审计表构建工具。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pandas as pd


def build_entity_to_literatures_csv(inv: Dict[str, List[int]], entity_name: str) -> pd.DataFrame:
    """构建实体主视角的聚合审计表。

    Args:
        inv: 反向索引（实体 -> 文献 id 列表）。
        entity_name: 实体列名。

    Returns:
        聚合审计 DataFrame。
    """
    rows: List[Dict[str, Any]] = []
    for entity, id_list in inv.items():
        ids = sorted(set(int(x) for x in id_list))
        rows.append(
            {
                entity_name: entity,
                "literature_count": len(ids),
                "literature_ids_json": json.dumps(ids, ensure_ascii=False),
            }
        )
    return pd.DataFrame(rows, columns=[entity_name, "literature_count", "literature_ids_json"])


def build_literature_main_audit_csv(
    table: pd.DataFrame,
    attachment_inv: Dict[str, List[int]],
    tag_inv: Dict[str, List[int]],
) -> pd.DataFrame:
    """构建文献主视角的聚合审计表。

    Args:
        table: 主表 DataFrame（索引为文献 id）。
        attachment_inv: 附件反向索引。
        tag_inv: 标签反向索引。

    Returns:
        聚合审计 DataFrame。
    """
    id_to_attachments: Dict[int, List[str]] = {}
    for attachment_path, id_list in attachment_inv.items():
        for rid in id_list:
            id_to_attachments.setdefault(int(rid), []).append(str(attachment_path))

    id_to_tags: Dict[int, List[str]] = {}
    for tag, id_list in tag_inv.items():
        for rid in id_list:
            id_to_tags.setdefault(int(rid), []).append(str(tag))

    rows: List[Dict[str, Any]] = []
    for rid in [int(x) for x in list(table.index)]:
        attachments = sorted(set(id_to_attachments.get(rid, [])))
        tags = sorted(set(id_to_tags.get(rid, [])))
        rows.append(
            {
                "id": rid,
                "attachment_count": len(attachments),
                "attachments_json": json.dumps(attachments, ensure_ascii=False),
                "tag_count": len(tags),
                "tags_json": json.dumps(tags, ensure_ascii=False),
            }
        )

    return pd.DataFrame(
        rows,
        columns=["id", "attachment_count", "attachments_json", "tag_count", "tags_json"],
    )
