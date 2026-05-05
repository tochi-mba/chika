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

import json
import time
from typing import Any

from chika.core.skill_registry import Skill
from chika.core.tool_registry import ToolDefinition
from chika.core.variable_store import VarType

_VALID_STATUS = {"pending", "in_progress", "done"}


def _clean_task(t: Any, idx: int, parent_id: str | None = None) -> dict:
    """Coerce whatever the LLM sent into a valid task dict.

    Tasks may carry an optional ``subtasks`` list — same shape as the
    top-level tasks. A parent's status is derived from its subtasks
    (see ``_recompute_parent_status``); auto-derivation only kicks in
    when subtasks are present.
    """
    base_id = f"{parent_id}.{idx}" if parent_id else f"t{idx}"
    if isinstance(t, str):
        return {"id": base_id, "text": t, "status": "pending", "subtasks": []}
    if isinstance(t, dict):
        text = (t.get("text") or t.get("content") or "").strip()
        status = t.get("status") or "pending"
        if status not in _VALID_STATUS:
            status = "pending"
        tid = t.get("id") or base_id
        # Aliases for the subtasks field — same kwarg-drift defence as
        # the top-level ``tasks`` resolver.
        raw_subs = (t.get("subtasks") or t.get("children")
                    or t.get("steps") or t.get("items") or [])
        subs: list[dict] = []
        if isinstance(raw_subs, list):
            for j, s in enumerate(raw_subs, start=1):
                subs.append(_clean_task(s, j, parent_id=str(tid)))
        return {
            "id":       str(tid),
            "text":     text,
            "status":   status,
            "subtasks": subs,
        }
    return {"id": base_id, "text": str(t), "status": "pending", "subtasks": []}


def _recompute_parent_status(task: dict) -> None:
    """If a task has subtasks, derive its status from theirs.

    - Any in_progress sub  → parent in_progress
    - All subs done       → parent done
    - Otherwise           → pending

    Called after every plan mutation that could change a sub's status.
    """
    subs = task.get("subtasks") or []
    if not subs:
        return
    for sub in subs:
        _recompute_parent_status(sub)
    if any(s.get("status") == "in_progress" for s in subs):
        task["status"] = "in_progress"
    elif all(s.get("status") == "done" for s in subs):
        task["status"] = "done"
    else:
        task["status"] = "pending"


def _walk_tasks(tasks: list[dict]):
    """Yield (task, depth) for every task and sub-task in DFS order."""
    def _go(items: list[dict], depth: int):
        for t in items:
            if not isinstance(t, dict):
                continue
            yield t, depth
            yield from _go(t.get("subtasks") or [], depth + 1)
    yield from _go(tasks, 0)


def _any_in_progress(task: dict) -> bool:
    """True if this task or any descendant is in_progress."""
    if task.get("status") == "in_progress":
        return True
    for sub in task.get("subtasks") or []:
        if isinstance(sub, dict) and _any_in_progress(sub):
            return True
    return False


def _promote_first_pending_leaf(task: dict) -> bool:
    """Mark the first pending LEAF in this subtree as in_progress.

    Returns True if a promotion happened. Walks the subtree depth-first
    and stops at the first match; parent statuses are recomputed by the
    caller via :func:`_recompute_parent_status`.
    """
    subs = task.get("subtasks") or []
    if not subs:
        if task.get("status") == "pending":
            task["status"] = "in_progress"
            return True
        return False
    for sub in subs:
        if isinstance(sub, dict) and _promote_first_pending_leaf(sub):
            return True
    return False


def _find_task(tasks: list[dict], task_id: str) -> dict | None:
    """Find a task anywhere in the tree by id. Returns None if not found."""
    for task, _depth in _walk_tasks(tasks):
        if task.get("id") == task_id:
            return task
    return None


def _remove_task(tasks: list[dict], task_id: str) -> bool:
    """Remove the task with ``task_id`` from anywhere in the tree.

    Returns True iff a task was removed. Mutates ``tasks`` in place.
    """
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            continue
        if t.get("id") == task_id:
            tasks.pop(i)
            return True
        subs = t.get("subtasks") or []
        if subs and _remove_task(subs, task_id):
            return True
    return False


