"""综述草稿生成（P1，占位可运行版）。

本脚本用于基于若干篇候选文献生成一个“综述草稿”。

本版实现保持简单：
- 从 `matrix.jsonl`（推荐）或 `docs.jsonl`（兜底）读取材料
- 让模型按给定的提纲输出 markdown 草稿
- 输出到 output_dir 下的 `review_draft.md`

为什么优先基于 matrix：
- 先把每篇文献抽取成统一字段，综述阶段 prompt 更短、更稳定。

Args:
    config_path: 调度器传入的配置文件路径。

Returns:
    写出的文件 Path 列表。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from autodokit.tools.llm_clients import AliyunDashScopeClient, load_aliyun_llm_config
from autodokit.tools import load_json_or_py


@dataclass
class ReviewDraftConfig:
    """综述草稿配置。

    Attributes:
        input_matrix_jsonl: 文献矩阵 jsonl（推荐）。
        input_docs_jsonl: 若没有矩阵文件，可直接用 docs.jsonl（会导致 prompt 更长）。
        output_dir: 输出目录。
        outline: 综述提纲（字符串或列表）。
        title: 综述标题。
        model: 模型名称。
        system_prompt: 系统提示词。
        max_items: 最多使用多少篇文献（避免 prompt 太长）。
    """

    input_matrix_jsonl: Optional[str] = None
    input_docs_jsonl: Optional[str] = None
    output_dir: str = "output"
    outline: Any = None
    title: str = "综述草稿"
    model: str = "qwen-plus"
    system_prompt: str = "你是一名严谨的学术研究助理。请用中文输出，结构清晰，避免杜撰。"
    max_items: int = 30


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def _normalize_outline(outline: Any) -> str:
    if outline is None:
        return (
            "1. 研究背景与问题定义\n"
            "2. 核心概念与测度方法\n"
            "3. 主要研究脉络与代表性结论（按主题分组）\n"
            "4. 分歧点与争议\n"
            "5. 研究不足与未来方向\n"
        )
    if isinstance(outline, str):
        return outline.strip()
    if isinstance(outline, list):
        return "\n".join(str(x) for x in outline if str(x).strip())
    return str(outline)


def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)

    merged: Dict[str, Any] = dict(raw_cfg)
    model_route = merged.get("model_route") if isinstance(merged.get("model_route"), dict) else {}

    cfg = ReviewDraftConfig(
        input_matrix_jsonl=str(merged.get("input_matrix_jsonl")) if merged.get("input_matrix_jsonl") else None,
        input_docs_jsonl=str(merged.get("input_docs_jsonl")) if merged.get("input_docs_jsonl") else None,
        output_dir=str(merged.get("output_dir") or "output"),
        outline=merged.get("outline"),
        title=str(merged.get("title") or "综述草稿"),
        model=str(merged.get("model") or "qwen-plus"),
        system_prompt=str(merged.get("system_prompt") or "").strip() or ReviewDraftConfig.system_prompt,
        max_items=int(merged.get("max_items") or 30),
    )

    out_dir = Path(cfg.output_dir)
    if not out_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
            f"或检查 workspace_root 配置。当前值={cfg.output_dir!r}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    materials: List[Dict[str, Any]] = []
    source_note = ""

    if cfg.input_matrix_jsonl:
        p = Path(cfg.input_matrix_jsonl)
        if not p.is_absolute():
            raise ValueError(
                "input_matrix_jsonl 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
                f"或检查 workspace_root 配置。当前值={cfg.input_matrix_jsonl!r}"
            )
        materials = _read_jsonl(p)
        source_note = f"matrix: {p}"
    elif cfg.input_docs_jsonl:
        p = Path(cfg.input_docs_jsonl)
        if not p.is_absolute():
            raise ValueError(
                "input_docs_jsonl 必须为绝对路径：请确认 main.py 已启用统一路径解析，"
                f"或检查 workspace_root 配置。当前值={cfg.input_docs_jsonl!r}"
            )
        # docs 比较长，这里只取标题/年份/摘要（如果有）或前几千字，避免 prompt 爆炸
        docs = _read_jsonl(p)
        for d in docs[: cfg.max_items]:
            materials.append(
                {
                    "uid": d.get("uid"),
                    "title": d.get("title") or d.get("meta", {}).get("title"),
                    "year": d.get("year") or d.get("meta", {}).get("year"),
                    "abstract": d.get("abstract") or d.get("meta", {}).get("abstract"),
                    "text_head": str(d.get("text") or "")[:2000],
                }
            )
        source_note = f"docs: {p}"
    else:
        raise ValueError("请至少提供 input_matrix_jsonl 或 input_docs_jsonl")

    if cfg.max_items and len(materials) > cfg.max_items:
        materials = materials[: cfg.max_items]

    outline_text = _normalize_outline(cfg.outline)
    materials_text = json.dumps(materials, ensure_ascii=False, indent=2)

    prompt = (
        f"请基于下面的文献材料生成一份中文综述草稿（markdown）。\n"
        f"要求：\n"
        f"- 严禁杜撰：只能基于材料中出现的信息做归纳；不确定的地方用‘可能/尚不明确’表述。\n"
        f"- 尽量按主题组织，而不是逐篇复述。\n"
        f"- 在关键结论段落后面用括号标注引用 uid 列表，例如： (uid: 12, 35)\n\n"
        f"综述标题：{cfg.title}\n\n"
        f"提纲：\n{outline_text}\n\n"
        f"材料（JSON）：\n{materials_text}\n"
    )

    route_hints: Dict[str, Any] = dict(model_route)
    route_hints.setdefault("input_chars", len(materials_text))

    llm_cfg = load_aliyun_llm_config(
        model=cfg.model,
        affair_name="综述草稿生成",
        route_hints=route_hints,
    )
    client = AliyunDashScopeClient(llm_cfg)
    draft = client.generate_text(prompt=prompt, system=cfg.system_prompt, max_tokens=4096)

    out_path = out_dir / "review_draft.md"
    out_path.write_text(
        "\n".join(
            [
                f"# {cfg.title}",
                "",
                f"- source: {source_note}",
                f"- model: {llm_cfg.model}",
                f"- backend: {llm_cfg.sdk_backend}",
                "",
                "---",
                "",
                draft,
                "",
            ]
        ),
        encoding="utf-8",
    )

    return [out_path]

