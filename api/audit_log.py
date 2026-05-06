"""Append-only audit log of permission decisions + tool executions.

Trust UX is the moat for an agentic tool. Today we have categories +
ask/skip primitives but no observability — users can't see what was
approved when, can't grant temporarily, can't see what changed.

This module is the persistence side of the fix. It records:

  - Approval decisions (user said yes/no to a tool prompt)
  - Permission changes (category flipped from ask → skip etc.)
  - Timed grants (skip until <timestamp>)
  - Tool executions (after the fact — not per-event spam, just one
    line per tool actually run with a result kind)

Format
------
NDJSON at ``data/audit.jsonl`` — append-only, line-per-record. Easy
to ``tail -f`` in development, easy to grep in incident triage, and
NDJSON readers don't choke on a partial last line.

Schema (every record)
---------------------
- ``ts`` — ISO-8601 UTC timestamp
- ``kind`` — "approval" | "permission_change" | "tool_run" | "grant_expired"
- ``actor`` — "user" | "system"
- ``tool`` — tool name (when applicable)
- ``category`` — permission category (when applicable)
- ``decision`` — "approve" | "deny" | "skip" | "ask" (when applicable)
- ``ttl_minutes`` — for timed grants; None for permanent
- ``reason`` — free-form context (e.g. "user clicked deny in modal")
- ``session_id`` — for cross-referencing with event_log session NDJSONs

Rotation
--------
Capped at 10 MB. When the active log hits the cap, it's renamed to
``audit.jsonl.<ts>`` and a fresh log starts. Rotation is best-effort
— a failure during rotation logs but doesn't block the audit write
itself (better to have an over-cap log than to drop the record).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_PATH: Path = Path("data") / "audit.jsonl"

# Rotation threshold — 10 MB matches `.chika/update_state.json` discipline:
# tight enough to keep grep-friendly, loose enough that a chatty session
# isn't constantly rotating.
_ROTATE_AT_BYTES = 10 * 1024 * 1024


@dataclass
class AuditRecord:
    """One line of the audit log."""
    kind: str                              # "approval" | "permission_change" | "tool_run" | "grant_expired"
    actor: str = "user"                    # who/what made the decision
    tool: str | None = None
    category: str | None = None
    decision: str | None = None            # "approve" | "deny" | "skip" | "ask"
    ttl_minutes: int | None = None
    reason: str | None = None
    session_id: str | None = None
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_jsonl(self) -> str:
        """One-line JSON representation. Drops None fields for compactness."""
        d = {k: v for k, v in asdict(self).items() if v is not None}
        return json.dumps(d, separators=(",", ":")) + "\n"


class AuditLog:
    """Thread-safe append-only writer + best-effort reader.

    Why a class, not module-level functions: tests need to inject a
    custom path (tmp_path) without having to monkeypatch a global.
    Engine attaches one of these as a bus subscriber.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_PATH
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: AuditRecord) -> None:
        """Write one record. Never raises (best-effort observability)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                self._maybe_rotate()
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(record.to_jsonl())
        except OSError as exc:
            log.warning("audit log write failed: %s", exc)

    def read_all(self) -> list[dict[str, Any]]:
        """Return every record. Skips malformed lines."""
        if not self._path.is_file():
            return []
        out: list[dict[str, Any]] = []
        try:
            with self._path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as exc:
            log.warning("audit log read failed: %s", exc)
        return out

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        """Return the last ``n`` records. Used by ``/audit`` slash cmd."""
        all_records = self.read_all()
        return all_records[-n:] if n > 0 else all_records

    def _maybe_rotate(self) -> None:
        """If the log file is at or beyond the threshold, rotate it.

        Rename current → ``audit.jsonl.<ts>``, leave a fresh empty log.
        Failure is logged but non-fatal — caller will write to the
        oversized log rather than drop the record.
        """
        try:
            if not self._path.is_file():
                return
            if self._path.stat().st_size < _ROTATE_AT_BYTES:
                return
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            rotated = self._path.with_suffix(self._path.suffix + f".{ts}")
            os.replace(self._path, rotated)
        except OSError as exc:
            log.warning("audit log rotation failed: %s", exc)


# Module-level default for production use. Tests construct their own
# ``AuditLog(tmp_path / "audit.jsonl")``.
DEFAULT_LOG = AuditLog()


# ── Helpers — common record kinds ────────────────────────────────────


def record_approval(
    *,
    tool: str,
    category: str | None,
    decision: str,
    actor: str = "user",
    reason: str | None = None,
    session_id: str | None = None,
    log_obj: AuditLog | None = None,
) -> None:
    (log_obj or DEFAULT_LOG).append(AuditRecord(
        kind="approval",
        tool=tool,
        category=category,
        decision=decision,
        actor=actor,
        reason=reason,
        session_id=session_id,
    ))


def record_permission_change(
    *,
    category: str,
    decision: str,
    actor: str = "user",
    ttl_minutes: int | None = None,
    reason: str | None = None,
    log_obj: AuditLog | None = None,
) -> None:
    (log_obj or DEFAULT_LOG).append(AuditRecord(
        kind="permission_change",
        category=category,
        decision=decision,
        actor=actor,
        ttl_minutes=ttl_minutes,
        reason=reason,
    ))


def record_tool_run(
    *,
    tool: str,
    category: str | None,
    success: bool,
    session_id: str | None = None,
    log_obj: AuditLog | None = None,
) -> None:
    (log_obj or DEFAULT_LOG).append(AuditRecord(
        kind="tool_run",
        tool=tool,
        category=category,
        decision="ok" if success else "error",
        actor="system",
        session_id=session_id,
    ))


def record_grant_expired(
    *,
    category: str,
    log_obj: AuditLog | None = None,
) -> None:
    (log_obj or DEFAULT_LOG).append(AuditRecord(
        kind="grant_expired",
        category=category,
        actor="system",
    ))
