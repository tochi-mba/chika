"""Tests for chika/_cli/tool_summaries.py.

Locks down each per-tool formatter so a regression in one doesn't
silently fall back to the JSON dump (which would be invisible bug rot).
Each formatter has at least one happy path, one fall-through-to-None
path, and one malformed-input path verifying the try/except in
``summarise()`` swallows formatter bugs without breaking rendering.
"""
from __future__ import annotations

import pytest

from chika._cli import tool_summaries as ts


# ── summarise() core dispatch ────────────────────────────────────────


def test_unknown_tool_returns_none():
    """Tools without a registered formatter must fall through to None
    so the renderer's JSON-dump fallback kicks in."""
    assert ts.summarise("totally_made_up_tool", {"foo": "bar"}) is None


def test_formatter_exception_swallowed():
    """A formatter raising must NEVER break tool rendering."""
    # file_read accepts dict; pass an int → AttributeError on .get
    assert ts.summarise("file_read", 42) is None


def test_non_dict_result_returns_none_for_dict_formatter():
    """Most formatters check isObj/isinstance(r, dict) — non-dict in
    must return None."""
    for tool in ("file_read", "web_fetch", "browser_screenshot",
                 "plan_set", "git_commit"):
        assert ts.summarise(tool, "string-result") is None
        assert ts.summarise(tool, [1, 2, 3]) is None
        assert ts.summarise(tool, None) is None


# ── _short helper ────────────────────────────────────────────────────


def test_short_truncates_with_ellipsis():
    assert ts._short("hello world", 11) == "hello world"
    assert ts._short("hello world", 5) == "hell…"


def test_short_strips_newlines():
    assert ts._short("line1\nline2", 30) == "line1 line2"


def test_short_handles_none():
    assert ts._short(None) == "None"  # str(None) per the impl


# ── File tools ───────────────────────────────────────────────────────


def test_file_read_with_line_count_and_total_partial():
    """When line_count != total, surface both numbers."""
    out = ts.summarise("file_read", {
        "path": "src/foo.py", "line_count": 30, "total_lines": 200,
    })
    assert out == "read 30/200 lines · src/foo.py"


def test_file_read_with_total_full_file():
    out = ts.summarise("file_read", {
        "path": "x.py", "line_count": 100, "total_lines": 100,
    })
    assert out == "read 100 lines · x.py"


def test_file_read_with_only_size():
    out = ts.summarise("file_read", {"path": "x.bin", "size_bytes": 4096})
    assert out == "4096B · x.bin"


def test_file_read_with_only_content_falls_back_to_line_count():
    out = ts.summarise("file_read", {"content": "a\nb\nc"})
    assert out == "read 3 lines"


def test_file_read_with_empty_content():
    out = ts.summarise("file_read", {"content": ""})
    assert out == "read 0 lines"


def test_file_read_with_no_useful_fields_returns_none():
    """Empty dict → no formatter info → fall through."""
    assert ts.summarise("file_read", {}) is None


def test_file_write_with_size_bytes():
    out = ts.summarise("file_write", {"path": "x.txt", "size_bytes": 12})
    assert out == "wrote 12B → x.txt"


def test_file_write_with_bytes_written_alias():
    out = ts.summarise("file_write", {"path": "x.txt", "bytes_written": 50})
    assert out == "wrote 50B → x.txt"


def test_file_write_no_size_with_path():
    out = ts.summarise("file_write", {"path": "x.txt"})
    assert out == "wrote → x.txt"


def test_file_edit_lines_summary():
    out = ts.summarise("file_edit_lines", {
        "lines_replaced": 5, "total_lines": 100,
    })
    assert out == "replaced 5 lines · 100 lines total"


def test_file_replace_summary():
    out = ts.summarise("file_replace", {"replaced": True, "path": "x.py"})
    assert out == "replaced 1 occurrence · x.py"


def test_file_replace_when_not_replaced_returns_none():
    assert ts.summarise("file_replace", {"replaced": False, "path": "x.py"}) is None


def test_file_append_summary():
    out = ts.summarise("file_append", {"appended_bytes": 24, "path": "log.txt"})
    assert out == "appended 24B → log.txt"


