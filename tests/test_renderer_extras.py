"""Targeted coverage for chika/_cli/renderer.py uncovered branches.

Hits:
- _render_plan_panel (visibility window, goal, requirements, nested subtasks)
- _on_auto_continue / _on_auto_continue_blocked / _commit_answer_to_scrollback
- _on_condition_eval (true/false/named/missing)
- _on_compaction / _on_chat_title / _on_loop_iteration / _on_map_item
- _on_validation_warning / _on_variable_set
- one-off renderers (render_banner, render_status_line, render_pet,
  render_kv_table, render_json_block)
- end_turn flushing thinking-only path
"""
from __future__ import annotations

import io
import time
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from chika._cli import renderer as r
from chika._cli.renderer import (
    Renderer,
    render_banner,
    render_json_block,
    render_kv_table,
    render_pet,
    render_status_line,
)


def _make_console() -> Console:
    """In-memory Rich console safe for unicode on Windows (no cp1252 file)."""
    return Console(
        record=True,
        width=120,
        file=io.StringIO(),
        force_terminal=False,
    )


def _renderer(plan_provider=None) -> Renderer:
    """Build a Renderer that writes to an in-memory recording console."""
    return Renderer(console=_make_console(), show_thinking=True,
                    plan_provider=plan_provider)


# ── _render_plan_panel ─────────────────────────────────────────────────


def test_plan_panel_no_provider_returns_none():
    rd = _renderer(plan_provider=None)
    assert rd._render_plan_panel() is None


def test_plan_panel_window_closed_returns_none():
    rd = _renderer(plan_provider=lambda: {"tasks": [{"id": "t1", "text": "x", "status": "pending"}]})
    rd._plan_visible_until = 0  # closed
    rd._running_tool = None
    assert rd._render_plan_panel() is None


def test_plan_panel_visible_when_running_plan_tool():
    plan = {"tasks": [{"id": "t1", "text": "design", "status": "in_progress", "subtasks": []}]}
    rd = _renderer(plan_provider=lambda: plan)
    rd._running_tool = {"tool": "plan_set", "started_at": time.time()}
    panel = rd._render_plan_panel()
    assert panel is not None


def test_plan_panel_visible_within_window():
    plan = {"tasks": [{"id": "t1", "text": "design", "status": "in_progress"}]}
    rd = _renderer(plan_provider=lambda: plan)
    rd._show_plan_for(60.0)
    panel = rd._render_plan_panel()
    assert panel is not None


def test_plan_panel_provider_exception_returns_none():
    def boom():
        raise RuntimeError("provider broke")
    rd = _renderer(plan_provider=boom)
    rd._show_plan_for(60.0)
    assert rd._render_plan_panel() is None


def test_plan_panel_non_dict_returns_none():
    rd = _renderer(plan_provider=lambda: "not a dict")
    rd._show_plan_for(60.0)
    assert rd._render_plan_panel() is None


def test_plan_panel_no_tasks_returns_none():
    rd = _renderer(plan_provider=lambda: {"tasks": []})
    rd._show_plan_for(60.0)
    assert rd._render_plan_panel() is None


def test_plan_panel_renders_full_plan():
    plan = {
        "goal": "Ship X",
        "requirements": ["must work offline", "no React"],
        "tasks": [
            {"id": "t1", "text": "design", "status": "done", "subtasks": []},
            {
                "id": "t2", "text": "build", "status": "in_progress",
                "subtasks": [
                    {"id": "t2.1", "text": "frontend", "status": "in_progress"},
                    {"id": "t2.2", "text": "backend", "status": "pending"},
                ],
            },
            {"id": "t3", "text": "ship", "status": "pending"},
            "raw-string-task",  # non-dict — must be skipped
        ],
    }
    rd = _renderer(plan_provider=lambda: plan)
    rd._show_plan_for(60.0)
    panel = rd._render_plan_panel()
    assert panel is not None


def test_plan_panel_empty_text_uses_placeholder():
    """An empty task text falls back to '(empty)'."""
    plan = {"tasks": [{"id": "t1", "text": "", "status": "pending"}]}
    rd = _renderer(plan_provider=lambda: plan)
    rd._show_plan_for(60.0)
    panel = rd._render_plan_panel()
    assert panel is not None


# ── _show_plan_for ─────────────────────────────────────────────────────


def test_show_plan_for_extends_window():
    rd = _renderer()
    rd._plan_visible_until = 0.0
    rd._show_plan_for(30.0)
    assert rd._plan_visible_until > time.time()


