"""Generic kwarg alias resolution at the tool dispatcher.

LLMs drift on parameter names — they emit ``q`` for ``query``,
``types`` for ``type``, ``track_id`` for ``id``, etc. Without a
fallback, dispatch raises ``TypeError: unexpected keyword argument`` and
aborts the whole workflow. The alias resolver in
``chika.core.tool_registry`` rewrites common drift to the canonical
name BEFORE calling the handler.

These tests pin:
  - The exact regression from the user's session (``q``→``query``,
    ``types``→``type``).
  - Conservative renaming: only rewrite when the alias's target is
    in THIS handler's signature.
  - Handlers with ``**kwargs`` skip rewriting (they already swallow).
  - Unknown kwargs without an alias get dropped silently (the LLM's
    default-arg drift gets ignored, not crashed on).
"""
from __future__ import annotations

import asyncio

import pytest

from chika.core.tool_registry import (
    ToolDefinition,
    ToolRegistry,
    _resolve_kwargs,
)


# ── _resolve_kwargs unit tests ────────────────────────────────────────


@pytest.mark.parametrize("alias,canonical", [
    ("q",         "query"),
    ("types",     "type"),
    ("kind",      "type"),
    ("max",       "limit"),
    ("max_results", "limit"),
    ("count",     "limit"),
    ("start",     "offset"),
    ("steps",     "tasks"),
    ("template",  "stack"),
    ("framework", "stack"),
    ("link",      "url"),
    ("uri",       "url"),
    ("title",     "name"),
])
def test_alias_rewrites_when_canonical_matches_signature(alias: str, canonical: str):
    """Each alias rewrites to its canonical when the handler asks
    for the canonical name."""
    # Build a real handler with exactly the canonical param. Using
    # ``exec`` because we need a runtime-defined param name; the
    # built handler is the only thing the test cares about.
    src = f"def h({canonical}=None): return {{'{canonical}': {canonical}}}"
    ns: dict = {}
    exec(src, ns)
    handler = ns["h"]

    out = _resolve_kwargs(handler, {alias: "value-from-llm"})
    assert out == {canonical: "value-from-llm"}, (
        f"alias {alias!r} should rewrite to {canonical!r}; got {out!r}"
    )


def test_alias_passthrough_when_already_canonical():
    """If the LLM already used the canonical name, no rewriting."""
    def h(query=None):
        return query
    out = _resolve_kwargs(h, {"query": "hello"})
    assert out == {"query": "hello"}


def test_alias_skipped_when_handler_doesnt_accept_canonical():
    """``q`` is the alias for ``query`` — but if the handler doesn't
    take ``query`` either, drop ``q`` (don't rewrite blindly)."""
    def h(filter=None):
        return filter
    out = _resolve_kwargs(h, {"q": "hello"})
    assert out == {}, (
        "q shouldn't rewrite when the handler has neither q nor query"
    )


def test_alias_skipped_when_handler_takes_var_kwargs():
    """A handler with ``**kwargs`` is a passthrough — don't mess with
    its arg shape, it'll deal with whatever the LLM emitted."""
    def h(**kwargs):
        return kwargs
    out = _resolve_kwargs(h, {"q": "hello", "weird": True})
    assert out == {"q": "hello", "weird": True}


def test_alias_doesnt_overwrite_existing_canonical():
    """Edge case: LLM passed BOTH ``q`` and ``query``. Keep
    ``query`` (it's already canonical), drop the duplicate ``q``."""
    def h(query=None):
        return query
    out = _resolve_kwargs(h, {"query": "first", "q": "second"})
    assert out == {"query": "first"}


def test_unknown_kwarg_without_alias_is_dropped():
    """LLM passed a kwarg that's neither in the signature nor a known
    alias. Drop it — the handler's defaults take over."""
    def h(query=None):
        return query
    out = _resolve_kwargs(h, {"query": "hi", "completely_random": "x"})
    assert out == {"query": "hi"}


# ── End-to-end: dispatch resolves aliases before calling handler ──────


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_dispatch_with_q_alias_for_query_succeeds():
    """The exact regression from the user's session:
    ``spotify_search(q='folded kehlani', types='track')`` raised
    ``TypeError: unexpected keyword argument 'q'``. With the alias
    layer, both kwargs rewrite cleanly and the call succeeds."""
    registry = ToolRegistry()
    captured: dict = {}

    async def search(query: str, type: str = "track", limit: int = 10) -> dict:
        captured["query"] = query
        captured["type"] = type
        captured["limit"] = limit
        return {"ok": True, "query": query, "type": type}

    registry.register(ToolDefinition(
        name="search",
        description="search test",
        parameters={"type": "object"},
        handler=search,
    ))

    result = _run(registry.dispatch("search", {
        "q": "folded kehlani",
        "types": "track",
    }))
    assert result["ok"] is True
    assert captured["query"] == "folded kehlani"
    assert captured["type"] == "track"


def test_dispatch_drops_unknown_kwargs_without_aliases():
    """LLM hallucinated a kwarg name with no alias. Dispatch must
    NOT crash — the handler runs with its defaults."""
    registry = ToolRegistry()

    async def get_thing(name: str = "default") -> dict:
        return {"name": name}

    registry.register(ToolDefinition(
        name="get_thing",
        description="get test",
        parameters={"type": "object"},
        handler=get_thing,
    ))

    result = _run(registry.dispatch("get_thing", {
        "name": "mochi",
        "totally_random_unknown_arg": 42,
    }))
    assert result == {"name": "mochi"}


def test_dispatch_with_var_kwargs_handler_passes_through_unchanged():
    """Handlers with ``**kwargs`` already absorb LLM drift — alias
    layer must not interfere."""
    registry = ToolRegistry()
    captured: dict = {}

    async def passthrough(**kwargs) -> dict:
        captured.update(kwargs)
        return kwargs

    registry.register(ToolDefinition(
        name="passthrough",
        description="passthrough test",
        parameters={"type": "object"},
        handler=passthrough,
    ))

    _run(registry.dispatch("passthrough", {
        "q": "hi", "weird_alias": "x", "name": "y",
    }))
    assert captured == {"q": "hi", "weird_alias": "x", "name": "y"}
