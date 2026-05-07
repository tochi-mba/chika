"""Auto-archive contract — when ``plan_set`` replaces an existing plan,
the prior plan moves to ``$plan_archive`` automatically. Tests cover
every edge case the user asked us to think through:

  - First plan ever (nothing to archive)
  - Replacing an empty plan (skip — no value)
  - Replacing a partial plan (some tasks done, some pending)
  - Replacing a fully-completed plan ("shipped" reason)
  - Replacing a fully-abandoned plan ("abandoned" reason)
  - Replacing while a task is in_progress (status → "interrupted")
  - Replacing with identical content (skip — would clutter history)
  - Replacing with cosmetic-only changes (still archive — different
    surface area than identical)
  - History cap of 25 enforced (oldest evicted)
  - plan_clear drops without archiving (the explicit escape hatch)
  - plan_archive (explicit) still works alongside auto-archive
  - Auto-archived entries are flagged with auto_archived: True
  - The new plan's goal is recorded in the OLD plan's
    ``superseded_by_goal`` so retrospectives can chase the chain

Plus event-emission contract: a ``plan_archived`` event lands on the
WS bus with the right shape every time auto-archive triggers.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from chika.core.variable_store import VariableStore
from chika.skills.plan_skill import _make_plan_tools


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def tools():
    """Each test gets a fresh variable store + plan-skill tools."""
    store = VariableStore()
    (plan_set, plan_update, plan_get, plan_add, plan_remove,
     plan_edit, plan_archive, plan_history,
     plan_clear) = _make_plan_tools(store)
    return {
        "store":         store,
        "set":           plan_set,
        "update":        plan_update,
        "get":           plan_get,
        "add":           plan_add,
        "remove":        plan_remove,
        "edit":          plan_edit,
        "archive":       plan_archive,
        "history":       plan_history,
        "clear":         plan_clear,
    }


def _archive_count(tools_):
    var = tools_["store"].get("plan_archive")
    return len(var.value) if var else 0


def _archive_list(tools_):
    var = tools_["store"].get("plan_archive")
    return list(var.value) if var else []


# ── First plan — nothing to archive ─────────────────────────────────────


def test_first_plan_set_does_not_archive_anything(tools):
    result = _run(tools["set"](["task A", "task B"]))
    assert result.get("auto_archived") is False
    assert _archive_count(tools) == 0


# ── Replacing an empty plan ─────────────────────────────────────────────


def test_replacing_empty_plan_skips_archive(tools):
    """If the prior plan somehow has no tasks (empty list), auto-archive
    short-circuits — no value in retaining a shell."""
    # Force an empty plan into the store (bypass plan_set's own guard
    # that rejects empty task lists).
    from chika.core.variable_store import VarType
    tools["store"].set("plan", {
        "goal": "", "requirements": [], "tasks": [],
        "created_at": time.time(), "updated_at": time.time(),
    }, VarType.JSON, source="test")

    result = _run(tools["set"](["new A", "new B"]))
    assert result["auto_archived"] is False
    assert _archive_count(tools) == 0


# ── Replacing a partial plan ────────────────────────────────────────────


def test_replacing_partial_plan_archives_with_superseded_reason(tools):
    _run(tools["set"](["A", "B", "C"]))
    _run(tools["update"](task_id="t1", status="done"))
    # Replace
    new_plan = _run(tools["set"](["NEW1", "NEW2"], goal="rebuild auth"))

    assert new_plan["auto_archived"] is True
    history = _archive_list(tools)
    assert len(history) == 1
    archived = history[0]
    assert archived["auto_archived"] is True
    assert "superseded by plan_set" in archived["archive_reason"]
    assert "1/3" in archived["archive_reason"]
    assert archived["superseded_by_goal"] == "rebuild auth"


# ── Fully-completed plan → 'shipped' ────────────────────────────────────


def test_replacing_completed_plan_uses_shipped_reason(tools):
    _run(tools["set"](["A", "B"]))
    _run(tools["update"](task_id="t1", status="done"))
    _run(tools["update"](task_id="t2", status="done"))

    _run(tools["set"](["NEXT"]))
    archived = _archive_list(tools)[0]
    assert "shipped" in archived["archive_reason"]


# ── Fully-abandoned plan → 'abandoned' ──────────────────────────────────


def test_replacing_zero_progress_plan_uses_abandoned_reason(tools):
    _run(tools["set"](["A", "B"]))
    # Don't mark anything done — the default sets t1 to in_progress.
    # Reset it to pending so done_count is genuinely 0.
    _run(tools["update"](task_id="t1", status="pending"))

    _run(tools["set"](["NEXT"]))
    archived = _archive_list(tools)[0]
    assert "abandoned" in archived["archive_reason"]


# ── In-progress task at archive time → 'interrupted' ────────────────────


def test_in_progress_task_marked_interrupted_on_archive(tools):
    _run(tools["set"](["A", "B"]))
    # By default plan_set marks the first task in_progress
    plan = tools["store"].get("plan").value
    assert plan["tasks"][0]["status"] == "in_progress"

    _run(tools["set"](["NEW"]))
    archived = _archive_list(tools)[0]
    # The previously in-progress task is stamped 'interrupted' in the
    # archive — pending tasks stay pending.
    assert archived["tasks"][0]["status"] == "interrupted"
    assert archived["tasks"][1]["status"] == "pending"


def test_in_progress_status_recursively_handled_in_subtasks(tools):
    """Nested in_progress tasks deep in the tree also get marked
    interrupted."""
    _run(tools["set"]([{
        "text": "outer task",
        "subtasks": [
            {"text": "nested in-progress", "status": "in_progress"},
            {"text": "nested pending"},
        ],
    }]))
    _run(tools["set"](["new"]))
    archived = _archive_list(tools)[0]
    nested = archived["tasks"][0]["subtasks"]
    assert nested[0]["status"] == "interrupted"
    assert nested[1]["status"] == "pending"


# ── Identical content replace → skip archive ────────────────────────────


def test_identical_content_replace_skips_archive(tools):
    """The agent occasionally re-issues plan_set with the same tasks
    (e.g., on a retry). We don't clutter history with N copies of the
    same plan."""
    _run(tools["set"](["A", "B"]))
    _run(tools["set"](["A", "B"]))  # identical
    assert _archive_count(tools) == 0


def test_replace_with_one_task_changed_DOES_archive(tools):
    """Sanity: changing even one task triggers the archive — only
    fully-identical replacements are skipped."""
    _run(tools["set"](["A", "B"]))
    _run(tools["set"](["A", "C"]))
    assert _archive_count(tools) == 1


def test_replace_with_different_goal_DOES_archive(tools):
    """Goal change counts as content change."""
    _run(tools["set"](["A"], goal="alpha"))
    _run(tools["set"](["A"], goal="beta"))
    assert _archive_count(tools) == 1


def test_replace_with_different_requirements_DOES_archive(tools):
    _run(tools["set"](["A"], requirements=["one"]))
    _run(tools["set"](["A"], requirements=["two"]))
    assert _archive_count(tools) == 1


# ── History cap (25) ────────────────────────────────────────────────────


def test_history_cap_at_25_oldest_evicted(tools):
    """Set 30 distinct plans — only the most recent 25 should survive
    in history."""
    for i in range(30):
        _run(tools["set"]([f"plan-{i}-task"]))
    history = _archive_list(tools)
    assert len(history) == 25
    # Oldest is plan-4 (because plans 0-3 got evicted; plan-29 is
    # current and not yet archived). Wait — plan-29 IS the current
    # (most recent set), and it gets archived only when the NEXT
    # plan_set fires. So we expect plan-4 through plan-28 in archive
    # (25 entries), plan-29 still active.
    goals = [
        next(
            (t["text"] for t in p["tasks"] if "task" in t["text"]),
            "",
        ) for p in history
    ]
    assert any("plan-4-" in g for g in goals)
    assert not any("plan-3-" in g for g in goals)
    assert any("plan-28-" in g for g in goals)


# ── plan_clear (explicit escape hatch) ──────────────────────────────────


def test_plan_clear_drops_without_archiving(tools):
    _run(tools["set"](["A", "B"]))
    _run(tools["update"](task_id="t1", status="done"))
    result = _run(tools["clear"]())
    assert result["cleared"] is True
    # No active plan
    assert tools["store"].get("plan") is None
    # And NOTHING was added to the archive
    assert _archive_count(tools) == 0


def test_plan_clear_no_op_when_no_plan(tools):
    result = _run(tools["clear"]())
    assert result["cleared"] is False
    assert "no active plan" in result["note"]


def test_plan_clear_then_set_does_not_archive(tools):
    """plan_clear leaves $plan empty, so the next plan_set has nothing
    to auto-archive."""
    _run(tools["set"](["A"]))
    _run(tools["clear"]())
    result = _run(tools["set"](["B"]))
    assert result["auto_archived"] is False
    assert _archive_count(tools) == 0


# ── plan_archive (explicit) still works ─────────────────────────────────


def test_explicit_plan_archive_still_archives(tools):
    _run(tools["set"](["A"], goal="ship feature X"))
    result = _run(tools["archive"](reason="user pivoted"))
    assert result["archived"] is True
    archived = _archive_list(tools)[0]
    assert archived["archive_reason"] == "user pivoted"
    # Explicit archive is NOT flagged as auto.
    assert archived["auto_archived"] is False
    # Plan was cleared (UI panels go blank).
    assert tools["store"].get("plan") is None


def test_explicit_plan_archive_followed_by_plan_set_creates_two_entries(tools):
    """plan_archive clears the plan; the next plan_set has nothing to
    auto-archive (active was cleared). So the archive holds exactly
    ONE entry from the explicit call, not two."""
    _run(tools["set"](["A"]))
    _run(tools["archive"](reason="abandoned"))
    _run(tools["set"](["B"]))
    assert _archive_count(tools) == 1


def test_explicit_archive_with_no_plan_returns_friendly_note(tools):
    result = _run(tools["archive"]())
    assert result["archived"] is False
    assert result["note"]


def test_explicit_archive_skips_when_plan_has_no_tasks(tools):
    """Empty plan → explicit archive also skips."""
    from chika.core.variable_store import VarType
    tools["store"].set("plan", {
        "goal": "", "requirements": [], "tasks": [],
        "created_at": time.time(), "updated_at": time.time(),
    }, VarType.JSON, source="test")
    result = _run(tools["archive"]())
    assert result["archived"] is False


# ── plan_history reflects auto-archives ─────────────────────────────────


def test_plan_history_returns_auto_archived_entries(tools):
    _run(tools["set"](["plan-A"]))
    _run(tools["set"](["plan-B"]))
    _run(tools["set"](["plan-C"]))

    result = _run(tools["history"]())
    assert result["count"] == 2
    # plan_history returns newest-first per its existing contract
    assert result["plans"][0]["tasks"][0]["text"] == "plan-B"
    assert result["plans"][1]["tasks"][0]["text"] == "plan-A"


# ── Auto vs explicit flagging ───────────────────────────────────────────


def test_auto_archive_sets_auto_archived_true(tools):
    _run(tools["set"](["A"]))
    _run(tools["set"](["B"]))
    archived = _archive_list(tools)[0]
    assert archived["auto_archived"] is True


def test_explicit_archive_sets_auto_archived_false(tools):
    _run(tools["set"](["A"]))
    _run(tools["archive"]())
    archived = _archive_list(tools)[0]
    assert archived["auto_archived"] is False


# ── superseded_by_goal links ────────────────────────────────────────────


def test_superseded_by_goal_recorded_on_auto_archive(tools):
    _run(tools["set"](["A"], goal="first"))
    _run(tools["set"](["B"], goal="second"))
    archived = _archive_list(tools)[0]
    assert archived["superseded_by_goal"] == "second"


def test_no_superseded_by_goal_when_explicit_archive(tools):
    _run(tools["set"](["A"], goal="first"))
    _run(tools["archive"]())
    archived = _archive_list(tools)[0]
    # Explicit archives don't have a 'next plan' to link to
    assert "superseded_by_goal" not in archived


# ── Archive metadata ────────────────────────────────────────────────────


def test_archived_at_timestamp_recorded(tools):
    _run(tools["set"](["A"]))
    before = time.time()
    _run(tools["set"](["B"]))
    after = time.time()
    archived = _archive_list(tools)[0]
    assert before <= archived["archived_at"] <= after


# ── WS event emission ──────────────────────────────────────────────────


def test_plan_archived_event_emitted_on_auto_archive(tools):
    """The auto-archive path schedules a ``plan_archived`` broadcast.
    We patch the broadcaster and verify both the call AND the payload
    shape (auto:true, source:plan_set, summary fields)."""
    broadcast = AsyncMock()

    async def _go():
        with patch("api.broadcast.push_to_all_frontend_sessions", broadcast):
            await tools["set"](["A"], goal="first goal")
            await tools["set"](["B"], goal="second goal")
        # let the scheduled task drain
        await asyncio.sleep(0)

    asyncio.run(_go())
    # First plan_set → no archive → no event. Second → 1 event.
    assert broadcast.await_count == 1
    payload = broadcast.await_args.args[0]
    assert payload["type"] == "plan_archived"
    assert payload["auto"] is True
    assert payload["goal"] == "first goal"
    assert payload["superseded_by"] == "second goal"
    assert payload["source"] == "plan_set"
    assert payload["history_count"] == 1


def test_plan_archived_event_emitted_on_explicit_archive(tools):
    broadcast = AsyncMock()

    async def _go():
        with patch("api.broadcast.push_to_all_frontend_sessions", broadcast):
            await tools["set"](["A"])
            await tools["archive"](reason="shipped")
        await asyncio.sleep(0)

    asyncio.run(_go())
    assert broadcast.await_count == 1
    payload = broadcast.await_args.args[0]
    assert payload["auto"] is False
    assert payload["source"] == "plan_archive"
    assert payload["reason"] == "shipped"


def test_plan_archived_event_NOT_emitted_when_skipping_identical(tools):
    broadcast = AsyncMock()

    async def _go():
        with patch("api.broadcast.push_to_all_frontend_sessions", broadcast):
            await tools["set"](["A"])
            await tools["set"](["A"])  # identical → no archive → no event
        await asyncio.sleep(0)

    asyncio.run(_go())
    assert broadcast.await_count == 0


# ── Concurrency: rapid plan_set calls don't lose archives ──────────────


def test_rapid_consecutive_plan_sets_keep_every_archive(tools):
    """Three back-to-back plan_set calls → archive holds the first two."""
    _run(tools["set"](["A"]))
    _run(tools["set"](["B"]))
    _run(tools["set"](["C"]))
    history = _archive_list(tools)
    assert len(history) == 2
    assert history[0]["tasks"][0]["text"] == "A"
    assert history[1]["tasks"][0]["text"] == "B"


# ── plan_get sanity (no regression in existing surface) ────────────────


def test_plan_get_returns_only_active_not_archived(tools):
    _run(tools["set"](["old"]))
    _run(tools["set"](["new"]))
    result = _run(tools["get"]())
    # plan_get returns the live plan; archived plans are accessed via
    # plan_history.
    assert result["plan"]["tasks"][0]["text"] == "new"
