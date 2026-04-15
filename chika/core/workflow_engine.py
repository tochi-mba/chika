"""
WorkflowEngine — executes workflow JSON and yields typed events as an async generator.

Supports all 10 step types:
  sequential, parallel, conditional, loop, map, fan_out, retry, pipeline, sub_workflow
  (event/wait-for-file is handled via loop + wait tool)

Every event is a dict with at minimum {"type": "..."}.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator

from chika.core.tool_registry import ToolRegistry
from chika.core.variable_store import VariableStore
from chika.core.logger import log as _log

Event = dict[str, Any]

_STRUCTURAL_TYPES = frozenset({
    "sequential", "parallel", "conditional", "loop",
    "map", "fan_out", "retry", "pipeline", "sub_workflow",
})


class WorkflowEngine:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        variable_store: VariableStore,
        llm_caller: "LLMCaller | None" = None,
        approval_handler: "ApprovalHandler | None" = None,
    ) -> None:
        self._tools = tool_registry
        self._vars = variable_store
        self._llm = llm_caller
        self._sub_workflows: dict[str, list[dict]] = {}
        # approval_handler: async (request_id, tool_name, args) -> bool
        # Set per-WebSocket connection so the handler can talk back to that client.
        self.approval_handler: "ApprovalHandler | None" = approval_handler

    def register_sub_workflow(self, workflow_id: str, steps: list[dict]) -> None:
        self._sub_workflows[workflow_id] = steps

    def _profile(self) -> str:
        v = self._vars.get("profile.name")
        return v.value if v else "unknown"

    async def execute(self, workflow: dict) -> AsyncGenerator[Event, None]:
        """Top-level entry: execute a workflow dict and stream events."""
        wf_id = workflow.get("id", "workflow")
        wf_name = workflow.get("name", wf_id)
        _log.info("workflow_start", workflow_id=wf_id, name=wf_name, profile=self._profile())
        yield {"type": "workflow_start", "workflow_id": wf_id, "name": wf_name}

        async for event in self._exec_node(workflow):
            yield event

        _log.info("workflow_done", workflow_id=wf_id, profile=self._profile())
        yield {"type": "workflow_done", "workflow_id": wf_id,
               "variables": {k: v.value for k, v in self._vars.all().items()}}

    # ── Node dispatch ────────────────────────────────────────────────────────

    async def _exec_node(self, node: dict) -> AsyncGenerator[Event, None]:
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
        if op == "gt":           return float(raw) > float(expected)
        if op == "lt":           return float(raw) < float(expected)
        if op == "gte":          return float(raw) >= float(expected)
        if op == "lte":          return float(raw) <= float(expected)
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
            # Store whatever is in the last updated variable from the loop
            pass  # variables already stored by inner steps

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

        yield {"type": "map_item", "step_id": sid, "index": 0, "total": len(items)}

        async def run_item(idx: int, item: Any) -> None:
            async with semaphore:
                self._vars.set(item_var, item)
                await queue.put({"type": "map_item", "step_id": sid, "index": idx, "total": len(items)})
                step = json.loads(json.dumps(step_template))  # deep copy
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

        last_result = None
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

            last_result = buffered
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

        steps = self._sub_workflows.get(wf_id)
        if steps is None:
            yield {"type": "error", "step_id": sid, "message": f"Sub-workflow {wf_id!r} not found"}
        else:
            for step in steps:
                async for e in self._exec_node(step): yield e

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
        error = result.get("error") if isinstance(result, dict) else None
        warning = result.get("warning") if isinstance(result, dict) else None
        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        if error:
            _log.error("tool_error", tool=tool_name, step_id=sid, error=error, duration_ms=duration, profile=self._profile())
        elif warning:
            _log.error("tool_warning", tool=tool_name, step_id=sid, warning=warning, exit_code=exit_code, duration_ms=duration, profile=self._profile())
        else:
            _log.info("tool_ok", tool=tool_name, step_id=sid, exit_code=exit_code, duration_ms=duration, profile=self._profile())
        yield {"type": "tool_result", "step_id": sid, "tool": tool_name,
               "result": result, "error": error, "duration_ms": duration}

        if store_as:
            from chika.core.variable_store import VarType
            var_type = VarType.JSON if isinstance(result, (dict, list)) else VarType.TEXT
            v = self._vars.set(store_as, result, var_type)
            yield {"type": "variable_set", "name": f"${store_as}",
                   "var_type": v.type.value, "size_bytes": v.size_bytes, "value_preview": str(result)[:120]}

    async def _exec_meta_tool(self, name: str, args: dict) -> Any:
        if self._llm is None:
            return {"error": "LLM caller not configured"}
        if name == "llm_summarise":
            prompt = args.get("prompt", "Summarise the following.")
            context = args.get("context", {})
            ctx_str = json.dumps(context, indent=2) if isinstance(context, (dict, list)) else str(context)
            return await self._llm.complete(f"{prompt}\n\n{ctx_str}")
        elif name == "llm_transform":
            import re as _re
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
