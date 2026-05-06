"""Per-session NDJSON event log + replay primitives.

Captures every WS event into ``data/sessions/<session_id>.jsonl`` so a
session can be:

  - Replayed offline against any surface (CLI / frontend / extension)
  - Diffed across surfaces to detect rendering drift
  - Used as a regression repro when a customer reports a bad turn
  - Demoed without needing the original LLM call

The reviewer specifically called out the differentiator as
**"one engine, multiple synchronized surfaces"** — this module is
the artifact that makes the differentiator concrete.

Format
------
NDJSON: one JSON object per line, each a captured event.

Schema additions on top of the engine event:
  - ``ts`` — append-time UTC ISO-8601 (set here, not by the engine)
  - ``session_id`` — for cross-referencing with audit.jsonl

Rotation
--------
Capped at 5 MB per session. When a session crosses the cap, the file
is rotated to ``<id>.jsonl.<ts>``. Replay reads the *active* file by
default; tests can pass a rotated file explicitly.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_DIR: Path = Path("data") / "sessions"

_ROTATE_AT_BYTES = 5 * 1024 * 1024


class EventLog:
    """Per-session event recorder. One instance per session_id.

    The engine attaches one of these as a bus subscriber for the
    session it owns. Logs are append-only; rotation is automatic.
    """

    def __init__(self, session_id: str, *, root: Path | None = None) -> None:
        # Sanitise session_id — no path traversal, no funky chars.
        clean = "".join(c for c in session_id if c.isalnum() or c in ("-", "_"))
        if not clean:
            clean = "unknown"
        self._session_id = clean
        self._root = root or DEFAULT_DIR
        self._lock = threading.Lock()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def path(self) -> Path:
        return self._root / f"{self._session_id}.jsonl"

    def emit(self, event: dict[str, Any]) -> None:
        """Append one event. Stamps ts + session_id, never raises."""
        if not isinstance(event, dict):
            return
        # Don't re-stamp if engine already provided ts
        ts = event.get("ts") or datetime.now(UTC).isoformat()
        record = {**event, "ts": ts, "session_id": self._session_id}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                self._maybe_rotate()
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError as exc:
            log.warning("event_log emit failed: %s", exc)

    def read_all(self) -> list[dict[str, Any]]:
        """Read every recorded event. Skips malformed lines."""
        if not self.path.is_file():
            return []
        out: list[dict[str, Any]] = []
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as exc:
            log.warning("event_log read failed: %s", exc)
        return out

    def _maybe_rotate(self) -> None:
        try:
            if not self.path.is_file():
                return
            if self.path.stat().st_size < _ROTATE_AT_BYTES:
                return
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            rotated = self.path.with_suffix(self.path.suffix + f".{ts}")
            os.replace(self.path, rotated)
        except OSError as exc:
            log.warning("event_log rotation failed: %s", exc)


# ── Replay ───────────────────────────────────────────────────────────


def list_sessions(root: Path | None = None) -> list[str]:
    """All session_ids that have a recorded event log."""
    cache_root = root or DEFAULT_DIR
    if not cache_root.is_dir():
        return []
    return sorted(p.stem for p in cache_root.glob("*.jsonl"))


def load_events(session_id: str, root: Path | None = None) -> list[dict[str, Any]]:
    """Read every event from the active log file for ``session_id``."""
    return EventLog(session_id, root=root).read_all()


def replay(
    events: Iterable[dict[str, Any]],
    handler,
    *,
    skip_internal: bool = True,
) -> int:
    """Dispatch ``events`` to ``handler`` in order.

    ``handler`` is any callable taking an event dict. The CLI's
    Renderer.handle, the frontend store's dispatch, and the extension's
    message handler all match this shape.

    ``skip_internal=True`` (default) skips events whose ``type`` starts
    with an underscore — those are engine-internal markers (cancellation,
    transcript boundaries) that surfaces don't render.

    Returns the count of events dispatched.
    """
    n = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        etype = event.get("type", "")
        if skip_internal and isinstance(etype, str) and etype.startswith("_"):
            continue
        try:
            handler(event)
        except Exception as exc:
            log.warning("replay handler raised on %r: %s", etype, exc)
            continue
        n += 1
    return n
