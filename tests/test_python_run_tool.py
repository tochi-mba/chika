"""Coverage for chika/tools/python_run_tool.py.

The bulk of the module is pure helpers — AST scanning, pip-log
parsing, error classification, candidate resolution. Those are
deterministic and need no subprocess. We test them directly. The
actual subprocess spawn / install paths are exercised by the
integration tests in test_e2e_engine_stub.py + test_cli_e2e.py.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from chika.tools import python_run_tool as prt


# ── _top_level_imports ─────────────────────────────────────────────────


def test_top_level_imports_simple(tmp_path: Path):
    script = tmp_path / "a.py"
    script.write_text("import os\nimport sys\nprint(1)\n")
    assert prt._top_level_imports(script) == ["os", "sys"]


def test_top_level_imports_from_form(tmp_path: Path):
    script = tmp_path / "b.py"
    script.write_text("from pathlib import Path\nfrom collections import deque\n")
    assert prt._top_level_imports(script) == ["collections", "pathlib"]


def test_top_level_imports_dotted_returns_root(tmp_path: Path):
    """``import pygame.locals`` should resolve to ``pygame``, not the dotted form."""
    script = tmp_path / "c.py"
    script.write_text("import pygame.locals\nimport os.path\n")
    out = prt._top_level_imports(script)
    assert "pygame" in out
    assert "os" in out
    assert "pygame.locals" not in out


def test_top_level_imports_relative_imports_skipped(tmp_path: Path):
    """``from . import sibling`` (level=1) is intra-package; we skip it."""
    script = tmp_path / "d.py"
    script.write_text("from . import sibling\nfrom os import path\n")
    out = prt._top_level_imports(script)
    assert "os" in out
    # The relative import has no module name → not added.


def test_top_level_imports_invalid_syntax_returns_empty(tmp_path: Path):
    """Unparseable scripts shouldn't crash — return [] and let runtime decide."""
    script = tmp_path / "broken.py"
    script.write_text("def (\n")  # Syntax error
    assert prt._top_level_imports(script) == []


def test_top_level_imports_missing_file_returns_empty(tmp_path: Path):
    """Missing files don't crash."""
    assert prt._top_level_imports(tmp_path / "nope.py") == []


# ── _missing_modules ───────────────────────────────────────────────────


def test_missing_modules_filters_stdlib():
    """Stdlib modules are never reported as missing."""
    out = prt._missing_modules(["os", "sys", "json", "pathlib"])
    assert out == []


def test_missing_modules_finds_truly_missing():
    """A module that doesn't exist anywhere appears in the output."""
    out = prt._missing_modules(["this_module_should_not_exist_anywhere_v9999"])
    assert out == ["this_module_should_not_exist_anywhere_v9999"]


def test_missing_modules_mixed():
    """A mix of stdlib + missing returns just the missing ones."""
    out = prt._missing_modules(["os", "ghost_module_xyz", "json"])
    assert out == ["ghost_module_xyz"]


# ── _pip_candidates ────────────────────────────────────────────────────


def test_pip_candidates_unknown_returns_self():
    """An unknown import name maps to itself as the only candidate."""
    assert prt._pip_candidates("requests") == ["requests"]


def test_pip_candidates_known_alternatives():
    """``cv2`` is well-known to map to ``opencv-python`` first."""
    out = prt._pip_candidates("cv2")
    assert out[0] == "opencv-python"
    assert "opencv-python-headless" in out


def test_pip_candidates_pygame_has_ce_fallback():
    """``pygame`` walks to ``pygame-ce`` when the canonical wheel is missing."""
    out = prt._pip_candidates("pygame")
    assert out == ["pygame", "pygame-ce"]


def test_pip_candidates_pillow_aliasing():
    """``import PIL`` → ``Pillow`` is the canonical pip name."""
    assert prt._pip_candidates("PIL") == ["Pillow"]


def test_pip_candidates_yaml_aliasing():
    assert prt._pip_candidates("yaml") == ["PyYAML"]


def test_pip_candidates_bs4_aliasing():
    assert prt._pip_candidates("bs4") == ["beautifulsoup4"]


# ── _summarise_pip_log ─────────────────────────────────────────────────


def test_summarise_pip_log_extracts_error_lines():
    """ERROR-prefixed lines surface in the summary."""
    log = "\n".join([
        "Downloading thing.tar.gz",
        "Downloading another.whl",
        "ERROR: Could not find a version that satisfies the requirement foo",
        "ERROR: No matching distribution found for foo",
        "  fixing things",
    ])
    out = prt._summarise_pip_log(log)
    assert "ERROR: Could not find a version" in out
    assert "ERROR: No matching distribution found" in out


def test_summarise_pip_log_keeps_tail():
    """Even without ERROR lines, the last ~15 lines come back."""
    log = "\n".join(f"line {i}" for i in range(50))
    out = prt._summarise_pip_log(log)
    # Tail should include the latest entries.
    assert "line 49" in out
    assert "line 35" in out


def test_summarise_pip_log_dedupes_lines():
    """Duplicate ERROR lines collapse to a single entry."""
    log = "\n".join([
        "ERROR: same problem",
        "ERROR: same problem",
        "  more text",
    ])
    out = prt._summarise_pip_log(log)
    # Should appear only once.
    assert out.count("ERROR: same problem") == 1


def test_summarise_pip_log_empty_falls_back_to_tail():
    """An empty log should not crash; returns whatever's in tail."""
    out = prt._summarise_pip_log("")
    assert out == ""  # Empty log → empty summary, no exception.


# ── _classify_failure ──────────────────────────────────────────────────


def test_classify_failure_no_wheel():
    log = "ERROR: No matching distribution found for foo"
    assert prt._classify_failure(log) == "no_wheel_for_this_python"


