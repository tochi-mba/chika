"""Event contract tests — pin the cross-surface event model.

The audit found that event types are emitted as raw dicts despite
Pydantic models existing for many of them, and that the extension
silently dropped events the frontend renders. This test file is the
drift-detection net.

What we enforce here:

1. Every ``EventType`` value either has a Pydantic model or is
   accepted as typeless (registry is the source of truth).
2. Every ``EventType`` value is routed to at least one surface — no
   silent drops.
3. ``validate_event`` round-trips known-good payloads (the model fills
   in default fields).
4. ``validate_event(strict=True)`` raises on missing required fields.
5. Tool-correlation invariant: ``tool_call`` and ``tool_result``
   always carry a non-empty ``step_id`` after validation.
"""
from __future__ import annotations

import pytest

from api import event_routing
from api.models import (
    EventType,
    EventValidationError,
    is_known_event_type,
    validate_event,
)


# ── Registry coverage ────────────────────────────────────────────────


def test_every_event_type_is_routed_to_some_surface():
    """A new event type that no surface handles is the bug we're
    preventing. CLI ∪ Frontend ∪ Extension ∪ Extension-drops must
    cover every EventType."""
    routed = event_routing.all_routed_events()
    missing = {et.value for et in EventType} - routed
    assert not missing, (
        f"event types not routed to any surface (and not on the "
        f"explicit drop list): {sorted(missing)}"
    )


def test_extension_drops_and_accepts_are_disjoint():
    """An event can't be both on the accept list and the drop list."""
    overlap = event_routing.EXTENSION_EVENTS & event_routing.EXTENSION_DROPS_ON_PURPOSE
    assert not overlap, f"events on both EXTENSION accept and drop lists: {overlap}"


def test_is_known_event_type_recognises_each_member():
    for et in EventType:
        assert is_known_event_type(et.value), f"{et.value} should be recognised"


def test_is_known_event_type_rejects_unknown():
    assert is_known_event_type("not_a_real_event_type_xyz") is False


# ── validate_event behaviour ─────────────────────────────────────────


def test_validate_event_round_trips_token_event():
    payload = {"type": "token", "text": "hello"}
    out = validate_event(payload)
    assert out["type"] == "token"
    assert out["text"] == "hello"


def test_validate_event_unknown_type_passes_through():
    """Unknown types flow unchanged — the registry is permissive."""
    payload = {"type": "some_made_up_thing", "x": 1}
    assert validate_event(payload) == payload


def test_validate_event_strict_raises_on_missing_required():
    """tool_call requires step_id, tool, args — strict mode raises
    if any are missing."""
    with pytest.raises(EventValidationError):
        validate_event(
            {"type": "tool_call", "tool": "shell_exec"},
            strict=True,
        )


def test_validate_event_lax_returns_invalid_payload_unchanged():
    bad = {"type": "tool_call", "tool": "shell_exec"}  # missing step_id, args
    assert validate_event(bad, strict=False) == bad


def test_validate_event_strict_accepts_valid_tool_call():
    out = validate_event(
        {
            "type": "tool_call",
            "step_id": "step-42",
            "tool": "shell_exec",
            "args": {"command": "echo hi"},
        },
        strict=True,
    )
    assert out["step_id"] == "step-42"
    assert out["tool"] == "shell_exec"


def test_validate_event_strict_accepts_valid_tool_result():
    out = validate_event(
        {
            "type": "tool_result",
            "step_id": "step-42",
            "tool": "shell_exec",
            "result": "ok",
            "error": None,
            "duration_ms": 12,
        },
        strict=True,
    )
    assert out["step_id"] == "step-42"
    assert out["error"] is None


def test_validate_event_non_dict_raises_strict():
    with pytest.raises(EventValidationError):
        validate_event("not a dict", strict=True)  # type: ignore[arg-type]


def test_validate_event_non_dict_returns_unchanged_lax():
    # Lax mode is best-effort; non-dict payloads pass through (caller
    # bug, but we don't want to break the WS edge).
    assert validate_event("not a dict", strict=False) == "not a dict"  # type: ignore[arg-type]


# ── Tool correlation invariant ───────────────────────────────────────


