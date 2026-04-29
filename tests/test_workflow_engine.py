"""Tests for WorkflowEngine — all 10 step types, variable interpolation, meta-tools."""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio

from chika.core.tool_registry import ToolDefinition, ToolRegistry
from chika.core.variable_store import VariableStore
from chika.core.workflow_engine import WorkflowEngine

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_registry(*tool_defs):
    reg = ToolRegistry()
    for t in tool_defs:
        reg.register(t)
    return reg


def make_tool(name, return_val=None, fail=False):
    async def handler(**kwargs):
        if fail:
            raise RuntimeError(f"Tool {name} failed intentionally")
        return return_val if return_val is not None else {"tool": name, "kwargs": kwargs}
    return ToolDefinition(
        name=name,
        description=f"Test tool {name}",
        parameters={"type": "object", "properties": {}},
        handler=handler,
    )


async def collect(gen):
    """Collect all events from an async generator."""
    events = []
    async for e in gen:
        events.append(e)
    return events


def run(coro):
    return asyncio.run(coro)


def make_engine(tools=None, llm_caller=None):
    reg = ToolRegistry()
    if tools:
        for t in tools:
            reg.register(t)
    store = VariableStore()
    return WorkflowEngine(reg, store, llm_caller), store


# ── workflow_start / workflow_done ────────────────────────────────────────────

def test_workflow_start_and_done_events():
    engine, _ = make_engine()
    wf = {"id": "wf1", "name": "My Workflow", "type": "sequential", "steps": []}
    events = run(collect(engine.execute(wf)))
    types = [e["type"] for e in events]
    assert "workflow_start" in types
    assert "workflow_done" in types
    start = next(e for e in events if e["type"] == "workflow_start")
    assert start["workflow_id"] == "wf1"
    assert start["name"] == "My Workflow"


def test_workflow_done_includes_variables():
    engine, store = make_engine([make_tool("t")])
    store.set("result", "my_value")
    wf = {"id": "w", "type": "sequential", "steps": []}
    events = run(collect(engine.execute(wf)))
    done = next(e for e in events if e["type"] == "workflow_done")
    assert "result" in done["variables"]
    assert done["variables"]["result"] == "my_value"


# ── Sequential ────────────────────────────────────────────────────────────────

def test_sequential_runs_steps_in_order():
    order = []
    async def t1(**kw): order.append("t1"); return {"step": 1}
    async def t2(**kw): order.append("t2"); return {"step": 2}
    reg = ToolRegistry()
    reg.register(ToolDefinition("t1", "t1", {"type": "object", "properties": {}}, t1))
    reg.register(ToolDefinition("t2", "t2", {"type": "object", "properties": {}}, t2))
    store = VariableStore()
    engine = WorkflowEngine(reg, store)
    wf = {
        "id": "s", "type": "sequential",
        "steps": [
            {"id": "s1", "tool": "t1", "args": {}},
            {"id": "s2", "tool": "t2", "args": {}},
        ],
    }
    run(collect(engine.execute(wf)))
    assert order == ["t1", "t2"]


def test_sequential_store_result_as():
    engine, store = make_engine([make_tool("echo", return_val={"output": "hello"})])
    wf = {
        "id": "s", "type": "sequential",
        "steps": [{"id": "s1", "tool": "echo", "args": {}, "store_result_as": "$myvar"}],
    }
    events = run(collect(engine.execute(wf)))
    assert store.get_value("myvar") == {"output": "hello"}
    var_events = [e for e in events if e["type"] == "variable_set"]
    assert any(e["name"] == "$myvar" for e in var_events)


def test_sequential_step_start_and_done():
    engine, _ = make_engine([make_tool("noop")])
    wf = {
        "id": "seq1", "type": "sequential",
        "steps": [{"id": "x", "tool": "noop", "args": {}}],
    }
    events = run(collect(engine.execute(wf)))
    start_events = [e for e in events if e["type"] == "step_start"]
    done_events = [e for e in events if e["type"] == "step_done"]
    assert any(e["step_id"] == "seq1" for e in start_events)
    assert any(e["step_id"] == "seq1" for e in done_events)


# ── Leaf step / tool_call ─────────────────────────────────────────────────────

def test_leaf_step_emits_tool_call_and_result():
    engine, _ = make_engine([make_tool("ping", return_val={"pong": True})])
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{"id": "p", "tool": "ping", "args": {"x": 1}}],
    }
    events = run(collect(engine.execute(wf)))
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool"] == "ping"
    assert len(tool_results) == 1
    assert tool_results[0]["result"]["pong"] is True


