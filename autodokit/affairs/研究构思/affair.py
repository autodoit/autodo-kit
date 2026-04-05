"""研究构思事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import load_json_or_py, write_affair_json_result


def ideate_research(topic: str, literature_gaps: list[str], variable_ideas: list[str], target_journal: str) -> dict:
    """把宽泛主题压缩为研究问题与路线图。"""

    questions = [
        f"{topic} 在什么情境下最值得研究？",
        f"{topic} 是否存在可识别的因果机制？",
        f"{topic} 在不同样本或地区是否存在异质性？",
    ]
    return {
        "status": "PASS",
        "mode": "research-ideation",
        "result": {
            "topic": topic,
            "literature_gaps": literature_gaps,
            "variable_ideas": variable_ideas,
            "target_journal": target_journal,
            "research_questions": questions,
            "hypotheses": [f"H{i + 1}: 围绕“{topic}”形成可检验命题。" for i in range(min(3, len(questions)))],
            "roadmap": ["文献检索", "变量设计", "识别策略筛选", "实证分析", "结果写作"],
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = ideate_research(
        topic=str(raw_cfg.get("topic") or ""),
        literature_gaps=list(raw_cfg.get("literature_gaps") or []),
        variable_ideas=list(raw_cfg.get("variable_ideas") or []),
        target_journal=str(raw_cfg.get("target_journal") or ""),
    )
    return write_affair_json_result(raw_cfg, config_path, "research_ideation_result.json", result)
