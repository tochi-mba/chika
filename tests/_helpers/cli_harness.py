"""Subprocess harness for end-to-end CLI tests.

Spawns ``python chika.py`` with a stub-LLM script (``CHIKA_STUB_LLM_SCRIPT``),
pipes the user input via stdin, captures stdout/stderr, strips ANSI escape
codes, and returns the result.

Why a stub provider — the engine spins up a real client at construction
time. The CLI starts before any test code can monkey-patch the engine.
The stub provider hooks ``_stream_llm`` / ``_llm_complete`` at the
engine layer (see ``ChikaEngine.__init__``), so the subprocess never
needs an API key.

The harness is intentionally simple: each scenario is "send these lines,
read until the process exits, assert on the cleaned output". For more
interactive flows (prompts mid-turn) we'd need pexpect, but every
chika REPL turn ends with the prompt redrawing — stdin EOF is enough.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# ANSI escape sequence stripper. Matches CSI (\x1b[...) and OSC (\x1b]...\x07)
# variants. Good enough for rich's output.
_ANSI_RE = re.compile(
    r"""
        \x1b\[[0-?]*[ -/]*[@-~]      # CSI sequences  (e.g. \x1b[31m)
        | \x1b\][^\x07]*\x07         # OSC sequences  (e.g. terminal title)
        | \x1b[@-Z\\-_]              # 2-byte escape sequences
    """,
    re.VERBOSE,
)


def strip_ansi(text: str) -> str:
    """Remove ANSI colour / cursor / OSC sequences from rich's output."""
    return _ANSI_RE.sub("", text)


@dataclass
class CliResult:
    returncode: int
    stdout: str            # raw, with ANSI
    stderr: str
    plain: str             # stdout with ANSI stripped

    def line_starts_with(self, prefix: str) -> bool:
        return any(ln.lstrip().startswith(prefix) for ln in self.plain.splitlines())

    def contains(self, needle: str) -> bool:
        return needle in self.plain


def run_cli(
    inputs: list[str],
    *,
    script: dict | None = None,
    script_path: str | None = None,
    timeout: float = 30.0,
    extra_env: dict[str, str] | None = None,
) -> CliResult:
    """Spawn ``python chika.py``, feed ``inputs`` via stdin, return the result.

    Either ``script`` (a dict — auto-written to a tempfile) or
    ``script_path`` (an existing file) must be provided. The path is
    handed to the child via ``CHIKA_STUB_LLM_SCRIPT``.

    Each entry in ``inputs`` is sent as one line (newline appended). The
    last line is always ``/quit`` so the REPL exits cleanly.
    """
    if script is None and script_path is None:
        raise ValueError("Pass either script= or script_path=")

    cleanup_path: Path | None = None
    if script is not None:
        # Write the script to a tmpfile that survives long enough for the
        # child to read it. Caller's tmp_path fixture would be cleaner but
        # we want this helper to be usable outside pytest too.
        import tempfile
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        )
        json.dump(script, fh)
        fh.flush()
        fh.close()
        script_path = fh.name
        cleanup_path = Path(fh.name)

    env = os.environ.copy()
    env["CHIKA_STUB_LLM_SCRIPT"] = script_path or ""
    # Force a known provider so config.get_provider_config() doesn't blow up
    # on missing keys — the stub short-circuits before any real call.
    env.setdefault("CHIKA_PROVIDER", "anthropic")
    env.setdefault("ANTHROPIC_API_KEY", "test-stub-key")
    # Pet speech off — we don't want a parallel LLM call from the CLI.
    env["CHIKA_PET_SPEECH"] = "off"
    # Redirect the child's settings file to a tmp path so slash
    # commands like ``/auto-continue off`` and ``/state verbs off``
    # don't write to the committed ``data/settings.json``. The conftest
    # autouse fixture handles this for in-process tests; for subprocess
    # tests we need an env var the child can read at import time.
    if "CHIKA_SETTINGS_PATH" not in env:
        import tempfile as _tf
        _settings_tmp = _tf.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        )
        # Seed with the same defaults the real file would have, so the
        # child sees ``auto_continue=on`` etc. without having to run init().
        json.dump({
            "auto_continue":     "on",
            "auto_continue_max": 10,
            "autonomy":          "supervised",
            "tool_permissions":  {},
            "pet_speech":        "off",
            "pet_speech_tokens": 40,
            "state_verbs":       "on",
            "state_verbs_tokens": 80,
        }, _settings_tmp)
        _settings_tmp.flush(); _settings_tmp.close()
        env["CHIKA_SETTINGS_PATH"] = _settings_tmp.name
    # Force-disable rich's terminal-detection magic so stdout is line-buffered
    # plain text — easier to assert on.
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if extra_env:
        env.update(extra_env)

    # Always end with /quit so the REPL gracefully exits even if a turn fails.
    if not inputs or inputs[-1].strip() != "/quit":
        inputs = list(inputs) + ["/quit"]
    stdin_payload = "\n".join(inputs) + "\n"

    try:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "chika.py")],
            input=stdin_payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            env=env,
            timeout=timeout,
        )
    finally:
        if cleanup_path is not None:
            try:
                cleanup_path.unlink()
            except OSError:
                pass

    return CliResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        plain=strip_ansi(proc.stdout),
    )


def script(turns: list[dict], *, title: str = "Stub Chat",
           completions: list[str] | None = None) -> dict:
    """Build a stub-LLM script payload for ``run_cli``.

    Each turn is ``{"text": "...", "workflow": {...}?}``. Completions are
    fallback responses for ``_llm_complete`` (title gen, condense, etc.)
    served in order.
    """
    return {
        "title":       title,
        "turns":       list(turns),
        "completions": list(completions or []),
    }


def text_turn(text: str) -> dict:
    return {"text": text}


def workflow_turn(workflow: dict, narrative: str = "") -> dict:
    return {"text": narrative, "workflow": workflow}
