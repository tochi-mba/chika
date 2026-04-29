"""
plan_skill — session-scoped task planning.

Gives chika the equivalent of Claude Code's TodoWrite: a structured list of
tasks it can set at the start of a non-trivial job and update as it goes.

The plan lives in `$plan` on the variable store. Three tools:
  - plan_set     set the initial task list
  - plan_update  mark a single task's status (pending | in_progress | done)
  - plan_get     return the current plan (also auto-rendered in $plan)

Why this helps the agent:
  - Forces it to decompose big jobs into named steps BEFORE diving in
  - Gives it a place to mark progress, so multi-turn tasks stay coherent
  - The frontend can render a live checklist from $plan
  - It is *cheap* — pure variable-store writes, no LLM calls
"""
from __future__ import annotations

import time
from typing import Any

from chika.core.skill_registry import Skill
from chika.core.tool_registry import ToolDefinition
from chika.core.variable_store import VarType

_VALID_STATUS = {"pending", "in_progress", "done"}


def _clean_task(t: Any, idx: int) -> dict:
    """Coerce whatever the LLM sent into a valid task dict."""
    if isinstance(t, str):
        return {"id": f"t{idx}", "text": t, "status": "pending"}
    if isinstance(t, dict):
        text = (t.get("text") or t.get("content") or "").strip()
        status = t.get("status") or "pending"
        if status not in _VALID_STATUS:
            status = "pending"
        tid = t.get("id") or f"t{idx}"
        return {"id": str(tid), "text": text, "status": status}
    return {"id": f"t{idx}", "text": str(t), "status": "pending"}


def _make_plan_tools(variable_store):

    async def plan_set(tasks: list) -> dict:
        """
        Set the plan for this session. Replaces any existing plan.
        Each task may be a string or {id, text, status}.
        """
        if not isinstance(tasks, list) or not tasks:
            return {"error": "plan_set requires a non-empty list of tasks"}
        cleaned = [_clean_task(t, i) for i, t in enumerate(tasks, start=1)]
        # Default: first task is in_progress, rest pending
        if not any(t["status"] == "in_progress" for t in cleaned):
            for t in cleaned:
                if t["status"] == "pending":
                    t["status"] = "in_progress"
                    break
        plan = {
            "tasks": cleaned,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        variable_store.set("plan", plan, VarType.JSON,
                           description="Session task plan",
                           source="plan:set")
        return {"_source": "plan_set", "count": len(cleaned), "plan": plan}

    async def plan_update(task_id: str, status: str, text: str | None = None) -> dict:
        """
        Update a single task's status. Optionally rewrite its text (for when
        scope shifts mid-job). Automatically promotes the next pending task
        to in_progress when you mark the current one done.
        """
        if status not in _VALID_STATUS:
            return {"error": f"invalid status {status!r}; must be one of {sorted(_VALID_STATUS)}"}
        var = variable_store.get("plan")
        if var is None or not isinstance(var.value, dict):
            return {"error": "no plan set yet — call plan_set first"}
        plan = dict(var.value)
        tasks = list(plan.get("tasks") or [])
        matched = False
        for t in tasks:
            if t.get("id") == task_id:
                t["status"] = status
                if text:
                    t["text"] = text
                matched = True
                break
        if not matched:
            return {"error": f"task_id {task_id!r} not found in current plan"}
        # Auto-promote the next pending task when we close one out.
        if status == "done" and not any(t.get("status") == "in_progress" for t in tasks):
            for t in tasks:
                if t.get("status") == "pending":
                    t["status"] = "in_progress"
                    break
        plan["tasks"] = tasks
        plan["updated_at"] = time.time()
        variable_store.set("plan", plan, VarType.JSON,
                           description="Session task plan",
                           source="plan:update")
        return {"_source": "plan_update", "plan": plan}

    async def plan_get() -> dict:
        var = variable_store.get("plan")
        if var is None or not isinstance(var.value, dict):
            return {"_source": "plan_get", "plan": None, "message": "no plan set"}
        return {"_source": "plan_get", "plan": var.value}

    return plan_set, plan_update, plan_get


def build_plan_skill(variable_store) -> Skill:
    plan_set, plan_update, plan_get = _make_plan_tools(variable_store)
    return Skill(
        name="plan",
        description="Session-scoped task planning (decompose big jobs, track progress)",
        tools=[
            ToolDefinition(
                name="plan_set",
                description=(
                    "Set the task plan at the start of any multi-step job. "
                    "Pass a list of short tasks in execution order. The first "
                    "pending task is auto-marked in_progress. Call this ONCE "
                    "at the start of a non-trivial task (3+ steps), then use "
                    "plan_update to track progress. Skip this for trivial "
                    "single-step tasks."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "tasks": {
                            "type": "array",
                            "items": {"type": ["string", "object"]},
                            "description": (
                                "Ordered list of short task descriptions. Strings "
                                "become pending tasks; objects {id, text, status} "
                                "allow explicit control."
                            ),
                        },
                    },
                    "required": ["tasks"],
                },
                handler=plan_set,
            ),
            ToolDefinition(
                name="plan_update",
                description=(
                    "Mark a task's status. Use as you finish each one — "
                    "'pending' | 'in_progress' | 'done'. When you mark a "
                    "task 'done' the next pending task auto-promotes to "
                    "'in_progress'. Pass 'text' to rewrite the task "
                    "description if scope changed."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "ID of the task to update (e.g. 't1', 't2', ...)"},
                        "status":  {"type": "string", "enum": ["pending", "in_progress", "done"]},
                        "text":    {"type": "string", "description": "Optional: rewrite the task description"},
                    },
                    "required": ["task_id", "status"],
                },
                handler=plan_update,
            ),
            ToolDefinition(
                name="plan_get",
                description="Return the current plan. Useful mid-workflow to remember where you are.",
                parameters={"type": "object", "properties": {}},
                handler=plan_get,
            ),
        ],
        workflow_examples="""
### Session planning

**At the start of a non-trivial job (3+ steps):**
```json
{"tool": "plan_set", "args": {"tasks": [
  "Search for the project's test files",
  "Read the main test config",
  "Run the failing test with verbose output",
  "Diagnose the error from the traceback",
  "Write a fix and verify it"
]}}
```

**As each task completes:**
```json
{"tool": "plan_update", "args": {"task_id": "t1", "status": "done"}}
```

Keep this lightweight — 3–8 tasks, each a short phrase. Don't re-plan
every turn. Update tasks as you actually finish them.
""",
    )
