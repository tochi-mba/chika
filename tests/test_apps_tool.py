"""Tests for chika/tools/apps_tool.py."""
from __future__ import annotations

import asyncio
import platform
from unittest.mock import MagicMock, patch

from chika.tools.apps_tool import app_open, APP_OPEN_TOOL


def run(coro):
    return asyncio.run(coro)


class TestAppOpen:
    def test_windows_success(self):
        with patch("platform.system", return_value="Windows"), \
             patch("os.startfile"):
            result = run(app_open("notepad"))
        assert result["success"] is True
        assert result["opened"] == "notepad"
        assert result["platform"] == "Windows"

    def test_darwin_success(self):
        with patch("platform.system", return_value="Darwin"), \
             patch("subprocess.Popen") as mock_popen:
            result = run(app_open("Safari"))
        assert result["success"] is True
        assert result["opened"] == "Safari"
        assert result["platform"] == "Darwin"
        mock_popen.assert_called_once_with(["open", "Safari"])

    def test_linux_success(self):
        with patch("platform.system", return_value="Linux"), \
             patch("subprocess.Popen") as mock_popen:
            result = run(app_open("firefox"))
        assert result["success"] is True
        mock_popen.assert_called_once_with(["xdg-open", "firefox"])

    def test_exception_returns_error(self):
        with patch("platform.system", return_value="Darwin"), \
             patch("subprocess.Popen", side_effect=Exception("not found")):
            result = run(app_open("nonexistent_app"))
        assert result["success"] is False
        assert "error" in result
        assert result["opened"] == "nonexistent_app"


class TestAppOpenToolDefinition:
    def test_name(self):
        assert APP_OPEN_TOOL.name == "app_open"

    def test_requires_approval_false(self):
        assert APP_OPEN_TOOL.requires_approval is False
