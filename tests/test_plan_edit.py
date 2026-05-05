"""Tests for ``plan_edit`` — the structured patch tool.

Covers:
- Each op type applied in isolation (set_goal, set_task_status, etc.)
- Multiple ops in one call apply in order
- A failing op doesn't stop subsequent ops; per-op result records the failure
- Substring (fingerprint) replace finds + replaces; reports not_found cleanly
- Sub-task handling: add_subtask, parent-status auto-roll-up after edits
- Defensive errors: no plan yet, empty operations list, unknown op kind
"""
from __future__ import annotations

import asyncio

from chika.core.variable_store import VariableStore
from chika.skills.plan_skill import _make_plan_tools


def _build():
    vs = VariableStore()
    (plan_set, plan_update, plan_get, plan_add, plan_remove, plan_edit,
     *_extra) = _make_plan_tools(vs)
    asyncio.run(plan_set(
        goal="Build a tic-tac-toe game in vanilla JS",
        requirements=["No build step", "Two-player only"],
        tasks=[
            {"id": "t1", "text": "HTML scaffold"},
            {"id": "t2", "text": "Game logic", "subtasks": [
                {"id": "t2.1", "text": "Win detection"},
                {"id": "t2.2", "text": "Turn handling"},
            ]},
            {"id": "t3", "text": "Styles"},
        ],
    ))
    return vs, plan_edit, plan_get


# ── Per-op behaviour ─────────────────────────────────────────────────────

def test_set_goal_replaces_the_aim():
    _, plan_edit, plan_get = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "set_goal", "value": "Build a TIC-TAC-TOE in TypeScript instead"},
    ]))
    assert out["applied"] == 1
    assert out["plan"]["goal"] == "Build a TIC-TAC-TOE in TypeScript instead"


def test_add_and_remove_requirement():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "add_requirement", "value": "Must work offline"},
        {"op": "remove_requirement", "match": "Two-player"},
    ]))
    assert out["applied"] == 2
    reqs = out["plan"]["requirements"]
    assert "Must work offline" in reqs
    assert not any("Two-player" in r for r in reqs)


def test_set_task_text_and_status_anywhere_in_tree():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "set_task_text", "task_id": "t2.1", "value": "Win + draw detection"},
        {"op": "set_task_status", "task_id": "t1", "value": "done"},
    ]))
    assert out["applied"] == 2
    tasks = out["plan"]["tasks"]
    t1 = next(t for t in tasks if t["id"] == "t1")
    t2 = next(t for t in tasks if t["id"] == "t2")
    t2_1 = next(s for s in t2["subtasks"] if s["id"] == "t2.1")
    assert t1["status"] == "done"
    assert t2_1["text"] == "Win + draw detection"


def test_add_task_at_end_and_after_id():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "add_task", "task": "Deploy to GitHub Pages"},
        {"op": "add_task", "after_id": "t1",
         "task": {"text": "CSS reset"}},
    ]))
    assert out["applied"] == 2
    texts = [t["text"] for t in out["plan"]["tasks"]]
    assert texts.index("CSS reset") == 1   # right after t1
    assert texts[-1] == "Deploy to GitHub Pages"


def test_add_subtask_appends_under_parent():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "add_subtask", "parent_id": "t2",
         "task": {"text": "AI opponent"}},
    ]))
    assert out["applied"] == 1
    t2 = next(t for t in out["plan"]["tasks"] if t["id"] == "t2")
    assert any(s["text"] == "AI opponent" for s in t2["subtasks"])


def test_remove_task_drops_from_anywhere():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "remove_task", "task_id": "t2.2"},
        {"op": "remove_task", "task_id": "t3"},
    ]))
    assert out["applied"] == 2
    tasks = out["plan"]["tasks"]
    assert all(t["id"] != "t3" for t in tasks)
    t2 = next(t for t in tasks if t["id"] == "t2")
    assert all(s["id"] != "t2.2" for s in t2["subtasks"])


# ── Fingerprint find_replace ─────────────────────────────────────────────

def test_replace_in_field_swaps_substring_in_goal():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "replace_in_field", "field": "goal",
         "find": "vanilla JS", "replace": "TypeScript"},
    ]))
    assert out["applied"] == 1
    assert "TypeScript" in out["plan"]["goal"]
    assert "vanilla JS" not in out["plan"]["goal"]


def test_replace_in_task_swaps_substring_in_task_text():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "replace_in_task", "task_id": "t2.1",
         "find": "Win detection", "replace": "Win/draw detection"},
    ]))
    assert out["applied"] == 1
    plan = out["plan"]
    t2 = next(t for t in plan["tasks"] if t["id"] == "t2")
    t2_1 = next(s for s in t2["subtasks"] if s["id"] == "t2.1")
    assert t2_1["text"] == "Win/draw detection"


def test_replace_reports_not_found_cleanly():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "replace_in_field", "field": "goal",
         "find": "NON_EXISTENT_PHRASE", "replace": "X"},
    ]))
    assert out["applied"] == 0
    assert out["failed"] == 1
    assert out["results"][0]["error"] == "not_found"


# ── Multi-op + failure isolation ─────────────────────────────────────────

def test_failing_op_doesnt_block_subsequent_ops():
    """One bad op in the middle should not halt the rest."""
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "set_goal", "value": "Step 1: ok"},
        {"op": "set_task_text", "task_id": "DOES_NOT_EXIST", "value": "x"},
        {"op": "set_goal", "value": "Step 3: ok"},
    ]))
    assert out["applied"] == 2
    assert out["failed"] == 1
    assert out["plan"]["goal"] == "Step 3: ok"


def test_unknown_op_returns_clean_error():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "set_goal", "value": "ok"},
        {"op": "ENTIRELY_FICTIONAL_OP", "task_id": "t1"},
    ]))
    assert out["applied"] == 1
    assert any("unknown op" in (r.get("error") or "")
               for r in out["results"] if not r.get("ok"))


# ── Parent-status auto-roll-up after edits ───────────────────────────────

def test_marking_all_subtasks_done_promotes_parent_to_done():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "set_task_status", "task_id": "t2.1", "value": "done"},
        {"op": "set_task_status", "task_id": "t2.2", "value": "done"},
    ]))
    assert out["applied"] == 2
    t2 = next(t for t in out["plan"]["tasks"] if t["id"] == "t2")
    assert t2["status"] == "done", "parent must auto-promote when every leaf is done"


def test_one_subtask_in_progress_promotes_parent_to_in_progress():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[
        {"op": "set_task_status", "task_id": "t2.1", "value": "in_progress"},
    ]))
    t2 = next(t for t in out["plan"]["tasks"] if t["id"] == "t2")
    assert t2["status"] == "in_progress"


# ── Defensive ────────────────────────────────────────────────────────────

def test_plan_edit_errors_when_no_plan_active():
    vs = VariableStore()
    plan_edit = _make_plan_tools(vs)[5]
    out = asyncio.run(plan_edit(operations=[
        {"op": "set_goal", "value": "x"},
    ]))
    assert "error" in out
    assert "no plan" in out["error"].lower()


def test_plan_edit_errors_on_empty_operations():
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(operations=[]))
    assert "error" in out


def test_plan_edit_accepts_alias_kwarg_for_operations():
    """LLMs sometimes type ``ops=`` or ``patches=`` instead of ``operations=``.
    The handler should resolve those aliases."""
    _, plan_edit, _ = _build()
    out = asyncio.run(plan_edit(ops=[
        {"op": "set_goal", "value": "via alias"},
    ]))
    assert out["applied"] == 1
    assert out["plan"]["goal"] == "via alias"
