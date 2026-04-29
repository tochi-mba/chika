from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Matches $var, $var.field, $var.field.sub, $var[0], $var.field[0]
_VAR_RE = re.compile(
    r"\$([a-zA-Z_][a-zA-Z0-9_]*(?:(?:\.[a-zA-Z_][a-zA-Z0-9_]*)|\[\d+\])*)"
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
        """
        parts = ref.replace("[", ".").replace("]", "").split(".")
        # Try progressively longer dotted prefixes as the variable name
        # e.g. for "profile.workspace" try "profile.workspace" before "profile"
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
        result = var.value
        for part in parts:
            if not part:
                continue
            try:
                if isinstance(result, dict):
                    result = result[part]
                elif isinstance(result, list):
                    result = result[int(part)]
                elif hasattr(result, part):
                    result = getattr(result, part)
                else:
                    return f"${ref}"
            except (KeyError, IndexError, ValueError):
                return f"${ref}"
        return result