def test_file_info_directory():
    out = ts.summarise("file_info", {"path": "/tmp/x", "is_dir": True})
    assert out == "directory · /tmp/x"


def test_file_info_with_size_and_extension():
    out = ts.summarise("file_info", {
        "path": "x.py", "size_bytes": 100, "extension": ".py",
    })
    assert out == "100B · .py · x.py"


# ── Shell tools ──────────────────────────────────────────────────────


def test_shell_exec_exit_zero_with_output():
    out = ts.summarise("shell_exec", {"exit_code": 0, "stdout": "hello\n"})
    assert out == "exit 0 · hello"


def test_shell_exec_exit_zero_no_output():
    out = ts.summarise("shell_exec", {"exit_code": 0, "stdout": ""})
    assert out == "exit 0"


def test_shell_exec_returncode_alias():
    """Some shells use ``returncode`` instead of ``exit_code``."""
    out = ts.summarise("shell_exec", {"returncode": 1, "stdout": "fail"})
    assert out == "exit 1 · fail"


def test_shell_exec_background_pid():
    out = ts.summarise("shell_exec", {"pid": 1234, "background": True})
    assert out == "started · pid 1234"


def test_shell_get_output_with_pid():
    out = ts.summarise("shell_get_output", {"pid": 99, "stdout": "a\nb\nc"})
    assert out == "pid 99 · 3 lines"


def test_shell_get_output_no_pid_one_line():
    out = ts.summarise("shell_get_output", {"stdout": "single line"})
    assert out == "1 line"


def test_shell_kill_killed_true():
    out = ts.summarise("shell_kill", {"killed": True, "pid": 42})
    assert out == "killed pid 42"


# ── Web tools ────────────────────────────────────────────────────────


def test_web_fetch_full_summary():
    out = ts.summarise("web_fetch", {
        "status": 200, "bytes": 4096, "url": "https://example.com",
    })
    assert out == "200 · 4096B · https://example.com"


def test_web_fetch_status_code_alias():
    out = ts.summarise("web_fetch", {"status_code": 404})
    assert out == "404"


def test_web_fetch_truncates_long_url():
    out = ts.summarise("web_fetch", {
        "url": "https://example.com/" + "x" * 100,
    })
    assert "…" in out


def test_web_search_with_results_and_query():
    out = ts.summarise("web_search", {
        "results": [{"title": "a"}, {"title": "b"}],
        "query": "vue 3 component library",
    })
    assert out == "2 results · 'vue 3 component library'"


def test_web_search_empty_results():
    out = ts.summarise("web_search", {"results": [], "query": "nothing"})
    assert out == "0 results · 'nothing'"


def test_web_search_no_query():
    out = ts.summarise("web_search", {"results": [{}, {}, {}]})
    assert out == "3 results"


def test_web_head_summary():
    out = ts.summarise("web_head", {"status": 301, "url": "https://x.com"})
    assert out == "301 · https://x.com"


def test_verify_url_ok():
    out = ts.summarise("verify_url", {"ok": True, "url": "https://x.com"})
    assert out == "verified · https://x.com"


def test_verify_url_failure_returns_none():
    assert ts.summarise("verify_url", {"ok": False}) is None


# ── Browser tools ────────────────────────────────────────────────────


def test_browser_screenshot_with_dimensions():
    out = ts.summarise("browser_screenshot", {"width": 1280, "height": 720})
    assert out == "screenshot · 1280×720"


def test_browser_screenshot_no_dimensions_returns_none():
    assert ts.summarise("browser_screenshot", {"image": "..."}) is None


def test_browser_navigate_with_url():
    out = ts.summarise("browser_navigate", {"url": "https://github.com"})
    assert out == "navigated · https://github.com"


def test_browser_get_text_chars_and_title():
    out = ts.summarise("browser_get_text", {
        "char_count": 5000, "title": "Page Title",
    })
    assert out == "5000 chars · Page Title"


def test_browser_get_text_chars_only():
    out = ts.summarise("browser_get_text", {"char_count": 100})
    assert out == "100 chars"


