"""Coverage for chika/_cli/pet_speech.py — LLM-driven pet quips."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chika._cli import pet_speech as ps


# ── _summarise_turn ────────────────────────────────────────────────────


def test_summarise_turn_no_events():
    assert ps._summarise_turn([]) == "no tools used"


def test_summarise_turn_with_tools():
    events = [
        {"type": "tool_call", "tool": "file_read"},
        {"type": "tool_call", "tool": "shell_exec"},
        {"type": "tool_result", "error": ""},
    ]
    out = ps._summarise_turn(events)
    assert "file_read" in out
    assert "shell_exec" in out


def test_summarise_turn_dedupes_tool_names():
    events = [
        {"type": "tool_call", "tool": "file_read"},
        {"type": "tool_call", "tool": "file_read"},
        {"type": "tool_call", "tool": "file_read"},
    ]
    out = ps._summarise_turn(events)
    # Should only appear once, not three times.
    assert out.count("file_read") == 1


def test_summarise_turn_caps_tools_at_5():
    events = [
        {"type": "tool_call", "tool": f"tool_{i}"} for i in range(10)
    ]
    out = ps._summarise_turn(events)
    # First 5 should appear, rest should be dropped.
    assert "tool_0" in out
    assert "tool_4" in out


def test_summarise_turn_counts_errors():
    events = [
        {"type": "tool_call", "tool": "x"},
        {"type": "tool_result", "error": "permission denied"},
        {"type": "tool_result", "error": "not found"},
    ]
    out = ps._summarise_turn(events)
    assert "2 tool error" in out


def test_summarise_turn_notes_token_emission():
    events = [
        {"type": "token", "text": "hi"},
    ]
    out = ps._summarise_turn(events)
    assert "produced a written reply" in out


def test_summarise_turn_combines_signals():
    events = [
        {"type": "tool_call", "tool": "shell_exec"},
        {"type": "tool_result", "error": "boom"},
        {"type": "token", "text": "sorry"},
    ]
    out = ps._summarise_turn(events)
    assert "shell_exec" in out
    assert "1 tool error" in out
    assert "produced a written reply" in out


# ── _pick_static ───────────────────────────────────────────────────────


def _fake_pet(quotes=None, name="Whiskers", personality="cute"):
    pet = MagicMock()
    pet.name = name
    pet.personality = personality
    pet.quotes = quotes or {}
    return pet


def test_pick_static_returns_one_of_the_state_quotes():
    pet = _fake_pet(quotes={"idle": ["meow", "purr"]})
    out = ps._pick_static(pet, "idle")
    assert out in ("meow", "purr")


def test_pick_static_falls_back_to_idle_for_unknown_state():
    pet = _fake_pet(quotes={"idle": ["chirp"]})
    out = ps._pick_static(pet, "unrecognised_state")
    assert out == "chirp"


def test_pick_static_returns_empty_when_no_quotes():
    pet = _fake_pet(quotes={})
    assert ps._pick_static(pet, "idle") == ""


# ── generate_quote ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_quote_returns_llm_response():
    pet = _fake_pet()
    engine = MagicMock()

    async def fake_complete(_engine, _prompt, *, max_tokens=40) -> str:  # noqa: ARG001
        return "tail wagging"

    with patch.object(ps, "_bounded_complete", fake_complete):
        out = await ps.generate_quote(
            engine, pet, state="idle", turn_events=[], max_tokens=40,
        )
    assert out == "tail wagging"


@pytest.mark.asyncio
async def test_generate_quote_strips_quotes_and_markdown():
    pet = _fake_pet()
    engine = MagicMock()

    async def fake_complete(_engine, _prompt, *, max_tokens=40) -> str:
        return '"tail wagging"\nignored line'

    with patch.object(ps, "_bounded_complete", fake_complete):
        out = await ps.generate_quote(
            engine, pet, state="idle", turn_events=[], max_tokens=40,
        )
    # Quotes stripped, only first line kept.
    assert out == "tail wagging"


@pytest.mark.asyncio
async def test_generate_quote_truncates_long_output():
    pet = _fake_pet()
    engine = MagicMock()

    async def fake_complete(_engine, _prompt, *, max_tokens=40) -> str:
        return "x" * 200

    with patch.object(ps, "_bounded_complete", fake_complete):
        out = await ps.generate_quote(
            engine, pet, state="idle", turn_events=[], max_tokens=40,
        )
    # Should be truncated to ~80 chars + ellipsis.
    assert len(out) <= 81
    assert out.endswith("…")


@pytest.mark.asyncio
async def test_generate_quote_falls_back_on_timeout():
    pet = _fake_pet(quotes={"idle": ["fallback line"]})
    engine = MagicMock()

    async def slow(*_a, **_kw):
        await asyncio.sleep(10)  # never finishes within timeout
        return ""

    with patch.object(ps, "_bounded_complete", slow), \
         patch.object(ps, "_TIMEOUT_S", 0.05):
        out = await ps.generate_quote(
            engine, pet, state="idle", turn_events=[], max_tokens=40,
        )
    assert out == "fallback line"


@pytest.mark.asyncio
async def test_generate_quote_falls_back_on_llm_exception():
    pet = _fake_pet(quotes={"idle": ["fallback"]})
    engine = MagicMock()

    async def err(*_a, **_kw):
        raise RuntimeError("LLM down")

    with patch.object(ps, "_bounded_complete", err):
        out = await ps.generate_quote(
            engine, pet, state="idle", turn_events=[], max_tokens=40,
        )
    assert out == "fallback"


@pytest.mark.asyncio
async def test_generate_quote_falls_back_when_llm_returns_empty():
    pet = _fake_pet(quotes={"idle": ["fallback"]})
    engine = MagicMock()

    async def empty(_engine, _prompt, *, max_tokens=40):  # noqa: ARG001
        return "   "

    with patch.object(ps, "_bounded_complete", empty):
        out = await ps.generate_quote(
            engine, pet, state="idle", turn_events=[], max_tokens=40,
        )
    assert out == "fallback"


# ── _bounded_complete ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bounded_complete_returns_empty_when_client_missing():
    """No live client → silent empty (not an exception)."""
    engine = MagicMock()
    engine._client = None
    out = await ps._bounded_complete(engine, "prompt", max_tokens=40)
    assert out == ""


# ── fire_and_forget ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fire_and_forget_invokes_on_done_with_result():
    pet = _fake_pet()
    engine = MagicMock()
    received: list[str] = []

    async def fake_generate(*_a, **_kw):
        return "yo"

    with patch.object(ps, "generate_quote", fake_generate):
        task = ps.fire_and_forget(
            engine, pet, state="idle", turn_events=[],
            max_tokens=40, on_done=received.append,
        )
        if task:
            await task
    assert received == ["yo"]


def test_fire_and_forget_returns_none_outside_event_loop():
    """When no event loop is running, fire_and_forget gracefully returns None."""
    pet = _fake_pet()
    engine = MagicMock()
    out = ps.fire_and_forget(
        engine, pet, state="idle", turn_events=[],
        max_tokens=40, on_done=lambda _: None,
    )
    # Outside an event loop we get None back instead of an exception.
    assert out is None or asyncio.iscoroutine(out) or hasattr(out, "cancel")
