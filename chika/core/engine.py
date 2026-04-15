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
            "Execute a structured workflow. Define the full plan as a workflow JSON with "
            "sequential/parallel/conditional/loop/map/fan_out/retry/pipeline/sub_workflow steps. "
            "Each step calls a registered tool. Results are stored as $variables for subsequent steps."
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
                    workflow_result_parts.append(json.dumps(event.get("variables", {}), indent=2))
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
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system_content = m["content"]
            else:
                filtered.append(m)

        tool_schema = {
            "name": "workflow_orchestrator",
            "description": WORKFLOW_ORCHESTRATOR_SCHEMA["function"]["description"],
            "input_schema": WORKFLOW_ORCHESTRATOR_SCHEMA["function"]["parameters"],
        }

        async with self._client.messages.stream(
            model=self._model,
            max_tokens=8192,
            system=system_content,
            messages=filtered,
            tools=[tool_schema],
        ) as stream:
            tool_use_block: dict | None = None
            tool_input_str = ""

            async for event in stream:
                etype = event.type

                if etype == "content_block_start":
                    if hasattr(event, "content_block") and event.content_block.type == "tool_use":
                        tool_use_block = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                        }
                        tool_input_str = ""

                elif etype == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text"):
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
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text if resp.content else ""
        return ""
