"""Tests for live_server tool — port-from-command parsing + the
already-running detection path that previously emitted broken
``http://localhost:?`` URLs."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
from pathlib import Path

import pytest

from chika.tools.live_server_tool import (
    _already_serving,
    _parse_port_from_command,
    live_server,
)
from chika.tools.shell_tool import ManagedProcess, ProcessRegistry


# ── _parse_port_from_command ────────────────────────────────────────


def test_parse_port_from_command_returns_int():
    cmd = "python -m http.server 8000 --directory /tmp/app"
    assert _parse_port_from_command(cmd) == 8000


def test_parse_port_from_command_with_full_python_path():
    cmd = "C:\\Python\\python.exe -m http.server 4173 --directory C:\\proj"
    assert _parse_port_from_command(cmd) == 4173


def test_parse_port_returns_none_when_no_http_server():
    assert _parse_port_from_command("npm run dev") is None


def test_parse_port_returns_none_when_malformed():
    assert _parse_port_from_command("python -m http.server --directory /x") is None


# ── _already_serving ──────────────────────────────────────────────


class _FakeProc:
    def __init__(self, pid):
        self.pid = pid


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "site"
    ws.mkdir()
    return ws


def test_already_serving_returns_port_when_match_found(workspace):
    cmd = f"python -m http.server 9876 --directory {workspace}"
    proc = ManagedProcess(pid=11111, command=cmd, process=_FakeProc(11111))
    ProcessRegistry.register(proc)
    try:
        existing = _already_serving(str(workspace))
        assert existing is not None
        assert existing["port"] == 9876
        assert existing["pid"] == 11111
    finally:
        ProcessRegistry.remove(11111)


def test_already_serving_skips_exited_processes(workspace):
    cmd = f"python -m http.server 8000 --directory {workspace}"
    proc = ManagedProcess(pid=22222, command=cmd, process=_FakeProc(22222))
    proc.running = False
    ProcessRegistry.register(proc)
    try:
        assert _already_serving(str(workspace)) is None
    finally:
        ProcessRegistry.remove(22222)


def test_already_serving_returns_none_for_different_directory(workspace, tmp_path):
    other = tmp_path / "other_site"
    other.mkdir()
    cmd = f"python -m http.server 7777 --directory {other}"
    proc = ManagedProcess(pid=33333, command=cmd, process=_FakeProc(33333))
    ProcessRegistry.register(proc)
    try:
        assert _already_serving(str(workspace)) is None
    finally:
        ProcessRegistry.remove(33333)


# ── live_server() integration ────────────────────────────────────


@pytest.mark.asyncio
async def test_live_server_already_running_returns_real_url(workspace, monkeypatch):
    """Regression for the ``http://localhost:?`` bug: when a server
    is already running, the returned URL must include the actual
    port, not a placeholder."""
    cmd = f"python -m http.server 9123 --directory {workspace}"
    proc = ManagedProcess(pid=55555, command=cmd, process=_FakeProc(55555))
    ProcessRegistry.register(proc)
    # Stub webbrowser.open so the test doesn't actually launch a tab.
    monkeypatch.setattr(
        "chika.tools.live_server_tool.webbrowser.open",
        lambda url: None,
    )
    try:
        result = await live_server(directory=str(workspace))
        assert result["already_running"] is True
        assert result["url"] == "http://localhost:9123"
        assert result["port"] == 9123
        assert result["pid"] == 55555
    finally:
        ProcessRegistry.remove(55555)


@pytest.mark.asyncio
async def test_live_server_already_running_unparseable_port_returns_error(
    workspace, monkeypatch,
):
    """When the existing process command has no parseable port, return
    a structured error rather than a broken URL."""
    # Command contains 'http.server' (matches detector) but no port —
    # contrived but verifies the unhappy-path branch.
    cmd = f"python -m http.server --directory {workspace}"
    proc = ManagedProcess(pid=66666, command=cmd, process=_FakeProc(66666))
    ProcessRegistry.register(proc)
    monkeypatch.setattr(
        "chika.tools.live_server_tool.webbrowser.open",
        lambda url: None,
    )
    try:
        result = await live_server(directory=str(workspace))
        assert result.get("error") == "already_running_unknown_port"
        assert result["pid"] == 66666
        assert "url" not in result   # never emit a broken URL
    finally:
        ProcessRegistry.remove(66666)


@pytest.mark.asyncio
async def test_live_server_missing_directory_returns_error():
    result = await live_server(directory="/path/that/definitely/does/not/exist")
    assert "error" in result
    assert "Directory does not exist" in result["error"]


@pytest.mark.asyncio
async def test_live_server_empty_directory_returns_error():
    result = await live_server(directory="")
    assert result.get("error") == "Missing required argument: directory"