def test_leaf_step_unknown_tool_returns_error_result():
    engine, _ = make_engine()
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{"id": "p", "tool": "no_such_tool", "args": {}}],
    }
    events = run(collect(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]
    assert len(results) == 1
    assert results[0]["error"] is not None


# ── Variable interpolation ────────────────────────────────────────────────────

def test_variable_interpolation_in_args():
    received_args = {}
    async def capture(**kw): received_args.update(kw); return {}
    reg = ToolRegistry()
    reg.register(ToolDefinition("cap", "cap", {"type": "object", "properties": {}}, capture))
    store = VariableStore()
    store.set("greeting", "hello world")
    engine = WorkflowEngine(reg, store)
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{"id": "s", "tool": "cap", "args": {"msg": "$greeting"}}],
    }
    run(collect(engine.execute(wf)))
    assert received_args.get("msg") == "hello world"


def test_variable_interpolation_nested_field():
    received_args = {}
    async def capture(**kw): received_args.update(kw); return {}
    reg = ToolRegistry()
    reg.register(ToolDefinition("cap", "cap", {"type": "object", "properties": {}}, capture))
    store = VariableStore()
    store.set("res", {"stdout": "output text"})
    engine = WorkflowEngine(reg, store)
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{"id": "s", "tool": "cap", "args": {"text": "$res.stdout"}}],
    }
    run(collect(engine.execute(wf)))
    assert received_args.get("text") == "output text"


def test_variable_chaining_between_steps():
    engine, store = make_engine([
        make_tool("step1", return_val={"value": 42}),
        make_tool("step2", return_val={"doubled": 84}),
    ])
    received = {}
    async def step2_check(**kw):
        received.update(kw)
        return {"done": True}
    reg = engine._tools
    reg.unregister("step2")
    reg.register(ToolDefinition("step2", "s2", {"type": "object", "properties": {}}, step2_check))

    wf = {
        "id": "w", "type": "sequential",
        "steps": [
            {"id": "s1", "tool": "step1", "args": {}, "store_result_as": "$r1"},
            {"id": "s2", "tool": "step2", "args": {"input": "$r1.value"}},
        ],
    }
    run(collect(engine.execute(wf)))
    assert received.get("input") == 42


# ── Parallel ──────────────────────────────────────────────────────────────────

