# Chika

![CI](https://github.com/your-username/chika/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

An agentic AI assistant with a **single tool surface** — the LLM doesn't call individual tools directly; it emits structured workflow JSON that the engine executes client-side. This keeps the model focused on intent and reasoning while a deterministic engine handles execution, grounding, and streaming.

```
User input → Engine → LLM streams tokens
                    ↓ (if workflow call detected)
              WorkflowEngine.execute()
                    ↓
              Tool dispatch (shell, file, web, git…)
                    ↓
              Result injected into history
                    ↓
              LLM produces final response
```

## Features

- **Multi-provider** — Anthropic (Claude), OpenAI, Azure OpenAI; switch via env var
- **Workflow engine** — 10 step types: `sequential`, `parallel`, `conditional`, `loop`, `map`, `fan_out`, `retry`, `pipeline`, `sub_workflow`, plus embedded single-step recovery
- **Grounding / anti-hallucination** — `$facts` ledger tracks every tool result; LLM sees source tags `(source: web_search:step_2)`; post-response validator flags unsupported claims
- **Extended thinking** — Anthropic extended thinking streamed as `{type: "thinking"}` events so the user can follow the reasoning
- **Prompt caching** — `cache_control: ephemeral` on the system prompt block (Anthropic); reduces latency and cost on long sessions
- **History compaction** — middle messages summarised via LLM when history exceeds token budget; tool-call/result pairs are never split
- **Multi-profile** — isolated workspaces, memory files, and optional password gates per profile
- **WebSocket streaming** — every event (`token`, `tool_call`, `tool_result`, `workflow_start`, `step_start`, `thinking`, `done`) streamed in real time
- **Approval gates** — sensitive tools (destructive shell ops, profile switches) pause and wait for user confirmation before running
- **Memory** — persistent per-profile Markdown file with TTL; auto-compacted when over budget

## Architecture

```
chika/
├── core/
│   ├── engine.py           # Main chat loop — prompt build → stream → workflow detect → synthesis
│   ├── workflow_engine.py  # Executes 10 step types; manages $facts ledger and fact tracking
│   ├── tool_registry.py    # Central tool registry with approval metadata
│   ├── skill_registry.py   # Bundles of related tools (git, web, spotify, verify, plan…)
│   ├── prompt_builder.py   # Assembles system prompt from core rules + variable context + memory
│   ├── compactor.py        # History compaction — preserves tool-call/result boundaries
│   ├── variable_store.py   # Runtime state: $profile.*, $facts, $plan, user vars with source tracking
│   ├── memory_manager.py   # Persistent per-profile memory with TTL
│   ├── profile_manager.py  # Profile isolation and password gates
│   └── device_store.py     # Maps device_id → session for multi-device WebSocket clients
├── tools/
│   ├── shell_tool.py       # shell_exec (asyncio subprocess + thread fallback for Windows)
│   ├── file_tools.py       # file_read/write/append/replace/search, dir_list
│   ├── web_fetch_tool.py   # web_search (DuckDuckGo), web_fetch with grounding validation
│   ├── memory_tool.py      # memory_persist / memory_recall / memory_forget
│   ├── variable_tools.py   # var_set / var_get / var_delete
│   ├── wait_tool.py        # wait_for_file, wait_for_event
│   ├── apps_tool.py        # app_open_tool, shell_open_app
│   └── live_server_tool.py # Managed local dev-server lifecycle
└── skills/
    ├── git_skill/          # clone, commit, push, branch, diff, status
    ├── web_skill/          # Advanced web interaction
    ├── verify_skill/       # verify_url (HEAD check), fact_check (against $facts)
    ├── plan_skill/         # plan_set / plan_get for multi-step decomposition
    ├── question_skill/     # ask_user — blocks on WebSocket approval dialog
    └── spotify_skill/      # OAuth Spotify integration

api/
├── server.py               # FastAPI + uvicorn; WebSocket /ws/ + REST endpoints
└── session_manager.py      # Singleton — creates/caches ChikaEngine per session_id

chika.py                    # CLI entry point — interactive REPL
config.py                   # All config via env vars; multi-provider factory
```

## Workflow JSON

The LLM emits a single JSON blob. The engine executes it and feeds the result back before producing a final response. Example:

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

## Grounding

Every tool result is tagged with its source before being stored in the `$facts` ledger:

```
[fact:web_search:step_1] FastAPI supports async WebSocket handlers natively.
[fact:file_read:step_2]  requirements.txt contains fastapi>=0.111.0
```

The system prompt instructs the LLM to only assert claims traceable to a `[fact:...]` entry. After each response, a lightweight validator checks factual claims against the ledger and emits a `validation_warning` event if any are unsupported.

## Setup

**Requirements:** Python 3.11+, Node 18+ (for the frontend)

```bash
# 1. Clone and install backend dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set CHIKA_PROVIDER and the matching API key
```

**.env options:**

```env
# Provider: anthropic | openai | azure
CHIKA_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Or OpenAI
# CHIKA_PROVIDER=openai
# OPENAI_API_KEY=sk-...

# Or Azure
# CHIKA_PROVIDER=azure
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_OPENAI_KEY=...
# AZURE_OPENAI_DEPLOYMENT=gpt-4o

# Engine tuning (all optional)
CHIKA_MAX_HISTORY_TOKENS=10000
CHIKA_MAX_WORKFLOW_STEPS=8
CHIKA_THINKING=true
CHIKA_VALIDATE_RESPONSE=true
CHIKA_API_KEY=             # leave empty to disable auth
```

**CLI (no frontend needed):**

```bash
python chika.py
```

**API server + frontend:**

```powershell
# Windows
./_run_backend.ps1
./_run_frontend.ps1
```

The server starts on `http://localhost:8000`. The Vue 3 frontend is served from `/`.

## API

The WebSocket endpoint is the primary interface.

**Connect:** `ws://localhost:8000/ws/?device_id=<uuid>`

**Send a message:**
```json
{ "type": "chat", "session_id": "sess_abc", "content": "List all Python files in this repo" }
```

**Event stream (server → client):**

| Event type | Description |
|---|---|
| `token` | Streamed LLM output token |
| `thinking` | Extended thinking token (Anthropic) |
| `workflow_start` | Workflow execution started |
| `step_start` | Individual step beginning |
| `tool_call` | Tool about to be invoked (name + args) |
| `tool_result` | Tool result (truncated for display) |
| `workflow_done` | Workflow complete with outcome summary |
| `approval_request` | Engine paused — awaiting user confirm/deny |
| `done` | Turn complete |
| `error` | Unrecoverable error |

**REST endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Server status |
| `GET` | `/sessions` | List sessions |
| `GET` | `/sessions/{id}/history` | Message history for a session |
| `DELETE` | `/sessions/{id}` | Clear session |
| `GET` | `/profiles` | List profiles |

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `CHIKA_PROVIDER` | `anthropic` | LLM provider: `anthropic`, `openai`, `azure` |
| `CHIKA_MAX_HISTORY_TOKENS` | `10000` | Token budget before history compaction triggers |
| `CHIKA_COMPACT_KEEP_FIRST` | `2` | Messages to preserve at history start during compaction |
| `CHIKA_COMPACT_KEEP_LAST` | `4` | Messages to preserve at history end during compaction |
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

## Tech Stack

- **Backend:** Python 3.11, FastAPI, Uvicorn, Pydantic v2, httpx
- **LLM:** Anthropic SDK, OpenAI SDK (covers Azure OpenAI)
- **Search:** DuckDuckGo (`ddgs`)
- **Frontend:** Vue 3, Pinia, Vite
- **Transport:** WebSocket (streaming), HTTP REST
