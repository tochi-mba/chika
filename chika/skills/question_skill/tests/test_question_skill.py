"""Tests for question_skill — structured ask_user questions."""
import asyncio

from chika.skills.question_skill import _make_ask_user, build_question_skill


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeEngine:
    """Stand-in for WorkflowEngine — just needs a question_handler attr."""
    def __init__(self, handler=None):
        self.question_handler = handler


def test_no_handler_returns_error():
    """CLI/test mode with no handler → structured error, no hang."""
    engine = _FakeEngine(handler=None)
    ask = _make_ask_user(engine)
    r = _run(ask(question="Pick one", options=["A", "B"]))
    assert r["error"] == "no_question_handler"


def test_need_at_least_two_options():
    engine = _FakeEngine(handler=lambda **kw: None)
    ask = _make_ask_user(engine)
    r = _run(ask(question="Pick", options=["only one"]))
    assert r["error"] == "need_at_least_two_options"


def test_options_are_normalised():
    """Accepts strings OR {label, description} dicts."""
    captured = {}
    async def fake_handler(*, request_id, question, options, header, multi_select):
        captured["options"] = options
        return {"choice": "A", "choice_index": 0}

    engine = _FakeEngine(handler=fake_handler)
    ask = _make_ask_user(engine)
    _run(ask(
        question="Pick one",
        options=[
            "Plain string",
            {"label": "Dict option", "description": "With description"},
        ],
    ))
    opts = captured["options"]
    assert opts[0] == {"label": "Plain string", "description": ""}
    assert opts[1] == {"label": "Dict option", "description": "With description"}


def test_handler_response_flows_through():
    async def fake_handler(**kw):
        return {"choice": "Chosen", "choice_index": 1, "notes": "important"}

    engine = _FakeEngine(handler=fake_handler)
    ask = _make_ask_user(engine)
    r = _run(ask(question="Pick", options=["A", "Chosen"]))
    assert r["choice"] == "Chosen"
    assert r["choice_index"] == 1
    assert r["notes"] == "important"
    assert r["_source"] == "ask_user"
    assert r["question"] == "Pick"


def test_options_too_many_returns_error():
    async def fake_handler(**kw):
        return {"choice": "a", "choice_index": 0}

    engine = _FakeEngine(handler=fake_handler)
    ask = _make_ask_user(engine)
    result = _run(ask(
        question="Too many",
        options=["a", "b", "c", "d", "e", "f", "g", "h"],
    ))
    assert result.get("error") == "too_many_options"


def test_skill_registers_ask_user_tool():
    engine = _FakeEngine()
    skill = build_question_skill(engine)
    names = {t.name for t in skill.tools}
    assert names == {"ask_user"}


def test_handler_lookup_is_dynamic():
    """
    The tool reads engine.question_handler at CALL time, so server.py can
    attach/replace the handler after the tool is already registered.
    """
    engine = _FakeEngine(handler=None)
    ask = _make_ask_user(engine)
    # Initially no handler → error
    r1 = _run(ask(question="Pick", options=["A", "B"]))
    assert r1["error"] == "no_question_handler"

    # Attach a handler, same tool reference should now use it
    async def fake_handler(**kw):
        return {"choice": "A", "choice_index": 0}
    engine.question_handler = fake_handler
    r2 = _run(ask(question="Pick", options=["A", "B"]))
    assert r2.get("choice") == "A"
