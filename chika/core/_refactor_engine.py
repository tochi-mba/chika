"""One-shot refactor script: extract helpers from chat() in engine.py."""
import pathlib

path = pathlib.Path('chika/core/engine.py')
src = path.read_text(encoding='utf-8')

# Sanity-check we have the right version
assert 'workflow_result_parts: list[str] = []' in src, 'expected marker not found'

# ---------------------------------------------------------------------------
# HELPERS  (inserted between _generate_title and the end of chat's section)
# ---------------------------------------------------------------------------
HELPERS = '''
    # --- helpers extracted from chat() -----------------------------------

    def _recover_leaked_workflow(
        self,
        turn_text: str,
        tool_call: "dict | None",
    ) -> "dict | None":
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
    ) -> "AsyncGenerator[Event, None]":
        """Stream all events from a workflow_orchestrator call.

        Stores the formatted result string in ``self._last_result_content``
        so the caller can append it to history after the generator finishes.
        """
        workflow_result_parts: list[str] = []
        workflow_errors: list[str] = []
        async for event in self._workflow_engine.execute(tool_call["args"]):
            yield event
            if event["type"] == "workflow_done":
                workflow_result_parts.append(self._format_workflow_result(event))
            elif event["type"] == "error":
                workflow_errors.append(event.get("message", ""))
            elif event["type"] == "tool_result" and event.get("error"):
                workflow_errors.append(
                    f"{event.get('tool', 'tool')} failed: {event['error']}"
                )
        variables_content = "\n".join(workflow_result_parts) or "{}"
        if workflow_errors:
            self._last_result_content = (
                "WORKFLOW ERRORS:\n" + "\n".join(workflow_errors)
                + "\n\nVARIABLES:\n" + variables_content
            )
        else:
            self._last_result_content = variables_content

    async def _force_followup(self) -> "AsyncGenerator[Event, None]":
        """Yield a forced LLM reply when the model completed tool calls
        without producing any visible text response to the user.
        """
        followup_messages = self._build_messages() + [{
            "role": "user",
            "content": (
                "[System: you just completed your work but did not reply to the user. "
                "Respond now \u2014 summarise what was done or answer the original question.]"
            ),
        }]
        followup_text = ""
        async for event in self._stream_llm(followup_messages):
            if event["type"] == "token":
                yield event
                followup_text += event["text"]
        if followup_text:
            self._history.append({"role": "assistant", "content": followup_text})

    async def _maybe_emit_title(
        self,
        title_task: "asyncio.Task | None",
        user_input: str,
    ) -> "AsyncGenerator[Event, None]":
        """Await the title generation background task and emit chat_title."""
        if title_task is None:
            return
        try:
            title = await title_task
            self._title = title
        except Exception:
            if not title_task.done():
                title_task.cancel()
            self._title = user_input[:50]
        yield {"type": "chat_title", "title": self._title, "session_id": self.session_id}

'''

# ---------------------------------------------------------------------------
# NEW chat() body
# ---------------------------------------------------------------------------
NEW_CHAT = '''    async def chat(self, user_input: str) -> AsyncGenerator[Event, None]:
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

        # \u2500\u2500\u2500 Agentic loop \u2014 LLM keeps calling workflows until it decides it\'s done \u2500
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
            tool_call = self._recover_leaked_workflow(turn_text, tool_call)
            if tool_call and "_cleaned_text" in tool_call:
                turn_text = tool_call.pop("_cleaned_text")
                buffered_tokens = [turn_text] if turn_text else []

            # Forward tokens \u2014 only when there is no pending tool call.
            # If the LLM wrote text alongside a tool call, that text is
            # premature narration; suppress it entirely.
            if not tool_call:
                for tok in buffered_tokens:
                    yield {"type": "token", "text": tok}

            # No tool call \u2192 LLM is done, save and exit loop
            if not (tool_call and tool_call.get("name") == "workflow_orchestrator"):
                _log.info("llm_done", turn=_turn, profile=profile)
                if turn_text:
                    self._history.append({"role": "assistant", "content": turn_text})
                    final_text = turn_text
                break

            # Tool call \u2192 save assistant turn, execute workflow, loop back
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

            self._history.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": self._last_result_content,
            })
            # Loop \u2192 next LLM turn with full context

        else:
            _log.warn("max_turns_reached", max=config.MAX_TOOL_TURNS, profile=profile)

        # If the LLM never produced a text response, force one
        if not final_text.strip():
            async for event in self._force_followup():
                yield event

'''

# ---------------------------------------------------------------------------
# Splice
# ---------------------------------------------------------------------------
lines = src.splitlines(keepends=True)

# Find chat() start
chat_start = next(
    i for i, l in enumerate(lines)
    if '    async def chat(self, user_input: str)' in l
)

# Find chat() end (next method at same indentation level)
chat_end = next(
    i for i in range(chat_start + 1, len(lines))
    if lines[i].startswith('    async def ') or lines[i].startswith('    def ')
)

print(f'chat(): lines {chat_start+1}\u2013{chat_end} (0-indexed {chat_start}\u2013{chat_end-1})')

# Replace chat() block
new_lines = lines[:chat_start] + [NEW_CHAT] + lines[chat_end:]

# Find _generate_title in updated list
gen_title_pos = next(
    i for i, l in enumerate(new_lines)
    if '    async def _generate_title(' in l
)
print(f'Inserting helpers before line {gen_title_pos+1}')

# Insert helpers
final_lines = new_lines[:gen_title_pos] + [HELPERS] + new_lines[gen_title_pos:]
final_src = ''.join(final_lines)

# Add _last_result_content to __init__
final_src = final_src.replace(
    '        self._needs_restore_event: bool = False',
    '        self._needs_restore_event: bool = False\n'
    '        self._last_result_content: str = "{}"  # written by _run_workflow',
    1,
)

path.write_text(final_src, encoding='utf-8')
print(f'Done. {len(final_src.splitlines())} lines.')
