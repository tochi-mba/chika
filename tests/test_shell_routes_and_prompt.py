"""Tests for the cross-surface shell-management additions:

- /api/shells, /api/shells/{pid}/kill, /api/shells/kill_all
- Active shells injected into the system prompt
- ProcessRegistry survives the round-trip
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config as cfg

cfg.MAX_MEMORY_TOKENS = 1000
cfg.MAX_HISTORY_TOKENS = 10000
cfg.CHIKA_API_KEY = ""
cfg.GROUNDING_VALIDATE_RESPONSE = False

from fastapi.testclient import TestClient

from api.server import app
from chika.core.prompt_builder import PromptBuilder
from chika.tools.shell_tool import ManagedProcess, ProcessRegistry


client = TestClient(app)


class _FakeProcess:
    """Stand-in for asyncio.subprocess.Process that records kill() calls."""
    def __init__(self, pid: int):
        self.pid = pid
        self.killed = False
    def kill(self):
        self.killed = True


def _make_proc(pid: int, command: str = "echo hi") -> ManagedProcess:
    p = ManagedProcess(pid=pid, command=command, process=_FakeProcess(pid))
    ProcessRegistry.register(p)
    return p


def _drop(*pids: int) -> None:
    for pid in pids:
        ProcessRegistry.remove(pid)


# ── /api/shells listing ──────────────────────────────────────────────────


def test_list_shells_includes_registered_processes():
    pid = 999_001
    _make_proc(pid, "ls -la /tmp")
    try:
        res = client.get("/api/shells")
        assert res.status_code == 200
        pids = [p["pid"] for p in res.json()["processes"]]
        assert pid in pids
    finally:
        _drop(pid)


def test_kill_shell_marks_running_false_and_calls_kill():
    pid = 999_002
    proc = _make_proc(pid, "yes > /dev/null")
    try:
        res = client.post(f"/api/shells/{pid}/kill")
        assert res.status_code == 200
        assert res.json()["killed"] is True
        assert proc.process.killed is True
        assert proc.running is False
    finally:
        _drop(pid)


def test_kill_unknown_shell_returns_404():
    res = client.post("/api/shells/123456789/kill")
    assert res.status_code == 404


def test_kill_already_exited_returns_already_exited():
    pid = 999_003
    proc = _make_proc(pid, "true")
    proc.running = False
    proc.exit_code = 0
    try:
        res = client.post(f"/api/shells/{pid}/kill")
        assert res.status_code == 200
        assert res.json()["already_exited"] is True
        assert res.json()["exit_code"] == 0
    finally:
        _drop(pid)


def test_kill_all_kills_only_running_processes():
    pid_a = 999_004
    pid_b = 999_005
    pid_c = 999_006
    a = _make_proc(pid_a, "running cmd a")
    b = _make_proc(pid_b, "running cmd b")
    c = _make_proc(pid_c, "exited cmd")
    c.running = False
    c.exit_code = 0
    try:
        res = client.post("/api/shells/kill_all")
        assert res.status_code == 200
        data = res.json()
        assert pid_a in data["killed"] and pid_b in data["killed"]
        assert pid_c not in data["killed"]
        assert a.process.killed is True
        assert b.process.killed is True
        # Already-exited process is left alone.
        assert c.process.killed is False
    finally:
        _drop(pid_a, pid_b, pid_c)


# ── System prompt injection ──────────────────────────────────────────────


def test_active_shells_appear_in_system_prompt():
    pb = PromptBuilder()
    rendered = pb.build(
        tool_list=[],
        variables=[],
        memory="",
        active_shells=[
            {"pid": 4242, "command": "npm run dev", "running": True,
             "exit_code": None},
            {"pid": 4243, "command": "python script.py", "running": False,
             "exit_code": 0},
        ],
    )
    assert "ACTIVE SHELLS" in rendered
    assert "pid 4242" in rendered
    assert "npm run dev" in rendered
    assert "pid 4243" in rendered
    assert "exited (code 0)" in rendered
    assert "shell_kill" in rendered  # the hint to terminate runaways


def test_no_active_shells_section_when_registry_empty():
    pb = PromptBuilder()
    rendered = pb.build(
        tool_list=[],
        variables=[],
        memory="",
        active_shells=None,
    )
    assert "ACTIVE SHELLS" not in rendered


def test_long_commands_in_prompt_are_truncated():
    pb = PromptBuilder()
    very_long = "x" * 500
    rendered = pb.build(
        tool_list=[],
        variables=[],
        memory="",
        active_shells=[
            {"pid": 1, "command": very_long, "running": True, "exit_code": None}
        ],
    )
    # Truncated with an ellipsis — full 500-char string must NOT appear.
    assert very_long not in rendered
    assert "…" in rendered or "..." in rendered
