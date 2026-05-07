from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# ── Global kwarg alias map ────────────────────────────────────────────
#
# Common drift LLMs introduce: ``q`` instead of ``query``, ``types``
# instead of ``type``, ``track_id`` instead of ``id``, etc. This map
# is consulted by ``dispatch`` BEFORE calling the handler — if the
# LLM passed a kwarg that's not in the handler's signature AND the
# alias target IS, we silently rename. Conservative by design: an
# alias only fires when its target is an actual parameter of THIS
# handler (so ``user_id`` doesn't get renamed for handlers that
# legitimately want ``user_id``).
#
# Each entry is one direction; the inverse is added automatically below.
# Add more as drift surfaces in real sessions — bias is "support
# every reasonable LLM phrasing rather than fail loudly on a typo."
_KWARG_ALIASES_RAW: dict[str, list[str]] = {
    # The single most common drift: LLM uses ``q`` for search queries.
    "query":  ["q"],
    # Spotify/HTTP API drift on ``type``: LLM emits ``types`` (plural).
    "type":   ["types", "kind"],
    # Various ID parameter drift.
    "id":     ["item_id", "object_id"],
    "ids":    ["item_ids", "object_ids"],
    # Spotify-specific resource ID drift — the agent often passes a
    # bare ``id`` when the handler asks for the typed resource id.
    # Maps the bare alias to the more-specific param name. The
    # dispatcher picks the FIRST canonical that's actually in this
    # handler's signature, so e.g. ``spotify_get_artist`` (which
    # takes ``artist_id``) rewrites ``id`` → ``artist_id``, while a
    # handler that takes a generic ``id`` is left alone.
    "artist_id":   ["id", "artist", "artistId"],
    "track_id":    ["id", "track", "trackId"],
    "album_id":    ["id", "album", "albumId"],
    "playlist_id": ["id", "playlist", "playlistId"],
    "user_id":     ["id", "user", "userId"],
    "device_id":   ["id", "device", "deviceId"],
    "category_id": ["id", "category", "categoryId"],
    "show_id":     ["id", "show", "showId"],
    "episode_id":  ["id", "episode", "episodeId"],
    # Limit / offset / pagination drift.
    "limit":  ["max_results", "max", "count"],
    "offset": ["start", "skip", "from"],
    # Plan-tool task drift (already covered case-by-case but layered
    # here so any future plan-shaped tool inherits it).
    "tasks":   ["steps", "items", "list", "todos"],
    "task_id": ["id", "task", "taskId"],
    "status":  ["state", "new_status"],
    # Misc text aliases.
    "text":     ["message", "content", "body"],
    "name":     ["title"],
    "path":     ["file", "filepath", "filename"],
    "url":      ["link", "uri"],
    # web_app scaffold drift (matches existing scaffold_tool aliasing
    # so the generic layer + the per-tool layer agree).
    "stack":    ["template", "framework"],
}


def _build_alias_index() -> dict[str, list[str]]:
    """Flatten the raw map into a single-direction lookup:
    ``alias → list[canonical_param]``. Multiple canonical params for
    one alias is unusual but legal — the dispatcher picks the first
    one that actually matches the handler signature."""
    out: dict[str, list[str]] = {}
    for canonical, aliases in _KWARG_ALIASES_RAW.items():
        for alias in aliases:
            out.setdefault(alias, []).append(canonical)
    return out


_KWARG_ALIASES: dict[str, list[str]] = _build_alias_index()


def _accepted_params(handler: Callable) -> tuple[set[str], bool]:
    """Inspect a handler and return ``(positional/keyword param names,
    accepts_var_kwargs)``. ``accepts_var_kwargs`` skips alias rewriting —
    handlers with ``**kwargs`` already swallow extras."""
    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):
        return set(), True
    names: set[str] = set()
    has_kwargs = False
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            has_kwargs = True
            continue
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        names.add(param.name)
    return names, has_kwargs


def _resolve_kwargs(handler: Callable, args: dict[str, Any]) -> dict[str, Any]:
    """Rewrite alias kwargs to their canonical names + drop any
    leftover unknowns when the handler doesn't accept ``**kwargs``.

    The LLM frequently passes ``q="…"`` to a handler that wants
    ``query="…"`` — without this layer, dispatch raises
    ``TypeError: unexpected keyword argument 'q'`` and aborts the
    whole workflow. With it, we silently rename and the call succeeds.
    """
    accepted, has_kwargs = _accepted_params(handler)
    if has_kwargs:
        # Handler accepts **kwargs — passthrough unchanged.
        return args

    out: dict[str, Any] = {}
    for k, v in args.items():
        if k in accepted:
            out[k] = v
            continue
        # Try to map via the alias index.
        for canonical in _KWARG_ALIASES.get(k, []):
            if canonical in accepted and canonical not in out:
                out[canonical] = v
                break
        else:
            # No alias hit — drop the kwarg silently. The handler's
            # default fills in.
            continue
    return out


