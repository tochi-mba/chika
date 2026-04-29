# Chika

![CI](https://github.com/tochi-mba/chika/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

An agentic AI assistant with **full browser control** — reads your open tabs, navigates pages, extracts data, takes screenshots, and answers questions about anything you can see in Chrome. Powered by Claude, GPT-4o, or Azure OpenAI.

---

## Quick Start

**Requires Python 3.11+**

```bash
git clone https://github.com/tochi-mba/chika
cd chika
python install.py
```

The installer will:
- Install all dependencies
- Walk you through choosing a provider (Anthropic / OpenAI / Azure)
- Securely prompt for your API key
- Create your `.env`
- Start the server

Then open **http://localhost:8000**

---

## Chrome Extension

The extension gives Chika hands in your browser — it can read tabs, navigate, screenshot, click, and monitor changes.

**Load it once, works forever:**

| Step | Action |
|---|---|
| 1 | Open Chrome and go to **`chrome://extensions`** |
| 2 | Enable **Developer mode** (toggle, top-right corner) |
| 3 | Click **Load unpacked** |
| 4 | Select the **`extension/`** folder inside the cloned repo |
| 5 | Click the Chika icon in your toolbar → **Options** |
| 6 | Server URL: **`http://localhost:8000`** (pre-filled) |
| 7 | Click **Test connection** — should show ✓ Connected |

> **Edge:** Same steps at `edge://extensions`
>
> **Firefox:** `about:debugging` → This Firefox → Load Temporary Add-on → select `extension/manifest.json`

Once connected, Chika can see everything in your browser. Try:

```
"What's the latest post on this page?"
"Open YouTube history and tell me what I watched last"
"Search Hacker News for posts about Rust and summarise the top 3"
"Compare the pricing on these two tabs"
```

---

## Features

- **Browser control** — read DOM, extract text, navigate, screenshot, wait for elements, run JavaScript
- **Multi-provider** — Anthropic (Claude), OpenAI, Azure OpenAI; switch via env var
- **Workflow engine** — 10 step types: `sequential`, `parallel`, `conditional`, `loop`, `map`, `fan_out`, `retry`, `pipeline`, `sub_workflow`, plus single-step recovery
- **Grounding / anti-hallucination** — `$facts` ledger tracks every tool result; LLM sees source tags; post-response validator flags unsupported claims
- **Extended thinking** — Anthropic extended thinking streamed in real time so you can follow the reasoning
- **Prompt caching** — `cache_control: ephemeral` on the system prompt (Anthropic); reduces latency and cost
- **History compaction** — older messages summarised by the LLM when history exceeds token budget; tool-call/result pairs are never split
- **Multi-profile** — isolated workspaces, memory files, and optional password gates per user
- **WebSocket streaming** — every event (`token`, `tool_call`, `tool_result`, `workflow_start`, `thinking`, `done`) streamed in real time
- **Approval gates** — destructive operations pause and wait for user confirmation before running
- **Persistent memory** — per-profile Markdown memory with TTL, auto-compacted when over budget

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
├── core/
│   ├── engine.py           # Main chat loop — prompt build → stream → workflow detect → synthesis
│   ├── workflow_engine.py  # Executes 10 step types; manages $facts ledger
│   ├── tool_registry.py    # Central tool registry with approval metadata
│   ├── skill_registry.py   # Bundles of related tools (browser, git, web, spotify…)
│   ├── prompt_builder.py   # Assembles system prompt from rules + variable context + memory
│   ├── compactor.py        # History compaction — preserves tool-call/result boundaries
│   ├── variable_store.py   # Runtime state: $profile.*, $facts, $plan, user vars
│   ├── memory_manager.py   # Persistent per-profile memory with TTL
│   ├── profile_manager.py  # Profile isolation and password gates
│   └── device_store.py     # Maps device_id → session for multi-device WebSocket clients
├── tools/
│   ├── shell_tool.py       # shell_exec (asyncio subprocess + thread fallback for Windows)
│   ├── file_tools.py       # file_read/write/append/replace/search, dir_list
│   ├── web_fetch_tool.py   # web_search (DuckDuckGo), web_fetch with grounding
│   ├── memory_tool.py      # memory_persist / memory_recall / memory_forget
│   ├── variable_tools.py   # var_set / var_get / var_delete
│   ├── wait_tool.py        # wait_for_file, wait_for_event
│   ├── apps_tool.py        # app_open_tool, shell_open_app
│   └── live_server_tool.py # Managed local dev-server lifecycle
└── skills/
    ├── browser_skill/      # 14 browser tools — navigate, DOM, screenshot, JS eval…
    ├── git_skill/          # clone, commit, push, branch, diff, status
    ├── web_skill/          # Advanced web interaction
    ├── verify_skill/       # verify_url, fact_check (against $facts)
    ├── plan_skill/         # plan_set / plan_get for multi-step decomposition
    ├── question_skill/     # ask_user — blocks on WebSocket approval dialog
    └── spotify_skill/      # OAuth Spotify integration

api/
├── server.py               # FastAPI + Uvicorn; WebSocket /ws/ + REST endpoints
└── session_manager.py      # Singleton — creates/caches ChikaEngine per session

extension/                  # Chrome extension (Manifest V3)
├── background.js           # Service worker — WebSocket bridge to Chika server
├── content/bridge.js       # Content script — DOM access and page variable extraction
├── popup/                  # Chat UI popup
└── options/                # Settings page (server URL, API key, blocked domains)

chika.py                    # CLI entry point — interactive REPL
config.py                   # All config via env vars; multi-provider factory
```

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

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Server status + provider info |
| `GET` | `/sessions` | List active sessions |
| `GET` | `/sessions/{id}/history` | Message history |
| `DELETE` | `/sessions/{id}` | Clear session |
| `GET` | `/profiles` | List profiles |

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `CHIKA_PROVIDER` | `anthropic` | LLM provider: `anthropic`, `openai`, `azure` |
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

---

## Tech Stack

- **Backend:** Python 3.11, FastAPI, Uvicorn, Pydantic v2, httpx
- **LLM:** Anthropic SDK, OpenAI SDK (covers Azure OpenAI)
- **Search:** DuckDuckGo (`ddgs`)
- **Frontend:** Vue 3, Pinia, Vite
- **Extension:** Chrome Manifest V3, WebSocket
- **Transport:** WebSocket (streaming), HTTP REST

---

## License

[MIT](LICENSE) — © 2026 Tochi Mba
