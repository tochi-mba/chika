"""CLI renderer visual baselines.

We can't drive the rich-based CLI through Playwright, but rich's
``Console(record=True)`` captures every rendered character so we can
diff the output against a stable text baseline. Each test:

  1. Builds a Renderer with ``Console(record=True, width=100)``.
  2. Feeds a deterministic event stream (no timing, no randomness).
  3. Calls ``console.export_text(clear=False)`` to get the rendered
     output as plain text (ANSI stripped).
  4. Compares against a baseline file under ``tests/cli_baselines/``.
     If the baseline doesn't exist OR the env var
     ``UPDATE_CLI_BASELINES=1`` is set, the file is written.
     Otherwise we assert equality and fail with a unified diff.

Why text and not SVG / HTML?
  - Plain text is the most human-readable diff in code review.
  - Stripping ANSI normalises across terminals (Mac iTerm vs Windows
    cmd.exe vs CI runner with no TERM colour support).
  - Rich's layout uses Unicode box-drawing chars; those survive
    text export and visually convey the same panel structure.

Re-baseline workflow when the renderer's design legitimately changes:

    UPDATE_CLI_BASELINES=1 python -m pytest tests/test_cli_baselines.py
    git add tests/cli_baselines/
    git diff --staged tests/cli_baselines/  # eyeball the new look

The baselines are short (<3KB each) and live under git so a PR diff
shows exactly how a renderer change altered the UX.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path

import pytest
from rich.console import Console

from chika._cli.renderer import Renderer


_BASELINES = Path(__file__).parent / "cli_baselines"
_BASELINES.mkdir(exist_ok=True)


def _render_events(events: list[dict], *, width: int = 100) -> str:
    """Drive a fresh Renderer with ``events`` and return captured text.

    Each test gets a brand-new console + renderer so state from one
    baseline can't leak into another.
    """
    # ``record=True`` lets us pull every rendered character via
    # export_text(). ``force_terminal=True`` keeps panel borders
    # rendered even when stdout isn't a real TTY (CI runners).
    # ``no_color=True`` strips colour codes for clean text diffs.
    console = Console(
        record=True,
        width=width,
        force_terminal=True,
        no_color=True,
        highlight=False,
        soft_wrap=True,
        legacy_windows=False,
    )
    renderer = Renderer(console=console, show_thinking=True)
    for event in events:
        renderer.handle(event)
    # ``end_turn`` is what the live CLI calls at end-of-turn — it commits
    # buffered streaming tokens to scrollback (where ``export_text``
    # picks them up) and stops the rich.Live region. Without this,
    # token streams never make it into the captured text because Live
    # is configured ``transient=True`` (its last frame is erased on
    # stop). This was masking real renderer regressions: before the
    # fix, every streaming-tokens baseline was empty.
    renderer.end_turn()
    return console.export_text(clear=False)


def _compare_or_update(name: str, actual: str) -> None:
    """Diff ``actual`` against the baseline file under cli_baselines/.

    Writes the baseline if it doesn't exist or UPDATE_CLI_BASELINES=1.
    """
    path = _BASELINES / f"{name}.txt"
    update = os.environ.get("UPDATE_CLI_BASELINES") == "1"
    if update or not path.exists():
        path.write_text(actual, encoding="utf-8")
        if update:
            return
        # First-run: write the baseline and pass — the test still runs
        # to confirm rendering doesn't crash.
        return
    expected = path.read_text(encoding="utf-8")
    if actual == expected:
        return
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        fromfile=f"{name}.baseline.txt",
        tofile=f"{name}.actual.txt",
        lineterm="",
    ))
    pytest.fail(
        f"CLI baseline drift for {name!r}.\n"
        f"To accept the new output, re-run with "
        f"UPDATE_CLI_BASELINES=1 to regenerate the baseline.\n\n"
        f"{diff}",
    )


# ── Test cases ──────────────────────────────────────────────────────────────


def test_workflow_with_one_tool_call_success():
    """Most common shape: workflow_start → tool_call → tool_result → done."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf1", "name": "demo",
         "step_count": 1},
        {"type": "step_start", "step_id": "s1", "step_type": "sequential"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_read",
         "args": {"path": "main.py", "start_line": 1, "end_line": 10}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_read",
         "result": {"content": "print('hello')\n", "lines_read": 1},
         "duration_ms": 5},
        {"type": "step_done", "step_id": "s1", "duration_ms": 6},
        {"type": "workflow_done", "workflow_id": "wf1"},
    ]
    out = _render_events(events)
    _compare_or_update("workflow_one_tool_success", out)


def test_workflow_with_failed_tool_call():
    """Error path: tool_result with non-empty error field."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf2", "name": "fail-demo"},
        {"type": "step_start", "step_id": "s1", "step_type": "sequential"},
        {"type": "tool_call", "step_id": "s1", "tool": "shell_exec",
         "args": {"command": "missing-binary --flag"}},
        {"type": "tool_result", "step_id": "s1", "tool": "shell_exec",
         "result": None,
         "error": "command not found: missing-binary",
         "duration_ms": 2},
        {"type": "workflow_done", "workflow_id": "wf2"},
    ]
    out = _render_events(events)
    _compare_or_update("workflow_failed_tool", out)


def test_skill_load_renders_distinct_panel():
    """skill_load events get a custom panel with the skill name."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf3"},
        {"type": "tool_call", "step_id": "s1", "tool": "skill_load",
         "args": {"skill": "plan"}},
        {"type": "tool_result", "step_id": "s1", "tool": "skill_load",
         "result": {"skill": "plan", "char_count": 4321, "condensed": False},
         "duration_ms": 12},
        {"type": "workflow_done", "workflow_id": "wf3"},
    ]
    out = _render_events(events)
    _compare_or_update("skill_load_panel", out)


def test_token_streaming_renders_assistant_text():
    """Tokens stream into the live region; final state has full text."""
    events = [
        {"type": "token", "text": "Hello, "},
        {"type": "token", "text": "world! "},
        {"type": "token", "text": "Here's "},
        {"type": "token", "text": "your "},
        {"type": "token", "text": "answer."},
        {"type": "done"},
    ]
    out = _render_events(events)
    _compare_or_update("token_streaming", out)


def test_error_event_renders_error_panel():
    """Error events render as a red-bordered panel."""
    events = [
        {"type": "error", "message": "workflow failed: connection reset",
         "error_code": "engine_error"},
    ]
    out = _render_events(events)
    _compare_or_update("error_panel", out)


def test_variable_set_renders_inline_row():
    """variable_set events render compactly so the user sees what got stored."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "variable_set", "name": "plan", "var_type": "json",
         "size_bytes": 1234, "value_preview": '{"goal": "test"}'},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    out = _render_events(events)
    _compare_or_update("variable_set_row", out)


def test_loop_iteration_renders_inline():
    """Loop progress shows iteration N of M."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "loop_iteration", "step_id": "main_loop",
         "iteration": 3, "max": 10},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    out = _render_events(events)
    _compare_or_update("loop_iteration", out)


