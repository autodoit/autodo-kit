"""单篇精读笔记（P1，占位可运行版）。

本脚本用于对单篇文献生成“精读笔记”。它假设你已经完成 P0：
- `pdf_to_docs` 产出 `docs.jsonl`
- `解析与分块` 产出 `chunks.jsonl`

本版实现保持简单：
- 从 `docs.jsonl` 读取目标文献的全文文本（优先）
- 拼接一个较短的提示词
- 调用阿里百炼（DashScope）生成笔记
- 将结果写入 output_dir 下的 markdown 文件

注意：
- 不在代码中写任何 key；请通过环境变量 `DASHSCOPE_API_KEY` 或本地文件注入。
- 本脚本不做“复杂的容错/重试/降级”。缺依赖就让用户自行安装。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

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
class SinglePaperConfig:
    """单篇精读配置。

    Attributes:
        input_docs_jsonl: docs.jsonl 路径。
        output_dir: 输出目录。
        uid: 目标文献 uid（与文献数据表一致）。
        doc_id: 可选，目标文献 doc_id（若提供则优先使用）。
        model: 大模型名称。
        system_prompt: 可选系统提示词。
        user_prompt_template: 用户提示词模板（可用 {title}/{year}/{text} 占位）。
        max_chars: 为避免输入过长，本版按字符截断全文（不是严格 token）。
    """

    input_docs_jsonl: str
    output_dir: str
    uid: Optional[int] = None
    doc_id: Optional[str] = None
    model: str = "qwen-plus"
    system_prompt: str = "你是一名严谨的学术研究助理。请用中文输出，结构清晰。"
    user_prompt_template: str = (
        "请对下面这篇论文做单篇精读笔记。\n"
        "要求：\n"
        "1) 用要点列出研究问题、方法、数据、主要结论、贡献与局限；\n"
        "2) 给出3-5条可复用的‘引用式表述’（但不要杜撰原文不存在的结论）；\n"
        "3) 最后给出我进一步阅读时应关注的关键段落线索。\n\n"
        "论文信息：{title}（{year}）\n\n"
        "正文（可能较长，已截断）：\n{text}\n"
    )
    max_chars: int = 12000


def _read_target_doc(docs_jsonl: Path, *, uid: Optional[int], doc_id: Optional[str]) -> Dict[str, Any]:
    """从 docs.jsonl 读取目标文献。

    Args:
        docs_jsonl: docs.jsonl 路径。
        uid: 目标 uid。
        doc_id: 目标 doc_id。

    Returns:
        匹配到的文献对象（包含 text/title/year 等字段，字段不保证齐全）。

    Raises:
        ValueError: 未找到匹配文献。
    """

    with docs_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            if doc_id and str(obj.get("doc_id") or "") == str(doc_id):
                return obj
            if uid is not None and obj.get("uid") is not None and int(obj.get("uid")) == int(uid):
                return obj

    raise ValueError("未在 docs.jsonl 中找到目标文献。请检查 uid/doc_id 配置。")


def execute(config_path: Path) -> List[Path]:
    raw_cfg = load_json_or_py(config_path)

    merged: Dict[str, Any] = dict(raw_cfg)
    model_route = merged.get("model_route") if isinstance(merged.get("model_route"), dict) else {}

    cfg = SinglePaperConfig(
        input_docs_jsonl=str(merged.get("input_docs_jsonl") or ""),
        output_dir=str(merged.get("output_dir") or ""),
        uid=int(merged["uid"]) if merged.get("uid") is not None else None,
        doc_id=str(merged.get("doc_id")) if merged.get("doc_id") else None,
        model=str(merged.get("model") or "qwen-plus"),
        system_prompt=str(merged.get("system_prompt") or "").strip() or SinglePaperConfig.system_prompt,
        user_prompt_template=str(merged.get("user_prompt_template") or "").strip()
        or SinglePaperConfig.user_prompt_template,
        max_chars=int(merged.get("max_chars") or 12000),
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

    doc = _read_target_doc(docs_path, uid=cfg.uid, doc_id=cfg.doc_id)

    title = str(doc.get("title") or doc.get("meta", {}).get("title") or "未命名")
    year = str(doc.get("year") or doc.get("meta", {}).get("year") or "")
    text = str(doc.get("text") or "")
    if cfg.max_chars and len(text) > cfg.max_chars:
        text = text[: cfg.max_chars]

    prompt = cfg.user_prompt_template.format(title=title, year=year, text=text)

    route_hints: Dict[str, Any] = dict(model_route)
    route_hints.setdefault("input_chars", len(text))

    llm_cfg = load_aliyun_llm_config(
        model=cfg.model,
        affair_name="单篇精读",
        route_hints=route_hints,
    )
    client = AliyunDashScopeClient(llm_cfg)
    answer = client.generate_text(prompt=prompt, system=cfg.system_prompt)

    safe_uid = str(cfg.uid) if cfg.uid is not None else (cfg.doc_id or "doc")
    out_path = out_dir / f"single_reading_{safe_uid}.md"
    out_path.write_text(
        "\n".join(
            [
                f"# 单篇精读笔记：{title}",
                "",
                f"- uid/doc_id: {safe_uid}",
                f"- year: {year}",
                f"- model: {llm_cfg.model}",
                f"- backend: {llm_cfg.sdk_backend}",
                "",
                "---",
                "",
                answer,
                "",
            ]
        ),
        encoding="utf-8",
    )

    return [out_path]

