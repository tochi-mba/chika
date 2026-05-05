"""Tests for the auto-continue heuristic + engine recursion."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from chika.core.engine import _should_auto_continue


# ── Heuristic ───────────────────────────────────────────────────────────────

def test_continuation_phrases_trigger():
    triggers = [
        "Done. Next, I'll add the camera scrolling.",
        "Plan set. Next: build racer_main.py.",
        "Saved. Now I'll wire up collision detection.",
        "I'll continue with the asset pipeline.",
        "Then I'll layer in the soundtrack.",
        "Good progress. Continuing with the AI opponent.",
    ]
    for line in triggers:
        assert _should_auto_continue(line), f"expected auto-continue on: {line!r}"


def test_questions_block_continuation():
    # Even with a "next I'll" phrase, a trailing question must not auto-continue.
    txt = "Next, I'll add the audio system. Do you want stereo or mono?"
    assert not _should_auto_continue(txt), (
        "trailing question must suppress auto-continue"
    )


def test_clean_endings_dont_trigger():
    clean = [
        "Done. Let me know when you're ready for the next step.",
        "All set — the file is saved.",
        "Build complete. Ready when you are.",
        "",  # empty
        "ok.",  # too short
    ]
    for line in clean:
        assert not _should_auto_continue(line), f"unexpected trigger on: {line!r}"


def test_promise_in_middle_doesnt_trigger():
    # The trigger must be in the LAST paragraph. A historical "next I'll" in
    # an earlier paragraph isn't a current promise.
    txt = (
        "Earlier I said next I'll add the audio. We're past that now.\n\n"
        "The full pipeline is in place — done."
    )
    assert not _should_auto_continue(txt), (
        "phrase in earlier paragraph must not trigger"
    )


# ── Engine recursion ────────────────────────────────────────────────────────


class _FakeEngine:
    """Minimal stub matching the engine surface used by _chat_inner."""
    pass


def _build_engine_with_mock(turns: list[str]):
    """Build a real engine but stub _stream_llm to yield a canned text turn.

    Each call to _stream_llm pops the next entry from `turns` and yields it
    as a single token (no tool_call), so _chat_inner exits the agentic loop
    immediately and reaches the auto-continue check.
    """
    from api.session_manager import session_manager
    eng = session_manager.get_or_create("__test_auto_continue__")
    eng._history = []
    eng._title = ""
    eng._auto_continue_depth = 0

    state = {"i": 0}

    async def _fake_stream(self, _messages):
        i = state["i"]
        state["i"] += 1
        if i >= len(turns):
            yield {"type": "token", "text": "all done."}
            return
        for chunk in turns[i].split():
            yield {"type": "token", "text": chunk + " "}

    async def _fake_complete(self, _prompt: str) -> str:
        return "Test Title"

    async def _fake_validate(self, _text: str):
        return None

    # Bind as methods so engine code calling self._stream_llm(messages) works.
    eng._stream_llm = _fake_stream.__get__(eng, type(eng))
    eng._llm_complete = _fake_complete.__get__(eng, type(eng))
    eng._validate_grounding = _fake_validate.__get__(eng, type(eng))
    return eng


def test_engine_auto_continues_on_promise():
    """An assistant turn ending with 'Next, I'll …' triggers another turn."""
    eng = _build_engine_with_mock([
        "Phase 1 done. Next, I'll start phase 2.",
        "Phase 2 complete. Wrapping up cleanly.",
    ])

    async def _drive():
        events = []
        async for ev in eng.chat("kick it off"):
            events.append(ev)
        return events

    with patch("api.settings_store.get") as mock_get:
        mock_get.side_effect = lambda k, default=None: {
            "auto_continue": "on", "auto_continue_max": 5,
        }.get(k, default)
        events = asyncio.run(_drive())

    types = [e.get("type") for e in events]
    assert "auto_continue" in types, (
        f"expected an auto_continue event in stream, got types: {types}"
    )
    # Exactly one auto-continue (second turn ends cleanly, no recursion).
    assert types.count("auto_continue") == 1
    # Two 'done' events would indicate two top-level dones — should be one.
    assert types.count("done") == 1


def test_engine_respects_off_setting():
    """When auto_continue=off, the engine doesn't re-fire even with triggers."""
    eng = _build_engine_with_mock([
        "Phase 1 done. Next, I'll start phase 2.",
    ])

    async def _drive():
        return [ev async for ev in eng.chat("kick it off")]

    with patch("api.settings_store.get") as mock_get:
        mock_get.side_effect = lambda k, default=None: {
            "auto_continue": "off", "auto_continue_max": 5,
        }.get(k, default)
        events = asyncio.run(_drive())

    types = [e.get("type") for e in events]
    assert "auto_continue" not in types


def test_engine_respects_cap():
    """auto_continue_max=2 stops after 2 hops even if every turn promises more."""
    # 5 turns, each promising more.
    eng = _build_engine_with_mock([
        "step 1 done. Next, I'll go.",
        "step 2 done. Next, I'll go.",
        "step 3 done. Next, I'll go.",
        "step 4 done. Next, I'll go.",
        "step 5 done. Next, I'll go.",
    ])

    async def _drive():
        return [ev async for ev in eng.chat("start")]

    with patch("api.settings_store.get") as mock_get:
        mock_get.side_effect = lambda k, default=None: {
            "auto_continue": "on", "auto_continue_max": 2,
        }.get(k, default)
        events = asyncio.run(_drive())

    types = [e.get("type") for e in events]
    assert types.count("auto_continue") == 2, (
        f"expected exactly 2 auto-continues at cap=2, got {types.count('auto_continue')}"
    )