def test_thinking_block_renders_collapsible():
    """thinking events render as a quietly-styled reasoning panel."""
    events = [
        {"type": "thinking",
         "text": "Let me think about this. The user wants a Netflix clone."},
        {"type": "thinking",
         "text": " That requires real video assets and a responsive UI."},
        {"type": "thinking_end"},
        {"type": "token", "text": "Okay, I'll start with the project setup."},
        {"type": "done"},
    ]
    out = _render_events(events)
    _compare_or_update("thinking_block", out)


def test_full_turn_thinking_tools_answer():
    """End-to-end shape: thinking → tools → answer text → done."""
    events = [
        {"type": "thinking", "text": "Reading the file first."},
        {"type": "thinking_end"},
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_read",
         "args": {"path": "config.py"}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_read",
         "result": {"content": "DEBUG = True"}, "duration_ms": 3},
        {"type": "workflow_done", "workflow_id": "wf"},
        {"type": "token", "text": "Found "},
        {"type": "token", "text": "DEBUG=True "},
        {"type": "token", "text": "in config."},
        {"type": "done"},
    ]
    out = _render_events(events)
    _compare_or_update("full_turn", out)


def test_multiple_parallel_tool_calls():
    """Parallel step with several tool calls in flight."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "step_start", "step_id": "par", "step_type": "parallel"},
        {"type": "tool_call", "step_id": "p1", "tool": "web_fetch",
         "args": {"url": "https://example.com/a"}},
        {"type": "tool_call", "step_id": "p2", "tool": "web_fetch",
         "args": {"url": "https://example.com/b"}},
        {"type": "tool_result", "step_id": "p1", "tool": "web_fetch",
         "result": {"status": 200, "bytes": 1234}, "duration_ms": 90},
        {"type": "tool_result", "step_id": "p2", "tool": "web_fetch",
         "result": {"status": 200, "bytes": 5678}, "duration_ms": 120},
        {"type": "step_done", "step_id": "par", "duration_ms": 130},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    out = _render_events(events)
    _compare_or_update("parallel_tool_calls", out)


def test_compaction_event_renders_summary_panel():
    """Conversation compaction emits a summary the user should see."""
    events = [
        {"type": "compaction",
         "removed":         12,
         "kept":            6,
         "summary_preview":
            "Earlier discussion about Netflix clone scope and tech stack.",
         "tokens_removed":  4_200,
         "tokens_kept":     1_800},
    ]
    out = _render_events(events)
    _compare_or_update("compaction_panel", out)


def test_auto_continue_renders_inline_badge():
    """auto_continue events show a small badge so the user sees the
    engine is firing a follow-up turn on its own."""
    events = [
        {"type": "auto_continue",
         "reason": "agent ended with 'Now I'll wire up the player'",
         "depth":  1, "max": 10},
    ]
    out = _render_events(events)
    _compare_or_update("auto_continue_badge", out)


def test_validation_warning_renders_inline_caution():
    """Grounding-validator catches ungrounded URLs in assistant text."""
    events = [
        {"type": "validation_warning",
         "kind":     "ungrounded_urls",
         "message":  "Response cited 2 URLs that aren't in $facts.",
         "urls":     ["https://example.com/a", "https://example.com/b"]},
    ]
    out = _render_events(events)
    _compare_or_update("validation_warning", out)


def test_approval_required_renders_panel():
    """approval_required events surface the tool + message inline."""
    events = [
        {"type": "approval_required",
         "request_id":     "a1",
         "approval_type":  "confirm",
         "tool":           "shell_exec",
         "step_id":        "s1",
         "message":        "Run `npm install`?",
         "args":           {"command": "npm install", "cwd": "/workspace"}},
    ]
    out = _render_events(events)
    _compare_or_update("approval_required", out)


def test_workspace_scope_approval_distinct_from_confirm():
    """workspace_scope approvals get their own framing — three options
    instead of approve/deny."""
    events = [
        {"type": "approval_required",
         "request_id":     "a2",
         "approval_type":  "workspace_scope",
         "tool":           "file_write",
         "step_id":        "s1",
         "message":        "Chika wants to write outside the workspace.",
         "args": {
             "path":      "/Users/test/Downloads/netflix/index.html",
             "scope_dir": "/Users/test/Downloads/netflix",
             "workspace": "/workspace",
             "action":    "write",
         }},
    ]
    out = _render_events(events)
    _compare_or_update("approval_workspace_scope", out)


def test_loop_with_iterations_progress():
    """Loop with multiple iteration ticks shown in scrollback."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "step_start", "step_id": "main_loop", "step_type": "loop"},
        {"type": "loop_iteration", "step_id": "main_loop",
         "iteration": 1, "max": 5},
        {"type": "loop_iteration", "step_id": "main_loop",
         "iteration": 2, "max": 5},
        {"type": "loop_iteration", "step_id": "main_loop",
         "iteration": 3, "max": 5},
        {"type": "step_done", "step_id": "main_loop", "duration_ms": 400},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    out = _render_events(events)
    _compare_or_update("loop_progress", out)


def test_map_item_progress():
    """map step iterates over a collection — each item gets its own row."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "step_start", "step_id": "map_step", "step_type": "map"},
        {"type": "map_item", "step_id": "map_step",
         "index": 0, "value": "alpha"},
        {"type": "map_item", "step_id": "map_step",
         "index": 1, "value": "beta"},
        {"type": "map_item", "step_id": "map_step",
         "index": 2, "value": "gamma"},
        {"type": "step_done", "step_id": "map_step", "duration_ms": 60},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    out = _render_events(events)
    _compare_or_update("map_progress", out)


def test_retry_attempt_shows_attempt_count():
    """Retry steps surface attempt N of M so the user sees backoff."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "step_start", "step_id": "fetcher", "step_type": "retry"},
        {"type": "retry_attempt", "step_id": "fetcher",
         "attempt": 1, "max": 3,
         "reason": "previous: HTTP 503 from upstream"},
        {"type": "retry_attempt", "step_id": "fetcher",
         "attempt": 2, "max": 3,
         "reason": "previous: connection reset"},
        {"type": "step_done", "step_id": "fetcher", "duration_ms": 800},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    out = _render_events(events)
    _compare_or_update("retry_attempts", out)


def test_chat_title_event():
    """chat_title shows up at the top of the next render."""
    events = [
        {"type": "chat_title", "title": "Build Netflix clone"},
    ]
    out = _render_events(events)
    _compare_or_update("chat_title", out)


