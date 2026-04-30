"""Tests for chika/tools/variable_tools.py."""
from __future__ import annotations

import asyncio

import pytest

from chika.core.variable_store import VariableStore, VarType
from chika.tools.variable_tools import make_variable_tools


@pytest.fixture
def store():
    return VariableStore()


@pytest.fixture
def tools(store):
    return {t.name: t.handler for t in make_variable_tools(store)}


class TestSetVariable:
    def test_set_text(self, tools):
        result = asyncio.run(tools["set_variable"](name="foo", value="bar"))
        assert result["name"] == "$foo"
        assert result["type"] == "text"
        assert result["size_bytes"] == 3

    def test_set_strips_dollar(self, tools, store):
        asyncio.run(tools["set_variable"](name="$foo", value="val"))
        assert store.get("foo") is not None

    def test_set_json_type(self, tools):
        result = asyncio.run(tools["set_variable"](name="data", value={"x": 1}, var_type="json"))
        assert result["type"] == "json"

    def test_invalid_var_type_falls_back_to_text(self, tools):
        result = asyncio.run(tools["set_variable"](name="x", value="y", var_type="invalid_type"))
        assert result["type"] == "text"

    def test_with_description(self, tools, store):
        asyncio.run(tools["set_variable"](name="note", value="hello", description="a note"))
        var = store.get("note")
        assert var is not None
        assert var.description == "a note"


class TestGetVariable:
    def test_get_existing(self, tools, store):
        store.set("myvar", "myvalue")
        result = asyncio.run(tools["get_variable"](name="myvar"))
        assert result["value"] == "myvalue"
        assert result["name"] == "$myvar"

    def test_get_with_dollar_prefix(self, tools, store):
        store.set("myvar", "myvalue")
        result = asyncio.run(tools["get_variable"](name="$myvar"))
        assert result["value"] == "myvalue"

    def test_get_missing_returns_error(self, tools):
        result = asyncio.run(tools["get_variable"](name="doesnotexist"))
        assert "error" in result


class TestListVariables:
    def test_empty_store(self, tools):
        result = asyncio.run(tools["list_variables"]())
        assert result["variables"] == []

    def test_lists_set_variables(self, tools, store):
        store.set("a", "1")
        store.set("b", "2")
        result = asyncio.run(tools["list_variables"]())
        names = [v["name"] for v in result["variables"]]
        assert "a" in names
        assert "b" in names


class TestDeleteVariable:
    def test_delete_existing(self, tools, store):
        store.set("x", "y")
        result = asyncio.run(tools["delete_variable"](name="x"))
        assert result["deleted"] == "x"
        assert store.get("x") is None

    def test_delete_with_dollar(self, tools, store):
        store.set("x", "y")
        asyncio.run(tools["delete_variable"](name="$x"))
        assert store.get("x") is None

    def test_delete_nonexistent_is_noop(self, tools):
        result = asyncio.run(tools["delete_variable"](name="ghost"))
        assert result["deleted"] == "ghost"
