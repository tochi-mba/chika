from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

MAX_MEMORY_TOKENS = 2000


class MemoryEntry:
    def __init__(self, key: str, value: str, ttl_days: int | None = None) -> None:
        self.key = key
        self.value = value
        self.created = datetime.now(UTC).isoformat()
        self.accessed = 0
        self.ttl_days = ttl_days


class MemoryManager:
    def __init__(self, path: str = "memory.md", max_tokens: int = MAX_MEMORY_TOKENS) -> None:
        self._path = Path(path)
        self._max_tokens = max_tokens
        self._entries: dict[str, MemoryEntry] = {}
        self._load()

    # ── Public API ───────────────────────────────────────────────────────────

    def persist(self, key: str, value: str, ttl_days: int | None = None) -> None:
        # Sanitize key: strip chars that break the markdown heading format
        key = key.replace("#", "").replace("\n", " ").replace("\r", "").strip()
        if not key:
            import hashlib
            key = f"unnamed_{hashlib.md5(value.encode()).hexdigest()[:6]}"  # nosec B324 — not cryptographic
        entry = MemoryEntry(key, value, ttl_days)
        self._entries[key] = entry
        self._maybe_compact()
        self._save()

    def append(self, key: str, value: str, ttl_days: int | None = None) -> None:
        if key in self._entries:
            self._entries[key].value = self._entries[key].value.rstrip() + "\n" + value
            self._entries[key].ttl_days = ttl_days
        else:
            self.persist(key, value, ttl_days)
        self._maybe_compact()
        self._save()

    def forget(self, key: str) -> None:
        self._entries.pop(key, None)
        self._save()

    def seed(self, key: str, value: str) -> None:
        """Only sets if key doesn't already exist."""
        if key not in self._entries:
            self.persist(key, value)

    def read(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry:
            entry.accessed += 1
            return entry.value
        return None

    def list_keys(self) -> list[str]:
        return list(self._entries.keys())

    def all_entries(self) -> list[dict]:
        return [
            {
                "key": e.key,
                "value": e.value,
                "created": e.created,
                "accessed": e.accessed,
                "ttl_days": e.ttl_days,
            }
            for e in self._entries.values()
        ]

    def render_for_prompt(self) -> str:
        if not self._entries:
            return ""
        lines = ["## Memory\n"]
        for entry in self._entries.values():
            lines.append(f"**{entry.key}**: {entry.value}\n")
        return "\n".join(lines)

    # ── Internals ────────────────────────────────────────────────────────────

    def _estimate_tokens(self) -> int:
        return len(self.render_for_prompt()) // 4

    def _maybe_compact(self) -> None:
        if self._estimate_tokens() <= self._max_tokens:
            return
        now = datetime.now(UTC)

        # Drop expired first
        expired = [
            k for k, e in self._entries.items()
            if e.ttl_days and (now - datetime.fromisoformat(e.created)).total_seconds() / 86400 > e.ttl_days
        ]
        for k in expired:
            del self._entries[k]

        # Then drop least-accessed until under threshold
        if self._estimate_tokens() > self._max_tokens:
            by_access = sorted(self._entries.items(), key=lambda x: x[1].accessed)
            while self._estimate_tokens() > self._max_tokens and by_access:
                key, _ = by_access.pop(0)
                del self._entries[key]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["<!-- chika:memory -->\n"]
        for entry in self._entries.values():
            meta = json.dumps({
                "created": entry.created,
                "accessed": entry.accessed,
                "ttl_days": entry.ttl_days,
            })
            lines.append(f"## {entry.key}\n<!-- meta: {meta} -->\n{entry.value}\n\n")
        self._path.write_text("".join(lines), encoding="utf-8")

    def _load(self) -> None:
        if not self._path.exists():
            return
        text = self._path.read_text(encoding="utf-8")
        blocks = re.findall(
            r"## (.+?)\n<!-- meta: (.+?) -->\n(.*?)(?=\n## |\Z)",
            text,
            re.DOTALL,
        )
        for key, meta_str, value in blocks:
            try:
                meta = json.loads(meta_str)
            except json.JSONDecodeError:
                continue
            entry = MemoryEntry(key.strip(), value.strip(), meta.get("ttl_days"))
            entry.created = meta.get("created", entry.created)
            entry.accessed = meta.get("accessed", 0)
            self._entries[key.strip()] = entry
