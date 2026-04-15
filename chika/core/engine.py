"""
ChikaEngine — main chat loop.

The AI has ONE tool: workflow_orchestrator.
Flow:
  1. Build system prompt
  2. Stream tokens from LLM (yielding token events)
  3. If LLM calls workflow_orchestrator → WorkflowEngine.execute() → stream all events
  4. Feed workflow result back into history
  5. LLM produces final text response
  6. Yield done event
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncGenerator

import config
from chika.core.compactor import Compactor
from chika.core.logger import log as _log
from chika.core.memory_manager import MemoryManager
from chika.core.profile_manager import Profile
from chika.core.prompt_builder import PromptBuilder
from chika.core.skill_registry import SkillRegistry
from chika.core.tool_registry import ToolRegistry
from chika.core.variable_store import VariableStore
from chika.core.workflow_engine import WorkflowEngine

Event = dict[str, Any]

# ── Embedded-workflow extraction ──────────────────────────────────────────────

_WORKFLOW_TYPES = {
    "sequential", "parallel", "conditional", "loop",
    "map", "fan_out", "retry", "pipeline", "sub_workflow",
}


def _is_workflow(data: object) -> bool:
    return (
        isinstance(data, dict)
        and data.get("type") in _WORKFLOW_TYPES
        and any(k in data for k in ("steps", "branches", "step"))
    )


def _is_step(data: object) -> bool:
    """A single tool-call step leaked as text instead of a workflow."""
    return isinstance(data, dict) and "tool" in data and isinstance(data.get("tool"), str)


def _wrap_step(step: dict) -> dict:
    return {"type": "sequential", "id": "recovered_step", "steps": [step]}


def _extract_workflow_json(text: str) -> tuple[dict, str] | None:
    """
    If the LLM leaked workflow JSON into its text response instead of using
    the tool-call mechanism, find it, return (workflow_dict, cleaned_text).
    Handles both ```json ... ``` fences and bare { ... } blocks.
    """
    # 1. Code-fenced blocks first (```json or ```)
    for m in re.finditer(r"```(?:json)?\s*(\{.*?})\s*```", text, re.DOTALL):
        try:
            data = json.loads(m.group(1))
            if _is_workflow(data):
                clean = (text[: m.start()] + text[m.end() :]).strip()
                return data, clean
            if _is_step(data):
                clean = (text[: m.start()] + text[m.end() :]).strip()
                return _wrap_step(data), clean
        except json.JSONDecodeError:
            pass

    # 2. Bare JSON object — find the first { and match its closing }
    start = text.find("{")
    while start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        data = json.loads(candidate)
                        if _is_workflow(data):
                            clean = (text[:start] + text[i + 1 :]).strip()
                            return data, clean
                        if _is_step(data):
                            clean = (text[:start] + text[i + 1 :]).strip()
                            return _wrap_step(data), clean
                    except json.JSONDecodeError:
                        pass
                    break
        start = text.find("{", start + 1)

    return None


# ── The one tool the AI sees
WORKFLOW_ORCHESTRATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "workflow_orchestrator",
        "description": (
            "Execute a structured workflow against the registered toolset. You use "
            "this for ALL actions — single tool calls, multi-step sequences, branching, "
            "retries, parallel fan-outs.\n\n"
            "Shape: {type, steps/branches/step, id?, name?, ...}. Top-level `type` "
            "selects the structural behaviour; each step has `tool`, `args`, and "
            "optionally `store_result_as: \"$name\"` to save its result for later steps.\n\n"
            "Single tool call — use a sequential with one step:\n"
            "  {\"type\": \"sequential\", \"steps\": [{\"tool\": \"file_read\", "
            "\"args\": {\"path\": \"foo.py\", \"start_line\": 1, \"end_line\": 80}, "
            "\"store_result_as\": \"$foo\"}]}\n\n"
            "Structural types:\n"
            "  - sequential: steps run in order, each result stored as $var for later steps\n"
            "  - parallel:   all steps at once; optional `then` merges\n"
            "  - conditional: branch on a field — `condition` + `if_true` / `if_false`\n"
            "  - loop:       repeat `steps` while `condition` holds (or max_iterations)\n"
            "  - map:        apply `step` to every item in a list (concurrency-configurable)\n"
            "  - fan_out:    named parallel branches, merged by `fan_in`\n"
            "  - retry:      retry `step` with `backoff_seconds`; `on_all_failed: store_error`\n"
            "  - pipeline:   step N's output auto-feeds step N+1 via $pipeline_input\n"
            "  - sub_workflow: call a registered workflow by `workflow_id`\n\n"
            "Rules you must follow:\n"
            "  - $var refs in args are resolved from previous steps: use \"$foo.url\" to "
            "read a field, \"$list[0]\" for list index.\n"
            "  - Meta-tools llm_transform / llm_summarise REFUSE empty/unresolved context "
            "(the engine returns {error: 'refused_empty_context'}); gather real data first.\n"
            "  - ALWAYS pass a `schema` to llm_transform so the inner LLM returns a predictable shape.\n"
            "  - file_read requires start_line/end_line (no full-file reads); "
            "file_replace/file_edit_lines require a prior file_read of the exact range.\n"
            "  - Every retrieval tool (web_search, file_read, shell_exec, web_fetch, verify_url) "
            "auto-appends to the $facts ledger. Claims you make in your reply should be "
            "backed by $facts entries."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id":    {"type": "string", "description": "Unique workflow identifier"},
                "name":  {"type": "string", "description": "Human-readable name"},
                "type":  {
                    "type": "string",
                    "enum": ["sequential", "parallel", "conditional", "loop", "map",
                             "fan_out", "retry", "pipeline", "sub_workflow"],
                },
                "steps": {"type": "array", "items": {"type": "object"}, "description": "Steps for sequential/parallel/pipeline"},
                "branches": {"type": "array", "items": {"type": "object"}, "description": "Branches for fan_out"},
                "condition": {"type": "object", "description": "Condition for conditional/loop"},
                "if_true":   {"type": "object"},
                "if_false":  {"type": "object"},
                "max_iterations": {"type": "integer"},
                "step":      {"type": "object", "description": "Step template for map/retry"},
                "over":      {"type": "string",  "description": "$variable reference for map"},
                "item_var":  {"type": "string"},
                "concurrency": {"type": "integer"},
                "max_attempts":  {"type": "integer"},
                "backoff_seconds": {"type": "array", "items": {"type": "number"}},
                "retry_on":  {"type": "object"},
                "then":      {"type": "object"},
                "fan_in":    {"type": "object"},
                "workflow_id": {"type": "string"},
                "store_result_as": {"type": "string"},
            },
            "required": ["type"],
        },
    },
}


class LLMCaller:
    """Thin wrapper so WorkflowEngine can call the LLM for meta-tools."""
    def __init__(self, engine: "ChikaEngine") -> None:
        self._engine = engine

    async def complete(self, prompt: str) -> str:
        return await self._engine._llm_complete(prompt)


class ChikaEngine:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        variable_store: VariableStore,
        memory_manager: MemoryManager,
        prompt_builder: PromptBuilder,
        skill_registry: SkillRegistry,
    ) -> None:
        self._tools = tool_registry
        self._vars = variable_store
        self._memory = memory_manager
        self._prompt = prompt_builder
        self._skills = skill_registry
        self._history: list[dict] = []
        self._active_profile: Profile | None = None
        self.session_id: str = ""
        self._title: str = ""
        self._chat_store = None  # ChatStore | None, injected by session_manager
        self._needs_restore_event: bool = False
        # Hooks called after every switch_profile(). Each receives the new Profile.
        # Use this to dynamically register/unregister tools based on the active profile.
        self._profile_switch_hooks: list = []

        cfg = config.get_provider_config()
        self._provider = cfg.provider
        self._model = cfg.model
        self._client = config.make_client()

        llm_caller = LLMCaller(self)
        self._workflow_engine = WorkflowEngine(tool_registry, variable_store, llm_caller)
        self._compactor = Compactor(
            llm_caller,
            max_tokens=config.MAX_HISTORY_TOKENS,
            keep_first=config.COMPACT_KEEP_FIRST,
            keep_last=config.COMPACT_KEEP_LAST,
        )

    # ── Public ───────────────────────────────────────────────────────────────

    async def chat(self, user_input: str) -> AsyncGenerator[Event, None]:
        is_first_message = len(self._history) == 0
        profile = self._active_profile.name if self._active_profile else "unknown"
        _log.info("chat_start", profile=profile, message_preview=user_input[:120])
        self._history.append({"role": "user", "content": user_input})

        # Start title generation in parallel for the first message of a new chat
        title_task: "asyncio.Task | None" = None
        if is_first_message and not self._title:
            title_task = asyncio.create_task(self._generate_title(user_input))

        # Compact if needed
        if self._compactor.needs_compaction(self._history):
            self._history, compact_event = await self._compactor.compact(self._history)
            if compact_event:
                yield compact_event

        # ── Agentic loop — LLM keeps calling workflows until it decides it's done ─
        final_text = ""

        for _turn in range(config.MAX_TOOL_TURNS):
            _log.info("llm_turn", turn=_turn, profile=profile)
            messages = self._build_messages()
            turn_text = ""
            buffered_tokens: list[str] = []
            tool_call: dict | None = None

            async for event in self._stream_llm(messages):
                if event["type"] == "token":
                    turn_text += event["text"]
                    buffered_tokens.append(event["text"])
                elif event["type"] == "_tool_call_raw":
                    tool_call = event["data"]
                else:
                    yield event

            # Recover workflow JSON leaked into text response
            if not tool_call:
                extracted = _extract_workflow_json(turn_text)
                if extracted:
                    workflow_json, clean_text = extracted
                    tool_call = {
                        "id": f"recovered_{abs(hash(json.dumps(workflow_json, sort_keys=True)))}",
                        "name": "workflow_orchestrator",
                        "args": workflow_json,
                    }
                    turn_text = clean_text
                    buffered_tokens = [clean_text] if clean_text else []

            # Forward tokens to frontend — but ONLY when there is no tool call.
            # If the LLM wrote text alongside a tool call, that text is premature:
            # it's narrating results it hasn't received yet. Suppress it entirely.
            # The real response will come after the workflow finishes.
            if not tool_call:
                for tok in buffered_tokens:
                    yield {"type": "token", "text": tok}

            # No tool call → LLM is done, save and exit loop
            if not (tool_call and tool_call.get("name") == "workflow_orchestrator"):
                _log.info("llm_done", turn=_turn, profile=profile)
                if turn_text:
                    self._history.append({"role": "assistant", "content": turn_text})
                    final_text = turn_text
                break

            # Tool call → save assistant turn, execute workflow, loop back
            self._history.append({
                "role": "assistant",
                "content": turn_text or None,
                "tool_calls": [{
                    "id": tool_call["id"],
                    "type": "function",
                    "function": {"name": "workflow_orchestrator",
                                 "arguments": json.dumps(tool_call["args"])},
                }],
            })

            workflow_result_parts: list[str] = []
            workflow_errors: list[str] = []
            async for event in self._workflow_engine.execute(tool_call["args"]):
                yield event
                if event["type"] == "workflow_done":
                    workflow_result_parts.append(self._format_workflow_result(event))
                elif event["type"] == "error":
                    workflow_errors.append(event.get("message", ""))
                elif event["type"] == "tool_result" and event.get("error"):
                    workflow_errors.append(f"{event.get('tool', 'tool')} failed: {event['error']}")

            variables_content = "\n".join(workflow_result_parts) or "{}"
            if workflow_errors:
                result_content = "WORKFLOW ERRORS:\n" + "\n".join(workflow_errors) + "\n\nVARIABLES:\n" + variables_content
            else:
                result_content = variables_content
            self._history.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": result_content,
            })
            # Loop → next LLM turn with full context of what just happened

        else:
            _log.warn("max_turns_reached", max=config.MAX_TOOL_TURNS, profile=profile)

        # If the LLM never produced a text response, force one
        if not final_text.strip():
            followup_messages = self._build_messages() + [{
                "role": "user",
                "content": (
                    "[System: you just completed your work but did not reply to the user. "
                    "Respond now — summarise what was done or answer the original question.]"
                ),
            }]
            followup_text = ""
            async for event in self._stream_llm(followup_messages):
                if event["type"] == "token":
                    yield event
                    followup_text += event["text"]
            if followup_text:
                self._history.append({"role": "assistant", "content": followup_text})

        # ── Post-response grounding validation ──────────────────────────
        # If the final text contains specific factual markers (URLs, numbers,
        # proper nouns) that don't trace back to $facts, emit a warning
        # event. Best-effort: never blocks the response, never raises.
        if getattr(config, "GROUNDING_VALIDATE_RESPONSE", True) and final_text.strip():
            try:
                warning = await self._validate_grounding(final_text)
                if warning:
                    yield warning
            except Exception:
                _log.exc("grounding_validation_failed", profile=profile)

        # Resolve title (ran in parallel with the main LLM response)
        if title_task is not None:
            try:
                title = await asyncio.wait_for(asyncio.shield(title_task), timeout=15.0)
                self._title = title
            except Exception:
                if title_task and not title_task.done():
                    title_task.cancel()
                self._title = user_input[:50]
            yield {"type": "chat_title", "title": self._title, "session_id": self.session_id}

        # Persist chat to disk after each turn
        if self._chat_store is not None and self.session_id and self._active_profile:
            self._chat_store.save(
                self._active_profile.name,
                self.session_id,
                self._history,
                self._title,
            )

        yield {"type": "done"}

    async def _generate_title(self, first_message: str) -> str:
        """Generate a short chat title from the user's first message."""
        prompt = (
            "Generate a concise title (3–6 words) for a conversation that starts with:\n\n"
            f'"{first_message[:300]}"\n\n'
            "Reply with ONLY the title. No quotes, no trailing punctuation."
        )
        title = await self._llm_complete(prompt)
        return title.strip().strip('"').strip("'")[:60] or first_message[:50]

    def switch_profile(self, profile: Profile) -> None:
        """Swap the active profile: new memory file, update workspace variable."""
        self._memory = MemoryManager(
            path=profile.memory_path,
            max_tokens=config.MAX_MEMORY_TOKENS,
        )
        # Keep skill registry's memory reference in sync
        self._skills._memory = self._memory
        self._active_profile = profile
        # Expose profile info as session variables
        self._vars.set("profile.name", profile.name, description="Active profile name")
        self._vars.set("profile.workspace", profile.workspace, description="Profile workspace directory")
        from chika.core.logger import LOG_PATH
        self._vars.set("chika.log", str(LOG_PATH), description="Live structured log file — read this to diagnose errors")
        import tempfile, pathlib
        tmp = str(pathlib.Path(tempfile.gettempdir()).as_posix())
        self._vars.set("chika.tmp", tmp, description="OS temp directory — use this for curl output files instead of /tmp/")
        # Notify hooks so they can register/unregister profile-scoped tools
        for hook in self._profile_switch_hooks:
            try:
                hook(profile)
            except Exception:
                pass

    def reset(self) -> None:
        self._history.clear()
        self._vars.clear()
        # Re-expose profile vars after clear
        if self._active_profile:
            self._vars.set("profile.name", self._active_profile.name)
            self._vars.set("profile.workspace", self._active_profile.workspace)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _format_workflow_result(self, workflow_done_event: dict) -> str:
        """
        Build the tool-result payload that goes back to the LLM.

        Instead of dumping raw JSON of every variable, we produce a labelled
        block per variable with its provenance ("source") tag, so the LLM can
        tell at a glance which facts came from a real tool call vs. which are
        engine-seeded ($profile.name etc.). This is the core grounding layer:
        the LLM sees *where each fact came from*.

        $facts — the rolling fact ledger — is always rendered first so any
        claim-check can find it immediately.
        """
        variables = workflow_done_event.get("variables", {})
        # Try to pull source metadata from the live variable store.
        # Fall back to raw JSON if the store doesn't know about the name
        # (e.g. tests that instantiate WorkflowEngine without the engine).
        lines: list[str] = []
        all_vars = self._vars.all() if self._vars else {}

        # Surface the ledger first — it's the authoritative grounded record.
        facts_var = all_vars.get("facts")
        if facts_var and isinstance(facts_var.value, list) and facts_var.value:
            lines.append("## $facts — grounded evidence retrieved so far")
            lines.append(
                "Every entry below is a real result from a tool call this "
                "session. When you answer the user, CITE these entries. If "
                "a claim you want to make is not represented here, either "
                "run another tool to gather evidence or tell the user you "
                "don't have it. Do NOT synthesize."
            )
            lines.append(json.dumps(facts_var.value, indent=2))
            lines.append("")

        lines.append("## Workflow variables")
        for name, value in variables.items():
            if name == "facts":
                continue  # already rendered above
            var = all_vars.get(name)
            source = var.source if var else None
            header = f"### ${name}" + (f"  (source: {source})" if source else "  (source: engine/seed)")
            lines.append(header)
            try:
                rendered = json.dumps(value, indent=2, default=str)
            except Exception:
                rendered = str(value)
            # Truncate huge values so the LLM context doesn't explode
            if len(rendered) > 6000:
                rendered = rendered[:6000] + f"\n...[truncated, full length {len(rendered)} chars]"
            lines.append(rendered)
            lines.append("")
        return "\n".join(lines) or "{}"

    def _build_messages(self) -> list[dict]:
        system_prompt = self._prompt.build(
            tool_list=self._tools.list_for_prompt(),
            variables=self._vars.list_summary(),
            memory=self._memory.render_for_prompt(),
        )
        return [{"role": "system", "content": system_prompt}] + self._history

    async def _stream_llm(self, messages: list[dict]) -> AsyncGenerator[Event, None]:
        if self._provider in ("azure", "openai"):
            async for e in self._stream_openai(messages): yield e
        elif self._provider == "anthropic":
            async for e in self._stream_anthropic(messages): yield e

    async def _stream_openai(self, messages: list[dict]) -> AsyncGenerator[Event, None]:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=[WORKFLOW_ORCHESTRATOR_SCHEMA],
            tool_choice="auto",
            stream=True,
        )

        tool_builders: dict[int, dict] = {}
        async for chunk in response:
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue
            delta = choice.delta

            if delta.content:
                yield {"type": "token", "text": delta.content}

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_builders:
                        tool_builders[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_builders[idx]["id"] += tc.id
                    if tc.function and tc.function.name:
                        tool_builders[idx]["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_builders[idx]["arguments"] += tc.function.arguments

        if tool_builders:
            for builder in tool_builders.values():
                try:
                    args = json.loads(builder["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield {"type": "_tool_call_raw", "data": {
                    "id": builder["id"],
                    "name": builder["name"],
                    "args": args,
                }}

    async def _stream_anthropic(self, messages: list[dict]) -> AsyncGenerator[Event, None]:
        # Convert history format: system message is separate in Anthropic API
        system_content = ""
        # Convert OpenAI-format history → Anthropic content-block format.
        # Chika stores history in OpenAI shape ({role: "tool", tool_call_id, ...}
        # and assistant messages with "tool_calls"). Anthropic rejects role=tool
        # outright; it wants tool_use / tool_result as content blocks on
        # assistant / user messages respectively.
        filtered = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                system_content = m["content"]
            elif role == "tool":
                # OpenAI tool-result → Anthropic user message with tool_result block
                filtered.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id") or "",
                        "content": m.get("content") or "",
                    }],
                })
            elif role == "assistant" and m.get("tool_calls"):
                # OpenAI assistant-with-tool-calls → Anthropic assistant message
                # with text + tool_use content blocks.
                blocks: list[dict] = []
                text = m.get("content")
                if text:
                    blocks.append({"type": "text", "text": text})
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    try:
                        tool_input = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        tool_input = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id") or "",
                        "name": fn.get("name") or "",
                        "input": tool_input,
                    })
                if blocks:
                    filtered.append({"role": "assistant", "content": blocks})
            else:
                # Plain user/assistant text messages pass through as-is
                filtered.append(m)

        # Anthropic strictly requires the first message to be role=user. If the
        # conversion dropped something and left us with an assistant-leading
        # sequence (edge case during restoration), prepend a synthetic user.
        if filtered and filtered[0].get("role") != "user":
            filtered.insert(0, {"role": "user", "content": "(continue)"})

        tool_schema = {
            "name": "workflow_orchestrator",
            "description": WORKFLOW_ORCHESTRATOR_SCHEMA["function"]["description"],
            "input_schema": WORKFLOW_ORCHESTRATOR_SCHEMA["function"]["parameters"],
        }

        # Prompt caching: the 300+ line system prompt is static for the session
        # (tool_list/variables/memory sections change, but the bulk of the base
        # prompt is identical turn-to-turn). Flagging it as an ephemeral cache
        # checkpoint lets Anthropic reuse the prefix across turns — cheaper
        # and faster, with no behavioural change.
        system_block = [{
            "type": "text",
            "text": system_content,
            "cache_control": {"type": "ephemeral"},
        }] if system_content else []

        # Extended thinking: enable hidden reasoning before the response. When
        # the SDK doesn't support the parameter (older version), fall through
        # silently so we never block the main path.
        stream_kwargs = dict(
            model=self._model,
            max_tokens=(
                getattr(config, "ANTHROPIC_MAX_TOKENS_THINKING", 32768)
                if getattr(config, "THINKING_ENABLED", False)
                else getattr(config, "ANTHROPIC_MAX_TOKENS", 16384)
            ),
            system=system_block,
            messages=filtered,
            tools=[tool_schema],
        )
        if getattr(config, "THINKING_ENABLED", False):
            stream_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": getattr(config, "THINKING_BUDGET_TOKENS", 4000),
            }
            # Extended thinking requires temperature=1 per Anthropic docs
            stream_kwargs["temperature"] = 1.0

        # Transient-error retry: Anthropic (and any streaming API) can return
        # 'overloaded_error', 429 rate-limits, or connection drops mid-stream.
        # Retry with exponential backoff — up to 4 attempts — before giving
        # up. Non-transient errors (auth, invalid_request) propagate immediately.
        import anthropic as _anthropic_module
        _TRANSIENT = tuple(
            e for e in (
                getattr(_anthropic_module, "APIConnectionError", None),
                getattr(_anthropic_module, "APITimeoutError", None),
                getattr(_anthropic_module, "InternalServerError", None),
                getattr(_anthropic_module, "RateLimitError", None),
            ) if e is not None
        )
        _OVERLOADED_TYPES = ("overloaded_error", "api_error")

        def _is_transient(exc: Exception) -> bool:
            if _TRANSIENT and isinstance(exc, _TRANSIENT):
                return True
            body = getattr(exc, "body", None)
            if isinstance(body, dict):
                err = body.get("error") or {}
                if isinstance(err, dict) and err.get("type") in _OVERLOADED_TYPES:
                    return True
            msg = str(exc).lower()
            if any(k in msg for k in ("overloaded", "rate limit", "timeout", "connection error")):
                return True
            return False

        for attempt in range(1, 5):  # up to 4 attempts
            try:
                try:
                    stream_cm = self._client.messages.stream(**stream_kwargs)
                except TypeError:
                    # Older SDK without `thinking` kwarg — retry without it
                    stream_kwargs.pop("thinking", None)
                    stream_kwargs.pop("temperature", None)
                    stream_cm = self._client.messages.stream(**stream_kwargs)

                async with stream_cm as stream:
                    tool_use_block: dict | None = None
                    tool_input_str = ""
                    in_thinking_block = False

                    async for event in stream:
                        etype = event.type

                        if etype == "content_block_start":
                            if hasattr(event, "content_block"):
                                cb_type = event.content_block.type
                                if cb_type == "tool_use":
                                    tool_use_block = {
                                        "id": event.content_block.id,
                                        "name": event.content_block.name,
                                    }
                                    tool_input_str = ""
                                elif cb_type == "thinking":
                                    in_thinking_block = True

                        elif etype == "content_block_delta":
                            delta = event.delta
                            if hasattr(delta, "thinking"):
                                yield {"type": "thinking", "text": delta.thinking}
                            elif hasattr(delta, "text"):
                                yield {"type": "token", "text": delta.text}
                            elif hasattr(delta, "partial_json"):
                                tool_input_str += delta.partial_json

                        elif etype == "content_block_stop":
                            if tool_use_block and tool_input_str:
                                try:
                                    args = json.loads(tool_input_str)
                                except json.JSONDecodeError:
                                    args = {}
                                yield {"type": "_tool_call_raw", "data": {
                                    "id": tool_use_block["id"],
                                    "name": tool_use_block["name"],
                                    "args": args,
                                }}
                                tool_use_block = None
                                tool_input_str = ""
                            elif in_thinking_block:
                                yield {"type": "thinking_end"}
                                in_thinking_block = False
                return  # stream completed successfully

            except Exception as exc:
                if attempt < 4 and _is_transient(exc):
                    backoff = min(2 ** attempt, 16)  # 2, 4, 8 seconds
                    _log.warn("anthropic_transient_retry",
                              attempt=attempt, backoff=backoff, error=str(exc)[:200])
                    yield {"type": "retry_notice",
                           "message": f"Anthropic API transient error ({type(exc).__name__}); retry {attempt}/3 in {backoff}s",
                           "attempt": attempt}
                    import asyncio as _asyncio
                    await _asyncio.sleep(backoff)
                    continue
                raise

    async def _validate_grounding(self, response_text: str) -> Event | None:
        """
        Lightweight post-response check. Returns a `validation_warning` event
        if the response appears to make specific factual claims that aren't
        traceable to the $facts ledger.

        Strategy:
        1. If the response is short or has no specific factual markers
           (URLs, proper-noun-like capitalised phrases, explicit numbers) →
           skip. No point paying for a validator on "sure!" or "done.".
        2. Extract URLs from the response. For each, check it appears in
           $facts. If a URL is cited that was never retrieved, that's a
           strong hallucination signal — warn.
        3. If $facts is empty but the response has factual markers, emit
           a weaker "ungrounded" warning.
        """
        import re

        min_len = getattr(config, "GROUNDING_MIN_LENGTH", 160)
        if len(response_text) < min_len:
            return None

        # Extract URLs from the response
        url_re = re.compile(r"https?://[^\s\)\]\>\"'`]+")
        response_urls = set(url_re.findall(response_text))

        # Collect grounded URLs from $facts
        grounded_urls: set[str] = set()
        facts_var = self._vars.get("facts")
        facts_list = facts_var.value if (facts_var and isinstance(facts_var.value, list)) else []
        for f in facts_list:
            if isinstance(f, dict):
                if f.get("url"):
                    grounded_urls.add(str(f["url"]))
                if f.get("final_url"):
                    grounded_urls.add(str(f["final_url"]))

        # Well-known domains that don't need per-URL grounding. These are
        # root references the model routinely suggests ("check coingecko for
        # live prices") — flagging them as fabrications is noise.
        _TRUSTED_HOSTS = {
            "google.com", "www.google.com",
            "youtube.com", "www.youtube.com", "youtu.be",
            "github.com", "www.github.com",
            "wikipedia.org", "en.wikipedia.org", "www.wikipedia.org",
            "stackoverflow.com", "www.stackoverflow.com",
            "npmjs.com", "www.npmjs.com",
            "pypi.org", "www.pypi.org",
            "developer.mozilla.org", "mdn.io",
            "docs.python.org", "nodejs.org", "reactjs.org", "vuejs.org",
            "coinmarketcap.com", "www.coinmarketcap.com",
            "coingecko.com", "www.coingecko.com",
            "coindesk.com", "www.coindesk.com",
            "anthropic.com", "docs.claude.com", "console.anthropic.com",
            "openai.com", "platform.openai.com",
        }

        def _host(u: str) -> str:
            m = re.match(r"https?://([^/:]+)", u)
            return (m.group(1) if m else "").lower()

        def _is_grounded(url: str) -> bool:
            base = url.rstrip("/").rstrip()
            grounded_norm = {g.rstrip("/") for g in grounded_urls}
            if base in grounded_norm:
                return True
            if _host(url) in _TRUSTED_HOSTS:
                return True
            return False

        # A URL is only a problem when it APPEARS TO BE CITED AS A SOURCE.
        # Detect citation intent by checking the ~80 chars before each URL
        # for citation markers. A URL mentioned as a suggestion ("you can try
        # X") or embedded in a code block is not a citation.
        _CITATION_MARKERS = re.compile(
            r"\b(source|sources|according to|cited|reference[sd]?|per\s+\w+|from\s+\[)\b",
            re.IGNORECASE,
        )

        ungrounded_cited_urls: list[str] = []
        for m in url_re.finditer(response_text):
            url = m.group(0)
            if _is_grounded(url):
                continue
            # Look backwards ~80 chars for citation intent
            pre = response_text[max(0, m.start() - 80):m.start()]
            if _CITATION_MARKERS.search(pre):
                ungrounded_cited_urls.append(url)

        # Deduplicate preserving order
        seen = set()
        ungrounded_cited_urls = [u for u in ungrounded_cited_urls
                                 if not (u in seen or seen.add(u))]

        if ungrounded_cited_urls:
            _log.warn("grounding_warning", reason="ungrounded_citation",
                      urls=ungrounded_cited_urls,
                      profile=self._active_profile.name if self._active_profile else "unknown")
            return {
                "type": "validation_warning",
                "severity": "high",
                "reason": "ungrounded_citation",
                "message": (
                    f"The response cites {len(ungrounded_cited_urls)} URL(s) as "
                    "sources but these URLs were not retrieved by any tool "
                    "this session. These citations may be fabricated."
                ),
                "urls": ungrounded_cited_urls,
            }

        # For the older metric, keep an audit-log entry when ungrounded URLs
        # are present — but DON'T warn the user. They may just be suggestions.
        all_ungrounded = [u for u in response_urls if not _is_grounded(u)]
        if all_ungrounded:
            _log.info("ungrounded_urls_mentioned", count=len(all_ungrounded),
                      profile=self._active_profile.name if self._active_profile else "unknown")

        # Keep the other citation-markers-without-retrieval heuristic below,
        # guarded by the same smarter rule (only flag if there's actual
        # citation language AND no $facts at all).
        citation_markers = _CITATION_MARKERS.search(response_text)

        if citation_markers and not facts_list:
            _log.warn("grounding_warning", reason="citations_without_retrieval",
                      profile=self._active_profile.name if self._active_profile else "unknown")
            return {
                "type": "validation_warning",
                "severity": "medium",
                "reason": "citations_without_retrieval",
                "message": (
                    "The response references sources, but no tool has been "
                    "called this session to retrieve any. Citations may be "
                    "fabricated."
                ),
            }

        return None

    async def _llm_complete(self, prompt: str) -> str:
        """Non-streaming single completion for meta-tools and compaction."""
        if self._provider in ("azure", "openai"):
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            )
            return resp.choices[0].message.content or ""
        elif self._provider == "anthropic":
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=getattr(config, "ANTHROPIC_COMPLETE_MAX_TOKENS", 8192),
                messages=[{"role": "user", "content": prompt}],
            )
            # Response may contain thinking / tool_use blocks before text.
            # Find the first text block and return it, skipping the rest.
            for block in (resp.content or []):
                if getattr(block, "type", None) == "text":
                    return getattr(block, "text", "") or ""
            return ""
        return ""
