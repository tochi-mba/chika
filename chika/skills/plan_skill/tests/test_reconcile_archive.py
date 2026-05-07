"""Coverage for plan_skill: plan_reconcile, plan_archive, plan_history.

These three tools dominate the uncovered range in plan_skill (lines
386-481, 859-923, 939-945). Together they're ~150 lines of logic the
existing tests didn't reach.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chika.core.variable_store import VariableStore, VarType
from chika.skills import plan_skill as ps

# ── helpers ────────────────────────────────────────────────────────────


@pytest.fixture
def vstore():
    return VariableStore()


@pytest.fixture
def plan_with_tasks(vstore):
    """Seed a basic plan in the variable store."""
    plan = {
        "goal":         "Ship feature X",
        "requirements": ["must work offline"],
        "tasks": [
            {"id": "t1", "text": "design",  "status": "in_progress", "subtasks": []},
            {"id": "t2", "text": "build",   "status": "pending",     "subtasks": []},
            {"id": "t3", "text": "release", "status": "pending",     "subtasks": []},
        ],
        "created_at": 1700000000.0,
        "updated_at": 1700000000.0,
    }
    vstore.set("plan", plan, VarType.JSON, description="seed", source="test")
    return plan


# ── plan_reconcile ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_engine_unavailable(vstore):
    """No engine → returns engine_unavailable error."""
    fn = ps._build_plan_reconcile(vstore, lambda: None)
    out = await fn()
    assert out["error"] == "engine_unavailable"
    assert "ChikaEngine" in out["hint"]


@pytest.mark.asyncio
async def test_reconcile_no_plan(vstore):
    """Engine present but no plan in store → no_plan error."""
    engine = MagicMock()
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    out = await fn()
    assert out["error"] == "no_plan"
    assert "plan_set" in out["hint"]


@pytest.mark.asyncio
async def test_reconcile_with_chat_excerpt_no_ops_needed(vstore, plan_with_tasks):
    """LLM returns ops=[] → applied=0, plan unchanged."""
    engine = MagicMock()
    engine._llm_complete = AsyncMock(
        return_value='{"ops": [], "reasoning": "already aligned"}',
    )
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    out = await fn(chat_excerpt="user: looks good")
    assert out["applied"] == 0
    assert out["ops"] == []
    assert out["reasoning"] == "already aligned"


@pytest.mark.asyncio
async def test_reconcile_uses_engine_history_when_no_excerpt(vstore, plan_with_tasks):
    """When chat_excerpt is empty, the engine's _history is sampled."""
    engine = MagicMock()
    engine._history = [
        {"role": "user", "content": "switch to React"},
        {"role": "assistant", "content": "ok"},
    ]
    engine._llm_complete = AsyncMock(return_value='{"ops": []}')
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    out = await fn()
    # Verify the prompt the LLM saw included history.
    call_args = engine._llm_complete.call_args[0]
    assert "switch to React" in call_args[0]
    assert out["applied"] == 0


@pytest.mark.asyncio
async def test_reconcile_history_skips_non_string_and_non_user_assistant(vstore, plan_with_tasks):
    """tool_call messages and non-string content are filtered out."""
    engine = MagicMock()
    engine._history = [
        {"role": "system", "content": "ignore me"},
        {"role": "tool_call", "content": "ignore"},
        {"role": "user", "content": ["non-string"]},  # non-string
        {"role": "assistant", "content": "kept"},
    ]
    engine._llm_complete = AsyncMock(return_value='{"ops": []}')
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    await fn()
    prompt = engine._llm_complete.call_args[0][0]
    assert "kept" in prompt
    assert "ignore me" not in prompt


@pytest.mark.asyncio
async def test_reconcile_long_message_truncated(vstore, plan_with_tasks):
    engine = MagicMock()
    engine._history = [
        {"role": "user", "content": "x" * 1000},
    ]
    engine._llm_complete = AsyncMock(return_value='{"ops": []}')
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    await fn()
    prompt = engine._llm_complete.call_args[0][0]
    assert "…" in prompt  # truncation marker


@pytest.mark.asyncio
async def test_reconcile_empty_history_uses_placeholder(vstore, plan_with_tasks):
    engine = MagicMock()
    engine._history = []
    engine._llm_complete = AsyncMock(return_value='{"ops": []}')
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    await fn()
    prompt = engine._llm_complete.call_args[0][0]
    assert "(no prior turns)" in prompt


@pytest.mark.asyncio
async def test_reconcile_llm_failure(vstore, plan_with_tasks):
    """LLM raising → llm_call_failed error."""
    engine = MagicMock()
    engine._llm_complete = AsyncMock(side_effect=RuntimeError("LLM down"))
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    out = await fn(chat_excerpt="x")
    assert out["error"] == "llm_call_failed"
    assert "RuntimeError" in out["detail"]