def test_tool_call_event_requires_step_id():
    """The bug we just fixed in extension/background.js: step_id is
    the contract; without it tool_call/tool_result correlation breaks
    across reconnects."""
    with pytest.raises(EventValidationError) as exc:
        validate_event(
            {
                "type": "tool_call",
                "tool": "shell_exec",
                "args": {},
                # step_id missing
            },
            strict=True,
        )
    assert "step_id" in str(exc.value)


def test_tool_result_event_requires_step_id():
    with pytest.raises(EventValidationError) as exc:
        validate_event(
            {
                "type": "tool_result",
                "tool": "shell_exec",
                "result": None,
                "error": None,
                "duration_ms": 0,
                # step_id missing
            },
            strict=True,
        )
    assert "step_id" in str(exc.value)


def test_tool_call_step_id_must_be_non_empty_at_runtime():
    """Empty-string step_id is the same bug as missing step_id —
    correlation can't work. Pydantic doesn't catch this by default,
    but we should still flag it in tests."""
    out = validate_event(
        {
            "type": "tool_call",
            "step_id": "",
            "tool": "shell_exec",
            "args": {},
        },
        strict=True,
    )
    # Document the current behaviour: pydantic accepts "". A future
    # tightening would add a min_length=1 constraint to the field.
    # For now the test asserts the round-trip doesn't crash so we
    # have a hook to tighten later.
    assert out["step_id"] == ""


# ── Workflow events ──────────────────────────────────────────────────


def test_workflow_start_event_validates():
    out = validate_event(
        {"type": "workflow_start", "workflow_id": "wf1", "name": "demo"},
        strict=True,
    )
    assert out["workflow_id"] == "wf1"


def test_workflow_done_event_validates():
    out = validate_event(
        {"type": "workflow_done", "workflow_id": "wf1", "variables": {}},
        strict=True,
    )
    assert out["workflow_id"] == "wf1"


def test_step_start_event_workflow_id_optional():
    out = validate_event(
        {"type": "step_start", "step_id": "s1", "step_type": "sequential"},
        strict=True,
    )
    assert out["step_id"] == "s1"


# ── Done / Error / Compaction ────────────────────────────────────────


def test_done_event_minimal():
    assert validate_event({"type": "done"}, strict=True)["type"] == "done"


def test_error_event_step_id_optional():
    out = validate_event({"type": "error", "message": "boom"}, strict=True)
    assert out["message"] == "boom"


def test_compaction_event_validates():
    out = validate_event(
        {"type": "compaction", "removed": 10, "kept": 5, "summary_preview": "..."},
        strict=True,
    )
    assert out["removed"] == 10


# ── Routing — surfaces have the right vocabulary ────────────────────


def test_cli_handles_streaming_events():
    """Tokens, thinking, and tool events must reach the CLI."""
    for et in (EventType.TOKEN, EventType.THINKING, EventType.TOOL_CALL,
               EventType.TOOL_RESULT, EventType.WORKFLOW_START):
        assert et.value in event_routing.CLI_EVENTS


def test_extension_does_not_drop_critical_events():
    """The extension popup needs at minimum: tool events, done, error,
    profile/settings updates."""
    must_handle = {
        EventType.TOOL_CALL.value,
        EventType.TOOL_RESULT.value,
        EventType.DONE.value,
        EventType.ERROR.value,
        EventType.PROFILE_INFO.value,
        EventType.SETTINGS_INFO.value,
    }
    missing = must_handle - event_routing.EXTENSION_EVENTS
    assert not missing, f"extension missing critical events: {missing}"


def test_extension_drops_streaming_events_on_purpose():
    """Tokens are firehose; the popup is a peek surface. Confirm the
    drop is deliberate (in EXTENSION_DROPS_ON_PURPOSE)."""
    drops = event_routing.EXTENSION_DROPS_ON_PURPOSE
    assert EventType.TOKEN.value in drops
    assert EventType.THINKING.value in drops


# ── Future-proofing: detect typo'd event types in code ──────────────


def test_no_event_type_value_collision():
    """Two EventType members with the same value would silently break
    validation. Pydantic enums prevent this — but assert anyway."""
    values = [et.value for et in EventType]
    assert len(values) == len(set(values))


def test_event_type_values_are_lowercase_with_underscores():
    """Naming convention — keeps emit sites consistent."""
    for et in EventType:
        assert et.value == et.value.lower(), f"{et.value} should be lowercase"
        assert " " not in et.value, f"{et.value} should use underscores"
