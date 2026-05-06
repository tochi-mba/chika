"""Tests for ``api/audit_log.py``."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from api import audit_log
from api.audit_log import (
    AuditLog,
    AuditRecord,
    record_approval,
    record_grant_expired,
    record_permission_change,
    record_tool_run,
)


# ── Basic append + read ──────────────────────────────────────────────


def test_append_and_read(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(AuditRecord(kind="approval", tool="shell_exec",
                            category="shell", decision="approve"))
    rows = log.read_all()
    assert len(rows) == 1
    assert rows[0]["kind"] == "approval"
    assert rows[0]["tool"] == "shell_exec"
    assert rows[0]["decision"] == "approve"
    assert "ts" in rows[0]


def test_read_all_empty_file_returns_empty_list(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    assert log.read_all() == []


def test_read_all_creates_dir_on_append(tmp_path):
    nested = tmp_path / "deep" / "nested" / "audit.jsonl"
    log = AuditLog(nested)
    log.append(AuditRecord(kind="approval", tool="shell_exec"))
    assert nested.is_file()


def test_read_all_skips_malformed_lines(tmp_path):
    p = tmp_path / "audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"kind": "approval", "tool": "x", "ts": "now"}\n'
        '{ broken\n'
        '{"kind": "tool_run", "tool": "y", "ts": "now"}\n',
        encoding="utf-8",
    )
    log = AuditLog(p)
    rows = log.read_all()
    assert len(rows) == 2
    assert rows[0]["tool"] == "x"
    assert rows[1]["tool"] == "y"


def test_record_drops_none_fields(tmp_path):
    """Compact serialisation: None-valued fields aren't emitted."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(AuditRecord(kind="approval", tool="shell_exec"))
    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    payload = json.loads(raw.strip())
    assert "category" not in payload
    assert "decision" not in payload


# ── Tail ─────────────────────────────────────────────────────────────


def test_tail_returns_last_n(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(5):
        log.append(AuditRecord(kind="tool_run", tool=f"tool_{i}"))
    out = log.tail(3)
    assert len(out) == 3
    assert [r["tool"] for r in out] == ["tool_2", "tool_3", "tool_4"]


def test_tail_zero_returns_all(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        log.append(AuditRecord(kind="tool_run", tool=f"t_{i}"))
    out = log.tail(0)
    assert len(out) == 3


# ── Concurrent append safety ─────────────────────────────────────────


def test_concurrent_appends_no_corruption(tmp_path):
    """Two threads writing simultaneously — every line must be valid JSON.
    The lock prevents interleaved writes."""
    log = AuditLog(tmp_path / "audit.jsonl")

    def writer(prefix: str, count: int) -> None:
        for i in range(count):
            log.append(AuditRecord(kind="tool_run", tool=f"{prefix}_{i}"))

    threads = [
        threading.Thread(target=writer, args=("a", 50)),
        threading.Thread(target=writer, args=("b", 50)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = log.read_all()
    assert len(rows) == 100
    # Every record must be parseable (lock prevented interleaved bytes).
    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    for line in raw.splitlines():
        json.loads(line)


# ── Rotation ─────────────────────────────────────────────────────────


def test_rotate_at_threshold(tmp_path, monkeypatch):
    """When the log hits the threshold, it gets renamed and a fresh
    log starts."""
    monkeypatch.setattr(audit_log, "_ROTATE_AT_BYTES", 200)
    log = AuditLog(tmp_path / "audit.jsonl")

    # Each record is roughly ~70 bytes; write enough to cross 200.
    for i in range(10):
        log.append(AuditRecord(kind="tool_run", tool=f"t_{i}"))

    # At least one rotation happened.
    rotated_files = list(tmp_path.glob("audit.jsonl.*"))
    assert len(rotated_files) >= 1


def test_rotate_failure_does_not_block_write(tmp_path, monkeypatch):
    """Best-effort rotation: even if the rename fails, the next append
    still writes (over-cap log, but no dropped records)."""
    monkeypatch.setattr(audit_log, "_ROTATE_AT_BYTES", 50)

    def boom(*a, **k):
        raise OSError("rotation fails on this hypothetical filesystem")
    monkeypatch.setattr(audit_log.os, "replace", boom)

    log = AuditLog(tmp_path / "audit.jsonl")
    # Fill to threshold
    for i in range(20):
        log.append(AuditRecord(kind="tool_run", tool=f"t_{i}"))
    # All records still in main file
    rows = log.read_all()
    assert len(rows) == 20


# ── Helper functions ─────────────────────────────────────────────────


def test_record_approval(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    record_approval(
        tool="shell_exec", category="shell",
        decision="deny", reason="user clicked deny",
        session_id="sess-1", log_obj=log,
    )
    rows = log.read_all()
    assert rows[0]["kind"] == "approval"
    assert rows[0]["decision"] == "deny"
    assert rows[0]["reason"] == "user clicked deny"


def test_record_permission_change_with_ttl(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    record_permission_change(
        category="shell", decision="skip", ttl_minutes=15,
        reason="JIT grant via /permissions", log_obj=log,
    )
    rows = log.read_all()
    assert rows[0]["kind"] == "permission_change"
    assert rows[0]["ttl_minutes"] == 15


def test_record_tool_run_records_ok_and_error(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    record_tool_run(tool="x", category=None, success=True, log_obj=log)
    record_tool_run(tool="y", category=None, success=False, log_obj=log)
    rows = log.read_all()
    assert rows[0]["decision"] == "ok"
    assert rows[1]["decision"] == "error"


def test_record_grant_expired(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    record_grant_expired(category="shell", log_obj=log)
    rows = log.read_all()
    assert rows[0]["kind"] == "grant_expired"
    assert rows[0]["category"] == "shell"
    assert rows[0]["actor"] == "system"


# ── Path resolution ──────────────────────────────────────────────────


def test_default_path_under_data():
    """Smoke check on the default path constant."""
    assert audit_log.DEFAULT_PATH == Path("data") / "audit.jsonl"


def test_audit_log_returns_path():
    log = AuditLog(Path("/tmp/x.jsonl"))
    assert log.path == Path("/tmp/x.jsonl")
