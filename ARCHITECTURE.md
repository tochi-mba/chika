# Chika — System Design

This document is the **authoritative high-level map** of how Chika is built. ADRs in [DECISIONS.md](DECISIONS.md) capture the *why* behind specific calls; this file captures the *what* and *how it fits together*.

If you only have ten minutes, read this. Then dip into ADRs that interest you.

---

## 1. What Chika is

A local-first agentic AI assistant with **four tightly-coupled surfaces**:

| Surface | Tech | Purpose |
|---|---|---|
| **CLI** (`chika`) | Python + rich + prompt_toolkit | Claude-Code-style REPL, all features available |
| **Frontend** | Vue 3 + Vite | Web UI with chat, settings, profile management |
| **Browser extension** | Chrome MV3 | Reads tabs, navigates, screenshots, monitors elements |
| **Backend API** | FastAPI + WebSocket | Engine + tool dispatch + WS broadcast to frontend/extension |

All four hit the **same `ChikaEngine`** — the orchestrator that streams LLM tokens, dispatches tool calls, runs the workflow engine, and emits events. That parity is non-negotiable; see [ADR-6](DECISIONS.md#adr-6).

---

## 2. The big picture

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  user's terminal │    │   web browser    │    │   chrome / edge  │
│   (chika REPL)   │    │   (Vue SPA)      │    │   (extension)    │
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         │ (in-process)          │ HTTP + WS             │ WS + chrome.runtime
         ▼                       ▼                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                       FastAPI server (api/)                      │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                     ChikaEngine (chika/core/)               │ │
│  │  ┌──────────┐  ┌──────────────┐  ┌──────────────────────┐   │ │
│  │  │ history  │→ │ LLM streamer │→ │ workflow engine      │   │ │
│  │  │ + facts  │  │ (anth/oa/az) │  │  - 10 step types     │   │ │
│  │  └──────────┘  └──────────────┘  │  - tool dispatch     │   │ │
│  │                                  │  - approval gates    │   │ │
│  │                                  │  - $facts ledger     │   │ │
│  │                                  └──────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Tools (chika/tools/, chika/skills/):                            │
│    shell · file · web_fetch · browser_* · python_run · git       │
│    skill_load · skill_query · plan_* · memory · profile · ...    │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
              ┌──────────────────────────────┐
              │     state on disk            │
              │  data/settings.json          │
              │  data/profiles.json          │
              │  data/chats/*.json           │
              │  data/memory/<profile>.md    │
              │  ~/.chika/extension/         │
              │  ~/.chika/data/  (installed) │
              │  ~/.chika/update_state.json  │
              └──────────────────────────────┘
```

Every event the engine emits (`token`, `tool_call`, `tool_result`, `workflow_start`, `thinking`, `done`, `pet_changed`, …) is broadcast over the WebSocket so all three UIs stay in lockstep.

---

## 3. Module map

### `chika/_cli/` — terminal UI

| Module | Responsibility |
|---|---|
| `app.py` | Entry point. Argv subcommands, REPL boot, auto-update thread, banner, profile picker |
| `commands.py` | Slash-command registry (`/help`, `/provider`, `/plan`, `/setup`, `/uninstall`, …) |
| `renderer.py` | Translates engine events into rich panels + the inline state row |
| `mark.py` | Brand-mark rasteriser for the terminal (half-block characters from the same SVG path used by the frontend) |
| `state_verbs.py` | Fire-and-forget LLM call producing context-aware verbs for the inline indicator |
| `pet_speech.py` | Optional pet-companion LLM quips |
| `update.py` | Install-kind detection + auto-update + GitHub release-asset resolution |
| `doctor.py` | Health checks (Python, deps, extension, .env, paths) |
| `setup.py` | Wraps `install.py`'s wizard for first-run + post-install |
| `uninstall.py` | Per-OS uninstall dispatch |
| `install_extension.py` | Copies the bundled extension to `~/.chika/extension/` and opens chrome://extensions |
| `interactive.py` | Approval handlers + question prompts (CLI parity with frontend modals) |

### `chika/core/` — engine

| Module | Responsibility |
|---|---|
| `engine.py` | `ChikaEngine` — streams tokens, dispatches tools, owns history + plan + facts |
| `workflow_engine.py` | 10 step types (`sequential`, `parallel`, `conditional`, `loop`, `map`, `fan_out`, `retry`, `pipeline`, `sub_workflow`) with single-step recovery |
| `compactor.py` | History compaction; never splits tool-call/result pairs |
| `memory_manager.py` | Per-profile markdown memory with TTL + auto-compaction |
| `workspace_policy.py` | Workspace-scope file-write gating |
| `logger.py` | `_SafeRotatingFileHandler` (Windows-aware: swallows PermissionError on rotation) |

### `chika/tools/` — runtime tools

Each is registered with `@register_tool` and exposed to the LLM via JSON schema. Categories:

- **shell** — `shell_exec`, `bg_shell_exec`, `shell_kill`, `python_run`
- **file** — `file_write`, `file_append`, `file_edit_lines`, `file_replace`
- **browser** — `browser_navigate`, `browser_click`, `browser_fill_input`, `browser_screenshot`, `browser_get_dom`, `browser_watch_element`, …
- **web** — `web_fetch`, `web_search`, `verify_url`, `web_head`
- **memory** — `memory_persist`, `memory_forget`, `memory_append`
- **profile** — `profile_create`, `profile_switch`, `set_profile_password`
- **git** — `git_commit`, `git_push`, `git_pr_create`, `git_pr_merge`, `git_checkout`, `git_branch`
- **plan** — `plan_set`, `plan_add`, `plan_update`, `plan_remove`, `plan_get`, `plan_edit`

Tool **permissions** sit on top: each tool resolves to a category, and each category has an `ask`/`skip` policy that the user controls via `/permissions` or the Settings modal.

### `chika/skills/` — skill packages (drop-in contract)

Each skill is a folder under `chika/skills/<name>_skill/` whose
`__init__.py` exports a fixed contract. Discovery walks the folder
at session-build time so dropping a skill folder is enough — no
edits required to the engine, server, CLI, settings store, or
frontend. See [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-new-skill--drop-in-contract)
for the full contract.

**Discovery layer** (`chika/skills/__init__.py`):

| Function | Responsibility |
|---|---|
| `iter_skill_modules()` | Walk every `<name>_skill/` folder that exports `SKILL_NAME` + `build_skill`. |
| `iter_skill_routers()` | Yield every skill's optional FastAPI router (`register_routes()`) — server.py mounts them. |
| `iter_skill_websocket_registrars()` | Yield every skill's `register_websocket(app)` for `@app.websocket(...)` endpoints. |
| `iter_skill_cli()` | Yield slash + argv subcommand dispatch tables for the CLI. |
| `iter_skill_ui_manifests()` | Yield `SKILL_UI` manifests for the dynamic Settings tab + extension popup section. |
| `iter_skill_intent_cases(dim)` | Walk per-skill `INTENT_CASES[dim]` for the planning-intent / ask-user / approval / etc. heuristics. |
| `fire_setting_changed`, `fire_env_changed`, `fire_session_linked` | Subscriber bus — settings_store / env router / WS endpoint fan changes out to every skill that opted in. |
| `render_intent_examples_block(dim)` | Sample positive/negative cases per dimension into the system prompt with per-skill + global thresholds. |

**Per-skill modules** (also opt-in):

| Module | Responsibility |
|---|---|
| `chika/skills/summarizer.py` | LLM-generated digests of each `SKILL.md`, hash-keyed, committed to `data/skill_summaries/`, injected into the agent's system prompt on every turn (non-blocking parallel generation at engine init) |
| `chika/skills/browser_skill/selectors.py` | Selector cascade: CSS → ARIA → text-content. Cached per `(url, original_spec)` — markup churn doesn't break sessions |
| `chika/skills/browser_skill/idempotency.py` | `(tab_id, action, args_sha) → result` cache with 30s TTL. Mid-flight WS reconnects don't re-fire destructive ops |
| `chika/skills/browser_skill/websocket.py` | The `/ws/extension/` endpoint — extension command/control protocol. Migrated out of `api/server.py` into the skill folder so the skill is genuinely self-contained. |
| `chika/skills/spotify_skill/routes.py` + `cli.py` + `ui/` | Spotify's full HTTP / CLI / Vue surface — drops in via the contract above. |

### `api/` — FastAPI server

| Route | Purpose |
|---|---|
| `POST /api/chat` | Start a chat turn (streamed via WS) |
| `GET/POST /api/settings` | Settings store (autonomy, permissions, pet, auto-update, …) |
| `GET/POST /api/env` | `.env` editor (secrets masked unless explicitly revealed) |
| `GET/POST /api/provider` | Active provider + model |
| `GET/POST /api/profiles` | Multi-profile management |
| `GET/POST /api/pets` | Pet companion catalogue + per-profile selection |
| `WS /ws` | Event stream (tokens, tool calls, plan updates, pet animations) |

Plus, since [ADR-31](DECISIONS.md#adr-31), [ADR-34](DECISIONS.md#adr-34), [ADR-35](DECISIONS.md#adr-35):

| Module | Responsibility |
|---|---|
| `api/models.py::EventType` + `validate_event` | Single source of truth for the 35+ engine event types. Strict-mode validation in tests catches drift; lax-at-runtime keeps the WS edge flowing |
| `api/event_routing.py` | Declarative `CLI_EVENTS` / `FRONTEND_EVENTS` / `EXTENSION_EVENTS` + `EXTENSION_DROPS_ON_PURPOSE`. The contract test fails CI if any event type is unrouted |
| `api/audit_log.py` | Append-only NDJSON at `data/audit.jsonl`. Records every approval decision, permission change, timed-grant expiry, tool-run outcome. 10 MB rotation |
| `api/event_log.py` | Per-session NDJSON at `data/sessions/<id>.jsonl`. Every WS event captured for offline replay. 5 MB rotation per session |
| `chika/_cli/replay.py` | `chika replay <session_id> [--surface cli\|raw\|count]` — dispatches recorded events to any surface. Foundation for cross-surface debug + demo |

Per-connection asyncio `Lock` serialises WS sends ([ADR-5](DECISIONS.md#adr-5)).

### `frontend/` — Vue SPA

Built with Vite. Components:

- `App.vue` — chat layout, branding, message stream
- `ChikaMark.vue` — canonical brand mark (SVG, animated states)
- `SettingsModal.vue` — autonomy / permissions / provider / pet / auto-update / state-verbs
- `PlanPanel.vue` — verbose hierarchical plan with accept/edit/reject
- `ToolEventRow.vue` — per-tool result formatting (uses `lib/toolSummaries.js`)

### `extension/` — Chrome MV3

- `manifest.json` (MV3, host permissions: `<all_urls>`)
- `background.js` (service worker — bridges browser APIs to the WebSocket)
- `content/bridge.js` (page-context bridge)
- `popup/` (toolbar popup with brand-mark + last-event preview)
- `options/` (server URL, connection test)

### `installers/` — native install pipelines

```
installers/
├── windows/
│   ├── chika.iss              ← Inno Setup script
│   ├── build_installer.ps1    ← orchestrates wheel + ISCC
│   ├── post_install.ps1       ← creates venv + pip installs wheel
│   ├── pre_uninstall.ps1      ← strips PATH, preserves user data
│   └── chika.cmd              ← on-PATH launcher (sets CHIKA_DATA_DIR)
├── macos/
│   ├── build_pkg.sh           ← pkgbuild + productbuild
│   ├── scripts/preinstall     ← clears prior venv
│   ├── scripts/postinstall    ← creates venv, pip installs, /usr/local/bin symlink
│   ├── chika                  ← launcher shim
│   └── uninstall.sh           ← user-runnable uninstaller
└── linux/
    ├── debian/control         ← .deb metadata
    ├── debian/postinst        ← creates venv, pip installs
    ├── debian/prerm           ← venv cleanup
    ├── chika                  ← launcher shim
    ├── build_deb.sh           ← uses dpkg-deb
    └── install.sh             ← universal curl|bash for any glibc
```

Each writes an `install_marker.json` so [`chika update`](chika/_cli/update.py) knows the right asset to download from GitHub Releases.

---

## 4. Install / update / uninstall flow

The matrix every install kind supports:

| Install kind | Detection | First install | Auto-update | Uninstall |
|---|---|---|---|---|
| `git_clone` | `.git/` at repo root | `python install.py` | `git pull --ff-only` + `pip install -e . --upgrade` (only when on main, clean tree, CI green) | `chika uninstall` → `pip uninstall chika` |
| `pip_pypi` | `importlib.metadata.version("chika")` | `pip install chika` | `pip install --upgrade chika` (CI-gated via PyPI publish) | `pip uninstall chika` |
| `windows_installer` | `install_marker.json` next to venv | Run `chika-setup-X.Y.Z.exe` | Download next .exe, run silently with `/SILENT /SUPPRESSMSGBOXES` | Add/Remove Programs, or `chika uninstall --yes` |
| `macos_installer` | `install_marker.json` at `/Library/Application Support/Chika/` | Run `Chika-X.Y.Z.pkg` | Download next .pkg, run `installer -pkg` | `sudo /Library/.../uninstall.sh`, or `chika uninstall --yes` |
| `linux_deb` | `dpkg -s chika` | `sudo dpkg -i chika_X.Y.Z_all.deb` | (future: apt repo) | `sudo apt remove chika`, or `chika uninstall --yes` |
| `linux_universal` | `install_marker.json` at `~/.local/share/chika/` | `curl install.sh \| bash` | Re-run `install.sh` | `~/.local/share/chika/uninstall.sh` |

**User data** (`~/.chika/`) is **always preserved** across uninstalls. `chika uninstall --remove-data` opts in to wiping it.

**Auto-update guards** (all must hold for silent apply):

- `auto_update == "on"` (default)
- newer version exists upstream
- upstream CI is green (every check-run `status=completed` AND `conclusion ∈ {success, skipped, neutral}`)
- on `main`/`master` (not feature branch)
- working tree clean
- this version hasn't already been auto-applied
- network reachable, GitHub not rate-limiting

Network checks throttled to once per hour via `~/.chika/update_state.json`.

---

## 5. Data flow — a single chat turn

```
user types → CLI prompt
    ↓
[CHAT] api/chat → ChikaEngine.chat(text)
    ↓
LLM streams response
    ├─ thinking tokens → renderer.thinking_panel
    ├─ assistant tokens → renderer.token_buffer + WS broadcast
    └─ workflow JSON detected
            ↓
        WorkflowEngine.execute(spec)
            ├─ approval gate? → handler (CLI prompt OR frontend modal)
            ├─ permission check (per-tool category)
            └─ tool dispatch → result → $facts ledger
            ↓
        emit tool_call, tool_result events → WS
    ↓
final answer streams → grounding validator post-checks claims
    ↓
emit done → CLI/frontend/extension all settle
    ↓
maybe auto-continue (if reply ends with "next, I'll …" and auto_continue=on)
```

Every event is mirrored to all three UIs through the WebSocket. The CLI runs the engine in-process; the frontend + extension see the same events over the wire.

---

## 6. Settings, profiles, and state

Three persistence layers:

### Settings (`data/settings.json` or `~/.chika/data/settings.json`)

Runtime knobs:

```json
{
  "autonomy": "supervised | autonomous",
  "tool_permissions": { "shell": "ask", "browser_write": "skip", ... },
  "pet_speech": "on | off",
  "pet_speech_tokens": 40,
  "auto_continue": "on | off",
  "auto_continue_max": 10,
  "state_verbs": "on | off",
  "state_verbs_tokens": 80,
  "auto_update": "on | off"
}
```

Surfaced identically in CLI (`/settings`, `/autonomy`, `/permissions`, `/pet`, `/auto-continue`, `/state`, `/auto-update`) and frontend (Settings modal). Validators in `api/settings_store.py` reject bad values from either entry point.

### Profiles (`data/profiles.json`)

Each profile owns:

- `name`, `workspace` (a directory path)
- `pet_id` (which pet companion to render)
- optional password hash (frontend gates reveal)

Switching profile rotates `engine._active_profile` + workspace policy + pet renderer.

### Memory (`data/memory/<profile>.md`)

Per-profile markdown file. The agent writes via `memory_persist` / `memory_append`; the engine pulls a condensed view into the system prompt every turn. Auto-compacted when over a token budget.

### `~/.chika/` (preserved across uninstalls)

| Path | Owner | Purpose |
|---|---|---|
| `~/.chika/extension/` | `chika install-extension` | Bundled extension source for "Load unpacked" |
| `~/.chika/data/` | Native installers (via `CHIKA_DATA_DIR`) | Settings + profiles + chat history |
| `~/.chika/update_state.json` | `chika update` background thread | Throttle timestamp, last-applied-SHA |

---

## 7. Branding parity

The chika trefoil renders on **four surfaces** with no shared rendering model. Geometry is **duplicated by hand** ([ADR-27](DECISIONS.md#adr-27)):

| Surface | File | Tech |
|---|---|---|
| Frontend SVG (canonical) | `frontend/src/components/ChikaMark.vue` | Vue 3, animated states |
| Extension popup | `extension/popup/popup.html` + `popup.css` | Inline SVG, vanilla CSS |
| Manifest PNGs | `extension/icons/_render.html` + `_render.mjs` | Playwright screenshot pipeline |
| CLI banner + state row | `chika/_cli/mark.py` | Python rasteriser → half-block characters |
| GitHub Pages landing | `docs/index.html` + `docs/style.css` | Inline SVG, CSS keyframes |

When the geometry changes, **all five** must change together. The "Brand mark" section of [CONTRIBUTING.md](CONTRIBUTING.md) lists the parity checklist.

---

## 8. Open source — governance and contribution

- **License:** MIT
- **Where work happens:** [github.com/tochi-mba/chika](https://github.com/tochi-mba/chika)
- **Issues:** bug reports + feature requests welcome
- **PRs:** see [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow (style, tests, baselines, commit format)
- **Decisions:** [DECISIONS.md](DECISIONS.md) — every architectural call is an ADR. Open a PR proposing a new ADR before doing big refactors.
- **CI gauntlet:**
  - `ruff check .`
  - `mypy chika/ api/ config.py`
  - `bandit -r chika/ api/ -ll -x tests/`
  - `pytest --cov=chika --cov=api --cov-fail-under=75`
  - `npm run test:e2e` (frontend + extension Playwright suites)

PRs that don't pass the gauntlet locally are unlikely to pass it in CI. See the "CI-equivalent local check" section in [CONTRIBUTING.md](CONTRIBUTING.md) for the exact command sequence.

---

## 9. Test pyramid

```
                 ┌────────────────────────────────────┐
                 │  visual snapshots (Playwright)     │  ← cross-platform
                 │  ~150 tests · CI-only baselines    │     (Linux only)
                 └────────────────────────────────────┘
              ┌──────────────────────────────────────────┐
              │  e2e: stub-LLM CLI, frontend Playwright,│  ← every surface
              │  extension Playwright (~80 tests)       │
              └──────────────────────────────────────────┘
        ┌──────────────────────────────────────────────────┐
        │  integration: workflow engine + tools end-to-end │  ← grouped
        │  with mocked subprocess + http (~300 tests)     │
        └──────────────────────────────────────────────────┘
   ┌────────────────────────────────────────────────────────┐
   │  unit: every module's public API + edge cases          │  ← bulk
   │  (~1500 tests)                                         │
   └────────────────────────────────────────────────────────┘
```

**Live-LLM tests** (`@pytest.mark.live_llm`) are gated behind `--live-llm` / `CHIKA_RUN_LIVE_LLM=1`. CI never flips either; they run only when a human explicitly asks. See [tests/conftest.py](tests/conftest.py).

---

## 10. Where to look when something breaks

| Symptom | Where to look |
|---|---|
| `chika` command not found | `chika doctor` — checks PATH + console-script registration |
| Extension won't load | `chika install-extension` re-deploys; check `~/.chika/extension/manifest.json` |
| Auto-update silent | `~/.chika/update_state.json` records last check + reason; `/update --check` shows live status |
| LLM responses slow | History compaction may be running mid-turn; check `chika/core/compactor.py` logs |
| WS disconnects | Per-connection lock could be held by a long broadcast; see [ADR-5](DECISIONS.md#adr-5) |
| Settings wiped after install | `CHIKA_DATA_DIR` not exported; check `chika.cmd` (Windows) or shim script |
| Permission prompts every tool | `/autonomy autonomous` skips by default; or set per-category via `/permissions` |
| Plan tasks stuck "in_progress" | Auto-continue capped at `auto_continue_max` (default 10); `/auto-continue max 20` raises it |

---

## 11. Roadmap-relevant ADRs

The most consequential design calls, in roughly the order someone reading the code would want them:

- [ADR-1](DECISIONS.md#adr-1) — workflow JSON spec executed deterministically by the engine
- [ADR-2](DECISIONS.md#adr-2) — `$facts` ledger as ground truth, post-response validator
- [ADR-6](DECISIONS.md#adr-6) — CLI parity with frontend (every WS event renders identically)
- [ADR-7](DECISIONS.md#adr-7) — `.env` and provider config edited through one atomic surface
- [ADR-19](DECISIONS.md#adr-19) — verbose hierarchical patch-editable plans across every surface
- [ADR-23](DECISIONS.md#adr-23) — plan-required gate for multi-step write workflows
- [ADR-25](DECISIONS.md#adr-25) — layered test pyramid; live-LLM gated
- [ADR-27](DECISIONS.md#adr-27) — one brand mark, four surfaces, geometry duplicated by hand
- [ADR-28](DECISIONS.md#adr-28) — inline state indicator with LLM-generated context-aware verbs
- [ADR-29](DECISIONS.md#adr-29) — auto-update gated on upstream CI
- [ADR-30](DECISIONS.md#adr-30) — native installers + landing page + uninstall parity
- [ADR-31](DECISIONS.md#adr-31) — event contract: Pydantic-validated, surface-routed, drift-detected
- [ADR-32](DECISIONS.md#adr-32) — skill summary injection (pre-generated, hash-keyed, non-blocking)
- [ADR-33](DECISIONS.md#adr-33) — browser tool resilience: selector cascade + idempotency
- [ADR-34](DECISIONS.md#adr-34) — permission audit log (NDJSON at `data/audit.jsonl`)
- [ADR-35](DECISIONS.md#adr-35) — session event log + `chika replay` (the differentiator artifact)
- [ADR-36](DECISIONS.md#adr-36) — pyramid health enforcement + landing-page snapshot coverage

---

## 12. Quick links

- [README.md](README.md) — for users (download, quick start, features)
- [DECISIONS.md](DECISIONS.md) — every ADR
- [CONTRIBUTING.md](CONTRIBUTING.md) — for contributors (dev setup, style, commit format)
- [installers/README.md](installers/README.md) — installer build pipeline
- [docs/](docs/) — landing page sources (deployed to github.io)