def test_browser_get_dom_with_char_count():
    out = ts.summarise("browser_get_dom", {"char_count": 12000})
    assert out == "12000B HTML"


def test_browser_get_dom_falls_back_to_html_length():
    out = ts.summarise("browser_get_dom", {"html": "<html>x</html>"})
    assert out == "14B HTML"


def test_browser_click_summary():
    out = ts.summarise("browser_click", {"ok": True, "selector": "button.go"})
    assert out == "clicked · button.go"


def test_browser_fill_input_summary():
    out = ts.summarise("browser_fill_input", {
        "filled": True, "selector": "input#search",
    })
    assert out == "filled · input#search"


def test_browser_get_page_var_keys_preview():
    out = ts.summarise("browser_get_page_var", {
        "var_path": "ytInitialData",
        "keys_preview": ["header", "contents", "footer"],
    })
    assert out == "ytInitialData → keys: header, contents, footer…"


def test_browser_get_page_var_with_bytes():
    out = ts.summarise("browser_get_page_var", {
        "var_path": "x", "bytes": 4096,
    })
    assert out == "x · 4096B"


def test_browser_watch_returns_watch_id():
    out = ts.summarise("browser_watch_element", {
        "watch_id": "abc-123", "selector": ".price",
    })
    assert out == "watching · .price"


# ── Plan tools ───────────────────────────────────────────────────────


def test_plan_set_singular():
    assert ts.summarise("plan_set", {"count": 1}) == "plan set · 1 task"


def test_plan_set_plural():
    assert ts.summarise("plan_set", {"count": 5}) == "plan set · 5 tasks"


def test_plan_update_progress():
    out = ts.summarise("plan_update", {
        "plan": {"tasks": [
            {"id": "t1", "status": "done"},
            {"id": "t2", "status": "in_progress"},
            {"id": "t3", "status": "done"},
        ]},
    })
    assert out == "plan updated · 2/3 done"


def test_plan_update_empty_plan():
    """No plan/tasks → 0/0 done is the honest answer."""
    out = ts.summarise("plan_update", {})
    assert out == "plan updated · 0/0 done"


def test_plan_add_count():
    assert ts.summarise("plan_add", {"added": ["t1", "t2"]}) == "+2 tasks"


def test_plan_add_singular():
    assert ts.summarise("plan_add", {"added": ["t1"]}) == "+1 task"


def test_plan_remove_count():
    assert ts.summarise("plan_remove", {"removed": ["t1", "t2", "t3"]}) == "-3 tasks"


def test_plan_archive_archived():
    assert ts.summarise("plan_archive", {"archived": True}) == "plan archived"


def test_plan_archive_no_active_returns_note():
    assert ts.summarise("plan_archive", {"archived": False, "note": "no plan"}) == "no plan"


def test_plan_history_count():
    assert ts.summarise("plan_history", {"count": 4}) == "4 archived plans"


# ── Memory tools ─────────────────────────────────────────────────────


def test_memory_persist_with_name_and_text():
    out = ts.summarise("memory_persist", {
        "name": "user_role", "text": "data scientist",
    })
    assert out == "remembered · user_role → 'data scientist'"


def test_memory_persist_name_only():
    out = ts.summarise("memory_persist", {"name": "user_role", "saved": True})
    assert out == "remembered · user_role"


def test_memory_persist_saved_only():
    """No name + no body but saved=True → still confirms."""
    assert ts.summarise("memory_persist", {"saved": True}) == "remembered"


def test_memory_recall_count():
    out = ts.summarise("memory_recall", {"memories": [{}, {}, {}]})
    assert out == "recalled 3 memories"


def test_memory_recall_singular():
    out = ts.summarise("memory_recall", {"memories": [{}]})
    assert out == "recalled 1 memory"


def test_memory_recall_zero():
    assert ts.summarise("memory_recall", {"memories": []}) == "recalled 0 memories"


def test_memory_forget_summary():
    assert ts.summarise("memory_forget", {"forgotten": True}) == "forgot memory"


# ── Git tools ────────────────────────────────────────────────────────


