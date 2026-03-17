"""生成文献元数据关系图（二分图）事务。

本事务用于从“文献元数据主表”构建并落盘三类实体
（作者、关键词、标签）与文献之间的二分图数据。

设计原因：
- 二分图/反向索引属于“派生数据”，强依赖去重与字段清洗策略；
- 将其与“导入与预处理”解耦，可让用户在合并去重之后再生成图数据，避免重复计算与错误传播。

输出格式说明见：`docs/二分图输出格式说明.md`。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from autodokit.tools import (
    build_adjacency_matrix_df,
    build_inverted_from_adjacency,
    build_inverted_index,
    load_json_or_py,
    sparse_from_inverted,
)


@dataclass
class Config:
    """配置数据类，表示本事务所需的配置项。

    Args:
        input_table_csv: 输入的文献主表 CSV 路径（包含 uid 索引）。
        output_dir: 输出目录。
        tag_list: 要匹配的标签列表。
        tag_match_fields: 用于匹配标签的字段列表（例如 title, abstract, keywords）。
    """

    input_table_csv: str
    output_dir: str
    tag_list: List[str]
    tag_match_fields: List[str]


DEFAULT_CONFIG: Dict[str, Any] = {
    # 约定：事务不负责提供相对路径默认值；必须由调度层注入绝对路径。
    "input_table_csv": "",
    "output_dir": "",
    "tag_list": ["graph", "risk", "bank", "systemic"],
    "tag_match_fields": ["title", "abstract", "keywords"],
}


def merge_config(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    """将用户配置与默认配置合并，用户配置字段优先覆盖默认值。

    Args:
        raw_config: 从配置文件读取的原始字典。

    Returns:
        合并后的配置字典。
    """

    merged = dict(DEFAULT_CONFIG)
    merged.update(raw_config)
    return merged


def normalize_text(text: str) -> str:
    """对文本做轻量归一化，用于标签匹配。

    说明：这里复用与“导入预处理”一致的核心目标：
    - 小写化
    - 去除多余空白

    Args:
        text: 原始文本。

    Returns:
        归一化后的文本。
    """

    s = (text or "").lower()
    return " ".join(s.split())


def split_authors(raw: str) -> List[str]:
    """将 author 字段拆分为作者列表，支持多种常见分隔符。

    Args:
        raw: 原始作者字段字符串。

    Returns:
        作者列表（已去除空项并做 strip）。
    """

    import re

    if not raw:
        return []
    parts = re.split(r"\s*(?:;|,|，|、|＆|/|\\|\||\sand\s)\s*", raw)
    return [p.strip() for p in parts if p and p.strip()]


def split_keywords(raw: str) -> List[str]:
    """将 keywords 字段拆分为关键字列表并去重，支持常见分隔符。

    Args:
        raw: 原始关键字字段字符串。

    Returns:
        规范化且去重后的关键字列表。
    """

    import re

    if not raw:
        return []
    parts = re.split(r"\s*[;,，/\\|]\s*", raw)
    parts = [p.strip() for p in parts if p and p.strip()]
    seen = set()
    out: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _save_pickle(obj: Any, path: Path) -> Path:
    """将对象以 pickle 序列化写入磁盘。

    Args:
        obj: 任意可序列化对象。
        path: 输出文件路径。

    Returns:
        写入的 Path 对象。
    """

    import pickle

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(obj, f, protocol=4)
    return path


def _save_csc_matrix(csc_mat, path: Path) -> Path | None:
    """将 scipy.sparse 的 csc_matrix 保存为 .npz 文件。

    Args:
        csc_mat: scipy.sparse.csc_matrix 对象。
        path: 输出路径（.npz）。

    Returns:
        成功则返回 path，否则返回 None。
    """

    try:
        from scipy.sparse import save_npz  # type: ignore

        path.parent.mkdir(parents=True, exist_ok=True)
        save_npz(str(path), csc_mat)
        return path
    except Exception:
        return None


def _build_bitsets_from_inverted(inv: Dict[str, List[int]], uid_list: List[int]) -> Dict[str, Any]:
    """把反向索引转换为位集合表示并返回。

    设计原因：
    - 位集合适合做高频的交并差集合运算；
    - 运行环境依赖不确定，因此按优先级尝试 pyroaring/bitarray，并在缺失时回退为 list。

    Args:
        inv: 反向索引（实体 -> uid 列表）。
        uid_list: 主表中的 uid 列表，顺序用于 bitarray 映射。

    Returns:
        dict[str, Any]，value 可能是 BitMap/bitarray/list。
    """

    bits: Dict[str, Any] = {}

    try:
        from pyroaring import BitMap as _RB  # type: ignore

        for key, ulist in inv.items():
            b = _RB()
            for uid in ulist:
                b.add(int(uid))
            bits[str(key)] = b
        return bits
    except Exception:
        pass

    try:
        from bitarray import bitarray as _BA  # type: ignore

        n = len(uid_list)
        uid_to_pos = {int(uid): i for i, uid in enumerate(uid_list)}
        for key, ulist in inv.items():
            ba = _BA(n)
            ba.setall(False)
            for uid in ulist:
                pos = uid_to_pos.get(int(uid))
                if pos is not None:
                    ba[pos] = True
            bits[str(key)] = ba
        return bits
    except Exception:
        pass

    return {str(k): [int(x) for x in v] for k, v in inv.items()}


def _run_and_write_all_outputs(config_path: Path) -> List[Path]:
    """读取配置并生成关系图数据，返回写出的文件路径列表。

    Args:
        config_path: 配置文件路径（json/py）。

    Returns:
        写出的文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    merged_cfg = merge_config(raw_cfg)

    # 过滤构造 Config（与其它事务保持一致的容错方式）
    try:
        from dataclasses import fields

        allowed_keys = {f.name for f in fields(Config)}
    except Exception:
        allowed_keys = set(DEFAULT_CONFIG.keys())

    filtered_cfg = {k: v for k, v in merged_cfg.items() if k in allowed_keys}
    config = Config(**filtered_cfg)

    input_table = Path(config.input_table_csv)
    output_dir = Path(config.output_dir)

    if not input_table.is_absolute():
        raise ValueError(f"input_table_csv 必须为绝对路径（应由调度层预处理）：{config.input_table_csv!r}")
    if not output_dir.is_absolute():
        raise ValueError(f"output_dir 必须为绝对路径（应由调度层预处理）：{str(output_dir)!r}")

    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    # 主表约定以 uid 为索引列（导入预处理脚本写出且 index_label=uid）
    table = pd.read_csv(input_table, encoding="utf-8-sig")
    if "uid" in table.columns:
        table.set_index("uid", inplace=True, drop=True)

    uid_list = [int(x) for x in list(table.index)]

    written_files: List[Path] = []

    def save_adjacency(entity_label: str, adj_df: pd.DataFrame) -> Path:
        path = output_dir / f"{entity_label}_adjacency.csv"
        adj_df.to_csv(path, index=False, encoding="utf-8-sig")
        return path

    def build_and_save_from_inverted(entity_label: str, inv: Dict[str, List[int]]) -> List[Path]:
        files: List[Path] = []

        inv_path = output_dir / f"{entity_label}_inverted_index.pkl"
        _save_pickle(inv, inv_path)
        files.append(inv_path)

        try:
            csc_mat, _labels = sparse_from_inverted(inv, uid_list)
            csc_path = output_dir / f"{entity_label}_csc.npz"
            saved = _save_csc_matrix(csc_mat, csc_path)
            if saved:
                files.append(saved)
        except Exception:
            pass

        bitsets = _build_bitsets_from_inverted(inv, uid_list)
        bitsets_path = output_dir / f"{entity_label}_bitsets.pkl"
        _save_pickle(bitsets, bitsets_path)
        files.append(bitsets_path)

        return files

    # 关键字二分图
    kw_inv = build_inverted_index(table, "keywords", split_keywords)
    kw_entities = list(kw_inv.keys())

    def kw_row_to_entities(_uid: int, row: Any) -> List[str]:
        return split_keywords(str(row.get("keywords", "")))

    kw_adj = build_adjacency_matrix_df(table, uid_list, kw_entities, kw_row_to_entities)
    written_files.append(save_adjacency("keywords", kw_adj))
    written_files.extend(build_and_save_from_inverted("keywords", kw_inv))

    # 作者二分图
    auth_inv = build_inverted_index(table, "author", split_authors)
    auth_entities = list(auth_inv.keys())

    def auth_row_to_entities(_uid: int, row: Any) -> List[str]:
        return split_authors(str(row.get("author", "")))

    auth_adj = build_adjacency_matrix_df(table, uid_list, auth_entities, auth_row_to_entities)
    written_files.append(save_adjacency("authors", auth_adj))
    written_files.extend(build_and_save_from_inverted("authors", auth_inv))

    # 标签二分图（基于字段文本包含匹配）
    tag_entities = list(config.tag_list)

    def tag_row_to_entities(_uid: int, row: Any) -> List[str]:
        combined = ""
        for fn in config.tag_match_fields:
            combined += f" {row.get(fn, '')}"
        combined_norm = normalize_text(combined)
        hits: List[str] = []
        for t in tag_entities:
            t_norm = normalize_text(t)
            if t_norm and t_norm in combined_norm:
                hits.append(t)
        return hits

    tag_adj = build_adjacency_matrix_df(table, uid_list, tag_entities, tag_row_to_entities)
    written_files.append(save_adjacency("tags", tag_adj))

    tag_inv = build_inverted_from_adjacency(uid_list, tag_adj)
    written_files.extend(build_and_save_from_inverted("tags", tag_inv))

    return written_files


def execute(config_path: Path) -> List[Path]:
    """供调度器调用的入口：执行并返回写出的文件清单。

    Args:
        config_path: 配置文件路径。

    Returns:
        写出的文件路径列表。
    """

    return _run_and_write_all_outputs(config_path)


def main() -> None:
    """命令行入口：直接运行并打印生成的文件列表。"""

    import sys

    if len(sys.argv) < 2:
        raise SystemExit(
            "用法：python 生成文献元数据关系图.py <config_path>\n"
            "示例：python autodokit/affairs/生成文献元数据关系图.py workflows/workflow_xxx/workflow.json"
        )

    cfg_path = Path(sys.argv[1])
    if not cfg_path.exists():
        raise SystemExit(f"配置文件不存在：{cfg_path}")

    written_files = _run_and_write_all_outputs(cfg_path)
    print("生成完成，已写出如下文件：")
    for p in written_files:
        print(f"  - {p}")


if __name__ == "__main__":
    main()