def _next_unique_id(tasks: list[dict], prefix: str = "t") -> str:
    """Generate a fresh top-level id like ``t7`` that doesn't collide with
    any existing top-level OR nested id."""
    used = {t.get("id") for t, _ in _walk_tasks(tasks)
            if isinstance(t, dict) and isinstance(t.get("id"), str)}
    n = len(used) + 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def _apply_plan_op(plan: dict, op: dict) -> dict:
    """Apply a single ``plan_edit`` op to ``plan`` in place.

    Returns ``{ok: bool, error?: str, ...}``. Pure dispatch — keeps
    ``plan_edit`` itself focused on validation + iteration.
    """
    kind = op.get("op")
    tasks = plan["tasks"]
    if kind == "set_goal":
        v = op.get("value")
        if not isinstance(v, str):
            return {"ok": False, "error": "set_goal requires a string value"}
        plan["goal"] = v.strip()
        return {"ok": True}

    if kind == "set_requirements":
        v = op.get("value")
        if not isinstance(v, list):
            return {"ok": False, "error": "set_requirements requires a list"}
        plan["requirements"] = [str(x).strip() for x in v if str(x).strip()]
        return {"ok": True}

    if kind == "add_requirement":
        v = op.get("value")
        if not isinstance(v, str) or not v.strip():
            return {"ok": False, "error": "add_requirement requires a non-empty string"}
        plan["requirements"].append(v.strip())
        return {"ok": True}

    if kind == "remove_requirement":
        match = (op.get("match") or "").strip()
        if not match:
            return {"ok": False, "error": "remove_requirement needs a 'match' substring"}
        for i, req in enumerate(plan["requirements"]):
            if match in req:
                plan["requirements"].pop(i)
                return {"ok": True, "removed": req}
        return {"ok": False, "error": "not_found", "match": match}

    if kind == "set_task_text":
        tid = op.get("task_id")
        v = op.get("value")
        if not tid or not isinstance(v, str):
            return {"ok": False, "error": "set_task_text needs task_id + string value"}
        target = _find_task(tasks, str(tid))
        if target is None:
            return {"ok": False, "error": "not_found", "task_id": tid}
        target["text"] = v.strip()
        return {"ok": True}

    if kind == "set_task_status":
        tid = op.get("task_id")
        v = op.get("value")
        if not tid or v not in _VALID_STATUS:
            return {"ok": False, "error": (
                "set_task_status needs task_id + status in "
                f"{sorted(_VALID_STATUS)}")}
        target = _find_task(tasks, str(tid))
        if target is None:
            return {"ok": False, "error": "not_found", "task_id": tid}
        target["status"] = v
        return {"ok": True}

    if kind == "add_task":
        raw = op.get("task")
        if raw is None:
            return {"ok": False, "error": "add_task needs a 'task' field"}
        new = _clean_task(raw, len(tasks) + 1)
        # Ensure the auto id doesn't collide.
        while _find_task(tasks, new["id"]) is not None:
            new["id"] = _next_unique_id(tasks)
        after_id = op.get("after_id")
        if after_id:
            for i, t in enumerate(tasks):
                if t.get("id") == after_id:
                    tasks.insert(i + 1, new)
                    return {"ok": True, "added": new["id"]}
            return {"ok": False, "error": "not_found", "after_id": after_id}
        tasks.append(new)
        return {"ok": True, "added": new["id"]}

    if kind == "add_subtask":
        parent_id = op.get("parent_id")
        raw = op.get("task")
        if not parent_id or raw is None:
            return {"ok": False, "error": "add_subtask needs parent_id + task"}
        parent = _find_task(tasks, str(parent_id))
        if parent is None:
            return {"ok": False, "error": "not_found", "parent_id": parent_id}
        parent.setdefault("subtasks", [])
        idx = len(parent["subtasks"]) + 1
        new = _clean_task(raw, idx, parent_id=str(parent_id))
        while _find_task(tasks, new["id"]) is not None:
            idx += 1
            new["id"] = f"{parent_id}.{idx}"
        parent["subtasks"].append(new)
        return {"ok": True, "added": new["id"]}

    if kind == "remove_task":
        tid = op.get("task_id")
        if not tid:
            return {"ok": False, "error": "remove_task needs task_id"}
        if _remove_task(tasks, str(tid)):
            return {"ok": True, "removed": tid}
        return {"ok": False, "error": "not_found", "task_id": tid}

    if kind == "replace_in_field":
        field = op.get("field")
        find = op.get("find")
        replace = op.get("replace", "")
        if field not in ("goal",) or not isinstance(find, str):
            return {"ok": False, "error": (
                "replace_in_field needs field='goal' and a 'find' string")}
        before = plan.get(field) or ""
        if find not in before:
            return {"ok": False, "error": "not_found", "find": find}
        plan[field] = before.replace(find, replace)
        return {"ok": True, "field": field}

    if kind == "replace_in_task":
        tid = op.get("task_id")
        find = op.get("find")
        replace = op.get("replace", "")
        if not tid or not isinstance(find, str):
            return {"ok": False, "error": (
                "replace_in_task needs task_id + 'find' string")}
        target = _find_task(tasks, str(tid))
        if target is None:
            return {"ok": False, "error": "not_found", "task_id": tid}
        before = target.get("text") or ""
        if find not in before:
            return {"ok": False, "error": "not_found", "find": find}
        target["text"] = before.replace(find, replace)
        return {"ok": True, "task_id": tid}

    return {"ok": False, "error": f"unknown op {kind!r}"}


# ── plan_reconcile — LLM-driven plan refresh ────────────────────────────
#
# When the user pivots direction mid-session (e.g. "switch from Tic Tac
# Toe to a Three.js racing game"), the agent often updates only the goal
# field via ``plan_edit(set_goal=...)`` and leaves stale tasks +
# requirements behind. ``plan_reconcile`` is the targeted fix: it asks
# the LLM, given the current plan + recent chat, which ``plan_edit`` ops
# would bring tasks + requirements back into agreement with the goal —
# and applies those ops automatically.
#
# Implementation: a closure over the engine ref so the tool can call
# ``engine._llm_complete``. Built in ``build_plan_skill`` and wired only
# when an engine reference is supplied (older callers without an engine
# get every other plan tool but not reconcile, which is fine — the agent
# can still call ``plan_set`` to fully replace the plan).


