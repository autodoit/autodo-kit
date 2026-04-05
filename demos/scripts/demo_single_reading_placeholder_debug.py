"""单篇精读占位引文调试脚本。

该脚本用于重新验证 `单篇精读` 事务的无 LLM 路径与占位引文插入流程：
- 自动从测试用文献目录挑选若干篇 Markdown 文献；
- 提取参考文献区文本，作为 `reference_lines` 调试输入；
- 生成临时 `structured.json` 与 `content.db`；
- 调用 `autodokit.affairs.单篇精读.affair.execute`；
- 打印输出文件路径与文献库写入结果。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from autodokit.affairs.单篇精读.affair import execute
from autodokit.tools.bibliodb_sqlite import persist_reference_main_table
from autodokit.tools.pdf_structured_data_tools import build_structured_data_payload


def _repo_root() -> Path:
    """返回仓库根目录。

    Returns:
        仓库根目录绝对路径。

    Raises:
        FileNotFoundError: 当仓库根目录不存在时抛出。

    Examples:
        >>> _repo_root().name
        'autodo-kit'
    """

    root = Path(__file__).resolve().parents[2]
    if not root.exists():
        raise FileNotFoundError(f"未找到仓库根目录：{root}")
    return root


def _sample_docs_root() -> Path:
    """返回测试用文献目录。

    Returns:
        测试文献根目录绝对路径。

    Raises:
        FileNotFoundError: 当测试文献目录不存在时抛出。
    """

    root = _repo_root() / "demos" / "data" / "文献原文数据" / "测试用文献" / "files"
    if not root.exists():
        raise FileNotFoundError(f"未找到测试文献目录：{root}")
    return root


def _debug_root() -> Path:
    """返回调试输出目录。

    Returns:
        调试输出目录绝对路径。
    """

    root = _repo_root() / "temps" / "single_reading_debug_recheck"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _extract_reference_lines(text: str) -> list[str]:
    """从文献 Markdown 文本中提取参考文献区行文本。

    Args:
        text: 文献 Markdown 内容。

    Returns:
        参考文献行文本列表。
    """

    lines = [line.strip() for line in str(text or "").splitlines()]
    start_idx = -1
    for idx, line in enumerate(lines):
        normalized = line.lower().strip("# *")
        if normalized in {"references", "reference", "参考文献"}:
            start_idx = idx + 1
            break

    if start_idx < 0:
        return []

    reference_lines: list[str] = []
    for line in lines[start_idx:]:
        if not line:
            continue
        if line.startswith("#"):
            break
        if len(line) < 10:
            continue
        reference_lines.append(line)
    return reference_lines


def _collect_sample_articles(limit: int = 3) -> list[Path]:
    """收集若干测试用文献 Markdown 文件。

    Args:
        limit: 最多收集的文献数。

    Returns:
        文献文件路径列表。
    """

    candidates = sorted(_sample_docs_root().rglob("*.md"))
    return candidates[:limit]


def _fallback_reference_lines() -> list[str]:
    """返回用于调试的兜底参考文献行。

    这些条目用于在自动提取不到参考文献时，仍能验证占位引文插入流程。

    Returns:
        参考文献行列表。
    """

    return [
        "Author A. 2020. Generic Research Example One.",
        "Author B. 2021. Generic Research Example Two.",
        "Author C. 2022. Generic Research Example Three.",
    ]


def _build_structured_json(record: dict[str, Any], output_path: Path) -> Path:
    """写出调试用 structured.json。

    Args:
        record: 单篇文献记录。
        output_path: 输出路径。

    Returns:
        输出文件路径。
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_structured_data_payload(
        pdf_path=(output_path.parent / f"{record['doc_id']}.pdf").resolve(),
        backend="local_pipeline_v2",
        backend_family="local",
        task_type="full_fine_grained",
        full_text=str(record.get("text") or ""),
        extract_error=None,
        text_meta={"backend": "markdown_debug_source"},
        uid_literature=str(record.get("uid") or record.get("doc_id") or ""),
        cite_key=str(record.get("doc_id") or record.get("uid") or ""),
        title=str(record.get("title") or record.get("doc_id") or "未命名"),
        year=str(record.get("year") or ""),
        references=[{"raw_text": line} for line in record.get("reference_lines") or []],
        capabilities={"text": {"enabled": True, "disabled_reason": None}},
    )
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _build_sample_dataset() -> dict[str, Any]:
    """构建调试数据集。

    Returns:
        包含 docs.jsonl 路径、bibliography_csv 路径和配置项的字典。
    """

    docs: list[dict[str, Any]] = []
    reference_lines: list[str] = []

    for index, md_path in enumerate(_collect_sample_articles(limit=3), start=1):
        text = md_path.read_text(encoding="utf-8")
        reference_lines.extend(_extract_reference_lines(text))
        docs.append(
            {
                "uid": int(md_path.parent.name) if md_path.parent.name.isdigit() else index,
                "doc_id": md_path.stem,
                "title": md_path.stem,
                "year": "",
                "text": text,
            }
        )

    dedup_reference_lines: list[str] = []
    seen: set[str] = set()
    for line in reference_lines:
        if line not in seen:
            seen.add(line)
            dedup_reference_lines.append(line)

    if not dedup_reference_lines:
        dedup_reference_lines = _fallback_reference_lines()

    debug_root = _debug_root()
    structured_dir = debug_root / "structured"
    content_db = debug_root / "content.db"
    output_dir = debug_root / "output"

    target_uid = docs[0]["uid"] if docs else 1
    target_structured_json = structured_dir / f"{docs[0]['doc_id']}.structured.json"

    literature_rows: list[dict[str, Any]] = []
    for doc in docs:
        doc["reference_lines"] = dedup_reference_lines
        structured_path = _build_structured_json(doc, structured_dir / f"{doc['doc_id']}.structured.json")
        literature_rows.append(
            {
                "uid_literature": str(doc["uid"]),
                "cite_key": str(doc["doc_id"]),
                "title": str(doc["title"]),
                "year": str(doc.get("year") or ""),
                "structured_abs_path": str(structured_path.resolve()),
            }
        )

    persist_reference_main_table(pd.DataFrame(literature_rows), content_db)

    return {
        "content_db": content_db,
        "target_structured_json": target_structured_json,
        "output_dir": output_dir,
        "reference_lines": dedup_reference_lines,
        "sample_count": len(docs),
        "target_uid": target_uid,
    }


def run_debug() -> list[Path]:
    """执行单篇精读调试。

    Returns:
        事务写出的文件路径列表。
    """

    payload = _build_sample_dataset()
    config = {
        "input_structured_json": str(payload["target_structured_json"].resolve()),
        "content_db": str(payload["content_db"].resolve()),
        "output_dir": str(payload["output_dir"].resolve()),
        "uid": int(payload["target_uid"]),
        "use_llm": False,
        "max_chars": 12000,
        "insert_placeholders_from_references": True,
        "reference_lines": payload["reference_lines"],
    }

    config_path = _debug_root() / "single_reading_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    outputs = execute(config_path)
    print("[调试配置]")
    print(f"- input_structured_json: {payload['target_structured_json']}")
    print(f"- content_db: {payload['content_db']}")
    print(f"- sample_count: {payload['sample_count']}")
    print(f"- target_uid: {payload['target_uid']}")
    print(f"- reference_lines: {len(payload['reference_lines'])}")
    print("[输出文件]")
    for path in outputs:
        print(f"- {path}")
    return outputs


def main() -> None:
    """脚本入口。"""

    run_debug()


if __name__ == "__main__":
    main()
