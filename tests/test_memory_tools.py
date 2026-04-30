"""Tests for chika/tools/memory_tool.py."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from chika.core.memory_manager import MemoryManager
from chika.tools.memory_tool import make_memory_tools


@pytest.fixture
def engine(tmp_path):
    eng = MagicMock()
    eng._memory = MemoryManager(path=str(tmp_path / "memory.md"))
    eng._active_profile = MagicMock()
    eng._active_profile.name = "default"
    return eng


@pytest.fixture
def tools(engine):
    return {t.name: t.handler for t in make_memory_tools(engine)}


class TestMemoryPersist:
    def test_persist_stores_value(self, tools, engine):
        result = asyncio.run(tools["memory_persist"](key="note", value="hello world"))
        assert result["ok"] is True
        assert result["key"] == "note"
        assert engine._memory.read("note") == "hello world"

    def test_persist_returns_profile(self, tools, engine):
        result = asyncio.run(tools["memory_persist"](key="k", value="v"))
        assert result["profile"] == "default"

    def test_persist_with_ttl(self, tools, engine):
        asyncio.run(tools["memory_persist"](key="temp", value="short-lived", ttl_days=7))
        # Just check it's stored — TTL is stored in metadata
        assert engine._memory.read("temp") == "short-lived"

    def test_persist_no_profile(self, tools, engine):
        engine._active_profile = None
        result = asyncio.run(tools["memory_persist"](key="k", value="v"))
        assert result["profile"] is None


class TestMemoryForget:
    def test_forget_existing_key(self, tools, engine):
        engine._memory.persist("note", "hello")
        result = asyncio.run(tools["memory_forget"](key="note"))
        assert result["ok"] is True
        assert engine._memory.read("note") is None

    def test_forget_nonexistent_is_noop(self, tools):
        result = asyncio.run(tools["memory_forget"](key="ghost"))
        assert result["ok"] is True


class TestMemoryRead:
    def test_read_existing(self, tools, engine):
        engine._memory.persist("mykey", "myvalue")
        result = asyncio.run(tools["memory_read"](key="mykey"))
        assert result["value"] == "myvalue"
        assert result["key"] == "mykey"

    def test_read_missing_returns_error(self, tools):
        result = asyncio.run(tools["memory_read"](key="missing"))
        assert "error" in result


class TestMemoryList:
    def test_empty_returns_empty(self, tools):
        result = asyncio.run(tools["memory_list"]())
        assert result["keys"] == []
        assert result["entries"] == []

    def test_lists_persisted_keys(self, tools, engine):
        engine._memory.persist("a", "1")
        engine._memory.persist("b", "2")
        result = asyncio.run(tools["memory_list"]())
        assert "a" in result["keys"]
        assert "b" in result["keys"]
        assert len(result["entries"]) == 2