_RECONCILE_PROMPT = (
    "You are a plan reconciliation agent. The user has shifted the goal "
    "of an ongoing session and the existing tasks + requirements may now "
    "be stale. Given the CURRENT plan and the RECENT CHAT, return a JSON "
    "object describing which plan_edit operations should be applied to "
    "bring the tasks + requirements back into agreement with the goal.\n\n"
    "Current plan (JSON):\n{plan_json}\n\n"
    "Recent chat (most-recent last):\n{chat}\n\n"
    "Operations vocabulary (each op is a dict with an 'op' key):\n"
    "  - set_requirements:  {{op: 'set_requirements', value: [string, ...]}}\n"
    "  - add_requirement:   {{op: 'add_requirement', value: string}}\n"
    "  - remove_requirement:{{op: 'remove_requirement', match: substring}}\n"
    "  - set_task_text:     {{op: 'set_task_text', task_id: 't1', value: string}}\n"
    "  - set_task_status:   {{op: 'set_task_status', task_id: 't1', value: 'pending'|'in_progress'|'done'}}\n"
    "  - add_task:          {{op: 'add_task', task: {{text: string}} }}\n"
    "  - remove_task:       {{op: 'remove_task', task_id: 't1'}}\n"
    "  - replace_in_task:   {{op: 'replace_in_task', task_id: 't1', find: substring, replace: string}}\n\n"
    "Rules:\n"
    "  - If the existing tasks + requirements ARE consistent with the new "
    "goal, return {{\"ops\": []}} verbatim.\n"
    "  - Prefer surgical edits (replace_in_task, remove_task) over full "
    "rewrites — preserve task ids and any 'done' progress that's still "
    "valid.\n"
    "  - Don't invent ops that aren't in the vocabulary.\n"
    "  - Return ONLY a JSON object of the form "
    "  {{\"ops\": [...], \"reasoning\": \"<one sentence>\"}}. No markdown, "
    "no commentary outside the JSON.\n"
)


def _build_plan_reconcile(variable_store, engine_getter):
    """Build the ``plan_reconcile`` handler.

    ``engine_getter`` is a callable returning the active engine (or None).
    Late binding means we can register the plan skill BEFORE the engine
    is constructed — the session manager fills in the engine reference
    afterwards via the same shared closure cell.
    """

    async def plan_reconcile(
        chat_excerpt: str | None = None,
        max_ops:      int = 12,
        **_extra,
    ) -> dict:
        engine_ref = engine_getter() if callable(engine_getter) else engine_getter
        """
        Re-align the current plan with the latest conversation context.

        - ``chat_excerpt`` (optional): a string the agent can pass with the
          relevant snippet from the conversation. When empty, the engine's
          history tail is sampled automatically.
        - ``max_ops``: cap on how many edit operations the LLM may
          propose in one call. Defaults to 12.

        Returns ``{ok, applied, ops, reasoning, plan}``. ``applied`` is the
        number of operations that succeeded; failures are itemised in
        ``failed_ops``. The plan in the variable store is the post-apply
        state.
        """
        if engine_ref is None:
            return {
                "error": "engine_unavailable",
                "hint": (
                    "plan_reconcile needs an LLM caller — run it from a "
                    "ChikaEngine session, not raw plan_skill."
                ),
            }

        var = variable_store.get("plan")
        if var is None or not isinstance(var.value, dict):
            return {"error": "no_plan", "hint": "call plan_set first"}
        plan = dict(var.value)

        # Build a chat excerpt from the engine's history if the caller
        # didn't supply one. We use the last ~10 user/assistant turns,
        # truncated, so the prompt stays small.
        if not chat_excerpt:
            history = list(getattr(engine_ref, "_history", []) or [])[-10:]
            lines: list[str] = []
            for msg in history:
                role = msg.get("role", "")
                if role not in ("user", "assistant"):
                    continue
                content = msg.get("content")
                if not isinstance(content, str):
                    continue
                snippet = content.strip().replace("\n", " ")
                if len(snippet) > 400:
                    snippet = snippet[:400] + "…"
                lines.append(f"[{role}] {snippet}")
            chat_excerpt = "\n".join(lines) or "(no prior turns)"

        prompt = _RECONCILE_PROMPT.format(
            plan_json=json.dumps(
                {
                    "goal":         plan.get("goal", ""),
                    "requirements": plan.get("requirements", []),
                    "tasks":        plan.get("tasks", []),
                },
                indent=2,
                ensure_ascii=False,
            ),
            chat=chat_excerpt,
        )

        try:
            raw = await engine_ref._llm_complete(prompt)
        except Exception as exc:
            return {
                "error":  "llm_call_failed",
                "detail": f"{type(exc).__name__}: {exc}",
            }

        # Be tolerant — some models wrap JSON in fences.
        import re as _re
        m = _re.search(r"\{.*\}", (raw or "").strip(), _re.DOTALL)
        parsed: dict = {}
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = {}

        ops = parsed.get("ops") or []
        if not isinstance(ops, list):
            ops = []
        if len(ops) > max_ops:
            ops = ops[:max_ops]

        if not ops:
            return {
                "_source":   "plan_reconcile",
                "applied":   0,
                "ops":       [],
                "reasoning": parsed.get("reasoning") or "no changes needed",
                "plan":      plan,
            }

        # Apply ops via the existing dispatcher to inherit its validation.
        plan["tasks"] = list(plan.get("tasks") or [])
        plan.setdefault("requirements", list(plan.get("requirements") or []))
        plan.setdefault("goal", plan.get("goal") or "")
        results: list[dict] = []
        for i, op in enumerate(ops):
            if not isinstance(op, dict):
                results.append({"index": i, "ok": False,
                                "error": "op must be a dict"})
                continue
            outcome = _apply_plan_op(plan, op)
            outcome["index"] = i
            outcome["op"]    = op.get("op")
            results.append(outcome)

        for top in plan["tasks"]:
            _recompute_parent_status(top)

        plan["updated_at"] = time.time()
        variable_store.set("plan", plan, VarType.JSON,
                           description="Session task plan",
                           source="plan:reconcile")

        applied = sum(1 for r in results if r.get("ok"))
        failed  = [r for r in results if not r.get("ok")]
        return {
            "_source":   "plan_reconcile",
            "applied":   applied,
            "failed":    len(failed),
            "ops":       results,
            "reasoning": parsed.get("reasoning") or "",
            "plan":      plan,
        }

    return plan_reconcile


