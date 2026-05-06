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

---

## ADR-6: CLI parity with the frontend — every event the WS emits, the CLI renders

**Status:** Implemented (`chika/_cli/`)

**Context**

The original CLI was a thin debug printer: bare `print()` calls per event, single-letter glyphs, no awareness of multi-phase turns (thinking → tool calls → answer). Compared to the frontend it felt like a degraded experience and rarely showed enough detail to diagnose anything.

**Decision**

The CLI is a peer surface, not a fallback. `chika/_cli/renderer.py` consumes the *same* event stream `api/server.py` pushes to the frontend, but renders to the terminal via `rich` (panels, Markdown, syntax highlight) and `prompt_toolkit` (slash-command autocomplete, history, multi-line edit). A turn renders in three phases — `thinking` → `tools` → `answer` — each committed to scrollback before the next begins so the on-screen order matches event chronology even though `rich.Live` is normally pinned to the bottom row.

**Consequences**

- Tool calls show as bordered blocks with inline args and indented results, just like the frontend cards.
- Slash commands (`/provider`, `/env`, `/autonomy`, `/pet`) edit the same `data/settings.json` and `.env` files the frontend modal does — there is one source of truth.
- Graceful degradation: missing `rich` / `prompt_toolkit` falls back to the legacy plain printer in `_cli/fallback.py`. Piped stdin (no TTY) auto-falls-back too so CI scripts still work.
- *Tradeoff*: two more dependencies (`rich`, `prompt_toolkit`). They are pure-Python, MIT-licensed, and ubiquitous, so the size and risk are acceptable.

---

## ADR-7: `.env` and provider config edited through one atomic surface used by CLI + frontend

**Status:** Implemented (`chika/_cli/env_file.py`, `api/routes/env.py`)

**Context**

Provider switching used to mean editing `.env` by hand and restarting. There was no way for the running app to surface the current `.env` state, no masking for secrets, and no validation. A frontend "Settings" panel that lived only in the browser would diverge from the CLI within a release.

**Decision**

`chika/_cli/env_file.py` is the single read/write layer for `.env`: atomic-rename writes (via `chika.core._io.atomic_write`), case-aware secret detection (whole `_KEY` / `_TOKEN` / `_SECRET` segments only — `MAX_TOKENS` is *not* a secret), and an explicit `--show-secrets` flag for both the CLI and the API. `api/routes/env.py` exposes `GET/PATCH /api/env` and `GET/PATCH /api/provider`; the CLI commands `/env` and `/provider` import the same helper module directly. The frontend `SettingsModal.vue` calls the REST routes.

**Consequences**

- One source of truth, one validation path, one atomic write.
- Restart-required keys (`CHIKA_PROVIDER`, API keys, port, host) are flagged in the response so the UI can prompt the user.
- Secrets never leak into logs or screenshots: the default mask shows the first/last 4 chars and length, never the full value.
- *Tradeoff*: provider/model changes still require a process restart — the engine binds its client at startup. A future improvement would let the engine hot-swap clients on a settings_update event.

---

## ADR-8: Pet companion is per-profile state, broadcast over WS, animated independently in CLI/frontend/extension

**Status:** Implemented (`chika/_cli/pets.py`, `api/routes/pets.py`, `frontend/src/components/PetCompanion.vue`, `extension/popup/popup.js`)

**Context**

Users sleep, work, and switch contexts; tools that feel "alive" reduce the cold-start friction of opening a terminal. Claude Code shipped an animated buddy as an April Fools joke that stuck. Chika has multiple surfaces (CLI, frontend, extension popup) and multiple users-per-machine via profiles. Each profile should pick its own companion, and the choice should propagate atomically.

**Decision**

Pet definitions live in `chika/_cli/pets.py` as a small dataclass library — id, name, personality string, multi-frame ASCII art per state (`idle`/`working`/`celebrate`/`sad`), accent colour, emoji. Per-profile selection is stored in `data/profiles/<name>/profile.json:pet_id` (managed by `ProfileManager.set_pet`). When a pet is changed, the API broadcasts `{type: "pet_changed", profile, pet_id}` to every connected frontend session via `push_to_all_frontend_sessions`. Each surface renders the same pet differently:

- **CLI**: ASCII frames in a Rich `Panel`, state driven by engine events accumulated during a turn.
- **Frontend**: emoji-based widget with CSS bobbing/working/celebrate animations, speech bubble driven by an event-state-machine (`derivePetState` in `stores/system.js`).
- **Extension popup**: tiny emoji that mirrors the active profile, with toast bubbles on tool calls.

LLM-driven speech bubbles (`pet_speech.py`) are opt-in (`pet_speech: on` in settings), token-capped (`pet_speech_tokens`, default 40), and **fired in parallel** via `asyncio.create_task` so they never delay the user-facing response.

**Consequences**

- A single source of truth (`profile.json`) means the CLI, frontend, and extension always agree on the active pet.
- The pet system is intentionally over-engineered for a "fun" feature because it doubles as a test of the broadcast-and-render pipeline: any future cross-surface state (themes, personalisation) can reuse the same pattern.
- *Tradeoff*: every surface has to know how to render the pet. If we add a TTY-less surface later (e.g. an iOS app) it will need its own renderer. Acceptable — pets are visual by nature.

---

## ADR-9: Skill docs live in `SKILL.md`, loaded on demand, condensed by a second LLM call when over budget

**Status:** Implemented (`chika/tools/skill_doc_tool.py`, `chika/skills/*/SKILL.md`)

**Context**

The system prompt was growing every time a new skill landed. Putting full skill references in the prompt taxes context and pays the cost on *every* turn, even when the skill is irrelevant. Putting nothing in the prompt means the agent has no idea how a skill works. Both extremes hurt.

**Decision**

Each skill folder ships a `SKILL.md` with deep usage notes — tool tables, common workflows, anti-patterns. The system prompt only knows that `skill_load(name)` exists. When the agent realises it needs a skill (e.g. before a multi-step git operation) it calls `skill_load("git")`. The tool reads `chika/skills/git_skill/SKILL.md` and returns it.

When the doc is over a configurable budget (`max_chars`, default 6000) the tool runs a *second* LLM call: it ships the doc plus the last ~8 messages of the chat to the same provider and asks for the parts relevant to the current task. The condensed version comes back in the tool result. If the second call fails it falls back to head-truncation rather than blowing up the turn.

**Consequences**

- The base system prompt stays small and stable across turns — better cache hit rate on Anthropic.
- Skill knowledge is structured documentation, not prompt soup: easy to edit, version-control, and review.
- The condense pass is conversation-aware: a Spotify chat will not have to read the git anti-patterns section.
- *Tradeoff*: a second LLM call costs tokens. The threshold is configurable; small docs return verbatim. The agent can pass `force_full: true` when it really wants the whole reference.

---

## ADR-10: Auto-continue — re-enter the agentic loop on "Next, I'll …" promises

**Status:** Implemented (`chika/core/engine.py`)

**Context**

LLMs habitually end a turn with "Next, I'll do X" and then stop, expecting the user to nudge them. For multi-step plans this is dead time: the user types "go" or "continue" repeatedly. The model has all the context it needs to keep going — it just won't.

**Decision**

After the agent's final reply lands, run a heuristic (`_should_auto_continue`) over the last paragraph. If it matches a curated list of continuation triggers (`"next, i'll"`, `"now i'll"`, `"i'll continue"`, `"then i'll"`, `"continuing with"`, etc.) AND the text doesn't end with `?` AND we're under the cap, recursively re-enter `_chat_inner("continue")` and stream those events. The text comes from EITHER the main agentic loop (`final_text`) OR `_force_followup` when the model only spoke after its tool calls — both paths feed the heuristic so a forced followup with a "Next, I'll …" tail still triggers.

**Consequences**

- Multi-step jobs run end-to-end without user "go" prompts.
- Hard cap at `auto_continue_max` (default 5 hops/turn) prevents runaway loops.
- `auto_continue` setting (`on`/`off`, default `on`) lets the user opt out.
- A typed `auto_continue` event is yielded so the trace shows `↻ auto-continue (1/5) — agent promised more work, firing another turn`.
- *Tradeoff*: false positives (agent says "Next, I'll consider X" rhetorically rather than as a promise) cost one wasted turn. The cap bounds the damage.

---

## ADR-11: Skill gate — refuse the tool, hand back the SKILL.md, retry next turn

**Status:** Implemented (`chika/core/workflow_engine.py:_check_skill_gate`)

**Context**

ADR-9 made SKILL.md the canonical reference for each skill, but nothing forced the agent to read it. The model would call `scaffold_web_app(stack="vite-three", ...)` without ever loading `web_app_skill/SKILL.md`, miss the alias `vite-three → three`, and crash 27 seconds later inside `npm create vite-three@latest`. The earlier auto-load gate (which loaded the doc in the background and ALSO ran the tool) fixed visibility but not the wrong-args problem — the tool call had already been made without doc context.

**Decision**

The gate now refuses the tool on first-use and replays the turn:

1. When a skill tool fires and its skill isn't in `_loaded_skills`, run `skill_load` directly to fetch the SKILL.md.
2. **Do NOT dispatch the original tool.** Mark the skill loaded, then yield a synthetic `tool_result` with `error: "skill_doc_required"` and a payload containing `{skill, tool_blocked, doc, char_count, hint}`.
3. The sequential aborts on the error; `_run_workflow` formats the doc body verbatim into the workflow result fed back to the LLM.
4. Auto-continue (ADR-10) fires the next turn. The agent now has the SKILL.md in context and re-plans correctly. The gate is no-op for that skill from this point forward.

**Consequences**

- The agent literally cannot use a skill's tools without first reading its SKILL.md.
- The "wrong tool, right name" failure mode (e.g. `vite-three`, `plan_set(steps=...)`) becomes a self-correcting nudge instead of a runtime crash.
- Defensive degrade: if `skill_load` itself fails (no SKILL.md on disk), the gate passes the tool through normally so the user can't be locked out of an undocumented skill.
- *Tradeoff*: the first-time-per-skill turn costs an extra agentic loop. With auto-continue on, the user sees `📚 SKILL.md loaded → re-planned workflow → tool ran` as one continuous flow.

---

## ADR-12: Mutable plan checklist — `plan_add` / `plan_remove` + runtime tick reminder

**Status:** Implemented (`chika/skills/plan_skill/`, `chika/core/engine.py:_build_plan_nudge`)

**Context**

The original `plan_set` replaced the entire plan, and `plan_update` only flipped a status. Mid-job changes (extra task discovered, completed work shipped and out of the queue) had no clean primitive — the agent would re-call `plan_set`, wiping all progress. Worse, even with the existing tools the model often forgot to call `plan_update` after finishing a task; the checklist would sit at `(0/6)` while the agent merrily wrote files.

