"""Idempotency layer for browser tool calls across extension reconnects.

The audit found a real failure mode: when the extension WS drops
mid-action (network blip, browser sleep, tab close), the engine
re-issues the same tool call — but the action has already happened.
For destructive ops (form submit, click "buy now") this double-fires.

This module gives the engine a 30-second sliding window of
``(tab_id, action, args_hash) → result``. Within the window, a
re-issue returns the cached result without re-running the action.
After the window, the cache entry expires and a re-issue re-runs.

Why 30 seconds — long enough to absorb realistic reconnects (most
WS reconnects complete within 5s), short enough that the agent's
"I'll do X" → user-page-state assumption stays consistent.

Why per-tab — a click on one tab's "Submit" button is a different
action from the same click on another tab.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

_DEFAULT_TTL_S = 30.0
_CACHE_MAX = 256


@dataclass(frozen=True)
class IdempotencyKey:
    """The tuple that uniquely identifies a "same action, same args" pair."""
    tab_id: int | str
    action: str
    args_sha: str

    @classmethod
    def from_call(cls, *, tab_id: int | str, action: str, args: dict) -> IdempotencyKey:
        # Stable JSON encoding so identical-but-reordered dicts produce
        # the same hash. ``sort_keys=True`` is the canonicaliser.
        canonical = json.dumps(args, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return cls(tab_id=tab_id, action=action, args_sha=digest)


@dataclass
class _Entry:
    result: Any
    expires_at: float


class IdempotencyCache:
    """Sliding-window LRU keyed by :class:`IdempotencyKey`.

    Use as:
        cache = IdempotencyCache()
        key = IdempotencyKey.from_call(tab_id=42, action="click", args={...})
        cached = cache.get(key)
        if cached is not None:
            return cached
        result = run_action(...)
        cache.put(key, result)
    """

    def __init__(self, *, ttl_seconds: float = _DEFAULT_TTL_S, maxsize: int = _CACHE_MAX) -> None:
        self._d: OrderedDict[IdempotencyKey, _Entry] = OrderedDict()
        self._ttl = ttl_seconds
        self._max = maxsize

    def get(self, key: IdempotencyKey, *, now: float | None = None) -> Any | None:
        ts = now if now is not None else time.monotonic()
        entry = self._d.get(key)
        if entry is None:
            return None
        if entry.expires_at <= ts:
            # Expired; evict and return miss.
            del self._d[key]
            return None
        # LRU touch.
        self._d.move_to_end(key)
        return entry.result

    def put(self, key: IdempotencyKey, result: Any, *, now: float | None = None) -> None:
        ts = now if now is not None else time.monotonic()
        self._d[key] = _Entry(result=result, expires_at=ts + self._ttl)
        self._d.move_to_end(key)
        while len(self._d) > self._max:
            self._d.popitem(last=False)

    def clear(self) -> None:
        self._d.clear()

    def prune(self, *, now: float | None = None) -> int:
        """Remove expired entries. Returns count pruned."""
        ts = now if now is not None else time.monotonic()
        expired = [k for k, e in self._d.items() if e.expires_at <= ts]
        for k in expired:
            del self._d[k]
        return len(expired)

    def __len__(self) -> int:
        return len(self._d)


# Global default cache. Per-engine caches can be created if isolation
# is needed (tests do this).
DEFAULT = IdempotencyCache()
