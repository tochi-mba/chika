"""Workflow-engine guards — unresolved $refs + tool-result trimming.

Pins two contracts that came out of a real user crash:

1. **Unresolved-$ref guard.** The user's session ran:

       spotify_search → store $search_result
       spotify_play   args={"uris": ["$search_result.tracks[0].uri"]}

   Spotify's search response shape is ``tracks: {items: [...]}`` — the
   path ``tracks[0]`` doesn't resolve, so the literal string
   ``$search_result.tracks[0].uri`` flowed straight into the tool and
   came back as a 400 with ``Invalid track uri:
   $search_result.tracks[0].uri``. The guard must catch this BEFORE
   dispatch and emit a clear ``unresolved_variable`` error pointing
   at the offending path.

2. **Tool-result trimming.** Spotify's track payload includes
   ``available_markets`` (180+ ISO country codes) per item, plus
   ``images`` (3 thumbnails), ``external_urls``, ``preview_url`` and
   other LLM-irrelevant fields that bloat the agent's context. The
   workflow engine trims these recursively at the boundary so they
   never enter the variable store.
"""
from __future__ import annotations

import asyncio

import pytest

from chika.core.tool_registry import ToolDefinition, ToolRegistry
from chika.core.variable_store import VarType, VariableStore
from chika.core.workflow_engine import (
    WorkflowEngine,
    _collect_unresolved_refs,
    _trim_tool_result,
)


# ── _collect_unresolved_refs ─────────────────────────────────────────


def test_collect_unresolved_refs_finds_top_level_string():
    assert _collect_unresolved_refs("$foo") == ["$foo"]


def test_collect_unresolved_refs_finds_dotted_ref():
    out = _collect_unresolved_refs("$foo.bar.baz")
    assert out == ["$foo.bar.baz"]


def test_collect_unresolved_refs_finds_indexed_ref():
    out = _collect_unresolved_refs("$search_result.tracks[0].uri")
    assert out == ["$search_result.tracks[0].uri"]


def test_collect_unresolved_refs_walks_into_lists():
    out = _collect_unresolved_refs(["$a", "fixed", "$b.c"])
    assert any("$a" in s for s in out)
    assert any("$b.c" in s for s in out)
    assert all("fixed" not in s for s in out)


def test_collect_unresolved_refs_walks_into_dicts():
    out = _collect_unresolved_refs({"uris": ["$x.y[0]"], "device": "abc123"})
    assert any("$x.y[0]" in s for s in out)
    assert all("abc123" not in s for s in out)


def test_collect_unresolved_refs_returns_empty_when_clean():
    assert _collect_unresolved_refs({"a": 1, "b": ["c", 2]}) == []


def test_collect_unresolved_refs_ignores_non_ref_dollar_signs():
    """Mid-string ``$`` (currency, regex token) shouldn't false-positive.
    The match is anchored to the full string."""
    assert _collect_unresolved_refs("price: $5.99") == []
    assert _collect_unresolved_refs("regex: $1") == []


# ── _trim_tool_result ────────────────────────────────────────────────


def test_trim_tool_result_drops_available_markets():
    """Spotify's 180-country ``available_markets`` array is the
    biggest single context bloat — must be stripped at every depth."""
    spotify_track = {
        "name": "Folded",
        "uri":  "spotify:track:abc",
        "available_markets": ["US", "GB", "JP", "DE"] * 50,  # 200 items
        "album": {
            "name": "Folded",
            "available_markets": ["US"] * 100,  # nested too
        },
    }
    out = _trim_tool_result(spotify_track)
    assert "available_markets" not in out
    assert "available_markets" not in out["album"]
    # Real fields preserved
    assert out["name"] == "Folded"
    assert out["album"]["name"] == "Folded"


def test_trim_tool_result_drops_image_arrays():
    """Spotify ``images`` array is three identical-content thumbnail
    URLs the agent never uses."""
    out = _trim_tool_result({"name": "Album", "images": [
        {"url": "https://i.scdn.co/640", "width": 640},
        {"url": "https://i.scdn.co/300", "width": 300},
        {"url": "https://i.scdn.co/64",  "width": 64},
    ]})
    assert "images" not in out
    assert out["name"] == "Album"


def test_trim_tool_result_drops_null_and_empty_keys():
    out = _trim_tool_result({
        "name": "Folded",
        "preview_url": None,
        "explicit": False,                     # explicit False kept (signal)
        "popularity": 0,                       # numeric 0 kept (signal)
        "external_ids": {"isrc": "USA22504"},  # noisy-keys dropped wholesale
        "empty_dict": {},
        "empty_list": [],
        "empty_str":  "",
    })
    assert out == {"name": "Folded", "explicit": False, "popularity": 0}


def test_trim_tool_result_truncates_long_lists():
    """Long lists get truncated to first N items + a marker so the
    agent knows truncation happened."""
    items = [{"id": str(i)} for i in range(50)]
    out = _trim_tool_result({"items": items})
    # 12 + 1 marker
    assert len(out["items"]) == 13
    assert "more (truncated)" in str(out["items"][-1])


def test_trim_tool_result_truncates_huge_strings():
    out = _trim_tool_result({"text": "a" * 10_000})
    assert len(out["text"]) < 10_000
    assert "truncated" in out["text"]


