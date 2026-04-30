"""Tests for chika/tools/wait_tool.py."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from chika.tools.wait_tool import wait, WAIT_TOOL


class TestWait:
    def test_returns_waited_seconds(self):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = asyncio.run(wait(1.0))
        assert result["waited_seconds"] == 1.0
        mock_sleep.assert_called_once_with(1.0)

    def test_clamps_negative_to_zero(self):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = asyncio.run(wait(-5.0))
        assert result["waited_seconds"] == 0.0
        mock_sleep.assert_called_once_with(0.0)

    def test_clamps_large_to_300(self):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = asyncio.run(wait(999.0))
        assert result["waited_seconds"] == 300.0
        mock_sleep.assert_called_once_with(300.0)

    def test_exactly_300_allowed(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(wait(300.0))
        assert result["waited_seconds"] == 300.0


class TestWaitTool:
    def test_tool_definition_name(self):
        assert WAIT_TOOL.name == "wait"

    def test_tool_handler_is_wait(self):
        assert WAIT_TOOL.handler is wait
