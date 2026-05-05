from __future__ import annotations

from typing import Any

from pydantic import BaseModel

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