def test_cancelled_event_renders_clear_marker():
    """cancelled events are shown so the user knows we stopped."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "shell_exec",
         "args": {"command": "long-running-task"}},
        {"type": "cancelled"},
    ]
    out = _render_events(events)
    _compare_or_update("cancelled_event", out)


def test_long_tool_args_get_truncated():
    """Args longer than the preview cap show a '…' suffix; baselines
    pin exactly how that truncation looks."""
    long = "x" * 400
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "shell_exec",
         "args": {"command": long}},
        {"type": "tool_result", "step_id": "s1", "tool": "shell_exec",
         "result": {"stdout": "ok\n"}, "duration_ms": 1},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    out = _render_events(events)
    _compare_or_update("long_args_truncated", out)


def test_tool_result_with_long_output_truncated():
    """Multi-line tool results get capped at a max line count."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "shell_exec",
         "args": {"command": "ls -la /"}},
        {"type": "tool_result", "step_id": "s1", "tool": "shell_exec",
         "result": {
             "stdout": "\n".join(f"line-{i}" for i in range(40)),
             "exit_code": 0,
         },
         "duration_ms": 8},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    out = _render_events(events)
    _compare_or_update("long_output_truncated", out)


def test_condition_eval_rendering():
    """condition_eval shows the predicate result with a ✓/✗ glyph."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "condition_eval", "step_id": "guard",
         "result": True,
         "expression": "$response.status == 200"},
        {"type": "condition_eval", "step_id": "guard2",
         "result": False,
         "expression": "$count > 10"},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    out = _render_events(events)
    _compare_or_update("condition_eval", out)


def test_browser_watch_trigger_rendering():
    """browser_watch_trigger surfaces inline so the user sees what fired."""
    events = [
        {"type": "browser_watch_trigger",
         "event_name": "price_changed",
         "data": {
             "selector": ".product-price",
             "previous": "$99.99",
             "current":  "$79.99",
         }},
    ]
    out = _render_events(events)
    _compare_or_update("browser_watch_trigger", out)


def test_extension_status_connected_disconnected():
    """extension_status events show a paired-state line."""
    events = [
        {"type": "extension_status", "connected": True},
        {"type": "extension_status", "connected": False},
    ]
    out = _render_events(events)
    _compare_or_update("extension_status", out)


def test_skill_load_condensed_vs_verbatim():
    """When skill_load condenses a long doc, the panel marks ``condensed``."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "skill_load",
         "args": {"skill": "browser"}},
        {"type": "tool_result", "step_id": "s1", "tool": "skill_load",
         "result": {
             "skill":      "browser",
             "char_count": 25_400,
             "condensed":  True,
         },
         "duration_ms": 850},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    out = _render_events(events)
    _compare_or_update("skill_load_condensed", out)


def test_multi_workflow_in_one_turn():
    """When the agent fires multiple workflows in a single turn, each
    one renders its own panel."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf1", "name": "first"},
        {"type": "tool_call", "step_id": "a", "tool": "file_read",
         "args": {"path": "x.py"}},
        {"type": "tool_result", "step_id": "a", "tool": "file_read",
         "result": {"content": "x"}, "duration_ms": 1},
        {"type": "workflow_done", "workflow_id": "wf1"},
        {"type": "workflow_start", "workflow_id": "wf2", "name": "second"},
        {"type": "tool_call", "step_id": "b", "tool": "shell_exec",
         "args": {"command": "echo hi"}},
        {"type": "tool_result", "step_id": "b", "tool": "shell_exec",
         "result": {"stdout": "hi\n"}, "duration_ms": 2},
        {"type": "workflow_done", "workflow_id": "wf2"},
    ]
    out = _render_events(events)
    _compare_or_update("multi_workflow", out)


def test_token_with_markdown_styling():
    """Markdown in assistant text (bold, code) round-trips through the
    streaming render — baseline pins exact output so a markdown-parser
    swap can't silently break formatting."""
    events = [
        {"type": "token",
         "text":
            "Here's the **fix**: use `file_replace` instead of writing a "
            "new file.\n\nThe key insight is that "},
        {"type": "token",
         "text": "*editing in place* preserves history."},
        {"type": "done"},
    ]
    out = _render_events(events)
    _compare_or_update("markdown_styled_tokens", out)


# ── Tool-specific renders ──────────────────────────────────────────────


def test_file_write_tool_call():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_write",
         "args": {"path": "src/main.py",
                  "content": "import config\nprint(config.NAME)"}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_write",
         "result": {"path": "src/main.py", "bytes_written": 42},
         "duration_ms": 4},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_file_write", _render_events(events))


def test_file_replace_tool_call():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_replace",
         "args": {"path": "src/main.py", "old": "DEBUG=True", "new": "DEBUG=False"}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_replace",
         "result": {"replacements": 1}, "duration_ms": 2},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_file_replace", _render_events(events))


def test_file_read_with_line_range():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_read",
         "args": {"path": "src/utils.py", "start_line": 50, "end_line": 80}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_read",
         "result": {"content": "def helper():\n    return 1"},
         "duration_ms": 3},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_file_read_range", _render_events(events))


def test_web_search_tool_call():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "web_search",
         "args": {"query": "best vue 3 component library 2026", "max_results": 5}},
        {"type": "tool_result", "step_id": "s1", "tool": "web_search",
         "result": {
             "query":   "best vue 3 component library 2026",
             "results": [
                 {"title": "Vuetify",  "url": "https://vuetifyjs.com"},
                 {"title": "Naive UI", "url": "https://www.naiveui.com"},
             ],
         },
         "duration_ms": 320},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_web_search", _render_events(events))


def test_web_fetch_tool_call():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "web_fetch",
         "args": {"url": "https://example.com/api/data.json"}},
        {"type": "tool_result", "step_id": "s1", "tool": "web_fetch",
         "result": {"status": 200, "bytes": 4321,
                    "content_type": "application/json"},
         "duration_ms": 215},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_web_fetch", _render_events(events))


def test_browser_navigate_tool_call():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_navigate",
         "args": {"url": "https://github.com/anthropics/claude-code"}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_navigate",
         "result": {"tab_id": 42, "url": "https://github.com/anthropics/claude-code"},
         "duration_ms": 850},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_browser_navigate", _render_events(events))


def test_browser_screenshot_tool_call():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_screenshot",
         "args": {"tab_id": 42}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_screenshot",
         "result": {"image": "<base64-png>", "width": 1280, "height": 720},
         "duration_ms": 95},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_browser_screenshot", _render_events(events))


def test_git_commit_tool_call():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "git_commit",
         "args": {"message": "feat: ship the demo", "files": ["src/main.py", "README.md"]}},
        {"type": "tool_result", "step_id": "s1", "tool": "git_commit",
         "result": {"sha": "abc123def", "files_changed": 2},
         "duration_ms": 60},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_git_commit", _render_events(events))


def test_memory_persist_tool_call():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "memory_persist",
         "args": {"name": "user_role",
                  "description": "User is a senior data scientist",
                  "type": "user",
                  "body": "User is a data scientist focused on observability."}},
        {"type": "tool_result", "step_id": "s1", "tool": "memory_persist",
         "result": {"saved": True, "name": "user_role"},
         "duration_ms": 8},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_memory_persist", _render_events(events))