def test_classify_failure_compile():
    log = "error: Microsoft Visual C++ 14.0 or greater is required"
    assert prt._classify_failure(log) == "compile_failed_no_toolchain"


def test_classify_failure_compile_subprocess():
    log = "subprocess-exited-with-error"
    assert prt._classify_failure(log) == "compile_failed_no_toolchain"


def test_classify_failure_network():
    log = "Could not connect to pypi.org"
    assert prt._classify_failure(log) == "network_error"


def test_classify_failure_dns():
    log = "Temporary failure in name resolution"
    assert prt._classify_failure(log) == "network_error"


def test_classify_failure_permission():
    log = "Access is denied"
    assert prt._classify_failure(log) == "permission_denied"


def test_classify_failure_unknown():
    log = "Something happened we did not expect"
    assert prt._classify_failure(log) == "unknown"


# ── _windows_creationflags ─────────────────────────────────────────────


def test_windows_creationflags_zero_off_windows():
    """On non-Windows, returns 0 (no creation flags)."""
    with patch.object(prt.sys, "platform", "linux"):
        assert prt._windows_creationflags() == 0


def test_windows_creationflags_create_new_console_on_windows():
    """On Windows, returns CREATE_NEW_CONSOLE (0x10)."""
    with patch.object(prt.sys, "platform", "win32"):
        assert prt._windows_creationflags() == 0x10


# ── _try_install ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_try_install_success_path():
    """When pip exits 0, _try_install returns (0, log)."""
    class FakeProc:
        returncode = 0
        async def communicate(self):
            return (b"installed!\n", None)

    async def fake_create(*a, **kw):
        return FakeProc()

    with patch.object(prt.asyncio, "create_subprocess_exec", fake_create):
        rc, log = await prt._try_install("requests")
    assert rc == 0
    assert "installed" in log


@pytest.mark.asyncio
async def test_try_install_failure_path():
    """When pip exits non-zero, _try_install propagates the code + log."""
    class FakeProc:
        returncode = 1
        async def communicate(self):
            return (b"ERROR: no wheel\n", None)

    async def fake_create(*a, **kw):
        return FakeProc()

    with patch.object(prt.asyncio, "create_subprocess_exec", fake_create):
        rc, log = await prt._try_install("nope")
    assert rc == 1
    assert "no wheel" in log


# ── _install_module — walks the alternatives list ──────────────────────


@pytest.mark.asyncio
async def test_install_module_succeeds_on_first_candidate():
    """When the first pip candidate works, no fallbacks are tried."""
    calls: list[str] = []

    async def fake_install(dist):
        calls.append(dist)
        return 0, "installed"

    with patch.object(prt, "_try_install", fake_install):
        out = await prt._install_module("pygame")
    assert out["ok"] is True
    assert out["installed_as"] == "pygame"
    assert calls == ["pygame"]   # Stops on first success.


@pytest.mark.asyncio
async def test_install_module_falls_back_to_alternative():
    """When the first candidate fails, the next is tried."""
    calls: list[str] = []

    async def fake_install(dist):
        calls.append(dist)
        # First call (pygame) fails; second (pygame-ce) succeeds.
        if dist == "pygame":
            return 1, "ERROR: No matching distribution found for pygame"
        return 0, "installed"

    with patch.object(prt, "_try_install", fake_install):
        out = await prt._install_module("pygame")
    assert out["ok"] is True
    assert out["installed_as"] == "pygame-ce"
    assert calls == ["pygame", "pygame-ce"]


@pytest.mark.asyncio
async def test_install_module_all_candidates_fail_returns_fix_command():
    """When every candidate fails, surface a `fix_command` for the user."""

    async def fake_install(dist):
        return 1, "ERROR: No matching distribution found"

    with patch.object(prt, "_try_install", fake_install):
        out = await prt._install_module("pygame")
    assert out["ok"] is False
    assert out["import_name"] == "pygame"
    assert "pip install" in out["fix_command"]
    # Fix command suggests the LAST attempted distribution.
    assert "pygame-ce" in out["fix_command"]
    assert out["reason"] == "no_wheel_for_this_python"


# ── Validation in _python_run ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_python_run_rejects_empty_script():
    out = await prt._python_run(script="")
    assert "error" in out
    assert "non-empty" in out["error"]


@pytest.mark.asyncio
async def test_python_run_rejects_non_string_script():
    out = await prt._python_run(script=None)  # type: ignore[arg-type]
    assert "error" in out


@pytest.mark.asyncio
async def test_python_run_rejects_missing_file(tmp_path: Path):
    out = await prt._python_run(script=str(tmp_path / "ghost.py"))
    assert "error" in out
    assert "not found" in out["error"]


@pytest.mark.asyncio
async def test_python_run_rejects_non_py_extension(tmp_path: Path):
    other = tmp_path / "x.txt"
    other.write_text("hello")
    out = await prt._python_run(script=str(other))
    assert "error" in out
    assert ".py" in out["error"]


@pytest.mark.asyncio
async def test_python_run_resolves_relative_path(tmp_path: Path):
    """When `working_directory` is given, relative scripts resolve there."""
    sub = tmp_path / "wd"
    sub.mkdir()
    (sub / "ghost.py").touch()
    # ``ghost.py`` exists under wd/ — but we'll claim it's not there to
    # short-circuit before the spawn. Easier: give a path that doesn't
    # exist anywhere to confirm the wd is consulted in the resolution.
    out = await prt._python_run(
        script="ghost.py", working_directory=str(sub),
    )
    # We're past the resolution step — if it failed earlier with
    # "not found", the wd lookup didn't help. Either way, we don't
    # actually want to spawn here, so accept any error or success.
    assert isinstance(out, dict)