**Decision**

Three changes:

1. **New tools**: `plan_add(tasks, after_id=None)` to insert without replacing, `plan_remove(task_ids)` to drop completed-and-shipped items. Both auto-promote the next pending task to `in_progress` when the active task is removed.

2. **Runtime nudge**: `_build_plan_nudge` runs after every workflow. If the workflow used WRITE_TOOLS (`file_write`, `shell_exec`, `git_commit`, `scaffold_web_app`, `python_run`, `browser_navigate`, etc.) AND there is an `in_progress` task AND no plan_* tool was called in the workflow, prepend a 🚨 reminder to the workflow result fed back to the LLM. The reminder names the in-progress task ID and tells the model to start its next workflow with `plan_update(task_id="…", status="done")`.

3. **CLI persistence**: `Renderer.end_turn()` commits the final plan panel into scrollback (not just the Live region) so the conversation history shows the checklist's progression turn-by-turn.

**Consequences**

- The checklist is honest — boxes get ticked or the LLM gets nagged.
- Read-only workflows (just `file_read` / `git_status`) don't trigger the nudge — there's nothing to tick.
- Workflows without an active plan don't trigger it either — the nudge is for plan-aware sessions only.
- Per-skill kwarg drift (`plan_set(steps=…)` instead of `plan_set(tasks=…)`) is absorbed by alias resolution in the plan tools.
- *Tradeoff*: the nudge string is noise when the agent already plans to call `plan_update` in its next turn. Acceptable — it's just extra context, not an error.

---

## ADR-13: BM25 retrieval over chunked SKILL.md (`skill_query` tool)

**Status:** Implemented (`chika/tools/skill_query_index.py`)

**Context**

`skill_load` returns the entire SKILL.md (or a condensed version). For "remind me of the exact args for `plan_set`" the model only needs ~200 chars from the Tools table — but pays for thousands. A second LLM condense pass closes the gap but adds latency. Embeddings + a vector DB would solve the targeted-retrieval case but add an external dependency and per-query API cost.

**Decision**

Ship a zero-dep BM25 retrieval index. Each SKILL.md is chunked on `## ` headings (oversized sections sub-split on blank lines), tokenised with a curated stopword list, and indexed with classic BM25 (`k1=1.5`, `b=0.75`). The agent calls `skill_query(skill, query, k=3)` to get the top-k chunks ranked by relevance. The index lives at `data/skill_index/<skill>.json` and rebuilds whenever the SKILL.md mtime changes.

BM25 is empirically competitive with dense embeddings on this corpus shape (technical docs with exact tool names, parameter shapes, code blocks) — exact identifier matches score perfectly because they tokenise to the same terms. Zero deps, deterministic across runs, no API key.

**Consequences**

- "How do I call plan_set?" returns the Tools table chunk + Pattern example in <1ms.
- The cache file means startup cost is paid once per SKILL.md edit, not per query.
- Embedding-mode can layer on top later as a setting if a use case appears that BM25 can't handle.
- *Tradeoff*: BM25 doesn't generalise across phrasing as well as embeddings — "how do I plan a thing?" might miss the plan_set chunk if the doc never uses the word "plan a thing". Compensated by the fact that SKILL.md prose IS the technical vocabulary the model already knows.

---

## ADR-14: Soft workflow limits — guideline for the agent, not a sandbox cap

**Status:** Implemented (`chika/core/workflow_engine.py:execute`)

**Context**

`MAX_WORKFLOW_STEPS = 8` and `MAX_FILE_WRITES_PER_WF = 3` were hard aborts. A 9-step workflow returned an `error` event before any step ran, even when the over-cap step was a trivial `file_read`. The user hit this repeatedly on legitimate work.

**Decision**

Soft + hard tier:

- **Soft target** (the existing config values): emit a `validation_warning` and keep executing. The agent's prompt is updated to say "Target ≤8 steps" instead of "rejected".
- **Hard ceiling** (10× the soft target, minimum 80 steps / 30 file_writes): still aborts. This catches genuinely runaway / accidentally recursive specs, not legitimate big workflows.

**Consequences**

- The agent's "rule of thumb" prompt nudges still apply — workflows stay small *because* it's easier to debug, not because the engine forbids it.
- Recovery from oversize is one warning + the actual work, instead of "abort and re-plan".
- *Tradeoff*: no hard limit at the soft target means a misbehaving prompt could routinely emit 20-step workflows. The warning gives us a signal to address the prompt before the hard ceiling bites.

---

## ADR-15: Prompt-↔-SKILL.md de-duplication with an auto-generated tool reference

**Status:** Implemented (`chika/core/skill_registry.py`, `chika/core/prompt_builder.py`, `scripts/sync_skill_docs.py`)

**Context**

Every skill's `workflow_examples` was injected into the system prompt every turn (~3-6K tokens), AND the same content was duplicated in each `SKILL.md`. Triple-coverage in `_REFERENCE_SECTIONS["web"]` + skill workflow_examples + SKILL.md. Editing one without the others created drift; the user found a `plan_set(steps=…)` example in the SKILL.md that disagreed with the actual `plan_set(tasks=…)` signature, which crashed at runtime.

**Decision**

Three structural changes:

1. **`SkillRegistry` skips workflow_examples injection** when the skill's folder contains a `SKILL.md`. The doc is the canonical source; injection is the defensive fallback for skills that don't have one yet.

2. **`_REFERENCE_SECTIONS` slimmed**: the `"web"` block (covered by `web_skill/SKILL.md`) is gone; the `"code"` block keeps only cross-cutting tool guidance (`python_run` vs `shell_exec` vs `app_open`, missing-deps install URLs, `pip_install_failed` recovery) — skill-specific bits moved to the relevant SKILL.md.

3. **Auto-generated tool-reference appendix** (`scripts/sync_skill_docs.py`): introspects the live registry, writes a fenced `## Tool reference` block into every SKILL.md with every tool's name, description, kwargs (with types and required flags), and approval status. Content outside the markers is preserved. CI runs the same script with `--check` to fail when source drifts from doc.

A regression test `test_every_registered_tool_appears_in_its_skill_md` parametrizes over every (skill, tool) pair to assert the tool name shows up in its SKILL.md — adding a tool without doc updates is now a CI failure.

**Consequences**

- Static prompt size dropped from ~7-9K tokens per turn → ~3.3K (depending on which workflow_examples were live).
- A doc that lies about the tool surface is impossible: either the tool name is in the appendix or the drift test fails.
- *Tradeoff*: maintainers must re-run `python scripts/sync_skill_docs.py` after touching any tool definition. The CI check makes this a hard requirement, not a nice-to-have.

---

## ADR-16: `web_app` skill — scaffold any browser stack with a single tool call

**Status:** Implemented (`chika/skills/web_app_skill/`)

**Context**

"Make me a tic-tac-toe game" used to take ~20 `file_write` calls and a sequence of `npm create` invocations the agent rebuilt from scratch every time. Every framework had a slightly different scaffolding incantation; the agent guessed the canonical one and got it wrong (e.g. `npm create vite-three@latest`).

**Decision**

A `scaffold_web_app(stack, name, target_dir, install)` tool with three dispatch paths:

- **Built-in templates** (instant, no network): `vanilla`, `static-site`. Files written directly from the tool — sub-50ms scaffold for prototypes.
- **Vite family**: any of `vite-vue` / `vite-react` / `vite-svelte` / `vite-solid` / `vite-preact` / `vite-lit` / `vite-qwik` (TS or JS) plus aliases. Maps to `npm create vite@latest <name> -- --template <vite-template>`. Game/canvas stacks (`three`, `p5`, `phaser`) are vite-vanilla starters with the relevant npm package added via `extra_packages`.
- **Canonical scaffolders** (`next`, `nuxt`, `astro`, `sveltekit`, `remix`, `qwik-city`, `lit-app`): each entry maps the stack id to its idiomatic `create-*` invocation with non-interactive flags.
- **Fallthrough**: unknown stack ids hit `npm create <stack>@latest <name>` — works for any future scaffolder published to npm without code changes.

`_resolve_stack` also runs alias resolution (`vite-three → three`, `threejs → three`, `react-vite → vite-react`, common synonyms) BEFORE dispatch so common LLM kwarg slips don't trigger a 27-second 404. Failed dispatches return suggestions from a curated list so the agent can retry without guessing.

**Consequences**

- Most "make me a web app" intents resolve in one tool call.
- The decision tree in `web_app_skill/SKILL.md` tells the agent which stack to pick from the actual requirement (no-build → `vanilla`; SEO/content → `astro`; full-stack → `sveltekit`; 3D → `three`).
- The skill gate (ADR-11) ensures the SKILL.md is loaded before scaffold_web_app runs the first time, so the agent sees the alias table.
- *Tradeoff*: adding a new scaffolder type means a `_STACKS` entry. The fallthrough handles unknown ids, but with worse error messages than first-class entries.

---

## ADR-17: `python_run` — desktop apps with auto-installed dependencies and a real console

**Status:** Implemented (`chika/tools/python_run_tool.py`)

**Context**

`shell_exec("python racing_game.py", wait_for_completion=False)` returned a pid but the pygame window never appeared. Two compounding bugs: (1) the engine returned `exit_code: -1` (a placeholder) the moment the subprocess was created, before the script had even reached `import pygame`; the agent declared success on the pid alone. (2) On Windows, processes spawned from the engine inherit the parent's hidden subprocess flags — pygame refuses to draw a window when stdout is a pipe.

**Decision**

A dedicated `python_run` tool with three guarantees:

1. **Pre-flight imports**: AST-scans the script for top-level imports, runs `pip install` for any that aren't on `sys.path`. Maps install-name-≠-import-name cases (`PIL → Pillow`, `cv2 → opencv-python`, `pygame → pygame, pygame-ce`). Walks fallbacks on failure (`pygame` 404 on Python 3.14? Try `pygame-ce`).
2. **Real desktop session on Windows**: spawns Python with `CREATE_NEW_CONSOLE` so the GUI window actually attaches to the user's desktop.
3. **2-second grace window** before returning, so a fast `ImportError` or syntax error surfaces in the very first tool result instead of pretending the script is "running".

`shell_exec` background mode also gained the same grace-window treatment (`_wait_for_early_exit`) so existing `shell_exec("python script.py", wait_for_completion=False)` calls don't lie either.

**Consequences**

- "Make me a pygame racing demo" now actually puts a window on screen.
- `pip_install_failed` errors carry a `fix_command` field with a literal copy-paste shell line; the system prompt forbids the agent from saying "install pygame" with no command — must show fix_command verbatim.
- *Tradeoff*: AST-scanning misses imports inside functions / conditionally-imported modules. The grace window catches those at runtime when the script crashes.

---

