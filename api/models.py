from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ValidationError

# ── Inbound (client → server) ────────────────────────────────────────────────

class UserMessage(BaseModel):
    type: str = "user_message"
    text: str
    session_id: str = ""


# ── Outbound events (server → client) ────────────────────────────────────────

class TokenEvent(BaseModel):
    type: str = "token"
    text: str

class WorkflowStartEvent(BaseModel):
    type: str = "workflow_start"
    workflow_id: str
    name: str

class StepStartEvent(BaseModel):
    type: str = "step_start"
    step_id: str
    step_type: str
    workflow_id: str | None = None

class ToolCallEvent(BaseModel):
    type: str = "tool_call"
    step_id: str
    tool: str
    args: dict[str, Any]

class ToolResultEvent(BaseModel):
    type: str = "tool_result"
    step_id: str
    tool: str
    result: Any
    error: str | None
    duration_ms: int

class VariableSetEvent(BaseModel):
    type: str = "variable_set"
    name: str
    var_type: str
    size_bytes: int
    value_preview: str = ""

class ConditionEvalEvent(BaseModel):
    type: str = "condition_eval"
    step_id: str
    condition: dict
    result: bool

class LoopIterationEvent(BaseModel):
    type: str = "loop_iteration"
    step_id: str
    iteration: int
    max: int

class MapItemEvent(BaseModel):
    type: str = "map_item"
    step_id: str
    index: int
    total: int

class RetryAttemptEvent(BaseModel):
    type: str = "retry_attempt"
    step_id: str
    attempt: int
    max: int

class StepDoneEvent(BaseModel):
    type: str = "step_done"
    step_id: str
    duration_ms: int

class WorkflowDoneEvent(BaseModel):
    type: str = "workflow_done"
    workflow_id: str
    variables: dict[str, Any]

class MemoryUpdateEvent(BaseModel):
    type: str = "memory_update"
    key: str
    value: str

class CompactionEvent(BaseModel):
    type: str = "compaction"
    removed: int
    kept: int
    summary_preview: str = ""

class DoneEvent(BaseModel):
    type: str = "done"

class ErrorEvent(BaseModel):
    type: str = "error"
    message: str
    step_id: str | None = None


class PlanArchivedEvent(BaseModel):
    """Fired when ``plan_set`` auto-archives the previous plan, OR
    when ``plan_archive`` is explicitly called. Lets every UI surface
    show a brief "archived" chip + an updated history count without
    polling. Carries summary fields only — never the full task list,
    so the event stays small enough to broadcast cheaply."""
    type: str = "plan_archived"
    auto: bool = False
    goal: str | None = None
    reason: str | None = None
    tasks_total: int = 0
    tasks_done: int = 0
    archived_at: float | None = None
    superseded_by: str | None = None
    history_count: int = 0
    source: str | None = None


class SpotifyAuthChangedEvent(BaseModel):
    """Broadcast whenever a profile's Spotify connection state flips
    (auth completes, user disconnects, refresh fails). Surfaces use it
    to swap their UI without polling the status endpoint. Never carries
    raw tokens — only display-name + product tier."""
    type: str = "spotify_auth_changed"
    authorized: bool
    display_name: str | None = None
    product: str | None = None
    error: str | None = None


# ── REST response models ──────────────────────────────────────────────────────

class SessionInfo(BaseModel):
    session_id: str
    message_count: int
    variable_count: int

class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict

class SkillInfo(BaseModel):
    name: str
    description: str
    tools: list[str]
    workflow_examples: str

class VariableInfo(BaseModel):
    name: str
    type: str
    size_bytes: int
    description: str

class MemoryEntryInfo(BaseModel):
    key: str
    value: str
    created: str
    accessed: int
    ttl_days: int | None


class SettingsPatch(BaseModel):
    autonomy: str | None = None
    tool_permissions: dict[str, str] | None = None
    pet_speech: str | None = None
    pet_speech_tokens: int | None = None
    auto_continue: str | None = None
    auto_continue_max: int | None = None
    # ``skills_disabled`` is the dynamic-skill toggle list — a flip
    # here triggers session_manager.reload_skills() server-side so
    # tool availability changes mid-session without a restart.
    skills_disabled: list[str] | None = None
    spotify_share_across_profiles: str | None = None
    spotify_profile_overrides: dict[str, bool] | None = None


# ── Event contract — single source of truth ──────────────────────────────────
#
# Every event the engine emits belongs to one of these types. Surfaces (CLI,
# frontend, extension) consume these names. Adding a new event means:
#
#   1. Add the type to ``EventType``
#   2. Add a Pydantic model above (or accept that it's typeless)
#   3. Add it to the right surface set in ``api/event_routing.py``
#   4. Update ``test_event_contract.py``
#
# The audit (Phase 0 of the system-hardening plan) found 35+ event types
# already in flight. We're enumerating them here so drift becomes visible.


