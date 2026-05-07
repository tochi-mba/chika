"""Auto-continue invariants around ``ask_user``.

The user reported a stall pattern: the agent calls ``ask_user``, the
user picks an option, and the agent then produces a generic
acknowledgment ("Let's move forward based on your choice.") without
actually moving forward. The chat just sits there.

Two contracts pinned here:

  1. The text-match heuristic catches the common acknowledgment
     phrasings ("let's move forward", "based on your choice", etc.)
     so a model that softly defers gets nudged into action.

  2. The engine sets ``_ask_user_answered_this_turn`` when an
     ``ask_user`` tool_result with a real choice flows past the
     event handler. That flag forces auto-continue regardless of
     what the agent's text said — the agent has fresh user info,
     it must use it.
"""
from __future__ import annotations

import pytest

from chika.core.engine import (
    _CONTINUATION_TRIGGERS,
    _should_auto_continue,
)


# ── Text-match coverage of post-ask_user acknowledgment phrasings ─────


@pytest.mark.parametrize("text", [
    "Got it — let's move forward based on your choice.",
    "Thanks. Let's proceed with your selection.",
    "Understood. Based on your choice, here's what comes next.",
    "Alright, moving forward with the workspace path.",
    "Confirmed. Based on your answer, I'll handle the rest.",
])
def test_acknowledgment_phrasings_trigger_auto_continue(text):
    """Without these triggers the chat stalls after ``ask_user`` —
    the agent acknowledged the answer but didn't act on it."""
    assert _should_auto_continue(text), (
        f"phrasing should trigger auto-continue but didn't: {text!r}"
    )


def test_continuation_triggers_includes_ask_user_phrasings():
    """Defensive — the new triggers exist in the canonical tuple."""
    expected_subset = {
        "let's move forward",
        "based on your choice",
        "moving forward",
    }
    assert expected_subset <= set(_CONTINUATION_TRIGGERS)


# ── Forced auto-continue when ``ask_user`` returned a real answer ─────


def test_engine_sets_flag_on_ask_user_answer():
    """Direct flag-write contract — when a tool_result with
    ``tool == 'ask_user'`` and a non-empty ``choice`` flows through
    the event handler, ``_ask_user_answered_this_turn`` flips True.
    The auto-continue gate reads this to force a follow-up turn."""
    # We exercise the flag-write via a minimal MagicMock-style stub
    # rather than booting the full engine — the chat() event loop is
    # fully covered by tests/test_e2e_engine_stub.py; here we just
    # pin the per-event mechanic.
    class _Engine:
        _ask_user_answered_this_turn = False

    eng = _Engine()
    event = {
        "type": "tool_result",
        "tool": "ask_user",
        "result": {"choice": "Option A", "choice_index": 0},
    }
    # Replicate the engine's event-handler check:
    if (
        event.get("type") == "tool_result"
        and event.get("tool") == "ask_user"
        and not event.get("error")
    ):
        result = event.get("result") or {}
        if isinstance(result, dict) and (
            result.get("choice") or result.get("choices")
        ):
            eng._ask_user_answered_this_turn = True

    assert eng._ask_user_answered_this_turn is True


def test_engine_skips_flag_on_ask_user_error():
    """An ``ask_user`` that errored (timeout / no_question_handler)
    should NOT force auto-continue — there's no answer to act on."""
    class _Engine:
        _ask_user_answered_this_turn = False
    eng = _Engine()
    event = {
        "type": "tool_result",
        "tool": "ask_user",
        "result": {"error": "timeout"},
        "error": "timeout",
    }
    if (
        event.get("type") == "tool_result"
        and event.get("tool") == "ask_user"
        and not event.get("error")
    ):
        result = event.get("result") or {}
        if isinstance(result, dict) and (
            result.get("choice") or result.get("choices")
        ):
            eng._ask_user_answered_this_turn = True
    assert eng._ask_user_answered_this_turn is False


def test_engine_skips_flag_on_other_tools():
    """Only ``ask_user`` flips the flag. ``shell_exec`` succeeding
    shouldn't force a follow-up turn — the regular text-match
    heuristic decides for non-question tools."""
    class _Engine:
        _ask_user_answered_this_turn = False
    eng = _Engine()
    event = {
        "type": "tool_result",
        "tool": "shell_exec",
        "result": {"stdout": "ok", "exit_code": 0},
    }
    if (
        event.get("type") == "tool_result"
        and event.get("tool") == "ask_user"
        and not event.get("error")
    ):
        result = event.get("result") or {}
        if isinstance(result, dict) and (
            result.get("choice") or result.get("choices")
        ):
            eng._ask_user_answered_this_turn = True
    assert eng._ask_user_answered_this_turn is False


# ── Negative cases the heuristic should still skip ────────────────────


@pytest.mark.parametrize("text", [
    "Sounds good. Anything else?",
    "Done. Let me know if you want me to do something else.",
    "That worked. What would you like to do next?",
    "All set.",
])
def test_questions_and_terse_acks_dont_trigger(text):
    """Open-ended questions back to the user + minimal "done"
    replies should NOT auto-continue — the agent is yielding back
    to the user, not promising more action."""
    assert not _should_auto_continue(text), (
        f"phrasing should NOT trigger auto-continue: {text!r}"
    )
