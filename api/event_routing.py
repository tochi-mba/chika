"""Per-surface event routing.

Defines which event types each surface (CLI, frontend, extension) should
receive. The audit found drift — the extension silently dropped
``validation_warning``, ``thinking``, and ``shell_*`` events that the
frontend handles. By declaring the routes explicitly, surfaces that
intend to drop an event do so deliberately, and surfaces that should
handle a new event type are forced to consider it when the type is added.

Every event type in :class:`api.models.EventType` should appear in at
least one set below. The ``test_event_contract.py`` enforces this — a
drift-detection check that fails CI when a contributor adds a new event
type without thinking about routing.
"""
from __future__ import annotations

from api.models import EventType

# Events the CLI renders. The CLI runs in-process with the engine, so
# strictly speaking it sees everything — but we still declare the
# expected set so a drift between "engine emits" and "CLI handles" is
# visible to the contract tests.
CLI_EVENTS: frozenset[str] = frozenset({
    EventType.TOKEN.value,
    EventType.THINKING.value,
    EventType.THINKING_END.value,
    EventType.WORKFLOW_START.value,
    EventType.WORKFLOW_DONE.value,
    EventType.STEP_START.value,
    EventType.STEP_DONE.value,
    EventType.LOOP_ITERATION.value,
    EventType.CONDITION_EVAL.value,
    EventType.MAP_ITEM.value,
    EventType.RETRY_ATTEMPT.value,
    EventType.RETRY_BACKOFF.value,
    EventType.RETRY_NOTICE.value,
    EventType.TOOL_CALL.value,
    EventType.TOOL_RESULT.value,
    EventType.VARIABLE_SET.value,
    EventType.MEMORY_UPDATE.value,
    EventType.COMPACTION.value,
    EventType.VALIDATION_WARNING.value,
    EventType.DONE.value,
    EventType.ERROR.value,
    EventType.CANCELLED.value,
    EventType.CHAT_TITLE.value,
    EventType.PROFILE_INFO.value,
    EventType.PROFILE_SWITCH_DONE.value,
    EventType.SETTINGS_INFO.value,
    EventType.PET_CHANGED.value,
    EventType.RESET_DONE.value,
    EventType.APPROVAL_REQUIRED.value,
    EventType.SHELL_PROCESS_START.value,
    EventType.SHELL_OUTPUT.value,
    EventType.SHELL_PROCESS_DONE.value,
    EventType.SESSION_INFO.value,
    EventType.CHAT_LIST.value,
    EventType.EXTENSION_STATUS.value,
    EventType.SPOTIFY_AUTH_CHANGED.value,
})

# Events the Vue frontend handles. Lives in
# ``frontend/src/composables/useChika.js`` (audit ref).
FRONTEND_EVENTS: frozenset[str] = CLI_EVENTS

# Events the Chrome extension popup handles. Tighter than the frontend —
# the popup is a peek, not a full chat surface, so it skips low-signal
# events like raw `token` deltas and thinking traces.
#
# The drift-detection test enforces that any event NOT in this set is
# either in the explicit "drop on purpose" list below, or fails CI.
EXTENSION_EVENTS: frozenset[str] = frozenset({
    EventType.WORKFLOW_START.value,
    EventType.WORKFLOW_DONE.value,
    EventType.TOOL_CALL.value,
    EventType.TOOL_RESULT.value,
    EventType.DONE.value,
    EventType.ERROR.value,
    EventType.CANCELLED.value,
    EventType.PET_CHANGED.value,
    EventType.PROFILE_INFO.value,
    EventType.SETTINGS_INFO.value,
    EventType.EXT_CHAT_START.value,
    EventType.EXT_CHAT_TURN.value,
    EventType.EXT_CHAT_ERROR.value,
    EventType.EXT_CHAT_DONE.value,
    EventType.EXTENSION_STATUS.value,
    EventType.SPOTIFY_AUTH_CHANGED.value,
    EventType.PING.value,
    EventType.PONG.value,
})

# Events deliberately dropped by the extension popup.
EXTENSION_DROPS_ON_PURPOSE: frozenset[str] = frozenset({
    EventType.TOKEN.value,            # popup doesn't render streaming text
    EventType.THINKING.value,         # popup doesn't show reasoning
    EventType.THINKING_END.value,
    EventType.STEP_START.value,
    EventType.STEP_DONE.value,
    EventType.LOOP_ITERATION.value,
    EventType.CONDITION_EVAL.value,
    EventType.MAP_ITEM.value,
    EventType.RETRY_ATTEMPT.value,
    EventType.RETRY_BACKOFF.value,
    EventType.RETRY_NOTICE.value,
    EventType.VARIABLE_SET.value,
    EventType.MEMORY_UPDATE.value,
    EventType.COMPACTION.value,
    EventType.VALIDATION_WARNING.value,
    EventType.CHAT_TITLE.value,
    EventType.CHAT_LIST.value,
    EventType.SESSION_INFO.value,
    EventType.PROFILE_SWITCH_DONE.value,
    EventType.RESET_DONE.value,
    EventType.APPROVAL_REQUIRED.value,
    EventType.SHELL_PROCESS_START.value,
    EventType.SHELL_OUTPUT.value,
    EventType.SHELL_PROCESS_DONE.value,
})


def all_routed_events() -> frozenset[str]:
    """Every event that any surface either accepts or explicitly drops.

    The contract test asserts ``set(EventType) ==
    all_routed_events()`` — i.e. no event type is unrouted (silent drop
    was the bug we're trying to prevent).
    """
    return (
        CLI_EVENTS
        | FRONTEND_EVENTS
        | EXTENSION_EVENTS
        | EXTENSION_DROPS_ON_PURPOSE
    )
