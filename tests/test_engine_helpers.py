"""Targeted coverage for chika/core/engine.py pure helpers.

The full ChikaEngine wiring is heavy (LLM client, profile, skill registry,
etc.), but several module-level + static helpers are easy to exercise:

- ``_normalise_text`` — Unicode punctuation normaliser
- ``_should_auto_continue`` — paragraph-tail heuristic
- ``_is_workflow`` / ``_is_step`` / ``_wrap_step``
- ``_extract_workflow_json`` — fenced + bare JSON extraction
- ``_StubScriptRunner`` — deterministic LLM playback for tests
- ``ChikaEngine._compute_thinking_budget`` (staticmethod, no ``self``)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chika.core import engine as e


# ── _normalise_text ────────────────────────────────────────────────────


def test_normalise_text_lowercases():
    assert e._normalise_text("HELLO") == "hello"


def test_normalise_text_replaces_curly_apostrophes():
    """U+2019 (right single quote) → U+0027 (ASCII apostrophe)."""
    assert e._normalise_text("I’ll do it") == "i'll do it"


def test_normalise_text_replaces_curly_double_quotes():
    assert e._normalise_text("“hi”") == '"hi"'


def test_normalise_text_replaces_dashes():
    """em / en / minus all flatten to ASCII hyphen."""
    assert e._normalise_text("a—b–c−d") == "a-b-c-d"


def test_normalise_text_preserves_ascii():
    assert e._normalise_text("plain ascii here") == "plain ascii here"


# ── _should_auto_continue ──────────────────────────────────────────────


def test_should_auto_continue_short_text_returns_false():
    """Below 20 chars after strip → false."""
    assert e._should_auto_continue("ok") is False


def test_should_auto_continue_empty_returns_false():
    assert e._should_auto_continue("") is False


def test_should_auto_continue_question_returns_false():
    """A question is not a promise — even with a continuation phrase before."""
    assert e._should_auto_continue(
        "Done. Next, I'll add the camera. Want me to?",
    ) is False


def test_should_auto_continue_question_with_curly_quote_returns_false():
    """The trailing `?` should be detected after curly quotes are stripped."""
    text = "Sure thing.” Now I'll continue?"
    assert e._should_auto_continue(text) is False


def test_should_auto_continue_with_next_phrase():
    text = "Saved the file.\n\nNext, I'll add the camera and lighting."
    assert e._should_auto_continue(text) is True


def test_should_auto_continue_with_curly_apostrophe():
    text = "Saved.\n\nNext, I’ll write the readme."
    assert e._should_auto_continue(text) is True


def test_should_auto_continue_now_phrase():
    text = "I read the file.\n\nNow I'll implement the missing function."
    assert e._should_auto_continue(text) is True


def test_should_auto_continue_phrase_must_be_in_last_paragraph():
    """A continuation phrase only in an earlier paragraph → false (only the
    last paragraph is checked)."""
    text = (
        "Now I'll do the first step.\n\n"
        "Everything looks great and the change is finished cleanly."
    )
    assert e._should_auto_continue(text) is False


def test_should_auto_continue_no_trigger_returns_false():
    text = "All done — the file is saved and the tests are green."
    assert e._should_auto_continue(text) is False


def test_should_auto_continue_continuing_with():
    text = "OK saved.\n\nContinuing with the rest of the implementation."
    assert e._should_auto_continue(text) is True


# ── _is_workflow / _is_step / _wrap_step ──────────────────────────────


def test_is_workflow_basic_sequential():
    wf = {"type": "sequential", "steps": [{"tool": "x", "args": {}}]}
    assert e._is_workflow(wf) is True


def test_is_workflow_loop_with_steps():
    wf = {"type": "loop", "steps": [], "condition": {}}
    assert e._is_workflow(wf) is True


def test_is_workflow_unknown_type():
    assert e._is_workflow({"type": "invalid", "steps": []}) is False


def test_is_workflow_missing_steps_branches_step():
    """Type matches but no payload → false."""
    assert e._is_workflow({"type": "sequential"}) is False


def test_is_workflow_non_dict():
    assert e._is_workflow("not a dict") is False
    assert e._is_workflow(None) is False


def test_is_step_with_tool():
    assert e._is_step({"tool": "file_read", "args": {}}) is True


def test_is_step_without_tool():
    assert e._is_step({"args": {}}) is False


def test_is_step_non_string_tool():
    assert e._is_step({"tool": 123}) is False


def test_is_step_non_dict():
    assert e._is_step([{"tool": "x"}]) is False


def test_wrap_step_creates_sequential():
    wrapped = e._wrap_step({"tool": "x", "args": {}})
    assert wrapped["type"] == "sequential"
    assert wrapped["steps"] == [{"tool": "x", "args": {}}]


# ── _extract_workflow_json ────────────────────────────────────────────


def test_extract_workflow_json_in_fences():
    text = (
        "Here's the workflow:\n"
        '```json\n{"type": "sequential", "steps": [{"tool": "x", "args": {}}]}\n```'
    )
    extracted = e._extract_workflow_json(text)
    assert extracted is not None
    wf, clean = extracted
    assert wf["type"] == "sequential"
    assert "Here's" in clean


def test_extract_workflow_json_bare_object():
    text = 'Doing it: {"type": "sequential", "steps": [{"tool": "f", "args": {}}]} done'
    extracted = e._extract_workflow_json(text)
    assert extracted is not None
    wf, clean = extracted
    assert wf["type"] == "sequential"


def test_extract_workflow_json_step_wrapped():
    """A bare {tool: x, args: ...} gets wrapped into a sequential."""
    text = '{"tool": "file_read", "args": {"path": "x"}}'
    extracted = e._extract_workflow_json(text)
    assert extracted is not None
    wf, _ = extracted
    assert wf["type"] == "sequential"
    assert wf["steps"][0]["tool"] == "file_read"


def test_extract_workflow_json_no_json_returns_none():
    assert e._extract_workflow_json("just plain text, no json here") is None


def test_extract_workflow_json_invalid_json_in_fence():
    text = "```json\n{not actually json}\n```"
    assert e._extract_workflow_json(text) is None


def test_extract_workflow_json_picks_first_workflow():
    """When multiple objects exist, the first matching workflow is chosen."""
    text = (
        '{"foo": "bar"} '
        '{"type": "sequential", "steps": [{"tool": "x", "args": {}}]}'
    )
    extracted = e._extract_workflow_json(text)
    assert extracted is not None
    wf, _ = extracted
    assert wf["type"] == "sequential"


def test_extract_workflow_json_caps_input_size():
    """Input over 50KB is truncated; valid workflow inside the cap is found."""
    prefix = "x" * 49_000
    suffix = '{"type": "sequential", "steps": [{"tool": "f", "args": {}}]}'
    extracted = e._extract_workflow_json(prefix + " " + suffix)
    assert extracted is not None


def test_extract_workflow_json_unbalanced_braces():
    """Unbalanced braces → no extraction (no infinite loop)."""
    text = "{ broken { stuff }"
    assert e._extract_workflow_json(text) is None


# ── _StubScriptRunner ─────────────────────────────────────────────────


def test_stub_runner_loads_script(tmp_path):
    script = tmp_path / "stub.json"
    script.write_text(json.dumps({
        "turns": [{"text": "hello"}],
        "title": "Test",
        "completions": ["c1", "c2"],
    }))
    runner = e._StubScriptRunner(str(script))
    assert runner._title == "Test"
    assert runner._completions == ["c1", "c2"]


def test_stub_runner_default_title(tmp_path):
    script = tmp_path / "stub.json"
    script.write_text(json.dumps({"turns": []}))
    runner = e._StubScriptRunner(str(script))
    assert runner._title == "Stub Chat"


@pytest.mark.asyncio
async def test_stub_runner_stream_yields_tokens(tmp_path):
    script = tmp_path / "stub.json"
    script.write_text(json.dumps({
        "turns": [{"text": "hello world"}],
    }))
    runner = e._StubScriptRunner(str(script))
    events = [ev async for ev in runner.stream()]
    # Words "hello" + "world" → 2 token events.
    tokens = [ev for ev in events if ev["type"] == "token"]
    assert len(tokens) == 2


@pytest.mark.asyncio
async def test_stub_runner_stream_yields_workflow(tmp_path):
    script = tmp_path / "stub.json"
    workflow = {"type": "sequential", "steps": [{"tool": "x", "args": {}}]}
    script.write_text(json.dumps({
        "turns": [{"text": "", "workflow": workflow}],
    }))
    runner = e._StubScriptRunner(str(script))
    events = [ev async for ev in runner.stream()]
    raw = [ev for ev in events if ev["type"] == "_tool_call_raw"]
    assert len(raw) == 1
    assert raw[0]["data"]["name"] == "workflow_orchestrator"
    assert raw[0]["data"]["args"] == workflow


@pytest.mark.asyncio
async def test_stub_runner_stream_exhausted(tmp_path):
    """Once turns are exhausted, stream emits a sentinel token."""
    script = tmp_path / "stub.json"
    script.write_text(json.dumps({"turns": []}))
    runner = e._StubScriptRunner(str(script))
    events = [ev async for ev in runner.stream()]
    assert len(events) == 1
    assert "ran out of scripted turns" in events[0]["text"]


@pytest.mark.asyncio
async def test_stub_runner_complete_returns_title_for_title_prompt(tmp_path):
    script = tmp_path / "stub.json"
    script.write_text(json.dumps({"turns": [], "title": "My Chat"}))
    runner = e._StubScriptRunner(str(script))
    out = await runner.complete("Generate a concise title for this chat")
    assert out == "My Chat"


@pytest.mark.asyncio
async def test_stub_runner_complete_returns_canned_completions(tmp_path):
    script = tmp_path / "stub.json"
    script.write_text(json.dumps({
        "turns": [],
        "completions": ["A", "B"],
    }))
    runner = e._StubScriptRunner(str(script))
    a = await runner.complete("anything")
    b = await runner.complete("anything")
    c = await runner.complete("anything")  # exhausted
    assert a == "A"
    assert b == "B"
    assert c == ""


# ── _compute_thinking_budget ──────────────────────────────────────────


def test_compute_thinking_budget_short_message():
    msgs = [{"role": "user", "content": "hi"}]
    out = e.ChikaEngine._compute_thinking_budget(msgs, max_budget=8000)
    assert out == max(8000 // 4, 1024)


def test_compute_thinking_budget_medium_message():
    msgs = [{"role": "user", "content": "x" * 300}]
    out = e.ChikaEngine._compute_thinking_budget(msgs, max_budget=8000)
    assert out == max(8000 // 2, 1024)


def test_compute_thinking_budget_long_message():
    msgs = [{"role": "user", "content": "x" * 600}]
    out = e.ChikaEngine._compute_thinking_budget(msgs, max_budget=8000)
    assert out == 8000


def test_compute_thinking_budget_with_tool_results():
    """A user message holding a tool_result block forces the full budget."""
    msgs = [
        {
            "role": "user",
            "content": [{"type": "tool_result", "content": "..."}],
        },
    ]
    out = e.ChikaEngine._compute_thinking_budget(msgs, max_budget=8000)
    assert out == 8000


def test_compute_thinking_budget_floor_at_1024():
    """Even with low max_budget, returns at least 1024."""
    msgs = [{"role": "user", "content": "hi"}]
    out = e.ChikaEngine._compute_thinking_budget(msgs, max_budget=100)
    assert out == 1024


def test_compute_thinking_budget_extracts_text_from_list_content():
    """User content as a list of {text} blocks is concatenated."""
    msgs = [
        {
            "role": "user",
            "content": [{"text": "x" * 600}],
        },
    ]
    out = e.ChikaEngine._compute_thinking_budget(msgs, max_budget=8000)
    assert out == 8000  # treated as long


# ── LLMCaller ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_caller_delegates_to_engine():
    """LLMCaller.complete defers to engine._llm_complete."""
    class FakeEngine:
        def __init__(self):
            self.called_with = None
        async def _llm_complete(self, prompt):
            self.called_with = prompt
            return "result"

    fake = FakeEngine()
    caller = e.LLMCaller(fake)  # type: ignore[arg-type]
    out = await caller.complete("hello")
    assert out == "result"
    assert fake.called_with == "hello"
