"""Additional workflow engine tests — conditional operators and edge cases."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio

from chika.core.tool_registry import ToolDefinition, ToolRegistry
from chika.core.variable_store import VariableStore
from chika.core.workflow_engine import WorkflowEngine


def run(coro):
    return asyncio.run(coro)


async def collect(gen):
    events = []
    async for e in gen:
        events.append(e)
    return events


def make_engine(tools=None):
    reg = ToolRegistry()
    if tools:
        for t in tools:
            reg.register(t)
    store = VariableStore()
    return WorkflowEngine(reg, store), store


def make_tool(name, return_val=None):
    async def handler(**kwargs):
        return return_val if return_val is not None else {"tool": name}
    return ToolDefinition(
        name=name, description=f"Test {name}",
        parameters={"type": "object", "properties": {}},
        handler=handler,
    )


# ── is_null / not_null operators ─────────────────────────────────────────────

def test_condition_is_null_true_when_var_is_none():
    engine, store = make_engine([make_tool("t")])
    store.set("null_var", None)
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "cond1", "type": "conditional",
            "condition": {"field": "$null_var", "operator": "is_null"},
            "if_true": {"id": "leaf1", "tool": "t", "args": {}},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert len(cond_events) == 1
    assert cond_events[0]["result"] is True


def test_condition_is_null_false_when_var_set():
    engine, store = make_engine([make_tool("t")])
    store.set("x", "some_value")
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "cond1", "type": "conditional",
            "condition": {"field": "$x", "operator": "is_null"},
            "if_false": {"id": "leaf1", "tool": "t", "args": {}},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is False


def test_condition_not_null_true_when_var_set():
    engine, store = make_engine([make_tool("t")])
    store.set("y", "present")
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "cond1", "type": "conditional",
            "condition": {"field": "$y", "operator": "not_null"},
            "if_true": {"id": "leaf1", "tool": "t", "args": {}},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is True


def test_condition_not_null_false_when_var_is_none():
    engine, store = make_engine([make_tool("t")])
    store.set("none_var", None)
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "cond1", "type": "conditional",
            "condition": {"field": "$none_var", "operator": "not_null"},
            "if_false": {"id": "leaf1", "tool": "t", "args": {}},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is False


# ── Numeric comparison operators ──────────────────────────────────────────────

def test_condition_gt_true():
    engine, store = make_engine()
    store.set("count", 5)
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "cond1", "type": "conditional",
            "condition": {"field": "$count", "operator": "gt", "value": 3},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is True


def test_condition_gt_false():
    engine, store = make_engine()
    store.set("count", 2)
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "cond1", "type": "conditional",
            "condition": {"field": "$count", "operator": "gt", "value": 3},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is False


def test_condition_lt_true():
    engine, store = make_engine()
    store.set("n", 1)
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "c", "type": "conditional",
            "condition": {"field": "$n", "operator": "lt", "value": 10},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is True


def test_condition_gte_true_on_equal():
    engine, store = make_engine()
    store.set("n", 5)
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "c", "type": "conditional",
            "condition": {"field": "$n", "operator": "gte", "value": 5},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is True


def test_condition_lte_true_on_equal():
    engine, store = make_engine()
    store.set("n", 5)
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "c", "type": "conditional",
            "condition": {"field": "$n", "operator": "lte", "value": 5},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is True


def test_condition_numeric_non_numeric_returns_false():
    engine, store = make_engine()
    store.set("n", "not_a_number")
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "c", "type": "conditional",
            "condition": {"field": "$n", "operator": "gt", "value": 1},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is False


# ── contains / in / not_in operators ─────────────────────────────────────────

def test_condition_contains():
    engine, store = make_engine()
    store.set("msg", "hello world")
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "c", "type": "conditional",
            "condition": {"field": "$msg", "operator": "contains", "value": "world"},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is True


def test_condition_in():
    engine, store = make_engine()
    store.set("color", "red")
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "c", "type": "conditional",
            "condition": {"field": "$color", "operator": "in", "value": ["red", "blue"]},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is True


def test_condition_not_in():
    engine, store = make_engine()
    store.set("color", "green")
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "c", "type": "conditional",
            "condition": {"field": "$color", "operator": "not_in", "value": ["red", "blue"]},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is True


def test_condition_unknown_operator_returns_false():
    engine, store = make_engine()
    store.set("x", "y")
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{
            "id": "c", "type": "conditional",
            "condition": {"field": "$x", "operator": "fancy_op", "value": "y"},
        }],
    }
    events = run(collect(engine.execute(wf)))
    cond_events = [e for e in events if e["type"] == "condition_eval"]
    assert cond_events[0]["result"] is False
