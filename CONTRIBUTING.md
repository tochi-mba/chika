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
