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
import pathlib
import re
import tempfile
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

import config

if TYPE_CHECKING:
    from chika.core.chat_store import ChatStore

from chika.core.compactor import Compactor
from chika.core.intent import detect_planning_intent
from chika.core.logger import LOG_PATH
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


# ── Auto-continue detection ──────────────────────────────────────────────
#
# The agent has a habit of ending a turn with "Next, I'll add the camera…"
# and then waiting for the user to nudge it. ``_should_auto_continue``
# matches those patterns at the END of an assistant reply. The engine
# detects them after a turn completes and fires another turn with
# user_input="continue" — capped by ``auto_continue_max`` in settings.
#
# Triggers only fire when:
#   - the response is non-trivial (>= 20 chars after strip)
#   - the LAST PARAGRAPH contains a "next I'll …" / "now I'll …" phrase
#   - the response does NOT end with "?" (the agent is asking, not promising)

_CONTINUATION_TRIGGERS = (
    "next, i'll", "next, i will", "next i'll", "next i will",
    "next:", "next up:", "next up,",
    "now i'll", "now, i'll", "now i will", "now, i will",
    "i'll now", "i will now",
    "i'll next", "i'll continue", "i will continue",
    "i'll add", "i'll build", "i'll implement", "i'll create",
    "i'll wire", "i'll layer", "i'll set up", "i'll write",
    "then i'll", "then i will",
    "continuing with", "continuing by",
    "i'll proceed", "moving on,", "moving on:",
    "after that, i'll", "after that i'll",
    # Post-``ask_user`` slips — the agent often acknowledges the
    # user's answer without USING it ("Let's move forward based on
    # your choice." / "Now proceeding with your selection."). These
    # patterns force the auto-continue gate so the next turn
    # actually acts on the answer.
    "let's move forward", "lets move forward", "let's proceed",
    "lets proceed", "based on your choice", "based on your selection",
    "based on your answer", "with your choice", "with your selection",
    "moving forward",
)


def _normalise_text(text: str) -> str:
    """Lowercase + replace fancy Unicode punctuation with ASCII equivalents.

    LLMs routinely emit curly quotes (U+2019 right single, U+201D right
    double, etc.) in markdown output — so a literal substring match for
    ``"i'll"`` (with U+0027) misses ``"I’ll"`` (with U+2019). That bug
    silently disabled auto-continue on every multi-step turn whose final
    paragraph used Markdown-style typography. Normalising before matching
    fixes both apostrophes and dashes (em / en / minus) at once.
    """
    return (
        text.lower()
        .replace("’", "'")  # right single quote
        .replace("‘", "'")  # left single quote
        .replace("“", '"')  # left double quote
        .replace("”", '"')  # right double quote
        .replace("—", "-")  # em dash
        .replace("–", "-")  # en dash
        .replace("−", "-")  # math minus
    )


def _should_auto_continue(text: str) -> bool:
    """True if the assistant promised to do more work in the next turn."""
    if not text:
        return False
    s = text.strip()
    if len(s) < 20:
        return False
    # If ending in a question, the agent is asking — don't barge in.
    # Strip both ASCII and Unicode quote chars before checking the tail.
    if s.rstrip().rstrip("””\"'’").endswith("?"):
        return False
    # Only consider the last paragraph (continuation promises tend to be
    # the closing line, not buried mid-response). Normalise Unicode
    # punctuation before substring matching.
    last_para = _normalise_text(s.split("\n\n")[-1])
    return any(t in last_para for t in _CONTINUATION_TRIGGERS)

# ── Ollama text-mode tool instructions ────────────────────────────────────────
# Injected at the END of the system prompt for Ollama providers. Overrides the
# "tool call" framing in _CORE, which Ollama models can't act on.