def test_python_run_tool_call():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "python_run",
         "args": {"code": "import json\nprint(json.dumps({'ok': True}))"}},
        {"type": "tool_result", "step_id": "s1", "tool": "python_run",
         "result": {"stdout": '{"ok": true}\n', "exit_code": 0},
         "duration_ms": 22},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_python_run", _render_events(events))


# ── Edge cases ──────────────────────────────────────────────────────────


def test_tool_call_with_no_args():
    """Some tools (plan_get, browser_get_active_tab) take no args."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "plan_get", "args": {}},
        {"type": "tool_result", "step_id": "s1", "tool": "plan_get",
         "result": {"plan": None}, "duration_ms": 1},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_call_no_args", _render_events(events))


def test_tool_result_with_complex_nested_object():
    """Deeply nested results truncate properly (line + char caps)."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_get_dom",
         "args": {"selector": "main"}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_get_dom",
         "result": {
             "html": "<main>" + "<div></div>" * 100 + "</main>",
             "url":   "https://example.com/page",
             "title": "Example Domain",
             "metadata": {"depth": 4, "elements": 134, "scripts": 2},
         },
         "duration_ms": 30},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_complex_nested_result", _render_events(events))


def test_workflow_with_no_name():
    """workflow_start without a name still renders cleanly."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf-no-name"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_read",
         "args": {"path": "x.py"}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_read",
         "result": {"content": "x"}, "duration_ms": 1},
        {"type": "workflow_done", "workflow_id": "wf-no-name"},
    ]
    _compare_or_update("workflow_no_name", _render_events(events))


def test_tool_result_unicode_content():
    """Non-ASCII tool output renders without mangling."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_read",
         "args": {"path": "greetings.txt"}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_read",
         "result": {"content": "Hello 世界! Привет 🌍"},
         "duration_ms": 2},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_unicode_result", _render_events(events))


def test_step_with_zero_duration():
    """0ms duration renders as 0ms (not blank, not -1ms)."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "plan_set",
         "args": {"tasks": ["a"]}},
        {"type": "tool_result", "step_id": "s1", "tool": "plan_set",
         "result": {"_source": "plan_set", "count": 1},
         "duration_ms": 0},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("zero_duration", _render_events(events))


def test_step_with_high_duration():
    """A multi-second duration renders as expected (e.g. 12340ms)."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "shell_exec",
         "args": {"command": "npm install"}},
        {"type": "tool_result", "step_id": "s1", "tool": "shell_exec",
         "result": {"exit_code": 0, "stdout": "added 234 packages\n"},
         "duration_ms": 12340},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("high_duration", _render_events(events))


def test_string_arg_with_quotes_and_newlines():
    """JSON encoding keeps quotes + newlines visible in the args preview."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_write",
         "args": {"path": "out.json",
                  "content": '{"name": "value", "list": ["a", "b"]}\n'}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_write",
         "result": {"bytes_written": 36}, "duration_ms": 1},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("args_with_quotes_newlines", _render_events(events))


def test_tool_call_with_bytes_result():
    """Tools that return base64 / binary still render compactly."""
    import base64
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_screenshot",
         "args": {"tab_id": 12}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_screenshot",
         "result": {
             "image_bytes": base64.b64encode(b"\x89PNG" + b"\x00" * 20).decode(),
             "width":  1280, "height": 720,
         },
         "duration_ms": 88},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_bytes_result", _render_events(events))


def test_tool_call_with_none_result():
    """Some tools return literal None (e.g. memory_forget on miss)."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "memory_forget",
         "args": {"name": "ghost"}},
        {"type": "tool_result", "step_id": "s1", "tool": "memory_forget",
         "result": None, "duration_ms": 0},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_none_result", _render_events(events))


def test_thinking_only_no_answer():
    """Thinking content without any subsequent token still renders."""
    events = [
        {"type": "thinking", "text": "Considering the request..."},
        {"type": "thinking", "text": " Decision: skip — unsafe action."},
        {"type": "thinking_end"},
        {"type": "done"},
    ]
    _compare_or_update("thinking_only", _render_events(events))


def test_multiple_thinking_blocks():
    """Multiple thinking → answer → thinking → answer cycles."""
    events = [
        {"type": "thinking", "text": "First reflection."},
        {"type": "thinking_end"},
        {"type": "token", "text": "Initial answer. "},
        {"type": "thinking", "text": "Second reflection — refining."},
        {"type": "thinking_end"},
        {"type": "token", "text": "Refined answer."},
        {"type": "done"},
    ]
    _compare_or_update("multiple_thinking_blocks", _render_events(events))


def test_chat_title_followed_by_workflow():
    """Title bar + first workflow render in the right order."""
    events = [
        {"type": "chat_title", "title": "Build Netflix clone"},
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "plan_set",
         "args": {"goal": "Netflix clone", "tasks": ["scaffold", "ui", "tests"]}},
        {"type": "tool_result", "step_id": "s1", "tool": "plan_set",
         "result": {"_source": "plan_set", "count": 3}, "duration_ms": 2},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("chat_title_then_workflow", _render_events(events))


def test_compaction_then_workflow():
    """Compaction summary + new workflow in the same turn."""
    events = [
        {"type": "compaction", "removed": 8, "kept": 4,
         "summary_preview": "Earlier discussion about API design."},
        {"type": "workflow_start", "workflow_id": "wf2"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_read",
         "args": {"path": "api.py"}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_read",
         "result": {"content": "x"}, "duration_ms": 1},
        {"type": "workflow_done", "workflow_id": "wf2"},
    ]
    _compare_or_update("compaction_then_workflow", _render_events(events))


def test_extension_status_then_browser_action():
    """Extension paired event + browser_navigate render in the right order."""
    events = [
        {"type": "extension_status", "connected": True},
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_get_active_tab", "args": {}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_get_active_tab",
         "result": {"tab_id": 1, "url": "https://github.com", "title": "GitHub"},
         "duration_ms": 12},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("ext_status_then_browser", _render_events(events))


def test_workflow_only_workflow_start():
    """workflow_start with no follow-up shouldn't crash the renderer."""
    events = [{"type": "workflow_start", "workflow_id": "wf"}]
    _compare_or_update("workflow_start_alone", _render_events(events))


def test_workflow_done_without_start():
    """workflow_done arriving without a matching start: should be tolerated."""
    events = [{"type": "workflow_done", "workflow_id": "wf-orphan"}]
    _compare_or_update("workflow_done_orphan", _render_events(events))


def test_step_start_without_workflow():
    """step_start outside a workflow still renders cleanly."""
    events = [{"type": "step_start", "step_id": "s1", "step_type": "sequential"}]
    _compare_or_update("step_start_orphan", _render_events(events))


