# Contributing to Chika

## Dev setup

```bash
# Clone and install (editable, with dev deps)
git clone <repo>
cd chika_v2
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Copy and configure environment
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY or OPENAI_API_KEY
```

## Running tests

```bash
pytest tests/ -v
```

For coverage report:

```bash
pytest tests/ --cov=chika --cov=api --cov-report=term-missing
```

## Code style

```bash
ruff check .         # lint
ruff check . --fix   # auto-fix
mypy chika/ api/ config.py --ignore-missing-imports
```

Pre-commit runs these automatically on every `git commit`.

## Adding a new tool

1. Create `chika/tools/your_tool.py`.
2. Define an `async` handler and wrap it in a `ToolDefinition`:

```python
from chika.core.tool_registry import ToolDefinition

async def your_handler(param: str) -> dict:
    return {"result": param}

YOUR_TOOL = ToolDefinition(
    name="your_tool",
    description="One-line description the LLM reads to decide when to use this tool.",
    parameters={
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "What param does"},
        },
        "required": ["param"],
    },
    handler=your_handler,
)
```

3. Register it in `api/session_manager.py` alongside the other tools.
4. Add tests in `tests/test_your_tool.py`.

All tool handlers must return `{"error": "<message>"}` on failure — never raise.

## Adding a new skill

Skills are collections of pre-built tool handlers that the LLM can call by name.

1. Create `chika/skills/your_skill/__init__.py`.
2. Export a `SkillDefinition` with `name`, `description`, `tools` (list of `ToolDefinition`), and an optional `system_prompt_fragment`.
3. Register in `api/session_manager.py` via `skill_registry.register(YOUR_SKILL)`.

## Commit format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

[optional body]
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`.

Examples:
- `fix(file_tools): prevent path traversal via .. segments`
- `feat(workflow): add retry step type with backoff`
- `test(variable_store): add concurrency + circular-ref tests`

## Brand mark (the chika trefoil)

Chika's mark is a stroke-only 3-leaf trefoil that renders on **four
surfaces** with incompatible rendering models. There's no shared
runtime that spans them all (Vue ≠ vanilla popup HTML ≠ Chrome MV3
PNG ≠ terminal grid), so the same geometry lives in 4 places. See
ADR-27 for the full rationale.

**Canonical source of truth:** `frontend/src/components/ChikaMark.vue`.

When you change the geometry (petal path, angles, hub radius, stroke
width), update **all four** of these in one PR:

| File | What it owns |
|------|--------------|
| `frontend/src/components/ChikaMark.vue` | The Vue component. Used by the SPA nav. |
| `extension/popup/popup.html` + `popup.css` | Inline SVG in the popup header. Vanilla CSS, same animation keyframes. |
| `extension/icons/_render.html` | The page Playwright screenshots to produce manifest PNGs. |
| `chika/_cli/mark.py` | Python rasteriser — samples the same cubic bezier into half-block characters. |

After editing all four, regenerate the manifest PNGs:

```bash
cd extension
node icons/_render.mjs
```

This writes `icon16/32/48/128.png` from the SVG. Re-run after every
geometry change so the toolbar icons stay in sync.

Spot-check the CLI rasterisation:

```bash
PYTHONIOENCODING=utf-8 python -m chika._cli.mark
```

Should print a recognisable 3-leaf trefoil in half-block characters.

If you change the **animation states** (idle / thinking / streaming /
success / intro), update both `ChikaMark.vue` and `popup.css` — they
share the same `@keyframes` definitions. The CLI doesn't carry per-leaf
animations (terminal grid resolution is too coarse); it uses the inline
state-row indicator instead (see ADR-28).

## Install / update / doctor CLI

Three argv subcommands sit in front of the REPL — they exit before
booting the engine, so they work even on a half-broken install:

| Command                  | Purpose                                                     |
|--------------------------|-------------------------------------------------------------|
| `chika install-extension`| Copy the bundled extension to `~/.chika/extension/` and open `chrome://extensions/`. Re-run after every release. |
| `chika update`           | `git pull --ff-only` + `pip install -e . --upgrade --no-deps` for clone installs; `pip install --upgrade chika` for pip installs. |
| `chika update --check`   | Peek without applying. Prints `available`, `up_to_date`, or the failure reason (`offline`, `rate_limited`, `ci_red`, `not_on_main`, `working_tree_dirty`, …). |
| `chika doctor`           | Verify the install (Python ≥3.11, every required import, extension intact, frontend built, `.env` present, `data/` writable, console script on PATH). Exit code 1 on `error`, 0 on `ok`/`warn`. |