_OLLAMA_TOOL_INSTRUCTIONS = """
## TOOL USE — CRITICAL OVERRIDE FOR THIS MODEL

You do NOT have access to function-calling. To take any action, output a JSON
code block. The engine detects it, executes it, and returns the result as a
`<tool_result>` message. Do NOT explain what you're about to do — just output
the JSON block directly.

Format — ALWAYS `{"type": "sequential", "steps": [...]}`:

Write a file:
```json
{"type": "sequential", "steps": [{"tool": "file_write", "args": {"path": "hello.html", "content": "..."}}]}
```

Run a shell command:
```json
{"type": "sequential", "steps": [{"tool": "shell_exec", "args": {"command": "ls -la"}}]}
```

Read a file:
```json
{"type": "sequential", "steps": [{"tool": "file_read", "args": {"path": "app.py", "start_line": 1, "end_line": 80}}]}
```

Multi-step (save result, use it next):
```json
{"type": "sequential", "steps": [
  {"tool": "file_read", "args": {"path": "notes.txt", "start_line": 1, "end_line": 80}, "store_result_as": "$content"},
  {"tool": "llm_summarise", "args": {"text": "$content", "instruction": "Summarise"}}
]}
```

Rules:
- Output ONE json block per turn. The engine runs it and returns results.
- After you see `<tool_result>`, use the data to reply to the user.
- Never fabricate tool results. Wait for the actual `<tool_result>`.
- Keep prose to the minimum. Act first, explain after.
"""


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
    # Cap input to prevent catastrophic backtracking on pathological LLM output
    text = text[:50_000]
    for m in re.finditer(r"```(?:json)?\s*(\{[^`]*})\s*```", text, re.DOTALL):
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
WORKFLOW_ORCHESTRATOR_SCHEMA: dict[str, Any] = {
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
    def __init__(self, engine: ChikaEngine) -> None:
        self._engine = engine

    async def complete(self, prompt: str) -> str:
        return await self._engine._llm_complete(prompt)


class _StubScriptRunner:
    """Deterministic LLM playback driver for CLI / WS subprocess tests.

    The script is a JSON file shaped like::

        {
          "turns": [
            {"text": "Sure thing."},
            {"text": "", "workflow": {"type": "sequential", "steps": [...]}},
            {"text": "Done."}
          ],
          "title": "Optional Test Chat",
          "completions": ["fallback for _llm_complete"]
        }

    Each ``turn`` corresponds to one ``_stream_llm`` invocation. ``text``
    is streamed as ``token`` events; ``workflow`` (if present) becomes a
    ``_tool_call_raw`` event. ``completions`` is a queue of canned
    responses for ``_llm_complete`` (title gen, condense, meta-tools).
    Once exhausted, ``_llm_complete`` returns ``""``.
    """

    def __init__(self, script_path: str) -> None:
        from pathlib import Path as _P
        with _P(script_path).open(encoding="utf-8") as fh:
            data = json.load(fh)
        self._turns: list[dict] = list(data.get("turns") or [])
        self._completions: list[str] = list(data.get("completions") or [])
        self._title: str = str(data.get("title") or "Stub Chat")
        self._cursor = 0
        self._completion_cursor = 0

    async def stream(self) -> AsyncGenerator[Event, None]:
        if self._cursor >= len(self._turns):
            yield {"type": "token", "text": (
                "[stub: ran out of scripted turns — close out the chat]"
            )}
            return
        turn = self._turns[self._cursor]
        self._cursor += 1
        text = str(turn.get("text") or "")
        for word in (text.split(" ") if text else []):
            yield {"type": "token", "text": word + " "}
        wf = turn.get("workflow")
        if wf is not None:
            import uuid as _uuid
            yield {
                "type": "_tool_call_raw",
                "data": {
                    "id":   f"call_{_uuid.uuid4().hex[:12]}",
                    "name": "workflow_orchestrator",
                    "args": wf,
                },
            }

    async def complete(self, prompt: str) -> str:
        if "title" in prompt.lower() and "concise" in prompt.lower():
            return self._title
        if self._completion_cursor < len(self._completions):
            out = self._completions[self._completion_cursor]
            self._completion_cursor += 1
            return out
        return ""


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
        self._chat_store: ChatStore | None = None
        self._needs_restore_event: bool = False
        self._last_result_content: str = "{}"  # written by _run_workflow
        # Hooks called after every switch_profile(). Each receives the new Profile.
        # Use this to dynamically register/unregister tools based on the active profile.
        self._profile_switch_hooks: list = []

        cfg = config.get_provider_config()
        self._provider = cfg.provider
        self._model = cfg.model
        # CHIKA_STUB_LLM_SCRIPT (test-only): path to a JSON file that scripts
        # the LLM responses for a fully-deterministic e2e run. When set we
        # skip the real client entirely — every _stream_llm / _llm_complete
        # call is served from disk. Used by CLI subprocess tests so they can
        # assert on the rendered terminal output without burning tokens.
        import os as _os
        self._stub_script_path = _os.environ.get("CHIKA_STUB_LLM_SCRIPT") or None
        self._stub_runner: _StubScriptRunner | None
        if self._stub_script_path:
            self._client = None
            self._stub_runner = _StubScriptRunner(self._stub_script_path)
        else:
            self._client = config.make_client()
            self._stub_runner = None
        # Track the provider/model the active client was built for, so
        # ``reload_client`` can detect whether a rebuild is actually
        # needed (model-only changes don't always need a new SDK
        # object — but rebuilding is cheap, so we do it unconditionally).
        self._client_provider: str = config.PROVIDER
        self._client_model: str = config.get_provider_config().model if not self._stub_runner else ""

        llm_caller = LLMCaller(self)
        self._workflow_engine = WorkflowEngine(tool_registry, variable_store, llm_caller)
        # Wire the skill registry into the workflow engine so its skill-gate
        # can reverse-lookup ``tool_name → skill_name`` and auto-load the
        # SKILL.md before any of that skill's tools fire.
        self._workflow_engine.set_skill_registry(skill_registry)
        # Back-reference so the skill gate can read ``self._skill_summaries``
        # at dispatch time and skip the refuse-and-reload step when the
        # summary is already in the system prompt (ADR-11 + ADR-32).
        self._workflow_engine.set_engine_ref(self)
        self._compactor = Compactor(
            llm_caller,
            max_tokens=config.MAX_HISTORY_TOKENS,
            keep_first=config.COMPACT_KEEP_FIRST,
            keep_last=config.COMPACT_KEEP_LAST,
        )
        # Set when a chat() generator is actively running.
        # Guards against two callers (e.g. frontend WS + extension) corrupting history.
        self._chat_busy: bool = False
        # Set by cancel() to interrupt the current streaming turn mid-flight.
        self._cancelled: bool = False
        # Auto-continue depth — incremented when the engine recursively
        # fires another turn because the assistant promised more work.
        # Reset to 0 at the top of every chat() call.
        self._auto_continue_depth: int = 0
        # Captured by _force_followup so the auto-continue heuristic can
        # run on text the model produced AFTER tool calls (when the main
        # agentic loop ended without yielding any user-visible tokens).
        self._last_followup_text: str = ""
        # True while a plan is awaiting user approval — set when plan_set
        # fires, cleared only when the user explicitly approves. Survives
        # turn boundaries so a denial → plan_edit → execute attempt
        # re-engages the approval gate instead of slipping through.
        self._plan_awaiting_approval: bool = False

        # Per-turn flag — set by the tool_result event handler when
        # ``ask_user`` returns a real choice. Read by the auto-continue
        # gate below to FORCE a follow-up turn (the agent has fresh
        # user info; it must act on it instead of stopping with a
        # generic acknowledgment).
        self._ask_user_answered_this_turn: bool = False

        # ── Skill summaries — auto-injected into the system prompt ──
        # Each shipped skill's SKILL.md is summarised once (cached in
        # ``data/skill_summaries/<id>.json``, hash-keyed). The summary
        # appears in EVERY turn's system prompt so the agent can pick
        # the right skill without paying for the full SKILL.md upfront.
        # Async regeneration kicks off here for stale/missing entries
        # without blocking the constructor — the next turn picks up
        # the fresh result. ADR-32.
        self._skill_summaries: dict = {}
        self._init_skill_summaries()

    def _init_skill_summaries(self) -> None:
        """Wire every shipped skill's SKILL.md summary into the engine.

        Calls ``summarizer.init_summaries`` with a callback that
        registers each summary on ``self._skill_summaries``. The
        prompt builder reads this dict on every turn so the latest
        summaries (including any background-generated ones) flow
        into the next turn's system prompt automatically.

        Failures are caught — a broken summarizer must NEVER block
        engine construction (worst case: agent operates without
        summaries, falls back to skill_load + SKILL.md as before)."""
        try:
            from chika.skills import iter_skill_modules
            from chika.skills.summarizer import init_summaries

            skills_map: dict = {}
            for mod in iter_skill_modules():
                spec = getattr(mod, "__file__", None)
                if not spec:
                    continue
                from pathlib import Path as _P
                skill_md = _P(spec).parent / "SKILL.md"
                if skill_md.is_file():
                    skills_map[mod.SKILL_NAME] = skill_md

            if not skills_map:
                return

            # llm_complete is None when no provider is configured —
            # init_summaries will load committed cache and skip async
            # regen, which is the right behaviour for offline / fresh
            # checkouts. When a client exists, we adapt the engine's
            # single-prompt ``_llm_complete(prompt)`` to the
            # summarizer's ``(*, system, user, max_tokens)`` shape by
            # concatenating system + user into one prompt — the
            # summarizer's parser is tolerant of leading prose, and
            # this avoids duplicating the per-provider call logic
            # already in ``_llm_complete``.
            llm_complete = None
            if self._client is not None:
                async def llm_complete(*, system: str, user: str, max_tokens: int) -> str:  # noqa: ARG001
                    prompt = f"{system}\n\n{user}"
                    try:
                        return await self._llm_complete(prompt)
                    except Exception:
                        return ""

            init_summaries(
                register_callback=self._register_skill_summary,
                skills=skills_map,
                llm_complete=llm_complete,
            )
        except Exception as exc:
            _log.info("skill_summaries.init_failed", error=str(exc))

    def _register_skill_summary(self, skill_id: str, summary) -> None:
        """Callback fed to ``summarizer.init_summaries``. Stashes the
        summary on ``self._skill_summaries`` keyed by skill id so the
        prompt builder can read it back on every turn."""
        self._skill_summaries[skill_id] = summary

    # ── Public ───────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Interrupt the current streaming turn. Safe to call from any context."""
        self._cancelled = True

    async def chat(self, user_input: str) -> AsyncGenerator[Event, None]:
        if self._chat_busy:
            yield {
                "type": "error",
                "message": "Chika is busy — wait for the current response to finish.",
                "error_code": "engine_busy",
            }
            yield {"type": "done"}
            return
        self._cancelled = False
        self._chat_busy = True
        # Reset auto-continue depth on every TOP-LEVEL call. Inner recursive
        # calls increment the counter without resetting.
        self._auto_continue_depth = 0
        # Per-session event log (ADR-35). Each event yielded from this
        # turn is appended to ``data/sessions/<session_id>.jsonl`` so
        # ``chika replay <session_id>`` can rehydrate the conversation
        # exactly. Built once per turn, fail-soft on FS errors.
        event_log = None
        try:
            from api.event_log import EventLog
            if self.session_id:
                event_log = EventLog(self.session_id)
        except Exception:
            event_log = None
        try:
            async for event in self._chat_inner(user_input):
                if event_log is not None:
                    try:
                        event_log.emit(event)
                    except Exception:
                        pass
                yield event
        finally:
            self._chat_busy = False
            self._cancelled = False

    async def _chat_inner(self, user_input: str) -> AsyncGenerator[Event, None]:
        # Reset per-turn capture so stale text from an earlier turn can't
        # accidentally trigger auto-continue on the next.
        self._last_followup_text = ""
        # Reset the ``ask_user`` answer flag — the tool_result handler
        # sets this when a fresh choice arrives so the auto-continue
        # gate forces a follow-up turn that actually acts on the answer.
        self._ask_user_answered_this_turn = False
        # Circuit-breaker: count identical (error_code, target) pairs across
        # this turn's workflows. Three repeats of the same denial/error
        # pattern means the agent is stuck in a retry loop — halt and
        # surface to the user instead of burning more approval prompts.
        # Cleared per top-level user turn (auto-continue resets too via
        # ``_auto_continue_depth = 0`` higher up the stack).
        repeat_errors: dict[tuple[str, str], int] = {}
        REPEAT_LIMIT = 3
        is_first_message = len(self._history) == 0
        profile = self._active_profile.name if self._active_profile else "unknown"
        _log.info("chat_start", profile=profile, message_preview=user_input[:120])
        _user_msg_appended = False
        self._history.append({"role": "user", "content": user_input})
        _user_msg_appended = True

        # Start title generation in parallel for the first message of a new chat
        title_task: asyncio.Task | None = None
        if is_first_message and not self._title:
            title_task = asyncio.create_task(self._generate_title(user_input))

        # Compact if needed
        if self._compactor.needs_compaction(self._history):
            self._history, compact_event = await self._compactor.compact(self._history)
            if compact_event is not None:
                yield compact_event

        # ─── Agentic loop — LLM keeps calling workflows until it decides it's done ─
        final_text = ""

        for _turn in range(config.MAX_TOOL_TURNS):
            if self._cancelled:
                if _user_msg_appended:
                    self._history.pop()
                    _user_msg_appended = False
                yield {"type": "cancelled"}
                yield {"type": "done"}
                return

            _log.info("llm_turn", turn=_turn, profile=profile)
            messages = self._build_messages()
            turn_text = ""
            buffered_tokens: list[str] = []
            tool_call: dict | None = None

            async for event in self._stream_llm(messages):
                if self._cancelled:
                    break
                if event["type"] == "token":
                    turn_text += event["text"]
                    buffered_tokens.append(event["text"])
                elif event["type"] == "_tool_call_raw":
                    tool_call = event["data"]
                else:
                    yield event

            if self._cancelled:
                # Flush whatever text we have so the UI doesn't show a blank response
                if turn_text.strip():
                    for tok in buffered_tokens:
                        yield {"type": "token", "text": tok}
                if _user_msg_appended:
                    self._history.pop()
                    _user_msg_appended = False
                yield {"type": "cancelled"}
                yield {"type": "done"}
                return

            # Recover workflow JSON leaked into text response
            tool_call = self._recover_leaked_workflow(turn_text, tool_call)
            if tool_call and "_cleaned_text" in tool_call:
                turn_text = tool_call.pop("_cleaned_text")
                buffered_tokens = [turn_text] if turn_text else []

            # Forward tokens — only when there is no pending tool call.
            # If the LLM wrote text alongside a tool call, that text is
            # premature narration; suppress it entirely.
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
            if self._provider == "ollama":
                # Ollama doesn't support role:tool or tool_calls — use plain text
                workflow_json_str = json.dumps(tool_call["args"])
                assistant_content = (turn_text + "\n" if turn_text else "") + \
                    f"```json\n{workflow_json_str}\n```"
                self._history.append({
                    "role": "assistant",
                    "content": assistant_content,
                })
            else:
                self._history.append({
                    "role": "assistant",
                    "content": turn_text or None,
                    "tool_calls": [{
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {
                            "name": "workflow_orchestrator",
                            "arguments": json.dumps(tool_call["args"]),
                        },
                    }],
                })

            self._last_result_content = "{}"
            async for event in self._run_workflow(tool_call):
                yield event
                # Track ``ask_user`` answers so the auto-continue gate
                # can force a follow-up turn — the agent has FRESH user
                # info and must use it. Without this rule, the model
                # often produces a non-action acknowledgment ("Let's
                # move forward based on your choice") and stops, leaving
                # the user staring at a stalled chat.
                if (
                    event.get("type") == "tool_result"
                    and event.get("tool") == "ask_user"
                    and not event.get("error")
                ):
                    result = event.get("result") or {}
                    if isinstance(result, dict) and (
                        result.get("choice") or result.get("choices")
                    ):
                        self._ask_user_answered_this_turn = True
                # Track repeated identical errors so the agent can't burn
                # the user's approval prompts in a loop. We pull the
                # ``error`` and target identifier from each tool_result.
                if event.get("type") == "tool_result" and event.get("error"):
                    err = str(event.get("error") or "").strip()
                    args = event.get("args") or {}
                    target = (
                        args.get("path")
                        or args.get("url")
                        or args.get("command")
                        or args.get("selector")
                        or ""
                    )
                    key = (err[:80], str(target)[:160])
                    repeat_errors[key] = repeat_errors.get(key, 0) + 1
                    if repeat_errors[key] >= REPEAT_LIMIT:
                        msg = (
                            f"Stopping: same error '{err}' on '{target}' "
                            f"repeated {REPEAT_LIMIT} times. Either change "
                            f"approach or ask the user — the retry loop is "
                            f"not progressing."
                        )
                        _log.warn(
                            "engine_circuit_breaker",
                            error=err, target=str(target),
                            count=repeat_errors[key], profile=profile,
                        )
                        yield {
                            "type": "error",
                            "message": msg,
                            "error_code": "repeated_error_circuit_breaker",
                        }
                        # Force the agent to surface to the user with this
                        # context — append as a tool result so the next
                        # LLM turn sees it explicitly.
                        self._last_result_content = json.dumps({
                            "error": "repeated_error_circuit_breaker",
                            "message": msg,
                            "advice": (
                                "Do NOT retry the same operation. Either "
                                "pivot the approach (different path, "
                                "different command, different selector) "
                                "or stop and tell the user what you need."
                            ),
                        })
                        break

            if self._provider == "ollama":
                # Inject result as a user message (Ollama text-mode)
                self._history.append({
                    "role": "user",
                    "content": f"<tool_result>\n{self._last_result_content}\n</tool_result>",
                })
            else:
                self._history.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": self._last_result_content,
                })
            # Loop → next LLM turn with full context

        else:
            _log.warn("max_turns_reached", max=config.MAX_TOOL_TURNS, profile=profile)

        # If the LLM never produced a text response, force one
        if not final_text.strip():
            async for event in self._force_followup():
                yield event

        # Post-response grounding validation: flag factual claims not traceable
        # to the $facts ledger. _validate_grounding is a no-op when facts are
        # empty or the response is short (controlled by GROUNDING_MIN_LENGTH).
        if final_text.strip() and config.GROUNDING_VALIDATE_RESPONSE:
            warning_event = await self._validate_grounding(final_text)
            if warning_event:
                yield warning_event

        # Emit the chat title (runs concurrently with the first LLM turn)
        async for event in self._maybe_emit_title(title_task, user_input):
            yield event

        # Auto-continue: when the agent ends with "next I'll …" / "now I'll
        # …" we fire a synthetic continuation so it actually does the next
        # thing. We check BOTH ``final_text`` (from the main agentic loop)
        # AND ``self._last_followup_text`` (from ``_force_followup``) since
        # the user-facing reply may come from either source.
        check_text = (final_text.strip() or self._last_followup_text.strip())
        if check_text and not self._cancelled:
            try:
                import api.settings_store as _settings
                enabled = _settings.get("auto_continue", "on") == "on"
                cap = int(_settings.get("auto_continue_max", 10))
            except Exception:
                enabled, cap = True, 10
            # FORCE auto-continue when ``ask_user`` returned a real
            # answer this turn — the agent has new info and must use
            # it. Don't rely on the text heuristic; the model often
            # produces a non-action acknowledgment ("Let's move
            # forward...") that previously stalled the chat. Bypasses
            # the heuristic but still respects the cap.
            forced = bool(self._ask_user_answered_this_turn)
            matched = forced or _should_auto_continue(check_text)
            if enabled and self._auto_continue_depth < cap and matched:
                self._auto_continue_depth += 1
                yield {
                    "type":          "auto_continue",
                    "depth":         self._auto_continue_depth,
                    "max":           cap,
                    "trigger_tail":  check_text[-200:],
                    "reason":        "ask_user_answered" if forced else "text_match",
                }
                async for ev in self._chat_inner("continue"):
                    yield ev
                return  # nested call yields its own "done"
            elif matched:
                # The agent promised more work but the gate blocked us.
                # Surface the reason so the user can act (raise the cap,
                # toggle the setting, or just type "continue").
                if not enabled:
                    reason = "auto_continue is off — re-enable with /auto-continue on"
                elif self._auto_continue_depth >= cap:
                    reason = (
                        f"hit auto-continue cap ({self._auto_continue_depth}/{cap}) — "
                        "raise it with /auto-continue max <int> or just type continue"
                    )
                else:
                    reason = "blocked"
                yield {
                    "type":         "auto_continue_blocked",
                    "reason":       reason,
                    "depth":        self._auto_continue_depth,
                    "max":          cap,
                    "trigger_tail": check_text[-160:],
                }

        yield {"type": "done"}


    # --- helpers extracted from chat() -----------------------------------

    def _recover_leaked_workflow(
        self,
        turn_text: str,
        tool_call: dict | None,
    ) -> dict | None:
        """Check whether the LLM leaked workflow JSON into its text output.

        If *tool_call* is already set (proper API call), returns it unchanged.
        Otherwise searches *turn_text* for embedded JSON, constructs a
        synthetic tool-call dict, and tags it with ``_cleaned_text`` (the
        remaining text after removing the JSON block).
        Returns ``None`` when no workflow JSON is found.
        """
        if tool_call:
            return tool_call
        extracted = _extract_workflow_json(turn_text)
        if not extracted:
            return None
        workflow_json, clean_text = extracted
        return {
            "id": f"recovered_{abs(hash(json.dumps(workflow_json, sort_keys=True)))}",
            "name": "workflow_orchestrator",
            "args": workflow_json,
            "_cleaned_text": clean_text,
        }

    async def _run_workflow(
        self,
        tool_call: dict,
    ) -> AsyncGenerator[Event, None]:
        """Stream all events from a workflow_orchestrator call.

        Stores the formatted result string in ``self._last_result_content``
        so the caller can append it to history after the generator finishes.
        """
        workflow_result_parts: list[str] = []
        workflow_errors: list[str] = []
        # Track tools used + whether plan was touched, so we can nudge the
        # agent when it does real work without ticking the checklist.
        tools_used: list[str] = []
        plan_touched = False
        # Set by plan_set / plan_edit when a goal- or requirements-class
        # mutation lands. Triggers an automatic plan_reconcile pass after
        # the workflow finishes so stale tasks don't drift behind a new
        # goal. Cleared once the reconcile fires.
        auto_reconcile_pending = False
        # Most recent plan-set result + its plan payload. After the
        # workflow finishes the engine asks the user to approve / edit
        # / deny the plan before letting the agent continue. This is
        # the user-facing gate: "I just made a plan, here it is, want
        # to ship it?"
        pending_plan_for_approval: dict | None = None
        async for event in self._workflow_engine.execute(tool_call["args"]):
            yield event
            etype = event["type"]
            if etype == "tool_call":
                t = event.get("tool", "")
                tools_used.append(t)
                if t in ("plan_update", "plan_remove", "plan_add", "plan_set"):
                    plan_touched = True
            elif etype == "tool_result":
                tool = event.get("tool", "")
                result = event.get("result")
                # Auto-reconcile bookkeeping. plan_reconcile itself never
                # re-triggers (would loop). plan_set always re-triggers
                # because the tool can't tell whether the goal changed —
                # plan_reconcile is a cheap no-op when the plan is
                # already consistent. plan_edit signals through the
                # ``_auto_reconcile`` field on its result dict.
                if tool == "plan_reconcile":
                    auto_reconcile_pending = False
                elif tool == "plan_set" and not event.get("error"):
                    auto_reconcile_pending = True
                    # Capture the plan for the approval gate. plan_set
                    # is the moment the user gets to approve / edit /
                    # deny before the agent commits to executing it.
                    if isinstance(result, dict) and isinstance(result.get("plan"), dict):
                        pending_plan_for_approval = result["plan"]
                        self._plan_awaiting_approval = True
                elif tool == "plan_edit" and not event.get("error"):
                    # If a plan is currently awaiting approval (i.e. user
                    # already saw it and denied / asked for edits), the
                    # revised plan ALSO needs explicit approval before
                    # execution. Without this, the agent silently edits
                    # the denied plan and starts running it — the bug
                    # the user hit. Same for plan_add / plan_remove.
                    if self._plan_awaiting_approval and isinstance(result, dict):
                        rev_plan = result.get("plan")
                        if isinstance(rev_plan, dict):
                            pending_plan_for_approval = rev_plan
                    if isinstance(result, dict) and result.get("_auto_reconcile"):
                        auto_reconcile_pending = True
                elif tool in ("plan_add", "plan_remove") and not event.get("error"):
                    # Same re-gate logic for plan_add / plan_remove while
                    # awaiting approval.
                    if self._plan_awaiting_approval and isinstance(result, dict):
                        rev_plan = result.get("plan")
                        if isinstance(rev_plan, dict):
                            pending_plan_for_approval = rev_plan
                elif isinstance(result, dict) and result.get("_auto_reconcile"):
                    auto_reconcile_pending = True
            if etype == "workflow_done":
                workflow_result_parts.append(self._format_workflow_result(event))
            elif etype == "error":
                workflow_errors.append(event.get("message", ""))
            elif etype == "tool_result" and event.get("error"):
                err = event["error"]
                payload = event.get("result")
                # Skill-gate refusals carry the full SKILL.md inline. We
                # MUST surface the doc body to the LLM verbatim so it can
                # re-plan on the next turn with the doc in context.
                if err == "skill_doc_required" and isinstance(payload, dict):
                    skill = payload.get("skill", "?")
                    doc = payload.get("doc") or ""
                    hint = payload.get("hint") or ""
                    workflow_errors.append(
                        f"{event.get('tool', 'tool')} REFUSED — skill_doc_required\n\n"
                        f"{hint}\n\n"
                        f"=== {skill} SKILL.md ({payload.get('char_count', len(doc))} chars) ===\n"
                        f"{doc}\n=== end SKILL.md ===\n"
                    )
                elif err == "plan_required" and isinstance(payload, dict):
                    # Special-case the plan-required gate so the LLM sees
                    # the hint inline (rather than as a one-line "tool
                    # failed: plan_required" that it'll ignore).
                    workflow_errors.append(
                        f"WORKFLOW REFUSED — plan_required\n\n"
                        f"{payload.get('hint', '')}\n\n"
                        f"writes_used: {payload.get('writes_used', [])}\n"
                        f"write_count: {payload.get('write_count', 0)}\n\n"
                        "Generate a NEW workflow now whose first step is "
                        "`plan_set` with goal + requirements + tasks "
                        "(consult the planning skill's SKILL.md for the "
                        "template via skill_load). "
                        "Then re-emit the original workflow."
                    )
                else:
                    workflow_errors.append(
                        f"{event.get('tool', 'tool')} failed: {err}"
                    )
        variables_content = "\n".join(workflow_result_parts) or "{}"

        # Auto-reconcile: when goal / requirements changed, dispatch a
        # plan_reconcile pass right now (before handing the result to the
        # LLM) so the next system prompt already shows the synced plan.
        # Skipped silently when the plan_reconcile tool isn't registered
        # (e.g. tests that build a minimal engine).
        if auto_reconcile_pending:
            try:
                rec_tool = self._tools.get("plan_reconcile")
            except Exception:
                rec_tool = None
            if rec_tool is not None:
                _log.info("plan_auto_reconcile",
                          profile=self._active_profile.name if self._active_profile else "?")
                try:
                    rec_result = await self._tools.dispatch("plan_reconcile", {})
                except Exception as exc:
                    rec_result = {"error": f"{type(exc).__name__}: {exc}"}
                # Surface a synthetic tool_call/tool_result pair so the
                # frontend / CLI shows the reconcile happened.
                yield {
                    "type":      "tool_call",
                    "step_id":   "plan_auto_reconcile",
                    "tool":      "plan_reconcile",
                    "args":      {"_auto": True},
                }
                yield {
                    "type":      "tool_result",
                    "step_id":   "plan_auto_reconcile",
                    "tool":      "plan_reconcile",
                    "result":    rec_result,
                    "error":     rec_result.get("error") if isinstance(rec_result, dict) else None,
                    "duration_ms": 0,
                }

        # Plan-approval gate. After the agent calls plan_set, ask the
        # user whether to approve / edit / deny BEFORE the agent
        # commits to executing the plan. The user response is fed
        # back to the LLM as the tool result so the next turn either
        # proceeds, revises the plan, or starts over.
        approval_directive: dict | None = None
        if pending_plan_for_approval is not None:
            approval_directive = await self._request_plan_approval(
                pending_plan_for_approval,
            )
            # Update the cross-turn flag based on the user's verdict.
            # Only an explicit "approve" lifts the gate — "edit" and
            # "deny" leave it engaged so the next plan_edit / plan_set
            # re-prompts the user.
            if approval_directive is not None:
                action = (approval_directive.get("action") or "").lower()
                self._plan_awaiting_approval = action != "approve"
            # Surface the approval outcome as a synthetic tool_result so
            # the renderer / frontend show the user's decision in the
            # conversation surface.
            if approval_directive is not None:
                yield {
                    "type":      "tool_call",
                    "step_id":   "plan_user_approval",
                    "tool":      "plan_user_approval",
                    "args":      {"_auto": True},
                }
                yield {
                    "type":      "tool_result",
                    "step_id":   "plan_user_approval",
                    "tool":      "plan_user_approval",
                    "result":    approval_directive,
                    "error":     None,
                    "duration_ms": 0,
                }

        # Plan-update nudge — when this workflow performed real work
        # (file_write / file_replace / shell_exec / git_commit / etc.) AND
        # there's an in_progress task in $plan AND the workflow didn't
        # touch the plan tools at all, append a stern reminder so the LLM
        # ticks the checklist on the very next turn. This is the runtime
        # backstop for the "MANDATORY: tick the checklist" prompt rule —
        # which the model has been ignoring on long sessions.
        plan_nudge = self._build_plan_nudge(tools_used, plan_touched)

        if workflow_errors:
            self._last_result_content = (
                "WORKFLOW ERRORS:\n"
                + "\n".join(workflow_errors)
                + "\n\nVARIABLES:\n"
                + variables_content
            )
        else:
            self._last_result_content = variables_content

        if plan_nudge:
            self._last_result_content = plan_nudge + "\n\n" + self._last_result_content

        # Append the user's plan-approval directive to the result
        # content so the LLM's NEXT turn knows whether to proceed,
        # revise, or restart. The directive is structured prose the
        # LLM can react to.
        if approval_directive is not None:
            self._last_result_content = (
                self._format_plan_approval_directive(approval_directive)
                + "\n\n"
                + self._last_result_content
            )

    async def _request_plan_approval(self, plan: dict) -> dict | None:
        """Ask the user to approve / edit / deny a freshly-set plan.

        Uses the workflow_engine's existing ``approval_handler`` channel
        so the plan-review modal pops in the same surface as other
        approvals (CLI prompt, frontend ApprovalModal, extension popup).

        Returns ``{action: "approve"}`` / ``{action: "edit", feedback}``
        / ``{action: "deny", reason}``. ``None`` when no approval channel
        is wired (e.g. tests / CLI without a TTY) — in that case the
        engine silently skips the gate so non-interactive flows work.
        """
        handler = getattr(self._workflow_engine, "approval_handler", None)
        if handler is None:
            return None
        # Build a compact summary the modal can render verbatim.
        summary_lines = []
        goal = (plan.get("goal") or "").strip()
        if goal:
            summary_lines.append(f"GOAL: {goal}")
        reqs = plan.get("requirements") or []
        if reqs:
            summary_lines.append("REQUIREMENTS:")
            for r in reqs[:8]:
                summary_lines.append(f"  - {r}")
        tasks = plan.get("tasks") or []
        if tasks:
            summary_lines.append("TASKS:")

            def _walk(items: list, depth: int = 0, counter=[0]):  # noqa: B006
                for t in items[:20]:
                    if not isinstance(t, dict):
                        continue
                    indent = "  " * depth
                    # Show ``text`` when present; fall back to the
                    # task ID with a ``(missing description)`` marker
                    # so the user at least sees WHICH task lacks
                    # context. ``plan_set`` validates non-empty text
                    # at intake, but this is defence-in-depth — a
                    # mid-plan ``plan_edit`` or upstream loader could
                    # still produce empty-text rows.
                    text = (t.get("text") or "").strip()
                    if not text:
                        tid = t.get("id") or "?"
                        text = f"<{tid}> (missing description)"
                    # NB: deliberately NOT showing status labels in
                    # the approval modal. ``plan_set`` auto-promotes
                    # the first leaf to ``in_progress`` so the agent
                    # has a starting target — but at APPROVAL time
                    # nothing has run yet, and a ``[in_progress]``
                    # tag on a not-yet-approved task confused users
                    # ("why is this already running if you're asking
                    # me to approve?"). Numbered bullets show the
                    # plan as a clean to-do list awaiting consent.
                    if depth == 0:
                        counter[0] += 1
                        marker = f"{counter[0]}."
                    else:
                        marker = "-"
                    summary_lines.append(f"{indent}{marker} {text[:120]}")
                    subs = t.get("subtasks") or []
                    if subs:
                        _walk(subs, depth + 1, counter)
            _walk(tasks)

        summary = "\n".join(summary_lines) or "(empty plan)"
        request_id = (
            f"plan_review_{int(__import__('time').time() * 1000) & 0xFFFFFFFF:08x}"
        )
        try:
            response = await handler(
                request_id=request_id,
                tool_name="plan_review",
                args={"plan": plan, "summary": summary},
                step_id="plan_review",
                message=(
                    "Chika just drafted this plan. Approve to let it run, "
                    "edit to send feedback, or deny to start over.\n\n"
                    + summary
                ),
                approval_type="plan_review",
            )
        except Exception:
            return None
        # The handler may return a bool (legacy) or a dict (new shape).
        if isinstance(response, bool):
            return {"action": "approve" if response else "deny",
                    "reason": ""}
        if isinstance(response, dict):
            action = (response.get("action") or
                      ("approve" if response.get("approved") else "deny")).lower()
            if action not in ("approve", "edit", "deny"):
                action = "deny"
            return {
                "action":   action,
                "feedback": response.get("feedback") or "",
                "reason":   response.get("reason") or "",
            }
        return {"action": "deny", "reason": "unexpected response shape"}

    @staticmethod
    def _format_plan_approval_directive(directive: dict) -> str:
        """Render the user's plan-review verdict as a strong prompt note
        the next LLM turn can act on."""
        action = (directive.get("action") or "").lower()
        if action == "approve":
            return (
                "🟢 PLAN APPROVAL — the user APPROVED the plan. "
                "Proceed by executing the next in-progress task."
            )
        if action == "edit":
            feedback = (directive.get("feedback") or "").strip() or "(no message)"
            return (
                "✏️ PLAN APPROVAL — the user wants EDITS to the plan "
                "before proceeding. Their feedback:\n\n"
                f"{feedback}\n\n"
                "Apply the edits with `plan_edit` (preserve task ids and "
                "any 'done' progress that's still valid). **The plan "
                "will be re-presented for approval automatically after "
                "your edits land — do NOT execute any task until the "
                "user explicitly approves the revised version.** This is "
                "enforced by the engine: any plan_set / plan_edit / "
                "plan_add / plan_remove while approval is pending will "
                "re-trigger the approval gate."
            )
        # action == "deny" or unknown
        reason = (directive.get("reason") or "").strip() or "(no reason given)"
        return (
            "🔴 PLAN APPROVAL — the user REJECTED the plan. Their reason:\n\n"
            f"{reason}\n\n"
            "Stop. Do NOT execute the plan. Re-read the user's original "
            "request and the rejection reason, then propose a different "
            "plan via `plan_set`. The user's feedback is the priority — "
            "don't argue with it. **The new plan will be re-presented "
            "for approval — do NOT execute any task until the user "
            "explicitly approves it.** This is enforced by the engine: "
            "any plan_set / plan_edit while approval is pending re-triggers "
            "the approval gate."
        )

    def _build_plan_nudge(self, tools_used: list[str],
                          plan_touched: bool) -> str | None:
        """If the workflow did real work but didn't tick the plan, return a
        reminder string to prepend to the LLM-facing result. ``None`` =
        no nudge needed."""
        if plan_touched:
            return None
        # Was there real work? Limited to tools that genuinely change state.
        WRITE_TOOLS = {
            "file_write", "file_replace", "file_edit_lines", "file_append",
            "shell_exec", "bg_shell_exec", "python_run", "live_server",
            "git_commit", "git_push", "git_checkout", "git_pr_create",
            "git_pr_merge", "scaffold_web_app",
            "browser_navigate", "browser_click", "browser_fill_input",
            "browser_open_tab", "browser_close_tab",
            "memory_persist", "memory_forget",
        }
        did_real_work = any(t in WRITE_TOOLS for t in tools_used)
        if not did_real_work:
            return None
        # Is there a current plan with an in_progress task?
        try:
            plan_var = self._vars.get("plan")
        except Exception:
            return None
        if plan_var is None or not isinstance(plan_var.value, dict):
            return None
        tasks = plan_var.value.get("tasks") or []
        if not isinstance(tasks, list):
            return None
        in_progress = [t for t in tasks
                       if isinstance(t, dict)
                       and t.get("status") == "in_progress"]
        if not in_progress:
            return None
        first = in_progress[0]
        used_str = ", ".join(t for t in tools_used if t in WRITE_TOOLS)
        return (
            "🚨 PLAN NUDGE — you ran write-class tools "
            f"({used_str}) but did not call any plan_* tool in this workflow. "
            f"Task `{first.get('id', '?')}` ('"
            f"{(first.get('text') or '')[:80]}') is still in_progress. "
            "**Your next workflow MUST start with `plan_update(task_id="
            f"\"{first.get('id', '?')}\", status=\"done\")`** if that task "
            "is now complete, or call `plan_update` with a different status "
            "if not. The user is watching the checklist — keep it accurate."
        )

    async def _force_followup(self) -> AsyncGenerator[Event, None]:
        """Yield a forced LLM reply when the model completed tool calls
        without producing any visible text response to the user.

        Uses a minimal context window (last few history messages) instead
        of the full system prompt + entire history to save tokens.
        """
        # Slice the tail but ensure we don't break tool_use/tool_result pairs.
        start = max(0, len(self._history) - 6)
        while start > 0 and self._history[start].get("role") == "tool":
            start -= 1
        tail = self._history[start:]
        followup_messages = [
            {"role": "system", "content": (
                "You are Chika. The user's task has been completed via tool calls. "
                "Summarise what was done or answer the original question. Be concise."
            )},
            *tail,
            {"role": "user", "content": (
                "[System: you just completed your work but did not reply to the user. "
                "Respond now — summarise what was done or answer the original question.]"
            )},
        ]
        followup_text = ""
        async for event in self._stream_llm(followup_messages):
            if event["type"] == "token":
                yield event
                followup_text += event["text"]
        if followup_text:
            self._history.append({"role": "assistant", "content": followup_text})
        # Expose the followup text so the outer ``_chat_inner`` can run its
        # auto-continue heuristic on it. Without this the reply that lands
        # AFTER tool calls never gets checked for "Next, I'll …" phrases
        # because ``final_text`` in the caller stays empty.
        self._last_followup_text = followup_text

    async def _maybe_emit_title(
        self,
        title_task: asyncio.Task | None,
        user_input: str,
    ) -> AsyncGenerator[Event, None]:
        """Await the title generation background task and emit chat_title."""
        if title_task is None:
            return
        try:
            title = await title_task
            self._title = title
        except Exception:
            self._title = user_input[:50]
        yield {"type": "chat_title", "title": self._title, "session_id": self.session_id}

    async def _generate_title(self, first_message: str) -> str:
        """Generate a short chat title from the user's first message."""
        prompt = (
            "Generate a concise title (3–6 words) for a conversation that starts with:\n\n"
            f'"{first_message[:300]}"\n\n'
            "Reply with ONLY the title. No quotes, no trailing punctuation."
        )
        try:
            title = await self._llm_complete(prompt)
            return title.strip().strip('"').strip("'")[:60] or first_message[:50]
        except Exception:
            return first_message[:50]

    def reload_client(self) -> dict[str, str]:
        """Hot-swap the LLM client to match the current ``.env``.

        Called after any path that mutates the .env file (the
        ``/provider`` slash, ``/model`` slash, ``PATCH /api/provider``,
        ``PATCH /api/env``). Re-reads .env via
        :func:`config.reload_from_env`, rebuilds the SDK client, and
        atomically replaces ``self._client``.

        Safety against in-flight streams:
            The Anthropic / OpenAI streaming methods grab ``self._client``
            into a local variable BEFORE awaiting any I/O, so a turn
            that's mid-stream when this swap happens finishes on the
            old client unaffected. The next turn picks up the new one.

        Returns a small status dict the slash command / HTTP route
        can surface to the user — ``{provider, model, changed}``.

        Raises :class:`RuntimeError` if the new provider's API key
        isn't set; the previous client stays active so the engine
        keeps working on the old provider until the user fixes the
        env. (The slash command catches and reports.)
        """
        if self._stub_runner is not None:
            # Test-stub mode — no live client to rebuild.
            return {"provider": "stub", "model": "", "changed": "false"}

        prev_provider = self._client_provider
        prev_model    = self._client_model

        config.reload_from_env()
        try:
            new_client = config.make_client()
        except Exception as exc:
            _log.warn("reload_client_failed", error=str(exc))
            raise RuntimeError(
                f"Couldn't switch to {config.PROVIDER}: {exc}. "
                "Check your .env for the right API key, then try again."
            ) from exc

        self._client = new_client
        self._client_provider = config.PROVIDER
        self._client_model    = config.get_provider_config().model

        changed = (
            prev_provider != self._client_provider
            or prev_model  != self._client_model
        )
        _log.info(
            "llm_client_reloaded",
            prev_provider=prev_provider,
            prev_model=prev_model,
            new_provider=self._client_provider,
            new_model=self._client_model,
            changed=changed,
        )
        return {
            "provider": self._client_provider,
            "model":    self._client_model,
            "changed":  "true" if changed else "false",
        }

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
        self._vars.set("chika.log", str(LOG_PATH), description="Live structured log file — read this to diagnose errors")
        tmp = str(pathlib.Path(tempfile.gettempdir()).as_posix())
        self._vars.set("chika.tmp", tmp, description="OS temp directory — use this for curl output files instead of /tmp/")
        # Notify hooks so they can register/unregister profile-scoped tools
        for hook in self._profile_switch_hooks:
            try:
                hook(profile)
            except Exception:
                _log.exc("profile_hook_error",
                         hook=repr(hook),
                         profile=profile.name if profile else "?")

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

        facts_var = all_vars.get("facts")
        if facts_var and isinstance(facts_var.value, list) and facts_var.value:
            lines.append("## $facts")
            lines.append(json.dumps(facts_var.value, default=str))
            lines.append("")

        lines.append("## Workflow variables")
        for name, value in variables.items():
            if name == "facts":
                continue
            var = all_vars.get(name)
            source = var.source if var else None
            header = f"### ${name}" + (f"  (source: {source})" if source else "  (source: engine/seed)")
            lines.append(header)
            try:
                rendered = json.dumps(value, default=str)
            except Exception:
                rendered = str(value)
            if len(rendered) > 6000:
                rendered = rendered[:6000] + f"\n...[truncated, full length {len(rendered)} chars]"
            lines.append(rendered)
            lines.append("")
        return "\n".join(lines) or "{}"

    def _latest_user_text(self) -> str:
        """Return the text of the most recent user message in history,
        or empty string if there isn't one. Used by intent heuristics
        and the per-turn system-prompt builder."""
        for m in reversed(self._history):
            if m.get("role") == "user":
                content = m.get("content")
                if isinstance(content, str):
                    return content
                # Multi-part content (image+text) — flatten the text parts
                if isinstance(content, list):
                    return " ".join(
                        (p.get("text") or "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                return ""
        return ""

    def _recent_tool_names(self) -> set[str]:
        """Extract tool names used in recent history for conditional prompting."""
        names: set[str] = set()
        for m in self._history:
            content = m.get("content") or ""
            if isinstance(content, str):
                for tc in m.get("tool_calls") or []:
                    args_str = (tc.get("function") or {}).get("arguments") or ""
                    try:
                        args = json.loads(args_str)
                        for step in args.get("steps") or []:
                            if "tool" in step:
                                names.add(step["tool"])
                    except Exception:
                        pass
        return names

    @staticmethod
    def _compute_thinking_budget(messages: list[dict], max_budget: int) -> int:
        """Scale thinking budget by message complexity.

        Short simple messages (greetings, quick questions) get a low budget.
        Longer messages or conversations with tool history get the full budget.
        """
        last_user = ""
        has_tool_results = False
        for m in reversed(messages):
            role = m.get("role", "")
            if role == "user" and not last_user:
                content = m.get("content", "")
                if isinstance(content, list):
                    last_user = " ".join(
                        b.get("text", "") for b in content if isinstance(b, dict)
                    )
                else:
                    last_user = str(content)
            if role == "user" and isinstance(m.get("content"), list):
                for block in m["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        has_tool_results = True
                        break

        msg_len = len(last_user)
        if has_tool_results or msg_len > 500:
            return max_budget
        if msg_len > 200:
            return max(max_budget // 2, 1024)
        return max(max_budget // 4, 1024)

    def _build_messages(self) -> list[dict]:
        # Skill index — name + 1-line description + has_doc flag so the
        # agent knows which skills exist and which can be loaded via
        # ``skill_load``. Cheap (just an iteration of the registry).
        try:
            skill_index = self._skills.skill_index()
        except Exception:
            skill_index = None

        # Skill-contributed prompt sections — every registered skill can
        # add a small dynamic block (its current state, counters, etc.).
        # The shell skill surfaces active shells, the pet skill surfaces
        # companion mood + current frame, the plan skill surfaces the
        # in-progress task. Errors per skill are swallowed inside
        # prompt_sections so a buggy contributor can't break a turn.
        try:
            skill_sections = self._skills.prompt_sections()
        except Exception:
            skill_sections = []

        # ── Skill summaries (ADR-32) — one digest per shipped skill ──
        # ``self._skill_summaries`` is populated at construction time
        # and asynchronously updated by ``init_summaries`` as
        # background regen finishes. Every turn picks up the latest
        # set, so a stale-then-regenerated summary lands in the
        # NEXT turn's prompt without any extra wiring.
        try:
            if self._skill_summaries:
                summary_block_lines = ["## Available skill summaries", ""]
                for skill_id in sorted(self._skill_summaries.keys()):
                    summary = self._skill_summaries[skill_id]
                    block_fn = getattr(summary, "to_prompt_block", None)
                    if callable(block_fn):
                        summary_block_lines.append(block_fn(skill_id))
                        summary_block_lines.append("")
                if len(summary_block_lines) > 2:
                    skill_sections = list(skill_sections) + [
                        "\n".join(summary_block_lines).rstrip()
                    ]
        except Exception:
            pass

        system_prompt = self._prompt.build(
            tool_list=self._tools.list_for_prompt(),
            variables=self._vars.list_summary(),
            memory=self._memory.render_for_prompt(),
            recent_tools=self._recent_tool_names(),
            skill_index=skill_index,
            skill_sections=skill_sections,
        )
        if self._provider == "ollama":
            system_prompt += _OLLAMA_TOOL_INSTRUCTIONS

        # Per-turn intent nudge: if the most recent user message looks
        # like a build/create task, append a short hint suggesting the
        # plan tool. Only fires when the heuristic matches; questions
        # and one-shot fixes get no hint. Hint is purely additive — it
        # doesn't override the agent's own judgment, and the user can
        # also tell the agent to skip planning explicitly.
        last_user = self._latest_user_text()
        if last_user:
            hint = detect_planning_intent(last_user)
            if hint:
                system_prompt += hint

        return [{"role": "system", "content": system_prompt}] + self._history

    async def _stream_llm(self, messages: list[dict]) -> AsyncGenerator[Event, None]:
        if self._stub_runner is not None:
            async for e in self._stub_runner.stream(): yield e
            return
        if self._provider in ("azure", "openai", "ollama"):
            async for e in self._stream_openai(messages): yield e
        elif self._provider == "anthropic":
            async for e in self._stream_anthropic(messages): yield e

    async def _stream_openai(self, messages: list[dict]) -> AsyncGenerator[Event, None]:
        import openai as _openai

        max_attempts = 4
        backoff = 2.0

        for attempt in range(max_attempts):
            tool_builders: dict[int, dict] = {}
            try:
                # Ollama doesn't reliably support the tools API — skip it and
                # rely on _recover_leaked_workflow to extract JSON from text.
                create_kwargs: dict = {
                    "model": self._model,
                    "messages": messages,
                    "max_tokens": config.OPENAI_MAX_TOKENS,
                    "stream": True,
                }
                if self._provider != "ollama":
                    create_kwargs["tools"] = [WORKFLOW_ORCHESTRATOR_SCHEMA]
                    create_kwargs["tool_choice"] = "auto"
                assert self._client is not None  # stub path returns earlier
                response = await self._client.chat.completions.create(**create_kwargs)

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
                return  # success

            except _openai.NotFoundError as exc:
                if self._provider == "ollama":
                    raise RuntimeError(
                        f"Ollama model '{self._model}' not found.\n"
                        f"  Pull it with: ollama pull {self._model}\n"
                        f"  Or list available models: ollama list\n"
                        f"  (If Ollama isn't running yet: ollama serve)"
                    ) from exc
                raise
            except (_openai.APIConnectionError, _openai.APITimeoutError,
                    _openai.InternalServerError, _openai.RateLimitError) as exc:
                if self._provider == "ollama" and isinstance(exc, _openai.APIConnectionError):
                    raise RuntimeError(
                        f"Cannot connect to Ollama at {config.OLLAMA_BASE_URL}\n"
                        f"  Start it with: ollama serve"
                    ) from exc
                if attempt >= max_attempts - 1:
                    raise
                _log.warn("openai_transient_error",
                             attempt=attempt + 1, error=str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

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

        # Anthropic requires every tool_use to have an immediately-following
        # tool_result. Strip any orphaned assistant+tool_use messages whose
        # tool_result was lost (e.g. via compaction or history slicing).
        sanitized: list[dict] = []
        for i, msg in enumerate(filtered):
            if msg.get("role") == "assistant":
                content = msg.get("content")
                if isinstance(content, list) and any(b.get("type") == "tool_use" for b in content if isinstance(b, dict)):
                    # Check the next message is a user/tool_result
                    next_msg = filtered[i + 1] if i + 1 < len(filtered) else None
                    next_content = (next_msg or {}).get("content")
                    next_has_result = (
                        next_msg
                        and next_msg.get("role") == "user"
                        and isinstance(next_content, list)
                        and any(b.get("type") == "tool_result" for b in next_content if isinstance(b, dict))
                    )
                    if not next_has_result:
                        # Strip tool_use blocks, keep only text
                        text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
                        if text_blocks:
                            sanitized.append({"role": "assistant", "content": text_blocks})
                        continue
            sanitized.append(msg)
        filtered = sanitized

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
            model_name = getattr(config, "ANTHROPIC_MODEL", "")
            if "4-6" in model_name or "opus-4" in model_name or "sonnet-4" in model_name:
                stream_kwargs["thinking"] = {"type": "adaptive"}
            else:
                max_budget = getattr(config, "THINKING_BUDGET_TOKENS", 4000)
                budget = self._compute_thinking_budget(filtered, max_budget)
                stream_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": budget,
                }
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
                assert self._client is not None  # stub path returns earlier
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
                                 if not (u in seen or seen.add(u))]  # type: ignore[func-returns-value]

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

        return None

    async def _llm_complete(self, prompt: str) -> str:
        """Non-streaming single completion for meta-tools and compaction."""
        if self._stub_runner is not None:
            return await self._stub_runner.complete(prompt)
        assert self._client is not None  # stub branch returns earlier
        if self._provider in ("azure", "openai", "ollama"):
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=config.OPENAI_MAX_TOKENS,
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
