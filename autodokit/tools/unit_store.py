"""文档单元数据库（Unit DB）落盘工具。

本模块用于把 `document_unit_splitter` 生成的 DocumentUnit 列表落盘到一个可追溯的目录结构，
并维护一个索引文件，记录每个单元的属性。

设计要点（符合开发者指南）：
- 事务侧只接收绝对路径，因此 `unit_db_dir` 必须由调度层在进入事务前绝对化。
- 本模块不负责路径“兜底解析”，只做校验与落盘。
- 单元内容文件采用 UTF-8 `.txt`，便于人类直接打开阅读；索引采用 `.jsonl`（可追加），
  并可选生成 `.csv` 汇总便于 Excel。

"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import uuid

from autodokit.tools.document_unit_splitter import DocumentUnit


@dataclass(frozen=True)
class UnitDBPaths:
    """Unit DB 目录结构路径。

    Attributes:
        root_dir: Unit DB 根目录（例如 <workspace_root>/data/文档单元数据库）。
        data_dir: 单元文件存储目录（root_dir/data）。
        index_jsonl: 单元索引（JSONL）。
        index_csv: 单元索引（CSV，可选生成）。
    """

    root_dir: Path
    data_dir: Path
    index_jsonl: Path
    index_csv: Path


def ensure_unit_db_dirs(unit_db_dir: Path) -> UnitDBPaths:
    """确保 Unit DB 目录结构存在。

    Args:
        unit_db_dir: Unit DB 根目录（必须绝对路径）。

    Returns:
        UnitDBPaths: 各路径对象。

    Raises:
        ValueError: unit_db_dir 不是绝对路径。
    """

    if not unit_db_dir.is_absolute():
        raise ValueError(f"unit_db_dir 必须为绝对路径（应由调度层绝对化）：{unit_db_dir}")

    root = unit_db_dir
    data_dir = (root / "data").resolve()
    root.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    return UnitDBPaths(
        root_dir=root,
        data_dir=data_dir,
        index_jsonl=(root / "units.jsonl").resolve(),
        index_csv=(root / "units.csv").resolve(),
    )


def _stable_hash(text: str) -> str:
    """生成稳定哈希，用于构造 unit_uid。"""

    h = hashlib.sha1()
    h.update(text.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def build_unit_uid(*, source_path: str, unit_index: int, unit_type: str, unit_text: str) -> str:
    """构造单元 UID。

    说明：
    - UID 需要稳定、可复现。
    - 这里结合 source_path + unit_index + unit_type + unit_text_hash。

    Args:
        source_path: 源文件绝对路径字符串。
        unit_index: 单元在文档内的序号。
        unit_type: 单元类型。
        unit_text: 单元文本。

    Returns:
        unit_uid 字符串。
    """

    text_hash = _stable_hash(unit_text)
    raw = f"{source_path}#{unit_index}#{unit_type}#{text_hash}"
    return _stable_hash(raw)


def write_units_to_db(
    *,
    unit_db_dir: Path,
    doc_name: str,
    source_rel_path: str,
    source_abs_path: str,
    units: List[DocumentUnit],
    doc_uid: Optional[str] = None,
    extra_doc_meta: Optional[Dict[str, Any]] = None,
    write_csv: bool = True,
) -> Dict[str, Any]:
    """把一个文档的 units 写入 Unit DB。

    Args:
        unit_db_dir: Unit DB 根目录（绝对路径）。
        doc_name: 文档名称（例如文件 stem）。
        source_rel_path: 源文件相对路径（相对 workspace_root，使用 / 分隔）。
        source_abs_path: 源文件绝对路径。
        units: 单元列表。
        doc_uid: 可选的文档 UID。
        extra_doc_meta: 可选附加 meta。
        write_csv: 是否同步写出 CSV 汇总（便于 Excel）。

    Returns:
        写入摘要信息（条数、路径等）。
    """

    paths = ensure_unit_db_dirs(unit_db_dir)

    # 使用微秒级时间戳 + 随机后缀，确保重建时 created_at 必然变化（便于增量维护与调试）。
    now = datetime.now().isoformat(timespec="microseconds") + "_" + uuid.uuid4().hex[:8]

    # 先预计算 unit_uid，便于写 prev/next 串联关系
    prepared: List[Dict[str, Any]] = []
    for idx, u in enumerate(units):
        text = (u.text or "").strip()
        if not text:
            continue

        unit_uid = build_unit_uid(
            source_path=str(source_abs_path),
            unit_index=int(idx),
            unit_type=str(u.unit_type),
            unit_text=text,
        )

        unit_file = (paths.data_dir / f"{unit_uid}.txt").resolve()

        meta = dict(getattr(u, "meta", {}) or {})
        prepared.append(
            {
                "unit_uid": unit_uid,
                "unit_type": str(u.unit_type),
                "unit_index": int(idx),
                "doc_name": str(doc_name),
                "doc_uid": str(doc_uid or ""),
                "source_rel_path": str(source_rel_path),
                "source_abs_path": str(source_abs_path),
                "unit_file": str(unit_file),
                "created_at": now,
                # 常用上下文字段：单独展开，便于查询
                "heading_level": meta.get("heading_level"),
                "context_heading_text": meta.get("context_heading_text"),
                "context_heading_level": meta.get("context_heading_level"),
                # 保留原始 meta 以便后续扩展
                "unit_meta": meta,
                "_text": text,
            }
        )

    # 写单元文件（内容）
    for row in prepared:
        unit_file = Path(str(row["unit_file"]))
        unit_file.write_text(str(row["_text"]) + "\n", encoding="utf-8")

    # 写索引行（追加 JSONL）
    index_rows: List[Dict[str, Any]] = []
    for i, row in enumerate(prepared):
        prev_uid = prepared[i - 1]["unit_uid"] if i > 0 else ""
        next_uid = prepared[i + 1]["unit_uid"] if i + 1 < len(prepared) else ""

        index_rows.append(
            {
                "unit_uid": row["unit_uid"],
                "unit_type": row["unit_type"],
                "unit_index": row["unit_index"],
                "doc_name": row["doc_name"],
                "doc_uid": row["doc_uid"],
                "source_rel_path": row["source_rel_path"],
                "source_abs_path": row["source_abs_path"],
                "unit_file": row["unit_file"],
                "created_at": row["created_at"],
                "prev_unit_uid": prev_uid,
                "next_unit_uid": next_uid,
                "heading_level": row.get("heading_level"),
                "context_heading_text": row.get("context_heading_text"),
                "context_heading_level": row.get("context_heading_level"),
                "extra_doc_meta": extra_doc_meta or {},
                "unit_meta": row.get("unit_meta") or {},
            }
        )

    if index_rows:
        with paths.index_jsonl.open("a", encoding="utf-8") as fout:
            for row in index_rows:
                fout.write(json.dumps(row, ensure_ascii=False) + "\n")

    if write_csv:
        _rebuild_csv_from_jsonl(paths.index_jsonl, paths.index_csv)

    return {
        "unit_db_dir": str(paths.root_dir),
        "units_written": int(len(index_rows)),
        "index_jsonl": str(paths.index_jsonl),
        "index_csv": str(paths.index_csv) if write_csv else "",
    }


def read_unit_index_rows(unit_db_dir: Path) -> List[Dict[str, Any]]:
    """读取 Unit DB 的索引行。

    说明：
    - 优先读取 `units.jsonl`，因为它是可追加写入的主索引；`units.csv` 可能由 jsonl 重建。
    - 若索引不存在，则返回空列表，便于“首次构建/空库”场景。

    Args:
        unit_db_dir: Unit DB 根目录（必须为绝对路径）。

    Returns:
        索引行列表（每行是 dict）。

    Raises:
        ValueError: unit_db_dir 不是绝对路径。
    """

    paths = ensure_unit_db_dirs(unit_db_dir)
    if not paths.index_jsonl.exists():
        return []

    rows: List[Dict[str, Any]] = []
    for ln in paths.index_jsonl.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        rows.append(json.loads(ln))
    return rows


def rewrite_unit_index(*, unit_db_dir: Path, rows: Iterable[Dict[str, Any]], write_csv: bool = True) -> UnitDBPaths:
    """用给定 rows 重写 Unit DB 索引文件。

    这么做的原因：
    - 现有 `write_units_to_db` 采用 JSONL 追加写入，适合“只增不删”。
    - 在“管理”事务中，我们需要删除/重建某些文档的 units，因此必须能把索引写回到一个干净状态。

    Args:
        unit_db_dir: Unit DB 根目录（必须为绝对路径）。
        rows: 全量索引行。
        write_csv: 是否同步重建 CSV 汇总。

    Returns:
        UnitDBPaths: Unit DB 目录结构路径。
    """

    paths = ensure_unit_db_dirs(unit_db_dir)
    normalized_rows = [dict(r) for r in rows]

    # 重写 jsonl：一次性写入，避免历史脏行积累
    with paths.index_jsonl.open("w", encoding="utf-8") as fout:
        for r in normalized_rows:
            fout.write(json.dumps(r, ensure_ascii=False) + "\n")

    if write_csv:
        _rebuild_csv_from_jsonl(paths.index_jsonl, paths.index_csv)

    return paths


def delete_units_by_source_rel_path(
    *,
    unit_db_dir: Path,
    source_rel_path: str,
    index_rows: List[Dict[str, Any]],
    delete_unit_files: bool = True,
) -> List[Dict[str, Any]]:
    """从索引中删除某个文档（source_rel_path）对应的全部 units。

    说明：
    - 本函数不直接读写索引文件，而是接收正在内存中维护的 `index_rows`，
      返回过滤后的新列表，便于调用方在一次事务结束时统一重写索引。
    - 选择按 `source_rel_path` 删除，是为了满足“同名不同后缀视为不同文档”的要求。

    Args:
        unit_db_dir: Unit DB 根目录（必须为绝对路径）。
        source_rel_path: 文档相对路径（相对 input_documents_dir，使用 / 分隔）。
        index_rows: 当前全量索引行。
        delete_unit_files: 是否删除 <unit_db_dir>/data/*.txt 单元内容文件。

    Returns:
        删除后的索引行列表。
    """

    _ = ensure_unit_db_dirs(unit_db_dir)
    autodokit = str(source_rel_path).replace("\\", "/")

    kept: List[Dict[str, Any]] = []
    to_delete: List[Dict[str, Any]] = []
    for r in index_rows:
        if str(r.get("source_rel_path") or "").replace("\\", "/") == autodokit:
            to_delete.append(r)
        else:
            kept.append(r)

    if delete_unit_files:
        for r in to_delete:
            unit_file = str(r.get("unit_file") or "").strip()
            if not unit_file:
                continue
            p = Path(unit_file)
            # 为什么做 exists 判断：索引可能来自手动修改或历史脏数据，清理时需容错。
            if p.exists() and p.is_file():
                try:
                    p.unlink()
                except OSError:
                    # 文件可能被占用或权限问题；管理事务不应因此整体失败
                    pass

    return kept


def _rebuild_csv_from_jsonl(index_jsonl: Path, index_csv: Path) -> None:
    """从 JSONL 重建 CSV（便于 Excel 打开）。"""

    if not index_jsonl.exists():
        return

    rows: List[Dict[str, Any]] = []
    with index_jsonl.open("r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue

    if not rows:
        return

    # 将 extra_doc_meta / unit_meta 展开为 JSON 字符串，避免 CSV 列爆炸
    for r in rows:
        if isinstance(r.get("extra_doc_meta"), (dict, list)):
            r["extra_doc_meta"] = json.dumps(r.get("extra_doc_meta"), ensure_ascii=False)
        if isinstance(r.get("unit_meta"), (dict, list)):
            r["unit_meta"] = json.dumps(r.get("unit_meta"), ensure_ascii=False)

    fieldnames = [
        "unit_uid",
        "unit_type",
        "unit_index",
        "doc_name",
        "doc_uid",
        "source_rel_path",
        "source_abs_path",
        "unit_file",
        "created_at",
        "prev_unit_uid",
        "next_unit_uid",
        "heading_level",
        "context_heading_text",
        "context_heading_level",
        "extra_doc_meta",
        "unit_meta",
    ]

    with index_csv.open("w", encoding="utf-8", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})
