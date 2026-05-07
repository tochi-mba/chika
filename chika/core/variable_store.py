from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Matches:
#   $var
#   $var.field        $var.field.sub
#   $var[0]           $var.field[0]
#   $var[*]           $var.tracks[*].uri    (list projection)
#
# ``[*]`` is the projection operator: walk the list at that point
# and pull the same sub-path from every item. Used for shapes like
# ``$top_tracks.tracks[*].uri`` → ``["spotify:track:a", "...:b"]``.
# Without it, agents had to hand-write each list index, which fails
# the moment the result shape changes between turns.
_VAR_RE = re.compile(
    r"\$([a-zA-Z_][a-zA-Z0-9_]*(?:(?:\.[a-zA-Z_][a-zA-Z0-9_]*)|\[\d+\]|\[\*\])*)"
)


class VarType(StrEnum):
    TEXT      = "text"
    JSON      = "json"
    BYTES     = "bytes"
    FILE_PATH = "file_path"


@dataclass
class Variable:
    name: str
    type: VarType
    value: Any
    description: str = ""
    size_bytes: int = 0
    # Provenance: which tool produced this value, in which workflow step.
    # None means the value was seeded by the engine / user, not a tool call.
    source: str | None = None


class VariableStore:
    def __init__(self) -> None:
        self._vars: dict[str, Variable] = {}

    def set(
        self,
        name: str,
        value: Any,
        var_type: VarType = VarType.TEXT,
        description: str = "",
        source: str | None = None,
    ) -> Variable:
        if isinstance(value, (str, bytes)):
            size = len(value)
        else:
            size = len(str(value))
        var = Variable(
            name=name,
            type=var_type,
            value=value,
            description=description,
            size_bytes=size,
            source=source,
        )
        self._vars[name] = var
        return var

    def set_file(self, name: str, path: str, content: bytes, description: str = "") -> Variable:
        payload = {
            "path": path,
            "content": base64.b64encode(content).decode(),
            "size": len(content),
        }
        return self.set(name, payload, VarType.BYTES, description)

    def get(self, name: str) -> Variable | None:
        return self._vars.get(name)

    def get_value(self, name: str) -> Any:
        var = self._vars.get(name)
        if var is None:
            raise KeyError(f"Variable '{name}' not found")
        if var.type == VarType.BYTES and isinstance(var.value, dict) and "content" in var.value:
            return base64.b64decode(var.value["content"])
        return var.value

    def delete(self, name: str) -> None:
        self._vars.pop(name, None)

    def clear(self) -> None:
        self._vars.clear()

    def all(self) -> dict[str, Variable]:
        return dict(self._vars)

    def list_summary(self) -> list[dict]:
        """
        Summary rendered into the system prompt. Short scalar values
        (text under ~200 chars) are inlined so the model doesn't burn a
        tool call just to learn that `$profile.workspace` resolves to
        `C:/.../workspace`. Large values still show only metadata.
        """
        out: list[dict] = []
        for k, v in self._vars.items():
            entry = {
                "name": k,
                "type": v.type.value,
                "size_bytes": v.size_bytes,
                "description": v.description,
                "source": v.source,
            }
            if v.type.value in ("text", "file_path") and isinstance(v.value, str) and len(v.value) <= 200:
                entry["value"] = v.value
            elif v.type.value == "json" and v.size_bytes <= 200:
                entry["value"] = v.value
            out.append(entry)
        return out

    # ── $ref resolution ──────────────────────────────────────────────────────

    def resolve(self, value: Any, _depth: int = 0) -> Any:
        """
        Recursively resolve $variable references in any value.

        "$status"        → variable value
        "$test_run.exit_code" → variable["exit_code"] (dict) or .exit_code (obj)
        "$items[2]"      → variable[2] (list index)
        Non-string or non-$ values pass through unchanged.

        _depth guards against circular references ($a → $b → $a); bails out
        after 20 levels rather than stack-overflowing.
        """
        if _depth > 20:
            return value  # circular ref or pathologically deep nesting — return as-is
        if isinstance(value, str):
            return self._resolve_str(value)
        elif isinstance(value, dict):
            return {k: self.resolve(v, _depth + 1) for k, v in value.items()}
        elif isinstance(value, list):
            return [self.resolve(item, _depth + 1) for item in value]
        return value

    def _resolve_str(self, s: str) -> Any:
        # Whole-value reference → return actual Python type (dict, list, int, …)
        if _VAR_RE.fullmatch(s):
            return self._lookup_ref(s[1:])

        # No $ present → pass through unchanged
        if "$" not in s:
            return s

        # Substring interpolation: replace every $ref embedded inside a larger string.
        # Result is always a string (we're building a larger string around the values).
        def replacer(m: re.Match) -> str:
            val = self._lookup_ref(m.group(1))
            if isinstance(val, str):
                return val   # resolved string, or unresolved "$ref" returned by _lookup_ref
            return str(val)  # int, bool, list, dict → str representation

        return _VAR_RE.sub(replacer, s)

    def _lookup_ref(self, ref: str) -> Any:
        """
        Resolve 'name.field[0]' (no leading $) from the store.
        Returns the resolved value, or the original '$ref' string if not found.

        Supports a ``[*]`` projection operator: ``items[*].uri``
        walks the list and pulls ``.uri`` from every entry, returning
        a fresh list. Projections compose with deeper paths — e.g.
        ``data.users[*].profile.email`` returns a flat list of
        emails (skipping items that don't have the deeper path).
        """
        # Tokenize: split on dots BUT preserve ``[*]`` and ``[N]``
        # markers so we can branch the walker on them.
        # Replace ``[N]`` → ``.N`` and ``[*]`` → ``.<*>`` (sentinel).
        tokenised = ref.replace("[*]", ".<*>").replace("[", ".").replace("]", "")
        parts = [p for p in tokenised.split(".") if p]

        # Find the variable name — try progressively longer dotted
        # prefixes (so ``profile.workspace`` resolves before falling
        # back to ``profile``).
        var = None
        prefix_len = len(parts)
        while prefix_len > 0:
            candidate = ".".join(parts[:prefix_len])
            if candidate in self._vars:
                var = self._vars[candidate]
                parts = parts[prefix_len:]
                break
            prefix_len -= 1
        if var is None:
            return f"${ref}"  # unresolved — preserve original

        return self._walk_path(var.value, parts, ref)

    def _walk_path(self, current: Any, parts: list[str], ref_for_error: str) -> Any:
        """Walk ``current`` along ``parts``. Branches on ``<*>``
        projection — when encountered, the rest of the path is
        applied to every list element and the results collected."""
        for i, part in enumerate(parts):
            if not part:
                continue
            if part == "<*>":
                # Projection — apply remaining path to every item.
                if not isinstance(current, list):
                    return f"${ref_for_error}"
                rest = parts[i + 1:]
                projected: list = []
                for item in current:
                    sub = self._walk_path(item, rest, ref_for_error)
                    # Skip items where the sub-path didn't resolve
                    # (preserves the "best-effort projection" shape).
                    if isinstance(sub, str) and sub.startswith("$"):
                        continue
                    projected.append(sub)
                return projected
            try:
                if isinstance(current, dict):
                    current = current[part]
                elif isinstance(current, list):
                    current = current[int(part)]
                elif hasattr(current, part):
                    current = getattr(current, part)
                else:
                    return f"${ref_for_error}"
            except (KeyError, IndexError, ValueError):
                return f"${ref_for_error}"
        return current
