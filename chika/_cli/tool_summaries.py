"""Per-tool compact result formatters for the CLI.

Each formatter takes a tool's ``result`` dict and returns a SHORT,
human-friendly summary string (≤120 chars) describing what happened
— tuned to the specific tool's semantics. The renderer prints this
in place of the generic JSON dump (``⎿ { ... }``).

Why this exists: a one-size-fits-all JSON dump treats every tool
result the same, but the user cares about totally different fields
per tool. ``web_fetch`` cares about status + bytes; ``file_read``
cares about line count; ``shell_exec`` cares about exit code +
output tail; ``plan_set`` cares about the plan summary, not the JSON
echo. Each formatter is a tiny function — easy to add a new one.

Pattern:

    def _summary(tool_name) -> str | None:
        ...

Returning ``None`` falls back to the generic JSON dump. So a
half-implemented formatter never breaks rendering.

Read tools (file_read, web_search, browser_get_text, …) typically
report quantity + source. Write tools (file_write, plan_set,
git_commit, …) typically report what was committed. Effect tools
(shell_exec, browser_click, …) typically report exit/effect status.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _short(s: Any, n: int = 60) -> str:
    """Truncate ``s`` to ``n`` characters with an ellipsis."""
    text = str(s).replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


# ── File tools ────────────────────────────────────────────────────────


def _file_read(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    path = r.get("path", "")
    line_count = r.get("line_count")
    total = r.get("total_lines")
    size = r.get("size_bytes")
    content = r.get("content")
    suffix = f" · {path}" if path else ""
    if line_count is not None and total is not None and line_count != total:
        return f"read {line_count}/{total} lines{suffix}"
    if total is not None:
        return f"read {total} lines{suffix}"
    if size is not None:
        return f"{size}B{suffix}"
    if isinstance(content, str):
        # Fallback: count lines in the content itself.
        n = content.count("\n") + 1 if content else 0
        return f"read {n} line{'s' if n != 1 else ''}{suffix}"
    return None


def _file_write(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    path = r.get("path", "?")
    size = r.get("size_bytes") or r.get("bytes_written") or r.get("bytes")
    if size is not None:
        return f"wrote {size}B → {path}"
    if r.get("ok") or path != "?":
        return f"wrote → {path}"
    return None


def _file_edit_lines(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    n = r.get("lines_replaced")
    total = r.get("total_lines")
    if n is not None and total is not None:
        return f"replaced {n} lines · {total} lines total"
    return None


def _file_replace(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    if r.get("replaced") and r.get("path"):
        return f"replaced 1 occurrence · {r['path']}"
    return None


def _file_append(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    bytes_ = r.get("appended_bytes")
    path = r.get("path", "?")
    if bytes_ is not None:
        return f"appended {bytes_}B → {path}"
    return None


def _file_info(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    path = r.get("path", "?")
    if r.get("is_dir"):
        return f"directory · {path}"
    size = r.get("size_bytes")
    ext = r.get("extension") or ""
    if size is not None:
        return f"{size}B · {ext} · {path}"
    return None


# ── Shell ─────────────────────────────────────────────────────────────


def _shell_exec(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    code = r.get("exit_code", r.get("returncode"))
    pid = r.get("pid")
    stdout = (r.get("stdout") or "").strip()
    if pid and r.get("background"):
        return f"started · pid {pid}"
    if code is not None:
        tail = _short(stdout, 50) if stdout else ""
        if tail:
            return f"exit {code} · {tail}"
        return f"exit {code}"
    return None


def _shell_get_output(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    out = r.get("stdout", "")
    if isinstance(out, str):
        lines = len(out.splitlines()) or (1 if out else 0)
        pid = r.get("pid")
        if pid:
            return f"pid {pid} · {lines} line{'s' if lines != 1 else ''}"
        return f"{lines} line{'s' if lines != 1 else ''}"
    return None


def _shell_kill(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    pid = r.get("pid")
    if r.get("killed") or r.get("ok"):
        return f"killed pid {pid}"
    return None


# ── Web ───────────────────────────────────────────────────────────────


def _web_fetch(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    status = r.get("status") or r.get("status_code")
    url = r.get("url", "")
    bytes_ = r.get("bytes") or r.get("size_bytes")
    parts = []
    if status is not None:
        parts.append(f"{status}")
    if bytes_ is not None:
        parts.append(f"{bytes_}B")
    if url:
        parts.append(_short(url, 60))
    return " · ".join(parts) if parts else None


def _web_search(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    results = r.get("results") or []
    query = r.get("query") or ""
    n = len(results) if isinstance(results, list) else 0
    if query:
        return f"{n} results · '{_short(query, 50)}'"
    return f"{n} results"


def _web_head(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    status = r.get("status") or r.get("status_code")
    url = r.get("url", "")
    if status is not None:
        return f"{status} · {_short(url, 60)}"
    return None


def _verify_url(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    if r.get("ok") or r.get("verified"):
        return f"verified · {_short(r.get('url', ''), 60)}"
    return None


# ── Browser ───────────────────────────────────────────────────────────


def _browser_screenshot(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    w, h = r.get("width"), r.get("height")
    if w and h:
        return f"screenshot · {w}×{h}"
    return None


def _browser_navigate(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    if r.get("url"):
        return f"navigated · {_short(r['url'], 60)}"
    return None


def _browser_get_text(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    chars = r.get("char_count")
    title = r.get("title", "")
    if chars is not None and title:
        return f"{chars} chars · {_short(title, 50)}"
    if chars is not None:
        return f"{chars} chars"
    return None


def _browser_get_dom(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    chars = r.get("char_count") or len(r.get("html", ""))
    if chars:
        return f"{chars}B HTML"
    return None


def _browser_click(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    if r.get("ok") or r.get("clicked"):
        return f"clicked · {_short(r.get('selector', ''), 60)}"
    return None


def _browser_fill_input(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    if r.get("ok") or r.get("filled"):
        return f"filled · {_short(r.get('selector', ''), 60)}"
    return None


def _browser_get_page_var(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    path = r.get("var_path", "")
    if r.get("keys_preview"):
        keys = ", ".join(map(str, r["keys_preview"][:5]))
        return f"{path} → keys: {keys}…"
    bytes_ = r.get("bytes")
    if bytes_:
        return f"{path} · {bytes_}B"
    return None


def _browser_watch(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    if r.get("watch_id"):
        return f"watching · {_short(r.get('selector', ''), 50)}"
    return None


# ── Plan ──────────────────────────────────────────────────────────────


def _plan_set(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    n = r.get("count")
    if n is not None:
        return f"plan set · {n} task{'s' if n != 1 else ''}"
    return None


def _plan_update(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    plan = r.get("plan") or {}
    tasks = plan.get("tasks") or []
    done = sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "done")
    return f"plan updated · {done}/{len(tasks)} done"


def _plan_add(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    added = r.get("added") or []
    if added:
        return f"+{len(added)} task{'s' if len(added) != 1 else ''}"
    return None


def _plan_remove(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    removed = r.get("removed") or []
    if removed:
        return f"-{len(removed)} task{'s' if len(removed) != 1 else ''}"
    return None


def _plan_archive(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    if r.get("archived"):
        return "plan archived"
    return r.get("note") or None


def _plan_history(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    n = r.get("count")
    if n is not None:
        return f"{n} archived plan{'s' if n != 1 else ''}"
    return None


# ── Memory ────────────────────────────────────────────────────────────


def _memory_persist(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    name = r.get("name")
    text = r.get("text") or r.get("content") or r.get("body") or ""
    if name and text:
        return f"remembered · {name} → '{_short(text, 60)}'"
    if name:
        return f"remembered · {name}"
    if text:
        return f"remembered · '{_short(text, 80)}'"
    if r.get("saved") or r.get("ok"):
        return "remembered"
    return None


def _memory_recall(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    items = r.get("memories") or r.get("results") or []
    n = len(items) if isinstance(items, list) else 0
    return f"recalled {n} memor{'ies' if n != 1 else 'y'}"


def _memory_forget(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    if r.get("forgotten") or r.get("ok"):
        return "forgot memory"
    return None


# ── Git ───────────────────────────────────────────────────────────────


def _git_status(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    branch = r.get("branch", "?")
    dirty = r.get("dirty") or r.get("modified") or []
    n = len(dirty) if isinstance(dirty, list) else 0
    return f"branch {branch} · {n} change{'s' if n != 1 else ''}"


def _git_log(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    commits = r.get("commits") or []
    n = len(commits) if isinstance(commits, list) else 0
    return f"{n} commit{'s' if n != 1 else ''}"


def _git_commit(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    sha = r.get("sha") or r.get("hash") or ""
    if sha:
        return f"committed {sha[:7]}"
    return None


def _git_diff(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    files = r.get("files_changed", r.get("files"))
    if files is not None:
        return f"diff · {files} file{'s' if files != 1 else ''}"
    return None


def _git_push(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    if r.get("pushed") or r.get("ok"):
        return f"pushed · {r.get('remote', 'origin')}/{r.get('branch', '?')}"
    return None


# ── Spotify ───────────────────────────────────────────────────────────


def _spotify_search(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    tracks = (r.get("tracks") or {}).get("items") or []
    if tracks:
        return f"{len(tracks)} tracks"
    return None


def _spotify_play(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    if r.get("ok"):
        return "▶ playing"
    return None


# ── LLM meta-tools ────────────────────────────────────────────────────


def _llm_summarise(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    summary = r.get("summary") or r.get("text") or ""
    if summary:
        return f"summary · '{_short(summary, 80)}'"
    return None


def _llm_transform(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    keys = list(r.keys())
    if keys:
        return f"transformed · keys: {', '.join(keys[:6])}"
    return None


# ── Other ─────────────────────────────────────────────────────────────


def _python_run(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    code = r.get("exit_code", r.get("returncode"))
    out = (r.get("stdout") or "").strip()
    if code is not None:
        if out:
            return f"exit {code} · {_short(out, 50)}"
        return f"exit {code}"
    return None


def _live_server(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    port = r.get("port")
    pid = r.get("pid")
    if port and pid:
        return f"localhost:{port} · pid {pid}"
    return None


def _scaffold_web_app(r: dict) -> str | None:
    if not isinstance(r, dict):
        return None
    files = r.get("files_created") or r.get("files") or []
    n = len(files) if isinstance(files, list) else 0
    return f"scaffolded · {n} file{'s' if n != 1 else ''}"


# ── Registry ──────────────────────────────────────────────────────────
# Tool name → formatter. Add new entries as new tools land. A missing
# entry falls back to the generic JSON dump (which is fine for tools
# whose results are too irregular for a single-line summary).

_FORMATTERS: dict[str, Callable[[Any], str | None]] = {
    # File
    "file_read":          _file_read,
    "file_write":         _file_write,
    "file_edit_lines":    _file_edit_lines,
    "file_replace":       _file_replace,
    "file_append":        _file_append,
    "file_info":          _file_info,
    # Shell
    "shell_exec":         _shell_exec,
    "shell_get_output":   _shell_get_output,
    "shell_kill":         _shell_kill,
    # Web
    "web_fetch":          _web_fetch,
    "web_search":         _web_search,
    "web_head":           _web_head,
    "verify_url":         _verify_url,
    # Browser
    "browser_screenshot":     _browser_screenshot,
    "browser_navigate":       _browser_navigate,
    "browser_get_text":       _browser_get_text,
    "browser_get_dom":        _browser_get_dom,
    "browser_click":          _browser_click,
    "browser_fill_input":     _browser_fill_input,
    "browser_get_page_var":   _browser_get_page_var,
    "browser_watch_element":  _browser_watch,
    # Plan
    "plan_set":      _plan_set,
    "plan_update":   _plan_update,
    "plan_add":      _plan_add,
    "plan_remove":   _plan_remove,
    "plan_archive":  _plan_archive,
    "plan_history":  _plan_history,
    # Memory
    "memory_persist":  _memory_persist,
    "memory_recall":   _memory_recall,
    "memory_forget":   _memory_forget,
    # Git
    "git_status":  _git_status,
    "git_log":     _git_log,
    "git_commit":  _git_commit,
    "git_diff":    _git_diff,
    "git_push":    _git_push,
    # Spotify
    "spotify_search":  _spotify_search,
    "spotify_play":    _spotify_play,
    # LLM meta
    "llm_summarise":   _llm_summarise,
    "llm_transform":   _llm_transform,
    # Other
    "python_run":         _python_run,
    "live_server":        _live_server,
    "scaffold_web_app":   _scaffold_web_app,
}


def summarise(tool: str, result: Any) -> str | None:
    """Return a short, human-friendly summary of ``result`` for ``tool``,
    or None if no formatter is registered (caller falls back to JSON dump).
    """
    fn = _FORMATTERS.get(tool)
    if fn is None:
        return None
    try:
        return fn(result)
    except Exception:
        # A formatter bug must never break tool result rendering.
        return None