def _format_signature(handler: Callable, parameters: dict) -> str:
    """Build a one-line `(name: type, ...)` signature for the system
    prompt. Required params come first (no default), optional params
    show their default. Falls back to the JSON-Schema's
    ``properties`` + ``required`` when the handler isn't introspectable.

    The signature is the single most concrete thing the agent needs
    to call a tool correctly. Without it, the model has to guess
    from the description prose.
    """
    parts: list[str] = []
    seen: set[str] = set()
    try:
        sig = inspect.signature(handler)
        for param in sig.parameters.values():
            if param.kind in (
                inspect.Parameter.VAR_KEYWORD,
                inspect.Parameter.VAR_POSITIONAL,
            ):
                continue
            ann = param.annotation
            ann_str = (
                getattr(ann, "__name__", None)
                or (str(ann) if ann is not inspect.Parameter.empty else "Any")
            )
            ann_str = ann_str.replace("typing.", "")
            if param.default is inspect.Parameter.empty:
                parts.append(f"{param.name}: {ann_str}")
            else:
                default_repr = repr(param.default)
                if len(default_repr) > 24:
                    default_repr = default_repr[:21] + "…"
                parts.append(f"{param.name}: {ann_str} = {default_repr}")
            seen.add(param.name)
    except (TypeError, ValueError):
        pass

    # Fall back to JSON-Schema for anything the handler signature
    # didn't surface (rare — covers tools whose handler is a
    # closure with **kwargs).
    if not parts and isinstance(parameters, dict):
        props = parameters.get("properties") or {}
        required = set(parameters.get("required") or [])
        for name, spec in props.items():
            if name in seen:
                continue
            t = (spec or {}).get("type", "any")
            if name in required:
                parts.append(f"{name}: {t}")
            else:
                parts.append(f"{name}: {t} = …")

    return f"({', '.join(parts)})"


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict          # JSON Schema object
    handler: Callable
    requires_approval: bool = False   # If True, engine pauses and waits for user approval before running
    approval_message: str = ""        # Human-readable reason shown in the approval dialog
    # approval_type controls what the approval dialog shows:
    #   "confirm"         — standard Yes/No
    #   "set_password"    — password input (optional) for setting/clearing a password
    #   "verify_password" — password input (required) for authentication
    approval_type: str = "confirm"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    async def dispatch(self, name: str, args: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name!r}"}
        import asyncio as _asyncio
        # Generic kwarg alias resolution — rename common LLM drift
        # (``q``→``query``, ``types``→``type``, ``track_id``→``id``,
        # etc.) BEFORE calling the handler. Without this, an LLM
        # quirk like ``spotify_search(q="…")`` raised
        # ``TypeError: unexpected keyword argument 'q'`` and aborted
        # the whole workflow. See ``_KWARG_ALIASES`` above.
        try:
            args = _resolve_kwargs(tool.handler, args)
        except Exception:
            # Conservative — if the alias resolver itself fails for
            # any reason, fall through with the original args. The
            # handler may still raise a clearer error.
            pass
        try:
            result = tool.handler(**args)
            if hasattr(result, "__await__"):
                result = await result
            return result
        except _asyncio.CancelledError:
            # Always propagate cancellation — never swallow it into an error
            # dict, or the caller can't tell the task was interrupted. This
            # was the source of mysterious `{"error": ""}` results.
            raise
        except Exception as exc:
            # Always include exception type + message (never empty) so logs
            # and tool_result payloads are diagnosable.
            msg = str(exc) or repr(exc)
            return {"error": f"{type(exc).__name__}: {msg}"}

    def list_for_prompt(self) -> list[dict]:
        """Return one row per tool with name + description + a
        compact parameter signature for the system prompt.

        The signature is a single-line summary of the tool's
        ``parameters`` JSON Schema — required args first, then
        optional args with defaults. This puts the exact kwarg
        names directly under the agent's nose, which dramatically
        cuts ``TypeError: missing 1 required positional argument``
        crashes (the agent passed ``id`` when the handler wanted
        ``artist_id``, or forgot to pass ``user_id`` to
        ``spotify_create_playlist`` because it didn't see ``user_id``
        as required).

        Output shape::

            {
                "name":        "spotify_search",
                "description": "Search Spotify for tracks/albums/...",
                "signature":   "(query: str, type: str = 'track', limit: int = 10)",
            }
        """
        out: list[dict] = []
        for t in self._tools.values():
            out.append({
                "name":        t.name,
                "description": t.description,
                "signature":   _format_signature(t.handler, t.parameters),
            })
        return out

    def openai_schemas(self) -> list[dict]:
        """Return OpenAI-format tool schemas (for providers that use tool-call API)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]
