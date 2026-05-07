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

# Canonical name used by the engine's skill registry.
SKILL_NAME = "question"


def _make_ask_user(workflow_engine_getter):
    """
    Build the ask_user tool bound to the session's WorkflowEngine. The
    workflow_engine is resolved THROUGH A GETTER at call time — that
    lets the auto-discovery loop register this skill before the engine
    exists, and lets server.py swap a live-UI handler in (and out) per
    WebSocket connection without having to re-register the tool. In
    CLI/test mode the handler is None and the tool returns a structured
    error instead of hanging.
    """
    async def ask_user(question: str, options: list, header: str = "", multi_select: bool = False) -> dict:
        workflow_engine = workflow_engine_getter() if callable(workflow_engine_getter) else workflow_engine_getter
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


def build_question_skill(workflow_engine_or_getter) -> Skill:
    """
    workflow_engine_or_getter: the session's WorkflowEngine, or a
    no-arg callable returning it. The ask_user tool looks up
    ``workflow_engine.question_handler`` at call time — server.py sets
    this attribute when the WebSocket connects. Accepting a getter
    lets the auto-discovery loop register the skill BEFORE the engine
    exists; legacy callsites passing the engine directly still work.
    """
    ask_user = _make_ask_user(workflow_engine_or_getter)
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


def build_skill(context):
    """Auto-discovery entry point. The ask_user tool reads
    ``workflow_engine.question_handler`` at call time, so the engine
    only needs to exist by the time the agent invokes it — not at
    skill-registration time. The workflow-engine getter handles that
    deferral cleanly."""
    return build_question_skill(context.workflow_engine_getter)


INTENT_CASES: dict = {
    "plan": {
        "positive": [
            "build me an interactive setup wizard that asks 5 questions then scaffolds the project",
        ],
        "negative": [
            "ask me whether I want OAuth or JWT",
            "wait for my answer before continuing",
        ],
    },
    # No "ask" dimension — this skill IS the ``ask_user`` tool. Calibrating
    # ask-vs-not against the skill that owns ask is recursive; the other
    # skills' ``ask`` cases are what the agent reads to decide.
}
