"""
WorkflowEngine — executes workflow JSON and yields typed events as an async generator.

Supports all 10 step types:
  sequential, parallel, conditional, loop, map, fan_out, retry, pipeline, sub_workflow
  (event/wait-for-file is handled via loop + wait tool)

Every event is a dict with at minimum {"type": "..."}.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re as _re
import time
from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING, Any

from chika.core.logger import log as _log
from chika.core.tool_registry import ToolRegistry
from chika.core.variable_store import VariableStore

if TYPE_CHECKING:
    from chika.core.engine import LLMCaller

ApprovalHandler = Callable[..., Any]

Event = dict[str, Any]

_STRUCTURAL_TYPES = frozenset({
    "sequential", "parallel", "conditional", "loop",
    "map", "fan_out", "retry", "pipeline", "sub_workflow",
})

# Tools that produce factual material the LLM may cite.
# Their results are auto-appended to the $facts ledger so every later turn
# has a single place to check whether a claim is grounded.
_FACT_PRODUCING_TOOLS = frozenset({
    "web_search", "web_fetch", "file_read", "shell_exec", "verify_url",
    "curl", "memory_recall",
    "git_log", "git_status", "git_diff", "git_branch",
})


def _looks_empty(value: Any) -> bool:
    """
    Heuristic: does this value look empty/missing/unresolved?
    Used to refuse llm_transform / llm_summarise on garbage input — feeding an
    LLM empty context is the #1 hallucination vector.
    """
    if value is None:
        return True
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return True
        # Unresolved $variable references pass through as literal "$foo"
        if s.startswith("$") and " " not in s:
            return True
        return False
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    if isinstance(value, dict):
        if not value:
            return True
        # web_search shape: {"query": "...", "results": [], "count": 0}
        if value.get("count") == 0 and not value.get("results"):
            return True
        if "results" in value and isinstance(value["results"], list) and not value["results"]:
            return True
        # error dict
        if "error" in value and len(value) <= 2:
            return True
        return False
    return False


class WorkflowEngine:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        variable_store: VariableStore,
        llm_caller: LLMCaller | None = None,
        approval_handler: ApprovalHandler | None = None,
    ) -> None:
        self._tools = tool_registry
        self._vars = variable_store
        self._llm = llm_caller
        self._sub_workflows: dict[str, list[dict]] = {}
        # approval_handler: async (request_id, tool_name, args) -> bool
        # Set per-WebSocket connection so the handler can talk back to that client.
        self.approval_handler: ApprovalHandler | None = approval_handler
        # question_handler: async (*, request_id, question, options, ...) -> dict
        # Set per-WebSocket connection (None until a WS wires it up).
        self.question_handler: Callable[..., Any] | None = None
        # Tracks which sub-workflow IDs are currently executing to detect circular references
        self._executing_workflow_ids: set[str] = set()

        # ── Skill gate ─────────────────────────────────────────────────────
        #
        # Tracks which skills the agent has already pulled the SKILL.md for
        # in this session. Before any tool belonging to a skill is dispatched,
        # the gate runs ``skill_load`` automatically if the skill hasn't been
        # loaded yet. This makes "always read SKILL.md before using a skill's
        # tools" a runtime invariant rather than a prompt suggestion.
        #
        # Populated by ``set_skill_registry`` so we can reverse-lookup
        # tool → skill at dispatch time.
        self._loaded_skills: set[str] = set()
        self._tool_to_skill: dict[str, str] = {}
        # Tools that are exempt from the gate even if technically owned by
        # a skill. ``skill_load`` and ``skill_query`` can never gate their
        # own call sites — that would block the agent from reading the
        # very docs it needs to satisfy the gate.
        self._skill_gate_exempt: set[str] = {"skill_load", "skill_query"}

    def register_sub_workflow(self, workflow_id: str, steps: list[dict]) -> None:
        self._sub_workflows[workflow_id] = steps

    def set_skill_registry(self, skill_registry: Any) -> None:
        """Wire in the skill registry so the gate can reverse-lookup
        ``tool_name → skill_name``. Called once after the registry is built.
        """
        index: dict[str, str] = {}
        try:
            skills = skill_registry._skills  # type: ignore[attr-defined]
        except AttributeError:
            return
        for skill_name, skill in skills.items():
            for tool in getattr(skill, "tools", []) or []:
                index[tool.name] = skill_name
        self._tool_to_skill = index

    def mark_skill_loaded(self, skill_name: str) -> None:
        """Record that ``skill_name``'s SKILL.md has been pulled this session."""
        if skill_name:
            self._loaded_skills.add(skill_name)

    async def _check_skill_gate(self, tool_name: str) -> dict | None:
        """Refuse-and-retry skill gate.

        If ``tool_name`` belongs to a skill whose SKILL.md hasn't been
        loaded this session, this method:

        1. Loads the SKILL.md by dispatching ``skill_load`` directly (does
           NOT yield events — the caller emits them).
        2. Marks the skill loaded so the same skill never refuses twice.
        3. Returns a dict telling the caller to REFUSE the original tool —
           the agent re-plans on the next turn with the doc in context.

        Returns ``None`` (= pass-through dispatch) when:
        - The tool is in the exempt set (``skill_load`` itself).
        - The tool doesn't belong to any skill.
        - The skill has already been loaded this session.
        - The ``skill_load`` tool isn't registered (defensive degrade).
        - ``skill_load`` failed (e.g. no SKILL.md on disk) — we don't want
          to soft-lock the user out of a skill that simply has no doc yet.
        """
        if tool_name in self._skill_gate_exempt:
            return None
        skill_name = self._tool_to_skill.get(tool_name)
        if not skill_name or skill_name in self._loaded_skills:
            return None

        loader = self._tools.get("skill_load")
        if loader is None:
            # Engine without the loader registered — gate is a silent no-op.
            self._loaded_skills.add(skill_name)
            return None

        sid = f"skill_gate_{skill_name}"
        t0 = time.monotonic()
        try:
            load_result = await self._tools.dispatch(
                "skill_load", {"skill": skill_name},
            )
        except Exception as exc:
            load_result = {"error": f"{type(exc).__name__}: {exc}"}
        duration = int((time.monotonic() - t0) * 1000)
        err = load_result.get("error") if isinstance(load_result, dict) else None

        # Mark loaded regardless — a failed load shouldn't re-trigger.
        self._loaded_skills.add(skill_name)

        # Loader events the caller should yield so the trace shows the
        # auto-load happened (with the 📚 audit badge).
        loader_events = [
            {"type": "tool_call", "step_id": sid, "tool": "skill_load",
             "args": {"skill": skill_name, "_auto": True}},
            {"type": "tool_result", "step_id": sid, "tool": "skill_load",
             "result": load_result, "error": err, "duration_ms": duration},
        ]

        # If the doc itself failed to load, don't lock the user out of the
        # tool — degrade to pass-through (with the loader events visible).
        if err:
            return {
                "skill_name":      skill_name,
                "loader_events":   loader_events,
                "refusal_payload": None,  # don't refuse the tool
            }

        doc = load_result.get("doc") if isinstance(load_result, dict) else ""
        char_count = (
            load_result.get("char_count") if isinstance(load_result, dict) else 0
        )
        return {
            "skill_name":    skill_name,
            "loader_events": loader_events,
            "refusal_payload": {
                "error":         "skill_doc_required",
                "skill":         skill_name,
                "tool_blocked":  tool_name,
                "char_count":    char_count,
                "doc":           doc,
                "hint": (
                    f"`{tool_name}` did NOT run. Reason: {skill_name!r}'s "
                    "SKILL.md had not been loaded — the gate refuses skill "
                    "tools on first use so you re-plan with the doc in "
                    "context. The full SKILL.md is embedded above; the "
                    "skill is now marked loaded for the rest of this "
                    "session. **Generate a new workflow_orchestrator call "
                    "now**, using the doc to pick the right tool, args, "
                    "and order. Subsequent calls to this skill's tools "
                    "will pass through normally."
                ),
            },
        }

    def _profile(self) -> str:
        v = self._vars.get("profile.name")
        return v.value if v else "unknown"

    @staticmethod
    def _count_steps(node: Any) -> int:
        """Recursively count leaf tool steps in a workflow tree."""
        if not isinstance(node, dict):
            return 0
        count = 1 if "tool" in node and "type" not in node else 0
        for key in ("steps", "branches"):
            for child in node.get(key) or []:
                count += WorkflowEngine._count_steps(child)
        for key in ("step", "if_true", "if_false", "then", "fan_in"):
            child = node.get(key)
            if isinstance(child, dict):
                count += WorkflowEngine._count_steps(child)
        return count

    @staticmethod
    def _count_file_writes(node: Any) -> int:
        """Count how many file_write calls are in a workflow tree."""
        if not isinstance(node, dict):
            return 0
        count = 1 if node.get("tool") == "file_write" and "type" not in node else 0
        for key in ("steps", "branches"):
            for child in node.get(key) or []:
                count += WorkflowEngine._count_file_writes(child)
        for key in ("step", "if_true", "if_false", "then", "fan_in"):
            child = node.get(key)
            if isinstance(child, dict):
                count += WorkflowEngine._count_file_writes(child)
        return count

    # Tools that materially change the user's environment. A workflow that
    # combines several of these without any plan_* call is real work that
    # should have a checklist behind it.
    _WRITE_TOOLS: frozenset[str] = frozenset({
        "file_write", "file_replace", "file_edit_lines", "file_append",
        "shell_exec", "bg_shell_exec", "python_run", "live_server",
        "scaffold_web_app",
        "git_commit", "git_push", "git_pull", "git_checkout",
        "git_pr_create", "git_pr_merge",
        "browser_navigate", "browser_click", "browser_fill_input",
        "browser_open_tab",
    })
    # Tools whose presence anywhere in the workflow exempts it from the
    # plan-required gate (the agent is *currently* planning, or breaking
    # out of a stuck state).
    _PLAN_GATE_EXEMPT: frozenset[str] = frozenset({
        "plan_set", "plan_add", "plan_update", "plan_remove", "plan_edit",
        "plan_get", "plan_reconcile", "plan_archive", "plan_history",
    })

    @staticmethod
    def _collect_tool_names(node: Any, out: list[str]) -> None:
        """Walk the workflow tree and accumulate every tool name."""
        if not isinstance(node, dict):
            return
        if "tool" in node and "type" not in node:
            out.append(node["tool"])
        for key in ("steps", "branches"):
            for child in node.get(key) or []:
                WorkflowEngine._collect_tool_names(child, out)
        for key in ("step", "if_true", "if_false", "then", "fan_in"):
            child = node.get(key)
            if isinstance(child, dict):
                WorkflowEngine._collect_tool_names(child, out)

    # ── Project-creation tools that ALWAYS require a plan ─────────────
    # These tools materially start a new project (scaffolding, app
    # bootstraps). The previous threshold-based gate let "scaffold +
    # one or two edits" workflows skip planning entirely; the user
    # consistently saw the agent build a Powder Toy clone with no
    # checklist. Now, ANY workflow that includes one of these tools
    # MUST have an active plan or include a plan_* tool itself.
    _ALWAYS_REQUIRE_PLAN: frozenset[str] = frozenset({
        "scaffold_web_app",
    })

    def _check_plan_required(self, workflow: dict) -> dict | None:
        """Refuse-and-retry: when this workflow does multi-step real
        work or contains a project-creation tool with no active plan
        AND no plan_* tool in the workflow itself, return a refusal
        payload. The caller emits a synthetic ``tool_result`` so the
        LLM re-plans with ``plan_set`` first.

        Three trigger conditions, any one is enough:

        1. **plan_set mixed with write tools in the same workflow** —
           refuse so the user can approve/edit the plan BEFORE write
           tools run. Otherwise the user sees scaffold_web_app's
           approval modal before they've even seen the plan.
        2. **Project-creation tool** (``scaffold_web_app`` + similar) —
           always blocks without a plan, regardless of step count.
           This catches the "build me a clone" pattern that previously
           sneaked under the threshold.
        3. **3+ write-class tool calls** — multi-step real work that
           deserves a checklist. Single edits + scaffolding + verify
           bundles still skip the gate.
        """
        tools: list[str] = []
        self._collect_tool_names(workflow, tools)

        # First gate: plan_set in the same workflow as write tools is a
        # UX bug — the user MUST approve the plan before writes start.
        if "plan_set" in tools:
            mixed_writes = sorted({t for t in tools if t in self._WRITE_TOOLS})
            if mixed_writes:
                return {
                    "error":         "plan_required",
                    "reason":        "plan_set_mixed_with_writes",
                    "write_count":   len(mixed_writes),
                    "writes_used":   mixed_writes,
                    "creation_tools": [
                        t for t in mixed_writes if t in self._ALWAYS_REQUIRE_PLAN
                    ],
                    "hint": (
                        "Workflow contains `plan_set` AND write-class tools "
                        f"({mixed_writes}). The plan-approval gate runs "
                        "AFTER a workflow finishes, so packing them together "
                        "makes the user see write-tool approval prompts "
                        "BEFORE they've seen the plan. Split into TWO "
                        "workflows:\n"
                        "  1. First workflow: ONLY `plan_set` (no other "
                        "tools). The runtime will pause for user approval.\n"
                        "  2. Second workflow (after approval): the actual "
                        "implementation work, no plan_set.\n"
                        "Re-emit just the plan_set call now."
                    ),
                }

        # Other plan_* tools (update/add/remove/etc.) can co-exist with
        # writes — those are progress ticks, not initial plan creation.
        if any(t in self._PLAN_GATE_EXEMPT for t in tools):
            return None

        write_count = sum(1 for t in tools if t in self._WRITE_TOOLS)
        creation_tools = [t for t in tools if t in self._ALWAYS_REQUIRE_PLAN]

        # Skip when nothing crosses the threshold AND nothing is a
        # project-creation tool.
        if write_count < 3 and not creation_tools:
            return None

        # Is there already an active plan?
        try:
            plan_var = self._vars.get("plan")
        except Exception:
            plan_var = None
        if plan_var is not None and isinstance(plan_var.value, dict) \
                and (plan_var.value.get("tasks") or []):
            return None

        if creation_tools:
            reason = (
                f"This workflow runs {creation_tools[0]} (a "
                "project-creation tool) and there's no active plan. "
                "Project creation always requires a plan first — "
                "call `plan_set` with goal + requirements + tasks "
                "(load the planning skill's SKILL.md if you need the "
                "template), then re-emit. Use `plan_set` as the FIRST "
                "step of this workflow if you want to plan + scaffold "
                "in one round-trip."
            )
        else:
            reason = (
                f"This workflow has {write_count} write-class tool calls "
                f"({sorted({t for t in tools if t in self._WRITE_TOOLS})}) "
                "and there's no active plan. The runtime requires a plan "
                "before multi-step real work — call `plan_set` FIRST with "
                "a verbose plan (goal, requirements, tasks with subtasks) "
                "and THEN re-emit your workflow. The planning skill's "
                "SKILL.md has the canonical template (load via "
                "skill_load). Single-step or read-only workflows are "
                "exempt from this gate."
            )

        return {
            "error":            "plan_required",
            "write_count":      write_count,
            "creation_tools":   creation_tools,
            "writes_used":      sorted({t for t in tools if t in self._WRITE_TOOLS}),
            "hint":             reason,
        }

    async def execute(self, workflow: dict) -> AsyncGenerator[Event, None]:
        """Top-level entry: execute a workflow dict and stream events.

        Workflow size guidelines (``MAX_WORKFLOW_STEPS``, ``MAX_FILE_WRITES_PER_WF``)
        are now SOFT limits — if the agent overshoots we emit a
        ``validation_warning`` and keep executing instead of aborting. The
        agent has prompt-side rules to keep workflows small; the runtime's
        job is to actually run the work. A hard ceiling at 10× the soft
        limit still aborts genuinely runaway / accidentally recursive
        workflows so we don't DOS the engine.
        """
        from config import MAX_FILE_WRITES_PER_WF, MAX_WORKFLOW_STEPS
        step_count = self._count_steps(workflow)
        fw_count = self._count_file_writes(workflow)

        # Hard safety ceilings — only triggered for genuinely runaway specs.
        hard_step_cap = max(MAX_WORKFLOW_STEPS * 10, 80)
        hard_fw_cap = max(MAX_FILE_WRITES_PER_WF * 10, 30)
        if step_count > hard_step_cap:
            yield {"type": "error", "message": (
                f"Workflow has {step_count} steps — exceeds the hard safety "
                f"cap of {hard_step_cap}. Refusing to execute. Split the "
                "work across multiple workflows."
            )}
            return
        if fw_count > hard_fw_cap:
            yield {"type": "error", "message": (
                f"Workflow has {fw_count} file_write calls — exceeds the "
                f"hard safety cap of {hard_fw_cap}. Refusing to execute. "
                "Use file_replace / file_append for edits, or split across "
                "workflows."
            )}
            return

        # Soft limits — warn the agent next turn but DO NOT block execution.
        if step_count > MAX_WORKFLOW_STEPS:
            yield {
                "type":     "validation_warning",
                "severity": "low",
                "reason":   "workflow_oversize",
                "message": (
                    f"Workflow has {step_count} steps (soft target is "
                    f"{MAX_WORKFLOW_STEPS}). Executing anyway, but next "
                    "time keep workflows small — use plan_set to outline "
                    "the full job and execute one piece per turn."
                ),
                "step_count":    step_count,
                "soft_limit":    MAX_WORKFLOW_STEPS,
            }
        if fw_count > MAX_FILE_WRITES_PER_WF:
            yield {
                "type":     "validation_warning",
                "severity": "low",
                "reason":   "workflow_oversize_writes",
                "message": (
                    f"Workflow has {fw_count} file_write calls (soft target "
                    f"is {MAX_FILE_WRITES_PER_WF}). Executing anyway. Use "
                    "file_replace / file_append for edits to existing files."
                ),
                "file_writes":  fw_count,
                "soft_limit":   MAX_FILE_WRITES_PER_WF,
            }

        wf_id = workflow.get("id", "workflow")
        wf_name = workflow.get("name", wf_id)

        # ── Plan-required gate ──────────────────────────────────────────
        # Refuse multi-step write workflows that don't have an active plan
        # AND don't include a plan_* tool. Forces the agent to call
        # plan_set first so there's a checklist for the user to track.
        plan_refusal = self._check_plan_required(workflow)
        if plan_refusal is not None:
            sid = "plan_gate"
            _log.info("plan_required_refusal",
                      workflow_id=wf_id,
                      write_count=plan_refusal["write_count"],
                      profile=self._profile())
            yield {"type": "tool_call", "step_id": sid,
                   "tool":   "plan_gate",
                   "args":   {"_auto": True,
                              "writes_used": plan_refusal["writes_used"]}}
            yield {
                "type":         "tool_result",
                "step_id":      sid,
                "tool":         "plan_gate",
                "result":       plan_refusal,
                "error":        "plan_required",
                "duration_ms":  0,
            }
            return

        _log.info("workflow_start", workflow_id=wf_id, name=wf_name, profile=self._profile())
        yield {"type": "workflow_start", "workflow_id": wf_id, "name": wf_name}

        async for event in self._exec_node(workflow):
            yield event

        _log.info("workflow_done", workflow_id=wf_id, profile=self._profile())
        yield {"type": "workflow_done", "workflow_id": wf_id,
               "variables": {k: v.value for k, v in self._vars.all().items()}}

    # ── Node dispatch ────────────────────────────────────────────────────────

    async def _exec_node(self, node: dict) -> AsyncGenerator[Event, None]:
        # Guard: the LLM sometimes emits a string (a raw command, a shell
        # line, or just narrative text) where a dict step is expected. In
        # the old code this crashed with AttributeError from node.get(...).
        # Now: shell-looking strings are wrapped as a shell_exec step;
        # other strings are skipped with an error event.
        if not isinstance(node, dict):
            _log.warn("malformed_workflow_node", got_type=type(node).__name__,
                      got_value=str(node)[:200], profile=self._profile())
            if isinstance(node, str) and node.strip():
                # Wrap as a shell_exec fallback — this is the most likely intent
                node = {"tool": "shell_exec", "args": {"command": node}, "id": "recovered_str_step"}
            else:
                yield {
                    "type": "error",
                    "step_id": "malformed",
                    "message": (
                        f"Workflow contained a non-dict node ({type(node).__name__}). "
                        "Steps must be dict objects with a 'tool' or 'type' field. "
                        f"Got: {str(node)[:200]!r}"
                    ),
                }
                return

        # Recover malformed node where AI wrote "tool": "conditional" instead of "type": "conditional"
        if "tool" in node and "type" not in node and node["tool"] in _STRUCTURAL_TYPES:
            node = {**node, "type": node["tool"]}
            del node["tool"]
        # Leaf step: has a "tool" field but no explicit structural "type"
        if "tool" in node and "type" not in node:
            async for e in self._exec_step(node): yield e
            return
        t = node.get("type", "sequential")
        if t == "sequential":
            async for e in self._exec_sequential(node): yield e
        elif t == "parallel":
            async for e in self._exec_parallel(node): yield e
        elif t == "conditional":
            async for e in self._exec_conditional(node): yield e
        elif t == "loop":
            async for e in self._exec_loop(node): yield e
        elif t == "map":
            async for e in self._exec_map(node): yield e
        elif t == "fan_out":
            async for e in self._exec_fan_out(node): yield e
        elif t == "retry":
            async for e in self._exec_retry(node): yield e
        elif t == "pipeline":
            async for e in self._exec_pipeline(node): yield e
        elif t == "sub_workflow":
            async for e in self._exec_sub_workflow(node): yield e
        else:
            # Leaf step — has a "tool" field
            async for e in self._exec_step(node): yield e

    # ── Sequential ───────────────────────────────────────────────────────────

    async def _exec_sequential(self, node: dict) -> AsyncGenerator[Event, None]:
        sid = node.get("id", "seq")
        yield {"type": "step_start", "step_id": sid, "step_type": "sequential"}
        t0 = time.monotonic()
        for step in node.get("steps", []):
            step_failed = False
            step_error_msg = ""
            async for e in self._exec_node(step):
                yield e
                # If this step produced a non-empty error, stop here.
                # Empty-string errors (e.g. from app_open on Windows) are ignored.
                if e.get("type") == "tool_result" and e.get("error"):
                    step_failed = True
                    step_error_msg = str(e["error"])
            if step_failed:
                _log.error("sequential_abort", step_id=sid, reason=step_error_msg, profile=self._profile())
                yield {"type": "error", "step_id": sid,
                       "message": f"Sequential aborted after step error: {step_error_msg}"}
                break
        yield {"type": "step_done", "step_id": sid, "duration_ms": int((time.monotonic() - t0) * 1000)}

    # ── Parallel ─────────────────────────────────────────────────────────────

    async def _exec_parallel(self, node: dict) -> AsyncGenerator[Event, None]:
        sid = node.get("id", "par")
        yield {"type": "step_start", "step_id": sid, "step_type": "parallel"}
        t0 = time.monotonic()

        # Collect all events from parallel branches into a queue
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        steps = node.get("steps", [])

        async def run_step(step: dict) -> None:
            async for event in self._exec_node(step):
                await queue.put(event)

        tasks = [asyncio.create_task(run_step(s)) for s in steps]

        async def drain() -> None:
            await asyncio.gather(*tasks)
            await queue.put(None)  # sentinel

        asyncio.create_task(drain())

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

        # then block
        if "then" in node:
            async for e in self._exec_node(node["then"]): yield e

        yield {"type": "step_done", "step_id": sid, "duration_ms": int((time.monotonic() - t0) * 1000)}

    # ── Conditional ──────────────────────────────────────────────────────────

    async def _exec_conditional(self, node: dict) -> AsyncGenerator[Event, None]:
        sid = node.get("id", "cond")
        yield {"type": "step_start", "step_id": sid, "step_type": "conditional"}
        t0 = time.monotonic()

        cond = node.get("condition", {})
        result = self._evaluate_condition(cond)
        yield {"type": "condition_eval", "step_id": sid, "condition": cond, "result": result}

        branch_key = "if_true" if result else "if_false"
        branch = node.get(branch_key)
        if branch:
            async for e in self._exec_node(branch): yield e

        yield {"type": "step_done", "step_id": sid, "duration_ms": int((time.monotonic() - t0) * 1000)}

    def _evaluate_condition(self, cond: dict) -> bool:
        field_ref = cond.get("field", "")
        raw = self._vars.resolve(field_ref)
        op = cond.get("operator", "equals")
        expected = cond.get("value")

        if op == "equals":       return raw == expected
        if op == "not_equals":   return raw != expected
        if op == "is_null":      return raw is None
        if op == "not_null":     return raw is not None
        if op == "in":           return raw in (expected or [])
        if op == "not_in":       return raw not in (expected or [])
        if op in ("gt", "lt", "gte", "lte"):
            try:
                lhs, rhs = float(raw), float(expected)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False  # non-numeric values can't be compared numerically
            if op == "gt":  return lhs > rhs
            if op == "lt":  return lhs < rhs
            if op == "gte": return lhs >= rhs
            if op == "lte": return lhs <= rhs
        if op == "contains":     return str(expected) in str(raw)
        return False

    # ── Loop ─────────────────────────────────────────────────────────────────

    async def _exec_loop(self, node: dict) -> AsyncGenerator[Event, None]:
        sid = node.get("id", "loop")
        yield {"type": "step_start", "step_id": sid, "step_type": "loop"}
        t0 = time.monotonic()

        max_iter = node.get("max_iterations", 100)
        cond = node.get("condition", {})
        steps = node.get("steps", [])
        on_max = node.get("on_max_iterations_reached", "continue")
        store_as = node.get("store_final_as")

        iteration = 0
        while iteration < max_iter:
            if not self._evaluate_condition(cond):
                break
            iteration += 1
            yield {"type": "loop_iteration", "step_id": sid, "iteration": iteration, "max": max_iter}
            for step in steps:
                async for e in self._exec_node(step): yield e

        if iteration >= max_iter and self._evaluate_condition(cond):
            if on_max == "fail":
                yield {"type": "error", "step_id": sid, "message": f"Loop {sid!r} hit max_iterations={max_iter}"}

        if store_as:
            # Resolve the last step's store_result_as variable as the final loop value
            last_step_store = ""
            for step in steps:
                sr = step.get("store_result_as", "").lstrip("$")
                if sr:
                    last_step_store = sr
            last_val = None
            if last_step_store:
                v = self._vars.get(last_step_store)
                last_val = v.value if v else None
            from chika.core.variable_store import VarType
            var_type = VarType.JSON if isinstance(last_val, (dict, list)) else VarType.TEXT
            sv = self._vars.set(store_as, last_val, var_type)
            yield {"type": "variable_set", "name": f"${store_as}",
                   "var_type": sv.type.value, "size_bytes": sv.size_bytes}

        yield {"type": "step_done", "step_id": sid,
               "iterations": iteration, "duration_ms": int((time.monotonic() - t0) * 1000)}

    # ── Map ──────────────────────────────────────────────────────────────────

    async def _exec_map(self, node: dict) -> AsyncGenerator[Event, None]:
        sid = node.get("id", "map")
        yield {"type": "step_start", "step_id": sid, "step_type": "map"}
        t0 = time.monotonic()

        over_ref = node.get("over", "")
        items = self._vars.resolve(over_ref)
        if isinstance(items, str):
            items = [line for line in items.splitlines() if line.strip()]
        if not isinstance(items, list):
            items = [items]

        item_var = node.get("item_var", "$item").lstrip("$")
        concurrency = node.get("concurrency", 5)
        step_template = node.get("step", {})
        store_as = node.get("store_result_as", "").lstrip("$")
        results: list[Any] = [None] * len(items)

        semaphore = asyncio.Semaphore(concurrency)
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        # Serialize item-var writes so concurrent tasks don't overwrite each
        # other's $item before the step template resolves it.
        _map_item_lock = asyncio.Lock()

        yield {"type": "map_item", "step_id": sid, "index": 0, "total": len(items)}

        async def run_item(idx: int, item: Any) -> None:
            async with semaphore:
                async with _map_item_lock:
                    self._vars.set(item_var, item)
                    await queue.put({"type": "map_item", "step_id": sid, "index": idx, "total": len(items)})
                    step = copy.deepcopy(step_template)
                    async for e in self._exec_node(step):
                        await queue.put(e)
                    store_ref = step_template.get("store_result_as", "").lstrip("$")
                    if store_ref:
                        v = self._vars.get(store_ref)
                        results[idx] = v.value if v else None

        tasks = [asyncio.create_task(run_item(i, item)) for i, item in enumerate(items)]

        async def drain() -> None:
            await asyncio.gather(*tasks)
            await queue.put(None)

        asyncio.create_task(drain())

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

        if store_as:
            v = self._vars.set(store_as, results)
            yield {"type": "variable_set", "name": f"${store_as}",
                   "var_type": v.type.value, "size_bytes": v.size_bytes}

        yield {"type": "step_done", "step_id": sid, "duration_ms": int((time.monotonic() - t0) * 1000)}

    # ── Fan-out ──────────────────────────────────────────────────────────────

    async def _exec_fan_out(self, node: dict) -> AsyncGenerator[Event, None]:
        sid = node.get("id", "fanout")
        yield {"type": "step_start", "step_id": sid, "step_type": "fan_out"}
        t0 = time.monotonic()

        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        branches = node.get("branches", [])

        async def run_branch(branch: dict) -> None:
            for step in branch.get("steps", []):
                async for event in self._exec_node(step):
                    await queue.put(event)

        tasks = [asyncio.create_task(run_branch(b)) for b in branches]

        async def drain() -> None:
            await asyncio.gather(*tasks)
            await queue.put(None)

        asyncio.create_task(drain())

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

        # fan_in
        if "fan_in" in node:
            async for e in self._exec_node(node["fan_in"]): yield e

        yield {"type": "step_done", "step_id": sid, "duration_ms": int((time.monotonic() - t0) * 1000)}

    # ── Retry ────────────────────────────────────────────────────────────────

    async def _exec_retry(self, node: dict) -> AsyncGenerator[Event, None]:
        sid = node.get("id", "retry")
        yield {"type": "step_start", "step_id": sid, "step_type": "retry"}
        t0 = time.monotonic()

        max_attempts = node.get("max_attempts", 3)
        backoffs = node.get("backoff_seconds", [2, 5, 10])
        retry_on = node.get("retry_on", {})
        on_all_failed = node.get("on_all_failed", "store_error")
        error_var = node.get("store_error_as", "").lstrip("$")
        step = node.get("step", {})

        for attempt in range(1, max_attempts + 1):
            yield {"type": "retry_attempt", "step_id": sid, "attempt": attempt, "max": max_attempts}
            buffered: list[Event] = []
            async for e in self._exec_node(step):
                buffered.append(e)

            # Check retry condition
            retry_cond_met = self._evaluate_condition(retry_on) if retry_on else False
            for e in buffered:
                yield e

            if not retry_cond_met:
                break  # success

            if attempt < max_attempts:
                delay = backoffs[min(attempt - 1, len(backoffs) - 1)]
                yield {"type": "retry_backoff", "step_id": sid, "delay_seconds": delay}
                await asyncio.sleep(delay)
        else:
            # All attempts exhausted
            if on_all_failed == "store_error" and error_var:
                v = self._vars.set(error_var, {"failed": True, "attempts": max_attempts})
                yield {"type": "variable_set", "name": f"${error_var}",
                       "var_type": v.type.value, "size_bytes": v.size_bytes}
            else:
                yield {"type": "error", "step_id": sid,
                       "message": f"Retry {sid!r} failed after {max_attempts} attempts"}

        yield {"type": "step_done", "step_id": sid, "duration_ms": int((time.monotonic() - t0) * 1000)}

    # ── Pipeline ─────────────────────────────────────────────────────────────

    async def _exec_pipeline(self, node: dict) -> AsyncGenerator[Event, None]:
        sid = node.get("id", "pipeline")
        yield {"type": "step_start", "step_id": sid, "step_type": "pipeline"}
        t0 = time.monotonic()

        steps = node.get("steps", [])
        pipeline_output: Any = None

        for i, step in enumerate(steps):
            # Inject previous step's output as pipeline_input
            if pipeline_output is not None:
                self._vars.set("pipeline_input", pipeline_output)

            async for e in self._exec_node(step): yield e

            # Collect output: use store_result_as, or pipeline_input variable
            store_ref = step.get("store_result_as", "").lstrip("$")
            if store_ref:
                v = self._vars.get(store_ref)
                pipeline_output = v.value if v else None
            else:
                v = self._vars.get("pipeline_output")
                if v:
                    pipeline_output = v.value

        yield {"type": "step_done", "step_id": sid, "duration_ms": int((time.monotonic() - t0) * 1000)}

    # ── Sub-workflow ─────────────────────────────────────────────────────────

    async def _exec_sub_workflow(self, node: dict) -> AsyncGenerator[Event, None]:
        sid = node.get("id", "sub")
        wf_id = node.get("workflow_id", "")
        yield {"type": "step_start", "step_id": sid, "step_type": "sub_workflow",
               "workflow_id": wf_id}
        t0 = time.monotonic()

        if wf_id in self._executing_workflow_ids:
            yield {"type": "error", "step_id": sid,
                   "message": f"Circular sub_workflow detected: {wf_id!r}"}
        else:
            steps = self._sub_workflows.get(wf_id)
            if steps is None:
                yield {"type": "error", "step_id": sid, "message": f"Sub-workflow {wf_id!r} not found"}
            else:
                self._executing_workflow_ids.add(wf_id)
                try:
                    for step in steps:
                        async for e in self._exec_node(step): yield e
                finally:
                    self._executing_workflow_ids.discard(wf_id)

        yield {"type": "step_done", "step_id": sid, "duration_ms": int((time.monotonic() - t0) * 1000)}

    # ── Leaf step (tool call) ────────────────────────────────────────────────

    async def _exec_step(self, step: dict) -> AsyncGenerator[Event, None]:
        sid = step.get("id", "step")
        tool_name = step.get("tool", "")
        raw_args = step.get("args", {})
        store_as = step.get("store_result_as", "").lstrip("$")
        # AI-generated human-readable reason for this specific step
        step_description = step.get("description", "")

        # Resolve $variable references in args
        resolved_args = self._vars.resolve(raw_args)

        # ── Skill gate ───────────────────────────────────────────────────
        # Refuse-and-retry: if this tool belongs to a skill whose SKILL.md
        # hasn't been loaded yet, we DO NOT dispatch the tool. We surface
        # the doc and a structured ``skill_doc_required`` error so the
        # agent re-plans on the next turn with the SKILL.md in context.
        gate = await self._check_skill_gate(tool_name)
        if gate is not None:
            for ev in gate["loader_events"]:
                yield ev
            payload = gate["refusal_payload"]
            if payload is not None:
                # Synthetic tool_call/tool_result for the REFUSED tool.
                yield {"type": "tool_call", "step_id": sid,
                       "tool": tool_name, "args": resolved_args}
                yield {
                    "type":         "tool_result",
                    "step_id":      sid,
                    "tool":         tool_name,
                    "result":       payload,
                    "error":        "skill_doc_required",
                    "duration_ms":  0,
                }
                # Sequential will abort on this error event the same way
                # any tool failure does — no need for a separate "error"
                # event. The outer engine reads the payload's `doc` and
                # feeds it back to the LLM for the retry turn.
                return
            # If the loader itself failed (no SKILL.md on disk), fall
            # through and dispatch the original tool — better UX than
            # locking the user out of an undocumented skill.

        # Track explicit skill_load calls too — when the agent ITSELF loads
        # a skill, mark it loaded so the gate doesn't re-fire later.
        if tool_name == "skill_load":
            requested = resolved_args.get("skill") if isinstance(resolved_args, dict) else None
            if requested:
                self.mark_skill_loaded(requested)

        # Check if tool requires user approval before running
        tool_def = self._tools.get(tool_name)
        if tool_def and tool_def.requires_approval and self.approval_handler:
            request_id = f"appr_{sid}_{int(time.monotonic()*1000)}"
            # Prefer the AI-written step description; fall back to the static approval_message
            message = step_description or tool_def.approval_message or tool_def.description
            yield {
                "type": "approval_required",
                "request_id": request_id,
                "tool": tool_name,
                "args": resolved_args,
                "step_id": sid,
                "message": message,
            }
            approved = await self.approval_handler(
                request_id, tool_name, resolved_args,
                step_id=sid, message=message,
                approval_type=getattr(tool_def, "approval_type", "confirm"),
            )
            if not approved:
                yield {
                    "type": "tool_result", "step_id": sid, "tool": tool_name,
                    "result": {"error": "Denied by user"}, "error": "Denied by user",
                    "duration_ms": 0,
                }
                return

        _log.info("tool_call", tool=tool_name, step_id=sid, args=resolved_args, profile=self._profile())
        yield {"type": "tool_call", "step_id": sid, "tool": tool_name, "args": resolved_args}
        t0 = time.monotonic()

        # Meta-tools
        try:
            if tool_name in ("llm_summarise", "llm_transform"):
                result = await self._exec_meta_tool(tool_name, resolved_args)
            else:
                result = await self._tools.dispatch(tool_name, resolved_args)
        except Exception:
            _log.exc("tool_exception", tool=tool_name, step_id=sid, profile=self._profile())
            result = {"error": f"Unhandled exception in {tool_name} — see chika.log for traceback"}

        duration = int((time.monotonic() - t0) * 1000)
        # Treat PRESENCE of an "error" key as an error (even if the string
        # is empty/falsy). Previously empty-string errors were logged as
        # tool_ok, masking real failures like dispatch catching an empty
        # exception. If error is literally "" we show a placeholder so the
        # log entry is still informative.
        has_error_key = isinstance(result, dict) and "error" in result
        raw_error = result.get("error") if isinstance(result, dict) else None
        error = raw_error if has_error_key else None
        if has_error_key and not raw_error:
            error = "(empty-string error from tool — likely cancelled or raised without message)"
        warning = result.get("warning") if isinstance(result, dict) else None
        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        if has_error_key:
            _log.error("tool_error", tool=tool_name, step_id=sid, error=error, duration_ms=duration, profile=self._profile())
        elif warning:
            _log.error("tool_warning", tool=tool_name, step_id=sid, warning=warning, exit_code=exit_code, duration_ms=duration, profile=self._profile())
        else:
            _log.info("tool_ok", tool=tool_name, step_id=sid, exit_code=exit_code, duration_ms=duration, profile=self._profile())
        yield {"type": "tool_result", "step_id": sid, "tool": tool_name,
               "result": result, "error": error, "duration_ms": duration}

        # Emit live memory events so the frontend panel updates without polling
        if not error:
            if tool_name == "memory_persist":
                yield {
                    "type": "memory_update",
                    "key":   resolved_args.get("key", ""),
                    "value": resolved_args.get("value", ""),
                }
            elif tool_name == "memory_forget":
                yield {
                    "type": "memory_delete",
                    "key": resolved_args.get("key", ""),
                }

        if store_as:
            from chika.core.variable_store import VarType
            var_type = VarType.JSON if isinstance(result, (dict, list)) else VarType.TEXT
            source_tag = f"{tool_name}:{sid}"
            v = self._vars.set(store_as, result, var_type, source=source_tag)
            yield {"type": "variable_set", "name": f"${store_as}",
                   "var_type": v.type.value, "size_bytes": v.size_bytes,
                   "value_preview": str(result)[:120], "source": source_tag}

        # Append to the $facts ledger for any tool that produces citable material.
        # Skip if the tool returned an error, or if the value looks empty.
        if tool_name in _FACT_PRODUCING_TOOLS and not error and not _looks_empty(result):
            self._append_fact(tool_name, sid, resolved_args, result)

    def _append_fact(self, tool_name: str, step_id: str, args: dict, result: Any) -> None:
        """
        Append a concise record of a fact-producing tool call to the $facts
        ledger. Keeps only `snippet`/`url`/`source` — not full result payloads —
        so the ledger stays cheap to pass back to the LLM.
        """
        entries: list[dict] = []
        if tool_name == "web_search" and isinstance(result, dict):
            for r in (result.get("results") or [])[:8]:
                if isinstance(r, dict):
                    entries.append({
                        "source": f"web_search:{step_id}",
                        "query": result.get("query"),
                        "url": r.get("url"),
                        "title": r.get("title"),
                        "snippet": (r.get("snippet") or "")[:400],
                    })
        elif tool_name == "file_read" and isinstance(result, dict):
            entries.append({
                "source": f"file_read:{step_id}",
                "path": args.get("path") or result.get("path"),
                "start_line": result.get("start_line") or args.get("start_line"),
                "end_line": result.get("end_line") or args.get("end_line"),
                "snippet": (str(result.get("content", ""))[:400]),
            })
        elif tool_name == "shell_exec" and isinstance(result, dict):
            entries.append({
                "source": f"shell_exec:{step_id}",
                "command": args.get("command"),
                "exit_code": result.get("exit_code"),
                "snippet": (str(result.get("stdout", ""))[:400]),
            })
        elif tool_name == "verify_url" and isinstance(result, dict):
            entries.append({
                "source": f"verify_url:{step_id}",
                "url": result.get("url"),
                "status": result.get("status"),
                "content_type": result.get("content_type"),
                "reachable": result.get("reachable"),
            })
        elif tool_name == "web_fetch" and isinstance(result, dict):
            entries.append({
                "source": f"web_fetch:{step_id}",
                "url": result.get("final_url") or result.get("url"),
                "status": result.get("status"),
                "content_type": result.get("content_type"),
                "snippet": (str(result.get("content", ""))[:400]),
                "truncated": result.get("truncated"),
            })
        else:
            # Generic fallback — stringified preview
            entries.append({
                "source": f"{tool_name}:{step_id}",
                "snippet": str(result)[:400],
            })

        from chika.core.variable_store import VarType
        existing = self._vars.get("facts")
        ledger: list[dict] = existing.value if (existing and isinstance(existing.value, list)) else []
        # Cap ledger size to avoid runaway growth (keep last 60 facts)
        ledger = (ledger + entries)[-60:]
        self._vars.set("facts", ledger, VarType.JSON,
                       description="Rolling ledger of tool-retrieved facts, each with source",
                       source="engine:ledger")

    async def _exec_meta_tool(self, name: str, args: dict) -> Any:
        if self._llm is None:
            return {"error": "LLM caller not configured"}
        # Hard guard: refuse to fire the inner LLM on empty/unresolved context.
        # This is the single biggest hallucination prevention — without it,
        # llm_transform on {"count": 0, "results": []} will confidently
        # fabricate a URL from training data.
        ctx_arg = args.get("context")
        input_arg = args.get("input")
        resolved_ctx = ctx_arg if ctx_arg is not None else input_arg
        # Only refuse when the caller explicitly passed context/input.
        # Some llm_summarise calls legitimately use prompt-only (e.g. title gen).
        if (ctx_arg is not None or input_arg is not None) and _looks_empty(resolved_ctx):
            return {
                "error": "refused_empty_context",
                "reason": (
                    f"{name} refused to run: the provided context/input is empty, "
                    "missing, or an unresolved $variable. Running the inner LLM "
                    "on empty context fabricates output. Fix: gather real data "
                    "(e.g. a web_search that actually returned results) first."
                ),
                "received": str(resolved_ctx)[:200] if resolved_ctx is not None else None,
            }
        if name == "llm_summarise":
            prompt = args.get("prompt", "Summarise the following.")
            context = args.get("context", {})
            # Strip raw image bytes from context before serialising — base64 PNG blobs
            # are for the outer multimodal model only and will blow up the inner LLM's
            # context window.  Replace them with a short placeholder.
            # Known image-bearing keys: "image", "_vision_image", any key ending in "_image".
            _IMAGE_PREFIXES = ("iVBOR", "/9j/", "AAAB", "R0lGO", "UEs")  # PNG, JPEG, WEBP, GIF, ZIP/WEBP
            def _strip_images(obj: Any, depth: int = 0) -> Any:
                if depth > 10:
                    return obj
                if isinstance(obj, dict):
                    out: dict = {}
                    for k, v in obj.items():
                        if (
                            isinstance(v, str) and len(v) > 500
                            and (
                                "image" in k.lower()
                                or (isinstance(v, str) and any(v.startswith(p) for p in _IMAGE_PREFIXES))
                            )
                        ):
                            out[k] = "[image data stripped — visual content available to outer model]"
                        else:
                            out[k] = _strip_images(v, depth + 1)
                    return out
                if isinstance(obj, list):
                    return [_strip_images(item, depth + 1) for item in obj]
                return obj
            context = _strip_images(context)
            ctx_str = json.dumps(context, indent=2) if isinstance(context, (dict, list)) else str(context)
            return await self._llm.complete(f"{prompt}\n\n{ctx_str}")
        elif name == "llm_transform":
            prompt = args.get("prompt", "Transform the following.")
            pipeline_input = args.get("input") or self._vars.resolve("$pipeline_input")
            # Use context if provided (preferred over pipeline_input)
            context = args.get("context")
            if context is not None:
                pipeline_input = context
            input_str = json.dumps(pipeline_input, indent=2) if isinstance(pipeline_input, (dict, list)) else str(pipeline_input)
            # Hard cap: ~100k chars ≈ 25k tokens. Prevents context_length_exceeded errors.
            # If content is this large, the agent should be using file_read with line ranges instead.
            _MAX_INPUT = 100_000
            if len(input_str) > _MAX_INPUT:
                input_str = input_str[:_MAX_INPUT] + f"\n... [INPUT TRUNCATED — was {len(input_str)} chars. Use file_read with start_line/end_line to read large content in chunks instead of passing it directly to llm_transform.]"
            # Schema: tell the inner LLM exactly what JSON structure to return
            schema = args.get("schema")
            schema_instruction = ""
            if schema is not None:
                schema_str = json.dumps(schema, indent=2) if isinstance(schema, (dict, list)) else str(schema)
                schema_instruction = f"\n\nReturn a JSON object matching this exact schema:\n{schema_str}\n\nRespond with valid JSON only — no explanation, no markdown fences."
            else:
                schema_instruction = "\n\nReturn a JSON object with a single key \"result\" containing the answer. Example: {\"result\": \"value here\"}. Respond with valid JSON only."
            raw = await self._llm.complete(f"{prompt}\n\nInput:\n{input_str}{schema_instruction}")
            raw = raw.strip()
            # Try to parse as JSON
            parsed = None
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                pass
            if parsed is None:
                for pattern in (r"```(?:json)?\s*(\{.*?\})\s*```", r"(\{.*\})"):
                    m = _re.search(pattern, raw, _re.DOTALL)
                    if m:
                        try:
                            parsed = json.loads(m.group(1))
                            break
                        except json.JSONDecodeError:
                            pass
            # When a schema is provided, return the parsed value directly so that
            # $var[0].field and $var.key access patterns work without an extra
            # ".result" indirection.  Without a schema we always return
            # {"result": ...} so the model has a consistent key to read from.
            if schema is not None and parsed is not None:
                return parsed

            # Normalize: always guarantee a "result" key with the primary value
            if parsed is None:
                # Plain text response (URL, single line, etc.)
                return {"result": raw}
            if isinstance(parsed, dict):
                if "result" not in parsed:
                    # Single-key dict like {"image_url": "..."} → promote to result
                    vals = list(parsed.values())
                    parsed["result"] = vals[0] if len(vals) == 1 else raw
                return parsed
            # Scalar or list
            return {"result": parsed}
        return {"error": f"Unknown meta-tool: {name}"}
