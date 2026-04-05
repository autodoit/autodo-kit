"""M1-M3 研究流程最小样例脚本。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from autodokit.tools import (
    allocate_reading_batches,
    build_candidate_readable_view,
    build_candidate_view_index,
    build_research_trajectory,
    extract_review_candidates,
    innovation_feasibility_score,
)


def build_demo_root() -> Path:
    """返回 demo 工作目录。

    Returns:
        demo 输出根目录。
    """

    demo_root = Path(__file__).resolve().parents[1] / "output" / "demo_research_workflow_m1_m3"
    demo_root.mkdir(parents=True, exist_ok=True)
    return demo_root


def build_sample_literature_table() -> pd.DataFrame:
    """构造最小文献主表样例。

    Returns:
        文献主表 DataFrame。
    """

    return pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "title": "Digital Finance Review",
                "first_author": "Wang",
                "year": "2024",
                "keywords": "review;digital finance",
                "abstract": "A review article for digital finance.",
                "entry_type": "journal",
                "source": "CNKI",
            },
            {
                "uid_literature": "lit-002",
                "title": "AI and Innovation",
                "first_author": "Li",
                "year": "2023",
                "keywords": "innovation;AI",
                "abstract": "An empirical paper.",
                "entry_type": "journal",
                "source": "CNKI",
            },
        ]
    )


def run_tools_demo(*, demo_root: Path) -> Dict[str, Any]:
    """运行工具级最小样例。

    Args:
        demo_root: demo 输出目录。

    Returns:
        工具级结果摘要。
    """

    literature_table = build_sample_literature_table()
    candidate_index = build_candidate_view_index(
        [
            {"uid_literature": "lit-001", "score": 95, "reason": "综述优先"},
            {"uid_literature": "lit-002", "score": 84, "reason": "主题相关"},
        ],
        source_round="round_01",
        source_affair="review_candidate_views",
    )
    readable_view = build_candidate_readable_view(candidate_index, literature_table)
    review_view = extract_review_candidates(readable_view)
    reading_batches = allocate_reading_batches(candidate_index, batch_size=1, review_uid_set=review_view["uid_literature"].tolist())
    trajectory = build_research_trajectory(readable_view.to_dict(orient="records"), topic="数字金融")
    innovation_score = innovation_feasibility_score(
        {
            "innovation_uid": "inn-demo-001",
            "title": "数字金融促进企业创新",
            "method_family": "双重差分",
            "scenario": "制造业企业",
            "data_source": "上市公司面板",
            "output_form": "机制识别结果",
        }
    )

    readable_view.to_csv(demo_root / "candidate_pool_readable.csv", index=False, encoding="utf-8-sig")
    reading_batches.to_csv(demo_root / "reading_batches.csv", index=False, encoding="utf-8-sig")
    (demo_root / "research_trajectory.json").write_text(json.dumps(trajectory, ensure_ascii=False, indent=2), encoding="utf-8")
    (demo_root / "innovation_score.json").write_text(json.dumps(innovation_score, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "candidate_count": len(candidate_index),
        "review_count": len(review_view),
        "batch_count": int(reading_batches["batch_id"].nunique()),
        "trajectory_items": trajectory["item_count"],
        "innovation_recommendation": innovation_score["recommendation"],
    }


def _write_config(config_path: Path, payload: Dict[str, Any]) -> None:
    """写入事务配置文件。

    Args:
        config_path: 配置文件路径。
        payload: 配置内容。

    Returns:
        None
    """

    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_affairs_demo(*, demo_root: Path) -> Dict[str, Any]:
    """运行事务级最小样例。

    Args:
        demo_root: demo 输出目录。

    Returns:
        事务级结果摘要。
    """

    literature_table = build_sample_literature_table()
    literature_csv = demo_root / "literatures.csv"
    literature_table.to_csv(literature_csv, index=False, encoding="utf-8-sig")

    candidate_module = importlib.import_module("autodokit.affairs.候选文献视图构建.affair")
    pool_module = importlib.import_module("autodokit.affairs.创新点池构建.affair")
    score_module = importlib.import_module("autodokit.affairs.创新点可行性验证.affair")

    candidate_config = demo_root / "candidate_config.json"
    _write_config(
        candidate_config,
        {
            "literature_csv": str(literature_csv),
            "output_dir": str(demo_root),
            "source_round": "round_01",
            "source_affair": "review_candidate_views",
            "batch_size": 1,
            "candidates": [
                {"uid_literature": "lit-001", "score": 95, "reason": "综述优先"},
                {"uid_literature": "lit-002", "score": 84, "reason": "主题相关"},
            ],
        },
    )
    candidate_outputs = candidate_module.execute(candidate_config)

    pool_config = demo_root / "innovation_pool_config.json"
    _write_config(
        pool_config,
        {
            "output_dir": str(demo_root),
            "topic": "数字金融",
            "gaps": ["缺少机制识别"],
            "scenario": "制造业企业",
            "data_source": "上市公司面板",
            "method_family": "双重差分",
            "output_form": "机制识别结果",
        },
    )
    pool_module.execute(pool_config)

    score_config = demo_root / "innovation_score_config.json"
    _write_config(
        score_config,
        {
            "output_dir": str(demo_root),
            "innovation_pool_csv": str(demo_root / "innovation_pool.csv"),
        },
    )
    score_outputs = score_module.execute(score_config)

    return {
        "candidate_output_count": len(candidate_outputs),
        "score_output_count": len(score_outputs),
        "gate_review_exists": (demo_root / "gate_review.json").exists(),
    }


def main() -> None:
    """运行 M1-M3 最小样例。

    Returns:
        None
    """

    demo_root = build_demo_root()
    tool_result = run_tools_demo(demo_root=demo_root)
    affair_result = run_affairs_demo(demo_root=demo_root)

    print("[M1-M3 tools demo]", json.dumps(tool_result, ensure_ascii=False, indent=2))
    print("[M1-M3 affairs demo]", json.dumps(affair_result, ensure_ascii=False, indent=2))
    print(f"[输出目录] {demo_root}")


if __name__ == "__main__":
    main()