def test_git_status_with_changes():
    out = ts.summarise("git_status", {
        "branch": "main", "dirty": ["a.py", "b.py"],
    })
    assert out == "branch main · 2 changes"


def test_git_status_clean():
    out = ts.summarise("git_status", {"branch": "main", "dirty": []})
    assert out == "branch main · 0 changes"


def test_git_log_summary():
    out = ts.summarise("git_log", {"commits": [{}, {}]})
    assert out == "2 commits"


def test_git_log_singular():
    assert ts.summarise("git_log", {"commits": [{}]}) == "1 commit"


def test_git_commit_truncates_sha():
    out = ts.summarise("git_commit", {"sha": "abc1234567890"})
    assert out == "committed abc1234"


def test_git_commit_hash_alias():
    out = ts.summarise("git_commit", {"hash": "deadbeefcafe"})
    assert out == "committed deadbee"


def test_git_diff_files_count():
    out = ts.summarise("git_diff", {"files_changed": 3})
    assert out == "diff · 3 files"


def test_git_push_summary():
    out = ts.summarise("git_push", {
        "pushed": True, "remote": "origin", "branch": "main",
    })
    assert out == "pushed · origin/main"


# ── Spotify ──────────────────────────────────────────────────────────


def test_spotify_search_with_tracks():
    out = ts.summarise("spotify_search", {
        "tracks": {"items": [{"name": "a"}, {"name": "b"}]},
    })
    assert out == "2 tracks"


def test_spotify_search_empty_returns_none():
    """No tracks → fall through (caller may want JSON dump for debug)."""
    assert ts.summarise("spotify_search", {"tracks": {"items": []}}) is None


def test_spotify_play_ok():
    assert ts.summarise("spotify_play", {"ok": True}) == "▶ playing"


# ── LLM meta ─────────────────────────────────────────────────────────


def test_llm_summarise_with_summary():
    out = ts.summarise("llm_summarise", {"summary": "the gist of it"})
    assert out == "summary · 'the gist of it'"


def test_llm_summarise_text_alias():
    out = ts.summarise("llm_summarise", {"text": "alt field name"})
    assert out == "summary · 'alt field name'"


def test_llm_transform_lists_keys():
    out = ts.summarise("llm_transform", {
        "title": "x", "score": 0.9, "tags": [], "extra": "z",
    })
    assert "transformed · keys: " in out
    # Order is dict-insertion which Python preserves; all four keys.
    for k in ("title", "score", "tags", "extra"):
        assert k in out


# ── Other tools ──────────────────────────────────────────────────────


def test_python_run_with_output():
    out = ts.summarise("python_run", {
        "exit_code": 0, "stdout": "Hello, world!",
    })
    assert out == "exit 0 · Hello, world!"


def test_live_server_summary():
    out = ts.summarise("live_server", {"port": 5500, "pid": 99})
    assert out == "localhost:5500 · pid 99"


def test_scaffold_web_app_count():
    out = ts.summarise("scaffold_web_app", {
        "files_created": ["index.html", "main.js", "styles.css"],
    })
    assert out == "scaffolded · 3 files"


def test_scaffold_web_app_files_alias():
    out = ts.summarise("scaffold_web_app", {"files": ["a.txt"]})
    assert out == "scaffolded · 1 file"


# ── Registry completeness ────────────────────────────────────────────


def test_registry_has_no_duplicate_keys():
    """Catch typos in the registry — every key must be unique."""
    keys = list(ts._FORMATTERS.keys())
    assert len(keys) == len(set(keys))


def test_every_registered_formatter_handles_empty_dict():
    """Every formatter must gracefully handle an empty dict — never raise."""
    for tool in ts._FORMATTERS:
        try:
            result = ts.summarise(tool, {})
        except Exception as exc:
            pytest.fail(f"{tool} formatter raised on empty dict: {exc}")
        # None is fine, string is fine, anything else is a bug
        assert result is None or isinstance(result, str), (
            f"{tool} returned non-string non-None: {result!r}"
        )


def test_every_registered_formatter_handles_none_input():
    """Defensive — None input should never raise."""
    for tool in ts._FORMATTERS:
        result = ts.summarise(tool, None)
        assert result is None