@pytest.mark.asyncio
async def test_reconcile_invalid_json_no_ops(vstore, plan_with_tasks):
    """LLM returns garbage → reconcile applies nothing, no crash."""
    engine = MagicMock()
    engine._llm_complete = AsyncMock(return_value="garbage no json here")
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    out = await fn(chat_excerpt="x")
    assert out["applied"] == 0


@pytest.mark.asyncio
async def test_reconcile_json_in_fences(vstore, plan_with_tasks):
    """LLM wraps JSON in markdown fences — should still parse."""
    engine = MagicMock()
    engine._llm_complete = AsyncMock(return_value='```json\n{"ops": [{"op":"add_requirement","value":"new req"}], "reasoning":"r"}\n```')
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    out = await fn(chat_excerpt="x")
    assert out["applied"] == 1
    assert "new req" in out["plan"]["requirements"]


@pytest.mark.asyncio
async def test_reconcile_caps_ops_at_max(vstore, plan_with_tasks):
    """ops list longer than max_ops is truncated."""
    engine = MagicMock()
    many_ops = [{"op": "add_requirement", "value": f"req{i}"} for i in range(20)]
    import json as _j
    engine._llm_complete = AsyncMock(
        return_value=_j.dumps({"ops": many_ops, "reasoning": "lots"}),
    )
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    out = await fn(chat_excerpt="x", max_ops=5)
    assert out["applied"] == 5


@pytest.mark.asyncio
async def test_reconcile_non_dict_op_recorded_as_error(vstore, plan_with_tasks):
    engine = MagicMock()
    import json as _j
    engine._llm_complete = AsyncMock(
        return_value=_j.dumps({"ops": ["not-a-dict", {"op": "add_requirement", "value": "ok"}]}),
    )
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    out = await fn(chat_excerpt="x")
    assert out["applied"] == 1
    assert out["failed"] == 1


@pytest.mark.asyncio
async def test_reconcile_non_list_ops_treated_as_empty(vstore, plan_with_tasks):
    engine = MagicMock()
    engine._llm_complete = AsyncMock(
        return_value='{"ops": "not a list", "reasoning": "x"}',
    )
    fn = ps._build_plan_reconcile(vstore, lambda: engine)
    out = await fn(chat_excerpt="x")
    assert out["applied"] == 0


# ── plan_archive ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_archive_no_active_plan(vstore):
    """Calling archive with no plan → returns archived=False, no error."""
    _, _, _, _, _, _, plan_archive, _, _ = ps._make_plan_tools(vstore)
    out = await plan_archive()
    assert out["archived"] is False


@pytest.mark.asyncio
async def test_archive_moves_plan_to_history(vstore, plan_with_tasks):
    _, _, _, _, _, _, plan_archive, _, _ = ps._make_plan_tools(vstore)
    out = await plan_archive(reason="shipped")
    assert out["archived"] is True
    assert out["count"] == 1
    assert out["plan"]["archive_reason"] == "shipped"
    # Active plan cleared.
    assert vstore.get("plan") is None
    # History populated.
    history = vstore.get("plan_archive")
    assert history is not None
    assert len(history.value) == 1


@pytest.mark.asyncio
async def test_archive_caps_history_at_25(vstore, plan_with_tasks):
    """When 25+ plans are already archived, oldest is dropped."""
    fake_history = [{"goal": f"old{i}"} for i in range(25)]
    vstore.set("plan_archive", fake_history, VarType.JSON,
               description="seed", source="test")
    _, _, _, _, _, _, plan_archive, _, _ = ps._make_plan_tools(vstore)
    out = await plan_archive()
    history = vstore.get("plan_archive").value
    assert len(history) == 25
    # The freshly-archived plan is last; the original [0] was dropped.
    assert history[0]["goal"] == "old1"
    assert out["plan"]["goal"] == "Ship feature X"


@pytest.mark.asyncio
async def test_archive_with_memory_persistence(vstore, plan_with_tasks):
    mm = MagicMock()
    mm.persist = MagicMock()
    _, _, _, _, _, _, plan_archive, _, _ = ps._make_plan_tools(
        vstore, memory_getter=lambda: mm,
    )
    out = await plan_archive(reason="shipped 2026-05-05")
    assert out["memory_line"]
    assert "plan archived" in out["memory_line"]
    assert "Ship feature X" in out["memory_line"]
    mm.persist.assert_called_once()


@pytest.mark.asyncio
async def test_archive_memory_getter_failure_does_not_block(vstore, plan_with_tasks):
    """If memory_getter or mm.persist throws, archive still returns archived=True."""
    def boom():
        raise RuntimeError("no profile")

    _, _, _, _, _, _, plan_archive, _, _ = ps._make_plan_tools(
        vstore, memory_getter=boom,
    )
    out = await plan_archive()
    assert out["archived"] is True
    assert out["memory_line"] is None


