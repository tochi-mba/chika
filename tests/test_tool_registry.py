"""Tests for ToolRegistry — register, dispatch, unregister, schema generation."""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio

import pytest

from chika.core.tool_registry import ToolDefinition, ToolRegistry


@pytest.fixture
def registry():
    return ToolRegistry()


def make_tool(name, return_val=None):
    async def handler(**kwargs):
        return return_val or {"called": name, "kwargs": kwargs}
    return ToolDefinition(
        name=name,
        description=f"Test tool {name}",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
        handler=handler,
    )


def test_register_and_get(registry):
    t = make_tool("my_tool")
    registry.register(t)
    assert registry.get("my_tool") is not None


def test_get_missing_returns_none(registry):
    assert registry.get("nonexistent") is None


def test_names(registry):
    registry.register(make_tool("a"))
    registry.register(make_tool("b"))
    names = registry.names()
    assert "a" in names
    assert "b" in names


def test_unregister(registry):
    registry.register(make_tool("removable"))
    registry.unregister("removable")
    assert registry.get("removable") is None


def test_unregister_missing_is_safe(registry):
    registry.unregister("nonexistent")  # should not raise


def test_dispatch_calls_handler(registry):
    registry.register(make_tool("echo"))
    result = asyncio.run(
        registry.dispatch("echo", {"x": "test"})
    )
    assert result["called"] == "echo"
    assert result["kwargs"]["x"] == "test"


def test_dispatch_unknown_tool_returns_error(registry):
    result = asyncio.run(
        registry.dispatch("unknown", {})
    )
    assert "error" in result


def test_dispatch_handler_exception_returns_error(registry):
    async def bad_handler(**kwargs):
        raise ValueError("intentional error")
    t = ToolDefinition("bad", "bad tool", {"type": "object", "properties": {}}, bad_handler)
    registry.register(t)
    result = asyncio.run(
        registry.dispatch("bad", {})
    )
    assert "error" in result
    assert "intentional error" in result["error"]


def test_list_for_prompt(registry):
    registry.register(make_tool("tool_x"))
    listing = registry.list_for_prompt()
    assert any(t["name"] == "tool_x" for t in listing)
    assert all("description" in t for t in listing)


def test_openai_schemas(registry):
    registry.register(make_tool("schema_tool"))
    schemas = registry.openai_schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "schema_tool"


def test_sync_handler_also_works(registry):
    def sync_handler(**kwargs):
        return {"sync": True}
    t = ToolDefinition("sync", "sync tool", {"type": "object", "properties": {}}, sync_handler)
    registry.register(t)
    result = asyncio.run(
        registry.dispatch("sync", {})
    )
    assert result["sync"] is True