def test_trim_tool_result_preserves_top_level_error_field():
    """``error`` is metadata the workflow engine inspects — must
    never get trimmed even when its value is a one-line string."""
    out = _trim_tool_result({"error": "no_token", "message": "auth required"})
    assert out["error"] == "no_token"
    assert out["message"] == "auth required"


def test_trim_tool_result_handles_nested_lists_in_dicts():
    out = _trim_tool_result({
        "tracks": {
            "items": [
                {"name": "A", "uri": "spotify:track:a", "available_markets": ["US"] * 100},
                {"name": "B", "uri": "spotify:track:b", "available_markets": ["GB"] * 100},
            ],
        },
    })
    assert "available_markets" not in out["tracks"]["items"][0]
    assert "available_markets" not in out["tracks"]["items"][1]
    assert out["tracks"]["items"][0]["uri"] == "spotify:track:a"


# ── End-to-end: workflow engine refuses dispatch on unresolved $ref ──


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def engine_with_recording_tool():
    """Workflow engine + a stub tool that records every call so
    tests can assert the dispatch was (or wasn't) reached."""
    tools = ToolRegistry()
    vs = VariableStore()
    calls: list[dict] = []

    async def _record(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "args": kwargs}

    tools.register(ToolDefinition(
        name="record",
        description="record args for assertion",
        parameters={"type": "object"},
        handler=_record,
    ))

    class _NullLLM:
        async def complete(self, prompt: str) -> str:  # noqa: ARG002
            return ""

    engine = WorkflowEngine(tools, vs, _NullLLM())
    engine.set_skill_registry(type("R", (), {"_skills": {}, "skills": lambda self: {}})())
    return engine, vs, calls


async def _drain(gen):
    out = []
    async for ev in gen:
        out.append(ev)
    return out


def test_workflow_refuses_dispatch_when_ref_doesnt_resolve(engine_with_recording_tool):
    """The exact regression from the user's spotify_play crash.
    ``$search_result.tracks[0].uri`` doesn't resolve (tracks is a
    dict, not a list), so the engine MUST refuse before dispatch."""
    engine, vs, calls = engine_with_recording_tool
    # Set up search_result with the actual Spotify shape.
    vs.set("search_result", {
        "tracks": {  # NOTE: dict, not list
            "items": [{"uri": "spotify:track:CORRECT"}],
        },
    }, var_type=VarType.JSON)

    wf = {"type": "sequential", "steps": [
        {"id": "play", "tool": "record",
         "args": {"uris": ["$search_result.tracks[0].uri"]}},
    ]}
    events = _run(_drain(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]

    # Tool was NOT called — dispatch was refused
    assert len(calls) == 0, "tool must not be dispatched with unresolved $ref"

    # Result is the structured guard error
    assert results, "must yield a tool_result event for the refusal"
    err = results[0]["result"]
    assert err.get("error") == "unresolved_variable"
    assert any("$search_result.tracks[0].uri" in p for p in err["unresolved_paths"])
    assert "hint" in err and "items" in err["hint"], (
        "hint must mention the right path (`tracks.items[0]`) so the "
        "agent re-plans correctly"
    )


def test_workflow_dispatches_when_ref_resolves(engine_with_recording_tool):
    """Sanity check the inverse: when the ref DOES resolve, the
    guard must let the call through unchanged."""
    engine, vs, calls = engine_with_recording_tool
    vs.set("search_result", {
        "tracks": {"items": [{"uri": "spotify:track:RESOLVED"}]},
    }, var_type=VarType.JSON)

    wf = {"type": "sequential", "steps": [
        {"id": "play", "tool": "record",
         "args": {"uris": ["$search_result.tracks.items[0].uri"]}},
    ]}
    events = _run(_drain(engine.execute(wf)))
    assert len(calls) == 1, "tool should fire once when refs resolve"
    assert calls[0]["uris"] == ["spotify:track:RESOLVED"]
    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["result"].get("ok") is True


def test_workflow_trims_tool_result_in_variable_store(engine_with_recording_tool):
    """End-to-end: when a tool returns a Spotify-shaped payload with
    ``available_markets``, what lands in the variable store is the
    TRIMMED version (no markets, no images, no external_urls)."""
    engine, vs, calls = engine_with_recording_tool

    # Replace the recording handler with one that emits a real-shaped Spotify response.
    async def _spotify_search(**_kwargs):
        return {
            "tracks": {
                "items": [{
                    "name": "Folded",
                    "uri": "spotify:track:abc",
                    "available_markets": ["US", "GB"] * 100,
                    "images": [{"url": "x"}, {"url": "y"}, {"url": "z"}],
                    "external_urls": {"spotify": "https://open.spotify.com/track/abc"},
                    "preview_url": "https://p.scdn.co/mp3-preview/foo",
                }],
                "limit": 1, "offset": 0, "total": 1,
            },
        }

    engine._tools.register(ToolDefinition(
        name="search",
        description="fake spotify search",
        parameters={"type": "object"},
        handler=_spotify_search,
    ))

    wf = {"type": "sequential", "steps": [
        {"id": "s", "tool": "search", "args": {},
         "store_result_as": "$result"},
    ]}
    _run(_drain(engine.execute(wf)))

    stored = vs.get("result").value
    item = stored["tracks"]["items"][0]
    assert item["name"] == "Folded"
    assert item["uri"] == "spotify:track:abc"
    # Noisy fields stripped
    assert "available_markets" not in item
    assert "images" not in item
    assert "external_urls" not in item
    assert "preview_url" not in item