def test_tool_result_without_call():
    """A tool_result with no preceding tool_call (e.g. cached/replayed)."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_result", "step_id": "ghost", "tool": "file_read",
         "result": {"content": "cached"}, "duration_ms": 0},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_result_orphan", _render_events(events))


def test_two_consecutive_tokens_no_space():
    """Tokens concatenate without inserted whitespace."""
    events = [
        {"type": "token", "text": "Hello"},
        {"type": "token", "text": "World"},
        {"type": "done"},
    ]
    _compare_or_update("tokens_no_space", _render_events(events))


def test_token_with_emoji():
    """Emojis in tokens render through the rich console."""
    events = [
        {"type": "token", "text": "Build complete! 🎉 Ready to ship."},
        {"type": "done"},
    ]
    _compare_or_update("token_emoji", _render_events(events))


def test_token_with_code_block():
    """Markdown code fences in streaming text."""
    events = [
        {"type": "token", "text": "Here's the snippet:\n\n```python\n"},
        {"type": "token", "text": "def hello():\n    print('hi')\n"},
        {"type": "token", "text": "```\n\nSave that to `app.py`."},
        {"type": "done"},
    ]
    _compare_or_update("token_code_block", _render_events(events))


def test_token_with_list():
    """Markdown lists in streaming text."""
    events = [
        {"type": "token", "text": "Steps:\n\n1. First step\n2. Second step\n3. Third step"},
        {"type": "done"},
    ]
    _compare_or_update("token_with_list", _render_events(events))


def test_token_with_link():
    """Markdown links in streaming text."""
    events = [
        {"type": "token", "text": "See [the docs](https://docs.example.com) for details."},
        {"type": "done"},
    ]
    _compare_or_update("token_with_link", _render_events(events))


def test_long_skill_name_in_skill_load():
    """Very long skill names truncate properly in the panel header."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "skill_load",
         "args": {"skill": "extremely_long_skill_name_with_underscores"}},
        {"type": "tool_result", "step_id": "s1", "tool": "skill_load",
         "result": {"skill": "extremely_long_skill_name_with_underscores",
                    "char_count": 8000, "condensed": False},
         "duration_ms": 12},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("skill_load_long_name", _render_events(events))


def test_loop_iteration_with_high_max():
    """Loop iteration with high max number alignment."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "loop_iteration", "step_id": "scrape", "iteration": 47, "max": 1000},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("loop_high_max", _render_events(events))


def test_loop_iteration_no_max():
    """Loop without a max bound (e.g. while-true)."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "loop_iteration", "step_id": "watch", "iteration": 3},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("loop_no_max", _render_events(events))


def test_condition_eval_string_result():
    """condition_eval where result is a string, not boolean."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "condition_eval", "step_id": "router",
         "result": "branch_a", "expression": "$state.kind"},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("condition_string", _render_events(events))


def test_variable_set_with_large_size():
    """variable_set with a multi-MB payload renders the size compactly."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "variable_set", "name": "scraped_data",
         "var_type": "json", "size_bytes": 2_400_000,
         "value_preview": "[{...}, {...}, {...}]"},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("variable_set_large", _render_events(events))


def test_variable_set_string_type():
    """variable_set with var_type=text."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "variable_set", "name": "summary",
         "var_type": "text", "size_bytes": 540,
         "value_preview": "The article discusses streaming services..."},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("variable_set_text", _render_events(events))


def test_variable_set_file_path_type():
    """variable_set with var_type=file_path."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "variable_set", "name": "screenshot",
         "var_type": "file_path", "size_bytes": 80,
         "value_preview": "/tmp/screenshot-1234567.png"},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("variable_set_file_path", _render_events(events))


def test_validation_warning_no_urls():
    """Validation warning that fires for non-URL grounding issues."""
    events = [
        {"type": "validation_warning",
         "kind":     "ungrounded_claim",
         "message":  "Response made claims that aren't in $facts."},
    ]
    _compare_or_update("validation_warning_no_urls", _render_events(events))


def test_retry_notice():
    """retry_notice fires when an LLM retry kicks in mid-stream."""
    events = [
        {"type": "retry_notice",
         "message": "rate-limited — retrying in 2s",
         "attempt": 1, "max": 5},
    ]
    _compare_or_update("retry_notice", _render_events(events))


def test_auto_continue_blocked():
    """auto_continue_blocked when the cap is reached."""
    events = [
        {"type": "auto_continue_blocked",
         "reason": "max depth reached",
         "depth":  10,
         "max":    10},
    ]
    _compare_or_update("auto_continue_blocked", _render_events(events))


def test_browser_watch_with_no_data():
    """browser_watch_trigger without a `data` payload."""
    events = [
        {"type": "browser_watch_trigger", "event_name": "page_load"},
    ]
    _compare_or_update("browser_watch_no_data", _render_events(events))