@pytest.mark.asyncio
async def test_archive_memory_persist_failure_swallowed(vstore, plan_with_tasks):
    mm = MagicMock()
    mm.persist = MagicMock(side_effect=OSError("disk full"))
    _, _, _, _, _, _, plan_archive, _, _ = ps._make_plan_tools(
        vstore, memory_getter=lambda: mm,
    )
    out = await plan_archive()
    assert out["archived"] is True
    # When persist fails, memory_line is reset to "" then mapped to None.
    assert out["memory_line"] is None


# ── plan_history ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_empty(vstore):
    _, _, _, _, _, _, _, plan_history, _ = ps._make_plan_tools(vstore)
    out = await plan_history()
    assert out["count"] == 0
    assert out["plans"] == []


@pytest.mark.asyncio
async def test_history_returns_newest_first(vstore):
    fake_history = [
        {"goal": "plan-A", "archived_at": 1.0},
        {"goal": "plan-B", "archived_at": 2.0},
        {"goal": "plan-C", "archived_at": 3.0},
    ]
    vstore.set("plan_archive", fake_history, VarType.JSON,
               description="seed", source="test")
    _, _, _, _, _, _, _, plan_history, _ = ps._make_plan_tools(vstore)
    out = await plan_history()
    assert out["plans"][0]["goal"] == "plan-C"
    assert out["plans"][2]["goal"] == "plan-A"


@pytest.mark.asyncio
async def test_history_respects_limit(vstore):
    fake_history = [{"goal": f"p{i}"} for i in range(10)]
    vstore.set("plan_archive", fake_history, VarType.JSON,
               description="seed", source="test")
    _, _, _, _, _, _, _, plan_history, _ = ps._make_plan_tools(vstore)
    out = await plan_history(limit=3)
    assert len(out["plans"]) == 3


@pytest.mark.asyncio
async def test_history_zero_limit_returns_all(vstore):
    """limit=0 → no truncation (the guard is `if limit and limit > 0`)."""
    fake_history = [{"goal": f"p{i}"} for i in range(7)]
    vstore.set("plan_archive", fake_history, VarType.JSON,
               description="seed", source="test")
    _, _, _, _, _, _, _, plan_history, _ = ps._make_plan_tools(vstore)
    out = await plan_history(limit=0)
    assert len(out["plans"]) == 7


# ── _make_plan_prompt_section ──────────────────────────────────────────


def test_prompt_section_no_plan(vstore):
    render = ps._make_plan_prompt_section(vstore)
    assert render() == ""


def test_prompt_section_no_tasks(vstore):
    vstore.set("plan", {"goal": "x", "tasks": []}, VarType.JSON,
               description="seed", source="test")
    render = ps._make_plan_prompt_section(vstore)
    assert render() == ""


def test_prompt_section_with_in_progress_task(vstore, plan_with_tasks):
    render = ps._make_plan_prompt_section(vstore)
    out = render()
    assert "## Active plan" in out
    assert "design" in out
    assert "Ship feature X" in out
    assert "in progress" in out


def test_prompt_section_progress_count(vstore):
    plan = {
        "goal": "x",
        "tasks": [
            {"id": "t1", "text": "a", "status": "done",        "subtasks": []},
            {"id": "t2", "text": "b", "status": "in_progress", "subtasks": []},
            {"id": "t3", "text": "c", "status": "pending",     "subtasks": []},
        ],
    }
    vstore.set("plan", plan, VarType.JSON, description="seed", source="test")
    render = ps._make_plan_prompt_section(vstore)
    out = render()
    assert "1/3" in out


def test_prompt_section_handles_nested_subtasks(vstore):
    plan = {
        "goal": "g",
        "tasks": [
            {
                "id": "t1", "text": "parent",
                "status": "in_progress",
                "subtasks": [
                    {"id": "t1.1", "text": "leaf-A", "status": "done",        "subtasks": []},
                    {"id": "t1.2", "text": "leaf-B", "status": "in_progress", "subtasks": []},
                ],
            },
        ],
    }
    vstore.set("plan", plan, VarType.JSON, description="seed", source="test")
    render = ps._make_plan_prompt_section(vstore)
    out = render()
    assert "leaf-B" in out  # in-progress leaf
    assert "1/2" in out


# ── build_plan_skill integration ───────────────────────────────────────


def test_build_plan_skill_returns_skill_with_all_tools():
    vstore = VariableStore()
    skill = ps.build_plan_skill(vstore)
    names = {t.name for t in skill.tools}
    assert {"plan_set", "plan_update", "plan_get",
            "plan_add", "plan_remove", "plan_edit",
            "plan_archive", "plan_history", "plan_reconcile"}.issubset(names)


def test_build_plan_skill_with_engine_getter():
    """Engine getter is wired into plan_reconcile via closure."""
    vstore = VariableStore()
    engine = MagicMock()
    skill = ps.build_plan_skill(vstore, engine_getter=lambda: engine)
    reconcile_tool = next(t for t in skill.tools if t.name == "plan_reconcile")
    assert callable(reconcile_tool.handler)
