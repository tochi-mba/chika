"""Coverage for chika/skills/browser_skill/extension_manager.py.

Tests connection lifecycle, command dispatch, future bridging, and watch
callbacks.  No real WebSocket — uses an AsyncMock that mimics ``send_json``.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from chika.skills.browser_skill.extension_manager import (
    MAX_PENDING,
    ExtensionManager,
)


@pytest.fixture
def mgr():
    """Fresh ExtensionManager per test (the singleton is shared globally)."""
    return ExtensionManager()


@pytest.fixture
def fake_ws():
    """Mock a fastapi.WebSocket with an awaitable send_json."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


# ── connect / disconnect ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_marks_connected(mgr, fake_ws):
    assert mgr.connected is False
    await mgr.connect(fake_ws)
    assert mgr.connected is True
    assert mgr._ws is fake_ws


@pytest.mark.asyncio
async def test_connect_replaces_old_connection_and_cancels_pending(mgr, fake_ws):
    """A reconnect should cancel any pending futures from the prior session."""
    await mgr.connect(fake_ws)
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    mgr._pending["abc"] = fut

    await mgr.connect(fake_ws)
    assert fut.done()
    with pytest.raises(ConnectionError):
        fut.result()
    assert mgr._pending == {}


@pytest.mark.asyncio
async def test_connect_cancels_lingering_chat_task(mgr, fake_ws):
    """A still-running chat task from a previous connection is cancelled on reconnect."""
    async def _runner() -> None:
        await asyncio.sleep(10)
    task = asyncio.create_task(_runner())
    mgr._chat_task = task
    mgr._connected = True
    await mgr.connect(fake_ws)
    await asyncio.sleep(0)  # let cancellation propagate
    assert task.cancelled() or task.done()
    assert mgr._chat_task is None


@pytest.mark.asyncio
async def test_disconnect_clears_state(mgr, fake_ws):
    await mgr.connect(fake_ws)
    mgr.disconnect()
    assert mgr.connected is False
    assert mgr._ws is None


@pytest.mark.asyncio
async def test_disconnect_idempotent(mgr):
    """Calling disconnect when already disconnected is a no-op."""
    mgr.disconnect()  # never connected
    assert mgr.connected is False


@pytest.mark.asyncio
async def test_disconnect_ignores_stale_ws(mgr, fake_ws):
    """If a stale handler calls disconnect with an old ws ref, ignore it."""
    await mgr.connect(fake_ws)
    other = MagicMock()
    mgr.disconnect(ws=other)
    assert mgr.connected is True


@pytest.mark.asyncio
async def test_disconnect_cancels_pending(mgr, fake_ws):
    await mgr.connect(fake_ws)
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    mgr._pending["x"] = fut
    mgr.disconnect()
    await asyncio.sleep(0)
    assert fut.done()


@pytest.mark.asyncio
async def test_status_listeners_fired(mgr, fake_ws):
    seen: list[bool] = []

    async def cb(connected: bool) -> None:
        seen.append(connected)

    mgr.add_status_listener(cb)
    await mgr.connect(fake_ws)
    mgr.disconnect()
    await asyncio.sleep(0)  # let create_task in disconnect fire
    assert True in seen
    assert False in seen


@pytest.mark.asyncio
async def test_status_listener_swallows_exceptions(mgr, fake_ws):
    async def boom(_: bool) -> None:
        raise RuntimeError("boom")

    mgr.add_status_listener(boom)
    await mgr.connect(fake_ws)  # must not raise


@pytest.mark.asyncio
async def test_remove_status_listener(mgr, fake_ws):
    seen: list[bool] = []

    async def cb(connected: bool) -> None:
        seen.append(connected)

    mgr.add_status_listener(cb)
    mgr.remove_status_listener(cb)
    await mgr.connect(fake_ws)
    assert seen == []


@pytest.mark.asyncio
async def test_remove_status_listener_missing_no_raise(mgr):
    async def cb(_: bool) -> None:
        pass
    mgr.remove_status_listener(cb)  # never registered — no error


# ── send_command ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_command_returns_error_when_not_connected(mgr):
    out = await mgr.send_command("nav", {})
    assert out["error"] == "extension_not_connected"


@pytest.mark.asyncio
async def test_send_command_returns_too_many_pending(mgr, fake_ws):
    await mgr.connect(fake_ws)
    loop = asyncio.get_event_loop()
    for i in range(MAX_PENDING):
        mgr._pending[f"id-{i}"] = loop.create_future()
    out = await mgr.send_command("nav", {})
    assert out["error"] == "too_many_pending"


@pytest.mark.asyncio
async def test_send_command_resolves_future(mgr, fake_ws):
    """A successful send → resolve flow returns the dispatched result."""
    await mgr.connect(fake_ws)

    captured: dict = {}
    original = fake_ws.send_json

    async def capture(payload: dict) -> None:
        captured.update(payload)
        # Schedule resolve in the next loop tick.
        asyncio.get_event_loop().call_later(
            0.01,
            lambda: mgr.resolve(payload["request_id"], {"status": "ok"}),
        )
        await original(payload)

    fake_ws.send_json = capture
    out = await mgr.send_command("nav", {"url": "x"}, timeout=2.0)
    assert out == {"status": "ok"}
    assert captured["action"] == "nav"
    assert captured["args"] == {"url": "x"}


