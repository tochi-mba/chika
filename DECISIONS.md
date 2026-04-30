# Architecture Decision Records

Non-obvious design choices in Chika. Written for engineers who want to understand *why*, not just what.

---

## ADR-1: LLM emits a workflow JSON spec; the engine executes it deterministically

**Status:** Implemented (`chika/tools/workflow_orchestrator.py`, `chika/core/engine.py`)

**Context**

Most LLM agent frameworks let the model call tools freely, one at a time, deciding after each result whether to call another. This works for short tasks but breaks down when you need a reliable sequence of steps (e.g. search → read → summarise → write). The model can hallucinate intermediate calls, get confused by intermediate results, or enter an infinite tool loop.

**Decision**

Expose a single tool to the LLM: `workflow_orchestrator`. Its argument is a JSON object - a *workflow spec* - that describes the entire plan upfront: step type (sequential / parallel / conditional), tool name, and args for each step. The engine validates and executes that spec deterministically; the LLM never sees the results mid-flight and cannot deviate from the declared plan.

```json
{
  "type": "sequential",
  "id": "research_flow",
  "steps": [
    { "tool": "web_search",  "args": { "query": "…" } },
    { "tool": "read_url",    "args": { "url": "{{web_search.results[0].url}}" } },
    { "tool": "memory_save", "args": { "content": "{{read_url.text}}" } }
  ]
}
```

**Consequences**

- *Determinism*: given the same spec, the engine always executes the same steps in the same order - easy to test, easy to audit.
- *Upfront approval*: with supervised autonomy, the entire plan is shown to the user once before any tool runs. No surprises partway through.
- *Text-mode compatibility*: Ollama models lack native tool calling. The system prompt injects workflow JSON instructions; `_recover_leaked_workflow` in `engine.py` extracts the JSON from free-form text output. The same execution path handles both cases.
- *Tradeoff*: the model must describe the full plan before seeing any results. Tasks that genuinely require mid-stream adaptation (e.g. "search until you find X") need explicit conditional steps in the spec.

---

## ADR-2: Ground truth is a per-turn $facts ledger, validated post-response

**Status:** Implemented (`chika/core/grounding.py`, `chika/core/engine.py`)

**Context**

LLMs confabulate. In an agentic setting this is dangerous: a model can cite a URL it never fetched, quote a file it never read, or invent a tool result. Standard RAG pipelines have no feedback loop - the model's final answer is never compared against what the tools actually returned.

**Decision**

Every tool result is appended to an in-memory `$facts` ledger for the current turn. After the LLM produces its final text, `GroundingValidator` scans the response for URLs and checks each one against the ledger. A URL in the response that was not fetched by a tool in this turn raises a grounding violation.

Two additional guardrails sit upstream:
1. `_looks_empty(context)` - if the current context (memory + conversation history) is below a minimum token count, meta-tools like `memory_search` are skipped entirely. Calling a recall tool on an empty store is a reliable hallucination source.
2. A trusted-hosts allowlist - only URLs from domains the user explicitly configured can be fetched; others are blocked before they reach the network.

**Consequences**

