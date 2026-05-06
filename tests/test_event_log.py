"""Tests for ``api/event_log.py`` + ``chika/_cli/replay.py``."""
from __future__ import annotations

import io
import json

import pytest

from api import event_log
from api.event_log import EventLog, list_sessions, load_events, replay


# ── EventLog basics ──────────────────────────────────────────────────


def test_emit_and_read_round_trip(tmp_path):
    log = EventLog("sess-1", root=tmp_path)
    log.emit({"type": "token", "text": "hello"})
    log.emit({"type": "done"})
    events = log.read_all()
    assert len(events) == 2
    assert events[0]["type"] == "token"
    assert events[0]["text"] == "hello"
    assert events[0]["session_id"] == "sess-1"
    assert "ts" in events[0]
    assert events[1]["type"] == "done"


def test_emit_creates_dir(tmp_path):
    log = EventLog("sess-1", root=tmp_path / "deep" / "nested")
    log.emit({"type": "token"})
    assert (tmp_path / "deep" / "nested" / "sess-1.jsonl").is_file()


def test_emit_non_dict_silently_dropped(tmp_path):
    log = EventLog("sess-1", root=tmp_path)
    log.emit("not a dict")  # type: ignore[arg-type]
    log.emit(["also not"])  # type: ignore[arg-type]
    log.emit({"type": "token"})
    events = log.read_all()
    assert len(events) == 1


def test_session_id_sanitisation(tmp_path):
    """Path-traversal-style ids are stripped."""
    log = EventLog("../../../etc/passwd", root=tmp_path)
    log.emit({"type": "token"})
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    # "../../../etc/passwd" sanitised to "etcpasswd" (alnum + - + _ only)
    assert "etcpasswd" in files[0].name


def test_empty_session_id_falls_back_to_unknown(tmp_path):
    log = EventLog("", root=tmp_path)
    assert log.session_id == "unknown"


def test_existing_ts_preserved(tmp_path):
    """If the engine already stamped ts, don't overwrite it."""
    log = EventLog("s", root=tmp_path)
    log.emit({"type": "token", "ts": "2026-01-01T00:00:00Z"})
    events = log.read_all()
    assert events[0]["ts"] == "2026-01-01T00:00:00Z"


def test_read_all_skips_malformed_lines(tmp_path):
    log = EventLog("sess-1", root=tmp_path)
    log.path.parent.mkdir(parents=True, exist_ok=True)
    log.path.write_text(
        '{"type": "a", "session_id": "sess-1"}\n'
        '{ broken\n'
        '{"type": "b", "session_id": "sess-1"}\n',
        encoding="utf-8",
    )
    events = log.read_all()
    assert [e["type"] for e in events] == ["a", "b"]


def test_read_all_missing_file_returns_empty(tmp_path):
    log = EventLog("nonexistent", root=tmp_path)
    assert log.read_all() == []


def test_path_property(tmp_path):
    log = EventLog("abc", root=tmp_path)
    assert log.path == tmp_path / "abc.jsonl"


# ── Rotation ─────────────────────────────────────────────────────────


def test_rotation_at_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(event_log, "_ROTATE_AT_BYTES", 200)
    log = EventLog("s", root=tmp_path)
    for i in range(20):
        log.emit({"type": "token", "text": f"x{i}" * 5})
    # Rotated file present alongside active log
    rotated = list(tmp_path.glob("s.jsonl.*"))
    assert len(rotated) >= 1


def test_rotation_failure_does_not_block_emit(tmp_path, monkeypatch):
    monkeypatch.setattr(event_log, "_ROTATE_AT_BYTES", 50)

    def boom(*a, **k):
        raise OSError("rotation broken")
    monkeypatch.setattr(event_log.os, "replace", boom)

    log = EventLog("s", root=tmp_path)
    for i in range(20):
        log.emit({"type": "token", "text": "x" * 5})
    # All 20 still present
    assert len(log.read_all()) == 20


# ── list_sessions / load_events ──────────────────────────────────────


def test_list_sessions_empty(tmp_path):
    assert list_sessions(tmp_path) == []


