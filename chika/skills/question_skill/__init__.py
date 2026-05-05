"""
question_skill — structured mid-plan user questions.

Gives chika the equivalent of Claude Code's AskUserQuestion: mid-plan it can
pause and ask the user a multiple-choice question via a proper UI, instead
of printing a question in text and hoping the user answers in the next
turn.

The skill's ask_user tool dispatches to a session-scoped question_handler
(wired in server.py symmetric to approval_handler). The handler emits a
`user_question` event with {request_id, question, options} and awaits a
future that is resolved by the frontend's `user_question_response` message.

Use cases:
- "Should I use OAuth or JWT for auth?"
- "Which of these files did you mean?"
- "Ready for me to deploy, or want to review first?"
"""
from __future__ import annotations

from chika.core.skill_registry import Skill
from chika.core.tool_registry import ToolDefinition


def _make_ask_user(workflow_engine):
    """
    Build the ask_user tool bound to the session's WorkflowEngine. At call
    time, the tool reads `workflow_engine.question_handler` — this lets
    server.py swap a live-UI handler in (and out) per WebSocket connection
    without having to re-register the tool. In CLI/test mode the handler
    is None and the tool returns a structured error instead of hanging.
    """
    async def ask_user(question: str, options: list, header: str = "", multi_select: bool = False) -> dict:
        handler = getattr(workflow_engine, "question_handler", None)
        if handler is None:
            return {
                "_source": "ask_user",
                "error": "no_question_handler",
                "reason": (
                    "This session has no UI attached to ask the user a "
                    "question (CLI or test mode). Ask in plain text in "
                    "your next response instead."
                ),
            }

        # Normalise options: accept plain strings OR {label, description}.
        normalised: list[dict] = []
        for i, opt in enumerate(options or []):
            if isinstance(opt, str):
                normalised.append({"label": opt, "description": ""})
            elif isinstance(opt, dict):
                normalised.append({
                    "label": str(opt.get("label", f"Option {i+1}")),
                    "description": str(opt.get("description", "")),
                })
            else:
                normalised.append({"label": str(opt), "description": ""})

        if len(normalised) < 2:
            return {
                "_source": "ask_user",
                "error": "need_at_least_two_options",
                "reason": "ask_user requires 2+ options. Ask in text instead.",
            }
        if len(normalised) > 6:
            return {
                "_source": "ask_user",
                "error": "too_many_options",
                "reason": (
                    f"ask_user supports at most 6 options, got {len(normalised)}. "
                    "Split into multiple questions or use plain text."
                ),
            }

        import secrets as _secrets
        request_id = "q_" + _secrets.token_hex(6)
        try:
            response = await handler(
                request_id=request_id,
                question=question,
                options=normalised,
                header=header,
                multi_select=multi_select,
            )
        except Exception as exc:
            return {"_source": "ask_user", "error": str(exc)}

        # response shape: {"choice": str, "choice_index": int, "notes": str}
        # OR for multi_select: {"choices": [...], "choice_indices": [...]}
        return {
            "_source": "ask_user",
            "question": question,
            **response,
        }

    return ask_user


def build_question_skill(workflow_engine) -> Skill:
    """
    workflow_engine: the session's WorkflowEngine. The ask_user tool will
    look up `workflow_engine.question_handler` at call time — server.py sets
    this attribute when the WebSocket connects.
    """
    ask_user = _make_ask_user(workflow_engine)
    return Skill(
        name="question",
        description="Ask the user a structured multiple-choice question mid-plan",
        tools=[
            ToolDefinition(
                name="ask_user",
                description=(
                    "Ask the user a structured multiple-choice question (2-6 "
                    "options). The UI renders a proper choice picker; their "
                    "selection comes back as the tool's result. Use when you "
                    "genuinely need a decision from the user before proceeding "
                    "— e.g. 'OAuth or JWT?', 'which of these 3 files did you "
                    "mean?', 'ready to deploy or want to review?'. Skip this "
                    "for yes/no on sensitive actions (approval flow covers "
                    "that) or for fully ambiguous open-ended questions (use "
                    "plain text response instead)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "The question to ask — end with ?"},
                        "options":  {
                            "type": "array",
                            "items": {"type": ["string", "object"]},
                            "description": (
                                "2-6 answer choices. Each may be a string "
                                "(becomes the label) or {label, description} "
                                "where description gives context for the choice."
                            ),
                        },
                        "header":   {"type": "string", "description": "Optional short chip label for the question (<12 chars), e.g. 'Auth method'"},
                        "multi_select": {"type": "boolean", "description": "Allow multiple selections (default false)"},
                    },
                    "required": ["question", "options"],
                },
                handler=ask_user,
            ),
        ],
        workflow_examples="",
    )
