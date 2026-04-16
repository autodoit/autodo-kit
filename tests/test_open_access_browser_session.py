"""英文开放下载的浏览器会话复用测试。"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from autodokit.tools.online_retrieval_literatures.open_access_literature_retrieval import RetrievalRecord


class _DummyPage:
    """最小页面对象。"""

    def __init__(self, url: str) -> None:
        self.url = url
        self.goto_calls: list[tuple[str, str, int]] = []

    def goto(self, url: str, *, wait_until: str, timeout: int):
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url
        return None


class _DummyContext:
    """最小上下文对象。"""

    def __init__(self) -> None:
        self.pages: list[_DummyPage] = [_DummyPage("https://initial.example/")]
        self.new_page_calls = 0

    def new_page(self) -> _DummyPage:
        self.new_page_calls += 1
        page = _DummyPage("about:blank")
        self.pages.append(page)
        return page


class _DummyBrowser:
    """最小浏览器对象。"""

    def __init__(self, context: _DummyContext) -> None:
        self._context = context

    def is_connected(self) -> bool:
        return True

    @property
    def contexts(self) -> list[_DummyContext]:
        return [self._context]


def test_browser_session_cache_reuses_single_window(monkeypatch, tmp_path) -> None:
    """同一 profile 与端口应复用同一个窗口。"""

    module = importlib.import_module("autodokit.tools.online_retrieval_literatures.open_access_literature_retrieval")
    monkeypatch.setattr(module, "_BROWSER_SESSION_CACHE", {}, raising=False)
    monkeypatch.setattr(module, "_BROWSER_SESSION_CLEANUP_REGISTERED", False, raising=False)

    context = _DummyContext()
    browser = _DummyBrowser(context)
    connect_calls: list[str] = []

    def fake_connect(cdp_url: str):
        connect_calls.append(cdp_url)
        return SimpleNamespace(stop=lambda: None), browser, context

    monkeypatch.setattr(module, "_connect_context", fake_connect)

    profile_dir = tmp_path / "profile"
    first_session, first_reused = module._acquire_browser_session(profile_dir, 9332, "https://example.com/one")
    second_session, second_reused = module._acquire_browser_session(profile_dir, 9332, "https://example.com/two")

    assert first_reused is True
    assert second_reused is True
    assert first_session is second_session
    assert connect_calls == ["http://127.0.0.1:9332"]
    assert context.new_page_calls == 0


def test_manual_login_retry_opens_new_tab_when_reused(monkeypatch, tmp_path) -> None:
    """复用窗口时应新开标签页而不是另起浏览器进程。"""

    module = importlib.import_module("autodokit.tools.online_retrieval_literatures.open_access_literature_retrieval")
    context = _DummyContext()
    session = SimpleNamespace(context=context)
    reuse_flags = iter([False, True])

    monkeypatch.setattr(module, "_acquire_browser_session", lambda *args, **kwargs: (session, next(reuse_flags)))
    monkeypatch.setattr(module, "_wait_for_human_if_needed", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        module,
        "_download_with_browser_session",
        lambda *args, **kwargs: {
            "status": "PASS",
            "title": "Title",
            "source": "unit",
            "saved_path": str(tmp_path / "paper.pdf"),
        },
    )

    paper_path = tmp_path / "paper.pdf"
    paper_path.write_bytes(b"%PDF-1.4\n%dummy\n")

    record = RetrievalRecord(
        source="unit",
        source_id="unit-001",
        title="Title",
        year="2024",
        doi="",
        journal="",
        authors=[],
        abstract="",
        landing_url="https://example.com/article",
        pdf_url="",
        bibtex_key="paper-001",
        raw={},
    )

    first_result = module._manual_login_retry(
        record,
        tmp_path,
        start_url=record.landing_url,
        request_timeout=10,
        max_attempts=2,
        min_request_delay_seconds=0.1,
        max_request_delay_seconds=0.1,
        allow_manual_intervention=False,
        keep_browser_open=False,
        browser_profile_dir=str(tmp_path / "profile"),
        browser_cdp_port=9332,
        manual_wait_timeout_seconds=1,
    )
    second_result = module._manual_login_retry(
        record,
        tmp_path,
        start_url=record.landing_url,
        request_timeout=10,
        max_attempts=2,
        min_request_delay_seconds=0.1,
        max_request_delay_seconds=0.1,
        allow_manual_intervention=False,
        keep_browser_open=False,
        browser_profile_dir=str(tmp_path / "profile"),
        browser_cdp_port=9332,
        manual_wait_timeout_seconds=1,
    )

    assert first_result["browser"]["reused_window"] is False
    assert second_result["browser"]["reused_window"] is True
    assert context.new_page_calls == 1
    assert len(context.pages) == 2
    assert context.pages[0].goto_calls[0][0] == record.landing_url
    assert context.pages[1].goto_calls[0][0] == record.landing_url
