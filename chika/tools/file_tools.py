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


async def file_write(path: str, content: str) -> dict:
    if not isinstance(content, str):
        return {"error": f"content must be a string, got {type(content).__name__} ({str(content)[:120]}). Use $variable.field to extract a specific field from a JSON result."}
    p, err = _safe_path(path)
    if err:
        return {"error": err}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"path": path, "size_bytes": p.stat().st_size}


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
    text = p.read_text(errors="replace")
    count = text.count(old_string)
    if count == 0:
        return {"error": f"old_string not found in {path}. Read the file first and copy the exact text."}
    if count > 1:
        return {"error": f"old_string appears {count} times in {path}. Provide more surrounding context to make it unique."}
    patched = text.replace(old_string, new_string, 1)
    p.write_text(patched, encoding="utf-8")
    return {"path": path, "replaced": True, "occurrences_found": count}


async def file_append(path: str, content: str) -> dict:
    if not isinstance(content, str):
        return {"error": f"content must be a string, got {type(content).__name__} ({str(content)[:120]}). Use $variable.field to extract a specific field from a JSON result."}
    p, err = _safe_path(path)
    if err:
        return {"error": err}
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
