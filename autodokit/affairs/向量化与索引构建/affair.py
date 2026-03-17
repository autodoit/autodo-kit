"""向量化与索引构建事务（第一版：TF-IDF）。

本事务将 `chunks.jsonl` 向量化并生成可用于检索的基础索引。

第一版选择 TF-IDF 的原因：
- 不依赖外部模型与 API，便于在调试阶段快速闭环。
- 足以支撑“关键词/语义近似检索”的基础能力，为后续接入 embedding 打地基。

输出：
- `tfidf.npz`：稀疏矩阵（行=chunk，列=term）
- `vocab.json`：词表与 ID 映射
- `chunk_meta.jsonl`：chunk_id -> uid/doc_id/meta 的映射
- `vector_manifest.json`：统计与参数回显

Args:
    config_path: 调度器传入配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。

Examples:
    >>> from autodokit.affairs.向量化与索引构建 import execute
    >>> execute(Path('workflows/workflow_010/workflow.json'))
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from autodokit.tools import load_json_or_py


@dataclass
class VectorizeConfig:
    """向量化配置。

    Attributes:
        input_chunks_jsonl: 分块数据路径。
        output_dir: 输出目录。
        vectorizer_type: 向量化器类型，第一版仅支持 tfidf。
        max_features: 词表最大大小。
        ngram_range: ngram 范围，例如 [1,2]。
    """

    input_chunks_jsonl: str
    output_dir: str
    vectorizer_type: str = "tfidf"
    max_features: int = 20000
    ngram_range: List[int] | Tuple[int, int] = (1, 2)


def _iter_chunks(path: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    texts: List[str] = []
    metas: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            texts.append(str(obj.get("text") or ""))
            metas.append(
                {
                    "chunk_id": obj.get("chunk_id"),
                    "uid": obj.get("uid"),
                    "doc_id": obj.get("doc_id"),
                    "meta": obj.get("meta") or {},
                }
            )
    return texts, metas


def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)

    affair_cfg: Dict[str, Any] = dict(raw_cfg)

    ngram_raw = affair_cfg.get("ngram_range") or [1, 2]
    if isinstance(ngram_raw, (list, tuple)) and len(ngram_raw) == 2:
        ngram_range = (int(ngram_raw[0]), int(ngram_raw[1]))
    else:
        ngram_range = (1, 2)

    cfg = VectorizeConfig(
        input_chunks_jsonl=str(affair_cfg.get("input_chunks_jsonl") or ""),
        output_dir=str(affair_cfg.get("output_dir") or ""),
        vectorizer_type=str(affair_cfg.get("vectorizer_type") or "tfidf"),
        max_features=int(affair_cfg.get("max_features") or 20000),
        ngram_range=ngram_range,
    )

    chunks_path = Path(cfg.input_chunks_jsonl)
    if not chunks_path.is_absolute():
        raise ValueError(
            "input_chunks_jsonl 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={cfg.input_chunks_jsonl!r}"
        )

    out_dir = Path(cfg.output_dir)
    if not out_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={cfg.output_dir!r}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    if cfg.vectorizer_type.lower() != "tfidf":
        raise ValueError("第一版仅支持 vectorizer_type=tfidf")

    texts, metas = _iter_chunks(chunks_path)

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "未安装 scikit-learn，无法进行 TF-IDF 向量化。请安装：pip install scikit-learn\n"
            f"原始错误：{exc}"
        ) from exc

    vectorizer = TfidfVectorizer(
        max_features=cfg.max_features,
        ngram_range=tuple(cfg.ngram_range),
        lowercase=False,
    )

    # 关键逻辑说明：
    # - 采用稀疏矩阵落盘；对上万 chunk 也能保持内存可控。
    X = vectorizer.fit_transform(texts)

    try:
        from scipy import sparse  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "未安装 scipy，无法保存稀疏矩阵。请安装：pip install scipy\n"
            f"原始错误：{exc}"
        ) from exc

    tfidf_path = out_dir / "tfidf.npz"
    vocab_path = out_dir / "vocab.json"
    chunk_meta_path = out_dir / "chunk_meta.jsonl"
    manifest_path = out_dir / "vector_manifest.json"

    sparse.save_npz(tfidf_path, X)

    # 关键逻辑说明：
    # scikit-learn 的 vocabulary_ value 可能是 numpy.int64，直接 json.dumps 会失败。
    vocab_clean = {str(k): int(v) for k, v in (vectorizer.vocabulary_ or {}).items()}
    vocab = {"vocabulary_": vocab_clean}
    vocab_path.write_text(json.dumps(vocab, ensure_ascii=False, indent=2), encoding="utf-8")

    with chunk_meta_path.open("w", encoding="utf-8") as f:
        for m in metas:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    manifest = {
        "input_chunks_jsonl": str(chunks_path),
        "output_dir": str(out_dir),
        "vectorizer_type": "tfidf",
        "max_features": cfg.max_features,
        "ngram_range": list(cfg.ngram_range),
        "chunks": int(X.shape[0]),
        "dim": int(X.shape[1]),
        "tfidf_nnz": int(X.nnz),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return [tfidf_path, vocab_path, chunk_meta_path, manifest_path]


def main() -> None:
    """命令行入口。"""

    import sys

    if len(sys.argv) < 2:
        raise SystemExit("用法：python 向量化与索引构建.py <config_path>")

    for p in execute(Path(sys.argv[1])):
        print(p)


if __name__ == "__main__":
    main()