- Hallucinated citations are caught before the response reaches the user.
- The ledger is per-turn, so it has no cross-turn memory leak - facts do not accumulate across the conversation.
- `GROUNDING_VALIDATE_RESPONSE=False` disables post-response validation in tests (where fake LLM output won't match any real tool results).
- *Tradeoff*: the validator only checks URLs, not numeric claims or paraphrased facts. It is a partial defence, not a proof.

---

## ADR-3: Two-layer session identity - persistent device_id, ephemeral session_id

**Status:** Implemented (`api/session_manager.py`, `api/server.py`)

**Context**

A naive single-ID session model breaks in two common scenarios: the server restarts (session gone), or the same physical device opens a new browser tab (two sessions for the same user, no cross-tab coherence). Both problems are real for a locally-hosted assistant.

**Decision**

Separate identity into two layers:

| Layer | Lifetime | Storage | Purpose |
|---|---|---|---|
| `device_id` | Permanent | `data/devices/<id>.json` | Identifies the physical browser / extension install |
| `session_id` | Conversation | In-memory | Identifies the current chat |

On every WebSocket connect the client sends its `device_id`. The server looks up the most recent `session_id` for that device. If the session is still alive in memory, it is resumed. If the server restarted, a new session is created and the device file is updated. The browser extension and web UI share this mechanism - both send a `device_id` in `extension_hello`.

**Consequences**

- A browser refresh or server restart does not lose the conversation if the client reconnects quickly.
- The device file is a plain JSON file; `data/` is gitignored, so no conversation data is committed.
- `device_id` is opaque (UUID4) and never transmitted over the network beyond the local LAN - it is not a security token.
- *Tradeoff*: the device file is not encrypted. Anyone with read access to the `data/` directory can see which sessions a device has had. Acceptable for a single-user local tool; not acceptable for a multi-tenant deployment.

---

## ADR-4: History compaction uses recursive subdivision, never splits tool pairs

**Status:** Implemented (`chika/core/engine.py:_compact_history`)

**Context**

Long conversations exceed the LLM's context window. The obvious fix - truncate the oldest messages - silently corrupts the message list if a `tool_use` message is kept but its paired `tool_result` is dropped (or vice versa). Both Anthropic and OpenAI reject such malformed histories with a hard error.

**Decision**

`_compact_history` keeps the first `COMPACT_KEEP_FIRST` messages (system prompt, early context) and the last `COMPACT_KEEP_LAST` messages (recent context), dropping the middle. Before returning, it scans the boundary: if either cut point falls inside a `tool_use` / `tool_result` pair, the boundary shifts outward until the pair is whole. If the result still exceeds `MAX_HISTORY_TOKENS`, the function calls itself recursively with tighter keep counts.

**Consequences**

- The compacted history is always structurally valid - no orphaned tool calls.
- Recursion terminates because keep counts shrink each level; the base case is an empty middle.
- `COMPACT_KEEP_FIRST` and `COMPACT_KEEP_LAST` are config values, tunable per deployment.
- *Tradeoff*: the middle of a long conversation is discarded entirely. A summary-based compaction (ask the LLM to summarise the dropped segment) would preserve more semantic content but adds latency and cost. The current approach is appropriate for an interactive assistant where recent context matters most.

---

## ADR-5: WebSocket send is serialised through a per-connection asyncio.Lock

**Status:** Implemented (`api/server.py:_run_chat`, `_ws_recv_loop`)

**Context**

A single WebSocket connection in Chika has multiple concurrent async writers: the LLM streaming loop emits `token` events; the process monitor emits `process_output` events; the approval handler emits `approval_required` events; background title generation emits `title_update`. Starlette's `WebSocket.send_json` is not thread-safe or concurrent-send-safe - two coroutines calling it at the same time produce a `RuntimeError: unexpected ASGI message`.

**Decision**

A `send_lock = asyncio.Lock()` is created per connection at the top of `websocket_endpoint`. Every call to `ws.send_json(...)` is wrapped:

```python
async with send_lock:
    await ws.send_json(event)
```

This serialises all writes on the event loop without blocking the thread - asyncio's cooperative multitasking means the lock releases between writes, allowing other coroutines to run.

**Consequences**

- No concurrent-write errors regardless of how many sources are writing simultaneously.
- Zero additional threads or queues; the lock is a lightweight asyncio primitive.
- The approval flow can send `approval_required` while the streaming loop is paused awaiting the approval Future - the lock is not held across the await, so both sides can acquire it in turn.
- *Tradeoff*: if a slow client causes `send_json` to back-pressure, the lock serialises that back-pressure across all writers. In practice this is fine for a single-user local tool; a high-throughput multi-client server would need a per-client send queue instead.
