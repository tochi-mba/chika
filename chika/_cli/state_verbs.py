"""Context-aware verbs for the inline state indicator.

The CLI's inline activity indicator (see ``renderer._render_state_row``)
shows a present-continuous verb beside the trefoil glyph — same
pattern as Claude Code's activity line ("✸ Vibing…"). By default the
verbs are a static rotation (``mark.INLINE_VERBS``). When a turn
starts we fire a tiny LLM call in the background asking for 6-8 verbs
that fit *this specific* user message — so a debugging request might
yield "Investigating, Tracing, Diagnosing, Hypothesising"; a refactor
request might yield "Sketching, Architecting, Untangling".

Pattern is fire-and-forget — exactly like ``pet_speech.py``. The
indicator falls back to static verbs while the LLM call is in flight,
then swaps in the contextual list when it returns. If the call fails,
times out, or the user has the feature disabled, the static list
keeps showing — purely cosmetic, never fails the turn.

User controls (via ``api.settings_store``):

- ``state_verbs``        : ``"off" | "on"`` — call the LLM at all
- ``state_verbs_tokens`` : ``int``          — max output tokens per call

Both surfaced in the CLI (``/state verbs ...``) and the frontend
Settings panel so changes propagate atomically.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chika.core.engine import ChikaEngine

# Per-call timeout — keep it tight so a slow LLM never delays anything.
_TIMEOUT_S = 5.0


def _build_prompt(user_message: str, history_tail: list[dict]) -> str:
    """Compress the active context into a short prompt the LLM can answer
    cheaply with a list of verbs."""
    # Last 3 user/assistant exchanges so the LLM sees what's happening,
    # without burning tokens on the full history.
    tail_lines: list[str] = []
    for msg in (history_tail or [])[-6:]:
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        snippet = content.strip().replace("\n", " ")
        if len(snippet) > 200:
            snippet = snippet[:200] + "…"
        tail_lines.append(f"[{role}] {snippet}")
    tail = "\n".join(tail_lines) or "(no prior turns)"

    return (
        "You are a CLI agent's status indicator. The user just asked:\n"
        f"---\n{user_message[:400]}\n---\n\n"
        "Recent context:\n"
        f"{tail}\n\n"
        "List 6 to 8 present-continuous verbs (single English words ending "
        "in -ing) describing what an AI assistant might be doing right now "
        "to answer this. They should match the SHAPE of the request — "
        "debugging questions get verbs like Investigating, Tracing; "
        "implementation questions get verbs like Sketching, Architecting; "
        "research questions get verbs like Surveying, Cross-referencing. "
        "Vary register so the user sees variety as they cycle.\n\n"
        "Reply with a comma-separated list, NOTHING else. No quotes, no "
        "preamble, no numbering. Example: Investigating, Tracing, "
        "Diagnosing, Hypothesising, Reasoning, Cross-checking"
    )


_VERB_RE = re.compile(r"[A-Za-z][A-Za-z\-']{2,18}ing", re.IGNORECASE)


def _parse_verbs(text: str) -> list[str]:
    """Pull -ing verbs out of an LLM response.  Tolerates the model
    adding bullets, numbering, or extra prose around the list."""
    raw = (text or "").strip()
    # First try comma-split (the requested format).
    candidates = [v.strip(" .•-*\"'\t") for v in raw.split(",")]
    cleaned: list[str] = []
    for v in candidates:
        m = _VERB_RE.search(v)
        if m:
            verb = m.group(0)
            # Title-case the first letter so they look uniform on screen.
            verb = verb[:1].upper() + verb[1:]
            if verb not in cleaned:
                cleaned.append(verb)
    # Cap at 12 even if the LLM got chatty.
    return cleaned[:12]


async def generate_verbs(engine: ChikaEngine, user_message: str,
                         history_tail: list[dict],
                         max_tokens: int = 80) -> list[str]:
    """Return a list of contextual verbs, or [] if the call fails."""
    prompt = _build_prompt(user_message, history_tail)
    try:
        text = await asyncio.wait_for(
            _bounded_complete(engine, prompt, max_tokens=max_tokens),
            timeout=_TIMEOUT_S,
        )
    except (TimeoutError, Exception):
        return []
    return _parse_verbs(text)


async def _bounded_complete(engine: ChikaEngine, prompt: str, *, max_tokens: int) -> str:
    """Mirror of ``ChikaEngine._llm_complete`` with an explicit token cap.

    Same shape as ``pet_speech._bounded_complete`` — kept separate so
    the two cosmetic features can evolve independently without
    coupling.
    """
    import config

    cfg = config.get_provider_config()
    cap = max(16, min(int(max_tokens), 200))

    if engine._client is None:
        return ""

    if cfg.provider in ("azure", "openai", "ollama"):
        resp = await engine._client.chat.completions.create(
            model=engine._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=cap,
            temperature=0.8,
            stream=False,
        )
        return resp.choices[0].message.content or ""
    if cfg.provider == "anthropic":
        resp = await engine._client.messages.create(
            model=engine._model,
            max_tokens=cap,
            temperature=0.8,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in (resp.content or []):
            if getattr(block, "type", None) == "text":
                return getattr(block, "text", "") or ""
    return ""


def fire_and_forget(engine: ChikaEngine, user_message: str,
                    history_tail: list[dict],
                    on_done: Any,
                    *,
                    max_tokens: int = 80) -> asyncio.Task | None:
    """Schedule a background verb-generation; ``on_done(list[str])``
    receives the parsed list when it lands. Swallows all errors —
    the indicator falls back to static verbs if anything goes wrong.

    ``max_tokens`` caps the LLM call (user-tuneable via
    ``state_verbs_tokens`` in settings).
    """
    async def _runner() -> None:
        verbs = await generate_verbs(
            engine, user_message, history_tail, max_tokens=max_tokens,
        )
        with contextlib.suppress(Exception):
            on_done(verbs)

    coro = _runner()
    try:
        return asyncio.create_task(coro)
    except RuntimeError:
        coro.close()
        return None
