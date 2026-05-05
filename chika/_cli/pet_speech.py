"""LLM-generated pet speech bubbles.

(Text only — no audio. "Speech" here means what the pet says in its bubble
above the ASCII frame.)

Off by default (cost-conscious). When enabled, the pet says one short line
per turn in its own personality. The LLM call is fire-and-forget: the main
response renders without blocking, then the quip drops in afterwards as a
small speech bubble.

Token budget is hard-capped per call (default 40 tokens, configurable). If
the LLM call fails or times out, we silently fall back to a static quote
from the pet's :attr:`quotes` table.

The user controls this via :mod:`api.settings_store`:

- ``pet_speech``        : ``"off" | "on"``    — call the LLM for quips
- ``pet_speech_tokens`` : ``int``             — max output tokens per quip

Settings are surfaced in both the CLI (``/pet speech ...``) and the
frontend Settings → Pet tab so changes propagate atomically.
"""
from __future__ import annotations

import asyncio
import contextlib
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chika._cli.pets import Pet
    from chika.core.engine import ChikaEngine

# Per-call timeout — keep it tight so a slow LLM never delays the next prompt.
_TIMEOUT_S = 6.0


def _summarise_turn(events: list[dict]) -> str:
    """Compress a turn's events into a short factual brief for the LLM.

    The pet doesn't need the full transcript — only enough to reference what
    just happened. Tool names, error flags, final answer length.
    """
    tools: list[str] = []
    errors = 0
    answered = False
    for ev in events:
        t = ev.get("type")
        if t == "tool_call":
            name = ev.get("tool", "?")
            if name not in tools:
                tools.append(name)
        elif t == "tool_result" and ev.get("error"):
            errors += 1
        elif t == "token":
            answered = True
    parts: list[str] = []
    if tools:
        parts.append(f"used tools: {', '.join(tools[:5])}")
    else:
        parts.append("no tools used")
    if errors:
        parts.append(f"{errors} tool error(s)")
    if answered:
        parts.append("produced a written reply")
    return "; ".join(parts)


def _pick_static(pet: Pet, state: str) -> str:
    """Best-effort fallback when the LLM call is disabled or fails."""
    options = pet.quotes.get(state) or pet.quotes.get("idle") or []
    if not options:
        return ""
    return random.choice(options)


async def generate_quote(
    engine: ChikaEngine,
    pet: Pet,
    *,
    state: str,
    turn_events: list[dict],
    max_tokens: int = 40,
) -> str:
    """Return a short pet quip for the current state.

    Calls the engine's LLM via :meth:`ChikaEngine._llm_complete` so it shares
    the same provider config — no extra API client to manage. Capped at
    ``max_tokens`` and clipped to ~80 chars regardless.
    """
    summary = _summarise_turn(turn_events)
    state_hint = {
        "celebrate": "the user just succeeded; be playful and proud",
        "sad":       "something failed; be sympathetic but light",
        "working":   "you're in the middle of a task; be in-character",
        "idle":      "you're chilling; greet or chirp, in-character",
    }.get(state, "")

    prompt = (
        f"You are {pet.name}, a tiny pet companion living in a developer's "
        f"terminal. Personality: {pet.personality or 'cute, helpful, low-key'}.\n\n"
        f"Context — this turn just ended: {summary}.\n"
        f"State: {state}.  ({state_hint})\n\n"
        f"Reply with ONE short line, max 12 words, lowercase preferred, "
        f"no markdown, no quotes. Stay in character. No questions."
    )

    try:
        text = await asyncio.wait_for(
            _bounded_complete(engine, prompt, max_tokens=max_tokens),
            timeout=_TIMEOUT_S,
        )
    except (TimeoutError, Exception):
        return _pick_static(pet, state)

    text = (text or "").strip().splitlines()[0].strip().strip('"').strip("'")
    if len(text) > 80:
        text = text[:80].rstrip() + "…"
    return text or _pick_static(pet, state)


async def _bounded_complete(engine: ChikaEngine, prompt: str, *, max_tokens: int) -> str:
    """Mirror of ``ChikaEngine._llm_complete`` with an explicit token cap.

    Avoids modifying the engine's public surface for this niche call.
    """
    import config

    cfg = config.get_provider_config()
    cap = max(8, min(int(max_tokens), 200))

    if engine._client is None:
        # Stub-only sessions don't have a live client; pet speech is
        # cosmetic, so silently return an empty quote.
        return ""

    if cfg.provider in ("azure", "openai", "ollama"):
        resp = await engine._client.chat.completions.create(
            model=engine._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=cap,
            temperature=0.9,
            stream=False,
        )
        return resp.choices[0].message.content or ""
    if cfg.provider == "anthropic":
        resp = await engine._client.messages.create(
            model=engine._model,
            max_tokens=cap,
            temperature=0.9,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in (resp.content or []):
            if getattr(block, "type", None) == "text":
                return getattr(block, "text", "") or ""
    return ""


def fire_and_forget(
    engine: ChikaEngine,
    pet: Pet,
    *,
    state: str,
    turn_events: list[dict],
    max_tokens: int,
    on_done: Any,
) -> asyncio.Task | None:
    """Schedule a pet quote generation in the background.

    ``on_done`` is invoked with the resulting string. The task swallows all
    exceptions; the main turn loop is never affected by pet voice failures.
    """
    async def _runner() -> None:
        text = await generate_quote(
            engine, pet,
            state=state, turn_events=turn_events,
            max_tokens=max_tokens,
        )
        with contextlib.suppress(Exception):
            on_done(text)

    try:
        return asyncio.create_task(_runner())
    except RuntimeError:
        return None
