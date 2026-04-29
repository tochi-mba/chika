"""Tests for VariableStore — storage, types, and $ref resolution."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
import pytest
from chika.core.variable_store import VariableStore, VarType


@pytest.fixture
def store():
    return VariableStore()


# ── set / get ────────────────────────────────────────────────────────────────

def test_set_and_get_text(store):
    store.set("name", "hello")
    v = store.get("name")
    assert v is not None
    assert v.value == "hello"
    assert v.type == VarType.TEXT


def test_set_json(store):
    store.set("data", {"key": "val"}, VarType.JSON)
    v = store.get("data")
    assert v.type == VarType.JSON
    assert v.value["key"] == "val"


def test_size_bytes_string(store):
    store.set("s", "hello")
    assert store.get("s").size_bytes == 5


def test_get_value(store):
    store.set("x", 42)
    assert store.get_value("x") == 42


def test_get_value_missing_raises(store):
    with pytest.raises(KeyError):
        store.get_value("nonexistent")


def test_delete(store):
    store.set("temp", "bye")
    store.delete("temp")
    assert store.get("temp") is None


def test_clear(store):
    store.set("a", "1")
    store.set("b", "2")
    store.clear()
    assert store.all() == {}


def test_list_summary(store):
    store.set("foo", "bar")
    summary = store.list_summary()
    assert len(summary) == 1
    assert summary[0]["name"] == "foo"


# ── $ref resolution ──────────────────────────────────────────────────────────

def test_resolve_simple_ref(store):
    store.set("x", "hello")
    assert store.resolve("$x") == "hello"


def test_resolve_nested_dict(store):
    store.set("obj", {"a": {"b": 99}})
    assert store.resolve("$obj.a.b") == 99


def test_resolve_list_index(store):
    store.set("lst", [10, 20, 30])
    assert store.resolve("$lst[1]") == 20


def test_resolve_nonexistent_returns_ref(store):
    assert store.resolve("$missing") == "$missing"


def test_resolve_non_ref_passthrough(store):
    assert store.resolve("hello") == "hello"
    assert store.resolve(42) == 42
    assert store.resolve(None) is None


def test_resolve_dict_recursion(store):
    store.set("cmd", "echo hello")
    result = store.resolve({"command": "$cmd", "timeout": 30})
    assert result == {"command": "echo hello", "timeout": 30}


def test_resolve_list_recursion(store):
    store.set("val", "world")
    assert store.resolve(["hello", "$val"]) == ["hello", "world"]


def test_resolve_nested_ref_in_dict(store):
    store.set("res", {"stdout": "output here", "exit_code": 0})
    assert store.resolve("$res.exit_code") == 0
    assert store.resolve("$res.stdout") == "output here"


def test_resolve_missing_field_returns_ref(store):
    store.set("obj", {"a": 1})
    assert store.resolve("$obj.nonexistent") == "$obj.nonexistent"


def test_set_file(store):
    store.set_file("img", "/path/img.png", b"binary_data", "test image")
    v = store.get("img")
    assert v.type == VarType.BYTES
    assert v.value["path"] == "/path/img.png"
    data = store.get_value("img")
    assert data == b"binary_data"


# ── Concurrency ───────────────────────────────────────────────────────────────

def test_concurrent_writes_no_corruption(store):
    """50 concurrent coroutine writes should all land without corruption."""
    async def write(i):
        store.set(f"key_{i}", f"value_{i}")

    async def run():
        await asyncio.gather(*[write(i) for i in range(50)])

    asyncio.run(run())

    for i in range(50):
        v = store.get(f"key_{i}")
        assert v is not None, f"key_{i} missing"
        assert v.value == f"value_{i}", f"key_{i} corrupted: {v.value}"


# ── Circular reference / depth guard ─────────────────────────────────────────

def test_resolve_depth_guard_no_recursion_error(store):
    """Circular $a → $b → $a must not raise RecursionError."""
    store.set("a", "$b")
    store.set("b", "$a")
    # Should return the value as-is (unresolved) rather than blowing the stack
    try:
        result = store.resolve("$a")
    except RecursionError:
        pytest.fail("RecursionError raised — depth guard not working")
    # result is either the raw string or a resolved value; either is fine


def test_resolve_deep_nesting_no_error(store):
    """A dict nested 25 levels deep must not raise RecursionError."""
    nested = "leaf"
    for _ in range(25):
        nested = {"child": nested}
    store.set("deep", nested)
    try:
        store.resolve("$deep")
    except RecursionError:
        pytest.fail("RecursionError raised on deep nesting")
