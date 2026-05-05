from __future__ import annotations

import base64
from pathlib import Path

from chika.core.tool_registry import ToolDefinition

# Hard cap: refuse to read files larger than this in one shot.
# The LLM should use start_line/end_line for large files.
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def _safe_path(path: str) -> tuple[Path, str | None]:
    """
    Resolve *path* and check for traversal attempts.
    Returns (resolved_path, None) on success or (Path(path), error_message) on failure.
    """
    if ".." in Path(path).parts:
        return Path(path), f"Path traversal not allowed: {path!r}"
    return Path(path).resolve(), None


# ── Workspace-scope hook ──────────────────────────────────────────────
#
# When a ChikaEngine is wired into a session, ``api.session_manager`` injects
# a ``WorkspacePolicy`` + the matching ``approval_handler`` here so the
# write-class file tools can ask the user before touching paths outside
# the active profile's workspace. Both default to None — when unset,
# writes proceed unchecked (matching legacy behaviour and CLI without
# an attached approval channel).
#
# We use ``contextvars.ContextVar`` so concurrent FastAPI sessions don't
# stomp on each other's policies — each WS connection task gets its own
# Context, and ``configure_workspace_policy`` only mutates that task's
# view. Module-level globals would collide as soon as two clients
# attached at once.
import contextvars as _cv

_WORKSPACE_POLICY: _cv.ContextVar = _cv.ContextVar(
    "chika_workspace_policy", default=None,
)
_WORKSPACE_APPROVAL_HANDLER: _cv.ContextVar = _cv.ContextVar(
    "chika_workspace_approval_handler", default=None,
)

# Module-level shims kept for the existing test fixture / older code
# paths that read these names directly. Reading them resolves the
# context-var, writing them updates the var so the legacy interface
# still functions in single-tenant test setups.


class _PolicyShim:
    """Descriptor-ish shim so legacy ``WORKSPACE_POLICY`` reads work."""
    def __get__(self, _obj, _objtype=None):
        return _WORKSPACE_POLICY.get()
    def __set__(self, _obj, value):
        _WORKSPACE_POLICY.set(value)


# A direct attribute so reads / writes work the same way ``WORKSPACE_POLICY = ...``
# did before. The ContextVar above is the source of truth.
def __getattr__(name):  # PEP 562 module __getattr__
    if name == "WORKSPACE_POLICY":
        return _WORKSPACE_POLICY.get()
    if name == "WORKSPACE_APPROVAL_HANDLER":
        return _WORKSPACE_APPROVAL_HANDLER.get()
    raise AttributeError(f"module 'file_tools' has no attribute {name!r}")


def configure_workspace_policy(policy, approval_handler) -> None:
    """Attach a WorkspacePolicy + approval handler to the file-write tools.

    Called by api.session_manager after a per-session ChikaEngine is built
    and its WS approval channel is open. Idempotent — re-calling with
    new instances replaces the values for the calling task's Context.
    """
    _WORKSPACE_POLICY.set(policy)
    _WORKSPACE_APPROVAL_HANDLER.set(approval_handler)


async def _gate_write(path: str | Path, action: str) -> dict | None:
    """If the active workspace policy refuses ``action`` on ``path``,
    return a structured error dict. Otherwise return None to let the
    caller proceed.
    """
    policy = _WORKSPACE_POLICY.get()
    if policy is None:
        return None
    decision = await policy.check(
        path,
        action=action,
        approval_handler=_WORKSPACE_APPROVAL_HANDLER.get(),
    )
    if decision.allowed:
        return None
    return {
        "error":     "denied_by_workspace_policy",
        "scope":     decision.scope,
        "reason":    decision.reason,
        "path":      str(path),
        "workspace": getattr(policy, "workspace", None),
        "hint": (
            "The user denied this write because it falls outside the "
            "active profile's workspace. Either keep work inside the "
            "workspace, ask the user to re-approve with session scope, "
            "or pause and explain what you need."
        ),
    }


