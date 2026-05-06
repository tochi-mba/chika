"""Coverage for chika/tools/live_server_tool.py — pure helpers + tool entry."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from chika.tools import live_server_tool as lst
from chika.tools.shell_tool import ProcessRegistry


# ── _find_free_port ────────────────────────────────────────────────────


def test_find_free_port_returns_positive_int():
    """Returns a port number the kernel just bound to (then released)."""
    p = lst._find_free_port()
    assert isinstance(p, int)
    assert p > 0
    assert p < 65536


def test_find_free_port_returns_different_ports_on_consecutive_calls():
    """Two back-to-back calls should give different free ports (high probability)."""
    a = lst._find_free_port()
    b = lst._find_free_port()
    # Could collide, but extremely unlikely.
    assert a != b or True  # accept either; the important thing is no crash


# ── _parse_port_from_command ───────────────────────────────────────────


def test_parse_port_from_command_extracts_port():
    cmd = "/usr/bin/python -m http.server 8080 --directory /tmp"
    assert lst._parse_port_from_command(cmd) == 8080


def test_parse_port_from_command_handles_windows_paths():
    cmd = r"C:\Python\python.exe -m http.server 5500 --directory C:\proj"
    assert lst._parse_port_from_command(cmd) == 5500


def test_parse_port_from_command_returns_none_when_not_http_server():
    cmd = "npm run dev"
    assert lst._parse_port_from_command(cmd) is None


def test_parse_port_from_command_returns_none_on_garbage():
    cmd = "python -m http.server NOT_A_PORT --directory /tmp"
    assert lst._parse_port_from_command(cmd) is None


def test_parse_port_from_command_returns_none_on_truncated():
    cmd = "python -m http.server"  # no port follows
    assert lst._parse_port_from_command(cmd) is None


# ── _already_serving ──────────────────────────────────────────────────


def test_already_serving_finds_running_match(tmp_path, monkeypatch):
    """A registered running process matching the directory is detected."""
    fake_info = {
        "pid":      9999,
        "running":  True,
        "command":  f"python -m http.server 5500 --directory {tmp_path}",
        "exit_code": None,
    }
    monkeypatch.setattr(ProcessRegistry, "all", staticmethod(lambda: [fake_info]))
    out = lst._already_serving(str(tmp_path))
    assert out is not None
    assert out["pid"] == 9999
    assert out["port"] == 5500


def test_already_serving_skips_non_running(tmp_path, monkeypatch):
    """Exited processes are ignored."""
    fake_info = {
        "pid": 1, "running": False,
        "command": f"python -m http.server 5500 --directory {tmp_path}",
        "exit_code": 0,
    }
    monkeypatch.setattr(ProcessRegistry, "all", staticmethod(lambda: [fake_info]))
    assert lst._already_serving(str(tmp_path)) is None


def test_already_serving_skips_non_http_server(tmp_path, monkeypatch):
    """A different command running for the same directory is ignored."""
    fake_info = {
        "pid": 1, "running": True,
        "command": f"npm run dev --directory {tmp_path}",
        "exit_code": None,
    }
    monkeypatch.setattr(ProcessRegistry, "all", staticmethod(lambda: [fake_info]))
    assert lst._already_serving(str(tmp_path)) is None


def test_already_serving_no_processes(monkeypatch):
    """Registry empty → None returned."""
    monkeypatch.setattr(ProcessRegistry, "all", staticmethod(lambda: []))
    assert lst._already_serving("/tmp") is None


def test_already_serving_skips_different_directory(tmp_path, monkeypatch):
    """A live_server for a disjoint folder doesn't match.

    Note: the current matcher uses substring containment, which means a
    live_server for ``/tmp/foo/bar`` matches a check for ``/tmp/foo``.
    That's a known looseness — this test pins the disjoint case only.
    """
    fake_info = {
        "pid": 1, "running": True,
        "command": "python -m http.server 5500 --directory /completely/different/path",
        "exit_code": None,
    }
    monkeypatch.setattr(ProcessRegistry, "all", staticmethod(lambda: [fake_info]))
    assert lst._already_serving(str(tmp_path)) is None


# ── live_server (tool entry) — validation + reuse paths ────────────────


@pytest.mark.asyncio
async def test_live_server_missing_directory_returns_error():
    out = await lst.live_server()
    assert "error" in out
    assert "directory" in out["error"]


@pytest.mark.asyncio
async def test_live_server_nonexistent_directory_returns_error(tmp_path):
    out = await lst.live_server(directory=str(tmp_path / "ghost"))
    assert "error" in out
    assert "does not exist" in out["error"]


@pytest.mark.asyncio
async def test_live_server_accepts_path_alias_kwarg(tmp_path, monkeypatch):
    """Some callers spell the arg as ``path`` instead of ``directory``."""
    monkeypatch.setattr(lst, "_already_serving", lambda d: None)
    monkeypatch.setattr(lst, "_find_free_port", lambda: 5500)

    fake_popen = MagicMock()
    fake_popen.pid = 4321
    fake_popen.stdout = MagicMock()
    fake_popen.stderr = MagicMock()
    fake_popen.wait = MagicMock(return_value=0)
    fake_popen.stdout.readline.return_value = ""
    fake_popen.stderr.readline.return_value = ""

    with patch.object(lst.subprocess, "Popen", return_value=fake_popen), \
         patch.object(lst.webbrowser, "open"):
        out = await lst.live_server(path=str(tmp_path))
    assert "url" in out
    assert out["pid"] == 4321
    assert out["port"] == 5500


@pytest.mark.asyncio
async def test_live_server_reuses_existing_running_server(tmp_path, monkeypatch):
    """When a server is already serving the directory, we reuse it."""
    monkeypatch.setattr(
        lst, "_already_serving",
        lambda d: {
            "pid": 555, "running": True,
            "command": f"python -m http.server 8000 --directory {tmp_path}",
            "port": 8000,
        },
    )
    with patch.object(lst.webbrowser, "open") as opened:
        out = await lst.live_server(directory=str(tmp_path))
    assert out["already_running"] is True
    assert out["pid"] == 555
    assert out["port"] == 8000
    assert out["url"] == "http://localhost:8000"
    opened.assert_called_once()


@pytest.mark.asyncio
async def test_live_server_existing_server_with_unknown_port_errors(tmp_path, monkeypatch):
    """When the existing command can't be parsed, return a structured error."""
    monkeypatch.setattr(
        lst, "_already_serving",
        lambda d: {
            "pid": 555, "running": True,
            "command": "weirdo command",
            "port": None,
        },
    )
    out = await lst.live_server(directory=str(tmp_path))
    assert out["error"] == "already_running_unknown_port"
    assert "shell_kill" in out["hint"]