## ADR-18: Tool kwarg alias resolution — absorb LLM kwarg drift, fail loud only when nothing matches

**Status:** Implemented (`chika/skills/plan_skill/`, `chika/skills/web_app_skill/scaffold_tool.py`)

**Context**

LLMs routinely pick a near-synonym for a required kwarg name. `plan_set(steps=[...])` instead of `plan_set(tasks=[...])`; `scaffold_web_app(template="vite-vue", project_name="x")` instead of `scaffold_web_app(stack="vite-vue", name="x")`. The first version of the kwarg-tolerance fix (`**_extra` to absorb extras) actually made this WORSE: `steps=` got eaten silently, `tasks` was missing, and the function crashed with `TypeError: missing 1 required positional argument: 'tasks'`.

**Decision**

Every tool that has been bitten by kwarg drift now:

1. Declares its required arg as `Optional[T] = None` instead of strict positional.
2. Walks a curated alias list (`steps`, `items`, `list`, `plan`, `todos` for `tasks`; `template`, `project_name`, `project` for `stack`/`name`) — first match wins.
3. Returns a structured error naming the canonical kwarg AND every alias when nothing matches.
4. Documents the canonical name in its SKILL.md with explicit "the kwarg is `tasks`, not `steps` — aliases tolerated" prose.

**Consequences**

- Common LLM slips become invisible runtime resolutions instead of crashes.
- The SKILL.md drift test (ADR-15) ensures the canonical name is documented, so the model has a chance to learn.
- *Tradeoff*: alias lists are a maintenance burden — every new tool with potential drift needs its alias table curated. We accept this for the most-bitten tools (plan_*, scaffold_web_app); other tools fall through to the strict-required-arg behaviour.

---

## ADR-19: Plans are verbose, hierarchical, and patch-editable across every surface

**Status:** Implemented (`chika/skills/plan_skill/`, `chika/_cli/`, `frontend/src/components/PlanPanel.vue`, `extension/popup/`)

**Context**

The original plan was a flat list of one-line tasks with status. That's enough scaffolding for "remind me what's left" but it leaves real value on the table:

- The agent's goal and the user's must-haves were never captured anywhere durable, so once the prompt scrolled out of context the model lost the contract.
- Multi-step tasks couldn't decompose ("implement the simulation engine" is one task in plan_set, but obviously six in execution).
- When the user wanted to tweak the plan ("use TypeScript instead of JS", "add an offline-first requirement") the agent's only option was `plan_set` again, which wiped progress.
- The plan only existed in `$plan` as a JSON blob. The user's three UIs (CLI, frontend, extension) all rendered it inconsistently or not at all.

**Decision**

Three structural changes:

1. **Verbose, hierarchical plan shape**:
   - `goal` (string) — one-sentence aim, surfaced as a banner.
   - `requirements` (list[str]) — explicit must-haves the user stated or the work obviously demands.
   - `tasks` (list of {id, text, status, **subtasks**}) — top-level work; each task may have sub-tasks of the same shape, recursively. Sub-task status auto-rolls up: parent is `done` iff every leaf is `done`, `in_progress` if any leaf is, else `pending`. Promoting "the next pending leaf" walks the tree depth-first so cap-rolled-up parents move work forward without manual choreography.

2. **`plan_edit(operations=[...])` patch tool**: instead of "replace the whole plan", the agent can apply a list of structured ops:
   - `set_goal`, `set_requirements`, `add_requirement`, `remove_requirement(match=substring)`
   - `set_task_text`, `set_task_status` (work on any node in the tree)
   - `add_task(after_id?)`, `add_subtask(parent_id)`, `remove_task`
   - `replace_in_field(field, find, replace)`, `replace_in_task(task_id, find, replace)` — substring "fingerprint" replaces. The agent picks a unique fragment; the op fails clean (`not_found`) when the fragment isn't there. No regex, no fuzzy matching — exact substring keeps the semantics predictable.
   Operations apply in order; failures in one don't block the rest. Each op records its own `{ok, error?, ...}` result so the agent can see exactly what landed.

3. **Cross-surface accept/edit/reject UX**:
   - **CLI**: `/plan` prints goal + requirements + nested tasks; `/plan accept|reject|edit <feedback>` print copy-paste messages the user can send to nudge the agent.
   - **Frontend**: `PlanPanel.vue` + `PlanTaskList.vue` render the full plan above the chat with a progress bar, **Accept / Edit / Reject** buttons, and per-task tick controls. Editing opens an inline feedback form; clicking a task's tick cycles its status (the agent sees the structured nudge and applies it via `plan_update` or `plan_edit`).
   - **Extension popup**: a compact strip with the goal headline, done/total counter, and three buttons that send the same accept/edit/reject messages so the user can drive plan flow from the browser without opening the frontend.

All three surfaces read the same `$plan` variable broadcast via `variable_set` events; all three send their accept/edit/reject as plain user messages. There's no extra state machine — the LLM sees the user's nudge and reaches for `plan_set` / `plan_edit` itself.

**Consequences**

- Plans stay coherent across long sessions because the goal and requirements are captured as data, not prose that scrolls out of context.
- Mid-job tweaks are now ~5-token operations (a single `plan_edit` op) instead of full replans that lose progress.
- Sub-task auto-rollup means the user's "is t2 done?" is computable without the agent having to remember to mark the parent.
- The substring "fingerprint" replace is deliberately conservative: the agent has to pick a unique fragment, so a bad target produces `not_found` instead of silently mis-editing the wrong field.
- *Tradeoff*: more tools (`plan_edit` joins set/update/get/add/remove) and more shape (the schema doc grew). The auto-generated tool reference in each SKILL.md (ADR-15) keeps the doc accurate without manual maintenance.

---

## ADR-20: Auto-continue raised to 10 hops by default + visible "blocked" diagnostic

**Status:** Implemented (`api/settings_store.py`, `chika/core/engine.py`, `chika/_cli/renderer.py`)

**Context**

ADR-10's auto-continue cap of 5 hops was too low for the kind of multi-step plans the agent now produces (a verbose plan with sub-tasks routinely needs 7-12 turns to execute). When the cap was hit the conversation just stopped silently — the user thought the agent was broken when it was actually waiting at the cap. Same silent fail when `auto_continue` was toggled off.

**Decision**

Two changes:

1. **Default cap raised to 10**. `_AUTO_CONTINUE_DEFAULTS["auto_continue_max"] = 10`. Existing users on disk still see their saved value (the init logic only fills missing keys), but new installs ship with the higher cap. A regression test asserts the defaults table directly so a future PR can't quietly revert.

2. **`auto_continue_blocked` event**: when the heuristic matches (the agent DID promise more work) but the gate refuses (cap hit, setting off, future reasons), the engine emits a typed `auto_continue_blocked` event with a human-readable `reason` string. The CLI renderer shows it as `⚠ auto-continue blocked — hit cap (10/10) — raise it with /auto-continue max <int> or just type continue`. The user sees WHY the agent stopped instead of having to figure it out.

**Consequences**

- Multi-step jobs run to completion under the default settings.
- "Why did it stop?" becomes obvious instead of mysterious.
- *Tradeoff*: more events on the wire (one `auto_continue_blocked` per blocked turn). Negligible — these are sub-100-byte payloads, max one per agent turn.

---

## ADR-21: Scaffolder hardened — closed stdin, non-interactive env, real timeouts, killable trees

**Status:** Implemented (`chika/skills/web_app_skill/scaffold_tool.py`)

**Context**

`scaffold_web_app(stack="vite-svelte", ...)` hung indefinitely in production. Root cause: `npm create vite@latest` (vite 6+) prompts interactively for "Use rolldown-vite?" / "Pick variant" even when `--template <name>` is passed, and our subprocess wasn't closing stdin — so the shell sat there waiting for user input that could never arrive.

The earlier mocked tests covered the dispatch logic but never exercised real `subprocess.communicate`, which is exactly where the bug lived.

**Decision**

`_run` and `_run_sync` now both:

1. **Close stdin** (`stdin=subprocess.DEVNULL`). Prompts hit EOF and the scaffolder falls back to defaults instead of waiting.
2. **Set non-interactive env vars**: `CI=1`, `npm_config_yes=true`, `ADBLOCK=1`. Many `create-*` packages check for a TTY or these env vars before drawing UI.
3. **Per-run timeout** (default 120s) with **reliable kill of the whole process tree**: on Windows we use `CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F /PID`; on POSIX we use `setsid` + `os.killpg`. Without this, killing the shell on Windows leaves child `node`/`npm` processes alive holding the pipe handles, which makes the parent `subprocess.communicate()` block past the timeout.
4. **Synthetic timeout marker** in the returned log so the caller can surface "scaffold timed out after Ns" cleanly instead of returning blank output.

A new test file [tests/test_scaffold_subprocess.py](tests/test_scaffold_subprocess.py) hits the real subprocess path with: a stdin-reading shell command (which would hang without DEVNULL), a 30s sleep guarded by a 2s timeout (which would block past the timeout without the kill-tree handling), and a Python-process env-var probe (which would fail without the env propagation).

**Consequences**

- Vite/Next/Astro scaffolders run to completion in 1-4s; no hangs.
- A misbehaving scaffolder dies on time with a diagnosable error.
- *Tradeoff*: subprocess management on Windows is now more complex (taskkill /T) but the alternative is the silent hang.

---

## ADR-22: SKILL.md retrieval — first-class `skill_load` and `skill_query` (BM25)

**Status:** Implemented — see ADR-9 (load full doc) and ADR-13 (BM25 chunked queries) for the existing pieces, this ADR captures the stitched cross-surface UX.

The agent loads a SKILL.md via `skill_load(skill="…")` for first encounter (refused-on-call by the gate, ADR-11) and queries chunks via `skill_query(skill, query, k=3)` for follow-ups. The CLI shows both as distinct events: 📚 SKILL.md panel for `skill_load`, a labelled tool row for `skill_query`. The frontend's `ToolEventRow.vue` highlights `skill_load` events with an accent-bordered row + condensed/verbatim badge so the user can audit how often the agent is consulting docs vs. winging it.

---

## ADR-23: Plan-required gate — multi-step write workflows refuse without an active plan

**Status:** Implemented (`chika/core/workflow_engine.py:_check_plan_required`)

**Context**

The skill gate (ADR-11) made the agent load `plan_skill/SKILL.md` before its first plan_* call. But "having read the SKILL.md" and "actually using `plan_set` instead of just diving in" turned out to be different problems. In the user's session right before this ADR landed, the agent loaded the plan SKILL.md, then immediately wrote `main.py` and ran `pip install pygame` with no `plan_set` anywhere in sight — exactly the failure mode the SKILL.md warns against. Prompt-only enforcement isn't enough.

**Decision**

