"""从 PDF 提取可检索文本（通用说明）。

本事务的目标（用一句话说明）：
- 把选定的论文 PDF 自动转换为纯文本文件，使之可被搜索和喂入模型或人工快速阅读。

为什么需要它（使用角度，通俗）：
- 人工打开 PDF、复制粘贴正文是重复且低效的工作；该事务自动做这件事情并记录解析失败的文件供人工复核。

本事务做什么（技术摘要，便于理解）：
- 读取主表（或候选清单），根据每条记录的 `pdf_path` 提取文本（逐页），并把每篇的文本写为一行 JSON（docs.jsonl）。
- 记录解析失败的案例（文件不存在、空文本或解析错误），便于后续人工处理。

输入（必需）：
- `input_table_csv`：主表（含 pdf_path 字段）。
- 可选：`only_candidates_csv`：若只对候选清单的 PDF 提取，则指定该文件。

输出（必需产物）：
- `docs.jsonl`：每行一个 JSON，包含 doc_id、uid、text、meta 等字段。
- `pdf_extract_failures.csv`：记录解析失败的项。
- `doc_manifest.json`：本次运行的统计与配置回显。

在自动化流程中的位置（示例）：
- 场景：当你决定要精读一批候选 PDF 时，运行本事务可把全部 PDF 转为可全文搜索的文本，随后用查找或索引工具定位关键段落。

何时用（简短建议）：
- 在你已经有 PDF 文件并且希望批量抽取全文以便后续自动化处理或人工快速检索时使用。

运行示例（项目 `workflow_010`）：
- 运行整个 flow（含预筛选、提取与分块）:

  py main.py

- 单独运行本事务：

    py -c "from pathlib import Path; from autodo-kit.affairs.从PDF提取可检索文本 import execute; execute(Path('workflows/workflow_010/workflow.json'))"

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表（docs.jsonl、failures.csv、manifest.json）。

Examples:
    >>> from pathlib import Path
    >>> from autodokit.affairs.从PDF提取可检索文本 import execute
    >>> execute(Path('workflows/workflow_010/workflow.json'))
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from autodokit.tools import load_json_or_py


@dataclass
class PdfToDocsConfig:
    """PDF 提取配置。

    Attributes:
        input_table_csv: 文献主表路径。
        only_candidates_csv: 可选，候选清单 CSV（含 uid 列）。若提供则仅处理候选。
        pdf_path_field: 主表中存放 PDF 路径的字段名。
        output_dir: 输出目录。
        max_pages: 最多提取的页数；None 表示不限制。
        limit: 调试用，仅处理前 N 篇。
    """

    input_table_csv: str
    only_candidates_csv: str | None = None
    pdf_path_field: str = "pdf_path"
    output_dir: str = "output"
    max_pages: int | None = 50
    limit: int | None = None


def _iter_uids_from_candidates(path: Path) -> List[int]:
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "uid" not in df.columns:
        raise ValueError(f"候选清单缺少 uid 列：{path}")
    out: List[int] = []
    for x in df["uid"].tolist():
        try:
            out.append(int(x))
        except Exception:
            continue
    return out


def _extract_pdf_text(pdf_path: Path, *, max_pages: int | None) -> str:
    """用 PyMuPDF 提取 PDF 文本。"""

    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "未安装 PyMuPDF（fitz）。请安装：pip install pymupdf\n"
            f"原始错误：{exc}"
        ) from exc

    doc = fitz.open(str(pdf_path))
    texts: List[str] = []
    n = doc.page_count
    page_limit = n if max_pages is None else min(n, int(max_pages))

    # 关键逻辑说明：
    # - 逐页抽取可以避免一次性读取导致内存暴涨。
    # - 未来若需要更高质量，可改为 layout-aware 的提取策略。
    for i in range(page_limit):
        page = doc.load_page(i)
        texts.append(page.get_text("text"))

    doc.close()
    return "\n".join(texts).strip()


def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)

    affair_cfg: Dict[str, Any] = dict(raw_cfg)

    cfg = PdfToDocsConfig(
        input_table_csv=str(affair_cfg.get("input_table_csv") or ""),
        only_candidates_csv=str(affair_cfg.get("only_candidates_csv") or "") or None,
        pdf_path_field=str(affair_cfg.get("pdf_path_field") or "pdf_path"),
        output_dir=str(affair_cfg.get("output_dir") or ""),
        max_pages=affair_cfg.get("max_pages"),
        limit=affair_cfg.get("limit"),
    )

    input_table_csv = Path(cfg.input_table_csv)
    if not input_table_csv.is_absolute():
        raise ValueError(
            "input_table_csv 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={cfg.input_table_csv!r}"
        )

    out_dir = Path(cfg.output_dir)
    if not out_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={cfg.output_dir!r}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    table = pd.read_csv(input_table_csv, encoding="utf-8-sig")
    if "uid" in table.columns:
        table = table.set_index("uid", drop=False)

    only_uids: Optional[set[int]] = None
    if cfg.only_candidates_csv:
        cand_path = Path(cfg.only_candidates_csv)
        if not cand_path.is_absolute():
            raise ValueError(
                "only_candidates_csv 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
                f"或检查 workspace_root 配置。当前值={cfg.only_candidates_csv!r}"
            )
        if cand_path.exists():
            only_uids = set(_iter_uids_from_candidates(cand_path))

    docs_path = out_dir / "docs.jsonl"
    failures_path = out_dir / "pdf_extract_failures.csv"
    manifest_path = out_dir / "doc_manifest.json"

    wrote_docs = 0
    failures: List[Dict[str, Any]] = []

    with docs_path.open("w", encoding="utf-8") as f:
        for idx, (_uid, row) in enumerate(table.iterrows()):
            if cfg.limit is not None and wrote_docs >= int(cfg.limit):
                break

            try:
                uid = int(row.get("uid")) if pd.notna(row.get("uid")) else int(str(_uid))
            except Exception:
                uid = int(str(_uid))

            if only_uids is not None and uid not in only_uids:
                continue

            pdf_raw = row.get(cfg.pdf_path_field)
            pdf_path = Path(str(pdf_raw)) if pd.notna(pdf_raw) and str(pdf_raw).strip() else None
            if not pdf_path:
                failures.append({"uid": uid, "pdf_path": "", "error_type": "missing_pdf_path", "error_message": "缺少 pdf_path"})
                continue

            # 约定：事务不做任何路径转换；pdf_path 必须已是绝对路径。
            if not pdf_path.is_absolute():
                failures.append({
                    "uid": uid,
                    "pdf_path": str(pdf_raw),
                    "error_type": "invalid_pdf_path",
                    "error_message": "pdf_path 必须为绝对路径（应由调度层预处理）",
                })
                continue

            if not pdf_path.exists():
                failures.append({"uid": uid, "pdf_path": str(pdf_path), "error_type": "pdf_not_found", "error_message": "PDF 文件不存在"})
                continue

            try:
                text = _extract_pdf_text(pdf_path, max_pages=cfg.max_pages)
                if not text:
                    failures.append({"uid": uid, "pdf_path": str(pdf_path), "error_type": "empty_text", "error_message": "提取文本为空"})
                    continue
            except Exception as exc:
                failures.append({"uid": uid, "pdf_path": str(pdf_path), "error_type": "extract_error", "error_message": str(exc)})
                continue

            doc = {
                "doc_id": f"uid:{uid}",
                "uid": uid,
                "source_pdf_path": str(pdf_path),
                "text": text,
                "meta": {
                    "title": row.get("title"),
                    "author": row.get("author"),
                    "year": row.get("year"),
                    "keywords": row.get("keywords"),
                },
            }
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
            wrote_docs += 1

    pd.DataFrame(failures).to_csv(failures_path, index=False, encoding="utf-8-sig")

    manifest = {
        "input_table_csv": str(input_table_csv),
        "only_candidates_csv": cfg.only_candidates_csv,
        "output_dir": str(out_dir),
        "docs_jsonl": str(docs_path),
        "failures_csv": str(failures_path),
        "docs_count": int(wrote_docs),
        "failures_count": int(len(failures)),
        "max_pages": cfg.max_pages,
        "limit": cfg.limit,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return [docs_path, failures_path, manifest_path]


def main() -> None:
    """命令行入口。"""

    import sys

    if len(sys.argv) < 2:
        raise SystemExit("用法：python 从PDF提取可检索文本.py <config_path>")

    for p in execute(Path(sys.argv[1])):
        print(p)


if __name__ == "__main__":
    main()

