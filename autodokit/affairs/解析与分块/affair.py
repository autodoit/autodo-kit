"""解析与分块事务。

本事务只接受统一结构化结果作为输入，并产出 chunk manifest、chunk 分片与索引表。
旧 `docs.jsonl` / `chunks.jsonl` 链路已退役，不再作为 PDF 主链契约。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from autodokit.tools import load_json_or_py
from autodokit.tools.bibliodb_sqlite import load_literatures_df, replace_chunk_set_records
from autodokit.tools.contentdb_sqlite import resolve_content_db_config
from autodokit.tools.pdf_structured_data_tools import (
    build_chunk_entries_from_structured_data,
    load_structured_data,
    write_chunk_shards,
)


@dataclass
class ChunkConfig:
    """分块配置。"""

    output_dir: str = ""
    chunk_size: int = 1500
    min_chunk_size: int = 200
    input_structured_dir: Optional[str] = None
    content_db: Optional[str] = None
    source_scope: str = "structured"
    source_backend: str = "structured_json"
    chunk_shard_size: int = 200
    chunks_uid: str = ""
    db_input_key: str = ""


def _build_chunks_uid(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    if text:
        return text
    return f"chunks-{datetime.now(tz=UTC).strftime('%Y%m%d%H%M%S')}"


def _collect_structured_paths(*, structured_dir: Optional[str], content_db: Optional[str]) -> List[Path]:
    """收集结构化 JSON 路径列表。"""

    paths: List[Path] = []
    seen: set[str] = set()
    if content_db:
        db_path = Path(str(content_db))
        if not db_path.is_absolute():
            raise ValueError(f"content_db 必须为绝对路径：{db_path}")
        table = load_literatures_df(db_path).fillna("")
        if "structured_abs_path" in table.columns:
            for _, row in table.iterrows():
                structured_abs_path = str(row.get("structured_abs_path") or "").strip()
                if not structured_abs_path or structured_abs_path in seen:
                    continue
                path = Path(structured_abs_path)
                if path.exists() and path.is_file():
                    paths.append(path)
                    seen.add(structured_abs_path)
    if structured_dir:
        root = Path(str(structured_dir))
        if not root.is_absolute():
            raise ValueError(f"input_structured_dir 必须为绝对路径：{root}")
        for path in sorted(root.glob("*.structured.json")):
            key = str(path.resolve())
            if key in seen:
                continue
            paths.append(path.resolve())
            seen.add(key)
    return paths


def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)

    affair_cfg: Dict[str, Any] = dict(raw_cfg)
    content_db_path, db_input_key = resolve_content_db_config(affair_cfg)

    cfg = ChunkConfig(
        output_dir=str(affair_cfg.get("output_dir") or ""),
        chunk_size=int(affair_cfg.get("chunk_size") or 1500),
        min_chunk_size=int(affair_cfg.get("min_chunk_size") or 200),
        input_structured_dir=str(affair_cfg.get("input_structured_dir") or "").strip() or None,
        content_db=str(content_db_path) if content_db_path is not None else None,
        source_scope=str(affair_cfg.get("source_scope") or "structured"),
        source_backend=str(affair_cfg.get("source_backend") or "structured_json"),
        chunk_shard_size=int(affair_cfg.get("chunk_shard_size") or 200),
        chunks_uid=_build_chunks_uid(str(affair_cfg.get("chunks_uid") or "")),
        db_input_key=db_input_key,
    )

    out_dir = Path(cfg.output_dir)
    if not out_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={cfg.output_dir!r}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = out_dir / "chunk_manifest.json"
    stats_path = out_dir / "chunk_stats.json"

    structured_paths = _collect_structured_paths(
        structured_dir=cfg.input_structured_dir,
        content_db=cfg.content_db,
    )
    if not structured_paths:
        raise ValueError("未找到可用于分块的 structured.json 文件。请提供 input_structured_dir 或 content_db。")

    chunk_rows: List[Dict[str, Any]] = []
    for path in structured_paths:
        structured_data = load_structured_data(path)
        chunk_rows.extend(
            build_chunk_entries_from_structured_data(
                structured_data,
                chunk_size=cfg.chunk_size,
                min_chunk_size=cfg.min_chunk_size,
            )
        )

    shard_result = write_chunk_shards(
        chunk_rows,
        output_dir=out_dir,
        chunks_uid=cfg.chunks_uid,
        source_scope=cfg.source_scope,
        source_backend=cfg.source_backend,
        source_doc_count=len(structured_paths),
        max_chunks_per_shard=cfg.chunk_shard_size,
    )
    manifest = shard_result["manifest"]

    if cfg.content_db:
        db_chunk_rows: List[Dict[str, Any]] = []
        shard_size = max(1, int(cfg.chunk_shard_size))
        for index, row in enumerate(chunk_rows):
            shard_index = index // shard_size
            shard_abs_path = ""
            if shard_index < len(manifest.get("shards") or []):
                shard_abs_path = str((manifest.get("shards") or [])[shard_index].get("chunks_abs_path") or "")
            db_chunk_rows.append(
                {
                    "chunk_id": str(row.get("chunk_id") or ""),
                    "chunks_uid": cfg.chunks_uid,
                    "uid_literature": str(row.get("uid_literature") or row.get("uid") or ""),
                    "cite_key": str(row.get("cite_key") or row.get("doc_id") or ""),
                    "shard_abs_path": shard_abs_path,
                    "chunk_index": int(row.get("chunk_index") or index + 1),
                    "chunk_type": str(row.get("chunk_type") or "structured_chunk"),
                    "char_start": int((row.get("char_start") or 0) or 0),
                    "char_end": int((row.get("char_end") or 0) or 0),
                    "text_length": len(str(row.get("text") or "")),
                    "created_at": str(manifest.get("created_at") or ""),
                }
            )
        replace_chunk_set_records(
            Path(str(cfg.content_db)),
            chunk_set_row={
                "chunks_uid": cfg.chunks_uid,
                "source_scope": cfg.source_scope,
                "chunks_abs_path": str(manifest_path),
                "source_backend": cfg.source_backend,
                "chunk_count": int(manifest.get("chunk_count") or len(chunk_rows)),
                "source_doc_count": int(manifest.get("source_doc_count") or len(structured_paths)),
                "created_at": str(manifest.get("created_at") or ""),
                "status": str(manifest.get("status") or "ready"),
            },
            chunk_rows=db_chunk_rows,
        )

    stats = {
        "input_structured_dir": str(cfg.input_structured_dir or ""),
        "content_db": str(cfg.content_db or ""),
        "db_input_key": cfg.db_input_key,
        "output_dir": str(out_dir),
        "source_scope": cfg.source_scope,
        "source_backend": cfg.source_backend,
        "chunks_uid": cfg.chunks_uid,
        "docs": int(len(structured_paths)),
        "chunks": int(len(chunk_rows)),
        "chunk_size": cfg.chunk_size,
        "min_chunk_size": cfg.min_chunk_size,
        "chunk_shard_size": cfg.chunk_shard_size,
        "chunk_manifest_json": str(shard_result["manifest_path"]),
    }
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return [Path(shard_result["manifest_path"]), stats_path, *shard_result["shard_paths"]]


def main() -> None:
    """命令行入口。"""

    import sys

    if len(sys.argv) < 2:
        raise SystemExit("用法：python 解析与分块.py <config_path>")

    for p in execute(Path(sys.argv[1])):
        print(p)


if __name__ == "__main__":
    main()


