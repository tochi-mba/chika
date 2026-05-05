"""Shared pytest fixtures + marker gating for the chika test suite.

Markers
-------
``@pytest.mark.live_llm``
    Test calls a real upstream LLM (Anthropic / Azure / OpenAI) and burns
    real tokens. Off by default — gated behind ``--live-llm`` on the
    command line OR ``CHIKA_RUN_LIVE_LLM=1`` in the environment. CI never
    flips either, so these only run when a human explicitly asks.

``@pytest.mark.slow``
    Test takes longer than ~5s (subprocess spawn, npm install, etc.).
    Always runs locally; CI also runs them. Listed for discoverability.

``@pytest.mark.cli_e2e``
    Spawns the real ``python chika.py`` process and drives it via stdin.
    Runs in CI but uses a stub LLM (see ``tests/_helpers/stub_llm.py``).

``@pytest.mark.frontend_e2e`` / ``@pytest.mark.extension_e2e``
    Playwright suites under ``frontend/e2e/`` and ``extension/e2e/``.
    Skipped at the pytest layer — the real runner is ``npm run e2e`` in
    each project. Markers exist so we can list them in ``pytest --markers``.

Gate logic
----------
We register a ``--live-llm`` flag. When NOT supplied, every test marked
``live_llm`` is auto-skipped with a helpful reason. Tests that need a
real key still check ``os.environ`` themselves and skip if missing — the
flag is necessary but not sufficient.
"""
from __future__ import annotations

import os

import pytest


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--live-llm",
        action="store_true",
        default=False,
        help=(
            "Run tests marked @pytest.mark.live_llm — these call real LLMs "
            "and cost real money. Default: skipped. Equivalent to "
            "CHIKA_RUN_LIVE_LLM=1."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_llm: test calls a real upstream LLM — only runs with --live-llm",
    )
    config.addinivalue_line("markers", "slow: test takes more than ~5 seconds")
    config.addinivalue_line(
        "markers", "cli_e2e: spawns python chika.py and drives via stdin",
    )
    config.addinivalue_line(
        "markers", "frontend_e2e: Playwright frontend suite (run via npm run e2e)",
    )
    config.addinivalue_line(
        "markers", "extension_e2e: Playwright extension suite (run via npm run e2e)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-skip live-LLM tests unless explicitly enabled."""
    live_enabled = (
        config.getoption("--live-llm")
        or os.environ.get("CHIKA_RUN_LIVE_LLM") == "1"
    )
    if live_enabled:
        return
    skip_marker = pytest.mark.skip(
        reason=(
            "live LLM test — pass --live-llm or set CHIKA_RUN_LIVE_LLM=1 "
            "to run (costs real tokens)"
        ),
    )
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(autouse=True)
def _reset_workspace_policy_module_globals():
    """Reset the workspace-policy globals on ``chika.tools.file_tools``
    after every test. Otherwise a WS-pipeline test that wires a policy
    leaks it to later tests, causing seemingly-unrelated file_tools
    tests to deny writes to /tmp.

    The policy is per-session in production; tests are also per-session,
    so wiping it on the way out matches real behaviour.
    """
    yield
    try:
        from chika.tools import file_tools as _ft
        # Use the public configurator so the underlying context-vars
        # are reset rather than relying on attribute writes (the module
        # exposes contextvar-backed shims under those names).
        _ft.configure_workspace_policy(None, None)
    except Exception:
        pass
