"""Coverage for chika/skills/browser_skill/__init__.py — tool dispatch + validation."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from chika.skills import browser_skill as bs


# ── helpers / fixtures ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_rate_limiter(monkeypatch):
    """Force rate-limiter to always allow so we can exercise tool logic."""
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (True, 0))


@pytest.fixture
def mock_send():
    """Patch extension_manager.send_command with an AsyncMock."""
    with patch.object(bs.extension_manager, "send_command", new_callable=AsyncMock) as m:
        m.return_value = {"ok": True}
        yield m


# ── _rate_check / _push / set_frontend_push ───────────────────────────


def test_rate_check_returns_none_when_allowed(monkeypatch):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (True, 0))
    assert bs._rate_check() is None


def test_rate_check_returns_error_when_blocked(monkeypatch):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 3))
    out = bs._rate_check()
    assert out["error"] == "rate_limited"
    assert out["retry_after_seconds"] == 3
    assert "3s" in out["message"]


def test_set_frontend_push_assigns_module_global():
    sentinel = AsyncMock()
    bs.set_frontend_push(sentinel)
    assert bs._push_to_frontend is sentinel
    bs.set_frontend_push(None)


@pytest.mark.asyncio
async def test_push_no_op_when_no_handler():
    bs.set_frontend_push(None)
    # Should not raise.
    await bs._push({"type": "browser_watch_trigger"})


@pytest.mark.asyncio
async def test_push_calls_handler_when_set():
    handler = AsyncMock()
    bs.set_frontend_push(handler)
    try:
        await bs._push({"type": "x"})
        handler.assert_awaited_once_with({"type": "x"})
    finally:
        bs.set_frontend_push(None)


@pytest.mark.asyncio
async def test_push_swallows_handler_exceptions():
    handler = AsyncMock(side_effect=RuntimeError("boom"))
    bs.set_frontend_push(handler)
    try:
        await bs._push({"type": "x"})  # must not raise
    finally:
        bs.set_frontend_push(None)


# ── READ tools ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_browser_get_tabs_dispatches(mock_send):
    out = await bs.browser_get_tabs()
    mock_send.assert_awaited_once_with("get_tab_list", {})
    assert out == {"ok": True}


@pytest.mark.asyncio
async def test_browser_get_tabs_returns_rate_limit_error(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 5))
    out = await bs.browser_get_tabs()
    assert out["error"] == "rate_limited"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_get_active_tab_dispatches(mock_send):
    await bs.browser_get_active_tab()
    mock_send.assert_awaited_once_with("get_active_tab", {})


@pytest.mark.asyncio
async def test_browser_get_text_passes_args(mock_send):
    out = await bs.browser_get_text(
        tab_id=42, selector="main", find="hello", context_lines=3, wait_for=".x",
    )
    args, kwargs = mock_send.call_args
    assert args[0] == "get_tab_text"
    assert args[1]["tab_id"] == 42
    assert args[1]["selector"] == "main"
    assert args[1]["find"] == "hello"
    assert args[1]["context_lines"] == 3
    assert args[1]["wait_for"] == ".x"
    assert out == {"ok": True}


@pytest.mark.asyncio
async def test_browser_get_text_clamps_context_lines(mock_send):
    await bs.browser_get_text(context_lines=999)
    assert mock_send.call_args[0][1]["context_lines"] == 50


@pytest.mark.asyncio
async def test_browser_get_text_negative_context_lines_zero(mock_send):
    await bs.browser_get_text(context_lines=-3)
    assert mock_send.call_args[0][1]["context_lines"] == 0


@pytest.mark.asyncio
async def test_browser_get_text_invalid_selector(mock_send):
    with patch.object(bs, "validate_selector", return_value=(None, "bad")):
        out = await bs.browser_get_text(selector=":bad")
    assert out["error"] == "invalid_selector"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_get_text_invalid_wait_for(mock_send):
    def fake_validate(sel):
        if sel == ".bad":
            return None, "bad wait_for"
        return sel, None
    with patch.object(bs, "validate_selector", side_effect=fake_validate):
        out = await bs.browser_get_text(selector="ok", wait_for=".bad")
    assert out["error"] == "invalid_wait_for"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_get_text_find_too_long(mock_send):
    out = await bs.browser_get_text(find="x" * 201)
    assert out["error"] == "invalid_find"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_get_text_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_get_text()
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_get_page_var_dispatches(mock_send):
    await bs.browser_get_page_var(var_path="ytInitialData", tab_id=7, max_bytes=20000)
    args, _ = mock_send.call_args
    assert args[0] == "get_page_var"
    assert args[1]["var_path"] == "ytInitialData"
    assert args[1]["tab_id"] == 7
    assert args[1]["max_bytes"] == 20000


@pytest.mark.asyncio
async def test_browser_get_page_var_clamps_max_bytes_high(mock_send):
    await bs.browser_get_page_var(var_path="x", max_bytes=10_000_000)
    assert mock_send.call_args[0][1]["max_bytes"] == 300_000


@pytest.mark.asyncio
async def test_browser_get_page_var_clamps_max_bytes_low(mock_send):
    await bs.browser_get_page_var(var_path="x", max_bytes=10)
    assert mock_send.call_args[0][1]["max_bytes"] == 1000


@pytest.mark.asyncio
async def test_browser_get_page_var_missing_path(mock_send):
    out = await bs.browser_get_page_var(var_path="")
    assert out["error"] == "missing_var_path"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_get_page_var_non_string_path(mock_send):
    out = await bs.browser_get_page_var(var_path=None)  # type: ignore[arg-type]
    assert out["error"] == "missing_var_path"


@pytest.mark.asyncio
async def test_browser_get_page_var_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 2))
    out = await bs.browser_get_page_var(var_path="x")
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_get_dom_dispatches(mock_send):
    await bs.browser_get_dom(tab_id=1, selector="article")
    args, _ = mock_send.call_args
    assert args[0] == "get_tab_dom"
    assert args[1]["tab_id"] == 1
    assert args[1]["selector"] == "article"


@pytest.mark.asyncio
async def test_browser_get_dom_invalid_selector(mock_send):
    with patch.object(bs, "validate_selector", return_value=(None, "nope")):
        out = await bs.browser_get_dom(selector=":bad")
    assert out["error"] == "invalid_selector"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_get_dom_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_get_dom()
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_get_element_dispatches(mock_send):
    await bs.browser_get_element(selector="#price", attribute="value")
    args, _ = mock_send.call_args
    assert args[0] == "get_element"
    assert args[1]["selector"] == "#price"
    assert args[1]["attribute"] == "value"


@pytest.mark.asyncio
async def test_browser_get_element_requires_selector(mock_send):
    out = await bs.browser_get_element(selector="")
    assert out["error"] == "selector_required"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_get_element_invalid_selector(mock_send):
    with patch.object(bs, "validate_selector", return_value=(None, "x")):
        out = await bs.browser_get_element(selector=":bad")
    assert out["error"] == "invalid_selector"


@pytest.mark.asyncio
async def test_browser_get_element_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_get_element(selector="#x")
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_screenshot_attaches_vision_block(mock_send):
    mock_send.return_value = {"image": "BASE64DATA"}
    out = await bs.browser_screenshot(tab_id=3)
    assert out["_vision_image"] == "BASE64DATA"
    assert out["_vision_media_type"] == "image/png"


@pytest.mark.asyncio
async def test_browser_screenshot_no_vision_block_on_error(mock_send):
    mock_send.return_value = {"image": "x", "error": "tab_gone"}
    out = await bs.browser_screenshot()
    assert "_vision_image" not in out


@pytest.mark.asyncio
async def test_browser_screenshot_no_vision_block_when_no_image(mock_send):
    mock_send.return_value = {}
    out = await bs.browser_screenshot()
    assert "_vision_image" not in out


@pytest.mark.asyncio
async def test_browser_screenshot_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_screenshot()
    assert out["error"] == "rate_limited"


# ── WRITE tools ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_browser_navigate_invalid_url(mock_send):
    with patch.object(bs, "validate_url", return_value="bad scheme"):
        out = await bs.browser_navigate(url="javascript:alert(1)")
    assert out["error"] == "invalid_url"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_navigate_blocked_domain(mock_send):
    with patch.object(bs, "validate_url", return_value=None), \
         patch.object(bs, "is_write_blocked", return_value=True):
        out = await bs.browser_navigate(url="https://bank.com")
    assert out["error"] == "blocked_domain"
    assert "blocked" in out["message"].lower()
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_navigate_passes_args(mock_send):
    with patch.object(bs, "validate_url", return_value=None), \
         patch.object(bs, "is_write_blocked", return_value=False):
        await bs.browser_navigate(url="https://example.com", tab_id=2, new_tab=True)
    args, _ = mock_send.call_args
    assert args[0] == "navigate"
    assert args[1]["url"] == "https://example.com"
    assert args[1]["tab_id"] == 2
    assert args[1]["new_tab"] is True


@pytest.mark.asyncio
async def test_browser_navigate_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_navigate(url="https://x.com")
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_open_tab_default_about_blank(mock_send):
    await bs.browser_open_tab()
    args, _ = mock_send.call_args
    assert args[0] == "open_tab"
    assert args[1]["url"] == "about:blank"


@pytest.mark.asyncio
async def test_browser_open_tab_validates_url_when_provided(mock_send):
    with patch.object(bs, "validate_url", return_value="bad") as v:
        out = await bs.browser_open_tab(url="javascript:alert(1)")
    v.assert_called_once_with("javascript:alert(1)")
    assert out["error"] == "invalid_url"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_open_tab_skips_validate_for_about_blank(mock_send):
    with patch.object(bs, "validate_url") as v:
        await bs.browser_open_tab(url="about:blank")
    v.assert_not_called()


@pytest.mark.asyncio
async def test_browser_open_tab_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_open_tab()
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_close_tab_dispatches(mock_send):
    await bs.browser_close_tab(tab_id=99)
    args, _ = mock_send.call_args
    assert args[0] == "close_tab"
    assert args[1]["tab_id"] == 99


@pytest.mark.asyncio
async def test_browser_close_tab_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_close_tab(tab_id=1)
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_switch_tab_dispatches(mock_send):
    await bs.browser_switch_tab(tab_id=12)
    args, _ = mock_send.call_args
    assert args[0] == "switch_tab"
    assert args[1]["tab_id"] == 12


@pytest.mark.asyncio
async def test_browser_switch_tab_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_switch_tab(tab_id=1)
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_click_dispatches(mock_send):
    await bs.browser_click(selector="button.submit")
    args, _ = mock_send.call_args
    assert args[0] == "click"
    assert args[1]["selector"] == "button.submit"


@pytest.mark.asyncio
async def test_browser_click_invalid_selector(mock_send):
    with patch.object(bs, "validate_selector", return_value=(None, "bad")):
        out = await bs.browser_click(selector=":bad")
    assert out["error"] == "invalid_selector"


@pytest.mark.asyncio
async def test_browser_click_requires_selector(mock_send):
    out = await bs.browser_click(selector="")
    assert out["error"] == "selector_required"


@pytest.mark.asyncio
async def test_browser_click_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_click(selector="x")
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_fill_input_dispatches(mock_send):
    await bs.browser_fill_input(selector="input.q", value="hello")
    args, _ = mock_send.call_args
    assert args[0] == "fill_input"
    assert args[1]["value"] == "hello"


@pytest.mark.asyncio
async def test_browser_fill_input_invalid_selector(mock_send):
    with patch.object(bs, "validate_selector", return_value=(None, "x")):
        out = await bs.browser_fill_input(selector=":bad", value="x")
    assert out["error"] == "invalid_selector"


@pytest.mark.asyncio
async def test_browser_fill_input_requires_selector(mock_send):
    out = await bs.browser_fill_input(selector="", value="x")
    assert out["error"] == "selector_required"


@pytest.mark.asyncio
async def test_browser_fill_input_value_too_long(mock_send):
    out = await bs.browser_fill_input(selector="input", value="x" * 10_001)
    assert out["error"] == "value_too_long"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_fill_input_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_fill_input(selector="x", value="y")
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_scroll_default_direction(mock_send):
    await bs.browser_scroll()
    args, _ = mock_send.call_args
    assert args[0] == "scroll"
    assert args[1]["direction"] == "down"
    assert args[1]["amount"] == 500


@pytest.mark.asyncio
async def test_browser_scroll_invalid_direction(mock_send):
    out = await bs.browser_scroll(direction="diagonal")
    assert out["error"] == "invalid_direction"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_scroll_clamps_amount(mock_send):
    await bs.browser_scroll(amount=99_999)
    assert mock_send.call_args[0][1]["amount"] == 10_000


@pytest.mark.asyncio
async def test_browser_scroll_negative_amount_clamps_to_zero(mock_send):
    await bs.browser_scroll(amount=-5)
    assert mock_send.call_args[0][1]["amount"] == 0


@pytest.mark.asyncio
async def test_browser_scroll_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_scroll()
    assert out["error"] == "rate_limited"


# ── WATCH tools ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_browser_watch_element_success(monkeypatch, mock_send):
    monkeypatch.setattr(bs.extension_manager, "watch_count", lambda: 0)
    monkeypatch.setattr(bs.extension_manager, "register_watch_callback", lambda *a, **k: None)
    monkeypatch.setattr(bs.extension_manager, "unregister_watch", lambda *a, **k: None)
    mock_send.return_value = {"ok": True}
    out = await bs.browser_watch_element(selector="#x", event_name="x_changed")
    assert out["status"] == "watching"
    assert out["selector"] == "#x"
    assert out["event_name"] == "x_changed"
    assert "watch_id" in out


@pytest.mark.asyncio
async def test_browser_watch_element_limit_reached(monkeypatch, mock_send):
    monkeypatch.setattr(bs.extension_manager, "watch_count", lambda: bs.MAX_WATCH_COUNT)
    out = await bs.browser_watch_element(selector="#x", event_name="x")
    assert out["error"] == "watch_limit_reached"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_watch_element_invalid_selector(monkeypatch, mock_send):
    monkeypatch.setattr(bs.extension_manager, "watch_count", lambda: 0)
    with patch.object(bs, "validate_selector", return_value=(None, "bad")):
        out = await bs.browser_watch_element(selector=":bad", event_name="x")
    assert out["error"] == "invalid_selector"


@pytest.mark.asyncio
async def test_browser_watch_element_requires_selector(monkeypatch, mock_send):
    monkeypatch.setattr(bs.extension_manager, "watch_count", lambda: 0)
    out = await bs.browser_watch_element(selector="", event_name="x")
    assert out["error"] == "selector_required"


@pytest.mark.asyncio
async def test_browser_watch_element_clamps_debounce(monkeypatch, mock_send):
    monkeypatch.setattr(bs.extension_manager, "watch_count", lambda: 0)
    monkeypatch.setattr(bs.extension_manager, "register_watch_callback", lambda *a, **k: None)
    monkeypatch.setattr(bs.extension_manager, "unregister_watch", lambda *a, **k: None)
    mock_send.return_value = {"ok": True}
    out = await bs.browser_watch_element(
        selector="#x", event_name="x", debounce_ms=999_999_999,
    )
    assert out["debounce_ms"] == bs.MAX_DEBOUNCE_MS

    out = await bs.browser_watch_element(
        selector="#x", event_name="x", debounce_ms=1,
    )
    assert out["debounce_ms"] == bs.MIN_DEBOUNCE_MS


@pytest.mark.asyncio
async def test_browser_watch_element_send_error_unregisters(monkeypatch, mock_send):
    monkeypatch.setattr(bs.extension_manager, "watch_count", lambda: 0)
    monkeypatch.setattr(bs.extension_manager, "register_watch_callback", lambda *a, **k: None)
    unregistered: list[str] = []
    monkeypatch.setattr(
        bs.extension_manager, "unregister_watch", lambda wid: unregistered.append(wid),
    )
    mock_send.return_value = {"error": "tab_gone"}
    out = await bs.browser_watch_element(selector="#x", event_name="x")
    assert out["error"] == "tab_gone"
    assert len(unregistered) == 1  # cleanup happened


@pytest.mark.asyncio
async def test_browser_watch_element_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_watch_element(selector="x", event_name="y")
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_watch_element_callback_pushes_event(monkeypatch, mock_send):
    """Verify the registered callback pushes a browser_watch_trigger event."""
    monkeypatch.setattr(bs.extension_manager, "watch_count", lambda: 0)

    captured = {}

    def fake_register(wid, cb):
        captured["wid"] = wid
        captured["cb"] = cb

    monkeypatch.setattr(bs.extension_manager, "register_watch_callback", fake_register)
    monkeypatch.setattr(bs.extension_manager, "unregister_watch", lambda *a, **k: None)
    mock_send.return_value = {"ok": True}

    pushed: list[dict] = []
    async def fake_push(event):
        pushed.append(event)
    bs.set_frontend_push(fake_push)
    try:
        await bs.browser_watch_element(selector=".x", event_name="my_event")
        await captured["cb"](captured["wid"], {"text": "new"})
        assert len(pushed) == 1
        assert pushed[0]["type"] == "browser_watch_trigger"
        assert pushed[0]["event_name"] == "my_event"
        assert pushed[0]["selector"] == ".x"
        assert pushed[0]["data"] == {"text": "new"}
    finally:
        bs.set_frontend_push(None)


@pytest.mark.asyncio
async def test_browser_unwatch_dispatches_and_unregisters(monkeypatch, mock_send):
    unregistered: list[str] = []
    monkeypatch.setattr(
        bs.extension_manager, "unregister_watch", lambda wid: unregistered.append(wid),
    )
    mock_send.return_value = {"ok": True}
    out = await bs.browser_unwatch(watch_id="abc-123")
    assert unregistered == ["abc-123"]
    assert out == {"ok": True}


@pytest.mark.asyncio
async def test_browser_unwatch_returns_cancelled_on_send_error(monkeypatch, mock_send):
    monkeypatch.setattr(bs.extension_manager, "unregister_watch", lambda *a, **k: None)
    mock_send.return_value = {"error": "tab_gone"}
    out = await bs.browser_unwatch(watch_id="zzz")
    assert out["status"] == "cancelled"
    assert out["watch_id"] == "zzz"


@pytest.mark.asyncio
async def test_browser_list_watches_empty(monkeypatch, mock_send):
    monkeypatch.setattr(bs.extension_manager, "_watch_callbacks", {})
    out = await bs.browser_list_watches()
    assert out == {"watches": [], "count": 0}
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_list_watches_dispatches_with_ids(monkeypatch, mock_send):
    monkeypatch.setattr(
        bs.extension_manager, "_watch_callbacks",
        {"a": object(), "b": object()},
    )
    mock_send.return_value = {"watches": [{"id": "a"}, {"id": "b"}]}
    out = await bs.browser_list_watches()
    args, _ = mock_send.call_args
    assert args[0] == "list_watches"
    assert set(args[1]["watch_ids"]) == {"a", "b"}
    assert out == {"watches": [{"id": "a"}, {"id": "b"}]}


# ── COMPOUND tool — browser_run_research ───────────────────────────────


@pytest.mark.asyncio
async def test_browser_run_research_no_urls(mock_send):
    out = await bs.browser_run_research(urls=[])
    assert out["error"] == "no_urls"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_run_research_caps_urls_at_10(mock_send):
    """Only first 10 URLs are processed; rest silently dropped."""
    urls = [f"https://example.com/{i}" for i in range(15)]

    async def side_effect(name, payload, timeout=None):
        if name == "open_tab":
            return {"tab_id": 99}
        if name == "get_tab_text":
            return {"title": "T", "text": "x", "truncated": False}
        return {"ok": True}
    mock_send.side_effect = side_effect

    with patch.object(bs, "validate_url", return_value=None):
        out = await bs.browser_run_research(urls=urls)

    assert out["count"] == 10  # cap


@pytest.mark.asyncio
async def test_browser_run_research_records_invalid_url(mock_send):
    with patch.object(bs, "validate_url", return_value="bad scheme"):
        out = await bs.browser_run_research(urls=["javascript:alert(1)"])
    assert out["count"] == 1
    assert out["results"][0]["error"] == "bad scheme"


@pytest.mark.asyncio
async def test_browser_run_research_records_open_tab_error(mock_send):
    async def side_effect(name, payload, timeout=None):
        if name == "open_tab":
            return {"error": "popup_blocked", "message": "no"}
        return {"ok": True}
    mock_send.side_effect = side_effect
    with patch.object(bs, "validate_url", return_value=None):
        out = await bs.browser_run_research(urls=["https://example.com"])
    assert out["results"][0]["error"] == "popup_blocked"


@pytest.mark.asyncio
async def test_browser_run_research_caps_text_per_page(mock_send):
    async def side_effect(name, payload, timeout=None):
        if name == "open_tab":
            return {"tab_id": 1}
        if name == "get_tab_text":
            return {"title": "T", "text": "X" * 100_000, "truncated": False}
        return {"ok": True}
    mock_send.side_effect = side_effect
    with patch.object(bs, "validate_url", return_value=None):
        out = await bs.browser_run_research(urls=["https://example.com"])
    assert len(out["results"][0]["text"]) == 50_000


@pytest.mark.asyncio
async def test_browser_run_research_closes_opened_tabs(mock_send):
    """Verify the cleanup loop sends close_tab for each opened tab."""
    closes: list[int] = []

    async def side_effect(name, payload, timeout=None):
        if name == "open_tab":
            return {"tab_id": payload.get("url", "")[-1:]}  # use last char as fake id
        if name == "get_tab_text":
            return {"title": "T", "text": "x"}
        if name == "close_tab":
            closes.append(payload["tab_id"])
            return {"ok": True}
        return {"ok": True}
    mock_send.side_effect = side_effect

    with patch.object(bs, "validate_url", return_value=None):
        out = await bs.browser_run_research(
            urls=["https://example.com/1", "https://example.com/2"],
        )
    assert out["count"] == 2
    assert len(closes) == 2


@pytest.mark.asyncio
async def test_browser_run_research_rate_limited(monkeypatch, mock_send):
    monkeypatch.setattr(bs.rate_limiter, "check", lambda: (False, 1))
    out = await bs.browser_run_research(urls=["https://x.com"])
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_browser_run_research_success_count(mock_send):
    async def side_effect(name, payload, timeout=None):
        if name == "open_tab":
            return {"tab_id": 1}
        if name == "get_tab_text":
            return {"title": "T", "text": "ok"}
        return {"ok": True}
    mock_send.side_effect = side_effect
    with patch.object(bs, "validate_url", return_value=None):
        out = await bs.browser_run_research(
            urls=["https://example.com/a", "https://example.com/b"],
            query="hello",
        )
    assert out["query"] == "hello"
    assert out["success"] == 2


# ── BROWSER_SKILL definition ───────────────────────────────────────────


def test_browser_skill_has_expected_tools():
    names = {t.name for t in bs.BROWSER_SKILL.tools}
    expected = {
        "browser_get_tabs", "browser_get_active_tab", "browser_get_text",
        "browser_get_page_var", "browser_get_dom", "browser_get_element",
        "browser_screenshot",
        "browser_navigate", "browser_open_tab", "browser_close_tab",
        "browser_switch_tab", "browser_click", "browser_fill_input",
        "browser_scroll",
        "browser_watch_element", "browser_unwatch", "browser_list_watches",
        "browser_run_research",
    }
    assert expected.issubset(names)


def test_browser_skill_write_tools_require_approval():
    """Read tools never require approval; write tools do."""
    by_name = {t.name: t for t in bs.BROWSER_SKILL.tools}
    write_tools = [
        "browser_navigate", "browser_open_tab", "browser_close_tab",
        "browser_switch_tab", "browser_click", "browser_fill_input",
        "browser_scroll",
    ]
    for name in write_tools:
        assert by_name[name].requires_approval is True, name

    read_tools = [
        "browser_get_tabs", "browser_get_active_tab", "browser_get_text",
        "browser_get_dom", "browser_get_element", "browser_screenshot",
    ]
    for name in read_tools:
        assert by_name[name].requires_approval is False, name


def test_browser_skill_memory_seed_present():
    assert "browser_trust" in bs.BROWSER_SKILL.memory_seeds
