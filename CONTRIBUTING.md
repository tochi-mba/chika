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

## PR checklist

- [ ] Tests pass: `pytest tests/ -v`
- [ ] Linting clean: `ruff check .`
- [ ] No type regressions: `mypy chika/ api/ config.py --ignore-missing-imports`
- [ ] New tools return `{"error": ...}` on failure
- [ ] New tools registered in `session_manager.py`
- [ ] Sensitive data (API keys, tokens) not committed