A runtime gate at the top of `WorkflowEngine.execute`:

1. Walk the workflow tree and collect every leaf tool name.
2. Count tools that match the curated `_WRITE_TOOLS` set (`file_write`, `shell_exec`, `python_run`, `live_server`, `scaffold_web_app`, `git_commit`, browser writes…).
3. If the count is **≥ 3** AND `$plan` doesn't exist (or has no tasks) AND no `plan_*` tool appears in the workflow itself, REFUSE the workflow.

The refusal yields a synthetic `tool_call` + `tool_result` with `error: "plan_required"` and a payload listing the offending writes plus a hint pointing to `plan_set`. The engine's `_run_workflow` formats this special-case error so the LLM sees the hint inline (alongside the existing `skill_doc_required` formatting). Auto-continue (ADR-10) fires the next turn; the agent emits a new workflow whose first step is `plan_set`; the gate is now satisfied; the workflow body runs.

The threshold of 3 writes (not 2) is deliberate — single-edit fixes and tiny scaffolds shouldn't pay the cost of a plan. Read-only workflows (`file_read`, `git_status`, `git_diff`) are completely exempt.

**Consequences**

- "Make me a powder toy clone" can no longer skip the plan; the user always sees a checklist before real work starts.
- The agent has two valid escape hatches: include `plan_set` AS the first step of the same workflow (one round-trip), or run `plan_set` in its own workflow first. Both are explicit in the hint.
- *Tradeoff*: when the agent picks "include plan_set in this workflow", it commits to plan + execution in one batch — riskier than separating them, since plan errors block real work. Acceptable: plan_set is cheap and the gate's purpose is to make the plan exist, not to choreograph it.

---

## ADR-24: `python_run` is the canonical entrypoint for Python scripts; `shell_exec("pip install …")` is a system-prompt anti-pattern

**Status:** Implemented (`chika/core/prompt_builder.py`)

**Context**

In the same session that exposed ADR-23, after `pygame` failed to build from source on Python 3.14, the agent's response was: "run this in PowerShell to fix it: `python -m pip install pygame-ce`". That defeats the entire purpose of `python_run` (ADR-17) which has the `pygame → pygame-ce` fallback chain built in. The agent regressed because the prompt rule didn't EXPLICITLY forbid `shell_exec` for pip install.

**Decision**

Add a hard rule under `# CROSS-CUTTING TOOL RULES`:

> **NEVER `shell_exec("python -m pip install <package>")` to fix a missing import.** That bypasses python_run's fallback chain and dumps the user into "manually run this command" land. ALWAYS use `python_run` for the *script*; pip install is its job, not yours.

**Consequences**

- The agent's natural reach for a fresh shell command on missing-import errors gets caught at prompt time.
- `python_run`'s fallback table (`pygame → pygame-ce`, `cv2 → opencv-python`, `PIL → Pillow`, etc.) is the single source of truth for "this import works on this Python version".
- *Tradeoff*: prompt rules are still soft compared to the runtime gate (ADR-23). If the agent ignores the rule, the user sees the bad shell output. A future runtime guard that intercepts `shell_exec` calls containing `pip install` and rewrites them is possible but not worth the complexity for now.

---

## ADR-25: Layered test pyramid with stub-LLM e2e on every surface; live-LLM tests gated behind `--live-llm`

**Status:** Implemented (`tests/`, `frontend/e2e/`, `extension/e2e/`, `.github/workflows/`)

**Context**

The pre-existing suite covered backend internals well (~830 tests) but had no e2e for the CLI renderer, frontend, or extension. UI bugs (CLI panel layout, frontend plan-rendering wiring, extension popup state) were detected only by manual smoke. We also had no convention for tests that hit a real LLM: a "should we run that?" decision happened ad-hoc every time someone added one.

**Decision**

Build a four-layer pyramid:

1. **Backend stub-LLM** (`tests/test_e2e_engine_stub.py`) — engine is real, prompt builder is real, workflow engine is real, skill registry is real. Only `_stream_llm` and `_llm_complete` are scripted via `tests/_helpers/stub_llm.py`. Every event the user / CLI / WS sees is asserted on. Cheapest layer with the highest signal-to-noise.

2. **CLI subprocess** (`tests/test_e2e_cli.py`) — spawns `python chika.py` with `CHIKA_STUB_LLM_SCRIPT=...` (a runtime hook in `ChikaEngine.__init__` that reads a JSON script from disk when set). stdin / stdout are real pipes; ANSI is stripped before assertions. Every panel, slash command, and rendering path runs end-to-end without burning a token. The harness is `tests/_helpers/cli_harness.py` (`run_cli`, `script`, `text_turn`, `workflow_turn`).

3. **Frontend Playwright + Vitest** (`frontend/e2e/`, `frontend/src/**/__tests__/`) — Playwright for full-app flows with `window.WebSocket` replaced by a mock that lets tests inject any sequence of engine events. Vitest for store / component unit coverage. Visual snapshots under `frontend/e2e/visual.spec.js-snapshots/`.

4. **Extension Playwright** (`extension/e2e/`) — `chromium.launchPersistentContext` with `--load-extension=...`, popup URL discovered from the registered service worker. Covers popup smoke, background SW lifecycle, and visual snapshots.

5. **Live-LLM smoke** (`tests/test_live_llm_smoke.py`) — `@pytest.mark.live_llm`. The conftest auto-skips these unless `--live-llm` is passed (or `CHIKA_RUN_LIVE_LLM=1`). CI never flips either. There's a separate manually-triggered workflow (`.github/workflows/live-llm.yml`) for explicit "run a real model before release" runs.

The frontend's `system.js` got a small fix in the same change: `tool_result` events for `plan_*` tools now unpack `result.plan` into `variables.plan.value`, and `workflow_done` merges the full variables dict into the store. Without this, the plan panel saw only the truncated 120-char preview from `variable_set`. The e2e tests caught it on the first run.

**Consequences**

- Every UI surface has a deterministic regression net.
- The stub-LLM pattern is reusable: add a turn list, hand to `install(engine, StubLLM(...))`, drive `engine.chat()`. New regressions land as a new test in < 30 LOC.
- The `live_llm` gate makes "yes you may call the real LLM here" an explicit decision rather than an implicit cost.
- *Tradeoff*: visual snapshots need refreshing when the design changes. Update with `npx playwright test --update-snapshots visual.spec.js`. Baselines are committed under `<spec>-snapshots/<name>-chromium-<os>.png` so CI's ubuntu baselines match a `--update-snapshots` run on the same OS.

---

## ADR-26: Visual snapshots are platform-specific; CI generates Linux baselines via labelled workflow rather than locally via Docker

**Status:** Implemented (`frontend/playwright.config.js`, `.github/workflows/update-snapshots.yml`)

**Context**

Visual baselines under `frontend/e2e/*-snapshots/` are pixel-compared in CI. Chromium renders fonts and antialiasing slightly differently across Linux, macOS and Windows even with identical DOM and CSS — so a baseline a dev generates on macOS or Windows will fail in CI on `ubuntu-latest`. Microsoft's Playwright docs flag this explicitly and recommend two paths:

1. Devs run snapshot generation inside the official `mcr.microsoft.com/playwright:vX-jammy` Docker image so locally-produced baselines match the CI runner.
2. CI itself regenerates baselines on demand and commits them back.

(1) requires every dev to install Docker. Some don't have it, some are on locked-down corporate machines, some are on Windows where the Docker → WSL2 setup is awkward. We hit this directly: a Windows-based dev pushed beautiful Win32 baselines that all failed on Linux CI's `chromium-linux` channel.

**Decision**

Take path (2). Per-platform baselines are committed (`*-chromium-linux.png` for CI, optional `*-chromium-win32.png` / `*-chromium-darwin.png` for local dev preview). The standard Playwright path template (which embeds `-{platform}` in the filename) is used — we don't try to share one baseline across platforms.

The `.github/workflows/update-snapshots.yml` workflow regenerates the Linux baselines on demand:

- Triggered when a PR is labelled `update-snapshots`, OR by manual `workflow_dispatch`.
- Spins up `ubuntu-latest`, runs `npx playwright test --update-snapshots`, commits the regenerated `*-chromium-linux.png` files back to the PR's source branch via the workflow's `GITHUB_TOKEN`.
- Removes the `update-snapshots` label after running so the workflow doesn't re-trigger in a loop.

This pattern is what Vercel (Next.js), Microsoft (playwright-mcp) and others use for the same problem.

**Consequences**

- Devs don't need Docker locally. Push UI changes, see CI fail on visual diff, label the PR, re-baseline lands as a follow-up commit on the same PR.
- The CI-generated baselines are the ground truth. Local platform baselines (`-chromium-win32.png` etc.) are convenience artefacts for design review — CI never reads them.
- *Tradeoff*: a malicious PR could push UI regressions and self-label to "rebaseline" them. Mitigation: maintainers gate the label, and `permissions: contents: write` is scoped to the head branch only — the workflow can't push to `main` directly.
- *Future*: if Docker becomes a standard dev requirement, swap the workflow trigger for a local `npm run update-snapshots:docker` script so the dev cycle is self-contained.

---

## ADR-27: One brand mark, four surface tiers — geometry duplicated by hand because no shared rendering model spans them all

**Status:** Implemented (`frontend/src/components/ChikaMark.vue`, `extension/popup/popup.html`, `extension/popup/popup.css`, `extension/icons/_render.html`, `extension/icons/_render.mjs`, `chika/_cli/mark.py`, `chika/_cli/renderer.py`)

**Context**

Chika's brand mark — a stroke-only 3-leaf trefoil with a centre anchor dot — needs to render consistently on four surfaces with completely incompatible rendering models:

1. **Frontend (Vue 3 SPA)** — full SVG with CSS animations.
2. **Extension popup (`popup.html`)** — vanilla HTML + CSS, no Vue runtime, no module imports across the manifest boundary. Inline SVG with the same CSS animations.
3. **Chrome toolbar icon (manifest)** — Chrome MV3 hard constraint: only static PNGs at 16/32/48/128 px. **Cannot animate at all** — even Lottie / WebP-animated decode to a single static frame.
4. **CLI banner (rich/Python)** — monospace terminal grid. No SVG support, no curves, no animation primitives below the rich.Live API.

A single source of truth (one SVG file, imported everywhere) is impossible: Vue can't import into the popup's manifest context, Chrome's manifest only accepts PNG paths, and a terminal grid can't render SVG. The geometry must live in 4 places.

The animation states (idle / thinking / streaming / success / intro) are similarly divergent — the Vue component's per-leaf flip animation can't survive PNG export, and the half-block character grid in the CLI can't carry per-leaf rotation either.

**Decision**

Accept the duplication. Codify a "geometry parity rule" so each downstream copy is recognisably the same mark.