def test_workflow_with_skill_then_other_tool():
    """skill_load followed by a tool from that skill renders both panels."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "skill_load",
         "args": {"skill": "browser"}},
        {"type": "tool_result", "step_id": "s1", "tool": "skill_load",
         "result": {"skill": "browser", "char_count": 8000, "condensed": False},
         "duration_ms": 4},
        {"type": "tool_call", "step_id": "s2", "tool": "browser_navigate",
         "args": {"url": "https://example.com"}},
        {"type": "tool_result", "step_id": "s2", "tool": "browser_navigate",
         "result": {"tab_id": 1}, "duration_ms": 200},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("skill_then_browser", _render_events(events))


def test_no_empty_baselines():
    """CI guard — fail if any baseline file is empty or pure whitespace
    (and not on the documented intentional-silence allowlist).

    An empty baseline means the renderer didn't surface anything for
    that event type — the agent's output was invisible to the user.
    Every event MUST produce visible UI: add an ``_on_<event_type>``
    handler in ``chika/_cli/renderer.py`` (or extend ``end_turn`` to
    flush whatever the new event leaves behind) and re-baseline.
    """
    offenders: list[tuple[str, int]] = []
    for path in sorted(_BASELINES.glob("*.txt")):
        name = path.stem
        text = path.read_text(encoding="utf-8")
        non_ws = "".join(text.split())
        if len(non_ws) >= 4:
            continue
        offenders.append((name, len(non_ws)))

    assert not offenders, (
        "CLI baseline file(s) are empty or near-empty:\n"
        + "\n".join(f"  - {name} ({n} non-ws chars)" for name, n in offenders)
        + "\n\nFix: add an `_on_<event_type>` handler in "
        "``chika/_cli/renderer.py`` (or extend ``end_turn``) so the "
        "event produces visible output, then regenerate the baseline."
    )


def test_no_duplicate_baselines_across_files():
    """Two different baseline files should NEVER have identical content
    — that means we're snapshotting the same render twice and only
    catching half the regressions we think we are.

    Allowlist exact pairs that are intentionally identical (e.g. two
    tests of disjoint event types both produce empty output).
    """
    # Pairs whose identical output is documented + intentional. Empty
    # by default — every test should produce distinct rendered output.
    # If a duplicate slips through, fix the test fixture so the two
    # renderings differ rather than allowlisting the dup here.
    _ALLOWED_DUPES: set[frozenset[str]] = set()

    by_content: dict[str, list[str]] = {}
    for path in sorted(_BASELINES.glob("*.txt")):
        content = path.read_text(encoding="utf-8")
        by_content.setdefault(content, []).append(path.stem)

    duplicates: list[tuple[str, str]] = []
    for names in by_content.values():
        if len(names) < 2:
            continue
        # Generate every unordered pair within the duplicate group.
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if frozenset({a, b}) not in _ALLOWED_DUPES:
                    duplicates.append((a, b))

    assert not duplicates, (
        "Found CLI baseline files with identical content. Either:\n"
        "  - The two tests are genuinely covering the same render — "
        "remove one, OR distinguish them with different fixtures.\n"
        "  - The duplication is intentional — add the pair to "
        "_ALLOWED_DUPES with a comment.\n\n"
        "Duplicates:\n"
        + "\n".join(f"  - {a} == {b}" for a, b in duplicates)
    )


def test_no_duplicate_visual_baselines_frontend():
    """Same duplicate guard, applied to the frontend Playwright PNG
    baselines. Two snapshot files with identical bytes mean we're
    snapshotting the same render under two different names — a
    coverage hole disguised as coverage.
    """
    # Documented same-render pairs. Add only after eyeballing the diff
    # and confirming the duplication is unavoidable. Empty by default —
    # if a baseline matches another, fix the fixture so it doesn't.
    _allowed: set[frozenset[str]] = set()
    _check_no_duplicate_binaries(
        Path(__file__).parent.parent / "frontend" / "e2e",
        ".png",
        allowed_pairs=_allowed,
    )


def test_no_duplicate_visual_baselines_extension():
    """Same guard for the extension popup baselines."""
    _check_no_duplicate_binaries(
        Path(__file__).parent.parent / "extension" / "e2e",
        ".png",
        allowed_pairs=set(),
    )


def _check_no_duplicate_binaries(
    root: Path,
    suffix: str,
    *,
    allowed_pairs: set[frozenset[str]],
) -> None:
    """Walk every ``*.png`` (or ``suffix``) below ``root`` and fail the
    test if any two files have identical content. Hashes for speed.
    """
    import hashlib

    if not root.exists():
        return  # No directory yet — nothing to check.

    by_hash: dict[str, list[Path]] = {}
    for path in root.rglob(f"*{suffix}"):
        # Skip Playwright's debug attachments (test-results/) — they're
        # transient screenshots from failed runs, not committed baselines.
        if "test-results" in path.parts:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        by_hash.setdefault(digest, []).append(path)

    duplicates: list[tuple[str, str]] = []
    for paths in by_hash.values():
        if len(paths) < 2:
            continue
        names = [str(p.relative_to(root)) for p in paths]
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if frozenset({a, b}) not in allowed_pairs:
                    duplicates.append((a, b))

    assert not duplicates, (
        f"Found visual baseline files with identical content under {root}.\n"
        "Duplicate baselines mean two tests think they're snapshotting "
        "different things but actually capture the same render. Either:\n"
        "  - Vary the fixture so the renders differ (recommended).\n"
        "  - Remove the duplicate test.\n"
        "  - Add the pair to ``allowed_pairs`` if intentional.\n\n"
        + "\n".join(f"  - {a} == {b}" for a, b in duplicates)
    )




# ── Additional tool baselines ──────────────────────────────────────────


def test_tool_dir_list():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "dir_list",
         "args": {"path": "src/", "max_depth": 2}},
        {"type": "tool_result", "step_id": "s1", "tool": "dir_list",
         "result": {"entries": ["main.py", "utils.py", "tests/"]},
         "duration_ms": 4},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_dir_list", _render_events(events))


def test_tool_file_search():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_search",
         "args": {"pattern": "TODO", "path": "src/"}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_search",
         "result": {"matches": [
             {"file": "src/main.py", "line": 42, "text": "# TODO: refactor"},
             {"file": "src/api.py",  "line": 18, "text": "# TODO: validate"},
         ]},
         "duration_ms": 23},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_file_search", _render_events(events))


def test_tool_file_append():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_append",
         "args": {"path": "log.txt", "content": "[2026-05-05] new entry\n"}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_append",
         "result": {"bytes_appended": 25}, "duration_ms": 1},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_file_append", _render_events(events))


def test_tool_file_edit_lines():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_edit_lines",
         "args": {"path": "main.py", "start": 5, "end": 8,
                  "replacement": "def updated():\n    pass"}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_edit_lines",
         "result": {"lines_changed": 4}, "duration_ms": 2},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_file_edit_lines", _render_events(events))


def test_tool_bg_shell_exec():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "bg_shell_exec",
         "args": {"command": "npm run dev"}},
        {"type": "tool_result", "step_id": "s1", "tool": "bg_shell_exec",
         "result": {"pid": 9876, "command": "npm run dev"},
         "duration_ms": 30},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_bg_shell_exec", _render_events(events))


def test_tool_shell_kill():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "shell_kill",
         "args": {"pid": 9876}},
        {"type": "tool_result", "step_id": "s1", "tool": "shell_kill",
         "result": {"killed": True, "pid": 9876}, "duration_ms": 5},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_shell_kill", _render_events(events))


def test_tool_shell_get_output():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "shell_get_output",
         "args": {"pid": 9876, "tail_lines": 20}},
        {"type": "tool_result", "step_id": "s1", "tool": "shell_get_output",
         "result": {"stdout": "ready on http://localhost:5173",
                    "running": True}, "duration_ms": 2},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_shell_get_output", _render_events(events))


def test_tool_live_server():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "live_server",
         "args": {"path": "./public", "port": 5500}},
        {"type": "tool_result", "step_id": "s1", "tool": "live_server",
         "result": {"url": "http://localhost:5500", "pid": 1234},
         "duration_ms": 120},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_live_server", _render_events(events))


def test_tool_scaffold_web_app():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "scaffold_web_app",
         "args": {"stack": "vite-react-ts", "name": "demo",
                  "target_dir": "./projects/demo", "install": True}},
        {"type": "tool_result", "step_id": "s1", "tool": "scaffold_web_app",
         "result": {"path": "./projects/demo", "deps_installed": 124,
                    "stack": "vite-react-ts"}, "duration_ms": 18000},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_scaffold_web_app", _render_events(events))


def test_tool_browser_click():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_click",
         "args": {"selector": "button[type=submit]"}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_click",
         "result": {"clicked": True, "selector": "button[type=submit]"},
         "duration_ms": 18},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_browser_click", _render_events(events))


def test_tool_browser_fill_input():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_fill_input",
         "args": {"selector": "input[name=email]",
                  "value": "user@example.com"}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_fill_input",
         "result": {"filled": True}, "duration_ms": 12},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_browser_fill_input", _render_events(events))


def test_tool_browser_get_text():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_get_text",
         "args": {"selector": "main", "find": "release"}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_get_text",
         "result": {"text": "Latest release: v2.0.0\nReleased 2 days ago",
                    "char_count": 42}, "duration_ms": 35},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_browser_get_text", _render_events(events))


def test_tool_browser_get_dom():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_get_dom",
         "args": {"selector": "ytd-video-renderer"}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_get_dom",
         "result": {"html": "<ytd-video-renderer>...</ytd-video-renderer>"},
         "duration_ms": 80},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_browser_get_dom", _render_events(events))


def test_tool_browser_get_page_var():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_get_page_var",
         "args": {"var_path": "ytInitialData.contents"}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_get_page_var",
         "result": {"too_large": True, "size_bytes": 2_400_000,
                    "keys_preview": ["twoColumnBrowseResultsRenderer"]},
         "duration_ms": 120},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_browser_get_page_var", _render_events(events))


def test_tool_browser_watch_element():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_watch_element",
         "args": {"selector": ".price", "event_name": "price_changed"}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_watch_element",
         "result": {"watch_id": "watch_1234", "selector": ".price"},
         "duration_ms": 8},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_browser_watch", _render_events(events))


def test_tool_git_status():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "git_status", "args": {}},
        {"type": "tool_result", "step_id": "s1", "tool": "git_status",
         "result": {"branch": "main", "ahead": 2, "behind": 0,
                    "modified": ["src/main.py"], "untracked": ["temp.txt"]},
         "duration_ms": 22},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_git_status", _render_events(events))


def test_tool_git_diff():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "git_diff",
         "args": {"file": "src/main.py"}},
        {"type": "tool_result", "step_id": "s1", "tool": "git_diff",
         "result": {"diff": "@@ -1,3 +1,3 @@\n-old\n+new\n"},
         "duration_ms": 10},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_git_diff", _render_events(events))


def test_tool_git_log():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "git_log",
         "args": {"limit": 5}},
        {"type": "tool_result", "step_id": "s1", "tool": "git_log",
         "result": {"commits": [
             {"sha": "abc1234", "msg": "feat: ship demo"},
             {"sha": "def5678", "msg": "fix: handle edge case"},
         ]}, "duration_ms": 7},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_git_log", _render_events(events))


def test_tool_git_push():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "git_push",
         "args": {"branch": "feature/demo"}},
        {"type": "tool_result", "step_id": "s1", "tool": "git_push",
         "result": {"pushed": True, "commits": 3}, "duration_ms": 1200},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_git_push", _render_events(events))


def test_tool_memory_recall():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "memory_recall",
         "args": {"query": "user role"}},
        {"type": "tool_result", "step_id": "s1", "tool": "memory_recall",
         "result": {"matches": [{"name": "user_role", "body": "data scientist"}]},
         "duration_ms": 6},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_memory_recall", _render_events(events))


def test_tool_memory_forget():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "memory_forget",
         "args": {"name": "old_preference"}},
        {"type": "tool_result", "step_id": "s1", "tool": "memory_forget",
         "result": {"removed": True, "name": "old_preference"},
         "duration_ms": 2},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_memory_forget", _render_events(events))


def test_tool_plan_set():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "plan_set",
         "args": {"goal": "Build the demo",
                  "tasks": [{"id": "t1", "text": "first", "status": "pending"}]}},
        {"type": "tool_result", "step_id": "s1", "tool": "plan_set",
         "result": {"_source": "plan_set", "count": 1},
         "duration_ms": 1},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_plan_set", _render_events(events))


def test_tool_plan_update():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "plan_update",
         "args": {"task_id": "t1", "status": "done"}},
        {"type": "tool_result", "step_id": "s1", "tool": "plan_update",
         "result": {"_source": "plan_update"}, "duration_ms": 1},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_plan_update", _render_events(events))


def test_tool_plan_add():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "plan_add",
         "args": {"text": "new sub-step", "parent_id": "t1"}},
        {"type": "tool_result", "step_id": "s1", "tool": "plan_add",
         "result": {"_source": "plan_add", "task_id": "t1.1"},
         "duration_ms": 1},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_plan_add", _render_events(events))


def test_tool_plan_remove():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "plan_remove",
         "args": {"task_id": "t2"}},
        {"type": "tool_result", "step_id": "s1", "tool": "plan_remove",
         "result": {"_source": "plan_remove"}, "duration_ms": 1},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_plan_remove", _render_events(events))


def test_tool_plan_archive():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "plan_archive",
         "args": {"reason": "user pivoted"}},
        {"type": "tool_result", "step_id": "s1", "tool": "plan_archive",
         "result": {"_source": "plan_archive", "archived": True},
         "duration_ms": 3},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_plan_archive", _render_events(events))


def test_tool_plan_history():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "plan_history", "args": {}},
        {"type": "tool_result", "step_id": "s1", "tool": "plan_history",
         "result": {"plans": [
             {"goal": "Earlier plan", "archived_at": 1700000000},
             {"goal": "Even earlier plan", "archived_at": 1690000000},
         ]}, "duration_ms": 4},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_plan_history", _render_events(events))


def test_tool_ask_user():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "ask_user",
         "args": {"question": "Which framework?",
                  "options": [{"label": "React"}, {"label": "Vue"}]}},
        {"type": "tool_result", "step_id": "s1", "tool": "ask_user",
         "result": {"choice": "Vue", "choice_index": 1},
         "duration_ms": 4500},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_ask_user", _render_events(events))


def test_tool_verify_url():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "verify_url",
         "args": {"url": "https://example.com"}},
        {"type": "tool_result", "step_id": "s1", "tool": "verify_url",
         "result": {"status": 200, "valid": True, "final_url": "https://example.com"},
         "duration_ms": 80},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_verify_url", _render_events(events))


def test_tool_web_head():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "web_head",
         "args": {"url": "https://example.com/heavy.zip"}},
        {"type": "tool_result", "step_id": "s1", "tool": "web_head",
         "result": {"status": 200, "size": 12345678,
                    "content_type": "application/zip"},
         "duration_ms": 50},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_web_head", _render_events(events))


def test_tool_app_open():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "app_open",
         "args": {"app": "Calculator"}},
        {"type": "tool_result", "step_id": "s1", "tool": "app_open",
         "result": {"opened": True, "app": "Calculator"},
         "duration_ms": 250},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_app_open", _render_events(events))


def test_tool_spotify_play():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "spotify_play",
         "args": {"query": "lo-fi beats"}},
        {"type": "tool_result", "step_id": "s1", "tool": "spotify_play",
         "result": {"now_playing": "Lofi Beats Mix", "uri": "spotify:track:abc123"},
         "duration_ms": 800},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_spotify_play", _render_events(events))


def test_tool_spotify_search():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "spotify_search",
         "args": {"query": "miles davis", "limit": 3}},
        {"type": "tool_result", "step_id": "s1", "tool": "spotify_search",
         "result": {"tracks": [
             {"name": "So What",      "uri": "spotify:track:1"},
             {"name": "Blue in Green", "uri": "spotify:track:2"},
         ]}, "duration_ms": 350},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_spotify_search", _render_events(events))


def test_tool_skill_query():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "skill_query",
         "args": {"skill": "browser", "query": "youtube history selector", "k": 3}},
        {"type": "tool_result", "step_id": "s1", "tool": "skill_query",
         "result": {"matches": [
             {"heading": "Pattern 8", "score": 0.92},
             {"heading": "Rule 3",    "score": 0.81},
         ]}, "duration_ms": 12},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_skill_query", _render_events(events))


def test_tool_llm_summarise():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "llm_summarise",
         "args": {"context": "$page", "prompt": "summarise this page"}},
        {"type": "tool_result", "step_id": "s1", "tool": "llm_summarise",
         "result": {"summary": "The article describes Vue 3 patterns."},
         "duration_ms": 2400},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_llm_summarise", _render_events(events))


def test_tool_llm_transform():
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "llm_transform",
         "args": {"context": "$results", "prompt": "Extract titles + URLs",
                  "schema": {"type": "array"}}},
        {"type": "tool_result", "step_id": "s1", "tool": "llm_transform",
         "result": [
             {"title": "First",  "url": "https://a.com"},
             {"title": "Second", "url": "https://b.com"},
         ], "duration_ms": 1800},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("tool_llm_transform", _render_events(events))


# ── Composite scenarios ────────────────────────────────────────────────


def test_long_workflow_many_steps():
    """A workflow with 6+ steps showing pacing of inline rows."""
    events = [{"type": "workflow_start", "workflow_id": "wf"}]
    for i, tool in enumerate([
        "file_read", "file_replace", "file_read", "shell_exec",
        "git_diff", "git_commit",
    ]):
        events += [
            {"type": "tool_call", "step_id": f"s{i}", "tool": tool,
             "args": {"x": i}},
            {"type": "tool_result", "step_id": f"s{i}", "tool": tool,
             "result": {"ok": True}, "duration_ms": 5},
        ]
    events += [{"type": "workflow_done", "workflow_id": "wf"}]
    _compare_or_update("long_workflow", _render_events(events))


def test_workflow_with_nested_substeps():
    """A workflow that nests parallel inside a sequential step."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "step_start", "step_id": "outer", "step_type": "sequential"},
        {"type": "step_start", "step_id": "fan",   "step_type": "parallel"},
        {"type": "tool_call", "step_id": "p1", "tool": "web_fetch",
         "args": {"url": "https://a.com"}},
        {"type": "tool_call", "step_id": "p2", "tool": "web_fetch",
         "args": {"url": "https://b.com"}},
        {"type": "tool_result", "step_id": "p1", "tool": "web_fetch",
         "result": {"status": 200}, "duration_ms": 80},
        {"type": "tool_result", "step_id": "p2", "tool": "web_fetch",
         "result": {"status": 200}, "duration_ms": 95},
        {"type": "step_done", "step_id": "fan", "duration_ms": 100},
        {"type": "step_done", "step_id": "outer", "duration_ms": 110},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("nested_substeps", _render_events(events))


