# Chika

![CI](https://github.com/tochi-mba/chika/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

An agentic AI assistant with **full browser control** — reads your open tabs, navigates pages, extracts data, takes screenshots, and answers questions about anything you can see in Chrome. Powered by Claude, GPT-4o, Azure OpenAI, or **Ollama (local/free)**.

> **System design:** see [ARCHITECTURE.md](ARCHITECTURE.md) for the full open-source plan — components, data flow, install/update/uninstall flows, governance.

---

## Install

Download the installer for your OS at **[tochi-mba.github.io/chika](https://tochi-mba.github.io/chika)** — the page auto-detects your platform.

| Platform | Installer | Uninstall via |
|---|---|---|
| **Windows** | [`chika-setup-X.Y.Z.exe`](https://github.com/tochi-mba/chika/releases/latest) | Settings → Apps → Installed apps → Chika → Uninstall |
| **macOS**   | [`Chika-X.Y.Z.pkg`](https://github.com/tochi-mba/chika/releases/latest) | `sudo /Library/Application\ Support/Chika/uninstall.sh` |
| **Linux (Debian/Ubuntu)** | [`chika_X.Y.Z_all.deb`](https://github.com/tochi-mba/chika/releases/latest) | `sudo apt remove chika` |
| **Linux (any distro)** | `curl -fsSL https://raw.githubusercontent.com/tochi-mba/chika/main/installers/linux/install.sh \| bash` | `~/.local/share/chika/uninstall.sh` |

Each installer puts `chika` on your PATH globally, registers in your OS app manager, and ships a real uninstaller. Per-user installs — no admin/sudo required.

After install, run `chika` from any terminal. First launch will nudge you to run `chika setup` to pick a provider and save your API key. **Settings can be changed anytime** — `/settings`, `/provider`, `/env`, or the web Settings modal.

> **Contributors:** if you want to develop chika, clone + install.py instead — see [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
git clone https://github.com/tochi-mba/chika
cd chika
python install.py
```

---

## Chrome Extension

The extension gives Chika hands in your browser — it can read tabs, navigate, screenshot, click, and monitor changes.

**One-command install:**

```bash
chika install-extension
```

That copies the bundled extension to `~/.chika/extension/` and opens `chrome://extensions/` for you. From there:

1. Toggle **Developer mode** (top-right)
2. Click **Load unpacked**
3. Select the folder it printed (`~/.chika/extension/`)

Re-run `chika install-extension` any time after an update to refresh your installed copy.

> **Edge:** same flow at `edge://extensions`
>
> **Firefox:** `about:debugging` → This Firefox → Load Temporary Add-on → select `~/.chika/extension/manifest.json`

---

## Update

Chika **auto-updates on launch** when upstream CI is green. You don't need to do anything. Manually:

```bash
chika update          # apply now
chika update --check  # peek; don't apply
chika doctor          # verify the install (Python, deps, extension, .env, …)
chika replay <id>     # replay a recorded session offline (debug + demo)
```

Inside the REPL: `/update`, `/update --check`, `/auto-update on|off`, `/doctor`.

The auto-update path varies by install kind:

| Install kind | Auto-update behaviour |
|---|---|
| Native installers (Windows .exe / macOS .pkg / Linux .deb / curl install.sh) | Downloads next installer from GitHub Releases, runs silently |
| `git clone + python install.py` | `git pull --ff-only` + editable refresh — only on `main`/`master`, clean tree, CI green |
| `pip install chika` | `pip install --upgrade chika` |

**Auto-update will NOT run** if you're on a feature branch, your working tree is dirty, upstream CI is red/in-progress, or the network is unreachable — fail-safe by design. Throttled to once an hour; state at `~/.chika/update_state.json`.

Disable the auto-update behaviour:

```bash
chika  # then: /auto-update off
```

---

## Uninstall

Two ways. Use whichever feels normal for your OS.

**Via your OS app manager** (the standard way):

- **Windows:** Settings → Apps → Installed apps → Chika → Uninstall
- **macOS:** `sudo /Library/Application\ Support/Chika/uninstall.sh`
- **Linux (.deb):** `sudo apt remove chika`
- **Linux (curl install):** `~/.local/share/chika/uninstall.sh`

**Via the CLI**:

```bash
chika uninstall              # show the right command for your install
chika uninstall --yes        # actually run it
chika uninstall --remove-data
                             # also wipe ~/.chika/  (settings, profiles, chats)
```

User data at `~/.chika/` is **always preserved by default**. A reinstall picks up where you left off — same settings, same profiles, same chat history. Pass `--remove-data` for a clean wipe.

Once connected, Chika can see everything in your browser. Try:

```
"What's the latest post on this page?"
"Open YouTube history and tell me what I watched last"
"Search Hacker News for posts about Rust and summarise the top 3"
"Compare the pricing on these two tabs"
```

---

## Features

- **Claude Code-style CLI** — `chika` opens an interactive REPL with bordered tool blocks, streaming Markdown output, an extended-thinking panel, slash-command autocomplete (`/help`, `/provider`, `/env`, `/autonomy`, `/pet`, …), and a pet companion in the corner
- **Browser control** — read DOM, extract text, navigate, screenshot, wait for elements, run JavaScript
- **Multi-provider** — Anthropic (Claude), OpenAI, Azure OpenAI, or Ollama (local/free); switch via env var, slash command (`/provider`), or the frontend Settings modal
- **Workflow engine** — 10 step types: `sequential`, `parallel`, `conditional`, `loop`, `map`, `fan_out`, `retry`, `pipeline`, `sub_workflow`, plus single-step recovery
- **Skill docs (`SKILL.md`)** — each skill folder ships a deep reference the agent pulls on demand via `skill_load` (or queries focused chunks via `skill_query`, BM25-ranked, zero-dep). The runtime **gates skill tools behind their SKILL.md**: first-time use refuses the tool, hands the doc back to the agent, and re-plans on the next turn — wrong-stack-id and wrong-kwarg crashes become self-correcting nudges. Docs are auto-deduped against the system prompt; a tool-reference appendix is generated from the live registry so a doc that lies about the tool surface fails CI.
- **Plan checklist** — verbose hierarchical plans with `goal`, `requirements`, and nested `subtasks` (auto-rolling status). Six tools: `plan_set` / `plan_add` / `plan_update` / `plan_remove` / `plan_get` / **`plan_edit(operations=[...])`** (structured patches with substring "fingerprint" replaces, sub-task add/remove, etc.). Rendered with **Accept / Edit / Reject** affordance in all three UIs — frontend `PlanPanel.vue`, CLI `/plan` slash command, extension popup strip. Workflows that do real work without ticking a box trigger a runtime nudge with the in-progress task's id appended to the next-turn tool result.
- **Auto-continue** — agent ends with "Next, I'll …" / "Now I'll …" and the engine fires another turn automatically (capped at `auto_continue_max`, default 5). Multi-step plans run end-to-end without user nudges.
- **Web-app scaffolding** — `scaffold_web_app(stack, name)` creates working starters for any browser stack: built-in instant templates (`vanilla`, `static-site`) plus 30+ npm-create stacks (Vite-Vue/React/Svelte/Solid/Preact/Lit/Qwik, Next, Nuxt, Astro, SvelteKit, Remix, Three.js, p5, Phaser…). Stack-id aliases handle common LLM slips (`vite-three → three`).
- **Desktop apps** — `python_run` AST-scans imports, auto-installs missing modules (with fallback chain — `pygame → pygame-ce` on Python 3.14), spawns Python with `CREATE_NEW_CONSOLE` on Windows so GUI windows actually surface, and waits a 2-second grace before reporting status so import errors land in the first tool result.
- **Grounding / anti-hallucination** — `$facts` ledger tracks every tool result; LLM sees source tags; post-response validator flags unsupported claims
- **Extended thinking** — Anthropic extended thinking streamed in real time so you can follow the reasoning
- **Prompt caching** — `cache_control: ephemeral` on the system prompt (Anthropic); reduces latency and cost
- **History compaction** — older messages summarised by the LLM when history exceeds token budget; tool-call/result pairs are never split
- **Multi-profile** — isolated workspaces, memory files, optional password gates per user — and **each profile picks its own pet**
- **Pet companion** — animated ASCII pets in the CLI, a floating widget in the frontend, and an emoji peek in the browser-extension popup. Per-profile selection persists across sessions; opt-in LLM-generated speech bubbles run in parallel with the engine so they never slow your reply
- **WebSocket streaming** — every event (`token`, `tool_call`, `tool_result`, `workflow_start`, `thinking`, `done`, `pet_changed`) streamed in real time
- **Approval gates** — destructive operations pause and wait for user confirmation before running
- **Persistent memory** — per-profile Markdown memory with TTL, auto-compacted when over budget
- **In-app settings editor** — view and edit `.env` (secrets masked), switch providers/models, tune permissions, and pick a pet — all from the frontend Settings modal **and** the CLI. Both surfaces hit the same `/api/env`, `/api/provider`, `/api/settings`, `/api/pets` endpoints

---

## How It Works

```
User input → Engine → LLM streams tokens
                    ↓ (workflow call detected)
              WorkflowEngine.execute()
                    ↓
              Tool dispatch (browser, shell, file, web, git…)
                    ↓
              Result stored in $facts ledger
                    ↓
              LLM produces grounded final response
```

The LLM never calls tools directly. It emits a single structured **workflow JSON** blob. The engine executes it deterministically and feeds results back. This keeps the model focused on reasoning while the engine handles retries, parallelism, and grounding.

---

## Architecture

```
chika/
├── _cli/                   # The CLI surface (Claude Code-inspired)
│   ├── app.py              # REPL loop, Rich Console + prompt_toolkit
│   ├── renderer.py         # Translates engine events → tool blocks, panels
│   ├── commands.py         # Slash-command dispatcher (/help, /provider, /env, /pet…)
│   ├── env_file.py         # Atomic .env read/write; masks secrets
│   ├── pets.py             # ASCII pet definitions + state frames
│   ├── pet_speech.py       # Optional LLM-driven pet quips (parallel, fire-and-forget)
│   └── fallback.py         # Plain-text fallback when rich/prompt_toolkit missing
├── core/
│   ├── engine.py           # Main chat loop — prompt build → stream → workflow detect → synthesis
│   ├── workflow_engine.py  # Executes 10 step types; manages $facts ledger
│   ├── tool_registry.py    # Central tool registry with approval metadata
│   ├── skill_registry.py   # Bundles of related tools (browser, git, web, spotify…)
│   ├── prompt_builder.py   # Assembles system prompt from rules + variable context + memory
│   ├── compactor.py        # History compaction — preserves tool-call/result boundaries
│   ├── variable_store.py   # Runtime state: $profile.*, $facts, $plan, user vars
│   ├── memory_manager.py   # Persistent per-profile memory with TTL
│   ├── profile_manager.py  # Profile isolation, password gates, per-profile pet selection
│   └── device_store.py     # Maps device_id → session for multi-device WebSocket clients
├── tools/
│   ├── shell_tool.py       # shell_exec (asyncio subprocess + thread fallback for Windows)
│   ├── file_tools.py       # file_read/write/append/replace/search, dir_list
│   ├── web_fetch_tool.py   # web_search (DuckDuckGo), web_fetch with grounding
│   ├── memory_tool.py      # memory_persist / memory_recall / memory_forget
│   ├── variable_tools.py   # var_set / var_get / var_delete
│   ├── wait_tool.py        # wait_for_file, wait_for_event
│   ├── apps_tool.py        # app_open_tool, shell_open_app
│   ├── live_server_tool.py # Managed local dev-server lifecycle
│   ├── python_run_tool.py  # `python_run` — desktop apps; auto-installs deps; CREATE_NEW_CONSOLE on Windows
│   ├── skill_doc_tool.py   # `skill_load` (full SKILL.md) + `skill_query` (BM25 chunks)
│   └── skill_query_index.py # BM25 chunking + ranking + cache for SKILL.md
└── skills/
    ├── browser_skill/      # 18 browser tools — navigate, DOM, screenshot, JS eval, watches…
    ├── git_skill/          # 10 tools — status, diff, log, commit, push, PR create/merge
    ├── web_skill/          # web_search (DuckDuckGo)
    ├── web_app_skill/      # `scaffold_web_app` — vanilla / vite-* / next / nuxt / astro / sveltekit / three / p5 / phaser…
    ├── verify_skill/       # web_fetch / verify_url / fact_check against $facts
    ├── plan_skill/         # plan_set / plan_add / plan_update / plan_remove / plan_get / plan_edit
    ├── question_skill/     # ask_user — blocks on WebSocket approval dialog
    ├── spotify_skill/      # 55 Spotify tools — search, catalog, playback, playlists, library
    └── */SKILL.md          # Per-skill canonical reference; agent loads via skill_load,
                            # queries chunks via skill_query, gated on first use

api/
├── server.py               # FastAPI app + both WebSocket handlers (WS stays here)
├── auth.py                 # require_auth FastAPI dependency
├── broadcast.py            # Frontend socket registry + push_to_all_frontend_sessions
├── session_manager.py      # Singleton — creates/caches ChikaEngine per session
├── settings_store.py       # Runtime settings persisted to data/settings.json
└── routes/
    ├── health.py           # GET /health
    ├── extension.py        # GET /api/extension/status
    ├── profiles.py         # GET /api/profiles
    ├── sessions.py         # GET/DELETE/POST /api/session/*
    ├── registry.py         # GET /api/tools, /api/skills, /api/workflows
    ├── config.py           # GET /api/config
    ├── env.py              # GET/PATCH /api/env, /api/provider — used by CLI + frontend
    ├── pets.py             # GET /api/pets, GET/PATCH /api/profile/{name}/pet
    ├── settings.py         # GET/PATCH /api/settings
    ├── spotify.py          # GET /auth/spotify/*
    ├── chat_history.py     # GET/DELETE /api/profile/*/chats/*
    ├── docs.py             # GET /readme
    └── static.py           # StaticFiles mount (frontend/dist/)

extension/                  # Chrome extension (Manifest V3)
├── background.js           # Service worker — WebSocket bridge to Chika server
├── content/bridge.js       # Content script — DOM access and page variable extraction
├── popup/                  # Chat UI popup (with pet companion that mirrors profile choice)
└── options/                # Settings page (server URL, API key, blocked domains)

chika.py                    # CLI entry point — re-exports chika._cli.cli
config.py                   # All config via env vars; multi-provider factory
```

---

## CLI quick reference

```bash
chika                      # interactive Claude Code-style REPL
python chika.py            # same thing, no install needed
```

Slash commands (tab-complete on `/`):

| Command                                       | What it does                                     |
|-----------------------------------------------|--------------------------------------------------|
| `/help`                                       | List every command                               |
| `/status`                                     | Provider, model, profile, message + variable counts |
| `/provider [name]`                            | Show or switch LLM provider (writes to `.env`)   |
| `/model [id]`                                 | Show or set the model for the active provider    |
| `/env [KEY[=VALUE]] [--unset KEY]`            | View / edit `.env` keys; secrets masked          |
| `/autonomy supervised\|autonomous`            | Global approval preset                           |
| `/permissions <category> ask\|skip`           | Per-category override                            |
| `/profile [name]`                             | Show or switch profile                           |
| `/pet [list \| <id> \| none]`                 | Pick the active profile's pet                    |
| `/pet speech on\|off [tokens N]`              | Toggle LLM-generated pet quips + token budget    |
| `/plan` / `/plan accept` / `/plan reject` / `/plan edit <feedback>` | Inspect or signal accept/edit/reject of the active plan. The slash command prints a copy-paste message you can send to nudge the agent. |
| `/auto-continue [on\|off \| max <n>]`         | Toggle auto-fire on "Next, I'll …" promises (default on, cap 10) |
| `/tools`, `/skills`, `/vars`, `/memory`       | Inspect runtime registries                       |
| `/thinking on\|off`                           | Toggle the extended-thinking panel               |
| `/clear`, `/reset`, `/quit`                   | Screen / session control                         |

---

## Workflow JSON

The LLM emits a single JSON blob. The engine executes it and feeds results back. Example:

```json
{
  "type": "sequential",
  "id": "summarise_repo",
  "steps": [
    {
      "tool": "shell_exec",
      "id": "list_files",
      "params": { "command": "find . -name '*.py' | head -30" },
      "result_variable": "$py_files"
    },
    {
      "tool": "llm_summarise",
      "id": "summary",
      "params": { "input": "$py_files", "instruction": "Describe the project structure" }
    }
  ]
}
```

Parallel execution:

```json
{
  "type": "parallel",
  "id": "gather_context",
  "steps": [
    { "tool": "web_search", "params": { "query": "FastAPI best practices 2025" }, "result_variable": "$web" },
    { "tool": "file_read",  "params": { "path": "README.md" }, "result_variable": "$readme" }
  ]
}
```

---

## Testing

Chika ships with a layered test pyramid covering every surface — backend,
CLI, frontend, and Chrome extension. The default suite never burns LLM
tokens; live-LLM tests are gated behind an explicit flag.

### Backend (Python) — fast, deterministic

```bash
pytest -v
pytest --cov=chika --cov=api --cov-report=term-missing
```

860+ tests covering every tool, skill, workflow type, and engine path.
Highlights:

- `tests/test_e2e_engine_stub.py` — full agentic-loop e2e with a scripted
  stub LLM (auto-continue, plan gate, plan nudge, workflow JSON recovery,
  cancellation). See `tests/_helpers/stub_llm.py`.
- `tests/test_e2e_cli.py` — spawns `python chika.py` as a real subprocess,
  pipes user input via stdin, strips ANSI from the output, asserts on the
  rendered CLI. Uses `CHIKA_STUB_LLM_SCRIPT` to script the LLM.
- `tests/test_ws_e2e.py` — full WebSocket pipeline through FastAPI's
  `TestClient`.
- `tests/test_integration.py` — engine + workflow + skill registry with a
  mocked LLM.

### Frontend (Vue + Pinia)

```bash
cd frontend
npm install
npm run test:unit            # Vitest — stores + components, jsdom
npm run test:e2e:install     # one-time Playwright browser install
npm run test:e2e             # Playwright — full app, mocked WS
```

The Playwright suite stubs `window.WebSocket` so tests drive any sequence
of engine events deterministically. See `frontend/e2e/_fixtures.js` for
the WS mock + helpers (`pushEvent`, `pushSequence`, `sentMessages`).

Visual-regression baselines live under `frontend/e2e/visual.spec.js-snapshots/`.
Update with:

```bash
npm run test:e2e -- --update-snapshots visual.spec.js
```

### Chrome extension

```bash
cd extension
npm install
npm run test:e2e:install
npm run test:e2e
```

The extension fixture (`extension/e2e/_fixtures.js`) launches a
`chromium.launchPersistentContext` with `--load-extension=...`, reads the
extension's id from the registered service worker, and exposes the
popup URL. Background SW + popup + visual snapshots are covered.

### Live-LLM smoke pack

`tests/test_live_llm_smoke.py` calls a real upstream provider — costs real
tokens. It is **off by default**. Opt in:

```bash
pytest tests/test_live_llm_smoke.py --live-llm
# or
CHIKA_RUN_LIVE_LLM=1 pytest tests/test_live_llm_smoke.py
```

Use it before a release to confirm the prompt + tool wiring still works
against the model you're about to ship with. CI runs it only on
`workflow_dispatch` (see `.github/workflows/live-llm.yml`).

### Mocking the LLM

Three options depending on test layer:

```python
# 1. In-process: monkey-patch _stream_llm directly.
from tests._helpers.stub_llm import StubLLM, install
install(engine, StubLLM([
    StubLLM.text("Hello!"),
    StubLLM.workflow({"type": "sequential", "steps": [...]}),
    StubLLM.text("All done."),
]))

# 2. Subprocess (CLI): write a JSON script and set CHIKA_STUB_LLM_SCRIPT.
from tests._helpers.cli_harness import run_cli, script, text_turn
res = run_cli(inputs=["hello"], script=script([text_turn("hi back")]))
assert "hi back" in res.plain

# 3. Frontend / extension: see the WebSocket mock in e2e/_fixtures.js.
```

**Pytest markers** (`@pytest.mark.…`):
- `live_llm` — calls a real LLM. Auto-skipped without `--live-llm`.
- `slow` — > 5s; CLI subprocess tests are tagged.
- `cli_e2e` — spawns chika.py via subprocess.
- `frontend_e2e`, `extension_e2e` — Playwright suites (run via `npm run test:e2e`).

---

## Development

```bash
# Backend — auto-reload on file changes
uvicorn api.server:app --reload --port 8000

# Frontend — Vite dev server with HMR
cd frontend && npm install && npm run dev

# CLI — no server needed
python chika.py
# or after pip install -e .
chika
```

Enable structured log output to the terminal:

```bash
CHIKA_LOG_CONSOLE=1 uvicorn api.server:app --port 8000
```

**CI checks (run before committing):**

```bash
ruff check .
bandit -r chika/ api/ -ll -x tests/
pytest --cov=chika --cov=api --cov-fail-under=75 -q
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `chika: command not found` | Run `pip install -e .` from the project root |
| Server won't start | Check `.env` for typos; all int vars are safe-parsed and will log warnings |
| Extension not connecting | Make sure `CHIKA_API_KEY` matches exactly in both `.env` and the extension Options page |
| LLM errors / empty responses | Verify provider API keys in `.env`; check `chika.log` for structured error detail |
| `asyncio.NotImplementedError` on Windows | Already handled — server forces `WindowsProactorEventLoopPolicy` at startup |

---

## Manual Setup

If you prefer to configure things yourself instead of running `install.py`:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create config
cp .env.example .env
# Edit .env — set CHIKA_PROVIDER and your API key

# 3. Start the server
python api/server.py
# Open http://localhost:8000

# 4. Or use the CLI (no browser needed)
python chika.py
```

---

## API

The WebSocket endpoint is the primary interface.

**Connect:** `ws://localhost:8000/ws/?device_id=<uuid>`

**Send a message:**
```json
{ "type": "chat", "session_id": "sess_abc", "content": "List all Python files in this repo" }
```

**Event stream (server → client):**

| Event | Description |
|---|---|
| `token` | Streamed LLM output token |
| `thinking` | Extended thinking token (Anthropic) |
| `workflow_start` | Workflow execution started |
| `step_start` | Individual step beginning |
| `tool_call` | Tool about to be invoked (name + args) |
| `tool_result` | Tool result (truncated for display) |
| `workflow_done` | Workflow complete |
| `approval_request` | Engine paused — awaiting user confirm/deny |
| `done` | Turn complete |
| `error` | Unrecoverable error |

**REST endpoints:**

| Method  | Path                                  | Description                                              |
|---------|---------------------------------------|----------------------------------------------------------|
| `GET`   | `/health`                             | Server status + provider info                            |
| `GET`   | `/api/sessions`                       | List active sessions                                     |
| `GET`   | `/api/session/{id}/history`           | Message history                                          |
| `DELETE`| `/api/session/{id}`                   | Clear session                                            |
| `GET`   | `/api/profiles`                       | List profiles                                            |
| `GET`   | `/api/tools` / `/api/skills`          | Registered tools and skills                              |
| `GET`/`PATCH` | `/api/settings`                  | Runtime settings (autonomy, permissions, pet speech)     |
| `GET`/`PATCH` | `/api/env`                       | View/edit `.env` keys (secrets masked unless `?show_secrets=1`) |
| `GET`/`PATCH` | `/api/provider`                  | Switch LLM provider/model (writes to `.env`)             |
| `GET`   | `/api/pets`                           | Pet catalogue (id, emoji, accent, description)           |
| `GET`/`PATCH` | `/api/profile/{name}/pet`        | Read or change a profile's pet                           |

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `CHIKA_PROVIDER` | `anthropic` | LLM provider: `anthropic`, `openai`, `azure`, `ollama` |
| `OLLAMA_MODEL` | `llama3.1` | Model name for Ollama (e.g. `qwen2.5`, `deepseek-r1`) |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama API endpoint |
| `CHIKA_MAX_HISTORY_TOKENS` | `10000` | Token budget before history compaction triggers |
| `CHIKA_COMPACT_KEEP_FIRST` | `2` | Messages preserved at history start during compaction |
| `CHIKA_COMPACT_KEEP_LAST` | `4` | Messages preserved at history end during compaction |
| `CHIKA_MAX_TOOL_TURNS` | `20` | Max tool-call cycles per turn before hard stop |
| `CHIKA_MAX_WORKFLOW_STEPS` | `8` | Max steps per workflow execution |
| `CHIKA_MAX_MEMORY_TOKENS` | `2000` | Max tokens from memory injected into system prompt |
| `CHIKA_THINKING` | `true` | Enable Anthropic extended thinking |
| `CHIKA_THINKING_BUDGET` | `4000` | Token budget for extended thinking |
| `CHIKA_VALIDATE_RESPONSE` | `true` | Run post-response grounding validator |
| `CHIKA_GROUNDING_MIN_LENGTH` | `160` | Minimum response length (chars) to validate |
| `CHIKA_HOST` | `0.0.0.0` | API server bind address |
| `CHIKA_PORT` | `8000` | API server port |
| `CHIKA_API_KEY` | _(empty)_ | Optional bearer token for API auth |
| `CHIKA_AUTONOMY` | `supervised` | Default autonomy mode: `supervised` (ask before tools) or `autonomous` (skip all approvals) |
| `CHIKA_LOG_CONSOLE` | _(empty)_ | Set to `1` to echo structured logs to stdout in addition to `chika.log` |

Pet companion settings live in `data/settings.json` (managed via `/api/settings` and `/pet speech` in the CLI):

| Setting | Default | Description |
|---|---|---|
| `pet_speech` | `off` | Run a parallel LLM call after each turn to generate a pet quip |
| `pet_speech_tokens` | `40` | Max output tokens per quip (`8`–`200`) |

Per-profile pet selection is stored in `data/profiles/<name>/profile.json` under the `pet_id` key.

---

## Tech Stack

- **Backend:** Python 3.11, FastAPI, Uvicorn, Pydantic v2, httpx
- **LLM:** Anthropic SDK, OpenAI SDK (covers Azure OpenAI and Ollama)
- **Search:** DuckDuckGo (`ddgs`)
- **Frontend:** Vue 3, Pinia, Vite
- **Extension:** Chrome Manifest V3, WebSocket
- **Transport:** WebSocket (streaming), HTTP REST

---

## License

[MIT](LICENSE) — © 2026 Tochi Mba
