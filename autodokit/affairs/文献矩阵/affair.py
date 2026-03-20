"""批量文献矩阵（P1，占位可运行版）。

本脚本用于生成“文献矩阵”表格：对每篇文献抽取同一组字段（研究问题/方法/数据/结论/贡献/局限）。

本版实现保持简单：
- 从 `docs.jsonl` 读取前 N 篇（或指定 uid 列表）
- 对每篇文献单独调用一次大模型，得到结构化 YAML/JSON 风格文本
- 汇总写出一个 `matrix.jsonl`（一行一篇）和一个简易 `matrix.csv`

这样做的好处：
- 实现简单，便于逐步迭代。
- 不依赖复杂的 Map-Reduce 框架或向量检索。

Args:
    config_path: 调度器传入的配置文件路径。

Returns:
    写出的文件 Path 列表。
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from autodokit.core.template_affair import TemplateAffairBase
from autodokit.tools.llm_clients import AliyunDashScopeClient, load_aliyun_llm_config


@dataclass
class MatrixConfig:
    """文献矩阵配置。

    Attributes:
        input_docs_jsonl: docs.jsonl 路径。
        output_dir: 输出目录。
        limit: 处理前 N 篇（None 表示全量）。
        uids: 可选，只处理这些 uid。
        model: 模型名称。
        system_prompt: 系统提示词。
        user_prompt_template: 用户提示词模板。
        max_chars: 每篇正文截断字符数。
    """

    input_docs_jsonl: str
    output_dir: str
    limit: Optional[int] = 20
    uids: Optional[List[str]] = None
    model: str = "qwen-plus"
    system_prompt: str = "你是一名严谨的学术研究助理。请用中文输出，结构清晰。"
    user_prompt_template: str = (
        "你需要为文献矩阵抽取字段，并用 JSON 输出。\n"
        "只输出 JSON，不要任何额外解释。字段如下：\n"
        "title, year, research_question, method, data, findings, contribution, limitation, keywords\n\n"
        "论文信息：{title}（{year}）\n\n"
        "正文（可能较长，已截断）：\n{text}\n"
    )
    max_chars: int = 8000


def _iter_docs(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def _as_uid_list(v: Any) -> Optional[List[str]]:
    if v is None:
        return None
    if isinstance(v, list):
        out: List[str] = []
        for x in v:
            if x is None:
                continue
            uid_text = str(x).strip()
            if uid_text:
                out.append(uid_text)
        return out
    return None


def _run_literature_matrix(*, merged: Dict[str, Any]) -> List[Path]:
    """执行文献矩阵核心业务。

    Args:
        merged: 已合并配置字典。

    Returns:
        写出的文件路径列表。
    """

    model_route = merged.get("model_route") if isinstance(merged.get("model_route"), dict) else {}

    cfg = MatrixConfig(
        input_docs_jsonl=str(merged.get("input_docs_jsonl") or ""),
        output_dir=str(merged.get("output_dir") or ""),
        limit=int(merged["limit"]) if merged.get("limit") is not None else None,
        uids=_as_uid_list(merged.get("uids")),
        model=str(merged.get("model") or "qwen-plus"),
        system_prompt=str(merged.get("system_prompt") or "").strip() or MatrixConfig.system_prompt,
        user_prompt_template=str(merged.get("user_prompt_template") or "").strip() or MatrixConfig.user_prompt_template,
        max_chars=int(merged.get("max_chars") or 8000),
    )

    docs_path = Path(cfg.input_docs_jsonl)
    if not docs_path.is_absolute():
        raise ValueError(
            "input_docs_jsonl 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={cfg.input_docs_jsonl!r}"
        )

    out_dir = Path(cfg.output_dir)
    if not out_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={cfg.output_dir!r}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    docs = _iter_docs(docs_path)

    if cfg.uids:
        want = set(str(x).strip() for x in cfg.uids)
        docs = [d for d in docs if d.get("uid") is not None and str(d.get("uid")).strip() in want]

    if cfg.limit is not None:
        docs = docs[: int(cfg.limit)]

    route_hints: Dict[str, Any] = dict(model_route)
    route_hints.setdefault("input_chars", cfg.max_chars)

    llm_cfg = load_aliyun_llm_config(
        model=cfg.model,
        affair_name="文献矩阵",
        route_hints=route_hints,
    )
    client = AliyunDashScopeClient(llm_cfg)

    matrix_jsonl = out_dir / "matrix.jsonl"
    matrix_csv = out_dir / "matrix.csv"

    rows: List[Dict[str, Any]] = []
    with matrix_jsonl.open("w", encoding="utf-8") as fj:
        for doc in docs:
            title = str(doc.get("title") or doc.get("meta", {}).get("title") or "未命名")
            year = str(doc.get("year") or doc.get("meta", {}).get("year") or "")
            text = str(doc.get("text") or "")
            if cfg.max_chars and len(text) > cfg.max_chars:
                text = text[: cfg.max_chars]

            prompt = cfg.user_prompt_template.format(title=title, year=year, text=text)
            answer = client.generate_text(prompt=prompt, system=cfg.system_prompt)

            # 为什么这样做：让模型直接输出 JSON，脚本只做最小解析；解析失败也保留原文方便人工修订。
            record: Dict[str, Any]
            try:
                record = json.loads(answer)
            except Exception:
                record = {
                    "title": title,
                    "year": year,
                    "raw": answer,
                }

            record.setdefault("uid", doc.get("uid"))
            fj.write(json.dumps(record, ensure_ascii=False) + "\n")
            rows.append(record)

    # 写 CSV：字段固定，缺失填空。
    fieldnames = [
        "uid",
        "title",
        "year",
        "research_question",
        "method",
        "data",
        "findings",
        "contribution",
        "limitation",
        "keywords",
    ]

    with matrix_csv.open("w", encoding="utf-8-sig", newline="") as fc:
        w = csv.DictWriter(fc, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

    return [matrix_jsonl, matrix_csv]


class LiteratureMatrixTemplateAffair(TemplateAffairBase):
    """文献矩阵模板事务实现。"""

    def __init__(self) -> None:
        """初始化文献矩阵模板事务。"""

        super().__init__(affair_name="文献矩阵")

    def run_business(self, *, config: Dict[str, Any], workspace_root: Path | None) -> List[Path]:
        """执行文献矩阵业务。

        Args:
            config: 事务配置。
            workspace_root: 工作区根目录（当前未使用）。

        Returns:
            写出的文件路径列表。
        """

        _ = workspace_root
        return _run_literature_matrix(merged=dict(config))


def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """事务入口：执行文献矩阵。

    Args:
        config_path: 调度器传入配置路径。
        workspace_root: 工作区根目录。

    Returns:
        写出的文件路径列表。
    """

    affair = LiteratureMatrixTemplateAffair()
    return affair.execute(config_path=config_path, workspace_root=workspace_root)

