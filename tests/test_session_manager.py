"""Tests for SessionManager — session creation, isolation, listing, deletion."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import patch, MagicMock

# Patch config before importing session_manager to avoid needing real env vars
import config
config.MAX_MEMORY_TOKENS = 1000
config.MAX_HISTORY_TOKENS = 10000
config.MAX_TOOL_TURNS = 10
config.COMPACT_KEEP_FIRST = 2
config.COMPACT_KEEP_LAST = 4
config.CHIKA_API_KEY = ""

from api.session_manager import SessionManager
from chika.core.engine import ChikaEngine


# ── Session creation ──────────────────────────────────────────────────────────

def test_get_or_create_returns_engine():
    sm = SessionManager()
    engine = sm.get_or_create("session_001")
    assert isinstance(engine, ChikaEngine)


def test_get_or_create_same_id_returns_same_engine():
    sm = SessionManager()
    e1 = sm.get_or_create("abc")
    e2 = sm.get_or_create("abc")
    assert e1 is e2


def test_different_ids_return_different_engines():
    sm = SessionManager()
    e1 = sm.get_or_create("session_a")
    e2 = sm.get_or_create("session_b")
    assert e1 is not e2


# ── get ───────────────────────────────────────────────────────────────────────

def test_get_returns_none_for_unknown():
    sm = SessionManager()
    assert sm.get("nonexistent") is None


def test_get_returns_engine_after_create():
    sm = SessionManager()
    sm.get_or_create("x")
    assert sm.get("x") is not None


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_removes_session():
    sm = SessionManager()
    sm.get_or_create("del_me")
    sm.delete("del_me")
    assert sm.get("del_me") is None


def test_delete_nonexistent_is_safe():
    sm = SessionManager()
    sm.delete("never_existed")  # should not raise


def test_delete_does_not_affect_other_sessions():
    sm = SessionManager()
    sm.get_or_create("keep_me")
    sm.get_or_create("del_me")
    sm.delete("del_me")
    assert sm.get("keep_me") is not None


# ── list_sessions ─────────────────────────────────────────────────────────────

def test_list_sessions_empty():
    sm = SessionManager()
    assert sm.list_sessions() == []


def test_list_sessions_includes_created():
    sm = SessionManager()
    sm.get_or_create("s1")
    sm.get_or_create("s2")
    sessions = sm.list_sessions()
    ids = [s["session_id"] for s in sessions]
    assert "s1" in ids
    assert "s2" in ids


def test_list_sessions_not_includes_deleted():
    sm = SessionManager()
    sm.get_or_create("stay")
    sm.get_or_create("gone")
    sm.delete("gone")
    sessions = sm.list_sessions()
    ids = [s["session_id"] for s in sessions]
    assert "stay" in ids
    assert "gone" not in ids


def test_list_sessions_includes_message_count():
    sm = SessionManager()
    sm.get_or_create("s")
    sessions = sm.list_sessions()
    assert "message_count" in sessions[0]


def test_list_sessions_includes_variable_count():
    sm = SessionManager()
    sm.get_or_create("s")
    sessions = sm.list_sessions()
    assert "variable_count" in sessions[0]


# ── Session isolation ─────────────────────────────────────────────────────────

def test_sessions_have_isolated_variable_stores():
    sm = SessionManager()
    e1 = sm.get_or_create("iso_a")
    e2 = sm.get_or_create("iso_b")
    e1._vars.set("x", "from_a")
    assert e2._vars.get("x") is None


def test_sessions_have_isolated_histories():
    sm = SessionManager()
    e1 = sm.get_or_create("hist_a")
    e2 = sm.get_or_create("hist_b")
    e1._history.append({"role": "user", "content": "hello"})
    assert len(e2._history) == 0


def test_sessions_have_isolated_memory():
    sm = SessionManager()
    e1 = sm.get_or_create("mem_a")
    e2 = sm.get_or_create("mem_b")
    e1._memory.persist("k", "v")
    assert e2._memory.read("k") is None


# ── Tool registration ─────────────────────────────────────────────────────────

def test_engine_has_shell_tool_registered():
    sm = SessionManager()
    engine = sm.get_or_create("tools_test")
    assert engine._tools.get("shell_exec") is not None


def test_engine_has_file_tools_registered():
    sm = SessionManager()
    engine = sm.get_or_create("file_tools_test")
    for name in ["file_read", "file_write", "file_append", "file_edit_lines", "file_info"]:
        assert engine._tools.get(name) is not None, f"Missing tool: {name}"


def test_engine_has_variable_tools_registered():
    sm = SessionManager()
    engine = sm.get_or_create("var_tools_test")
    for name in ["set_variable", "get_variable", "list_variables"]:
        assert engine._tools.get(name) is not None, f"Missing tool: {name}"


def test_engine_has_memory_tools_registered():
    sm = SessionManager()
    engine = sm.get_or_create("mem_tools_test")
    for name in ["memory_persist", "memory_forget", "memory_list"]:
        assert engine._tools.get(name) is not None, f"Missing tool: {name}"


def test_engine_has_git_skill_tools():
    sm = SessionManager()
    engine = sm.get_or_create("git_test")
    assert engine._tools.get("git_status") is not None


def test_engine_has_web_skill_tools():
    sm = SessionManager()
    engine = sm.get_or_create("web_test")
    assert engine._tools.get("web_search") is not None
