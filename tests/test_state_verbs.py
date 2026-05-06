"""Tests for chika/_cli/state_verbs.py — context-aware verb generator
for the inline state indicator.

Covers the prompt builder, the LLM response parser, settings gate,
and the fire-and-forget glue.  The actual LLM call is mocked since
we don't burn tokens in unit tests.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from chika._cli import state_verbs as sv


# ── _parse_verbs — pulls -ing verbs out of LLM responses ─────────────


def test_parse_verbs_clean_csv():
    out = sv._parse_verbs("Investigating, Tracing, Diagnosing, Reasoning")
    assert out == ["Investigating", "Tracing", "Diagnosing", "Reasoning"]


def test_parse_verbs_handles_extra_whitespace():
    out = sv._parse_verbs("  Thinking ,  Pondering , Brewing  ")
    assert out == ["Thinking", "Pondering", "Brewing"]


def test_parse_verbs_strips_quotes_and_bullets():
    out = sv._parse_verbs('"Sketching", "Drafting", • Outlining')
    assert "Sketching" in out
    assert "Drafting" in out
    assert "Outlining" in out


def test_parse_verbs_dedupes():
    """Same verb twice → only kept once."""
    out = sv._parse_verbs("Vibing, Vibing, Pondering")
    assert out == ["Vibing", "Pondering"]


def test_parse_verbs_title_cases_lowercase():
    out = sv._parse_verbs("investigating, tracing")
    assert out == ["Investigating", "Tracing"]


def test_parse_verbs_skips_non_ing_words():
    """Only matches verbs ending in -ing — random words are dropped."""
    out = sv._parse_verbs("Investigating, foo, Tracing, bar")
    assert out == ["Investigating", "Tracing"]


def test_parse_verbs_caps_at_12():
    """Defensive: even if LLM returns 50 verbs, we cap to 12."""
    # All distinct, all valid -ing verbs, no digits (regex rejects digits).
    verbs_50 = [f"Going{chr(65 + i % 26)}ing" for i in range(50)]
    big = ", ".join(verbs_50)
    out = sv._parse_verbs(big)
    assert len(out) <= 12  # cap is upper-bound; dedup may yield fewer


def test_parse_verbs_empty_string_returns_empty():
    assert sv._parse_verbs("") == []


def test_parse_verbs_none_returns_empty():
    assert sv._parse_verbs(None) == []


def test_parse_verbs_no_matches_returns_empty():
    """Pure prose with no -ing verbs → empty list, falls back to static."""
    assert sv._parse_verbs("hello world this has no verbs") == []


def test_parse_verbs_handles_hyphenated():
    """Hyphens allowed in the regex — 'Cross-checking' is a valid verb."""
    out = sv._parse_verbs("Cross-checking, Investigating")
    assert "Cross-checking" in out


# ── _build_prompt — composes the LLM ask ─────────────────────────────


def test_build_prompt_includes_user_message():
    prompt = sv._build_prompt("why is this test failing", [])
    assert "why is this test failing" in prompt


def test_build_prompt_truncates_long_user_message():
    prompt = sv._build_prompt("x" * 2000, [])
    # Per implementation: user message capped at 400 chars.
    # Just make sure the prompt itself doesn't drag along the full 2000.
    assert len(prompt) < 1500


def test_build_prompt_includes_history_tail():
    prompt = sv._build_prompt("debug this", [
        {"role": "user", "content": "earlier turn"},
        {"role": "assistant", "content": "earlier reply"},
    ])
    assert "earlier turn" in prompt
    assert "earlier reply" in prompt


def test_build_prompt_skips_non_user_assistant():
    prompt = sv._build_prompt("debug", [
        {"role": "system", "content": "ignore me"},
        {"role": "tool", "content": "tool output"},
        {"role": "user", "content": "kept message"},
    ])
    assert "ignore me" not in prompt
    assert "tool output" not in prompt
    assert "kept message" in prompt


def test_build_prompt_skips_non_string_content():
    prompt = sv._build_prompt("x", [
        {"role": "user", "content": ["not a string"]},
        {"role": "user", "content": "valid"},
    ])
    assert "not a string" not in prompt
    assert "valid" in prompt


def test_build_prompt_truncates_long_history_messages():
    long_msg = "y" * 500
    prompt = sv._build_prompt("x", [
        {"role": "user", "content": long_msg},
    ])
    # Per implementation: each history message capped at 200 + ellipsis.
    assert "yyy…" in prompt or "yy…" in prompt


def test_build_prompt_empty_history_uses_placeholder():
    prompt = sv._build_prompt("x", [])
    assert "(no prior turns)" in prompt


def test_build_prompt_demands_csv_format():
    """We need the LLM to return a comma-separated list — make sure
    the prompt makes that demand explicitly."""
    prompt = sv._build_prompt("x", [])
    assert "comma-separated" in prompt.lower() or "csv" in prompt.lower()


# ── generate_verbs — full LLM dispatch ───────────────────────────────


@pytest.mark.asyncio
async def test_generate_verbs_returns_parsed_list_on_success(monkeypatch):
    engine = MagicMock()
    engine._client = MagicMock()
    async def fake_complete(eng, prompt, *, max_tokens):
        return "Investigating, Tracing, Diagnosing"
    monkeypatch.setattr(sv, "_bounded_complete", fake_complete)
    out = await sv.generate_verbs(engine, "debug this", [], max_tokens=80)
    assert out == ["Investigating", "Tracing", "Diagnosing"]


@pytest.mark.asyncio
async def test_generate_verbs_returns_empty_on_timeout(monkeypatch):
    engine = MagicMock()
    engine._client = MagicMock()
    async def fake_complete(eng, prompt, *, max_tokens):
        await asyncio.sleep(10)
        return "won't get here"
    monkeypatch.setattr(sv, "_bounded_complete", fake_complete)
    monkeypatch.setattr(sv, "_TIMEOUT_S", 0.05)
    out = await sv.generate_verbs(engine, "x", [], max_tokens=80)
    assert out == []


@pytest.mark.asyncio
async def test_generate_verbs_returns_empty_on_exception(monkeypatch):
    engine = MagicMock()
    async def fake_complete(eng, prompt, *, max_tokens):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(sv, "_bounded_complete", fake_complete)
    out = await sv.generate_verbs(engine, "x", [], max_tokens=80)
    assert out == []


# ── _bounded_complete — provider dispatch ─────────────────────────────


@pytest.mark.asyncio
async def test_bounded_complete_returns_empty_when_no_client(monkeypatch):
    """Stub-only sessions have engine._client=None; verbs degrade silently."""
    fake_cfg = MagicMock(provider="anthropic", model="x")
    import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "get_provider_config", lambda: fake_cfg)
    engine = MagicMock()
    engine._client = None
    out = await sv._bounded_complete(engine, "prompt", max_tokens=80)
    assert out == ""


@pytest.mark.asyncio
async def test_bounded_complete_caps_max_tokens(monkeypatch):
    """User-supplied tokens get clamped to [16, 200]."""
    fake_cfg = MagicMock(provider="openai", model="gpt")
    import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "get_provider_config", lambda: fake_cfg)

    captured = {}
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="Vibing"))]

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return fake_resp

    engine = MagicMock()
    engine._client = MagicMock()
    engine._client.chat.completions.create = fake_create
    engine._model = "gpt"

    # Below the floor (16):
    await sv._bounded_complete(engine, "p", max_tokens=4)
    assert captured["max_tokens"] == 16

    # Above the ceiling (200):
    await sv._bounded_complete(engine, "p", max_tokens=999)
    assert captured["max_tokens"] == 200


# ── fire_and_forget — background dispatch ─────────────────────────────


@pytest.mark.asyncio
async def test_fire_and_forget_calls_on_done_with_verbs(monkeypatch):
    """Happy path: scheduled task runs, on_done receives the verbs."""
    engine = MagicMock()
    engine._client = MagicMock()
    async def fake_complete(eng, prompt, *, max_tokens):
        return "Sketching, Drafting, Outlining"
    monkeypatch.setattr(sv, "_bounded_complete", fake_complete)

    received: list[list[str]] = []
    def on_done(verbs):
        received.append(verbs)

    task = sv.fire_and_forget(engine, "draft", [], on_done, max_tokens=80)
    assert task is not None
    await task
    assert received == [["Sketching", "Drafting", "Outlining"]]


def test_fire_and_forget_no_event_loop_returns_none():
    """When called outside a running loop — must close the coroutine
    cleanly so we don't get RuntimeWarning('coroutine was never awaited')."""
    engine = MagicMock()
    out = sv.fire_and_forget(engine, "x", [], lambda v: None)
    assert out is None


@pytest.mark.asyncio
async def test_fire_and_forget_swallows_on_done_exceptions(monkeypatch):
    """A buggy on_done callback must not break the background task."""
    engine = MagicMock()
    engine._client = MagicMock()
    async def fake_complete(eng, prompt, *, max_tokens):
        return "Vibing"
    monkeypatch.setattr(sv, "_bounded_complete", fake_complete)

    def buggy_on_done(_verbs):
        raise RuntimeError("on_done blew up")

    task = sv.fire_and_forget(engine, "x", [], buggy_on_done)
    await task