def _make_plan_tools(variable_store, memory_getter=None):
    """Closure-build the eight plan tools.

    ``memory_getter`` is an optional no-arg callable returning the
    active profile's MemoryManager. ``plan_archive`` calls it when set
    to drop a one-line summary of the archived plan into the profile's
    memory.md so the agent sees "we shipped X last session" in future
    system prompts.
    """

    async def plan_set(tasks: list | None = None,
                       goal: str | None = None,
                       requirements: list[str] | None = None,
                       **_extra) -> dict:
        """
        Set the plan for this session. Replaces any existing plan.

        Verbose-plan fields:
        - ``goal`` (str): one-sentence aim of the whole job. Helps the
          agent re-orient on long sessions.
        - ``requirements`` (list[str]): explicit constraints / must-haves
          ("must work offline", "no React", "needs to compile on 3.14").
          Surfaced in the rendered plan and the system prompt.
        - ``tasks`` (list): top-level tasks. Each may include
          ``subtasks: [...]`` for nested work — a parent's status is
          derived from its sub-tasks.

        Aliases — the LLM often picks a near-synonym for ``tasks``;
        ``steps`` / ``items`` / ``list`` / ``plan`` / ``todos`` all
        resolve. ``aim`` / ``objective`` resolve for ``goal``;
        ``constraints`` / ``musts`` for ``requirements``.
        """
        if tasks is None:
            for alias in ("steps", "items", "list", "plan", "todos"):
                v = _extra.get(alias)
                if isinstance(v, list):
                    tasks = v
                    break
        if not isinstance(tasks, list) or not tasks:
            return {"error": (
                "plan_set requires a non-empty list of tasks. "
                "Pass as `tasks=[...]` (aliases: steps, items, list, plan, todos)."
            )}
        if goal is None:
            goal = _extra.get("aim") or _extra.get("objective")
        if requirements is None:
            requirements = (_extra.get("constraints") or _extra.get("musts")
                             or _extra.get("must_have"))
        if isinstance(requirements, str):
            requirements = [requirements]
        if not isinstance(requirements, list):
            requirements = []

        cleaned = [_clean_task(t, i) for i, t in enumerate(tasks, start=1)]
        for t in cleaned:
            _recompute_parent_status(t)
        # Default: first leaf-task is in_progress, rest pending
        if not any(_any_in_progress(t) for t in cleaned):
            for t in cleaned:
                _promote_first_pending_leaf(t)
                if _any_in_progress(t):
                    break
        plan = {
            "goal":         (goal or "").strip(),
            "requirements": [r.strip() for r in requirements if r and r.strip()],
            "tasks":        cleaned,
            "created_at":   time.time(),
            "updated_at":   time.time(),
        }
        variable_store.set("plan", plan, VarType.JSON,
                           description="Session task plan",
                           source="plan:set")
        return {"_source": "plan_set", "count": len(cleaned), "plan": plan}

    async def plan_update(task_id: str | None = None,
                          status: str | None = None,
                          text: str | None = None,
                          **_extra) -> dict:
        """
        Update a single task's status anywhere in the tree (including
        sub-tasks). Auto-recomputes parent statuses from their sub-tasks
        and auto-promotes the next pending leaf when the current
        in-progress leaf is closed.

        Tolerates LLM kwarg drift — accepts ``id`` / ``task`` / ``taskId``
        for ``task_id``, and ``state`` / ``new_status`` for ``status``.
        """
        if task_id is None:
            task_id = _extra.get("id") or _extra.get("task") or _extra.get("taskId")
        if status is None:
            status = _extra.get("state") or _extra.get("new_status")
        if not task_id:
            return {"error": "plan_update requires a task_id (alias: id, task)"}
        if not status:
            return {"error": "plan_update requires a status (pending|in_progress|done)"}
        if status not in _VALID_STATUS:
            return {"error": f"invalid status {status!r}; must be one of {sorted(_VALID_STATUS)}"}
        var = variable_store.get("plan")
        if var is None or not isinstance(var.value, dict):
            return {"error": "no plan set yet — call plan_set first"}
        plan = dict(var.value)
        tasks = list(plan.get("tasks") or [])

        # Find the target task ANYWHERE in the tree (top-level or nested).
        target = _find_task(tasks, str(task_id))
        if target is None:
            return {"error": f"task_id {task_id!r} not found in current plan"}
        target["status"] = status
        if text:
            target["text"] = text

        # Recompute every parent's status from its sub-tasks. This makes
        # "parent is done iff every leaf is done" an automatic invariant
        # the agent can rely on.
        for top_task in tasks:
            _recompute_parent_status(top_task)

        # Auto-promote the next pending leaf when we close one out and
        # nothing else is in_progress.
        any_in_progress_anywhere = any(
            _any_in_progress(t) for t in tasks
        )
        if status == "done" and not any_in_progress_anywhere:
            for top_task in tasks:
                if _promote_first_pending_leaf(top_task):
                    _recompute_parent_status(top_task)
                    break

        plan["tasks"] = tasks
        plan["updated_at"] = time.time()
        variable_store.set("plan", plan, VarType.JSON,
                           description="Session task plan",
                           source="plan:update")
        return {"_source": "plan_update", "plan": plan}

    async def plan_get(**_extra) -> dict:
        var = variable_store.get("plan")
        if var is None or not isinstance(var.value, dict):
            return {"_source": "plan_get", "plan": None, "message": "no plan set"}
        return {"_source": "plan_get", "plan": var.value}

    async def plan_add(tasks: list | None = None,
                       after_id: str | None = None, **_extra) -> dict:
        """Append tasks to the current plan without replacing it.

        - ``tasks``: list of strings or {id, text, status} dicts
        - ``after_id``: insert immediately after this task id (default: append to end)

        Returns the full updated plan. New tasks default to ``pending``.
        Use this when the agent discovers extra work mid-job that wasn't in
        the original plan_set. Same alias handling as ``plan_set``.
        """
        if tasks is None:
            for alias in ("steps", "items", "list", "plan", "todos"):
                v = _extra.get(alias)
                if isinstance(v, list):
                    tasks = v
                    break
        if not isinstance(tasks, list) or not tasks:
            return {"error": (
                "plan_add requires a non-empty list of tasks "
                "(aliases accepted: steps, items, list, plan, todos)."
            )}
        var = variable_store.get("plan")
        if var is None or not isinstance(var.value, dict):
            # No plan yet — bootstrap one.
            return await plan_set(tasks)
        plan = dict(var.value)
        existing = list(plan.get("tasks") or [])
        # Generate non-colliding ids for new tasks
        used_ids = {t.get("id") for t in existing if isinstance(t, dict)}
        next_n = max(
            (int(tid[1:]) for tid in used_ids
             if isinstance(tid, str) and tid.startswith("t") and tid[1:].isdigit()),
            default=len(existing),
        )
        cleaned: list[dict] = []
        for raw in tasks:
            next_n += 1
            t = _clean_task(raw, next_n)
            # Ensure unique id
            while t["id"] in used_ids:
                next_n += 1
                t["id"] = f"t{next_n}"
            used_ids.add(t["id"])
            cleaned.append(t)

        if after_id:
            insert_at = next(
                (i for i, t in enumerate(existing) if t.get("id") == after_id),
                None,
            )
            if insert_at is None:
                return {"error": f"after_id {after_id!r} not found in plan"}
            existing[insert_at + 1:insert_at + 1] = cleaned
        else:
            existing.extend(cleaned)

        plan["tasks"] = existing
        plan["updated_at"] = time.time()
        variable_store.set("plan", plan, VarType.JSON,
                           description="Session task plan",
                           source="plan:add")
        return {
            "_source": "plan_add",
            "added":   [t["id"] for t in cleaned],
            "plan":    plan,
        }

    async def plan_remove(task_ids: list | str | None = None, **_extra) -> dict:
        """Drop one or more tasks from the plan.

        Accepts a single id string or a list of ids. Useful when:
          - a task you marked ``done`` has shipped and you want it out of the
            visible queue, or
          - the user changes direction and the task is no longer needed.

        Tasks not found are reported in the result rather than raising.
        Aliases — ``ids``, ``id``, ``task_id``, ``tasks`` accepted.
        """
        if task_ids is None:
            for alias in ("ids", "id", "task_id", "tasks"):
                v = _extra.get(alias)
                if v is not None:
                    task_ids = v
                    break
        if isinstance(task_ids, str):
            task_ids = [task_ids]
        if not isinstance(task_ids, list) or not task_ids:
            return {"error": "plan_remove requires a task id or list of ids"}
        var = variable_store.get("plan")
        if var is None or not isinstance(var.value, dict):
            return {"error": "no plan set yet"}
        plan = dict(var.value)
        existing = list(plan.get("tasks") or [])
        wanted = set(str(tid) for tid in task_ids)
        kept = [t for t in existing if t.get("id") not in wanted]
        removed = [t["id"] for t in existing if t.get("id") in wanted]
        not_found = sorted(wanted - set(removed))

        # Auto-promote next pending if we removed the in_progress one.
        if not any(t.get("status") == "in_progress" for t in kept):
            for t in kept:
                if t.get("status") == "pending":
                    t["status"] = "in_progress"
                    break

        plan["tasks"] = kept
        plan["updated_at"] = time.time()
        variable_store.set("plan", plan, VarType.JSON,
                           description="Session task plan",
                           source="plan:remove")
        return {
            "_source":   "plan_remove",
            "removed":   removed,
            "not_found": not_found,
            "plan":      plan,
        }

    async def plan_edit(operations: list | None = None, **_extra) -> dict:
        """Apply a list of structured patches to the current plan in one call.

        Each ``operation`` is a dict with an ``op`` field plus the keys
        relevant to that op. Operations are applied IN ORDER; if one
        fails the rest still attempt and the result lists per-op outcomes
        so the agent can see exactly what landed.

        Supported ops:

        | op                    | required keys                   | behaviour |
        |-----------------------|---------------------------------|-----------|
        | ``set_goal``          | ``value`` (string)              | Replace ``$plan.goal``. |
        | ``set_requirements``  | ``value`` (list of strings)     | Replace the entire requirements list. |
        | ``add_requirement``   | ``value`` (string)              | Append one requirement. |
        | ``remove_requirement``| ``match`` (string)              | Drop the first requirement containing ``match``. |
        | ``set_task_text``     | ``task_id``, ``value``          | Edit a task's text (anywhere in the tree). |
        | ``set_task_status``   | ``task_id``, ``value``          | Set status; auto-roll-up still applies. |
        | ``add_task``          | ``task`` (dict or string), ``after_id?`` | Append a top-level task or insert after id. |
        | ``add_subtask``       | ``parent_id``, ``task``         | Append a sub-task to a parent. |
        | ``remove_task``       | ``task_id``                     | Delete a task (and its sub-tree). |
        | ``replace_in_field``  | ``field`` (``goal``), ``find``, ``replace`` | Substring replace within a top-level field. |
        | ``replace_in_task``   | ``task_id``, ``find``, ``replace`` | Substring replace within a task's text. |

        ``replace_in_field`` and ``replace_in_task`` use plain substring
        matching — the user calls this "fingerprint". Choose a unique
        enough fragment that it won't false-match. The op fails (returns
        ``not_found``) when ``find`` doesn't appear in the target.

        Use this instead of re-running ``plan_set`` when the user says
        things like "swap WebAssembly for WebGPU" or "add a 'must work
        offline' requirement" — surgical edits keep status/progress.
        """
        if operations is None:
            operations = (_extra.get("ops") or _extra.get("patches")
                          or _extra.get("changes") or [])
        if not isinstance(operations, list) or not operations:
            return {"error":
                    "plan_edit requires a non-empty list of operations"}

        var = variable_store.get("plan")
        if var is None or not isinstance(var.value, dict):
            return {"error": "no plan set yet — call plan_set first"}

        plan = dict(var.value)
        plan["tasks"] = list(plan.get("tasks") or [])
        plan.setdefault("requirements", list(plan.get("requirements") or []))
        plan.setdefault("goal", plan.get("goal") or "")

        results: list[dict] = []
        for i, op_dict in enumerate(operations):
            if not isinstance(op_dict, dict):
                results.append({"index": i, "ok": False,
                                "error": "op must be a dict"})
                continue
            outcome = _apply_plan_op(plan, op_dict)
            outcome["index"] = i
            outcome["op"] = op_dict.get("op")
            results.append(outcome)

        # After all edits, recompute parent statuses from sub-task state.
        for top in plan["tasks"]:
            _recompute_parent_status(top)

        plan["updated_at"] = time.time()
        variable_store.set("plan", plan, VarType.JSON,
                           description="Session task plan",
                           source="plan:edit")

        applied = sum(1 for r in results if r.get("ok"))
        failed = [r for r in results if not r.get("ok")]
        # Auto-reconcile flag: when an op landed that materially changed
        # the goal or the requirements (the two fields that make tasks
        # drift), the engine fires plan_reconcile on the next step so
        # the agent doesn't have to remember to do it manually.
        _RECONCILE_TRIGGERS = frozenset({
            "set_goal", "replace_in_field",
            "set_requirements", "add_requirement", "remove_requirement",
        })
        triggered = any(
            r.get("ok") and (r.get("op") in _RECONCILE_TRIGGERS)
            for r in results
        )
        return {
            "_source":          "plan_edit",
            "applied":          applied,
            "failed":           len(failed),
            "results":          results,
            "plan":             plan,
            "_auto_reconcile":  triggered,
        }

    async def plan_archive(reason: str = "", **_extra) -> dict:
        """Retire the active plan and stash it in ``$plan_archive``.

        Use this when a plan is fully shipped (or abandoned) and you
        want a clean slate for the next job. The plan is NOT deleted —
        every archived plan is kept on a per-session list so you can
        ``plan_history`` to look at past plans, and the *current*
        ``$plan`` becomes empty so the system prompt + UI panels stop
        showing it.

        ``reason`` is an optional one-liner the archive remembers
        (e.g. "shipped", "abandoned — user pivoted", "superseded by
        plan_set on 2026-05-12"). Saved alongside the plan so future
        retrospectives see why it was archived.
        """
        var = variable_store.get("plan")
        if var is None or not isinstance(var.value, dict):
            return {
                "_source": "plan_archive",
                "archived": False,
                "note":     "no active plan to archive",
            }
        plan = dict(var.value)
        plan["archived_at"] = time.time()
        if reason and reason.strip():
            plan["archive_reason"] = reason.strip()[:200]

        existing = variable_store.get("plan_archive")
        history = list(existing.value) if existing and isinstance(
            existing.value, list,
        ) else []
        history.append(plan)
        # Cap the history at 25 entries so a long-running session doesn't
        # leak unbounded memory. Newest stays, oldest gets popped.
        history = history[-25:]
        variable_store.set(
            "plan_archive", history, VarType.JSON,
            description="Past plans archived from this session",
            source="plan:archive",
        )
        # Clear the current plan so prompts + UI panels go blank.
        variable_store.delete("plan")

        # Auto-memory: persist a one-line summary of the archived plan
        # to the profile's memory.md so future sessions recall what
        # was attempted. The summary stays short (one line) so the
        # memory file doesn't bloat over time. ``memory_getter``
        # resolves the live MemoryManager — when None (tests / minimal
        # engines) we just skip the persistence.
        memory_line = ""
        if callable(memory_getter):
            try:
                mm = memory_getter()
            except Exception:
                mm = None
            if mm is not None:
                goal = (plan.get("goal") or "").strip()[:160]
                tasks = plan.get("tasks") or []
                done = sum(
                    1 for t in tasks
                    if isinstance(t, dict) and t.get("status") == "done"
                )
                stamp = time.strftime("%Y-%m-%d")
                bits = [f"[{stamp}] plan archived"]
                if goal:
                    bits.append(f"goal: {goal}")
                bits.append(f"tasks done: {done}/{len(tasks)}")
                if reason and reason.strip():
                    bits.append(f"reason: {reason.strip()[:120]}")
                memory_line = " — ".join(bits)
                try:
                    mm.persist(f"plan_{int(plan.get('archived_at', 0))}",
                               memory_line)
                except Exception:
                    # Memory write is best-effort: never fail the
                    # archive call because the memory file is
                    # inaccessible.
                    memory_line = ""

        return {
            "_source":     "plan_archive",
            "archived":    True,
            "count":       len(history),
            "plan":        plan,
            "memory_line": memory_line or None,
        }

    async def plan_history(limit: int = 5, **_extra) -> dict:
        """Return the archived plans from this session, newest first.

        Use to reference a past plan ("what did the original Tic Tac
        Toe plan look like before we pivoted?") without bringing it
        back as the active plan. To re-activate, copy the tasks /
        goal into a fresh ``plan_set`` call.
        """
        var = variable_store.get("plan_archive")
        history = list(var.value) if var and isinstance(var.value, list) else []
        # Newest first.
        history = list(reversed(history))
        if limit and limit > 0:
            history = history[:limit]
        return {
            "_source": "plan_history",
            "count":   len(history),
            "plans":   history,
        }

    return (plan_set, plan_update, plan_get, plan_add, plan_remove,
            plan_edit, plan_archive, plan_history)