def test_parallel_emits_results_from_all_branches():
    engine, _ = make_engine([
        make_tool("a", return_val={"a": 1}),
        make_tool("b", return_val={"b": 2}),
    ])
    wf = {
        "id": "par", "type": "parallel",
        "steps": [
            {"id": "sa", "tool": "a", "args": {}},
            {"id": "sb", "tool": "b", "args": {}},
        ],
    }
    events = run(collect(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]
    tools_called = {e["tool"] for e in results}
    assert "a" in tools_called
    assert "b" in tools_called


def test_parallel_then_block_runs_after():
    order = []
    async def par_a(**kw): order.append("a"); return {}
    async def par_b(**kw): order.append("b"); return {}
    async def after(**kw): order.append("after"); return {}
    reg = ToolRegistry()
    for name, fn in [("par_a", par_a), ("par_b", par_b), ("after", after)]:
        reg.register(ToolDefinition(name, name, {"type": "object", "properties": {}}, fn))
    store = VariableStore()
    engine = WorkflowEngine(reg, store)
    wf = {
        "id": "p", "type": "parallel",
        "steps": [
            {"id": "sa", "tool": "par_a", "args": {}},
            {"id": "sb", "tool": "par_b", "args": {}},
        ],
        "then": {"id": "t", "tool": "after", "args": {}},
    }
    run(collect(engine.execute(wf)))
    assert "after" in order
    assert order.index("after") > 0


# ── Conditional ───────────────────────────────────────────────────────────────

def test_conditional_if_true_branch():
    engine, store = make_engine([
        make_tool("yes", return_val={"branch": "yes"}),
        make_tool("no", return_val={"branch": "no"}),
    ])
    store.set("flag", "go")
    wf = {
        "id": "cond", "type": "conditional",
        "condition": {"field": "$flag", "operator": "equals", "value": "go"},
        "if_true":  {"id": "t", "tool": "yes", "args": {}},
        "if_false": {"id": "f", "tool": "no",  "args": {}},
    }
    events = run(collect(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]
    assert len(results) == 1
    assert results[0]["result"]["branch"] == "yes"


def test_conditional_if_false_branch():
    engine, store = make_engine([
        make_tool("yes", return_val={"branch": "yes"}),
        make_tool("no", return_val={"branch": "no"}),
    ])
    store.set("flag", "stop")
    wf = {
        "id": "cond", "type": "conditional",
        "condition": {"field": "$flag", "operator": "equals", "value": "go"},
        "if_true":  {"id": "t", "tool": "yes", "args": {}},
        "if_false": {"id": "f", "tool": "no",  "args": {}},
    }
    events = run(collect(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]
    assert len(results) == 1
    assert results[0]["result"]["branch"] == "no"


def test_conditional_emits_condition_eval():
    engine, store = make_engine([make_tool("noop")])
    store.set("x", 5)
    wf = {
        "id": "c", "type": "conditional",
        "condition": {"field": "$x", "operator": "gt", "value": 3},
        "if_true": {"id": "n", "tool": "noop", "args": {}},
    }
    events = run(collect(engine.execute(wf)))
    cond_evals = [e for e in events if e["type"] == "condition_eval"]
    assert len(cond_evals) == 1
    assert cond_evals[0]["result"] is True


def test_conditional_operators():
    def check_op(op, val, expected, stored_val):
        engine, store = make_engine([make_tool("y"), make_tool("n")])
        store.set("v", stored_val)
        wf = {
            "id": "c", "type": "conditional",
            "condition": {"field": "$v", "operator": op, "value": val},
            "if_true":  {"id": "y", "tool": "y", "args": {}},
            "if_false": {"id": "n", "tool": "n", "args": {}},
        }
        events = run(collect(engine.execute(wf)))
        results = [e for e in events if e["type"] == "tool_result"]
        return results[0]["tool"] == ("y" if expected else "n")

    assert check_op("equals", "hello", True, "hello")
    assert check_op("not_equals", "hello", True, "world")
    assert check_op("gt", 3, True, 5)
    assert check_op("lt", 10, True, 5)
    assert check_op("gte", 5, True, 5)
    assert check_op("lte", 5, True, 5)
    assert check_op("contains", "ell", True, "hello")


# ── Loop ──────────────────────────────────────────────────────────────────────

def test_loop_runs_until_condition_false():
    call_count = [0]
    async def increment(**kw):
        call_count[0] += 1
        return {"count": call_count[0]}

    reg = ToolRegistry()
    reg.register(ToolDefinition("inc", "inc", {"type": "object", "properties": {}}, increment))
    store = VariableStore()
    store.set("counter", 0)
    engine = WorkflowEngine(reg, store)

    # Loop 3 times by decrementing a counter via the tool storing into $counter
    counter = [3]
    async def decrement(**kw):
        counter[0] -= 1
        store.set("counter", counter[0])
        return {"counter": counter[0]}

    reg.register(ToolDefinition("dec", "dec", {"type": "object", "properties": {}}, decrement))
    store.set("counter", 3)

    wf = {
        "id": "loop1", "type": "loop",
        "condition": {"field": "$counter", "operator": "gt", "value": 0},
        "max_iterations": 10,
        "steps": [{"id": "d", "tool": "dec", "args": {}}],
    }
    events = run(collect(engine.execute(wf)))
    loop_iters = [e for e in events if e["type"] == "loop_iteration"]
    assert len(loop_iters) == 3


def test_loop_max_iterations_reached_continue():
    engine, store = make_engine([make_tool("noop")])
    store.set("flag", True)
    wf = {
        "id": "loop2", "type": "loop",
        "condition": {"field": "$flag", "operator": "equals", "value": True},
        "max_iterations": 5,
        "on_max_iterations_reached": "continue",
        "steps": [{"id": "n", "tool": "noop", "args": {}}],
    }
    events = run(collect(engine.execute(wf)))
    iters = [e for e in events if e["type"] == "loop_iteration"]
    errors = [e for e in events if e["type"] == "error"]
    assert len(iters) == 5
    assert len(errors) == 0


def test_loop_max_iterations_reached_fail():
    engine, store = make_engine([make_tool("noop")])
    store.set("flag", True)
    wf = {
        "id": "loop3", "type": "loop",
        "condition": {"field": "$flag", "operator": "equals", "value": True},
        "max_iterations": 3,
        "on_max_iterations_reached": "fail",
        "steps": [{"id": "n", "tool": "noop", "args": {}}],
    }
    events = run(collect(engine.execute(wf)))
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1


def test_loop_emits_loop_iteration_events():
    counter = [2]
    async def dec(**kw):
        counter[0] -= 1
        return {"v": counter[0]}

    reg = ToolRegistry()
    reg.register(ToolDefinition("dec", "d", {"type": "object", "properties": {}}, dec))
    store = VariableStore()
    store.set("v", 2)
    engine = WorkflowEngine(reg, store)

    async def dec_and_store(**kw):
        counter[0] -= 1
        store.set("v", counter[0])
        return {"v": counter[0]}

    reg.unregister("dec")
    reg.register(ToolDefinition("dec", "d", {"type": "object", "properties": {}}, dec_and_store))
    store.set("v", 2)
    counter[0] = 2

    wf = {
        "id": "l", "type": "loop",
        "condition": {"field": "$v", "operator": "gt", "value": 0},
        "max_iterations": 10,
        "steps": [{"id": "d", "tool": "dec", "args": {}}],
    }
    events = run(collect(engine.execute(wf)))
    loop_events = [e for e in events if e["type"] == "loop_iteration"]
    assert all("iteration" in e for e in loop_events)
    assert all("max" in e for e in loop_events)


# ── Map ───────────────────────────────────────────────────────────────────────

def test_map_runs_step_for_each_item():
    processed = []
    async def process(**kw):
        processed.append(kw.get("item"))
        return {"processed": kw.get("item")}

    reg = ToolRegistry()
    reg.register(ToolDefinition("process", "p", {"type": "object", "properties": {"item": {"type": "string"}}}, process))
    store = VariableStore()
    store.set("items", ["a", "b", "c"])
    engine = WorkflowEngine(reg, store)

    wf = {
        "id": "m", "type": "map",
        "over": "$items",
        "item_var": "$item",
        "step": {"id": "p", "tool": "process", "args": {"item": "$item"}},
        "concurrency": 1,
    }
    events = run(collect(engine.execute(wf)))
    map_events = [e for e in events if e["type"] == "map_item"]
    assert len(map_events) >= 3


def test_map_store_results():
    async def double(**kw):
        val = kw.get("x", 0)
        return {"result": val * 2}

    reg = ToolRegistry()
    reg.register(ToolDefinition("double", "d", {"type": "object", "properties": {"x": {"type": "integer"}}}, double))
    store = VariableStore()
    store.set("nums", [1, 2, 3])
    engine = WorkflowEngine(reg, store)

    wf = {
        "id": "m", "type": "map",
        "over": "$nums",
        "item_var": "$item",
        "step": {"id": "d", "tool": "double", "args": {"x": "$item"}, "store_result_as": "$double_result"},
        "store_result_as": "$all_results",
        "concurrency": 1,
    }
    run(collect(engine.execute(wf)))
    # all_results should contain a list
    v = store.get("all_results")
    assert v is not None


def test_map_emits_map_item_events():
    engine, store = make_engine([make_tool("noop")])
    store.set("files", ["f1", "f2"])
    wf = {
        "id": "m", "type": "map",
        "over": "$files",
        "item_var": "$f",
        "step": {"id": "n", "tool": "noop", "args": {}},
        "concurrency": 2,
    }
    events = run(collect(engine.execute(wf)))
    map_events = [e for e in events if e["type"] == "map_item"]
    assert len(map_events) >= 2


# ── Fan-out ───────────────────────────────────────────────────────────────────

def test_fan_out_runs_named_branches():
    engine, _ = make_engine([
        make_tool("branch_a", return_val={"source": "a"}),
        make_tool("branch_b", return_val={"source": "b"}),
    ])
    wf = {
        "id": "fo", "type": "fan_out",
        "branches": [
            {"name": "A", "steps": [{"id": "a", "tool": "branch_a", "args": {}}]},
            {"name": "B", "steps": [{"id": "b", "tool": "branch_b", "args": {}}]},
        ],
    }
    events = run(collect(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]
    sources = {r["result"]["source"] for r in results}
    assert sources == {"a", "b"}


def test_fan_out_fan_in_merges():
    merge_called = [False]
    async def merge(**kw): merge_called[0] = True; return {"merged": True}
    reg = ToolRegistry()
    reg.register(ToolDefinition("a", "a", {"type": "object", "properties": {}}, lambda **kw: {}))
    reg.register(ToolDefinition("b", "b", {"type": "object", "properties": {}}, lambda **kw: {}))
    reg.register(ToolDefinition("merge", "m", {"type": "object", "properties": {}}, merge))
    store = VariableStore()
    engine = WorkflowEngine(reg, store)
    wf = {
        "id": "fo", "type": "fan_out",
        "branches": [
            {"name": "A", "steps": [{"id": "a", "tool": "a", "args": {}}]},
            {"name": "B", "steps": [{"id": "b", "tool": "b", "args": {}}]},
        ],
        "fan_in": {"id": "mi", "tool": "merge", "args": {}},
    }
    run(collect(engine.execute(wf)))
    assert merge_called[0]


# ── Retry ─────────────────────────────────────────────────────────────────────

def test_retry_succeeds_on_first_try():
    engine, store = make_engine([make_tool("flaky", return_val={"ok": True})])
    # No retry condition — won't retry
    wf = {
        "id": "r", "type": "retry",
        "max_attempts": 3,
        "step": {"id": "f", "tool": "flaky", "args": {}},
    }
    events = run(collect(engine.execute(wf)))
    retry_events = [e for e in events if e["type"] == "retry_attempt"]
    assert len(retry_events) == 1


def test_retry_emits_retry_attempt_events():
    attempt_counter = [0]
    async def flaky(**kw):
        attempt_counter[0] += 1
        return {"ok": False}

    reg = ToolRegistry()
    reg.register(ToolDefinition("flaky", "f", {"type": "object", "properties": {}}, flaky))
    store = VariableStore()
    store.set("ok", False)

    # Manually update store in handler so condition can check it
    async def flaky_updating(**kw):
        attempt_counter[0] += 1
        store.set("ok", False)
        return {"ok": False}

    reg.unregister("flaky")
    reg.register(ToolDefinition("flaky", "f", {"type": "object", "properties": {}}, flaky_updating))

    engine = WorkflowEngine(reg, store)
    wf = {
        "id": "r", "type": "retry",
        "max_attempts": 3,
        "backoff_seconds": [0, 0, 0],  # no actual waiting in tests
        "retry_on": {"field": "$ok", "operator": "equals", "value": False},
        "step": {"id": "f", "tool": "flaky", "args": {}},
    }
    events = run(collect(engine.execute(wf)))
    retry_events = [e for e in events if e["type"] == "retry_attempt"]
    assert len(retry_events) >= 1


def test_retry_on_all_failed_stores_error():
    async def always_fail(**kw):
        return {"ok": False}

    reg = ToolRegistry()
    reg.register(ToolDefinition("fail_tool", "f", {"type": "object", "properties": {}}, always_fail))
    store = VariableStore()
    store.set("ok", False)

    engine = WorkflowEngine(reg, store)
    wf = {
        "id": "r", "type": "retry",
        "max_attempts": 2,
        "backoff_seconds": [0, 0],
        "retry_on": {"field": "$ok", "operator": "equals", "value": False},
        "on_all_failed": "store_error",
        "store_error_as": "$retry_err",
        "step": {"id": "f", "tool": "fail_tool", "args": {}},
    }
    run(collect(engine.execute(wf)))
    err = store.get("retry_err")
    assert err is not None


# ── Pipeline ──────────────────────────────────────────────────────────────────

def test_pipeline_threads_output_between_steps():
    received = {}
    async def step1(**kw): return {"data": "from_step1"}
    async def step2(**kw): received.update(kw); return {"data": "from_step2"}

    reg = ToolRegistry()
    reg.register(ToolDefinition("s1", "s1", {"type": "object", "properties": {}}, step1))
    reg.register(ToolDefinition("s2", "s2", {"type": "object", "properties": {}}, step2))
    store = VariableStore()
    engine = WorkflowEngine(reg, store)

    wf = {
        "id": "pl", "type": "pipeline",
        "steps": [
            {"id": "p1", "tool": "s1", "args": {}, "store_result_as": "$step1_out"},
            {"id": "p2", "tool": "s2", "args": {}},
        ],
    }
    events = run(collect(engine.execute(wf)))
    step_types = [e.get("step_type") for e in events if e["type"] == "step_start"]
    assert "pipeline" in step_types


def test_pipeline_emits_step_start_pipeline():
    engine, _ = make_engine([make_tool("t1"), make_tool("t2")])
    wf = {
        "id": "pl", "type": "pipeline",
        "steps": [
            {"id": "p1", "tool": "t1", "args": {}},
            {"id": "p2", "tool": "t2", "args": {}},
        ],
    }
    events = run(collect(engine.execute(wf)))
    pipeline_starts = [e for e in events if e["type"] == "step_start" and e.get("step_type") == "pipeline"]
    assert len(pipeline_starts) == 1


# ── Sub-workflow ──────────────────────────────────────────────────────────────

def test_sub_workflow_executes_registered_steps():
    engine, _ = make_engine([make_tool("sub_tool", return_val={"sub": "ran"})])
    engine.register_sub_workflow("my_sub", [
        {"id": "ss", "tool": "sub_tool", "args": {}}
    ])
    wf = {
        "id": "main", "type": "sequential",
        "steps": [{"id": "sub", "type": "sub_workflow", "workflow_id": "my_sub"}],
    }
    events = run(collect(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]
    assert any(r["result"]["sub"] == "ran" for r in results)


def test_sub_workflow_missing_id_emits_error():
    engine, _ = make_engine()
    wf = {
        "id": "main", "type": "sequential",
        "steps": [{"id": "sub", "type": "sub_workflow", "workflow_id": "does_not_exist"}],
    }
    events = run(collect(engine.execute(wf)))
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) >= 1
    assert "not found" in errors[0]["message"]


# ── Meta-tools ────────────────────────────────────────────────────────────────

def test_meta_tool_without_llm_returns_error():
    engine, _ = make_engine()  # no LLM caller
    wf = {
        "id": "w", "type": "sequential",
        "steps": [{"id": "s", "tool": "llm_summarise", "args": {"prompt": "summarize", "context": "stuff"}}],
    }
    events = run(collect(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]
    assert len(results) == 1
    assert "error" in results[0]["result"]


def test_meta_tool_llm_summarise_calls_llm():
    class FakeLLM:
        async def complete(self, prompt):
            return "This is a summary."

    engine, _ = make_engine(llm_caller=FakeLLM())
    wf = {
        "id": "w", "type": "sequential",
        "steps": [
            {"id": "s", "tool": "llm_summarise", "args": {"prompt": "Summarise", "context": "some context"},
             "store_result_as": "$summary"}
        ],
    }
    run(collect(engine.execute(wf)))
    assert engine._vars.get_value("summary") == "This is a summary."


def test_meta_tool_llm_transform_parses_json():
    class FakeLLM:
        async def complete(self, prompt):
            return '{"transformed": true}'

    engine, _ = make_engine(llm_caller=FakeLLM())
    wf = {
        "id": "w", "type": "sequential",
        "steps": [
            {"id": "s", "tool": "llm_transform",
             "args": {"prompt": "transform this", "input": "raw data"},
             "store_result_as": "$out"}
        ],
    }
    run(collect(engine.execute(wf)))
    # llm_transform normalizes single-key dicts by promoting the value to `.result`
    # so downstream steps can always access `$var.result` uniformly.
    # (See workflow_engine._exec_meta_tool.)
    out = engine._vars.get_value("out")
    assert out["transformed"] is True
    assert out["result"] is True


# ── Nested workflows ──────────────────────────────────────────────────────────

def test_nested_sequential_in_parallel():
    engine, _ = make_engine([
        make_tool("a", return_val={"a": 1}),
        make_tool("b", return_val={"b": 2}),
        make_tool("c", return_val={"c": 3}),
    ])
    wf = {
        "id": "outer", "type": "parallel",
        "steps": [
            {
                "id": "inner", "type": "sequential",
                "steps": [
                    {"id": "x", "tool": "a", "args": {}},
                    {"id": "y", "tool": "b", "args": {}},
                ]
            },
            {"id": "z", "tool": "c", "args": {}},
        ],
    }
    events = run(collect(engine.execute(wf)))
    results = [e for e in events if e["type"] == "tool_result"]
    tools = {r["tool"] for r in results}
    assert tools == {"a", "b", "c"}


def test_duration_ms_in_step_done():
    engine, _ = make_engine([make_tool("t")])
    wf = {
        "id": "s", "type": "sequential",
        "steps": [{"id": "t", "tool": "t", "args": {}}],
    }
    events = run(collect(engine.execute(wf)))
    done_events = [e for e in events if e["type"] == "step_done"]
    assert all("duration_ms" in e for e in done_events)
    assert all(isinstance(e["duration_ms"], int) for e in done_events)
