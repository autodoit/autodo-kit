from __future__ import annotations

from autodokit.tools.online_retrieval_literatures.policies import assert_supported_combo
from autodokit.tools.online_retrieval_literatures.orchestrators.request_dispatcher import dispatch_request
from autodokit.tools.online_retrieval_literatures.executors import content_portal_spis


def test_capability_matrix_supports_spis_single_download() -> None:
    cell = assert_supported_combo("spis", "single", "download")
    assert cell["layer"] == "executor"


def test_dispatcher_debug_path_injects_request_profile() -> None:
    result = dispatch_request(
        {"source": "all", "mode": "debug", "action": "run", "request_profile": "mixed"},
        debug_handler=lambda payload: {"status": "PASS", "echo": payload.get("request_profile")},
    )
    assert result["status"] == "PASS"
    assert result["request_profile"] == "mixed"


def test_spis_delegate_by_request_profile(monkeypatch) -> None:
    monkeypatch.setattr(content_portal_spis, "execute_cnki_single_download", lambda payload: {"status": "PASS", "channel": "zh"})
    monkeypatch.setattr(content_portal_spis, "execute_open_single_download", lambda payload: {"status": "PASS", "channel": "en"})

    zh_result = content_portal_spis.execute_spis_single_download({"source": "spis"}, request_profile="zh")
    en_result = content_portal_spis.execute_spis_single_download({"source": "spis"}, request_profile="en")

    assert zh_result["channel"] == "zh"
    assert zh_result["spis_delegate"] == "zh_cnki"
    assert en_result["channel"] == "en"
    assert en_result["spis_delegate"] == "en_open_access"