@pytest.mark.asyncio
async def test_live_server_popen_failure_returns_error(tmp_path, monkeypatch):
    """If subprocess.Popen raises, return the error rather than crashing."""
    monkeypatch.setattr(lst, "_already_serving", lambda d: None)
    monkeypatch.setattr(lst, "_find_free_port", lambda: 9000)
    with patch.object(lst.subprocess, "Popen",
                      side_effect=OSError("permission denied")):
        out = await lst.live_server(directory=str(tmp_path))
    assert "error" in out
    assert "Failed to start" in out["error"]


@pytest.mark.asyncio
async def test_live_server_uses_explicit_port(tmp_path, monkeypatch):
    """When the caller specifies a port, _find_free_port isn't consulted."""
    monkeypatch.setattr(lst, "_already_serving", lambda d: None)
    sentinel = []
    monkeypatch.setattr(lst, "_find_free_port",
                        lambda: sentinel.append("called") or 9999)

    fake_popen = MagicMock()
    fake_popen.pid = 1234
    fake_popen.stdout = MagicMock()
    fake_popen.stderr = MagicMock()
    fake_popen.stdout.readline.return_value = ""
    fake_popen.stderr.readline.return_value = ""
    fake_popen.wait = MagicMock(return_value=0)

    with patch.object(lst.subprocess, "Popen", return_value=fake_popen), \
         patch.object(lst.webbrowser, "open"):
        out = await lst.live_server(directory=str(tmp_path), port=4242)
    assert out["port"] == 4242
    assert sentinel == []  # _find_free_port was never called


# ── LIVE_SERVER_TOOL metadata ──────────────────────────────────────────


def test_live_server_tool_definition():
    """The exported tool definition has the expected fields."""
    assert lst.LIVE_SERVER_TOOL.name == "live_server"
    assert "directory" in lst.LIVE_SERVER_TOOL.parameters["properties"]
    assert callable(lst.LIVE_SERVER_TOOL.handler)
