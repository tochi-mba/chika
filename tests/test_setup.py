"""Tests for ``chika setup`` + the first-run nudge.

Covers:

  - run_setup() — TTY guard, .env-already-exists guard, --force,
    Python version guard, install.py-missing guard, KeyboardInterrupt
    handling, install.py exception → SetupResult.
  - needs_first_run_setup() — every truth-table branch.
  - render_first_run_nudge() — actually emits something.
  - Slash command + argv subcommand wiring.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from chika._cli import setup as setup_mod


# ── needs_first_run_setup ────────────────────────────────────────────


def test_needs_first_run_when_env_missing(tmp_path):
    assert setup_mod.needs_first_run_setup(tmp_path) is True


def test_needs_first_run_when_env_empty(tmp_path):
    (tmp_path / ".env").touch()
    assert setup_mod.needs_first_run_setup(tmp_path) is True


def test_does_not_need_first_run_when_env_populated(tmp_path):
    (tmp_path / ".env").write_text("CHIKA_PROVIDER=anthropic\n")
    assert setup_mod.needs_first_run_setup(tmp_path) is False


def test_needs_first_run_uses_default_root_when_unspecified():
    """Smoke: passing no arg falls back to the project root."""
    # We don't assert the exact bool — depends on whether the user
    # has a populated .env in the repo. Just verify it doesn't blow up.
    result = setup_mod.needs_first_run_setup()
    assert isinstance(result, bool)


# ── render_first_run_nudge ───────────────────────────────────────────


def test_render_first_run_nudge_mentions_setup_and_settings():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    setup_mod.render_first_run_nudge(console)
    out = buf.getvalue()
    assert "/setup" in out
    assert "settings" in out.lower()
    assert "first-run" in out.lower() or "configure" in out.lower()


# ── run_setup TTY guard ──────────────────────────────────────────────


def test_run_setup_refuses_without_tty(tmp_path):
    """Wizard needs interactive stdin/stdout."""
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=False,
    )
    assert result.success is False
    assert "interactive" in result.message.lower() or "tty" in result.message.lower()


# ── Python version guard ─────────────────────────────────────────────


def test_run_setup_refuses_below_python_3_11(monkeypatch, tmp_path):
    class _VI(tuple):
        major = 3
        minor = 10
    monkeypatch.setattr(setup_mod.sys, "version_info", _VI((3, 10, 0, "final", 0)))
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=True,
    )
    assert result.success is False
    assert "3.11" in result.message


# ── .env guard ───────────────────────────────────────────────────────


def test_run_setup_refuses_when_env_exists_without_force(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("CHIKA_PROVIDER=anthropic\n")
    # Provide a fake install.py so the missing-install check passes
    # — we only want to hit the .env guard in this test.
    (tmp_path / "install.py").write_text("def main():\n    pass\n")
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=True,
    )
    assert result.success is False
    assert ".env already exists" in result.message
    assert "/provider" in result.message or "force" in result.message.lower()


def test_run_setup_proceeds_when_env_empty(tmp_path):
    """An empty .env doesn't trigger the guard."""
    (tmp_path / ".env").touch()
    (tmp_path / "install.py").write_text("def main():\n    print('wizard ran')\n")
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=True,
    )
    assert result.success is True


def test_run_setup_force_overrides_env_guard(tmp_path):
    (tmp_path / ".env").write_text("CHIKA_PROVIDER=anthropic\n")
    (tmp_path / "install.py").write_text("def main():\n    pass\n")
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=True, force=True,
    )
    assert result.success is True


# ── install.py guards ────────────────────────────────────────────────


def test_run_setup_refuses_when_install_py_missing(tmp_path):
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=True,
    )
    assert result.success is False
    assert "install.py" in result.message


def test_run_setup_refuses_when_install_py_has_no_main(tmp_path):
    (tmp_path / "install.py").write_text("# no main here\n")
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=True,
    )
    assert result.success is False
    assert "main" in result.message.lower()


def test_run_setup_handles_install_py_raising(tmp_path):
    (tmp_path / "install.py").write_text(
        "def main():\n    raise RuntimeError('wizard exploded')\n",
    )
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=True,
    )
    assert result.success is False
    assert "wizard exploded" in result.message


