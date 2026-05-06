"""Tests for ``chika uninstall`` across all install kinds.

Each install-kind branch is tested with the subprocess runner mocked
so we never actually run pip uninstall, sudo apt remove, or any
destructive command in test.
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest
from rich.console import Console

from chika._cli import uninstall as uninst


def _proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["x"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


# ── Unknown install kind ────────────────────────────────────────────


def test_uninstall_unknown_install(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind",
        lambda: "unknown",
    )
    result = uninst.uninstall_chika(console=None)
    assert result.kind == "unknown"
    assert result.success is False
    # Must mention each install kind so user can self-diagnose
    assert "pip" in result.message.lower()
    assert "windows" in result.message.lower()


# ── pip_pypi ────────────────────────────────────────────────────────


def test_uninstall_pip_pypi_dry_run_yes(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "pip_pypi",
    )
    result = uninst.uninstall_chika(yes=True, dry_run=True)
    assert result.success is True
    assert "dry-run" in result.message


def test_uninstall_pip_pypi_no_yes_just_instructs(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "pip_pypi",
    )
    result = uninst.uninstall_chika(yes=False)
    assert result.success is True
    assert "pip uninstall" in result.message


def test_uninstall_pip_pypi_runs_pip(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "pip_pypi",
    )
    captured: list[list[str]] = []

    def fake_run(cmd):
        captured.append(cmd)
        return _proc(returncode=0)

    result = uninst.uninstall_chika(yes=True, runner=fake_run)
    assert result.success is True
    assert any("pip" in c for c in captured[0])
    assert "uninstall" in captured[0]
    assert "chika" in captured[0]


def test_uninstall_pip_pypi_failure_surfaced(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "pip_pypi",
    )
    result = uninst.uninstall_chika(
        yes=True,
        runner=lambda cmd: _proc(returncode=1, stderr="permission denied"),
    )
    assert result.success is False
    assert "fail" in result.message.lower() or "permission" in result.message.lower()


# ── git_clone ────────────────────────────────────────────────────────


def test_uninstall_git_clone_includes_repo_dir_note(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "git_clone",
    )
    result = uninst.uninstall_chika(
        yes=True, runner=lambda cmd: _proc(returncode=0),
    )
    assert result.success is True
    assert "rm -rf" in result.message  # clone-dir hint
    assert "untouched" in result.message.lower()


# ── windows_installer ───────────────────────────────────────────────


def test_uninstall_windows_no_unins_falls_back_to_arp_instructions(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "windows_installer",
    )
    monkeypatch.setattr(uninst, "_resolve_install_dir", lambda: None)
    result = uninst.uninstall_chika(yes=True)
    assert result.success is True
    assert "Settings" in result.message and "Apps" in result.message


def test_uninstall_windows_runs_unins_when_yes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "windows_installer",
    )
    install_dir = tmp_path / "ChikaInstall"
    install_dir.mkdir()
    (install_dir / "unins000.exe").write_bytes(b"fake")
    monkeypatch.setattr(uninst, "_resolve_install_dir", lambda: install_dir)

    captured: list[list[str]] = []
    result = uninst.uninstall_chika(
        yes=True,
        runner=lambda cmd: captured.append(cmd) or _proc(returncode=0),
    )
    assert result.success is True
    assert any("unins000" in str(c) for c in captured[0])
    assert "/SILENT" in captured[0]


def test_uninstall_windows_no_yes_just_instructs(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "windows_installer",
    )
    install_dir = tmp_path / "ChikaInstall"
    install_dir.mkdir()
    (install_dir / "unins000.exe").write_bytes(b"fake")
    monkeypatch.setattr(uninst, "_resolve_install_dir", lambda: install_dir)

    result = uninst.uninstall_chika(yes=False)
    assert result.success is True
    assert "unins000.exe" in result.message
    assert "Settings" in result.message  # mentions ARP path too


def test_uninstall_windows_failure_returns_nonzero_result(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "windows_installer",
    )
    install_dir = tmp_path / "ChikaInstall"
    install_dir.mkdir()
    (install_dir / "unins000.exe").write_bytes(b"fake")
    monkeypatch.setattr(uninst, "_resolve_install_dir", lambda: install_dir)

    result = uninst.uninstall_chika(
        yes=True, runner=lambda cmd: _proc(returncode=42),
    )
    assert result.success is False
    assert "42" in result.message


# ── macos_installer ─────────────────────────────────────────────────


def test_uninstall_macos_no_script_falls_back(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "macos_installer",
    )
    # Path doesn't exist → graceful fallback message
    result = uninst.uninstall_chika(yes=True)
    assert result.success is True
    assert "uninstall script not found" in result.message.lower() or ".pkg" in result.message


def test_uninstall_macos_runs_sudo_script_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "macos_installer",
    )
    fake_script = tmp_path / "uninstall.sh"
    fake_script.write_text("#!/bin/bash\necho ok\n")

    # Patch the Path the impl looks at.
    real_path_cls = uninst.Path
    monkeypatch.setattr(
        uninst, "Path",
        lambda *a, **kw: fake_script if str(a[0]) == "/Library/Application Support/Chika/uninstall.sh" else real_path_cls(*a, **kw),
    )

    captured: list[list[str]] = []
    result = uninst.uninstall_chika(
        yes=True,
        runner=lambda cmd: captured.append(cmd) or _proc(returncode=0),
    )
    assert result.success is True
    # First arg of the captured cmd should be sudo
    assert captured[0][0] == "sudo"


# ── linux_deb ───────────────────────────────────────────────────────


def test_uninstall_deb_uses_apt_when_present(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "linux_deb",
    )
    monkeypatch.setattr(uninst.shutil, "which",
                         lambda name: f"/usr/bin/{name}" if name in ("apt-get", "apt") else None)
    captured: list[list[str]] = []
    result = uninst.uninstall_chika(
        yes=True, runner=lambda cmd: captured.append(cmd) or _proc(returncode=0),
    )
    assert result.success is True
    assert captured[0][0] == "sudo"
    assert any("apt" in s for s in captured[0])
    assert "chika" in captured[0]


def test_uninstall_deb_falls_back_to_dpkg_when_apt_missing(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "linux_deb",
    )
    monkeypatch.setattr(uninst.shutil, "which", lambda name: None)
    captured: list[list[str]] = []
    result = uninst.uninstall_chika(
        yes=True, runner=lambda cmd: captured.append(cmd) or _proc(returncode=0),
    )
    assert result.success is True
    assert "dpkg" in captured[0]


def test_uninstall_deb_no_yes_returns_apt_command(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "linux_deb",
    )
    monkeypatch.setattr(uninst.shutil, "which", lambda name: f"/usr/bin/{name}")
    result = uninst.uninstall_chika(yes=False)
    assert result.success is True
    assert "apt remove" in result.message


# ── linux_universal ─────────────────────────────────────────────────


def test_uninstall_linux_universal_falls_back_when_script_missing(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "linux_universal",
    )
    result = uninst.uninstall_chika(yes=True)
    assert result.success is True
    # Should print manual rm commands
    assert "rm -rf" in result.message or "uninstall" in result.message.lower()


def test_uninstall_linux_universal_runs_script_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "linux_universal",
    )
    real_path_cls = uninst.Path

    def fake_home():
        return tmp_path

    monkeypatch.setattr(real_path_cls, "home", staticmethod(fake_home))
    script_dir = tmp_path / ".local" / "share" / "chika"
    script_dir.mkdir(parents=True)
    (script_dir / "uninstall.sh").write_text("#!/usr/bin/env bash\necho ok\n")

    captured: list[list[str]] = []
    result = uninst.uninstall_chika(
        yes=True, runner=lambda cmd: captured.append(cmd) or _proc(returncode=0),
    )
    assert result.success is True
    assert captured[0][0] == "bash"


# ── --remove-data ───────────────────────────────────────────────────


def test_uninstall_remove_data_wipes_user_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "pip_pypi",
    )
    user_dir = tmp_path / ".chika"
    user_dir.mkdir()
    (user_dir / "settings.json").write_text("{}")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    uninst.uninstall_chika(
        yes=True, remove_data=True,
        runner=lambda cmd: _proc(returncode=0),
    )
    assert not user_dir.exists()


def test_uninstall_remove_data_skipped_on_failure(monkeypatch, tmp_path):
    """If the underlying uninstall fails, we must NOT wipe user data."""
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "pip_pypi",
    )
    user_dir = tmp_path / ".chika"
    user_dir.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    uninst.uninstall_chika(
        yes=True, remove_data=True,
        runner=lambda cmd: _proc(returncode=1, stderr="boom"),
    )
    # Dir is preserved because base uninstall failed
    assert user_dir.exists()


# ── Console rendering ───────────────────────────────────────────────


def test_uninstall_renders_panel_to_console(monkeypatch):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "pip_pypi",
    )
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    uninst.uninstall_chika(console=console, yes=False)
    out = buf.getvalue()
    assert "pip_pypi" in out
    assert "preserved" in out.lower() or "remove-data" in out.lower()


def test_uninstall_renders_remove_data_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chika._cli.update.detect_install_kind", lambda: "pip_pypi",
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / ".chika").mkdir()
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    uninst.uninstall_chika(
        console=console, yes=True, remove_data=True,
        runner=lambda cmd: _proc(returncode=0),
    )
    out = buf.getvalue()
    assert "wiped" in out.lower()


# ── Slash + argv wiring ─────────────────────────────────────────────


def test_slash_uninstall_dispatches(monkeypatch):
    from chika._cli import commands as cmd

    captured: dict = {}

    def fake_uninstall(*, console, yes, remove_data):
        captured["yes"] = yes
        captured["remove_data"] = remove_data
        return uninst.UninstallResult(kind="x", success=True, message="ok")

    monkeypatch.setattr(uninst, "uninstall_chika", fake_uninstall)

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    ctx = cmd.CommandContext(console=console, engine=None)  # type: ignore[arg-type]
    cmd.dispatch(ctx, "/uninstall --yes --remove-data")
    assert captured == {"yes": True, "remove_data": True}


def test_argv_uninstall_subcommand(monkeypatch):
    from chika._cli import app as appmod

    monkeypatch.setattr(
        uninst, "uninstall_chika",
        lambda **kw: uninst.UninstallResult(
            kind="pip_pypi", success=True, message="ok",
        ),
    )
    monkeypatch.setattr(appmod, "_run_rich", lambda: pytest.fail("nope"))
    appmod.cli(argv=["uninstall"])


def test_argv_uninstall_exits_nonzero_on_failure(monkeypatch):
    from chika._cli import app as appmod

    monkeypatch.setattr(
        uninst, "uninstall_chika",
        lambda **kw: uninst.UninstallResult(
            kind="pip_pypi", success=False, message="fail",
        ),
    )
    monkeypatch.setattr(appmod, "_run_rich", lambda: pytest.fail("nope"))
    with pytest.raises(SystemExit) as ei:
        appmod.cli(argv=["uninstall"])
    assert ei.value.code == 1


def test_uninstall_slash_command_in_help_listing():
    from chika._cli import commands as cmd
    names = {c.name for c in cmd.list_commands()}
    assert "uninstall" in names
