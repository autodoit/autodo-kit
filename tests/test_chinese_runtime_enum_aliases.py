from __future__ import annotations

from autodokit.affairs.导入和预处理文献元数据.affair import _normalize_run_mode
from autodokit.affairs.统一文献预处理解析.affair import _resolve_a055_run_mode
from autodokit.tools.affair_request_bus import (
    _apply_a040_request_business_payload,
    _apply_a045_request_business_payload,
    _apply_a050_request_business_payload,
    _apply_a055_request_business_payload,
)
from autodokit.tools.ocr.monkeyocr.runner import _normalize_execution_mode


def test_a020_run_mode_should_accept_chinese_aliases() -> None:
    assert _normalize_run_mode("增量") == "incremental"
    assert _normalize_run_mode("增量更新") == "incremental"
    assert _normalize_run_mode("全量重置") == "full_reset"
    assert _normalize_run_mode("全量重建") == "full_reset"


def test_affair_request_bus_should_normalize_chinese_business_enums() -> None:
    a040_config = _apply_a040_request_business_payload(
        {},
        {
            "seed_items": [{"cite_key": "demo-key"}],
            "online_trigger_policy": "仅人工种子触发",
        },
    )
    assert a040_config["online_trigger_policy"] == "manual_seed_only"

    a045_config = _apply_a045_request_business_payload(
        {},
        {
            "seed_items": [{"cite_key": "demo-key"}],
        },
    )
    assert a045_config["online_trigger_policy"] == "manual_seed_only"
    assert a045_config["online_acquisition_mode"] == "download_pdf"


def test_a050_a055_should_normalize_chinese_profile_and_execution_mode() -> None:
    a050_config = _apply_a050_request_business_payload({}, {"profile": "综述"})
    assert a050_config["profile"] == "review"
    assert a050_config["execution_mode"] == "priority_only"

    a055_config = _apply_a055_request_business_payload({}, {"profile": "非综述"})
    assert a055_config["profile"] == "non_review"
    assert a055_config["execution_mode"] == "full_preprocess"


def test_a055_run_mode_and_monkeyocr_execution_mode_should_accept_chinese_aliases(monkeypatch) -> None:
    monkeypatch.setenv("A055_RUN_MODE_OVERRIDE", "仅远端tmux")
    assert _resolve_a055_run_mode({}, parse_runtime={}, execution_mode="full_preprocess") == "remote_only_tmux"
    monkeypatch.delenv("A055_RUN_MODE_OVERRIDE")

    assert _resolve_a055_run_mode(
        {"run_mode": "本地分发远端"},
        parse_runtime={},
        execution_mode="full_preprocess",
    ) == "local_dispatch_remote"

    assert _normalize_execution_mode("自动") == "auto"
    assert _normalize_execution_mode("本地") == "local"
    assert _normalize_execution_mode("远端") == "remote"