def test_workflow_tool_call_then_error_then_recovery():
    """First call errors, then a recovery tool call succeeds."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "web_fetch",
         "args": {"url": "https://broken.example"}},
        {"type": "tool_result", "step_id": "s1", "tool": "web_fetch",
         "result": None, "error": "ECONNREFUSED", "duration_ms": 30},
        {"type": "tool_call", "step_id": "s2", "tool": "web_fetch",
         "args": {"url": "https://example.com/fallback"}},
        {"type": "tool_result", "step_id": "s2", "tool": "web_fetch",
         "result": {"status": 200, "bytes": 2400}, "duration_ms": 50},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("error_then_recovery", _render_events(events))


def test_step_done_with_zero_duration():
    """step_done with 0ms (e.g. for a one-shot tool wrapper)."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "step_start", "step_id": "s1", "step_type": "sequential"},
        {"type": "step_done",  "step_id": "s1", "duration_ms": 0},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("step_done_zero", _render_events(events))


def test_extension_status_then_workflow():
    """Extension paired event followed by a browser action."""
    events = [
        {"type": "extension_status", "connected": True},
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "tool_call", "step_id": "s1", "tool": "browser_get_active_tab",
         "args": {}},
        {"type": "tool_result", "step_id": "s1", "tool": "browser_get_active_tab",
         "result": {"tab_id": 1, "url": "https://github.com"},
         "duration_ms": 12},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("ext_paired_then_browser_v2", _render_events(events))


