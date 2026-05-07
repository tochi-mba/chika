"""
Factuality & grounding tests — the safety net for the overhaul.

These tests encode the invariants that prevent the "Loaded Waffles" class
of hallucination:

1. Tool results carry a source tag (`Variable.source`) so the LLM sees
   where every value came from.
2. Meta-tools (`llm_transform`, `llm_summarise`) REFUSE to run on empty
   or unresolved context — because running an LLM on empty context is
   the #1 fabrication vector.
3. Fact-producing tools (web_search, file_read, shell_exec, verify_url)
   auto-append to a rolling `$facts` ledger the session keeps.
4. `fact_check` tool can look up whether a claim is supported by ledger.
5. `verify_url` reports reachability without raising on network errors.
"""
import asyncio

from chika.core.tool_registry import ToolDefinition, ToolRegistry
from chika.core.variable_store import VariableStore, VarType
from chika.core.workflow_engine import WorkflowEngine, _looks_empty


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def collect(gen):
    out = []
    async for e in gen:
        out.append(e)
    return out


def make_engine(tool_defs=None, llm_caller=None):
    reg = ToolRegistry()
    for t in tool_defs or []:
        reg.register(t)
    store = VariableStore()
    return WorkflowEngine(reg, store, llm_caller), store


# ── 1. Source attribution ────────────────────────────────────────────────────

def test_tool_result_is_tagged_with_source():
    async def handler():
        return {"ok": True}
    tool = ToolDefinition(
        name="my_tool", description="test", parameters={"type": "object", "properties": {}},
        handler=handler,
    )
    engine, store = make_engine([tool])
    wf = {"type": "sequential", "steps": [
        {"id": "s1", "tool": "my_tool", "args": {}, "store_result_as": "$out"}
    ]}
    run(collect(engine.execute(wf)))
    var = store.get("out")
    assert var is not None
    assert var.source == "my_tool:s1", f"expected source 'my_tool:s1', got {var.source!r}"


def test_variable_store_list_summary_includes_source():
    store = VariableStore()
    store.set("x", "hi", source="web_search:s1")
    store.set("y", "ho")
    summary = store.list_summary()
    sources = {v["name"]: v["source"] for v in summary}
    assert sources == {"x": "web_search:s1", "y": None}


# ── 2. Empty-context refusal on meta-tools ───────────────────────────────────

def test_looks_empty_detects_empty_search_shape():
    assert _looks_empty({"count": 0, "results": []}) is True
    assert _looks_empty({"count": 0}) is True
    assert _looks_empty({"results": []}) is True
    assert _looks_empty({"error": "boom"}) is True
    assert _looks_empty("") is True
    assert _looks_empty("$unresolved_ref") is True
    assert _looks_empty(None) is True
    assert _looks_empty([]) is True
    assert _looks_empty({}) is True
    # Real content is NOT empty
    assert _looks_empty("actual text") is False
    assert _looks_empty({"results": [{"url": "..."}]}) is False
    assert _looks_empty([1, 2, 3]) is False


