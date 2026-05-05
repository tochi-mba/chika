"""Tests for shell_tool — execute, timeout, fire-and-forget."""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
import platform

from chika.tools.shell_tool import SHELL_TOOL, shell_exec


def run(coro):
    return asyncio.run(coro)


IS_WINDOWS = platform.system() == "Windows"


# ── Basic execution ───────────────────────────────────────────────────────────

def test_echo_returns_stdout():
    if IS_WINDOWS:
        result = run(shell_exec("echo hello"))
    else:
        result = run(shell_exec("echo hello"))
    assert "hello" in result["stdout"]
    assert result["exit_code"] == 0
    assert result["timed_out"] is False


def test_exit_code_zero_on_success():
    result = run(shell_exec("echo ok"))
    assert result["exit_code"] == 0


def test_exit_code_nonzero_on_failure():
    if IS_WINDOWS:
        result = run(shell_exec("exit 1", timeout_seconds=5))
    else:
        result = run(shell_exec("exit 1"))
    assert result["exit_code"] != 0


def test_stderr_captured():
    if IS_WINDOWS:
        result = run(shell_exec("echo error message 1>&2"))
    else:
        result = run(shell_exec("echo 'error message' >&2"))
    assert isinstance(result["stderr"], str)


def test_stdout_lines_field():
    if IS_WINDOWS:
        result = run(shell_exec("echo line1 && echo line2"))
    else:
        result = run(shell_exec("echo line1 && echo line2"))
    assert isinstance(result["stdout_lines"], list)
    # Should have at least one non-empty line
    assert len(result["stdout_lines"]) >= 1


def test_pid_returned():
    result = run(shell_exec("echo pid_test"))
    assert result["pid"] is not None
    assert isinstance(result["pid"], int)
    assert result["pid"] > 0


def test_result_contains_all_keys():
    result = run(shell_exec("echo test"))
    assert "stdout" in result
    assert "stderr" in result
    assert "exit_code" in result
    assert "timed_out" in result
    assert "pid" in result
    assert "stdout_lines" in result


# ── Timeout ───────────────────────────────────────────────────────────────────

def test_timeout_kills_process():
    if IS_WINDOWS:
        result = run(shell_exec("ping -n 10 127.0.0.1", timeout_seconds=0.5))
    else:
        result = run(shell_exec("sleep 10", timeout_seconds=0.5))
    assert result["timed_out"] is True
    assert result["exit_code"] == -1


def test_timeout_error_in_stderr():
    if IS_WINDOWS:
        result = run(shell_exec("ping -n 10 127.0.0.1", timeout_seconds=0.5))
    else:
        result = run(shell_exec("sleep 10", timeout_seconds=0.5))
    assert "timed out" in result["stderr"].lower()


def test_short_command_does_not_timeout():
    result = run(shell_exec("echo quick", timeout_seconds=10))
    assert result["timed_out"] is False


# ── Fire and forget ───────────────────────────────────────────────────────────

def test_fire_and_forget_returns_immediately():
    # Background mode now waits a short grace window (~1.5s) so fast crashes
    # surface in the first tool result. For a long-running command the call
    # still returns well before the command completes and reports
    # status: "running" with exit_code: -1 (i.e. unknown / still alive).
    import time as _t
    if IS_WINDOWS:
        cmd = "ping -n 10 127.0.0.1"  # ~10s on Windows
    else:
        cmd = "sleep 10"
    started = _t.monotonic()
    result = run(shell_exec(cmd, wait_for_completion=False))
    elapsed = _t.monotonic() - started
    assert result["pid"] is not None
    # Grace window is ~1.5s; allow generous slack for slow CI but it must
    # be far less than the command's own runtime.
    assert elapsed < 4.0, f"shell_exec returned in {elapsed:.2f}s — should have returned during grace window"
    assert result["status"] == "running"
    assert result["exit_code"] == -1


def test_fire_and_forget_returns_pid():
    if IS_WINDOWS:
        result = run(shell_exec("ping -n 5 127.0.0.1", wait_for_completion=False))
    else:
        result = run(shell_exec("sleep 5", wait_for_completion=False))
    assert isinstance(result["pid"], int)
    assert result["pid"] > 0


# ── Working directory ─────────────────────────────────────────────────────────

def test_working_directory(tmp_path):
    if IS_WINDOWS:
        result = run(shell_exec("cd", working_directory=str(tmp_path)))
        assert str(tmp_path).lower() in result["stdout"].lower()
    else:
        result = run(shell_exec("pwd", working_directory=str(tmp_path)))
        assert str(tmp_path) in result["stdout"]


# ── ToolDefinition ────────────────────────────────────────────────────────────

def test_shell_tool_definition_name():
    assert SHELL_TOOL.name == "shell_exec"


def test_shell_tool_has_required_parameters():
    props = SHELL_TOOL.parameters.get("properties", {})
    assert "command" in props
    required = SHELL_TOOL.parameters.get("required", [])
    assert "command" in required


def test_shell_tool_handler_is_callable():
    assert callable(SHELL_TOOL.handler)
