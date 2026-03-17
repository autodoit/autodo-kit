"""解析与分块事务（通用说明）。

本事务的目标（一句话）：
- 把每篇文章的长文本拆成多个可管理的小段（chunk），方便检索和逐段交给模型或人工阅读。

为什么需要它（使用角度，通俗）：
- 长文本一次性交给模型会超过上下文限制或导致模型失焦。把文章切成小段可以：
  - 让检索只返回最相关的小段，提升效率；
  - 使模型逐段处理并汇总为准确的摘要/笔记。

本事务做什么（技术摘要，便于理解）：
- 读取 `docs.jsonl`（每篇文章的纯文本），对文本做轻量清洗（去多余空行），按字符长度切片并保留重叠，以便保留上下文连续性。

输入（必需）：
- `docs.jsonl`：由 `pdf_to_docs` 生成，每行包含 `doc_id`、`uid`、`text` 等。

输出（必需产物）：
- `chunks.jsonl`：每行一个 chunk（包含 chunk_id、uid、doc_id、text、span、meta）。
- `chunk_stats.json`：本次分块数量与配置统计。

在自动化流程中的位置（示例）：
- 场景：你想在一批长文档中快速定位“政策冲击”相关内容，分块后检索能迅速返回最相关的小段；或把这些段落交给模型分别摘要再合并。

何时用（简短建议）：
- 在你需要做检索/自动摘要/或把文章交给模型逐段分析时使用。若只想人工全文阅读，可不分块。

运行示例（项目 `workflow_010`）：
- 运行整个 flow（含提取与分块）:

  py main.py

- 单独运行本事务：

    py -c "from pathlib import Path; from autodo-kit.affairs.解析与分块 import execute; execute(Path('workflows/workflow_010/workflow.json'))"

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表（chunks.jsonl、chunk_stats.json）。

Examples:
    >>> from pathlib import Path
    >>> from autodokit.affairs.解析与分块 import execute
    >>> execute(Path('workflows/workflow_010/workflow.json'))
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from autodokit.tools import load_json_or_py
from autodokit.tools.document_unit_splitter import DocumentUnit, split_document_to_units
from autodokit.tools.unit_store import write_units_to_db


@dataclass
class ChunkConfig:
    """分块配置。

    Attributes:
        input_documents_dir: 原始文档目录（仅支持 .md/.tex，绝对路径）。
        input_docs_jsonl: 兼容旧流程的 docs.jsonl（绝对路径，若提供则优先生效）。
        output_dir: 输出目录。
        chunk_size: chunk 字符数（按单元聚合时用于控制 chunk 的近似长度）。
        chunk_overlap: chunk 重叠字符数（仅在按字符切分时生效）。
        min_chunk_size: 最小 chunk 字符数。
        unit_aware: 是否先按“单元”重组文本（减少公式/代码块被打散的概率）。
        chunk_by_units: 是否严格按单元聚合生成 chunk（不切单元）。
        unit_overlap: 按单元聚合时，相邻 chunk 之间重叠的单元数量。
        min_units_per_chunk: 按单元聚合时，每个 chunk 最少包含多少个单元。
        max_units_per_chunk: 按单元聚合时，每个 chunk 最多包含多少个单元（主约束）。
        unit_db_dir: 文档单元数据库根目录（绝对路径）。
        persist_units: 是否把单元落盘到 Unit DB。
    """

    input_documents_dir: Optional[str] = None
    input_docs_jsonl: Optional[str] = None
    output_dir: str = ""
    chunk_size: int = 1500
    chunk_overlap: int = 200
    min_chunk_size: int = 200
    unit_aware: bool = True  # 是否先按“单元”重组文本（减少公式/代码块被打散的概率）
    chunk_by_units: bool = True  # 是否严格按单元聚合（chunk 边界不切段落/公式等）
    unit_overlap: int = 1  # 单元级 overlap（默认 1 个单元，保留上下文）
    min_units_per_chunk: int = 5
    max_units_per_chunk: int = 8
    unit_db_dir: Optional[str] = None
    persist_units: bool = False


def _clean_text(text: str) -> str:
    """对文本做最小清洗。

    关键逻辑说明：
    - 我们优先保证“可检索性”，因此清洗只做轻量处理，避免误删正文。
    """

    lines = [ln.strip() for ln in (text or "").splitlines()]
    # 合并连续空行
    out_lines: List[str] = []
    blank = False
    for ln in lines:
        if not ln:
            if not blank:
                out_lines.append("")
            blank = True
            continue
        blank = False
        out_lines.append(ln)
    cleaned = "\n".join(out_lines)
    return cleaned.strip()


def _chunk_text(text: str, *, size: int, overlap: int, min_size: int) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    if not text:
        return chunks

    if overlap >= size:
        overlap = max(0, size // 4)

    start = 0
    idx = 0
    n = len(text)
    while start < n:
        end = min(n, start + size)
        piece = text[start:end]

        if len(piece.strip()) >= min_size:
            chunks.append({"idx": idx, "start": start, "end": end, "text": piece})
            idx += 1

        if end >= n:
            break
        start = max(0, end - overlap)

    return chunks


def _chunk_units(
    units: List[DocumentUnit],
    *,
    max_units: int,
    min_units: int,
    unit_overlap: int,
    target_size: int,
    min_size: int,
) -> List[Dict[str, Any]]:
    """按单元聚合生成 chunk（主约束：单元数）。

    设计说明：
    - 你要求 chunk 不能切单元，因此 chunk 的边界只能落在单元边界。
    - 单元数更稳定：比如每块 5~8 个单元，比纯字符更不受公式/表格缩写影响。
    - 字符 target_size 作为“次约束”：避免单元文本异常长导致 chunk 过大。

    Args:
        units: 单元列表。
        max_units: 每块最多单元数（主约束）。
        min_units: 每块最少单元数（尽量满足；最后一块可少于该值）。
        unit_overlap: 相邻块重叠单元数。
        target_size: 次约束：目标字符上限（近似）。
        min_size: 最小 chunk 字符数。

    Returns:
        chunk dict 列表。
    """

    if not units:
        return []

    max_units = max(1, int(max_units))
    min_units = max(1, int(min_units))
    unit_overlap = max(0, int(unit_overlap))
    target_size = max(1, int(target_size))

    chunks: List[Dict[str, Any]] = []
    i = 0
    idx = 0
    n = len(units)

    while i < n:
        start = i
        buf: List[str] = []
        used_chars = 0
        used_units = 0

        while i < n:
            t = (units[i].text or "").strip()
            if not t:
                i += 1
                continue

            # 主约束：单元数
            if used_units >= max_units:
                break

            sep = "\n\n" if buf else ""
            add_len = len(sep) + len(t)

            # 次约束：字符数
            if buf and (used_chars + add_len > target_size) and (used_units >= min_units):
                break

            buf.append(t)
            used_chars += add_len
            used_units += 1
            i += 1

            if used_units >= max_units:
                break

        end = i
        text = "\n\n".join(buf).strip()
        if len(text) >= int(min_size):
            chunks.append({
                "idx": idx,
                "unit_start": start,
                "unit_end": end,
                "units": int(used_units),
                "text": text,
            })
            idx += 1

        if end >= n:
            break

        i = max(0, end - unit_overlap)
        if i <= start:
            i = end

    return chunks


def _iter_md_tex_files(root: Path) -> List[Path]:
    """递归枚举 md/tex 文件并返回稳定顺序。"""

    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".tex"}]
    files.sort(key=lambda p: str(p.relative_to(root)).replace("\\", "/"))
    return files


def _build_docs_jsonl_from_documents_dir(
    *,
    input_dir: Path,
    docs_path: Path,
    unit_aware: bool,
    unit_db_dir: Optional[Path],
    persist_units: bool,
) -> Dict[str, int]:
    """从原始文档目录生成 docs.jsonl，并可选落盘 Unit DB。"""

    supported = {".md", ".tex"}
    total_files = 0
    used_files = 0
    skipped_files = 0

    files = _iter_md_tex_files(input_dir)
    total_files = len(files)

    with docs_path.open("w", encoding="utf-8") as fout:
        for p in files:
            if p.suffix.lower() not in supported:
                skipped_files += 1
                continue

            doc_id = p.stem
            uid = str(p)

            units: List[DocumentUnit] = []
            if unit_aware:
                units = split_document_to_units(p)
                text = "\n\n".join([u.text for u in units if u.text.strip()]).strip()
            else:
                text = _clean_text(p.read_text(encoding="utf-8", errors="ignore"))

            text = _clean_text(text)
            if not text:
                skipped_files += 1
                continue

            if persist_units and unit_db_dir is not None and units:
                if not unit_db_dir.is_absolute():
                    raise ValueError(
                        f"unit_db_dir 必须为绝对路径（应由调度层绝对化）：{unit_db_dir}"
                    )
                rel = str(p.relative_to(input_dir)).replace("\\", "/")
                write_units_to_db(
                    unit_db_dir=unit_db_dir,
                    doc_name=str(doc_id),
                    source_rel_path=rel,
                    source_abs_path=str(p),
                    units=units,
                    doc_uid=str(uid),
                    extra_doc_meta={"workflow": "parse_and_chunk_v1"},
                    write_csv=True,
                )

            doc = {
                "doc_id": doc_id,
                "uid": uid,
                "text": text,
                "meta": {
                    "source_path": str(p),
                    "suffix": p.suffix.lower(),
                    "relative_path": str(p.relative_to(input_dir)).replace("\\", "/"),
                },
            }
            fout.write(json.dumps(doc, ensure_ascii=False) + "\n")
            used_files += 1

    return {
        "input_files_total": int(total_files),
        "input_files_used": int(used_files),
        "input_files_skipped": int(skipped_files),
    }


def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)

    affair_cfg: Dict[str, Any] = dict(raw_cfg)

    cfg = ChunkConfig(
        input_documents_dir=affair_cfg.get("input_documents_dir"),
        input_docs_jsonl=affair_cfg.get("input_docs_jsonl"),
        output_dir=str(affair_cfg.get("output_dir") or ""),
        chunk_size=int(affair_cfg.get("chunk_size") or 1500),
        chunk_overlap=int(affair_cfg.get("chunk_overlap") or 200),
        min_chunk_size=int(affair_cfg.get("min_chunk_size") or 200),
        unit_aware=bool(affair_cfg.get("unit_aware", True)),
        chunk_by_units=bool(affair_cfg.get("chunk_by_units", True)),
        unit_overlap=int(affair_cfg.get("unit_overlap", 1) or 1),
        min_units_per_chunk=int(affair_cfg.get("min_units_per_chunk", 5) or 5),
        max_units_per_chunk=int(affair_cfg.get("max_units_per_chunk", 8) or 8),
        unit_db_dir=affair_cfg.get("unit_db_dir"),
        persist_units=bool(affair_cfg.get("persist_units", False)),
    )

    out_dir = Path(cfg.output_dir)
    if not out_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={cfg.output_dir!r}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    docs_path = out_dir / "docs.jsonl"
    chunks_path = out_dir / "chunks.jsonl"
    stats_path = out_dir / "chunk_stats.json"

    source_docs_jsonl: Optional[Path] = None
    build_stats: Dict[str, int] = {}

    if cfg.input_docs_jsonl:
        p_docs = Path(str(cfg.input_docs_jsonl))
        if not p_docs.is_absolute():
            raise ValueError(
                "input_docs_jsonl 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
                f"或检查 workspace_root 配置。当前值={cfg.input_docs_jsonl!r}"
            )
        source_docs_jsonl = p_docs
    else:
        if not cfg.input_documents_dir:
            raise ValueError("必须提供 input_documents_dir（或 input_docs_jsonl）")
        in_dir = Path(str(cfg.input_documents_dir))
        if not in_dir.is_absolute():
            raise ValueError(
                "input_documents_dir 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
                f"或检查 workspace_root 配置。当前值={cfg.input_documents_dir!r}"
            )
        if not in_dir.exists() or not in_dir.is_dir():
            raise ValueError(f"input_documents_dir 不存在或不是目录：{in_dir}")

        build_stats = _build_docs_jsonl_from_documents_dir(
            input_dir=in_dir,
            docs_path=docs_path,
            unit_aware=bool(cfg.unit_aware),
            unit_db_dir=Path(str(cfg.unit_db_dir)) if cfg.unit_db_dir else None,
            persist_units=bool(cfg.persist_units),
        )
        source_docs_jsonl = docs_path

    chunk_count = 0
    doc_count = 0

    with source_docs_jsonl.open("r", encoding="utf-8") as fin, chunks_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            doc_count += 1

            uid = doc.get("uid")
            doc_id = doc.get("doc_id")
            meta = doc.get("meta") or {}

            cleaned = _clean_text(str(doc.get("text") or ""))

            if cfg.chunk_by_units:
                # 关键逻辑说明：此模式下 span 不再是字符偏移，而是单元索引范围。
                # 由于 docs.jsonl 的 text 已经过单元化拼接（unit_aware=True 时），
                # 这里通过把 cleaned 写入临时文件再 split，得到可复现的单元边界。
                tmp_path = (out_dir / f".unit_chunk_tmp_{doc_id}.txt")
                tmp_path.write_text(cleaned, encoding="utf-8")
                try:
                    units = split_document_to_units(tmp_path)
                finally:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass

                pieces = _chunk_units(
                    units,
                    max_units=cfg.max_units_per_chunk,
                    min_units=cfg.min_units_per_chunk,
                    unit_overlap=cfg.unit_overlap,
                    target_size=cfg.chunk_size,
                    min_size=cfg.min_chunk_size,
                )

                for p in pieces:
                    chunk = {
                        "chunk_id": f"{doc_id}#c{p['idx']}",
                        "uid": uid,
                        "doc_id": doc_id,
                        "text": p["text"],
                        "span": {"unit_start": p["unit_start"], "unit_end": p["unit_end"]},
                        "meta": {**meta, "span_type": "unit", "units": int(p.get("units") or 0)},
                    }
                    fout.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                    chunk_count += 1

                continue

            # 回退：按字符切分（旧模式）
            pieces = _chunk_text(
                cleaned,
                size=cfg.chunk_size,
                overlap=cfg.chunk_overlap,
                min_size=cfg.min_chunk_size,
            )

            for p in pieces:
                chunk = {
                    "chunk_id": f"{doc_id}#c{p['idx']}",
                    "uid": uid,
                    "doc_id": doc_id,
                    "text": p["text"],
                    "span": {"start": p["start"], "end": p["end"]},
                    "meta": {**meta, "span_type": "char"},
                }
                fout.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                chunk_count += 1

    stats = {
        "input_documents_dir": str(cfg.input_documents_dir or ""),
        "input_docs_jsonl": str(cfg.input_docs_jsonl or ""),
        "generated_docs_jsonl": str(docs_path) if docs_path.exists() else "",
        **build_stats,
        "output_dir": str(out_dir),
        "docs": int(doc_count),
        "chunks": int(chunk_count),
        "chunk_size": cfg.chunk_size,
        "chunk_overlap": cfg.chunk_overlap,
        "min_chunk_size": cfg.min_chunk_size,
        "unit_aware": bool(cfg.unit_aware),
        "chunk_by_units": bool(cfg.chunk_by_units),
        "unit_overlap": int(cfg.unit_overlap),
        "min_units_per_chunk": int(cfg.min_units_per_chunk),
        "max_units_per_chunk": int(cfg.max_units_per_chunk),
        "unit_db_dir": str(cfg.unit_db_dir or ""),
        "persist_units": bool(cfg.persist_units),
        "allowed_suffixes": [".md", ".tex"],
    }
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    written: List[Path] = []
    if docs_path.exists():
        written.append(docs_path)
    written.extend([chunks_path, stats_path])
    return written


def main() -> None:
    """命令行入口。"""

    import sys

    if len(sys.argv) < 2:
        raise SystemExit("用法：python 解析与分块.py <config_path>")

    for p in execute(Path(sys.argv[1])):
        print(p)


if __name__ == "__main__":
    main()


