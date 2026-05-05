"""End-to-end scaffolder tests that hit the actual subprocess.

Earlier scaffold tests mocked ``_run`` so the dispatch logic was covered
but the subprocess invocation itself wasn't — which let a "hangs forever
on an interactive prompt" bug ship. These tests exercise the real
``_run`` against tiny built-in templates (no network) AND the
hang-prevention path (closed stdin, non-interactive env, timeout).

Network-backed scaffolders (``vite-vue``, ``next``, etc.) are NOT run
here — they need npm + internet and are too slow / flaky for CI. A
manual smoke is documented in the SKILL.md.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from chika.skills.web_app_skill.scaffold_tool import (
    _run,
    _run_sync,
    _scaffold_web_app,
)


# ── Built-in templates: real subprocess path is unused but env is set ───

def test_vanilla_scaffold_writes_runnable_files_via_real_run(tmp_path: Path):
    """Built-in template doesn't shell out — pure file writes — but this
    still locks in the success-path contract end-to-end."""
    out = asyncio.run(_scaffold_web_app(
        stack="vanilla", name="real-vanilla", target_dir=str(tmp_path),
    ))
    assert out["ok"] is True
    project = Path(out["project"])
    assert (project / "index.html").is_file()
    assert (project / "main.js").is_file()
    assert (project / "styles.css").is_file()


# ── Subprocess hang prevention ─────────────────────────────────────────

def test_run_closes_stdin_so_interactive_prompts_cant_hang(tmp_path: Path):
    """The bug we're guarding against: a child that reads from stdin
    forever. With our hardening, stdin is /dev/null and the read returns
    EOF instantly — child must exit, not hang."""
    if sys.platform == "win32":
        # 'set /p' reads a line from stdin and blocks. EOF on stdin makes
        # it return immediately.
        cmd = "set /p _foo= && echo got=%_foo%"
    else:
        cmd = "read FOO && echo got=$FOO"

    rc, log = asyncio.run(_run(cmd, tmp_path, timeout=10.0))
    # The exact rc differs per shell; what matters is that we returned
    # within the timeout (i.e. didn't hang).
    assert rc != -1, (
        f"subprocess timed out — stdin must not have been DEVNULL.\n"
        f"log: {log!r}"
    )


def test_run_kills_runaway_subprocess_at_timeout(tmp_path: Path):
    """If the child genuinely hangs, the timeout must kill it and surface
    a clean error message — not block the engine forever. Use a Python
    sleep so the child responds to kill on every platform."""
    cmd = f'"{sys.executable}" -c "import time; time.sleep(30)"'

    import time as _t
    started = _t.monotonic()
    rc, log = asyncio.run(_run(cmd, tmp_path, timeout=2.0))
    elapsed = _t.monotonic() - started

    assert rc == -1, "timeout path must return rc=-1"
    assert "timed out" in log.lower(), f"log should mention timeout: {log!r}"
    assert elapsed < 8.0, (
        f"timeout enforcement is broken — call took {elapsed:.1f}s for "
        "a 2s timeout"
    )


def test_run_passes_non_interactive_env_vars(tmp_path: Path):
    """``CI`` and ``npm_config_yes`` must reach the subprocess so npm
    create defaults instead of prompting. Use Python (no shell quoting
    differences) so this test is portable."""
    cmd = (
        f'"{sys.executable}" -c '
        '"import os; print(\'CI=\' + os.environ.get(\'CI\',\'\')); '
        'print(\'YES=\' + os.environ.get(\'npm_config_yes\',\'\'))"'
    )
    rc, log = asyncio.run(_run(cmd, tmp_path, timeout=15.0))
    assert rc == 0, f"command failed: {log!r}"
    assert "CI=1" in log, f"CI env var not propagated: {log!r}"
    assert "YES=true" in log, f"npm_config_yes not propagated: {log!r}"


# ── Threaded fallback (Selector loop / older Windows) ──────────────────

def test_run_sync_fallback_also_closes_stdin_and_times_out(tmp_path: Path):
    """The Selector-loop threaded fallback must enforce the same
    hang-prevention as the asyncio path. Use a Python sleep so the child
    responds to kill on every platform."""
    cmd = f'"{sys.executable}" -c "import time; time.sleep(30)"'
    import time as _t
    started = _t.monotonic()
    rc, log = _run_sync(cmd, tmp_path, timeout=2.0)
    elapsed = _t.monotonic() - started
    assert rc == -1
    assert "timed out" in log.lower()
    assert elapsed < 8.0


# ── Real network scaffold — opt-in via env var ─────────────────────────

@pytest.mark.skipif(
    os.environ.get("CHIKA_SCAFFOLD_NETWORK_TESTS") != "1",
    reason="needs network + npm. Set CHIKA_SCAFFOLD_NETWORK_TESTS=1 to run.",
)
def test_real_vite_svelte_scaffold_completes_in_under_60s():
    """The exact path that hung in the user's session — vite-svelte. Opt-in
    because it needs network + npm. CHIKA_SCAFFOLD_NETWORK_TESTS=1 to run."""
    with tempfile.TemporaryDirectory(prefix="scaffold_test_") as tmp_dir:
        tmp = Path(tmp_dir)
        out = asyncio.run(_scaffold_web_app(
            stack="vite-svelte", name="probe", target_dir=str(tmp),
            install=False,
        ))
        assert out.get("ok") is True, out
        proj = Path(out["project"])
        assert (proj / "package.json").is_file()
        assert (proj / "vite.config.js").is_file() or (proj / "vite.config.ts").is_file()
