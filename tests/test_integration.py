"""Integration test — full chat turn through ChikaEngine with a mocked LLM."""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config as cfg

cfg.MAX_MEMORY_TOKENS = 1000
cfg.MAX_HISTORY_TOKENS = 10000
cfg.MAX_TOOL_TURNS = 10
cfg.COMPACT_KEEP_FIRST = 2
cfg.COMPACT_KEEP_LAST = 4
cfg.CHIKA_API_KEY = ""
cfg.GROUNDING_VALIDATE_RESPONSE = False

from chika.core.engine import ChikaEngine
from chika.core.memory_manager import MemoryManager
from chika.core.prompt_builder import PromptBuilder
from chika.core.skill_registry import SkillRegistry
from chika.core.tool_registry import ToolDefinition, ToolRegistry
from chika.core.variable_store import VariableStore

# ── Helpers ────────────────────────────────────────────────────────────────────

async def async_yield(*events):
    """Yield a fixed sequence of events as an async generator."""
    for e in events:
        yield e


def make_echo_tool():
    async def handler(message: str = "hello") -> dict:
        return {"echo": message}
    return ToolDefinition(
        name="echo",
        description="Echo a message",
        parameters={
            "type": "object",
            "properties": {"message": {"type": "string"}},
        },
        handler=handler,
    )


def make_engine():
    tool_registry = ToolRegistry()
    tool_registry.register(make_echo_tool())
    variable_store = VariableStore()
    memory_manager = MemoryManager(path="memory_test_integration.md")
    prompt_builder = PromptBuilder()
    skill_registry = SkillRegistry(
        tool_registry=tool_registry,
        memory_manager=memory_manager,
        prompt_builder=prompt_builder,
    )

    with patch("config.make_client", return_value=MagicMock()):
        engine = ChikaEngine(
            tool_registry=tool_registry,
            variable_store=variable_store,
            memory_manager=memory_manager,
            prompt_builder=prompt_builder,
            skill_registry=skill_registry,
        )
    return engine


async def collect_events(engine: ChikaEngine, user_input: str) -> list[dict]:
    events = []
    async for event in engine.chat(user_input):
        events.append(event)
    return events


# ── Turn 1: workflow call → turn 2: text response ─────────────────────────────

WORKFLOW_ARGS = {
    "type": "sequential",
    "id": "test_seq",
    "steps": [{"tool": "echo", "args": {"message": "integration"}}],
}


def make_turn1_stream():
    """Simulates the LLM making a workflow_orchestrator tool call."""
    async def _gen(*args, **kwargs):
        yield {
            "type": "_tool_call_raw",
            "data": {
                "id": "tc_001",
                "name": "workflow_orchestrator",
                "args": WORKFLOW_ARGS,
            },
        }
    return _gen


def make_turn2_stream():
    """Simulates the LLM returning final text tokens."""
    async def _gen(*args, **kwargs):
        yield {"type": "token", "text": "Done! "}
        yield {"type": "token", "text": "The echo ran successfully."}
    return _gen


@pytest.mark.asyncio
async def test_full_chat_turn_event_types():
    """All expected event types must be present in a full chat turn."""
    engine = make_engine()

    call_count = 0

    async def mock_stream_llm(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            async for e in make_turn1_stream()(messages):
                yield e
        else:
            async for e in make_turn2_stream()(messages):
                yield e

    with patch.object(engine, "_stream_llm", side_effect=mock_stream_llm):
        # Also suppress title generation to avoid LLM calls
        with patch.object(engine, "_generate_title", new_callable=AsyncMock, return_value="Test"):
            events = await collect_events(engine, "run the echo")

    event_types = {e["type"] for e in events}
    assert "workflow_start" in event_types, f"Missing workflow_start in {event_types}"
    assert "tool_call" in event_types, f"Missing tool_call in {event_types}"
    assert "tool_result" in event_types, f"Missing tool_result in {event_types}"
    assert "token" in event_types, f"Missing token in {event_types}"
    assert "done" in event_types, f"Missing done in {event_types}"


@pytest.mark.asyncio
async def test_full_chat_turn_done_is_last():
    """done event must be the last event emitted."""
    engine = make_engine()
    call_count = 0

    async def mock_stream_llm(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            async for e in make_turn1_stream()(messages):
                yield e
        else:
            async for e in make_turn2_stream()(messages):
                yield e

    with patch.object(engine, "_stream_llm", side_effect=mock_stream_llm):
        with patch.object(engine, "_generate_title", new_callable=AsyncMock, return_value="Test"):
            events = await collect_events(engine, "run the echo")

    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_full_chat_turn_tool_result_has_echo():
    """tool_result event should contain the echo tool's output."""
    engine = make_engine()
    call_count = 0

    async def mock_stream_llm(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            async for e in make_turn1_stream()(messages):
                yield e
        else:
            async for e in make_turn2_stream()(messages):
                yield e

    with patch.object(engine, "_stream_llm", side_effect=mock_stream_llm):
        with patch.object(engine, "_generate_title", new_callable=AsyncMock, return_value="Test"):
            events = await collect_events(engine, "run the echo")

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert tool_results, "No tool_result events found"
    assert any("echo" in json.dumps(e.get("result", {})) for e in tool_results)


@pytest.mark.asyncio
async def test_plain_text_response_no_workflow():
    """When the LLM returns plain text, only token + done events are emitted."""
    engine = make_engine()

    async def mock_stream_llm(messages):
        yield {"type": "token", "text": "Hello, world!"}

    with patch.object(engine, "_stream_llm", side_effect=mock_stream_llm):
        with patch.object(engine, "_generate_title", new_callable=AsyncMock, return_value="Test"):
            events = await collect_events(engine, "say hello")

    event_types = {e["type"] for e in events}
    assert "token" in event_types
    assert "done" in event_types
    assert "workflow_start" not in event_types
    assert "tool_call" not in event_types


@pytest.mark.asyncio
async def test_history_grows_after_turn():
    """After a chat turn, history should have at least user + assistant messages."""
    engine = make_engine()

    async def mock_stream_llm(messages):
        yield {"type": "token", "text": "Acknowledged."}

    with patch.object(engine, "_stream_llm", side_effect=mock_stream_llm):
        with patch.object(engine, "_generate_title", new_callable=AsyncMock, return_value="Test"):
            await collect_events(engine, "hello")

    roles = [m["role"] for m in engine._history]
    assert "user" in roles
    assert "assistant" in roles