def test_list_sessions_returns_ids(tmp_path):
    EventLog("a", root=tmp_path).emit({"type": "token"})
    EventLog("b", root=tmp_path).emit({"type": "token"})
    sessions = list_sessions(tmp_path)
    assert sessions == ["a", "b"]


def test_load_events_for_session(tmp_path):
    EventLog("s", root=tmp_path).emit({"type": "token", "text": "hi"})
    events = load_events("s", tmp_path)
    assert events[0]["text"] == "hi"


def test_load_events_missing_session(tmp_path):
    assert load_events("nope", tmp_path) == []


# ── replay() ─────────────────────────────────────────────────────────


def test_replay_dispatches_in_order():
    received: list[dict] = []
    events = [
        {"type": "token", "text": "hello"},
        {"type": "tool_call", "step_id": "s1", "tool": "x", "args": {}},
        {"type": "done"},
    ]
    n = replay(events, received.append)
    assert n == 3
    assert [e["type"] for e in received] == ["token", "tool_call", "done"]


def test_replay_skips_internal_events_by_default():
    received: list[dict] = []
    events = [
        {"type": "_internal", "x": 1},
        {"type": "token", "text": "hi"},
    ]
    n = replay(events, received.append)
    assert n == 1
    assert received[0]["type"] == "token"


def test_replay_includes_internal_when_skip_false():
    received: list[dict] = []
    events = [
        {"type": "_internal"},
        {"type": "token"},
    ]
    n = replay(events, received.append, skip_internal=False)
    assert n == 2


def test_replay_skips_non_dict():
    received: list[dict] = []
    events = ["not a dict", {"type": "token"}, 42, None]
    n = replay(events, received.append)  # type: ignore[arg-type]
    assert n == 1
    assert received[0]["type"] == "token"


def test_replay_handler_exception_does_not_stop():
    """A handler raising on one event must not break dispatch of the rest."""
    received: list[dict] = []

    def handler(e):
        if e.get("type") == "boom":
            raise ValueError("handler exploded")
        received.append(e)

    events = [
        {"type": "token"},
        {"type": "boom"},
        {"type": "done"},
    ]
    n = replay(events, handler)
    # The 'boom' event raised, so it doesn't count + isn't dispatched again
    assert n == 2
    assert [e["type"] for e in received] == ["token", "done"]


# ── chika replay CLI ────────────────────────────────────────────────


def test_replay_cli_lists_sessions(tmp_path, capsys):
    EventLog("alpha", root=tmp_path).emit({"type": "token"})
    EventLog("beta", root=tmp_path).emit({"type": "token"})

    from chika._cli import replay as replay_mod
    rc = replay_mod.main(["--list", "--root", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "beta" in out


def test_replay_cli_no_args_lists_when_empty(tmp_path, capsys):
    from chika._cli import replay as replay_mod
    rc = replay_mod.main(["--root", str(tmp_path)])
    assert rc == 0
    assert "no recorded sessions" in capsys.readouterr().out


def test_replay_cli_unknown_session_returns_one(tmp_path, capsys):
    from chika._cli import replay as replay_mod
    rc = replay_mod.main(["nonexistent", "--root", str(tmp_path)])
    assert rc == 1


def test_replay_cli_count_surface(tmp_path, capsys):
    log = EventLog("s1", root=tmp_path)
    log.emit({"type": "token"})
    log.emit({"type": "token"})
    log.emit({"type": "tool_call", "step_id": "x", "tool": "t", "args": {}})
    log.emit({"type": "done"})

    from chika._cli import replay as replay_mod
    rc = replay_mod.main(["s1", "--surface", "count", "--root", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "token" in out
    assert "total: 4" in out


def test_replay_cli_raw_surface(tmp_path, capsys):
    log = EventLog("s1", root=tmp_path)
    log.emit({"type": "token", "text": "hi"})

    from chika._cli import replay as replay_mod
    rc = replay_mod.main(["s1", "--surface", "raw", "--root", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out.strip().splitlines()[0])
    assert parsed["type"] == "token"
    assert parsed["text"] == "hi"