The same actions are slash commands inside the REPL: `/install-extension`, `/update`, `/update --check`, `/doctor`, `/auto-update [on|off]`.

**Auto-update on startup.** When `auto_update == "on"` (the default — see `data/settings.json`), `_run_rich` spawns a daemon thread that runs `chika._cli.update.auto_update_on_startup`. It hits the GitHub API once per hour (throttled via `~/.chika/update_state.json`), and only auto-applies when **all** these are true:

- The user is on `main` or `master` (not a feature branch — `git pull --ff-only` would pull the wrong ref).
- The working tree is clean (no `git status --porcelain` output).
- A newer commit exists on upstream main.
- Every check-run on that commit has `status=completed` AND `conclusion ∈ {success, skipped, neutral}`.
- We haven't already auto-applied this SHA (state file).

Any failure → notice only, no apply. The full rationale is ADR-29.

**When you add a new runtime dep**, update both `pyproject.toml` *and* `requirements.txt` and add the import to `chika._cli.doctor.REQUIRED_IMPORTS`. The `test_install_chika.py::test_requirements_txt_mirrors_pyproject_runtime` test will fail otherwise. Same goes for adding a top-level runtime file in `extension/` — list it in `chika._cli.install_extension._RUNTIME_TOP_LEVEL_FILES` (or its dir in `_RUNTIME_DIRS`), or `chika install-extension` will ship a broken extension.

## Visual snapshot baselines (Playwright)

Visual baselines under `frontend/e2e/*-snapshots/` and
`extension/e2e/*-snapshots/` are pixel-compared in CI. Chromium renders
fonts + antialiasing slightly differently on Linux vs macOS vs Windows,
so the canonical baselines are the **Linux ones** (CI runs on
`ubuntu-latest`). See ADR-26.

Workflow when you change UI that has a visual baseline:

1. Make your UI change locally; run the suite to see what fails.
   ```bash
   cd frontend
   BASE_URL=http://localhost:5173 npx playwright test
   ```
2. Push your branch and open a PR.
3. CI fails the visual snapshot tests with diff images uploaded as
   `frontend-playwright-report` artifacts — eyeball them to confirm the
   diff is intentional.
4. Add the **`update-snapshots`** label to the PR.
   `.github/workflows/update-snapshots.yml` runs on `ubuntu-latest`,
   regenerates every `-chromium-linux.png` baseline, and commits the
   updates back onto your PR branch.
5. The label auto-removes when done. CI re-runs and goes green.

Manual variant: trigger `update-snapshots.yml` from the Actions tab
(`workflow_dispatch`).

**Don't commit `-chromium-win32.png` or `-chromium-darwin.png`
baselines as if they were ground truth** — CI ignores them. If you see
them in a diff and didn't intend to push them, drop them. They're only
useful as a local design-review preview.

## CI-equivalent local check

Before opening a PR, run the same gauntlet CI does:

```bash
# Lint
python -m ruff check .

# Types
python -m mypy chika/ api/ config.py --ignore-missing-imports

# Python tests + coverage gate
python -m pytest tests/ -q --ignore=tests/test_cli_e2e.py \
  --cov=chika --cov=api --cov-fail-under=60

# Frontend Playwright (against the dev server for speed)
cd frontend
BASE_URL=http://localhost:5173 npx playwright test
```

If your `chromium-linux.png` baselines don't exist locally, the visual
tests will fail — that's expected. Use the workflow above to generate
them in CI.

## PR checklist

- [ ] Tests pass: `pytest tests/ -v`
- [ ] Linting clean: `ruff check .`
- [ ] No type regressions: `mypy chika/ api/ config.py --ignore-missing-imports`
- [ ] Coverage above the 60% gate (`--cov-fail-under=60`)
- [ ] If UI changed: visual snapshot baselines regenerated via the
  `update-snapshots` PR label (don't push Win32 / Darwin baselines)
- [ ] New tools return `{"error": ...}` on failure
- [ ] New tools registered in `session_manager.py`
- [ ] Sensitive data (API keys, tokens) not committed
