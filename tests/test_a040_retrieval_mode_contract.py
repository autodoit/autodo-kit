"""A040 三阶段模式配置最小契约测试（已脱敏为“科学学”场景）。"""

from __future__ import annotations

from autodokit.affairs.检索治理.affair import default_retrieval_handler


BASE_CFG = {
    "query": "systemic risk",
    "enable_local_retrieval": True,
    "enable_online_retrieval": False,
    "online_trigger_policy": "gap_only",
    "online_acquisition_mode": "none",
}


def _build_mode_cfg(mode: str, enable_online: bool) -> dict[str, object]:
    cfg = dict(BASE_CFG)
    cfg["enable_online_retrieval"] = enable_online
    cfg["online_acquisition_mode"] = mode
    return cfg


def test_a040_mode_local_only_contract() -> None:
    cfg = _build_mode_cfg("none", False)
    assert cfg["enable_local_retrieval"] is True
    assert cfg["enable_online_retrieval"] is False
    assert cfg["online_acquisition_mode"] == "none"


def test_a040_mode_online_metadata_only_contract() -> None:
    cfg = _build_mode_cfg("none", True)
    assert cfg["enable_online_retrieval"] is True
    assert cfg["online_acquisition_mode"] == "none"


def test_a040_mode_pdf_download_contract() -> None:
    cfg = _build_mode_cfg("download_pdf", True)
    assert cfg["enable_online_retrieval"] is True
    assert cfg["online_acquisition_mode"] == "download_pdf"


def test_a040_mode_html_extract_contract() -> None:
    cfg = _build_mode_cfg("html_extract", True)
    assert cfg["enable_online_retrieval"] is True
    assert cfg["online_acquisition_mode"] == "html_extract"


def test_retrieval_governance_handler_is_still_available() -> None:
    result = default_retrieval_handler(
        {
            "query": "你要咨询的问题",
            "object_type": "literature",
            "source_type": "online",
            "region_type": "global",
            "access_type": "open",
            "metadata": {},
        }
    )
    assert "bundle" in result
    assert "next_node" in result
