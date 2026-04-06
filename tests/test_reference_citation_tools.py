"""参考引文处理工具测试。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from autodokit.tools.reference_citation_tools import (
    _extract_reference_line_details_from_text,
    extract_reference_lines_from_attachment,
    process_reference_citation,
)
from autodokit.tools.storage_backend import load_reference_main_table, persist_reference_main_table


def _write_config(config_path: Path, workspace_root: Path) -> None:
    payload = {
        "workspace_root": str(workspace_root),
        "llm": {
            "aliyun_api_key_file": str(workspace_root / "bailian_api_key.txt"),
            "reference_parse_model": "qwen-flash",
        },
        "paths": {
            "log_db_path": str(workspace_root / "database" / "logs" / "aok_log.db"),
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_extract_reference_lines_from_attachment_should_mark_caj_as_pending(tmp_path: Path) -> None:
    caj_path = tmp_path / "demo.caj"
    caj_path.write_text("placeholder", encoding="utf-8")

    result = extract_reference_lines_from_attachment(caj_path, workspace_root=tmp_path)
    assert result["extract_status"] == "pending_caj_pipeline"
    assert result["attachment_type"] == "caj"


def test_extract_reference_line_details_should_split_merged_items_and_drop_abstract_noise() -> None:
    text = """
参考文献
[1] IMF. Responding to the financial crisis and measuring systemic risks [R]. Washington D.C.: Global Stability Report, 2011.
[2] 包全永. 银行系统性风险的传染模型研究 [J]. 金融研究, 2005（8）：72-84.
[3] 徐荣，郭娜，李金鑫，等. 我国房地产价格波动对系统性金融风险影响的动态机制研究 [J]. 南方经济，2017（11）：1-17.
Abstract: The fluctuations in housing prices cannot only directly reflect the market supply and demand relationship.
Key words: Housing price fluctuations
"""

    details = _extract_reference_line_details_from_text(text)

    assert len(details) == 3
    assert all("Abstract" not in item["reference_text"] for item in details)
    assert all("Key words" not in item["reference_text"] for item in details)
    assert details[0]["reference_text"].startswith("IMF.")
    assert details[1]["reference_text"].startswith("包全永")
    assert details[2]["reference_text"].startswith("徐荣")


def test_process_reference_citation_should_match_existing_record(monkeypatch, tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    config_path = workspace_root / "config" / "config.json"
    _write_config(config_path, workspace_root)

    literature_table = pd.DataFrame(
        [
            {
                "uid_literature": "lit-001",
                "cite_key": "wang-2024-digital_finance_review",
                "title": "Digital Finance Review",
                "first_author": "Wang",
                "year": "2024",
                "clean_title": "digital_finance_review",
                "title_norm": "digital finance review",
            }
        ]
    )

    def _fake_generate_text(self, **kwargs):
        _ = kwargs
        return json.dumps(
            {
                "first_author": "Wang",
                "year": "2024",
                "title_raw": "Digital Finance Review",
                "confidence": "0.95",
                "failure_reason": "",
            },
            ensure_ascii=False,
        )

    def _fake_load_config(**kwargs):
        from autodokit.tools.llm_clients import AliyunLLMConfig

        return AliyunLLMConfig(
            api_key="fake",
            model="qwen3.5-flash",
            base_url="https://example.com",
            sdk_backend="dashscope",
            region="cn-beijing",
            routing_info={},
        )

    monkeypatch.setattr("autodokit.tools.reference_citation_tools.load_aliyun_llm_config", _fake_load_config)
    monkeypatch.setattr("autodokit.tools.reference_citation_tools.AliyunLLMClient.generate_text", _fake_generate_text)

    updated_table, result = process_reference_citation(
        literature_table,
        "Wang. 2024. Digital Finance Review.",
        workspace_root=workspace_root,
        global_config_path=config_path,
        print_to_stdout=False,
    )

    assert len(updated_table) == 1
    assert result["action"] == "exists"
    assert result["matched_cite_key"] == "wang-2024-digital_finance_review"
    log_db = workspace_root / "database" / "logs" / "aok_log.db"
    with sqlite3.connect(log_db) as conn:
        parse_count = conn.execute("select count(*) from log_events where event_type='REFERENCE_LLM_PARSE'").fetchone()[0]
        match_count = conn.execute("select count(*) from log_events where event_type='REFERENCE_LOCAL_MATCH'").fetchone()[0]
        assert parse_count == 1
        assert match_count == 1


def test_process_reference_citation_should_insert_placeholder_when_parse_fails(monkeypatch, tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    config_path = workspace_root / "config" / "config.json"
    _write_config(config_path, workspace_root)

    monkeypatch.setattr(
        "autodokit.tools.reference_citation_tools.load_aliyun_llm_config",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("llm unavailable")),
    )

    updated_table, result = process_reference_citation(
        pd.DataFrame(),
        "[1] ???",
        workspace_root=workspace_root,
        global_config_path=config_path,
        print_to_stdout=False,
    )

    assert len(updated_table) == 1
    loaded = load_reference_main_table(workspace_root / "tmp.db") if False else updated_table
    _ = loaded
    row = dict(updated_table.iloc[0])
    assert int(row["is_placeholder"]) == 1
    assert int(row["llm_invoked"]) == 1
    assert row["parse_method"] == "affair_fallback_parser"
    assert row["online_lookup_status"] == "pending"
    assert result["matched_cite_key"]


def test_process_reference_citation_should_accept_integer_typed_history_columns(monkeypatch, tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    config_path = workspace_root / "config" / "config.json"
    _write_config(config_path, workspace_root)

    literature_table = pd.DataFrame(
        {
            "uid_literature": ["lit-001"],
            "cite_key": ["wang-2024-digital_finance_review"],
            "title": ["Digital Finance Review"],
            "first_author": ["Wang"],
            "year": ["2024"],
            "clean_title": ["digital_finance_review"],
            "title_norm": ["digital finance review"],
            "has_fulltext": pd.Series([1], dtype="int64"),
            "is_placeholder": pd.Series([0], dtype="int64"),
            "llm_invoked": pd.Series([0], dtype="int64"),
            "parse_failed": pd.Series([0], dtype="int64"),
        }
    )

    def _fake_generate_text(self, **kwargs):
        _ = kwargs
        return json.dumps(
            {
                "first_author": "Wang",
                "year": "2024",
                "title_raw": "Digital Finance Review",
                "confidence": "0.95",
                "failure_reason": "",
            },
            ensure_ascii=False,
        )

    def _fake_load_config(**kwargs):
        from autodokit.tools.llm_clients import AliyunLLMConfig

        return AliyunLLMConfig(
            api_key="fake",
            model="qwen3.5-flash",
            base_url="https://example.com",
            sdk_backend="dashscope",
            region="cn-beijing",
            routing_info={},
        )

    monkeypatch.setattr("autodokit.tools.reference_citation_tools.load_aliyun_llm_config", _fake_load_config)
    monkeypatch.setattr("autodokit.tools.reference_citation_tools.AliyunLLMClient.generate_text", _fake_generate_text)

    updated_table, result = process_reference_citation(
        literature_table,
        "Wang. 2024. Digital Finance Review.",
        workspace_root=workspace_root,
        global_config_path=config_path,
        print_to_stdout=False,
    )

    assert len(updated_table) == 1
    assert result["action"] == "exists"
    assert result["matched_cite_key"] == "wang-2024-digital_finance_review"