@pytest.mark.asyncio
async def test_send_command_send_failure_disconnects(mgr, fake_ws):
    await mgr.connect(fake_ws)
    fake_ws.send_json = AsyncMock(side_effect=RuntimeError("network gone"))
    out = await mgr.send_command("nav", {})
    assert out["error"] == "send_failed"
    assert mgr.connected is False


@pytest.mark.asyncio
async def test_send_command_timeout(mgr, fake_ws):
    await mgr.connect(fake_ws)
    out = await mgr.send_command("nav", {}, timeout=0.05)
    assert out["error"] == "timeout"


@pytest.mark.asyncio
async def test_send_command_connection_error_branch(mgr, fake_ws):
    """If the future is rejected with ConnectionError, return extension_disconnected."""
    await mgr.connect(fake_ws)
    loop = asyncio.get_event_loop()

    async def fail_future():
        await asyncio.sleep(0.01)
        for fut in list(mgr._pending.values()):
            if not fut.done():
                fut.set_exception(ConnectionError("ws closed"))

    loop.create_task(fail_future())
    out = await mgr.send_command("nav", {}, timeout=2.0)
    assert out["error"] == "extension_disconnected"


# ── resolve / reject / cancel_command ──────────────────────────────────


def test_resolve_unknown_request_id_silently(mgr):
    mgr.resolve("unknown", {"x": 1})  # must not raise


def test_resolve_already_done(mgr):
    loop = asyncio.new_event_loop()
    try:
        fut = loop.create_future()
        fut.set_result({"early": True})
        mgr._pending["x"] = fut
        mgr.resolve("x", {"late": True})  # must not raise — fut.done() guard
    finally:
        loop.close()


def test_reject_sets_error_dict(mgr):
    loop = asyncio.new_event_loop()
    try:
        fut = loop.create_future()
        mgr._pending["x"] = fut
        mgr.reject("x", "boom")
        assert fut.result() == {"error": "boom"}
    finally:
        loop.close()


def test_cancel_command_settles_with_cancelled(mgr):
    loop = asyncio.new_event_loop()
    try:
        fut = loop.create_future()
        mgr._pending["x"] = fut
        mgr.cancel_command("x")
        result = fut.result()
        assert result["error"] == "cancelled"
    finally:
        loop.close()


def test_cancel_command_unknown_no_raise(mgr):
    mgr.cancel_command("does-not-exist")


def test_set_chat_task(mgr):
    sentinel = object()
    mgr.set_chat_task(sentinel)  # type: ignore[arg-type]
    assert mgr._chat_task is sentinel
    mgr.set_chat_task(None)
    assert mgr._chat_task is None


# ── watch callbacks ────────────────────────────────────────────────────


def test_register_and_count_watch(mgr):
    async def cb(_, __):
        pass

    mgr.register_watch_callback("a", cb)
    mgr.register_watch_callback("b", cb)
    assert mgr.watch_count() == 2


def test_unregister_watch(mgr):
    async def cb(_, __):
        pass

    mgr.register_watch_callback("a", cb)
    mgr.unregister_watch("a")
    assert mgr.watch_count() == 0


def test_unregister_unknown_watch_no_raise(mgr):
    mgr.unregister_watch("missing")  # noop


@pytest.mark.asyncio
async def test_handle_watch_trigger_invokes_callback(mgr):
    seen: list[tuple[str, dict]] = []

    async def cb(wid: str, data: dict) -> None:
        seen.append((wid, data))

    mgr.register_watch_callback("w1", cb)
    await mgr.handle_watch_trigger("w1", {"text": "hi"})
    assert seen == [("w1", {"text": "hi"})]


@pytest.mark.asyncio
async def test_handle_watch_trigger_swallows_callback_errors(mgr):
    async def boom(_, __):
        raise RuntimeError("x")

    mgr.register_watch_callback("w1", boom)
    await mgr.handle_watch_trigger("w1", {})  # must not raise


@pytest.mark.asyncio
async def test_handle_watch_trigger_unknown_id_noop(mgr):
    await mgr.handle_watch_trigger("nope", {})  # noop


@pytest.mark.asyncio
async def test_handle_watch_cancelled_unregisters(mgr):
    async def cb(_, __):
        pass

    mgr.register_watch_callback("w1", cb)
    await mgr.handle_watch_cancelled("w1", "user_cancelled")
    assert mgr.watch_count() == 0


# ── send_raw ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_raw_returns_false_when_not_connected(mgr):
    ok = await mgr.send_raw({"type": "pong"})
    assert ok is False


@pytest.mark.asyncio
async def test_send_raw_succeeds(mgr, fake_ws):
    await mgr.connect(fake_ws)
    ok = await mgr.send_raw({"type": "pong"})
    assert ok is True
    fake_ws.send_json.assert_awaited_once_with({"type": "pong"})


@pytest.mark.asyncio
async def test_send_raw_disconnects_on_failure(mgr, fake_ws):
    await mgr.connect(fake_ws)
    fake_ws.send_json = AsyncMock(side_effect=RuntimeError("dead"))
    ok = await mgr.send_raw({"type": "pong"})
    assert ok is False
    assert mgr.connected is False
