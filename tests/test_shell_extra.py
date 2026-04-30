"""Additional tests for shell_tool — ProcessRegistry and background process management."""
import asyncio
import platform
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chika.tools.shell_tool import (
    ProcessRegistry,
    ManagedProcess,
    shell_get_output,
    shell_kill,
    shell_list_processes,
    shell_wait,
    shell_exec,
)

IS_WINDOWS = platform.system() == "Windows"


def run(coro):
    return asyncio.run(coro)


def _make_managed(pid=9999, command="test_cmd", running=True, exit_code=None,
                  stdout_lines=None, stderr_lines=None):
    proc_mock = MagicMock()
    proc_mock.kill = MagicMock()
    managed = ManagedProcess(
        pid=pid,
        command=command,
        process=proc_mock,
        stdout_buf=list(stdout_lines or []),
        stderr_buf=list(stderr_lines or []),
        running=running,
        exit_code=exit_code,
    )
    return managed


@pytest.fixture(autouse=True)
def clean_registry():
    """Remove test pids from the global registry before/after each test."""
    test_pids = [9990, 9991, 9992, 9993, 9994, 9995, 9996, 9997, 9998, 9999]
    for pid in test_pids:
        ProcessRegistry.remove(pid)
    yield
    for pid in test_pids:
        ProcessRegistry.remove(pid)


class TestShellGetOutput:
    def test_unknown_pid_returns_error(self):
        result = run(shell_get_output(9999))
        assert "error" in result
        assert "9999" in result["error"]

    def test_returns_buffered_output(self):
        managed = _make_managed(pid=9991, stdout_lines=["line1", "line2"],
                                 stderr_lines=["err1"])
        ProcessRegistry.register(managed)
        result = run(shell_get_output(9991))
        assert result["stdout"] == "line1\nline2"
        assert result["stderr"] == "err1"
        assert result["stdout_lines"] == ["line1", "line2"]
        assert result["total_stdout_lines"] == 2
        assert result["pid"] == 9991
        assert result["command"] == "test_cmd"

    def test_clear_flag_empties_buffers(self):
        managed = _make_managed(pid=9992, stdout_lines=["line1"])
        ProcessRegistry.register(managed)
        run(shell_get_output(9992, clear=True))
        assert managed.stdout_buf == []

    def test_reports_running_status(self):
        managed = _make_managed(pid=9993, running=True)
        ProcessRegistry.register(managed)
        result = run(shell_get_output(9993))
        assert result["running"] is True

    def test_reports_exit_code(self):
        managed = _make_managed(pid=9994, running=False, exit_code=0)
        ProcessRegistry.register(managed)
        result = run(shell_get_output(9994))
        assert result["exit_code"] == 0


class TestShellKill:
    def test_unknown_pid_returns_error(self):
        result = run(shell_kill(9999))
        assert "error" in result

    def test_kill_running_process(self):
        managed = _make_managed(pid=9995, running=True)
        ProcessRegistry.register(managed)
        result = run(shell_kill(9995))
        assert result["killed"] is True
        assert managed.running is False
        managed.process.kill.assert_called_once()

    def test_kill_already_exited_process(self):
        managed = _make_managed(pid=9996, running=False, exit_code=0)
        ProcessRegistry.register(managed)
        result = run(shell_kill(9996))
        assert result["already_exited"] is True
        assert result["exit_code"] == 0

    def test_kill_exception_returns_error(self):
        managed = _make_managed(pid=9997, running=True)
        managed.process.kill.side_effect = Exception("permission denied")
        ProcessRegistry.register(managed)
        result = run(shell_kill(9997))
        assert "error" in result


class TestShellListProcesses:
    def test_returns_dict_with_processes_key(self):
        result = run(shell_list_processes())
        assert "processes" in result
        assert isinstance(result["processes"], list)

    def test_includes_registered_process(self):
        managed = _make_managed(pid=9998, command="my_command", running=True)
        ProcessRegistry.register(managed)
        result = run(shell_list_processes())
        pids = [p["pid"] for p in result["processes"]]
        assert 9998 in pids


class TestShellWait:
    def test_unknown_pid_returns_error(self):
        result = run(shell_wait(9999))
        assert "error" in result

    def test_timeout_returns_timed_out(self):
        proc_mock = AsyncMock()
        proc_mock.wait = AsyncMock(side_effect=TimeoutError())
        managed = ManagedProcess(
            pid=9990,
            command="slow_cmd",
            process=proc_mock,
            stdout_buf=["partial"],
            stderr_buf=[],
            running=True,
            exit_code=None,
        )
        ProcessRegistry.register(managed)
        result = run(shell_wait(9990, timeout_seconds=0.01))
        assert result["timed_out"] is True
        assert result["running"] is True


class TestShellExecInvalidWorkingDirectory:
    def test_invalid_working_dir_returns_error(self):
        result = run(shell_exec("echo test", working_directory="/this/dir/does/not/exist/xyz"))
        assert "error" in result or result["exit_code"] != 0
