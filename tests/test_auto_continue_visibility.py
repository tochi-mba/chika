"""When auto-continue COULD have fired but didn't, the engine MUST emit
a visible ``auto_continue_blocked`` event naming the reason. Previously
the conversation just stopped with no signal — the user thought the
agent was broken when it was actually waiting at the cap or with the
setting toggled off.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch


def _build_engine(turn_text: str):
    from api.session_manager import session_manager
    eng = session_manager.get_or_create("__auto_continue_visibility__")
    eng._history = []
    eng._title = ""
    eng._auto_continue_depth = 0
    eng._last_followup_text = ""

    state = {"i": 0}

    async def _fake_stream(self, _messages):
        i = state["i"]
        state["i"] += 1
        for tok in (turn_text if i == 0 else "All done.").split():
            yield {"type": "token", "text": tok + " "}

    async def _fake_complete(self, _prompt: str) -> str:
        return "Test"

    async def _fake_validate(self, _text: str):
        return None

    eng._stream_llm = _fake_stream.__get__(eng, type(eng))
    eng._llm_complete = _fake_complete.__get__(eng, type(eng))
    eng._validate_grounding = _fake_validate.__get__(eng, type(eng))
    return eng


def _drive(eng) -> list[dict]:
    async def _go():
        return [ev async for ev in eng.chat("kick it off")]
    return asyncio.run(_go())


def test_auto_continue_blocked_emits_event_when_setting_off():
    """Setting=off should still fire a visible diagnostic so the user
    knows WHY the agent stopped."""
    promise = "Step 1 done. Next, I'll start step 2."
    eng = _build_engine(promise)
    with patch("api.settings_store.get") as mock_get:
        mock_get.side_effect = lambda k, default=None: {
            "auto_continue": "off", "auto_continue_max": 10,
        }.get(k, default)
        events = _drive(eng)

    blocked = [e for e in events if e.get("type") == "auto_continue_blocked"]
    assert len(blocked) == 1, (
        f"expected exactly 1 auto_continue_blocked event, got "
        f"{[e.get('type') for e in events]}"
    )
    assert "off" in blocked[0]["reason"].lower(), blocked[0]
    # And no actual auto-continue fired.
    assert not any(e.get("type") == "auto_continue" for e in events)


def test_auto_continue_blocked_emits_event_when_cap_hit():
    """When depth has already hit the cap, surface that explicitly so
    the user knows to either /auto-continue max <higher> or type continue."""
    promise = "Step 5 done. Next, I'll start step 6."
    eng = _build_engine(promise)

    # Force the cap-hit on the first check by setting cap=0. The condition
    # ``depth < cap`` (``0 < 0``) is False so the gate refuses. This is
    # equivalent to the user-visible "I've already auto-continued N times"
    # case but doesn't depend on the chat() reset semantics.
    with patch("api.settings_store.get") as mock_get:
        mock_get.side_effect = lambda k, default=None: {
            "auto_continue": "on", "auto_continue_max": 0,
        }.get(k, default)
        events = _drive(eng)

    blocked = [e for e in events if e.get("type") == "auto_continue_blocked"]
    assert len(blocked) == 1, blocked
    msg = blocked[0]["reason"].lower()
    assert "cap" in msg
    assert "/auto-continue" in msg or "continue" in msg


def test_no_blocked_event_when_text_doesnt_match_continuation():
    """If the heuristic doesn't match, no event of either kind — silence
    is correct here (nothing to report)."""
    eng = _build_engine("Done. Let me know if you need anything else.")
    with patch("api.settings_store.get") as mock_get:
        mock_get.side_effect = lambda k, default=None: {
            "auto_continue": "on", "auto_continue_max": 10,
        }.get(k, default)
        events = _drive(eng)
    assert not any(e.get("type") in ("auto_continue", "auto_continue_blocked")
                    for e in events)


def test_default_cap_is_now_10():
    """Most multi-step plans need ≥7 turns. A cap of 5 was too low —
    the agent would silently stop mid-plan. We assert the *defaults
    table* directly because an existing settings.json on disk would
    mask the new default for upgraded users (init() only fills missing
    keys)."""
    from api.settings_store import _AUTO_CONTINUE_DEFAULTS
    assert _AUTO_CONTINUE_DEFAULTS["auto_continue_max"] == 10, (
        "default auto_continue_max regressed below 10 — reverting to "
        "the old cap silently stops multi-step plans mid-flight."
    )