The **canonical** definition lives in `frontend/src/components/ChikaMark.vue`. It owns:

- Petal cubic-bezier path: `M 0,-58 C 13,-44 19,-22 0,-6 C -19,-22 -13,-44 0,-58 Z`
- Angles: `[0, 120, 240]`
- Hub-dot radius: `3.2`
- Stroke width: `3.4` (with `vector-effect: non-scaling-stroke`)
- All five animation states (idle, thinking, streaming, success, intro)

Three downstream copies must mirror those constants by hand:

| Surface         | Source file                         | What it carries                                |
|-----------------|-------------------------------------|-------------------------------------------------|
| Popup HTML      | `extension/popup/popup.html`        | Inline SVG + matching CSS in `popup.css`       |
| Manifest PNGs   | `extension/icons/_render.html`      | Same SVG, screenshot by `_render.mjs` to PNGs   |
| CLI banner      | `chika/_cli/mark.py`                | Python rasteriser — same cubic, half-block out  |

Each downstream file has a header comment pointing back at `ChikaMark.vue` as the source of truth.

**Workflow when geometry changes**

1. Edit `ChikaMark.vue` (canonical).
2. Mirror the same numbers into `popup.html`, `popup.css`, `_render.html`, and `chika/_cli/mark.py`.
3. Re-run `node extension/icons/_render.mjs` from `extension/` to regenerate manifest PNGs.
4. Run `python -m chika._cli.mark` to spot-check the CLI rasterisation.

**Animation state mapping per surface**

Different surfaces drop down to a strict subset based on what their rendering model can carry:

| State     | Vue / Popup           | Manifest PNG | CLI banner |
|-----------|-----------------------|--------------|------------|
| idle      | per-leaf prime breath | static       | static     |
| thinking  | periodic unfurl pulse | n/a          | static (state-row indicator carries the activity feel — see ADR-28) |
| streaming | sin-wave brightness   | n/a          | static (same) |
| success   | cascade pop           | n/a          | static     |
| intro     | rotateY-flip cascade  | n/a          | static     |

The CLI doesn't attempt animation in the banner — half-block half-pixel grids don't carry rotation gracefully, and a one-shot startup banner doesn't need to. *During* a turn, the inline state-row indicator (ADR-28) carries the activity feel instead.

**Consequences**

- Geometry changes require 4 file edits + a regen command, not 1. We accept this cost in exchange for native rendering on every surface — nothing is a screenshot, nothing is a fallback.
- Animation richness scales naturally with the surface. The mark still reads as the same trefoil everywhere because the silhouette is identical.
- *Tradeoff*: the duplicated CSS/SVG in `popup.css` and `popup.html` could drift from `ChikaMark.vue` if a maintainer only edits one. The header comment + this ADR are the only guard.
- *Future*: if/when the popup grows a Vite build pipeline, replace its inline SVG with an imported component from a shared package — that's the only path to deduplicate without losing native rendering.

---

## ADR-28: Inline state indicator with LLM-generated context-aware verbs (fire-and-forget)

**Status:** Implemented (`chika/_cli/state_verbs.py`, `chika/_cli/mark.py`, `chika/_cli/renderer.py`, `api/settings_store.py`, `chika/_cli/commands.py`, `frontend/src/components/SettingsModal.vue`)

**Context**

Claude Code shows an inline activity row while a turn is in flight: `✸ Vibing… 2.3s`. It's a single line that conveys "the agent is doing something, here's roughly what" — much friendlier than a blank screen during a long LLM call. The pattern is small but high-impact for perceived responsiveness.

We wanted the same in the chika CLI, with two upgrades:

1. **Visual parity with our trefoil mark** — the glyph beside the verb should read as our 3-leaf trefoil, not a generic asterisk. ADR-27 owns the geometry; this ADR owns how that geometry compresses to one terminal row.
2. **Context-aware verbs**, not a fixed rotation. "Vibing / Pondering / Cooking" works generically but "Investigating / Tracing / Diagnosing" is much better when the user just asked "why is this test failing" — the verbs match the *shape* of the request.

**Decision**

The indicator is a single inline row showing three triangle glyphs `◣ ▲ ◢` — one per trefoil leaf — with the highlighted leaf rotating each frame, then a verb and an elapsed-time counter:

```
  ◣ ▲ ◢   Investigating…   2.3s
```

Highlight rotation goes top → right → left, the same direction as the SVG's streaming wave (sin(2π(t/T − i/3))).

**Verbs are generated per turn by an LLM call** in a fire-and-forget background task — same shape as `pet_speech.py`. Pattern:

1. User submits a message → renderer opens the indicator window + kicks off the LLM call asking for 6-8 present-continuous verbs that fit *this specific* request.
2. Until the call returns, the indicator cycles through static defaults (`mark.INLINE_VERBS`).
3. When the call lands (~hundreds of ms later), `_state_verbs` is replaced with the contextual list and the indicator swaps in mid-cycle.
4. If the call fails, times out, or `state_verbs == "off"`, the static list keeps showing — the feature degrades gracefully.

**Settings (in `api.settings_store`)**

| Key                   | Type           | Default | Description                                       |
|-----------------------|----------------|---------|---------------------------------------------------|
| `state_verbs`         | `"on" / "off"` | `"on"`  | Whether to fire the LLM call at all              |
| `state_verbs_tokens`  | `int [16,200]` | `80`    | Token budget per LLM call                         |

Surfaced in:

- CLI: `/state verbs on|off`, `/state tokens <int>`
- Frontend: Settings → Behaviour tab

**Visibility window**

The indicator is shown only when no other UI is taking visual responsibility:

- Hidden when the tool spinner row is rendering (a tool is mid-execution).
- Hidden once `_answer_buf` has any tokens (streaming text takes over).
- Hidden once `_thinking_buf` has any reasoning (the thinking panel takes over).
- Cleared at `end_turn`.

So in practice the indicator fills the dead air between user input and the first sign of life, and again between tool completions if the LLM is rethinking.

**Consequences**

- The CLI feels alive between turns — same friendly responsiveness Claude Code has, with verbs tuned to the user's specific request.
- *Cost*: one extra ~80-token LLM call per turn. With Anthropic Sonnet-4 pricing this is sub-penny per turn; users on tight budgets can flip `state_verbs` off and pay nothing for the feature.
- *Tradeoff*: if the LLM call is slow, the contextual verbs may not arrive before the user has already seen the static defaults. We accept this — the swap is seamless and the static defaults are reasonable.
- *Future*: cache the verb list per (user-message-hash) so re-asks reuse the same verbs without re-generating. Probably not worth the cache layer until users complain.

---

## ADR-29: One-command install + auto-update gated on upstream CI

**Status:** Implemented (`chika/_cli/install_extension.py`, `chika/_cli/update.py`, `chika/_cli/doctor.py`, `chika/_cli/app.py`, `chika/_cli/commands.py`, `api/settings_store.py`)

**Context**

Two install pain-points kept showing up:

1. **Loading the browser extension**: users had to find the cloned repo's `extension/` directory by hand, navigate Chrome's settings, toggle dev mode, click Load unpacked. We can't actually install Chrome extensions programmatically — Chrome MV3 has forbidden that since 2014, only the Web Store and "Load unpacked" remain — but we *can* automate everything except the final mouse clicks.
2. **Updating Chika**: there was no obvious update path. `git pull` worked for clone installs, `pip install --upgrade chika` for pip installs, but nothing for someone who didn't know which they had. And nobody actually thinks to update — the new feature ships in main, the user keeps running last week's bits.

**Decision**

Three new entry points, each available both as an argv subcommand (`chika <name>`) and a slash command (`/<name>`):

| Command            | Argv                       | Slash                       |
|--------------------|----------------------------|-----------------------------|
| install-extension  | `chika install-extension`  | `/install-extension`        |
| update             | `chika update [--check]`   | `/update [--check]`         |
| doctor             | `chika doctor`             | `/doctor`                   |
| auto-update toggle | —                          | `/auto-update [on\|off]`    |

**install-extension** copies the runtime subset of `extension/` (manifest + `popup/` + `lib/` + `content/` + `options/` + `icons/*.png`, excluding `node_modules/`, `e2e/`, `test-results/`, `package*.json`, `playwright.config.js`, `_render.*`, `generate_icons.js`) to `~/.chika/extension/`, opens `chrome://extensions/` via `webbrowser.open`, and prints a 3-step instruction Panel. Wipe-and-recopy on each run so a release that renames a file doesn't leave the old one behind.

**update** detects install kind:
- `git_clone` (`.git/` present) → `git pull --ff-only` + `pip install -e . --upgrade --no-deps`
- `pip_pypi` (importable + has metadata, no `.git/`) → `pip install --upgrade chika`
- `unknown` → print the manual command for both paths

**Auto-update on startup** is the most opinionated piece. When `auto_update == "on"` (default), the CLI fires a background thread on REPL boot that:

