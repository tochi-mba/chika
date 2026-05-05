"""Live-LLM smoke tests — actually call the configured upstream provider.

These tests cost real tokens. They are skipped by default. Run with::

    pytest tests/test_live_llm_smoke.py --live-llm
    # or
    CHIKA_RUN_LIVE_LLM=1 pytest tests/test_live_llm_smoke.py

Use them as the final pre-release checkpoint: the stub suite proves the
plumbing is correct; the live suite proves the *prompt* still works
against a real model.

The tests use whatever provider ``CHIKA_PROVIDER`` is set to and require
the matching API key. They are deliberately tolerant — they assert on
"the response is non-empty and not an error", not on exact wording,
because real LLMs don't repeat themselves byte-for-byte.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config as cfg

cfg.MAX_MEMORY_TOKENS = 1000
cfg.MAX_HISTORY_TOKENS = 10000
cfg.MAX_TOOL_TURNS = 5
cfg.GROUNDING_VALIDATE_RESPONSE = False

import pytest

from chika.core.engine import ChikaEngine
from chika.core.memory_manager import MemoryManager
from chika.core.prompt_builder import PromptBuilder
from chika.core.skill_registry import SkillRegistry
from chika.core.tool_registry import ToolDefinition, ToolRegistry
from chika.core.variable_store import VariableStore


# Every test here is gated by the live_llm marker — the conftest skips
# them unless --live-llm is passed.
pytestmark = [pytest.mark.live_llm, pytest.mark.slow]


def _have_provider_key() -> bool:
    """Return True iff the active provider has a key in env."""
    provider = os.environ.get("CHIKA_PROVIDER", "anthropic").lower()
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    if provider == "azure":
        return bool(os.environ.get("AZURE_OPENAI_KEY"))
    if provider == "ollama":
        return True   # local
    return False


@pytest.fixture
def live_engine(tmp_path):
    if not _have_provider_key():
        pytest.skip("no API key for the configured provider")
    # Make sure the stub script env var is NOT set (would short-circuit).
    os.environ.pop("CHIKA_STUB_LLM_SCRIPT", None)

    tools = ToolRegistry()
    vars_ = VariableStore()
    mem = MemoryManager(path=tmp_path / "memory.md", max_tokens=1000)
    prompt = PromptBuilder()
    skills = SkillRegistry(tools, mem, prompt)

    async def _echo(message: str = "hi", **_e) -> dict:
        return {"echo": message}

    tools.register(ToolDefinition(
        name="echo", description="echo back",
        parameters={"type": "object",
                    "properties": {"message": {"type": "string"}}},
        handler=_echo,
    ))
    return ChikaEngine(tools, vars_, mem, prompt, skills)


# ── The actual smoke flows ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_live_simple_text_response(live_engine: ChikaEngine):
    """The model can answer a trivial prompt."""
    events = [ev async for ev in live_engine.chat(
        "Reply with the single word 'pong' and nothing else."
    )]
    types = [e["type"] for e in events]
    assert "done" in types
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert text.strip(), "live LLM returned empty text"


@pytest.mark.asyncio
async def test_live_calls_a_tool_when_asked(live_engine: ChikaEngine):
    """The model can call workflow_orchestrator on request."""
    events = [ev async for ev in live_engine.chat(
        "Call the echo tool with message='live-llm-test' via "
        "workflow_orchestrator. Reply briefly after."
    )]
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert any(e.get("tool") == "echo" for e in tool_calls), (
        f"expected an echo tool call, got: {[e.get('tool') for e in tool_calls]}"
    )


@pytest.mark.asyncio
async def test_live_does_not_drift_on_simple_question(live_engine: ChikaEngine):
    """The model answers a factual yes/no without inventing a tool call."""
    events = [ev async for ev in live_engine.chat(
        "Is the sky usually blue during a clear day? Answer yes or no."
    )]
    text = "".join(e["text"] for e in events if e["type"] == "token").strip().lower()
    assert "yes" in text or "no" in text
