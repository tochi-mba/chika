"""Stub LLM that scripts a ChikaEngine through deterministic responses.

The real engine talks to Anthropic / Azure / Ollama via
``ChikaEngine._stream_llm``. For e2e tests we need byte-for-byte
reproducible behaviour, so this module monkey-patches that one method
to replay a scripted list of "turns" — each turn is either text-only
("the model said hello") or a workflow tool call ("the model called
file_write with these args").

Usage::

    from tests._helpers.stub_llm import StubLLM, install

    stub = StubLLM([
        StubLLM.text("Hello! Let me read that file."),
        StubLLM.workflow({
            "type": "sequential",
            "id":   "wf",
            "steps": [{"tool": "file_read",
                       "args": {"path": "x.py", "start_line": 1, "end_line": 5}}],
        }),
        StubLLM.text("Done. Here's the summary…"),
    ])
    install(engine, stub)

The stub runs ``len(turns)`` times max, then errors loudly so a runaway
agentic loop is visible in the test output.

The stub also handles ``_force_followup`` cleanly — when the engine asks
for a "summarise what just happened" turn after tool calls, the stub
serves the next scripted text response.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any


@dataclass
class _Turn:
    """One scripted turn. Either (text, None) or (text, workflow_dict)."""
    text: str
    workflow: dict | None = None


class StubLLM:
    """Scripted LLM driver. Hand it a list of turns; it replays them in order."""

    def __init__(self, turns: list[_Turn]) -> None:
        self._turns = list(turns)
        self._cursor = 0
        # Tracks every payload the engine asked us to "stream", so a test
        # can assert what messages reached the LLM (system prompt, tool
        # results, etc.).
        self.captured_messages: list[list[dict]] = []
        self.captured_completions: list[str] = []

    # ── Factories ──────────────────────────────────────────────────────────

    @staticmethod
    def text(text: str) -> _Turn:
        """The LLM produces plain text and no tool call."""
        return _Turn(text=text, workflow=None)

    @staticmethod
    def workflow(wf: dict, narrative: str = "") -> _Turn:
        """The LLM produces a workflow_orchestrator tool call.

        ``narrative`` is optional pre-tool text the model emits alongside
        the call (most providers strip this, the engine does too — but
        some tests want to verify the suppression behaviour).
        """
        return _Turn(text=narrative, workflow=dict(wf))

    # ── Engine integration ────────────────────────────────────────────────

    async def stream(self, messages: list[dict]) -> AsyncGenerator[dict, None]:
        """Drop-in replacement for ``ChikaEngine._stream_llm``."""
        self.captured_messages.append(list(messages))
        if self._cursor >= len(self._turns):
            raise AssertionError(
                "StubLLM ran out of scripted turns — the engine asked for "
                f"turn #{self._cursor + 1} but only {len(self._turns)} were "
                "scripted. Add more turns or check why the engine is looping."
            )
        turn = self._turns[self._cursor]
        self._cursor += 1

        # Stream the text tokens first (one chunk per word — close enough
        # to real provider behaviour without needing token budget tracking).
        if turn.text:
            for chunk in _chunk_text(turn.text):
                yield {"type": "token", "text": chunk}

        if turn.workflow is not None:
            yield {
                "type": "_tool_call_raw",
                "data": {
                    "id":   f"call_{uuid.uuid4().hex[:12]}",
                    "name": "workflow_orchestrator",
                    "args": turn.workflow,
                },
            }

    async def complete(self, prompt: str) -> str:
        """Drop-in replacement for ``ChikaEngine._llm_complete``.

        Used by ``_generate_title``, the skill-doc condenser, and meta-tools.
        Title generation runs concurrently with the first chat turn, so
        we can't consume from the same scripted list — return a canned
        short title instead. Tests that care about title content should
        set ``stub.title_response`` before driving a turn.
        """
        self.captured_completions.append(prompt)
        # Smart-ish defaults so common paths don't blow up:
        if "title" in prompt.lower() and "concise" in prompt.lower():
            return getattr(self, "title_response", "Test Chat")
        if "documentation condenser" in prompt:
            return getattr(self, "condense_response", "(condensed doc)")
        return getattr(self, "default_completion", "")

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def turns_consumed(self) -> int:
        return self._cursor

    @property
    def turns_remaining(self) -> int:
        return len(self._turns) - self._cursor


def _chunk_text(text: str) -> list[str]:
    """Split text into small chunks that mimic streamed token deltas."""
    if not text:
        return []
    # Split into words but keep trailing whitespace so reassembly equals input.
    words = text.split(" ")
    out: list[str] = []
    for i, w in enumerate(words):
        out.append(w if i == len(words) - 1 else w + " ")
    return out


def install(engine: Any, stub: StubLLM) -> StubLLM:
    """Monkey-patch ``engine._stream_llm`` and ``_llm_complete`` to use the stub.

    Returns the stub so tests can chain assertions:

        stub = install(engine, StubLLM([...]))
        events = [e async for e in engine.chat("hi")]
        assert stub.turns_consumed == 1
    """
    engine._stream_llm = stub.stream  # type: ignore[assignment]
    engine._llm_complete = stub.complete  # type: ignore[assignment]
    # Provider-specific paths short-circuit to the same hook now.
    return stub


# ── Helpers for common workflow shapes ────────────────────────────────────


def wf_sequential(*steps: dict, wf_id: str = "wf") -> dict:
    """Build a minimal sequential workflow with the given steps."""
    return {"type": "sequential", "id": wf_id, "steps": list(steps)}


def step(tool: str, args: dict | None = None, **kwargs: Any) -> dict:
    """Build a single workflow step."""
    s: dict = {"tool": tool, "args": args or {}}
    s.update(kwargs)
    return s


def assistant_text(turn_text: str) -> _Turn:
    """Alias of ``StubLLM.text`` for readable scripts."""
    return StubLLM.text(turn_text)


def assistant_workflow(wf: dict, narrative: str = "") -> _Turn:
    """Alias of ``StubLLM.workflow`` for readable scripts."""
    return StubLLM.workflow(wf, narrative=narrative)