async def file_read(
    path: str,
    as_bytes: bool = False,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    """
    Read a file, optionally slicing by line range (1-indexed, inclusive).

    - start_line / end_line: return only that slice. total_lines is always the full count.
    - as_bytes: return base64-encoded binary content (ignores line range).
    """
    p, err = _safe_path(path)
    if err:
        return {"error": err}
    if not p.exists():
        return {"error": f"File not found: {path}"}
    if p.is_dir():
        return {"error": f"Path is a directory: {path}"}
    size = p.stat().st_size
    if size > MAX_FILE_SIZE_BYTES:
        return {"error": f"File too large to read in one shot ({size} bytes). Use start_line/end_line to read in sections."}
    if as_bytes:
        return {
            "path": path,
            "content": base64.b64encode(p.read_bytes()).decode(),
            "encoding": "base64",
            "size_bytes": size,
        }
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return {
            "error": "encoding_error",
            "encoding": "utf-8",
            "path": path,
            "detail": str(exc),
            "hint": "File may be binary or use a different encoding. Try as_bytes=True.",
        }
    all_lines = text.splitlines()
    total_lines = len(all_lines)

    if start_line is not None or end_line is not None:
        sl = max(1, start_line or 1)
        el = min(total_lines, end_line or total_lines)
        sliced = all_lines[sl - 1: el]
        return {
            "path": path,
            "content": "\n".join(sliced),
            "lines": sliced,
            "line_count": len(sliced),
            "total_lines": total_lines,
            "start_line": sl,
            "end_line": el,
            "size_bytes": p.stat().st_size,
        }

    return {
        "path": path,
        "content": text,
        "lines": all_lines,
        "line_count": total_lines,
        "total_lines": total_lines,
        "size_bytes": p.stat().st_size,
    }


async def file_edit_lines(path: str, start_line: int, end_line: int, new_content: str) -> dict:
    """Replace lines [start_line, end_line] (1-indexed, inclusive) with new_content."""
    p, err = _safe_path(path)
    if err:
        return {"error": err}
    if not p.exists():
        return {"error": f"File not found: {path}"}
    gate = await _gate_write(p, "edit")
    if gate is not None:
        return gate
    original = p.read_text(errors="replace")
    lines = original.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    patched = lines[: start_line - 1] + new_lines + lines[end_line:]
    p.write_text("".join(patched), encoding="utf-8")
    return {
        "path": path,
        "lines_replaced": end_line - start_line + 1,
        "new_line_count": len(new_lines),
        "total_lines": len(patched),
    }


async def file_write(path: str = "", content: str | None = None, **_extra) -> dict:
    """Write a file. Tolerates LLM kwarg-drift on the content parameter.

    Common drift patterns the LLM produces — all resolve to ``content``:
      - ``contents=`` (plural)
      - ``text=`` / ``body=`` / ``data=`` / ``source=``
      - ``file_path=`` instead of ``path=``
    """
    if not path:
        path = _extra.get("file_path") or _extra.get("filepath") or ""
    if content is None:
        for alias in ("contents", "text", "body", "data", "source"):
            v = _extra.get(alias)
            if v is not None:
                content = v
                break
    if not path:
        return {"error": "Missing required argument: path"}
    if not isinstance(content, str):
        return {"error": f"content must be a string, got {type(content).__name__} ({str(content)[:120]}). Use $variable.field to extract a specific field from a JSON result."}
    p, err = _safe_path(path)
    if err:
        return {"error": err}
    gate = await _gate_write(p, "write")
    if gate is not None:
        return gate
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"path": path, "size_bytes": p.stat().st_size}


def _suggest_anchor_lines(text: str, old_string: str, top_k: int = 3) -> list[dict]:
    """When ``file_replace`` can't find ``old_string`` verbatim, find the
    lines in ``text`` that look most like the FIRST line of the search
    string and return them with their line numbers + the surrounding
    context. The LLM uses this to course-correct without guessing.

    Heuristic: the first non-empty stripped line of ``old_string`` is
    the anchor. Lines containing it as a substring (case-sensitive) are
    surfaced first; if none match, we fall back to a fuzzy contains
    on the first 12 stripped chars so trailing whitespace differences
    don't hide an obvious match.
    """
    anchor_lines = [ln for ln in old_string.splitlines() if ln.strip()]
    if not anchor_lines:
        return []
    anchor = anchor_lines[0].strip()
    if len(anchor) < 4:
        return []  # too short to be useful as an anchor
    file_lines = text.splitlines()
    matches: list[tuple[int, int, str]] = []  # (score, line_no, text)

    short = anchor[:12]
    for i, line in enumerate(file_lines, start=1):
        if anchor in line:
            matches.append((100, i, line.rstrip()))
        elif short and short in line:
            matches.append((50, i, line.rstrip()))

    matches.sort(key=lambda x: -x[0])
    return [
        {"line_no": ln, "text": txt[:160]}
        for _score, ln, txt in matches[:top_k]
    ]


