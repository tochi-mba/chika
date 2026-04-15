"""
Chika structured logger.

Writes JSON-lines to chika.log in the repo root. Each line is a self-contained
JSON object with a timestamp, level, event name, and context fields.

Usage:
    from chika.core.logger import log
    log.info("tool_call", tool="file_replace", profile="rex", step="step_1")
    log.error("tool_error", tool="file_replace", error="old_string not found")
    log.exc("unhandled_exception", profile="rex")   # captures current traceback
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import traceback as tb
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
LOG_PATH = _REPO_ROOT / "chika.log"

_MAX_BYTES    = 4 * 1024 * 1024   # 4 MB per file
_BACKUP_COUNT = 3                  # chika.log, chika.log.1, chika.log.2, chika.log.3
_TRUNC        = 600                # truncate long string values after this many chars

# Fields we never truncate — diagnostic fields are useless when chopped.
_NEVER_TRUNCATE = frozenset({"traceback", "stacktrace", "error_trace"})


def _truncate(v: Any, key: str | None = None) -> Any:
    """Shorten long strings so the log stays readable."""
    if key in _NEVER_TRUNCATE:
        return v
    if isinstance(v, str) and len(v) > _TRUNC:
        return v[:_TRUNC] + f"…(+{len(v) - _TRUNC} chars)"
    if isinstance(v, dict):
        return {k: _truncate(val, key=k) for k, val in v.items()}
    if isinstance(v, list):
        truncated = [_truncate(i) for i in v[:10]]
        if len(v) > 10:
            truncated.append(f"…(+{len(v) - 10} more items)")
        return truncated
    return v


class _ChikaLogger:
    def __init__(self) -> None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_PATH,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger = logging.getLogger("chika.structured")
        self._logger.setLevel(logging.DEBUG)
        if not self._logger.handlers:
            self._logger.addHandler(handler)
        self._logger.propagate = False

    def _write(self, level: str, event: str, **fields: Any) -> None:
        record: dict[str, Any] = {
            "ts":    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "level": level,
            "event": event,
        }
        record.update(_truncate(fields))
        try:
            self._logger.info(json.dumps(record, default=str, ensure_ascii=False))
        except Exception:
            pass  # logging must never crash the app

    def info(self, event: str, **fields: Any) -> None:
        self._write("INFO", event, **fields)

    def warn(self, event: str, **fields: Any) -> None:
        self._write("WARN", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._write("ERROR", event, **fields)

    def exc(self, event: str, **fields: Any) -> None:
        """Log current exception with full traceback."""
        self._write("ERROR", event, traceback=tb.format_exc(), **fields)


# ── Singleton ─────────────────────────────────────────────────────────────────
log = _ChikaLogger()