def test_run_setup_handles_keyboardinterrupt(tmp_path):
    (tmp_path / "install.py").write_text(
        "def main():\n    raise KeyboardInterrupt\n",
    )
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=True,
    )
    assert result.success is False
    assert "cancel" in result.message.lower()


def test_run_setup_handles_systemexit_zero(tmp_path):
    (tmp_path / "install.py").write_text(
        "import sys\ndef main():\n    sys.exit(0)\n",
    )
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=True,
    )
    assert result.success is True


def test_run_setup_handles_systemexit_nonzero(tmp_path):
    (tmp_path / "install.py").write_text(
        "import sys\ndef main():\n    sys.exit(2)\n",
    )
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=True,
    )
    assert result.success is False
    assert "code 2" in result.message


def test_run_setup_handles_install_py_import_error(tmp_path):
    """install.py with a syntax error → import fails → SetupResult."""
    (tmp_path / "install.py").write_text("def main(:\n  pass\n")  # bad syntax
    result = setup_mod.run_setup(
        console=None, repo_root=tmp_path, is_tty=True,
    )
    assert result.success is False
    assert "import" in result.message.lower() or "failed" in result.message.lower()


# ── Console rendering ────────────────────────────────────────────────


def test_run_setup_renders_to_console(tmp_path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    setup_mod.run_setup(console=console, repo_root=tmp_path, is_tty=False)
    out = buf.getvalue()
    assert out  # something was rendered


# ── Slash + argv wiring ──────────────────────────────────────────────


def test_slash_setup_dispatches(monkeypatch):
    from chika._cli import commands as cmd

    called: list[bool] = []

    def fake_run_setup(*, console, force=False, repo_root=None, is_tty=None):
        called.append(force)
        return setup_mod.SetupResult(success=True, message="ok")

    monkeypatch.setattr(setup_mod, "run_setup", fake_run_setup)

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    ctx = cmd.CommandContext(console=console, engine=None)  # type: ignore[arg-type]
    cmd.dispatch(ctx, "/setup")
    cmd.dispatch(ctx, "/setup --force")
    assert called == [False, True]


def test_argv_setup_subcommand(monkeypatch):
    from chika._cli import app as appmod

    monkeypatch.setattr(
        setup_mod, "run_setup",
        lambda **_: setup_mod.SetupResult(success=True, message="ok"),
    )
    monkeypatch.setattr(appmod, "_run_rich",
                         lambda: pytest.fail("REPL must not boot"))
    appmod.cli(argv=["setup"])


def test_argv_setup_exits_nonzero_on_failure(monkeypatch):
    from chika._cli import app as appmod

    monkeypatch.setattr(
        setup_mod, "run_setup",
        lambda **_: setup_mod.SetupResult(success=False, message="fail"),
    )
    monkeypatch.setattr(appmod, "_run_rich", lambda: pytest.fail("nope"))
    with pytest.raises(SystemExit) as ei:
        appmod.cli(argv=["setup"])
    assert ei.value.code == 1


def test_argv_setup_passes_force_flag(monkeypatch):
    from chika._cli import app as appmod

    seen_force: list[bool] = []

    def fake(**kw):
        seen_force.append(kw.get("force", False))
        return setup_mod.SetupResult(success=True, message="ok")

    monkeypatch.setattr(setup_mod, "run_setup", fake)
    monkeypatch.setattr(appmod, "_run_rich", lambda: pytest.fail("nope"))
    appmod.cli(argv=["setup", "--force"])
    assert seen_force == [True]


# ── Slash command registered in /help ────────────────────────────────


def test_setup_slash_command_in_help_listing():
    from chika._cli import commands as cmd
    names = {c.name for c in cmd.list_commands()}
    assert "setup" in names


# ── Repo-root default ────────────────────────────────────────────────


def test_default_repo_root_resolves_to_project_root():
    p = setup_mod._default_repo_root()
    assert p.is_dir()
    # The repo root should have install.py
    assert (p / "install.py").is_file()