async def file_replace(path: str, old_string: str, new_string: str) -> dict:
    """Replace the first (or only) occurrence of old_string with new_string."""
    if not isinstance(old_string, str):
        return {"error": f"old_string must be a string, got {type(old_string).__name__}. Use $variable.field to extract a specific field from a JSON result."}
    if not isinstance(new_string, str):
        return {"error": f"new_string must be a string, got {type(new_string).__name__} ({str(new_string)[:120]}). Use $variable.field to extract a specific field from a JSON result."}
    p, err = _safe_path(path)
    if err:
        return {"error": err}
    if not p.exists():
        return {"error": f"File not found: {path}"}
    gate = await _gate_write(p, "replace")
    if gate is not None:
        return gate
    text = p.read_text(errors="replace")
    count = text.count(old_string)
    if count == 0:
        # Not-found errors are the #1 LLM failure mode for file_replace
        # because the model guesses at the exact string. Give it real
        # diagnostics instead of "Read the file first": the closest
        # lines we found, the exact line numbers, and an actionable
        # next step. The agent then knows where to look without
        # re-reading the whole file.
        suggestions = _suggest_anchor_lines(text, old_string)
        hint = (
            "old_string not found verbatim. Common causes: leading/trailing "
            "whitespace, smart quotes, line-ending differences, or the file "
            "has changed since the last read. "
            "Fix: `file_read` the path with the line range covering the "
            "expected location, copy the exact bytes, then retry. "
            "Or use `file_edit_lines(path, start_line, end_line, new_content)` "
            "if you already know the line range."
        )
        if suggestions:
            hint += " Closest matches found:"
        return {
            "error":            "old_string_not_found",
            "path":             path,
            "anchor":           (
                old_string.splitlines()[0][:120]
                if old_string.splitlines() else ""
            ),
            "suggestions":      suggestions,
            "total_lines":      text.count("\n") + 1,
            "hint":             hint,
        }
    if count > 1:
        # Find every occurrence's line number so the LLM can pick the
        # right one with a wider context fragment.
        line_numbers: list[int] = []
        idx = 0
        while True:
            idx = text.find(old_string, idx)
            if idx < 0:
                break
            line_numbers.append(text.count("\n", 0, idx) + 1)
            idx += 1
            if len(line_numbers) >= 12:
                break
        return {
            "error":         "old_string_not_unique",
            "path":          path,
            "occurrences":   count,
            "line_numbers":  line_numbers,
            "hint": (
                f"old_string appears {count} times in {path}. Provide more "
                "surrounding context (extra leading or trailing lines) to "
                "make the match unique, or call file_edit_lines with the "
                "specific line range you want to change."
            ),
        }
    patched = text.replace(old_string, new_string, 1)
    p.write_text(patched, encoding="utf-8")
    return {"path": path, "replaced": True, "occurrences_found": count}


async def file_append(path: str, content: str) -> dict:
    if not isinstance(content, str):
        return {"error": f"content must be a string, got {type(content).__name__} ({str(content)[:120]}). Use $variable.field to extract a specific field from a JSON result."}
    p, err = _safe_path(path)
    if err:
        return {"error": err}
    gate = await _gate_write(p, "append")
    if gate is not None:
        return gate
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(content)
    return {"path": path, "appended_bytes": len(content.encode())}


async def file_info(path: str) -> dict:
    p, err = _safe_path(path)
    if err:
        return {"error": err}
    if not p.exists():
        return {"error": f"Not found: {path}"}
    stat = p.stat()
    return {
        "path": path,
        "size_bytes": stat.st_size,
        "is_dir": p.is_dir(),
        "is_file": p.is_file(),
        "extension": p.suffix,
        "modified_ts": stat.st_mtime,
    }


FILE_TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        name="file_read",
        description=(
            "Read a file. Returns content, lines array, line_count, total_lines, size_bytes. "
            "Use start_line/end_line (1-indexed, inclusive) to read a specific section — "
            "total_lines is always the full file size so you can plan further reads."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path":       {"type": "string",  "description": "Absolute or relative file path"},
                "as_bytes":   {"type": "boolean", "description": "True = return base64-encoded bytes"},
                "start_line": {"type": "integer", "description": "First line to return (1-indexed, inclusive)"},
                "end_line":   {"type": "integer", "description": "Last line to return (1-indexed, inclusive)"},
            },
            "required": ["path"],
        },
        handler=file_read,
    ),
    ToolDefinition(
        name="file_edit_lines",
        description="Replace a line range in a file. 1-indexed, inclusive. Surgical edit — doesn't touch other lines.",
        parameters={
            "type": "object",
            "properties": {
                "path":        {"type": "string",  "description": "File path"},
                "start_line":  {"type": "integer", "description": "First line to replace (1-indexed)"},
                "end_line":    {"type": "integer", "description": "Last line to replace (inclusive)"},
                "new_content": {"type": "string",  "description": "Replacement text"},
            },
            "required": ["path", "start_line", "end_line", "new_content"],
        },
        handler=file_edit_lines,
    ),
    ToolDefinition(
        name="file_write",
        description="Write or overwrite a file entirely. Creates parent directories.",
        requires_approval=True,
        approval_message="Chika wants to write (overwrite) a file.",
        parameters={
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["path", "content"],
        },
        handler=file_write,
    ),
    ToolDefinition(
        name="file_replace",
        description=(
            "Replace an exact string in a file. PREFERRED over file_edit_lines for edits. "
            "You MUST read the file first (file_read) to copy old_string verbatim. "
            "Fails if old_string is not found or is ambiguous (add more surrounding context to make it unique)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path":       {"type": "string", "description": "File path"},
                "old_string": {"type": "string", "description": "Exact text to find and replace (must be unique in the file)"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        handler=file_replace,
    ),
    ToolDefinition(
        name="file_append",
        description="Append text to a file. Creates the file if it doesn't exist.",
        parameters={
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "Text to append"},
            },
            "required": ["path", "content"],
        },
        handler=file_append,
    ),
    ToolDefinition(
        name="file_info",
        description="Get file metadata: size, is_dir, extension, modified timestamp.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
            },
            "required": ["path"],
        },
        handler=file_info,
    ),
]
