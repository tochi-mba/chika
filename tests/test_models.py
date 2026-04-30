"""Tests for api/models.py — all 18 Pydantic models."""
from __future__ import annotations

import pytest
from api.models import (
    CompactionEvent,
    ConditionEvalEvent,
    DoneEvent,
    ErrorEvent,
    LoopIterationEvent,
    MapItemEvent,
    MemoryEntryInfo,
    MemoryUpdateEvent,
    RetryAttemptEvent,
    SessionInfo,
    SkillInfo,
    StepDoneEvent,
    StepStartEvent,
    ToolCallEvent,
    ToolInfo,
    ToolResultEvent,
    UserMessage,
    VariableInfo,
    VariableSetEvent,
    WorkflowDoneEvent,
    WorkflowStartEvent,
    TokenEvent,
)


class TestUserMessage:
    def test_defaults(self):
        m = UserMessage(text="hello")
        assert m.type == "user_message"
        assert m.text == "hello"
        assert m.session_id == ""

    def test_explicit_fields(self):
        m = UserMessage(text="hi", session_id="abc123", type="user_message")
        assert m.session_id == "abc123"


class TestTokenEvent:
    def test_defaults(self):
        e = TokenEvent(text="tok")
        assert e.type == "token"
        assert e.text == "tok"


class TestWorkflowStartEvent:
    def test_fields(self):
        e = WorkflowStartEvent(workflow_id="wf1", name="My Workflow")
        assert e.type == "workflow_start"
        assert e.workflow_id == "wf1"
        assert e.name == "My Workflow"


class TestStepStartEvent:
    def test_defaults(self):
        e = StepStartEvent(step_id="s1", step_type="sequential")
        assert e.type == "step_start"
        assert e.workflow_id is None

    def test_with_workflow(self):
        e = StepStartEvent(step_id="s1", step_type="parallel", workflow_id="wf1")
        assert e.workflow_id == "wf1"


class TestToolCallEvent:
    def test_fields(self):
        e = ToolCallEvent(step_id="s1", tool="web_search", args={"query": "test"})
        assert e.type == "tool_call"
        assert e.tool == "web_search"
        assert e.args == {"query": "test"}


class TestToolResultEvent:
    def test_fields(self):
        e = ToolResultEvent(step_id="s1", tool="web_search", result={"count": 3},
                            error=None, duration_ms=120)
        assert e.type == "tool_result"
        assert e.error is None
        assert e.duration_ms == 120

    def test_with_error(self):
        e = ToolResultEvent(step_id="s1", tool="web_search", result=None,
                            error="timeout", duration_ms=5000)
        assert e.error == "timeout"


class TestVariableSetEvent:
    def test_defaults(self):
        e = VariableSetEvent(name="$foo", var_type="text", size_bytes=42)
        assert e.type == "variable_set"
        assert e.value_preview == ""

    def test_with_preview(self):
        e = VariableSetEvent(name="$bar", var_type="json", size_bytes=10,
                             value_preview="{'key': 1}")
        assert e.value_preview == "{'key': 1}"


class TestConditionEvalEvent:
    def test_fields(self):
        cond = {"field": "$x", "operator": "equals", "value": True}
        e = ConditionEvalEvent(step_id="s1", condition=cond, result=True)
        assert e.type == "condition_eval"
        assert e.result is True


class TestLoopIterationEvent:
    def test_fields(self):
        e = LoopIterationEvent(step_id="s1", iteration=2, max=5)
        assert e.type == "loop_iteration"
        assert e.iteration == 2
        assert e.max == 5


class TestMapItemEvent:
    def test_fields(self):
        e = MapItemEvent(step_id="s1", index=0, total=3)
        assert e.type == "map_item"
        assert e.index == 0
        assert e.total == 3


class TestRetryAttemptEvent:
    def test_fields(self):
        e = RetryAttemptEvent(step_id="s1", attempt=1, max=3)
        assert e.type == "retry_attempt"
        assert e.attempt == 1
        assert e.max == 3


class TestStepDoneEvent:
    def test_fields(self):
        e = StepDoneEvent(step_id="s1", duration_ms=250)
        assert e.type == "step_done"
        assert e.duration_ms == 250


class TestWorkflowDoneEvent:
    def test_fields(self):
        e = WorkflowDoneEvent(workflow_id="wf1", variables={"$x": 42})
        assert e.type == "workflow_done"
        assert e.variables == {"$x": 42}


class TestMemoryUpdateEvent:
    def test_fields(self):
        e = MemoryUpdateEvent(key="note", value="remember this")
        assert e.type == "memory_update"
        assert e.key == "note"
        assert e.value == "remember this"


class TestCompactionEvent:
    def test_defaults(self):
        e = CompactionEvent(removed=5, kept=10)
        assert e.type == "compaction"
        assert e.summary_preview == ""

    def test_with_preview(self):
        e = CompactionEvent(removed=3, kept=7, summary_preview="summary text")
        assert e.summary_preview == "summary text"


class TestDoneEvent:
    def test_default(self):
        e = DoneEvent()
        assert e.type == "done"


class TestErrorEvent:
    def test_defaults(self):
        e = ErrorEvent(message="something broke")
        assert e.type == "error"
        assert e.step_id is None

    def test_with_step(self):
        e = ErrorEvent(message="tool failed", step_id="s3")
        assert e.step_id == "s3"


class TestSessionInfo:
    def test_fields(self):
        s = SessionInfo(session_id="sess1", message_count=5, variable_count=2)
        assert s.session_id == "sess1"
        assert s.message_count == 5
        assert s.variable_count == 2


class TestToolInfo:
    def test_fields(self):
        t = ToolInfo(name="web_search", description="Search the web",
                     parameters={"type": "object"})
        assert t.name == "web_search"
        assert t.parameters == {"type": "object"}


class TestSkillInfo:
    def test_fields(self):
        s = SkillInfo(name="web", description="Web tools",
                      tools=["web_search", "web_fetch"], workflow_examples="example")
        assert s.name == "web"
        assert len(s.tools) == 2


class TestVariableInfo:
    def test_fields(self):
        v = VariableInfo(name="$result", type="json", size_bytes=128,
                         description="search results")
        assert v.name == "$result"
        assert v.type == "json"


class TestMemoryEntryInfo:
    def test_fields(self):
        m = MemoryEntryInfo(key="note", value="text", created="2024-01-01T00:00:00",
                            accessed=3, ttl_days=7)
        assert m.key == "note"
        assert m.ttl_days == 7

    def test_no_ttl(self):
        m = MemoryEntryInfo(key="note", value="text", created="2024-01-01T00:00:00",
                            accessed=0, ttl_days=None)
        assert m.ttl_days is None