1. Hits the GitHub API for the latest commit on `main` plus its check-runs status (or PyPI's JSON API for pip installs).
2. If a newer SHA exists *and* CI is green *and* the user is on `main`/`master` *and* the working tree is clean *and* we haven't already auto-applied this SHA, run `update_chika` silently and print one line: `· auto-updated abc1234 → def5678 (restart Chika to load the new code)`.
3. Persist `last_check_at`, `last_remote_sha`, `last_applied_sha` to `~/.chika/update_state.json`. Throttle network checks to once per hour (GitHub's unauthed REST is 60 req/h).
4. On any failure (offline, rate-limited, dirty tree, feature branch, CI red, non-GitHub remote), record the reason in state and surface a `· update available` notice if there's a new SHA we just can't auto-apply.

The CI gate is the heart of this design. We never auto-roll the user onto a commit whose checks are still running, failing, cancelled, or absent — `_check_runs_all_green` requires every check-run to have `status=completed` and `conclusion ∈ {success, skipped, neutral}`. No CI configured at all → fail-safe, treat as not green.

**doctor** prints a report with one row per check (Python version, every required import, bundled extension intact, frontend built, `.env` present, `data/` writable, console script on PATH). Returns severity `ok | warn | error`; the argv subcommand exits with code 0 for ok/warn and 1 for error so install scripts and CI can gate on it.

**Why all four guards on auto-update**

- *CI gate*: don't roll users onto broken main.
- *Branch gate*: a `git pull --ff-only` on a feature branch would pull `origin/feature/x`, which has no relation to upstream main. Skip.
- *Dirty-tree gate*: pip install -e is fine over a dirty tree, but a `git pull` could conflict with WIP. Belt-and-braces.
- *Throttle*: two parallel chika launches could each fire a network call; the throttle absorbs that. GitHub's rate limit absolutely will bite users who don't have this.

**Why no auto-restart**

After update, the in-memory Python is still running last commit's bytecode. Restarting requires either re-execing or relaunching the shell — both fragile across IDEs, Docker, ssh sessions, prompt_toolkit's terminal grabs, etc. We tell the user "restart Chika" and exit. That's a worse UX in the abstract but a much more reliable one in practice.

**Test surface**

- `tests/test_install_extension.py` — 43 tests on the copy semantics, exclusions, idempotency, browser open, slash + argv commands, plus a real-extension smoke test that asserts every path the manifest references actually lands on disk.
- `tests/test_update.py` — 86 tests covering URL parsing, install-kind detection, every CI conclusion the GitHub API returns, the dirty-tree and feature-branch guards, throttle logic, state file persistence under failure, and the slash + argv commands.
- `tests/test_doctor.py` — 32 tests on each individual check + the orchestration + the cross-check that REQUIRED_IMPORTS doesn't drift from pyproject.toml's dependencies and `MIN_PYTHON` matches `requires-python`.
- `tests/test_install_chika.py` — 34 install-structure assertions: console script registered, `requirements.txt` mirrors pyproject runtime deps, every path the Chrome manifest references is on disk, every settings init key is seeded, and the doctor itself runs clean against this repo.

**Consequences**

- A clean checkout is now `git clone … && python install.py && chika install-extension` and the user is fully set up.
- Users no longer fall behind silently — Chika updates itself when it's safe to.
- *Tradeoff*: one extra GitHub API call per chika launch (throttled to ~24/day at most). If Chika ever goes viral we'll hit GitHub's anonymous rate limit; the path forward is GitHub App auth or moving the SHA + CI status check to a tiny CDN-cached JSON file we publish from CI.
- *Tradeoff*: PyPI publishing isn't gated on CI green at the registry level — a maintainer could push a broken release. We treat "newer version exists on PyPI" as `ci_green=True` because the publish step itself is in our CI workflow. If we ever change that, this assumption needs revisiting.

---

## ADR-30: Native installers per OS, app-manager parity, GitHub Pages landing

**Status:** Implemented (`installers/`, `chika/_cli/setup.py`, `chika/_cli/uninstall.py`, `chika/_cli/update.py`, `docs/`, `.github/workflows/release.yml`, `.github/workflows/pages.yml`, `api/settings_store.py`)

**Context**

Three problems were stacked:

1. The only documented install path was `git clone + python install.py`. End users (not contributors) don't want to think about Python or git — they want a button.
2. There was no way to uninstall Chika via the OS app manager (Add/Remove Programs on Windows, Applications-folder convention on macOS, `apt remove` on Linux). Pip-installed packages are invisible to those tools.
3. Auto-update only worked for git clones and (eventually) PyPI. A user who installed via a hypothetical native installer would have nothing.

**Decision — installers**

Three native installers + a universal Linux fallback, all per-user (no admin/sudo for any except macOS where `.pkg` to `/Library/...` requires it):

| OS | Format | Build tool | Install dir | Add/Remove Programs entry |
|---|---|---|---|---|
| Windows | `chika-setup-X.Y.Z.exe` | Inno Setup 6 (`installers/windows/chika.iss`) | `%LocalAppData%\Programs\Chika\` | Yes — Inno's AppId GUID |
| macOS   | `Chika-X.Y.Z.pkg`        | `pkgbuild` + `productbuild` | `/Library/Application Support/Chika/` + `/usr/local/bin/chika` symlink | `pkgutil` receipt + manual uninstall.sh |
| Linux (.deb) | `chika_X.Y.Z_all.deb` | `dpkg-deb`               | `/opt/chika/` + `/usr/bin/chika` shim | Yes — `dpkg -s chika`, `apt remove` |
| Linux (any) | `install.sh` (curl\|bash) | n/a                      | `~/.local/share/chika/` + `~/.local/bin/chika` shim | Manual `uninstall.sh` |

Each installer:

- Builds a venv on the user's machine (Python 3.11+ required) — venvs aren't relocatable so we don't ship one prebuilt.
- `pip install`s a bundled wheel into that venv.
- Drops a launcher shim (`chika.cmd` on Windows, `chika` shell script elsewhere) that exports `CHIKA_DATA_DIR=~/.chika/data` before forwarding to the venv. This means user state lives outside the install dir and survives uninstall.
- Writes `install_marker.json` with `{"kind": "<install_kind>", "version": "..."}` so `chika update` knows which auto-update path to take.
- On missing-Python, opens `python.org/downloads/` in the user's default browser instead of just printing an error.

**Decision — uninstall parity**

Both surfaces work:

- OS-native (Add/Remove Programs / `sudo .../uninstall.sh` / `apt remove`) — what users expect.
- `chika uninstall` — detects the install kind and either runs the right uninstaller (with `--yes`) or prints the exact command (default — show, don't surprise).

`chika uninstall` defaults to **preserving** `~/.chika/`. `--remove-data` opts in to wiping it. Same default applies to every OS-native uninstaller; reinstall picks up exactly where the user left off.

**Decision — auto-update for native installers**

`chika/_cli/update.py` gained four new `install_kind`s: `windows_installer`, `macos_installer`, `linux_deb`, `linux_universal`. Detection mirrors the marker file pattern (with a fallback to `dpkg -s chika` for the .deb case in case the marker was nuked).

Per-kind update behaviour:

- `windows_installer`: download `chika-setup-X.Y.Z.exe` from `releases/latest` and run with `/SILENT /SUPPRESSMSGBOXES`. Inno detects the existing install via AppId GUID and runs an in-place upgrade.
- `macos_installer`: download `Chika-X.Y.Z.pkg`, run `installer -pkg <path> -target ...`.
- `linux_deb`: (when we publish to an apt repo) `apt-get install --only-upgrade chika`. For now, manual `dpkg -i` of the next `.deb`.
- `linux_universal`: re-run `install.sh`. The script is idempotent — first install + upgrade + reinstall all work.

Asset filename patterns are encoded in `_expected_asset_name(kind, version)` in `update.py`. Build scripts produce matching names. A test (`test_installer_structure.py`) cross-checks the two so drift fails CI.

**Decision — GitHub Pages landing**

`docs/` is a single-page static site at `tochi-mba.github.io/chika`. Auto-detects the visitor's OS via `navigator.userAgent`/`navigator.platform`, fetches `releases/latest` from the GitHub API, and re-targets the primary CTA at the right asset. Falls back to a generic "view all releases" link if the API is rate-limited or there are no releases yet.

The page mirrors the CLI's brand mark + thinking-state animation by hand-duplicating the canonical SVG geometry (extending ADR-27's parity rule to a fifth surface). Visitors see the same chika they get in the terminal.

The page leans heavily on the **"settings change anytime"** reassurance — a recurring pain point with installers is users worry that pre-install choices are permanent. The landing tells them three times (hero subtitle, install card hints, footer reassurance) that everything is changeable.

**Decision — `chika setup` + first-run nudge**

After install, the user runs `chika` and gets a one-line hint: `first-run? provider + API key not configured. run /setup to launch the wizard`. They can dismiss it (just type their question) or run the wizard. The wizard is the same `install.py main()` that contributor installs use — single source of truth, no parallel prompt logic.

`chika setup` is also exposed as an argv subcommand for users who haven't booted the REPL yet.

Edge cases the wizard guards against:

- Non-TTY stdin → refuses (CI / piped input would block forever).
- Existing `.env` with content → refuses without `--force` (don't silently clobber a working configuration).
- Python below 3.11 → fails before asking for an API key.
- `install.py` missing or has no `main()` → corrupted install error message with the manual remediation command.

**Decision — `CHIKA_DATA_DIR` env var**

`api/settings_store.py` resolves the settings path from (in order): `CHIKA_SETTINGS_PATH`, then `CHIKA_DATA_DIR + "/settings.json"`, then `data/settings.json` relative to cwd. The launcher shims for all four native installers export `CHIKA_DATA_DIR=~/.chika/data` so settings persist across uninstalls. Future state stores (chat history, profiles, memory) can opt into the same env var without inventing new ones.

**Test surface**

- `tests/test_installer_structure.py` (65 tests) — installer file shape, Inno required sections, AppId is a GUID, asset naming matches the build scripts, marker contracts, brand-mark geometry parity between docs and the canonical Vue path, bash syntax checks (Linux/macOS only — skipped on Windows because MSYS bash mangles paths), PowerShell brace balance + ErrorActionPreference, Debian control fields, release workflow attaches all assets, Pages workflow deploys docs/.
- `tests/test_setup.py` (24 tests) — every guard, every error path, the slash + argv wiring, the first-run nudge content.
- `tests/test_uninstall.py` (25 tests) — every install kind, runner-failure paths, `--remove-data` semantics, console rendering, slash + argv wiring.
- `tests/test_update.py` (extended; 120 tests) — the four new install kinds, `_check_native_installer_upstream`, `_find_installer_asset`, `_dpkg_has_chika`, `_download_file` scheme guard, marker file detection across all kinds.

**Consequences**

- A new user goes from `tochi-mba.github.io/chika` → click → installer wizard → `chika` works in any terminal in under a minute. No git, no Python (well, Python is required, but the installer opens python.org if missing). No "where do I put this folder."
- Uninstall feels native: open Add/Remove Programs, click Uninstall. The CLI option exists for power users.
- Auto-update keeps working post-install — same `chika update` on the CLI, same notice on REPL launch.
- *Cost*: more CI surface (windows-latest + macos-latest + ubuntu-latest jobs in `release.yml`). Each installer build adds ~2-3 minutes per release.
- *Tradeoff*: installers are unsigned. Windows SmartScreen will show "Windows protected your PC" on first run; macOS Gatekeeper will refuse the .pkg without authentication. The next round adds Authenticode + Apple Developer ID + GPG signing — out of scope here because all three need cert procurement.
- *Tradeoff*: the macOS .pkg installs to `/Library/Application Support/` which requires admin. Per-user macOS installs would land at `~/Library/Application Support/` and not need admin, but then we can't symlink to `/usr/local/bin/`. Users would have to add `~/Library/Application Support/Chika/` to PATH manually, which isn't mac-native UX. We chose the admin-required path because it's standard.
- *Future*: code signing, AppImage builds, RPM builds, an in-frontend "Uninstall Chika" button (calls a new `/api/uninstall` endpoint that shells out to `chika uninstall --yes`).

---

## ADR-31: Event contract — Pydantic-validated, surface-routed, drift-detected

**Status:** Implemented (`api/models.py`, `api/event_routing.py`, `api/server.py`, `extension/background.js`, `tests/test_event_contract.py`)

**Context**

A staff-engineer architecture review of Chika identified the strongest property as "one engine, four surfaces" and warned that cross-surface drift would silently erode the differentiator over time. Three audits confirmed the concern:

- `api/models.py` had Pydantic event models, but they were **never validated** at emit time — events flew as raw dicts on the WS edge.
- `extension/background.js` correlated `tool_call` and `tool_result` via `id || step_id || (tool + '_' + Date.now())` — when `step_id` was absent, the fallback generated a fresh UUID, so `tool_call` and the matching `tool_result` got different ids and never correlated. **Live bug** affecting reconnects.
- The extension silently dropped `validation_warning`, `thinking`, and `shell_*` events the frontend rendered — drift the type system couldn't see.

**Decision**

Three-part contract enforcement:

1. **`EventType` enum** in `api/models.py` — single source of truth for the 35+ event names the engine emits. Adding a new event means adding to the enum (drift becomes a compile-time-ish event).
2. **`validate_event(payload, *, strict=False)`** — runtime validator that routes by `type` to the matching Pydantic model. Strict mode raises on missing required fields (used in tests). Lax mode at the WS edge logs and lets the event through (validation is observability, not gatekeeping — the WS edge can't fail every time the engine emits something).
3. **`api/event_routing.py`** — declarative `CLI_EVENTS`, `FRONTEND_EVENTS`, `EXTENSION_EVENTS`, plus `EXTENSION_DROPS_ON_PURPOSE` for events the popup surface deliberately ignores. The contract test (`tests/test_event_contract.py`) asserts every `EventType` is in at least one set — silent drops fail CI.

**Bug fix:** `extension/background.js` now requires `step_id` on `tool_call` and `tool_result`. Missing step_id → console.warn + drop. Drops surface the caller bug instead of masking it with a UUID that breaks correlation downstream.

**Why opt-in strict mode**

The audit found 35+ event types, only 16 with Pydantic models. Forcing strict validation at the WS edge would block production until every type has a model. Lax-at-runtime + strict-in-tests means we get drift detection (CI fails when `tool_call` is emitted without `step_id`) without taking down the WS edge if the engine adds an unmodelled event.

**Consequences**

- The bug that broke `tool_call`/`tool_result` correlation across reconnects is fixed.
- Adding a new event type now has a consistent shape: enum entry, optional Pydantic model, route assignment.
- 26 contract tests in `tests/test_event_contract.py` lock the shape.
- *Future*: as more event models land, strict-at-edge becomes feasible. For now, opt-in strict in tests catches drift without production risk.

---

## ADR-32: Skill summary injection — pre-generated, hash-keyed, non-blocking

**Status:** Implemented (`chika/skills/summarizer.py`, `data/skill_summaries/<id>.json`, `scripts/regenerate_skill_summaries.py`, `tests/test_skill_summarizer.py`)

**Context**

The agent has 10+ skills, each with a SKILL.md. Today the agent doesn't see those docs unless it explicitly calls `skill_load(skill_id)` — so the agent is guessing which skills exist. Wrong guess → wasted turn. Right guess → skill_load → another turn. Either way, multi-turn cost on every novel skill use.

**Decision**

LLM-generated **summaries** of each SKILL.md, injected into the system prompt on every turn:

- 80-120 tokens per skill — `purpose`, `when_to_use` (3 bullets), `key_tools` (3-5 names), `anti_patterns` (1-2 bullets)
- Twelve skills × 100 tokens = ~1.2k system prompt overhead, fully prompt-cacheable
- Pre-generated and committed to `data/skill_summaries/<skill_id>.json` — **zero runtime LLM cost** in the common case
- CI gate (`tests/test_skill_summary_drift.py` — to be added) verifies every committed SKILL.md has a matching-hash summary

**Detection mechanism — SHA-256 of file bytes**

mtime resets on `git pull` / `git checkout` (worst alternative). Git SHA misses uncommitted edits. File size has trivial false negatives. Content-addressable hash is the only choice that's both correct and cheap (12 skills × ~4 KB = 48 KB to hash on init).

**Non-blocking architecture (mirrors `chika/_cli/state_verbs.py`)**

1. Engine `__init__` calls `summarizer.init_summaries(register_callback, skills)`.
2. Cached summaries with matching hash → registered synchronously before init returns.
3. Stale or missing summaries → registered as `PENDING_SUMMARY` placeholder + `asyncio.create_task(generate_summary_async(...))` queued. Bounded concurrency: `Semaphore(6)`. Per-call timeout 30s.
4. **Engine init returns immediately.** The agent boots, the user can chat. As background tasks complete, `register_callback` updates `engine._skill_summaries`. The system-prompt assembler reads this dict on every turn — so newly-completed summaries land in the **next** turn (not retroactively into completed turns).

**Stale summaries are dropped, not kept as fallback.** Outdated capability claims in front of the agent are worse than no summary. Hash mismatch → cache invalidated → regenerate.

**The summarization system prompt is load-bearing.** Its full text lives in `chika/skills/summarizer.py::SUMMARIZATION_SYSTEM_PROMPT`:
- Establishes the agent-facing audience explicitly
- Bad/good contrasts for every field (concrete examples beat abstract rules)
- Explicit "surface the impressive capability" instruction in the PURPOSE rule
- Strict length caps + JSON-only output rule
- Prompt-injection defence clause: SKILL.md is content, not instructions to the summarizer

**Skill-gate integration (lifts a real friction point)**

ADR-11's first-use skill gate now skips when the skill's summary is in the system prompt. The agent has enough context for a competent first-use; no need for the refuse-and-retry roundtrip. The gate fires only when the summary genuinely isn't available (still in-flight at boot, LLM unreachable). Saves a turn per skill in the common case.

**Consequences**

- The agent picks the right skill on the first try far more often.
- Adding a new skill = SKILL.md + `data/skill_summaries/<id>.json` (the latter generated via `scripts/regenerate_skill_summaries.py`).
- 35 unit tests in `tests/test_skill_summarizer.py` cover every edge: hash determinism, malformed LLM output, oversized fields, prompt-injection attempts, atomic write under crash, orphaned cache pruning.
- *Future*: an `--update` flag on `chika doctor` that regenerates summaries; a "skill explorer" UI in the frontend that surfaces the summaries to humans too.

---

## ADR-33: Browser tool resilience — selector cascade + idempotency

**Status:** Implemented (`chika/skills/browser_skill/selectors.py`, `chika/skills/browser_skill/idempotency.py`, `tests/test_browser_hardening.py`)

**Context**

The reviewer specifically called out browser automation as the subsystem most likely to dominate maintenance in 12-18 months. Audit confirmed: 18 browser tools, all CSS-`querySelector`-only, no fallback strategies, no idempotency on mid-flight disconnects. Two failure modes already in flight:

1. **Markup churn** — site renames a class, every cached selector breaks until the agent retries with a different spec.
2. **Mid-flight reconnect** — WS drops between `tool_call` and `tool_result`, engine retries the action, action double-fires (form submit, click "Buy now" → very bad).

**Decision**

Two new modules in `chika/skills/browser_skill/`:

1. **`selectors.py`** — `candidate_specs(spec)` returns a cascade: CSS as-given → ARIA-aware variant when a label cue exists (`aria-label`, `title`, `alt`, `id`-as-words) → text-content variant via the extension's `:has-text("...")` synthetic pseudo. Successful resolutions cache per `(url, original_spec)` so subsequent actions reuse the working spec without re-cascading.
2. **`idempotency.py`** — `IdempotencyKey.from_call(tab_id, action, args) → SHA-256 hash`. `IdempotencyCache` stores results with a 30-second sliding TTL. On reconnect within window, the engine returns the cached result instead of re-running. Outside window, action runs again (state likely changed).

**Why 30 seconds for the idempotency window**

Long enough to absorb realistic WS reconnects (most complete < 5s, mobile network blips < 30s). Short enough that the agent's "I'll do X" → user-page-state assumption stays consistent (after 30s, the page may have changed; re-running is the right call).

**Why per-tab in the idempotency key**

A "click submit" on tab 42 is a different action from the same on tab 51. Sharing a cache across tabs would mask real divergence.

**Consequences**

- Markup-churn-driven test failures should drop sharply once the cache warms up.
- Form-double-submit class of bugs: gone for 30-second window.
- 21 unit tests in `tests/test_browser_hardening.py` lock the cascade + idempotency contracts.
- *Future*: Playwright `dom_resilience.spec.js` extension test that mutates a synthetic page mid-flight and asserts the cascade survives — needs the extension's content script to consume `candidate_specs()` first.

---

## ADR-34: Permission audit log

**Status:** Implemented (`api/audit_log.py`, `tests/test_audit_log.py`)

**Context**

Trust UX is the moat for an agentic tool. The audit found: categories work, ask/skip works, autonomy mode works — but there's no audit trail. Users can't see what was approved when, can't grant temporarily, can't see what changed.

**Decision**

Append-only NDJSON at `data/audit.jsonl`. One record per:

- **approval** — user said yes/no to a tool prompt
- **permission_change** — category flipped from ask → skip etc.
- **grant_expired** — a timed grant TTL elapsed
- **tool_run** — tool executed (post-hoc, one line per actual run, not per WS event)

Schema: `{ts, kind, actor, tool, category, decision, ttl_minutes, reason, session_id}`. None-valued fields are dropped at serialization for compactness.

**Rotation:** capped at 10 MB. When the active log hits the cap, it's renamed to `audit.jsonl.<ts>` and a fresh log starts. Rotation failure is logged but non-fatal — better an over-cap log than a dropped record.

**Concurrency:** internal `threading.Lock` so two threads writing simultaneously don't interleave bytes. 16 unit tests prove this end-to-end.

**Why NDJSON**

- `tail -f` works in development
- Partial last line doesn't corrupt earlier records (unlike JSON arrays)
- Trivial to grep / pipe / parse with any line-oriented tool
- Same format the event log uses (Phase 4) — operationally consistent

**Consequences**

- Users have ground truth for "what tools did the agent run?"
- Foundation for a future "Permissions audit" view in the frontend Settings modal
- *Future*: `/audit [--last N]` slash command + `chika audit` argv subcommand for browsing the log; JIT timed grants (`"skip until <ts>"`) consume the same log infrastructure.

---

## ADR-35: Session event log + replay

**Status:** Implemented (`api/event_log.py`, `chika/_cli/replay.py`, `tests/test_event_log.py`)

**Context**

The differentiator is "one engine, multiple synchronized surfaces." This ADR makes that concrete: every WS event for a session lands in `data/sessions/<session_id>.jsonl`, and `chika replay <session_id>` dispatches the recorded events to any chosen surface — CLI, frontend, extension.

**Decision**

`api/event_log.py::EventLog` is a per-session NDJSON writer. The engine attaches one as a bus subscriber for the session it owns. Schema mirrors the event payload + `ts` (append-time, set if absent) + `session_id` (sanitised — alnum + `-` + `_` only, defends against path traversal).

**Rotation:** 5 MB per session — half the audit-log threshold because per-session traffic is bursty (many tokens during streaming, then idle). Rotated to `<id>.jsonl.<ts>`. Replay reads the active file by default.

**`chika replay`** has three surface modes:
- `cli` — dispatch through `Renderer.handle` (the CLI replays the session as if you were there)
- `raw` — dump each event as one-line JSON to stdout (good for grep / piping / fixturing)
- `count` — bucket by event type with totals (sanity check the recording)

`replay()` itself is a small primitive — takes an iterable of events and a handler. Skips `_internal` events by default. Catches handler exceptions per-event so one broken event doesn't stop the rest of the replay.

**Why this matters operationally**

- A user reports a bad turn → grab their `data/sessions/<id>.jsonl` → `chika replay --surface cli` reproduces the turn locally without re-calling the LLM.
- Demo: record a real session, `chika replay --surface count` shows the event-type histogram — concrete proof of "one engine emitting consistent events."
- Regression tests can use a recorded session as a fixture instead of mocking the engine.

**Consequences**

- 25 unit tests cover read/write, rotation, malformed-line resilience, sanitised session ids, replay dispatch, handler-exception tolerance, and all three CLI surface modes.
- The audit log (Phase 3) and event log (Phase 4) share the same NDJSON discipline — operationally consistent.
- *Future*: a "Surface diff" tool — given a session, replay it against all three surfaces and diff the resulting render trees. Catches drift in the surfaces' rendering (vs. the engine emitting drift, which Phase 0's contract handles).
- *Tradeoff*: 5 MB × N sessions adds up. Cleanup policy is a TODO; current state: nothing prunes the sessions/ directory automatically. A future `chika doctor` step could surface "you have 200 MB of session logs, prune?".

---

## ADR-36: Pyramid health enforcement + landing-page snapshot coverage

**Status:** Implemented (`tests/test_pyramid_health.py`, `docs/e2e/landing.spec.js`, `.github/workflows/update-snapshots.yml`)

**Context**

Two pieces of cross-cutting work the reviewer + user both flagged:

1. **Pyramid degradation** — the reviewer warned that the test pyramid would silently invert as the suite grows. Lots of unit tests today; six months from now we won't notice if half are gone.
2. **Landing-page visual coverage** — the v0 redesign introduced a richer DOM but the existing e2e suite only had behavioural assertions. A real visual regression (broken hero card, missing button) would slip through.

**Decision**

**Pyramid floors.** `tests/test_pyramid_health.py` runs `pytest --collect-only` at test time, counts collected tests, and fails CI if the total drops below `MIN_TOTAL_TESTS`. The floor is set to ~80% of the current count so a small handful of deletions doesn't trip the alarm, but a structural shift does. Refresh the floor as part of a deliberate-deletion PR.

**Landing-page snapshots.** `docs/e2e/landing.spec.js` now contains ~13 snapshot tests, each running across the 7 viewport projects in `docs/playwright.config.js` (desktop + 3 phone profiles + iPhone 14 landscape + 2 tablet profiles). Coverage:

- Per-section snapshots: header, terminal showcase, features, install, update, uninstall, footer
- Full-page snapshots on mobile/tablet projects (verifies the entire single-column flow)
- Interaction snapshots: mobile-nav-open, primary-CTA-hover, features-grid-with-hover
- Per-card snapshots: install-card-windows, install-card-curl

Total baselines: ~70 PNGs once generated.

**`update-snapshots` workflow extension.** `.github/workflows/update-snapshots.yml` already regenerated frontend + extension baselines on the `update-snapshots` PR label. Extended in this round to also regenerate `docs/e2e/*-snapshots/`. Maintainer flow: open PR → CI shows landing-page diffs → add `update-snapshots` label → workflow regenerates baselines on Linux runner → commits back to PR → CI passes. Same pattern Vercel / Microsoft Playwright-MCP use for the cross-platform-snapshot problem.

**Why generated on the runner, not locally**

Chromium's font rendering / antialiasing differs between Linux and macOS / Windows by 1-2 pixels per character — enough to fail a strict pixel-diff. CI runs on Linux; baselines must too. Generating locally and pushing them would just regenerate on next CI run with a diff. Saving everyone the cycle.

**Consequences**

- Visual regression in the landing page is now caught at PR time, not by a user noticing the broken hero on tochi-mba.github.io/chika.
- The pyramid alarm fires loud (CI fail) when the suite shrinks unexpectedly.
- *Cost*: one extra ~3 minute CI step (the docs-e2e Playwright job — it's 7 viewports × ~13 tests each).
- *Tradeoff*: snapshot tests are noisy on legitimate redesign PRs. Mitigated by the `update-snapshots` workflow being one click. Documented in CONTRIBUTING.md.

---

## ADR-37: Auto-gen tooling (codegen + drift detection)

**Status:** Implemented (`scripts/gen_event_types.py`, `scripts/gen_openapi_client.py`, `scripts/check_brand_parity.py`, `scripts/regenerate_skill_summaries.py`, `scripts/check_skill_tool_drift.py`, `scripts/scaffold.py`, `installers/asset_names.py`)

**Context**

After Phase 0 (event contract) + Phase 1 (skill summaries) shipped, the manual upkeep of derived files became the new bottleneck:

- The Vue store typings + extension JSDoc were hand-maintained against `api/models.py` Pydantic models. Adding a new event meant editing four files instead of one.
- The brand-mark cubic-bezier path was duplicated by hand on five surfaces (ADR-27 policy) — drift was a "did the contributor remember?" problem.
- Skill summaries (ADR-32) needed a contributor-runnable regeneration path.
- Each new tool, skill, event type, or ADR followed a conventional pattern that contributors had to remember from the existing examples.
- The installer asset filenames (`chika-setup-{v}.exe`, `Chika-{v}.pkg`, `chika_{v}_all.deb`) were hard-coded in three build scripts plus the auto-update module — drift would break ``chika update`` silently.

**Decision**

Seven scripts under `scripts/` + one module under `installers/`. Each is a small focused tool with `--check` mode for CI:

| Script | Purpose | CI gate |
|---|---|---|
| `gen_event_types.py` | Pydantic event models → TS interfaces (`frontend/src/types/events.d.ts`) + JSDoc typedefs (`extension/lib/event-types.js`) | `--check` |
| `gen_openapi_client.py` | FastAPI OpenAPI spec → typed REST client (`frontend/src/types/api.d.ts` + `frontend/src/lib/api-client.js`) | `--check` |
| `check_brand_parity.py` | Verify the trefoil cubic-bezier matches across all 6 surfaces (Vue, popup, render-html, mark.py, landing, favicon) | exit 1 on drift |
| `regenerate_skill_summaries.py` | Walk every `chika/skills/*/SKILL.md`, regenerate `data/skill_summaries/*.json` via the configured LLM provider | `--check` |
| `check_skill_tool_drift.py` | Flag SKILL.md tool mentions that don't exist in the live registry | exit 1 on drift |
| `scaffold.py {skill,tool,event,adr}` | Generate the full file set for a new artefact + a passing test stub | n/a (interactive) |
| `installers/asset_names.py` | Single source of truth for installer asset filenames; build scripts + update module both read from here | covered by `test_installer_structure.py` |

Each script is opinionated about its output format: header banner says "AUTO-GENERATED — DO NOT EDIT BY HAND", a date stamp normalised away in `--check` so day-of-the-week doesn't flap CI, atomic write so a Ctrl-C never leaves a half-written generated file.

**Why hand-roll instead of vendoring openapi-typescript-codegen / datamodel-code-generator**

- Our surface is small: ~16 event models, ~12 REST routes. A 200-line generator we own beats a 20 MB dep we don't.
- Codegen libraries' opinions don't match ours — they generate axios clients (we want fetch), pull in their own runtime helpers, and make it hard to drop ESLint rules cleanly.
- A custom generator can shape the output around our existing conventions (header banner, normalised date stamp, atomic write).

**Doctor integration (extending ADR-29)**

`chika/_cli/doctor.py` gained three new checks that invoke the relevant `--check` script:

- `check_event_types_in_sync` — calls `gen_event_types.py --check`
- `check_brand_parity` — calls `check_brand_parity.py`
- `check_skill_summaries_in_sync` — calls `regenerate_skill_summaries.py --check`

All three are `warn`-only (never `error`). Drift is a contributor concern; users on a stale checkout should still get exit code 0 from doctor. The detail field includes the exact remediation command.

**Extension active-state detection (related)**

A complementary contribution this round: `chika/_cli/extension_detect.py` identifies whether the browser extension is loaded via three signals (heartbeat, Chrome profile walk, local files), used by:

- `chika install-extension` — skip the "open chrome://extensions/" prompt when already loaded; render a refresh-only panel instead
- The Windows / macOS / Linux `post_install` and `pre_uninstall` hooks — write `extension_detection.txt` for the installer success page; surface a removal reminder when uninstalling
- `chika uninstall` (CLI) — surface the same removal reminder
- The backend `extension_status` callback writes a heartbeat to `~/.chika/extension_active.json` whenever the extension WS connects, so subsequent runs see "confirmed active"

**Test surface**

- `tests/test_codegen_scripts.py` (24 tests) — every generator's `--check` mode passes on committed files, the round-trip is deterministic, parsers handle markdown fences + leading prose, scaffolders produce passing test stubs, brand-parity extracts both SVG path strings + Python constant blocks, asset-name SOT agrees with `update.py::_expected_asset_name`.
- `tests/test_extension_detect.py` (50+ tests) — every detection signal in isolation, confidence-tier rollup (heartbeat ≻ chrome_profile ≻ filesystem ≻ unknown), heartbeat freshness boundaries (parametrised across ages 0 → 30 days), GUI installer hook contracts (Windows / macOS / Linux all reference `detect_extension` + write `extension_detection.txt` + emit `chrome://extensions/` reminder).

**Consequences**

- Adding a new event type drops from a 4-file edit to: bump `EventType` enum + maybe a Pydantic model, then `python scripts/gen_event_types.py`. CI catches drift if the regen step is skipped.
- Adding a new skill: `python scripts/scaffold.py skill <name>` produces the directory + SKILL.md template + passing test. Then edit + `python scripts/regenerate_skill_summaries.py --skill <name>`.
- Brand-mark geometry drift (the ADR-27 enforcement nightmare) becomes a 30 ms CI step instead of a code-review checklist item.
- *Cost*: ~700 lines of generator code to maintain. Mitigated by each generator being narrowly scoped and having `--check` mode (changes to a generator are caught by their own contract tests).
- *Future*: a `chika dev gauntlet` command that runs every generator's `--check` plus ruff + mypy + bandit + pytest in one shot, so contributors can verify CI-equivalent state before pushing.