class EventType(str, Enum):  # noqa: UP042 — keep multiple-inheritance form for back-compat with `str(EventType.TOKEN)` callers
    # LLM streaming
    TOKEN = "token"
    THINKING = "thinking"
    THINKING_END = "thinking_end"
    # Workflow
    WORKFLOW_START = "workflow_start"
    WORKFLOW_DONE = "workflow_done"
    STEP_START = "step_start"
    STEP_DONE = "step_done"
    LOOP_ITERATION = "loop_iteration"
    CONDITION_EVAL = "condition_eval"
    MAP_ITEM = "map_item"
    RETRY_ATTEMPT = "retry_attempt"
    RETRY_BACKOFF = "retry_backoff"
    RETRY_NOTICE = "retry_notice"
    # Tools
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    VARIABLE_SET = "variable_set"
    # Memory + compaction
    MEMORY_UPDATE = "memory_update"
    COMPACTION = "compaction"
    # Validation
    VALIDATION_WARNING = "validation_warning"
    # Lifecycle
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"
    # State broadcasts
    CHAT_TITLE = "chat_title"
    CHAT_LIST = "chat_list"
    SESSION_INFO = "session_info"
    PROFILE_INFO = "profile_info"
    PROFILE_SWITCH_DONE = "profile_switch_done"
    SETTINGS_INFO = "settings_info"
    PET_CHANGED = "pet_changed"
    EXTENSION_STATUS = "extension_status"
    RESET_DONE = "reset_done"
    APPROVAL_REQUIRED = "approval_required"
    # Plan
    PLAN_ARCHIVED = "plan_archived"
    # Integrations
    SPOTIFY_AUTH_CHANGED = "spotify_auth_changed"
    # Shell
    SHELL_PROCESS_START = "shell_process_start"
    SHELL_OUTPUT = "shell_output"
    SHELL_PROCESS_DONE = "shell_process_done"
    # Extension-only relay
    EXT_CHAT_START = "ext_chat_start"
    EXT_CHAT_TURN = "ext_chat_turn"
    EXT_CHAT_ERROR = "ext_chat_error"
    EXT_CHAT_DONE = "ext_chat_done"
    # Heartbeat
    PING = "ping"
    PONG = "pong"


# Map from EventType value → strict Pydantic model. Events whose value isn't
# in this map are accepted as-is (typeless events, e.g. metadata broadcasts
# whose payload changes too often to model strictly).
_TYPED_MODELS: dict[str, type[BaseModel]] = {
    EventType.TOKEN.value:           TokenEvent,
    EventType.WORKFLOW_START.value:  WorkflowStartEvent,
    EventType.WORKFLOW_DONE.value:   WorkflowDoneEvent,
    EventType.STEP_START.value:      StepStartEvent,
    EventType.STEP_DONE.value:       StepDoneEvent,
    EventType.TOOL_CALL.value:       ToolCallEvent,
    EventType.TOOL_RESULT.value:     ToolResultEvent,
    EventType.VARIABLE_SET.value:    VariableSetEvent,
    EventType.LOOP_ITERATION.value:  LoopIterationEvent,
    EventType.CONDITION_EVAL.value:  ConditionEvalEvent,
    EventType.MAP_ITEM.value:        MapItemEvent,
    EventType.RETRY_ATTEMPT.value:   RetryAttemptEvent,
    EventType.MEMORY_UPDATE.value:   MemoryUpdateEvent,
    EventType.COMPACTION.value:      CompactionEvent,
    EventType.DONE.value:            DoneEvent,
    EventType.ERROR.value:           ErrorEvent,
    EventType.SPOTIFY_AUTH_CHANGED.value: SpotifyAuthChangedEvent,
    EventType.PLAN_ARCHIVED.value:        PlanArchivedEvent,
}


class EventValidationError(ValueError):
    """Raised when an event payload doesn't conform to its declared type."""


def validate_event(payload: dict, *, strict: bool = False) -> dict:
    """Validate ``payload`` against the registered model for its ``type``.

    Three modes:

      - **Known type, valid payload** → returns payload (dict round-trip via
        the model so default fields are filled in).
      - **Known type, invalid payload** → raises :class:`EventValidationError`
        when ``strict=True``; otherwise returns the payload unchanged so the
        WS edge keeps flowing (validation is observability, not gatekeeping).
      - **Unknown type** → returns payload unchanged in either mode. We
        deliberately *don't* raise on unknown types — the event registry
        grows organically and we don't want to break production every time
        the engine adds a new event type.

    Strict mode is intended for tests (``test_event_contract.py``) so a
    drifted contract fails CI instead of silently propagating.

    Why we don't enforce strict mode at the WS edge: the audit identified
    35+ event types in flight, only 16 of which have models. Enforcing all
    of them would block the WS edge until every type has a model. Strict
    mode is opt-in for tests; production runs in observability mode.
    """
    if not isinstance(payload, dict):
        if strict:
            raise EventValidationError(f"event payload must be a dict, got {type(payload).__name__}")
        return payload  # best-effort

    etype = payload.get("type")
    model = _TYPED_MODELS.get(etype) if isinstance(etype, str) else None
    if model is None:
        return payload

    try:
        validated = model(**payload)
    except ValidationError as exc:
        if strict:
            raise EventValidationError(
                f"event {etype!r} failed validation: {exc.errors()}",
            ) from exc
        return payload
    return validated.model_dump()


def is_known_event_type(name: str) -> bool:
    return any(et.value == name for et in EventType)
