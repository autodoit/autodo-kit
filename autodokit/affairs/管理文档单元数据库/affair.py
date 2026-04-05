"""构建文档单元数据库事务。

本事务仅做一件事：
- 从原始文档目录（当前仅支持 .md/.tex）读取文件，按“单元”切分（标题/段落/公式/图表/代码块/引文等），
  然后把每个单元落盘到 Unit DB，并写出索引数据库（units.jsonl/units.csv）。

为何单独做成事务：
- 方便把“知识库预处理”作为独立可重复的步骤运行；
- 便于后续事务（检索/向量化/阅读辅助）复用同一份 Unit DB。

配置字段（均必须为绝对路径，由调度层统一绝对化，符合开发者指南）：
- input_documents_dir: 原始文档目录（绝对路径，仅 md/tex）。
- unit_db_dir: Unit DB 根目录（绝对路径，例如 <workspace_root>/data/文档单元数据库）。

输出：
- <unit_db_dir>/data/*.txt
- <unit_db_dir>/units.jsonl
- <unit_db_dir>/units.csv
- <output_dir>/unit_db_stats.json（可选）

输出文件说明（目的与主要字段）

下面对常见输出文件的作用与字段做说明，便于调用者和维护者理解生成产物的结构与用途：

units.jsonl（主索引，行分隔 JSON）
- 作用：主索引文件，追加写入模式，记录每个文档单元（unit）的元信息，便于流式读取和后续处理（例如向量化、检索索引构建）。
- 每一行（JSON 对象）典型字段：
  - unit_uid: 单元唯一标识（稳定哈希，可用于文件名与跨运行追踪）。
  - unit_type: 单元类型（例如 paragraph/heading/equation 等）。
  - unit_index: 单元在源文档中的序号（从 0 开始）。
  - doc_name: 文档名（通常为文件 stem）。
  - doc_uid: 可选文档 UID（如有外部生成）。
  - source_rel_path: 源文件相对路径（相对于文档输入根，使用 / 分隔）。
  - source_abs_path: 源文件绝对路径（便于定位源文档）。
  - unit_file: 对应的单元内容文件路径（data 目录下的 .txt 文件）。
  - created_at: 写入时间戳（包含微秒与随机后缀，用于调试与排序）。
  - prev_unit_uid / next_unit_uid: 相邻单元的 unit_uid，便于按文档顺序串联。
  - heading_level / context_heading_text / context_heading_level: 常用上下文字段，表示单元所在的标题层级与最近的上下文标题文本。
  - extra_doc_meta: 写入时附加的文档级元信息（例如 doc_sha1、workflow 标识等），通常为对象/字典。
  - unit_meta: 单元级的原始 meta（来自分块器），可包含更多上下文信息。

units.csv（CSV 汇总）
- 作用：从 JSONL 重建的表格形式索引，便于用 Excel 或 pandas 快速查看与筛选。
- 说明：CSV 包含与 JSONL 等价的列；其中复杂字段（extra_doc_meta、unit_meta）被序列化为 JSON 字符串，以避免列爆炸。

data/*.txt（单元内容文件）
- 作用：每个单元的原始文本内容以 UTF-8 文本文件存储，便于人工检查与外部工具读取。
- 命名与格式：文件名为 {unit_uid}.txt，编码 UTF-8，内容为单元文本（末尾含换行）。
- 说明：索引中的 unit_file 字段指向这些文件的绝对路径；在删除单元时，管理逻辑可选择同时删除对应的 .txt 文件。

unit_db_stats.json / unit_db_manage_stats.json（运行统计与路径汇总）
- 作用：记录本次事务的输入/输出路径、变更统计与参数设置，便于审计、后续步骤接入与调试。
- 典型字段（可能根据具体事务略有差别）：
  - input_documents_dir: 本次扫描的输入文档根目录（绝对路径）。
  - unit_db_dir: Unit DB 根目录（绝对路径）。
  - documents_added: 被判定为新增的文档数量（仅管理事务）。
  - documents_removed: 被判定为删除的文档数量（仅管理事务）。
  - documents_modified: 被判定为修改的文档数量（仅管理事务）。
  - documents_processed / documents: 实际被处理的文档数（按场景命名不同）。
  - units_written: 本次写入的单元总数（整数）。
  - index_jsonl / index_csv / data_dir: 生成产物的路径（用于快速定位）。
  - allowed_suffixes: 允许的源文件后缀列表（例如 [".md", ".tex"]）。
  - change_detect_strategy: 变更检测策略（如 mtime_size / hash / mtime_size_then_hash）。
  - full_rebuild: 是否执行了全量重建（布尔）。

doc_manifest.json（扫描清单与变更明细）
- 作用：当管理事务开启文档持久化 manifest 时，写出本次扫描结果的详细清单，便于审计与增量逻辑验证。
- 结构与字段：
  - scan: 一个对象，键为源文档的相对路径，值为该文档的扫描状态信息，典型子字段：
    - rel: 源文档相对路径（/ 分隔）。
    - abs: 源文档绝对路径。
    - mtime_ns: 文件修改时间（纳秒）。
    - size: 文件大小（字节）。
    - sha1:（可选）在使用 hash 策略时记录的文件内容哈希。
  - added: 新检测到的文档列表（相对路径字符串）。
  - removed: 被检测为删除的文档列表。
  - modified: 被判定为修改的文档列表。

一致性与使用建议
- 推荐在每次运行后用 stats 中的 units_written 与 data 目录中文件数或 units.jsonl 的行数做一致性检查，确保索引与落盘文件匹配。
- 注意：write_units_to_db 采用 JSONL 追加写入以提高性能；管理事务在结束时会调用重写索引以清理历史脏行并重建 CSV，从而保持索引整洁。

Args:
    config_path: 调度器写入的临时配置文件路径。

Returns:
    写出的文件路径列表。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from autodokit.tools import load_json_or_py
from autodokit.tools.document_unit_splitter import split_document_to_units
from autodokit.tools.unit_store import (
    delete_units_by_source_rel_path,
    ensure_unit_db_dirs,
    read_unit_index_rows,
    rewrite_unit_index,
    write_units_to_db,
)


@dataclass
class BuildUnitDBConfig:
    """构建 Unit DB 的配置。"""

    input_documents_dir: str
    unit_db_dir: str
    output_dir: Optional[str] = None


@dataclass
class ManageUnitDBConfig:
    """管理 Unit DB 的配置。

    说明：
    - 本配置用于“增量维护” Unit DB：根据输入目录的文档增删改，自动更新 units 索引与 data/*.txt。

    Args:
        input_documents_dir: 原始文档目录（绝对路径，仅 md/tex）。
        unit_db_dir: Unit DB 根目录（绝对路径）。
        output_dir: 可选输出目录（用于写统计与调试文件）。
        change_detect_strategy: 变更检测策略：
            - "mtime_size": 只用修改时间+文件大小判断（快，但可能漏判极端情况）。
            - "hash": 只用内容哈希判断（稳，但慢）。
            - "mtime_size_then_hash": 先快判，疑似变化时再算哈希（推荐默认）。
        full_rebuild: 是否忽略增量，强制全量重建（兜底模式）。
        persist_doc_manifest: 是否写出 doc_manifest.json（调试用）。
    """

    input_documents_dir: str
    unit_db_dir: str
    output_dir: Optional[str] = None
    change_detect_strategy: str = "mtime_size_then_hash"
    full_rebuild: bool = False
    persist_doc_manifest: bool = True


def _iter_md_tex_files(root: Path) -> List[Path]:
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".tex"}]
    files.sort(key=lambda p: str(p.relative_to(root)).replace("\\", "/"))
    return files


def _file_sha1(p: Path) -> str:
    """计算文件内容 SHA1。

    Args:
        p: 文件路径。

    Returns:
        sha1 十六进制字符串。
    """

    h = hashlib.sha1()
    # 分块读取，避免大文件一次性读入内存
    with p.open("rb") as fin:
        while True:
            chunk = fin.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _scan_documents(
    *,
    input_documents_dir: Path,
    strategy: str,
) -> Dict[str, Dict[str, object]]:
    """扫描输入目录并物化文档状态。

    Args:
        input_documents_dir: 原始文档目录（绝对路径）。
        strategy: 变更检测策略。

    Returns:
        dict: key 为 source_rel_path（/ 分隔），value 为状态信息。
    """

    docs: Dict[str, Dict[str, object]] = {}
    for p in _iter_md_tex_files(input_documents_dir):
        rel = str(p.relative_to(input_documents_dir)).replace("\\", "/")
        st = p.stat()
        state: Dict[str, object] = {
            "rel": rel,
            "abs": str(p),
            "mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
            "size": int(st.st_size),
        }
        if strategy == "hash":
            state["sha1"] = _file_sha1(p)
        docs[rel] = state
    return docs


def _doc_fingerprint(state: Dict[str, object], *, strategy: str) -> Tuple[object, ...]:
    """把文档状态转换为可比对的指纹。

    Args:
        state: 扫描得到的状态。
        strategy: 变更检测策略。

    Returns:
        可哈希/可比较的 tuple。
    """

    if strategy == "hash":
        return ("hash", state.get("sha1") or "")
    # 默认 mtime+size
    return ("mtime_size", int(state.get("mtime_ns") or 0), int(state.get("size") or 0))


def execute(config_path: Path) -> List[Path]:
    cfg_raw = load_json_or_py(config_path)
    cfg = BuildUnitDBConfig(
        input_documents_dir=str(cfg_raw.get("input_documents_dir") or ""),
        unit_db_dir=str(cfg_raw.get("unit_db_dir") or ""),
        output_dir=str(cfg_raw.get("output_dir") or "") or None,
    )

    in_dir = Path(cfg.input_documents_dir)
    if not in_dir.is_absolute():
        raise ValueError(f"input_documents_dir 必须为绝对路径（应由调度层绝对化）：{cfg.input_documents_dir!r}")
    if not in_dir.exists() or not in_dir.is_dir():
        raise ValueError(f"input_documents_dir 不存在或不是目录：{in_dir}")

    unit_db_dir = Path(cfg.unit_db_dir)
    if not unit_db_dir.is_absolute():
        raise ValueError(f"unit_db_dir 必须为绝对路径（应由调度层绝对化）：{cfg.unit_db_dir!r}")

    paths = ensure_unit_db_dirs(unit_db_dir)

    out_dir: Optional[Path] = None
    if cfg.output_dir:
        out_dir = Path(cfg.output_dir)
        if not out_dir.is_absolute():
            raise ValueError(f"output_dir 必须为绝对路径（应由调度层绝对化）：{cfg.output_dir!r}")
        out_dir.mkdir(parents=True, exist_ok=True)

    files = _iter_md_tex_files(in_dir)

    docs_used = 0
    units_written_total = 0

    for p in files:
        units = split_document_to_units(p)
        if not units:
            continue

        rel = str(p.relative_to(in_dir)).replace("\\", "/")
        summary = write_units_to_db(
            unit_db_dir=unit_db_dir,
            doc_name=p.stem,
            source_rel_path=rel,
            source_abs_path=str(p),
            units=units,
            doc_uid=str(p),
            extra_doc_meta={"workflow": "build_unit_db_v1"},
            write_csv=True,
        )
        docs_used += 1
        units_written_total += int(summary.get("units_written") or 0)

    stats = {
        "input_documents_dir": str(in_dir),
        "unit_db_dir": str(unit_db_dir),
        "documents": int(docs_used),
        "units_written": int(units_written_total),
        "index_jsonl": str(paths.index_jsonl),
        "index_csv": str(paths.index_csv),
        "data_dir": str(paths.data_dir),
        "allowed_suffixes": [".md", ".tex"],
    }

    written: List[Path] = []
    if out_dir is not None:
        stats_path = (out_dir / "unit_db_stats.json").resolve()
        stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(stats_path)

    # Unit DB 产物
    written.append(paths.index_jsonl)
    written.append(paths.index_csv)

    return written


def execute_manage(config_path: Path) -> List[Path]:
    """管理 Unit DB（增量）：根据输入目录文档增删改更新单元索引与落盘文件。

    Args:
        config_path: 调度器写入的临时配置文件路径。

    Returns:
        写出的文件路径列表。

    Raises:
        ValueError: 关键配置缺失或不合法。
    """

    cfg_raw = load_json_or_py(config_path)
    cfg = ManageUnitDBConfig(
        input_documents_dir=str(cfg_raw.get("input_documents_dir") or ""),
        unit_db_dir=str(cfg_raw.get("unit_db_dir") or ""),
        output_dir=str(cfg_raw.get("output_dir") or "") or None,
        change_detect_strategy=str(cfg_raw.get("change_detect_strategy") or "mtime_size_then_hash"),
        full_rebuild=bool(cfg_raw.get("full_rebuild", False)),
        persist_doc_manifest=bool(cfg_raw.get("persist_doc_manifest", True)),
    )

    in_dir = Path(cfg.input_documents_dir)
    if not in_dir.is_absolute():
        raise ValueError(f"input_documents_dir 必须为绝对路径（应由调度层绝对化）：{cfg.input_documents_dir!r}")
    if not in_dir.exists() or not in_dir.is_dir():
        raise ValueError(f"input_documents_dir 不存在或不是目录：{in_dir}")

    unit_db_dir = Path(cfg.unit_db_dir)
    if not unit_db_dir.is_absolute():
        raise ValueError(f"unit_db_dir 必须为绝对路径（应由调度层绝对化）：{cfg.unit_db_dir!r}")

    paths = ensure_unit_db_dirs(unit_db_dir)

    out_dir: Optional[Path] = None
    if cfg.output_dir:
        out_dir = Path(cfg.output_dir)
        if not out_dir.is_absolute():
            raise ValueError(f"output_dir 必须为绝对路径（应由调度层绝对化）：{cfg.output_dir!r}")
        out_dir.mkdir(parents=True, exist_ok=True)

    strategy = cfg.change_detect_strategy.strip() or "mtime_size_then_hash"
    if strategy not in {"mtime_size", "hash", "mtime_size_then_hash"}:
        raise ValueError(f"不支持的 change_detect_strategy：{strategy}")

    # 1) 扫描当前输入目录
    scan_fast = _scan_documents(input_documents_dir=in_dir, strategy="mtime_size")

    # 2) 读取现有索引，并物化“已知文档 -> 指纹/信息”
    index_rows = read_unit_index_rows(unit_db_dir)

    existing_docs: Dict[str, Dict[str, object]] = {}
    for r in index_rows:
        rel = str(r.get("source_rel_path") or "").replace("\\", "/")
        abs_path = str(r.get("source_abs_path") or "")
        if not rel:
            continue
        if rel not in existing_docs:
            existing_docs[rel] = {"rel": rel, "abs": abs_path}

        # 记录索引里保存的 doc_sha1，避免用文件路径回读“旧内容”（文件已被修改会读到新内容）
        extra = r.get("extra_doc_meta")
        if isinstance(extra, dict):
            sha1_val = extra.get("doc_sha1")
            if isinstance(sha1_val, str) and sha1_val:
                existing_docs[rel]["doc_sha1"] = sha1_val

    # full_rebuild 时：把 existing 视为全删再全建
    scan_keys = set(scan_fast.keys())
    existing_keys = set(existing_docs.keys())

    added = scan_keys - existing_keys
    removed = existing_keys - scan_keys

    modified: set[str] = set()
    if cfg.full_rebuild:
        modified = scan_keys
        removed = existing_keys
        added = set()
    else:
        common = scan_keys & existing_keys

        if strategy == "mtime_size":
            for k in common:
                fp_old = _doc_fingerprint(existing_docs.get(k, {}), strategy="mtime_size")
                fp_new = _doc_fingerprint(scan_fast.get(k, {}), strategy="mtime_size")
                if fp_old != fp_new:
                    modified.add(k)

        elif strategy == "hash":
            # hash 策略意味着“只要内容变了就重建”，因此必须对 common 全量算 hash
            scan_with_hash = _scan_documents(input_documents_dir=in_dir, strategy="hash")
            for k in common:
                # old hash 优先取索引中保存的 doc_sha1（否则文件已被修改会读到新内容）
                old_sha1 = str(existing_docs.get(k, {}).get("doc_sha1") or "")
                if not old_sha1:
                    old_abs = str(existing_docs.get(k, {}).get("abs") or "")
                    try:
                        if old_abs:
                            p_old = Path(old_abs)
                            if p_old.exists() and p_old.is_file():
                                old_sha1 = _file_sha1(p_old)
                    except Exception:
                        old_sha1 = ""

                new_sha1 = str((scan_with_hash.get(k) or {}).get("sha1") or "")
                if old_sha1 != new_sha1:
                    modified.add(k)

        else:
            # mtime_size_then_hash：先用 mtime+size 快判，再用 hash 强判确认
            suspected: set[str] = set()
            for k in common:
                fp_old = _doc_fingerprint(existing_docs.get(k, {}), strategy="mtime_size")
                fp_new = _doc_fingerprint(scan_fast.get(k, {}), strategy="mtime_size")
                if fp_old != fp_new:
                    suspected.add(k)

            if suspected:
                for k in suspected:
                    old_sha1 = str(existing_docs.get(k, {}).get("doc_sha1") or "")
                    if not old_sha1:
                        old_abs = str(existing_docs.get(k, {}).get("abs") or "")
                        try:
                            if old_abs:
                                p_old = Path(old_abs)
                                if p_old.exists() and p_old.is_file():
                                    old_sha1 = _file_sha1(p_old)
                        except Exception:
                            old_sha1 = ""

                    try:
                        new_sha1 = _file_sha1((in_dir / k).resolve())
                    except Exception:
                        new_sha1 = ""

                    if old_sha1 != new_sha1:
                        modified.add(k)

    # 3) 执行删除（removed + modified 先删旧）
    for rel in sorted(removed | modified):
        index_rows = delete_units_by_source_rel_path(
            unit_db_dir=unit_db_dir,
            source_rel_path=rel,
            index_rows=index_rows,
            delete_unit_files=True,
        )

    # 先把“删除后的索引”写回磁盘，避免后续追加写入时把历史脏行继续带上
    rewrite_unit_index(unit_db_dir=unit_db_dir, rows=index_rows, write_csv=False)

    # 4) 执行新增 / 重建（added + modified）
    docs_used = 0
    units_written_total = 0

    for rel in sorted(added | modified):
        p = (in_dir / rel).resolve()
        if not p.exists() or not p.is_file():
            continue

        # 先计算文档级hash，写入extra_doc_meta，作为下次增量检测的“旧值来源”
        doc_sha1 = ""
        try:
            if strategy in {"hash", "mtime_size_then_hash"}:
                doc_sha1 = _file_sha1(p)
        except Exception:
            doc_sha1 = ""

        units = split_document_to_units(p)
        if not units:
            continue

        extra_meta = {"workflow": "manage_unit_db_v1"}
        if doc_sha1:
            extra_meta["doc_sha1"] = doc_sha1

        summary = write_units_to_db(
            unit_db_dir=unit_db_dir,
            doc_name=p.stem,
            source_rel_path=rel,
            source_abs_path=str(p),
            units=units,
            doc_uid=str(p),
            extra_doc_meta=extra_meta,
            # 这里先不写 csv，最后统一重写索引时再生成，减少 I/O
            write_csv=False,
        )
        docs_used += 1
        units_written_total += int(summary.get("units_written") or 0)

        # 由于 write_units_to_db 采用追加写入，这里把新增行重新读回内存会很慢；
        # 因此管理事务在结束时直接重新读取 jsonl 并重写，保证一致性即可。

    # 5) 结束时：读取最新 jsonl，并再次应用删除过滤（防止历史残留行）
    final_rows = read_unit_index_rows(unit_db_dir)
    for rel in sorted(removed):
        final_rows = delete_units_by_source_rel_path(
            unit_db_dir=unit_db_dir,
            source_rel_path=rel,
            index_rows=final_rows,
            delete_unit_files=False,
        )

    # 6) 写出干净索引（并重建 csv），可避免历史追加越积越多
    rewrite_unit_index(unit_db_dir=unit_db_dir, rows=final_rows, write_csv=True)

    stats = {
        "input_documents_dir": str(in_dir),
        "unit_db_dir": str(unit_db_dir),
        "documents_added": int(len(added)),
        "documents_removed": int(len(removed)),
        "documents_modified": int(len(modified)),
        "documents_processed": int(docs_used),
        "units_written": int(units_written_total),
        "index_jsonl": str(paths.index_jsonl),
        "index_csv": str(paths.index_csv),
        "data_dir": str(paths.data_dir),
        "allowed_suffixes": [".md", ".tex"],
        "change_detect_strategy": strategy,
        "full_rebuild": bool(cfg.full_rebuild),
    }

    written: List[Path] = []
    if out_dir is not None:
        stats_path = (out_dir / "unit_db_manage_stats.json").resolve()
        stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(stats_path)

        if cfg.persist_doc_manifest:
            manifest = {
                "scan": scan_fast,
                "added": sorted(added),
                "removed": sorted(removed),
                "modified": sorted(modified),
            }
            manifest_path = (out_dir / "doc_manifest.json").resolve()
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append(manifest_path)

    written.append(paths.index_jsonl)
    written.append(paths.index_csv)
    return written


def main() -> None:
    import sys

    if len(sys.argv) < 2:
        raise SystemExit("用法：python 管理文档单元数据库.py <config_path>")

    for p in execute(Path(sys.argv[1])):
        print(p)


if __name__ == "__main__":
    main()