def test_llm_transform_refuses_empty_context():
    class LyingLLM:
        """
        Represents the worst case: an LLM that happily fabricates when
        given empty context. The engine must refuse BEFORE calling it.
        """
        calls = 0
        async def complete(self, prompt):
            LyingLLM.calls += 1
            return '{"url": "https://totally-real-site-that-does-not-exist.com"}'

    engine, store = make_engine(llm_caller=LyingLLM())
    wf = {"type": "sequential", "steps": [
        {"id": "s1", "tool": "llm_transform",
         "args": {"prompt": "Extract the URL.", "context": {"count": 0, "results": []},
                  "schema": {"url": "string"}},
         "store_result_as": "$extracted"}
    ]}
    events = run(collect(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]
    assert len(results) == 1
    assert results[0]["result"].get("error") == "refused_empty_context"
    # Critical: the lying LLM was NEVER invoked
    assert LyingLLM.calls == 0


def test_llm_transform_refuses_unresolved_variable():
    class LyingLLM:
        calls = 0
        async def complete(self, prompt):
            LyingLLM.calls += 1
            return '{"result": "fabricated"}'

    engine, store = make_engine(llm_caller=LyingLLM())
    wf = {"type": "sequential", "steps": [
        {"id": "s1", "tool": "llm_transform",
         "args": {"prompt": "Extract.", "context": "$never_set",
                  "schema": {"result": "string"}},
         "store_result_as": "$out"}
    ]}
    events = run(collect(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]
    # ``$never_set`` doesn't resolve, so the workflow engine's
    # unresolved-$ref guard refuses BEFORE dispatching to the
    # llm_transform meta-tool. The error code is
    # ``unresolved_variable`` (more accurate than the old
    # ``refused_empty_context`` which only fired after dispatch).
    assert results[0]["result"].get("error") == "unresolved_variable"
    assert LyingLLM.calls == 0


def test_llm_transform_runs_on_real_context():
    class FakeLLM:
        async def complete(self, prompt):
            return '{"url": "https://example.com"}'

    engine, store = make_engine(llm_caller=FakeLLM())
    wf = {"type": "sequential", "steps": [
        {"id": "s1", "tool": "llm_transform",
         "args": {
             "prompt": "Extract URL.",
             "context": {"results": [{"url": "https://example.com", "title": "Example"}]},
             "schema": {"url": "string"},
         },
         "store_result_as": "$out"}
    ]}
    run(collect(engine.execute(wf)))
    val = store.get_value("out")
    assert val.get("url") == "https://example.com"


def test_llm_summarise_refuses_empty_context():
    class LyingLLM:
        calls = 0
        async def complete(self, prompt):
            LyingLLM.calls += 1
            return "Summary of nothing!"

    engine, store = make_engine(llm_caller=LyingLLM())
    wf = {"type": "sequential", "steps": [
        {"id": "s1", "tool": "llm_summarise",
         "args": {"prompt": "Summarise.", "context": {"count": 0, "results": []}},
         "store_result_as": "$sum"}
    ]}
    events = run(collect(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["result"].get("error") == "refused_empty_context"
    assert LyingLLM.calls == 0


# ── 3. $facts ledger auto-population ─────────────────────────────────────────

def test_web_search_result_populates_facts_ledger():
    async def fake_search(query: str, max_results: int = 8):
        return {
            "_source": "web_search",
            "query": query,
            "count": 2,
            "results": [
                {"title": "Example 1", "url": "https://a.com", "snippet": "hello"},
                {"title": "Example 2", "url": "https://b.com", "snippet": "world"},
            ],
        }

    tool = ToolDefinition(
        name="web_search",
        description="fake",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        handler=fake_search,
    )
    engine, store = make_engine([tool])
    wf = {"type": "sequential", "steps": [
        {"id": "s1", "tool": "web_search", "args": {"query": "test"}, "store_result_as": "$r"}
    ]}
    run(collect(engine.execute(wf)))
    facts_var = store.get("facts")
    assert facts_var is not None, "$facts ledger was not created"
    ledger = facts_var.value
    assert len(ledger) == 2, f"expected 2 fact entries, got {len(ledger)}"
    urls = {f["url"] for f in ledger}
    assert urls == {"https://a.com", "https://b.com"}
    assert all(f["source"].startswith("web_search:") for f in ledger)


def test_empty_web_search_does_not_populate_facts():
    async def empty_search(query: str):
        return {"_source": "web_search", "query": query, "count": 0, "results": []}

    tool = ToolDefinition(
        name="web_search", description="fake",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        handler=empty_search,
    )
    engine, store = make_engine([tool])
    wf = {"type": "sequential", "steps": [
        {"id": "s1", "tool": "web_search", "args": {"query": "nothing"}}
    ]}
    run(collect(engine.execute(wf)))
    facts_var = store.get("facts")
    # Empty search must not leak into the ledger — otherwise downstream
    # fact_check would falsely "support" fabrications.
    assert facts_var is None or not facts_var.value


def test_facts_ledger_bounded():
    """Ledger should cap at ~60 entries so long sessions don't blow up."""
    async def big_search(query: str):
        return {
            "_source": "web_search",
            "query": query,
            "count": 100,
            "results": [
                {"title": f"t{i}", "url": f"https://a.com/{i}", "snippet": "x"}
                for i in range(100)
            ],
        }

    tool = ToolDefinition(
        name="web_search", description="fake",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        handler=big_search,
    )
    engine, store = make_engine([tool])
    # The append_fact code takes only the top 8 results per call.
    # 8 searches × 8 results = 64 entries → should be capped at 60.
    # (MAX_WORKFLOW_STEPS = 8, so we stay within one workflow's limit.)
    steps = [
        {"id": f"s{i}", "tool": "web_search", "args": {"query": f"q{i}"}}
        for i in range(8)
    ]
    wf = {"type": "sequential", "steps": steps}
    run(collect(engine.execute(wf)))
    ledger = store.get("facts").value
    assert len(ledger) <= 60, f"ledger grew unbounded: {len(ledger)}"


# ── 4. fact_check tool ───────────────────────────────────────────────────────

def test_fact_check_reports_empty_ledger():
    from chika.skills.verify_skill import _make_fact_check
    store = VariableStore()
    fc = _make_fact_check(store)
    result = run(fc(claim="The Earth is round"))
    assert result["supported"] is False
    assert result["reason"] == "ledger_empty"


def test_fact_check_finds_matching_evidence():
    from chika.skills.verify_skill import _make_fact_check
    store = VariableStore()
    store.set("facts", [
        {
            "source": "web_search:s1",
            "query": "legends dessert popular",
            "url": "https://example.com/legends",
            "title": "Legends menu",
            "snippet": "The most ordered item at Legends is the waffle stack with chocolate.",
        },
    ], VarType.JSON, source="engine:ledger")
    fc = _make_fact_check(store)
    result = run(fc(claim="waffle stack Legends popular"))
    assert result["supported"] is True
    assert len(result["matches"]) >= 1
    assert result["matches"][0]["url"] == "https://example.com/legends"


def test_fact_check_refuses_unsupported_claim():
    from chika.skills.verify_skill import _make_fact_check
    store = VariableStore()
    store.set("facts", [
        {"source": "web_search:s1", "snippet": "Completely unrelated content."},
    ], VarType.JSON, source="engine:ledger")
    fc = _make_fact_check(store)
    # Claim mentions totally different tokens
    result = run(fc(claim="pineapple rollercoaster trumpet"))
    assert result["supported"] is False
    assert result["directive"] is not None


# ── 5. verify_url ────────────────────────────────────────────────────────────

def test_verify_url_returns_reachable_false_on_network_error():
    """verify_url must NEVER raise — it always returns a dict."""
    from chika.skills.verify_skill import verify_url
    # Use a URL scheme httpx can't resolve
    result = run(verify_url("http://definitely-not-a-real-host-12345.invalid", timeout=1.0))
    assert result["reachable"] is False
    assert "error" in result


# ── 6. Integration: full pipeline, empty search → no fabrication ─────────────

def test_end_to_end_empty_search_blocks_fabrication():
    """
    Regression test for the "Loaded Waffles" incident:
      1. web_search returns 0 results
      2. llm_transform is called to extract a URL from those 0 results
      3. Engine MUST refuse; lying LLM MUST NEVER be invoked
      4. $facts MUST remain empty
    """
    async def empty_search(query: str):
        return {"_source": "web_search", "query": query, "count": 0, "results": []}

    class LyingLLM:
        calls = 0
        async def complete(self, prompt):
            LyingLLM.calls += 1
            return '{"url": "https://fabricated-restaurant-page.com"}'

    tool = ToolDefinition(
        name="web_search", description="fake",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        handler=empty_search,
    )
    engine, store = make_engine([tool], llm_caller=LyingLLM())
    wf = {"type": "sequential", "steps": [
        {"id": "s1", "tool": "web_search",
         "args": {"query": "Legends popular dessert"}, "store_result_as": "$results"},
        {"id": "s2", "tool": "llm_transform",
         "args": {"prompt": "Extract best URL.", "context": "$results",
                  "schema": {"url": "string"}},
         "store_result_as": "$extracted"},
    ]}
    run(collect(engine.execute(wf)))
    # Sequential aborts on tool_result error — llm_transform returns error dict.
    # But importantly: no fabricated URL ever reaches the variable store.
    extracted_var = store.get("extracted")
    if extracted_var is not None:
        val = extracted_var.value
        # If it's stored at all, it must be the refusal, not a fake URL
        assert isinstance(val, dict) and val.get("error") == "refused_empty_context"
    # The lying LLM was not invoked
    assert LyingLLM.calls == 0, \
        "LLM was fired on empty context — hallucination vector is open"
    # No $facts were populated from the empty search
    facts = store.get("facts")
    assert facts is None or not facts.value