def _make_plan_prompt_section(variable_store):
    """Tiny per-turn block: goal + which task is in_progress.

    Surfacing this in the system prompt every turn means the agent
    doesn't need to re-read $plan to remember which task it's working
    on — and won't slip back into "what was I doing?" on long sessions.
    Empty string when no plan exists; the prompt builder skips empty
    contributions so we don't pay anything when planning is off.
    """
    def render() -> str:
        var = variable_store.get("plan")
        if var is None or not isinstance(var.value, dict):
            return ""
        plan = var.value
        goal = (plan.get("goal") or "").strip()
        tasks = plan.get("tasks") or []
        if not isinstance(tasks, list) or not tasks:
            return ""
        # Walk the tree to find the first leaf task in_progress.
        in_progress_text = ""
        in_progress_id   = ""

        def _walk(items):
            nonlocal in_progress_text, in_progress_id
            for t in items:
                if not isinstance(t, dict):
                    continue
                subs = t.get("subtasks") or []
                if subs:
                    _walk(subs)
                elif (
                    not in_progress_text
                    and t.get("status") == "in_progress"
                ):
                    in_progress_text = (t.get("text") or "").strip()
                    in_progress_id = t.get("id") or ""
        _walk(tasks)

        # Counts for a quick "how far along".
        leaves = []
        def _count(items):
            for t in items:
                if not isinstance(t, dict):
                    continue
                subs = t.get("subtasks") or []
                if subs:
                    _count(subs)
                else:
                    leaves.append(t)
        _count(tasks)
        done = sum(1 for l in leaves if l.get("status") == "done")
        total = len(leaves)

        lines = [
            "## Active plan",
            "",
            f"- progress: **{done}/{total}** leaves done",
        ]
        if goal:
            lines.append(f"- goal: {goal[:140]}")
        if in_progress_text:
            lines.append(
                f"- in progress: `{in_progress_id}` — {in_progress_text[:120]}"
            )
        lines.append("")
        lines.append(
            "Tick the in-progress task with `plan_update(task_id, "
            "status=\"done\")` IN THE SAME WORKFLOW that finishes it. "
            "If you discover new work, `plan_add` it instead of "
            "rewriting with `plan_set`."
        )
        return "\n".join(lines)

    return render