def test_browser_watch_with_full_data():
    """browser_watch_trigger with full data payload."""
    events = [
        {"type": "browser_watch_trigger",
         "event_name": "price_changed",
         "data": {
             "selector": ".price",
             "previous": "$99.99",
             "current":  "$79.99",
             "tab_id":   42,
         }},
    ]
    _compare_or_update("browser_watch_full", _render_events(events))


def test_extension_status_unpaired_alone():
    """A single disconnect event (without a prior pair) shouldn't crash."""
    events = [
        {"type": "extension_status", "connected": False},
    ]
    _compare_or_update("extension_status_unpaired", _render_events(events))


def test_three_step_sequential_workflow():
    """Three-step sequential render: read → edit → verify."""
    events = [
        {"type": "workflow_start", "workflow_id": "wf"},
        {"type": "step_start", "step_id": "seq", "step_type": "sequential"},
        {"type": "tool_call", "step_id": "s1", "tool": "file_read",
         "args": {"path": "main.py"}},
        {"type": "tool_result", "step_id": "s1", "tool": "file_read",
         "result": {"content": "x = 1"}, "duration_ms": 1},
        {"type": "tool_call", "step_id": "s2", "tool": "file_replace",
         "args": {"path": "main.py", "old": "x = 1", "new": "x = 2"}},
        {"type": "tool_result", "step_id": "s2", "tool": "file_replace",
         "result": {"replacements": 1}, "duration_ms": 1},
        {"type": "tool_call", "step_id": "s3", "tool": "shell_exec",
         "args": {"command": "python main.py"}},
        {"type": "tool_result", "step_id": "s3", "tool": "shell_exec",
         "result": {"stdout": "2\n", "exit_code": 0}, "duration_ms": 14},
        {"type": "step_done", "step_id": "seq", "duration_ms": 18},
        {"type": "workflow_done", "workflow_id": "wf"},
    ]
    _compare_or_update("three_step_sequential", _render_events(events))