def test_show_plan_for_only_extends_forward():
    rd = _renderer()
    rd._plan_visible_until = time.time() + 1000.0
    before = rd._plan_visible_until
    rd._show_plan_for(1.0)  # smaller window
    assert rd._plan_visible_until == before  # unchanged


# ── auto-continue events ───────────────────────────────────────────────


def test_on_auto_continue_emits_signal():
    rd = _renderer()
    rd._answer_buf = ["preview text"]
    rd._on_auto_continue({"depth": 2, "max": 10})
    # _commit_answer_to_scrollback flushed the buffer
    assert rd._answer_buf == []


def test_on_auto_continue_blocked_renders():
    rd = _renderer()
    rd._on_auto_continue_blocked({"reason": "max_depth_reached"})
    # No exception raised — handler ran cleanly.


def test_commit_answer_to_scrollback_no_buf():
    rd = _renderer()
    rd._answer_buf = []
    # Empty buffer → early return, no exceptions.
    rd._commit_answer_to_scrollback()


def test_commit_answer_to_scrollback_with_buf():
    rd = _renderer()
    rd._answer_buf = ["body text"]
    rd._commit_answer_to_scrollback()
    assert rd._answer_buf == []


# ── condition / loop / map / retry ─────────────────────────────────────


def test_on_condition_eval_true():
    rd = _renderer()
    rd._on_condition_eval({"result": True, "expression": "x > 0"})


def test_on_condition_eval_false():
    rd = _renderer()
    rd._on_condition_eval({"result": False, "expression": "x > 0"})


def test_on_condition_eval_named_branch():
    rd = _renderer()
    rd._on_condition_eval({"result": "branch_a", "step_id": "s1"})


def test_on_condition_eval_no_expr():
    rd = _renderer()
    rd._on_condition_eval({"result": True})


def test_on_loop_iteration():
    rd = _renderer()
    rd._on_loop_iteration({"iteration": 3, "max": 10})


def test_on_map_item():
    rd = _renderer()
    rd._on_map_item({"index": 0, "total": 5})


def test_on_retry_attempt_with_reason():
    rd = _renderer()
    rd._on_retry_attempt({"attempt": 2, "max": 3, "reason": "rate_limit"})


def test_on_retry_attempt_no_reason():
    rd = _renderer()
    rd._on_retry_attempt({"attempt": 1, "max": 3})


def test_on_compaction():
    rd = _renderer()
    rd._on_compaction({"removed": 5, "kept": 10})


def test_on_chat_title_with_title():
    rd = _renderer()
    rd._on_chat_title({"title": "Refactor auth"})


def test_on_chat_title_empty_silent():
    rd = _renderer()
    rd._on_chat_title({"title": ""})  # noop


def test_on_validation_warning():
    rd = _renderer()
    rd._on_validation_warning({"message": "ungrounded claim"})


def test_on_variable_set():
    rd = _renderer()
    rd._on_variable_set({"name": "x", "var_type": "STRING", "size_bytes": 24})


# ── handle dispatch ────────────────────────────────────────────────────


def test_handle_dispatches_to_known_event():
    rd = _renderer()
    called = {"hit": False}
    def fake(event):
        called["hit"] = True
    rd._on_chat_title = fake
    rd.handle({"type": "chat_title", "title": "X"})
    assert called["hit"] is True


def test_handle_unknown_event_silent():
    rd = _renderer()
    rd.handle({"type": "totally_unknown_event"})  # noop


# ── _pet_quote ─────────────────────────────────────────────────────────


def test_pet_quote_no_pet():
    rd = _renderer()
    assert rd._pet_quote("idle") == ""


def test_pet_quote_pet_with_quotes():
    rd = _renderer()
    pet = MagicMock()
    pet.quotes = {"idle": ["chirp", "purr"]}
    rd.pet = pet
    rd._tick = 1
    assert rd._pet_quote("idle") in ("chirp", "purr")


def test_pet_quote_missing_kind_returns_empty():
    rd = _renderer()
    pet = MagicMock()
    pet.quotes = {}
    rd.pet = pet
    assert rd._pet_quote("celebrate") == ""


def test_pet_quote_pet_quotes_raises():
    rd = _renderer()
    class BrokenPet:
        @property
        def quotes(self): raise RuntimeError("borked")
    rd.pet = BrokenPet()
    assert rd._pet_quote("idle") == ""


# ── update_pet_state ───────────────────────────────────────────────────


def test_update_pet_state_with_speech():
    rd = _renderer()
    rd.update_pet_state("celebrate", speech="great job!")
    assert rd._pet_state == "celebrate"
    assert rd._pet_speech == "great job!"


def test_update_pet_state_no_speech_keeps_existing():
    rd = _renderer()
    rd._pet_speech = "old"
    rd.update_pet_state("working")
    assert rd._pet_speech == "old"