def build_plan_skill(variable_store, engine_getter=None,
                     memory_getter=None) -> Skill:
    """Build the plan skill.

    ``engine_getter`` is a no-arg callable returning the engine (or None).
    Required for ``plan_reconcile`` to make LLM calls. Without it
    ``plan_reconcile`` returns a clear ``engine_unavailable`` error
    rather than silently misbehaving. Late-binding via a getter lets
    the session manager register the skill BEFORE the engine exists,
    then patch the getter to return the engine post-construction.

    ``memory_getter`` is an optional no-arg callable returning the
    active profile's MemoryManager. When supplied, ``plan_archive``
    drops a one-line summary into the profile memory so future
    sessions remember past plans without keeping them as the live
    ``$plan``.
    """
    (plan_set, plan_update, plan_get, plan_add, plan_remove,
     plan_edit, plan_archive, plan_history) = _make_plan_tools(
        variable_store, memory_getter=memory_getter,
    )
    plan_reconcile = _build_plan_reconcile(variable_store, engine_getter)
    section = _make_plan_prompt_section(variable_store)
    return Skill(
        name="plan",
        description="Session-scoped task planning (decompose big jobs, track progress)",
        tools=[
            ToolDefinition(
                name="plan_set",
                description=(
                    "Set the task plan at the start of any multi-step job. "
                    "Verbose by design: include `goal` (one-sentence aim), "
                    "`requirements` (the user's must-haves), and `tasks` (ordered "
                    "list, each optionally with `subtasks` for nested work). "
                    "Sub-task statuses auto-roll up — a parent is done iff "
                    "every leaf is done. The first pending leaf is auto-marked "
                    "in_progress. Use plan_update to track progress; plan_add "
                    "to insert work mid-job; plan_remove to drop completed-and-"
                    "shipped items. See plan SKILL.md for the verbose template."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "One-sentence aim of the whole job (e.g. 'Build a powder-toy clone in vanilla JS').",
                        },
                        "requirements": {
                            "type":  "array",
                            "items": {"type": "string"},
                            "description": "Explicit constraints / must-haves stated by the user or obvious from the work (e.g. 'must run offline').",
                        },
                        "tasks": {
                            "type": "array",
                            "items": {"type": ["string", "object"]},
                            "description": (
                                "Ordered top-level tasks. Strings become "
                                "pending tasks; objects {id, text, status, "
                                "subtasks} allow explicit control. Each task "
                                "may include a `subtasks` list of the same "
                                "shape — sub-statuses auto-roll up."
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
            ToolDefinition(
                name="plan_add",
                description=(
                    "Append tasks to the active plan WITHOUT replacing it. "
                    "Use when you discover new work mid-job. Optional "
                    "`after_id` inserts the new tasks immediately after a "
                    "specific existing task id."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "tasks": {
                            "type":  "array",
                            "items": {"type": ["string", "object"]},
                            "description": "New tasks to add (strings or {id, text, status} dicts).",
                        },
                        "after_id": {
                            "type": "string",
                            "description": "Optional: insert after this task id; default is append at end.",
                        },
                    },
                    "required": ["tasks"],
                },
                handler=plan_add,
            ),
            ToolDefinition(
                name="plan_remove",
                description=(
                    "Drop one or more tasks from the plan. Pass a task id "
                    "string or a list. Use this to clear out completed "
                    "work from the visible queue, or to cancel tasks the "
                    "user no longer wants."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "task_ids": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ],
                            "description": "Single task id or list of ids to remove.",
                        },
                    },
                    "required": ["task_ids"],
                },
                handler=plan_remove,
            ),
            ToolDefinition(
                name="plan_edit",
                description=(
                    "Apply a list of structured patches to the active plan in "
                    "one call (set_goal, set/add/remove_requirement, "
                    "set_task_text, set_task_status, add_task, add_subtask, "
                    "remove_task, replace_in_field, replace_in_task). Use "
                    "this when the user asks for a tweak (\"swap WebAssembly "
                    "for WebGPU\", \"add a 'must work offline' requirement\", "
                    "\"insert a UI polish task after t3\") instead of "
                    "rewriting the whole plan with plan_set — surgical edits "
                    "preserve task ids and progress. Each op is applied in "
                    "order; failures don't block the rest. See plan SKILL.md "
                    "for the full op reference."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "operations": {
                            "type":  "array",
                            "items": {"type": "object"},
                            "description": (
                                "Ordered list of {op, ...} patches. Each op "
                                "has its own required keys — see SKILL.md."
                            ),
                        },
                    },
                    "required": ["operations"],
                },
                handler=plan_edit,
            ),
            ToolDefinition(
                name="plan_reconcile",
                description=(
                    "Refresh the plan against the latest conversation context. "
                    "Runs an internal LLM call that compares the current goal + "
                    "requirements + tasks against the recent chat tail and "
                    "applies any plan_edit operations needed to bring stale "
                    "tasks/requirements back in line with the goal. Use this "
                    "right after the user pivots direction (e.g. 'switch to "
                    "Three.js racing'); the agent should call plan_reconcile "
                    "after plan_edit(set_goal=...) so tasks don't drift. "
                    "Returns {applied, ops, reasoning, plan}; reasoning is the "
                    "LLM's one-sentence justification. If nothing needs "
                    "changing it returns applied=0 and ops=[]."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "chat_excerpt": {
                            "type": "string",
                            "description": (
                                "Optional chat snippet to consult. When empty "
                                "the engine samples the recent history tail."
                            ),
                        },
                        "max_ops": {
                            "type": "integer",
                            "description": (
                                "Cap on operations the reconcile pass may "
                                "propose in one call. Default 12."
                            ),
                        },
                    },
                },
                handler=plan_reconcile,
            ),
            ToolDefinition(
                name="plan_archive",
                description=(
                    "Retire the current plan to ``$plan_archive`` (a per-"
                    "session list of past plans). The active ``$plan`` "
                    "becomes empty so the system prompt + UI panels go "
                    "blank — fresh slate for the next job. Past plans "
                    "are kept; use plan_history to see them. Also writes "
                    "a one-line summary to the profile memory so future "
                    "sessions recall what was attempted. Use this when "
                    "you've shipped a plan in full, or when the user "
                    "explicitly pivots and the old plan is dead. "
                    "Optional ``reason`` is preserved alongside the "
                    "archive entry."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": (
                                "Why this plan is being archived "
                                "('shipped', 'abandoned', 'superseded')."
                            ),
                        },
                    },
                },
                handler=plan_archive,
            ),
            ToolDefinition(
                name="plan_history",
                description=(
                    "Return the list of past archived plans for this "
                    "session, newest first. Use to reference what was "
                    "attempted before without re-activating the plan. "
                    "Default ``limit`` is 5 — pass higher for deeper "
                    "history."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Max archived plans to return (default 5).",
                        },
                    },
                },
                handler=plan_history,
            ),
        ],
        workflow_examples="",
        prompt_section=section,
    )
