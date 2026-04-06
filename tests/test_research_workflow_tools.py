"""通用流程支持工具测试。"""

from __future__ import annotations

import pandas as pd

from autodokit.tools import (
    allocate_reading_batches,
    build_candidate_readable_view,
    build_candidate_view_index,
    build_gate_review,
    build_research_trajectory,
    build_review_consensus_rows,
    build_review_future_rows,
    extract_review_candidates,
    extract_review_state_from_attachment,
    init_empty_innovation_pool_table,
    innovation_feasibility_score,
    innovation_pool_upsert,
    merge_human_gate_decision,
    score_gate_review,
)


def test_candidate_view_pipeline_should_work() -> None:
    """候选视图、综述抽取、批次分发与闸门审计应按预期工作。"""

    literature_table = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "title": "Digital Service Review",
                "first_author": "Wang",
                "year": "2024",
                "keywords": "review;digital service",
                "abstract": "A review article for digital service.",
                "entry_type": "journal",
                "source": "CNKI",
            },
            {
                "uid_literature": "lit-002",
                "title": "Workflow Innovation under AI",
                "first_author": "Li",
                "year": "2023",
                "keywords": "innovation;AI",
                "abstract": "Empirical study.",
                "entry_type": "journal",
                "source": "CNKI",
            },
        ]
    )
    candidate_index = build_candidate_view_index(
        [
            {"uid_literature": "lit-001", "score": 95, "reason": "优先处理"},
            {"uid_literature": "lit-002", "score": 82, "reason": "主题相关"},
        ],
        source_round="round_01",
        source_affair="review_candidate_views",
    )

    assert list(candidate_index["uid_literature"]) == ["lit-001", "lit-002"]

    readable_view = build_candidate_readable_view(candidate_index, literature_table)
    review_view = extract_review_candidates(readable_view)
    batches = allocate_reading_batches(candidate_index, batch_size=1, review_uid_set=review_view["uid_literature"].tolist())
    trajectory = build_research_trajectory(readable_view.to_dict(orient="records"), topic="通用主题")

    assert len(review_view) == 1
    assert review_view.iloc[0]["uid_literature"] == "lit-001"
    assert len(batches) == 2
    assert batches.iloc[0]["read_stage"] == "review"
    assert trajectory["item_count"] == 2

    review = build_gate_review(
        node_uid="A05",
        node_name="候选条目视图构建",
        summary="生成候选条目视图。",
        score=88,
    )
    scored_review = score_gate_review(review)
    merged_review = merge_human_gate_decision(scored_review, human_decision="pass", note="通过")

    assert scored_review["recommendation"] == "pass"
    assert merged_review["human_decision"] == "pass"


def test_innovation_pool_pipeline_should_work() -> None:
    """创新点池写入与可行性评分应按预期工作。"""

    pool_table = init_empty_innovation_pool_table()
    pool_table, inserted_item, action = innovation_pool_upsert(
        pool_table,
        {
            "title": "数字金融促进企业创新",
            "source_gap": "缺少机制识别",
            "method_family": "双重差分",
            "scenario": "制造业企业",
            "data_source": "上市公司面板",
            "output_form": "机制识别结果",
            "novelty_type": "问题导向法",
        },
    )

    assert action == "inserted"
    assert inserted_item["innovation_uid"].startswith("inn-")
    assert len(pool_table) == 1

    score_result = innovation_feasibility_score(inserted_item)
    assert score_result["score_total"] == 100.0
    assert score_result["recommendation"] == "promote"


def test_extract_review_state_from_attachment_should_reuse_tool_pipeline(monkeypatch) -> None:
    """文档附件抽取应返回全文、句子和参考条目结果。"""

    def _fake_extract_reference_lines_from_attachment(*args, **kwargs):
        _ = args, kwargs
        return {
            "attachment_path": "C:/tmp/demo.pdf",
            "attachment_type": "pdf",
            "extract_status": "ok",
            "extract_method": "pypdf",
            "full_text": "本文总结外部因素对目标结果的影响。文章基于已有材料进行归纳分析。研究发现关键变量会通过中介路径影响目标结果。未来应继续围绕扰动来源与响应策略开展研究。",
            "reference_lines": ["Wang. 2024. Digital Service Review."],
            "reference_line_details": [{"reference_text": "Wang. 2024. Digital Service Review."}],
            "pending_reason": "",
        }

    monkeypatch.setattr(
        "autodokit.tools.review_synthesis_tools.extract_reference_lines_from_attachment",
        _fake_extract_reference_lines_from_attachment,
    )

    state = extract_review_state_from_attachment(
        "C:/tmp/demo.pdf",
        workspace_root="C:/workspace",
        uid_literature="lit-001",
        cite_key="wang-2024-review",
        title="Digital Service Review",
        year="2024",
    )

    assert state["extract_status"] == "ok"
    assert len(state["sentences"]) >= 2
    assert len(state["core_findings"]) >= 1
    assert state["reference_lines"] == ["Wang. 2024. Digital Service Review."]


def test_build_review_summary_tables_should_generate_consensus_and_future_rows() -> None:
    """多篇状态记录应能生成共识表和未来方向表。"""

    review_states = [
        {
            "uid_literature": "lit-001",
            "cite_key": "cite-001",
            "core_findings": [{"index": 1, "sentence": "外部因素会通过中介路径影响目标结果。"}],
            "future_directions": [{"index": 4, "sentence": "未来应继续评估不同扰动情境下的响应策略。"}],
        },
        {
            "uid_literature": "lit-002",
            "cite_key": "cite-002",
            "core_findings": [{"index": 2, "sentence": "目标结果会受到外部扰动和传导机制的共同影响。"}],
            "future_directions": [{"index": 5, "sentence": "未来应进一步识别不同对象之间的异质性反应。"}],
        },
    ]

    consensus_df = build_review_consensus_rows(review_states)
    future_df = build_review_future_rows(review_states, topic="通用主题")

    assert not consensus_df.empty
    assert list(consensus_df["topic"])[0] == "核心对象关联"
    assert len(future_df) == 2