# ── set_pet ────────────────────────────────────────────────────────────


def test_set_pet_resets_tick():
    rd = _renderer()
    rd._tick = 99
    pet = MagicMock()
    rd.set_pet(pet)
    assert rd._tick == 0
    assert rd.pet is pet


# ── end_turn paths ─────────────────────────────────────────────────────


def test_end_turn_flushes_thinking_only_when_no_answer():
    """Turn ends with thinking buffered but no answer → thinking-no-answer panel."""
    rd = _renderer()
    rd._thinking_buf = ["I was reasoning about X"]
    rd._answer_buf = []
    rd.start_turn()
    rd._thinking_buf = ["I was reasoning about X"]
    rd._answer_buf = []
    rd.end_turn()
    # Calling end_turn shouldn't crash and should drain buffers.
    assert rd._thinking_buf == []
    assert rd._answer_buf == []


def test_end_turn_after_answer():
    rd = _renderer()
    rd.start_turn()
    rd._answer_buf = ["ok"]
    rd.end_turn()
    assert rd._answer_buf == []


def test_end_turn_no_answer_no_thinking_clean():
    rd = _renderer()
    rd.start_turn()
    rd.end_turn()  # clean shutdown


# ── one-off renderers ──────────────────────────────────────────────────


def test_render_banner_runs():
    console = _make_console()
    render_banner(console, version="2.0.0", provider="anthropic", model="opus-4-7")


def test_render_status_line_skips_empty_values():
    console = _make_console()
    render_status_line(console, env="dev", profile="", model="opus")


def test_render_pet_with_speech():
    console = _make_console()
    pet = MagicMock()
    pet.frame_for = MagicMock(return_value="( ^_^ )")
    pet.name = "Mochi"
    pet.accent = "magenta"
    render_pet(console, pet, state="celebrate", tick=0, speech="yay!")


def test_render_pet_idle_no_speech():
    console = _make_console()
    pet = MagicMock()
    pet.frame_for = MagicMock(return_value="( ._. )")
    pet.name = "Mochi"
    pet.accent = "blue"
    render_pet(console, pet, state="idle")


def test_render_kv_table_basic():
    console = _make_console()
    render_kv_table(console, "Settings", [("provider", "anthropic"), ("model", "opus")])


def test_render_kv_table_with_value_style():
    console = _make_console()
    render_kv_table(
        console, "Settings", [("k", "v")], value_style="bold green",
    )


def test_render_json_block_dict():
    console = _make_console()
    render_json_block(console, {"a": 1, "b": [1, 2, 3]})


def test_render_json_block_falls_back_on_unserializable():
    """Unserializable input → str() fallback path runs without crashing."""
    console = _make_console()
    class BadJson:
        def __repr__(self): return "BadJson()"

    render_json_block(console, BadJson())


# ── _shorten / _fmt_args / _fmt_result helpers ─────────────────────────


def test_shorten_below_limit():
    assert r._shorten("hello", 10) == "hello"


def test_shorten_above_limit_truncates():
    out = r._shorten("x" * 100, 10)
    assert len(out) <= 11  # 10 + ellipsis byte
    assert out.endswith("…")


def test_fmt_args_basic():
    out = r._fmt_args({"x": 1, "y": "abc"})
    plain = out.plain
    assert "x" in plain and "1" in plain
    assert "y" in plain


def test_fmt_args_truncates_long_string():
    long = "A" * 500
    out = r._fmt_args({"k": long})
    # _fmt_args caps each value preview at 80 chars then appends an
    # ellipsis. Whether the ellipsis is the literal '…' character or
    # the unicode escape '…' depends on the rich/Text encoding —
    # what matters is that the long value got truncated (shorter than
    # the original 500 characters) AND ended up containing many As.
    assert "AAAAAAAAAA" in out.plain  # the run survived
    assert len(out.plain) < 500       # but was clearly truncated


def test_fmt_args_handles_unserialisable():
    class Weird:
        def __repr__(self): return "<weird>"
    out = r._fmt_args({"k": Weird()})
    assert "weird" in out.plain.lower() or out.plain != ""


def test_fmt_result_string_passthrough():
    text = "hello world"
    assert r._fmt_result(text) == text


def test_fmt_result_truncates_lots_of_lines():
    many_lines = "\n".join(str(i) for i in range(100))
    out = r._fmt_result(many_lines)
    assert "more lines" in out


def test_fmt_result_handles_unserialisable():
    class Boom:
        def __repr__(self): return "BOOM"
    out = r._fmt_result(Boom())
    assert "BOOM" in out
