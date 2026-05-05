"""pet_skill — Chika's animated companion gets first-class agent tools.

The pet has been a UI-only ornament. This skill lets the agent actually
interact with it: pet it, feed it, play with it, ask after its mood,
remember things about it. Every interaction nudges a session-scoped
mood counter and writes a per-pet markdown memory file so facts about
the pet (name, quirks, favourite things) survive across sessions.

The skill ALSO declares a ``prompt_section`` contributor so the system
prompt always carries the active pet's name + mood + current frame +
relevant memory snippets. That fixes the "the agent has no idea its
pet exists" bug — when the user says "look at my cat!" the agent now
sees the same companion they do and can reply in character.

Tools
-----
- ``pet_pet``      — short happy bubble + brief celebrate frame
- ``pet_feed``     — feeds the pet; bumps mood; longer celebrate
- ``pet_play``     — extended play session; biggest mood bump
- ``pet_status``   — returns name, mood, current state, recent quotes
- ``pet_speak``    — give the pet a custom one-liner to say
- ``pet_remember`` — write a fact to the pet's memory file (favourite
  food, quirks, name corrections — anything the user wants the pet to
  remember next session)
- ``pet_recall``   — read the pet's memory file (or filter by query)

Memory file layout
------------------
``data/profiles/<profile>/pets/<pet_id>/memory.md``

One file per (profile, pet) pair, so swapping pets gives each its own
distinct continuity. When the user changes pets, the carry/clear
choice is exposed on the API + CLI — see ``copy_memory`` /
``clear_memory`` flags on the profile-pet endpoint and the ``/pet``
slash command.

Mood model
----------
Mood is a single integer in [-50, +50]. Every interaction bumps it; it
naturally decays back toward 0 once per minute (handled lazily — no
background thread). Interpretations:

  +25..+50  ecstatic / 'celebrate' state
  +5..+24   happy / cheerful idle frames
  -5..+4    neutral idle
  -24..-6   needy ('working' frame, sad bubble)
  -50..-25  sad state, drooping eyes

The mood is per-profile so different profiles see their pet in
different moods. Stored on the variable store under ``$pet_mood`` so it
persists across the session and survives compaction.
"""
from __future__ import annotations

import random
import time
from pathlib import Path

from chika.core.skill_registry import Skill
from chika.core.tool_registry import ToolDefinition
from chika.core.variable_store import VarType

# ── Persistent pet memory (per profile, per pet) ──────────────────────


def _pet_memory_path(profile_workspace: str, pet_id: str) -> Path:
    """Return the markdown file where the pet's memory lives.

    Layout: ``<profile_dir>/pets/<pet_id>/memory.md``. We accept the
    profile's *workspace* path (``data/profiles/<name>/workspace``) and
    walk up to the profile root so the pet directory sits next to
    ``memory.md`` rather than inside the user's actual workspace.
    """
    workspace = Path(profile_workspace).resolve()
    profile_root = workspace.parent  # workspace lives at profile_root/workspace
    return profile_root / "pets" / (pet_id or "default") / "memory.md"


def _read_pet_memory(workspace: str, pet_id: str) -> str:
    path = _pet_memory_path(workspace, pet_id)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _append_pet_memory(workspace: str, pet_id: str, fact: str) -> Path:
    """Append a fact to the pet's memory file. Creates parents if needed.

    Each line is timestamp-tagged so ordering survives compaction. The
    file format is intentionally plain markdown — readable by both the
    LLM and the user, no schema, no separator parsing.
    """
    path = _pet_memory_path(workspace, pet_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    line = f"- [{stamp}] {fact.strip()}\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return path


def copy_pet_memory(workspace: str, src_pet: str, dst_pet: str) -> bool:
    """Copy memory from one pet to another. Used by the ``/pet`` slash
    command + API endpoint when the user picks "carry the personality"
    on a pet swap."""
    src = _pet_memory_path(workspace, src_pet)
    if not src.exists():
        return False
    dst = _pet_memory_path(workspace, dst_pet)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def clear_pet_memory(workspace: str, pet_id: str) -> bool:
    """Wipe the named pet's memory file. Used on the "fresh start"
    branch of pet swaps. Idempotent — silently succeeds if no file."""
    path = _pet_memory_path(workspace, pet_id)
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return True


# Mood model -----------------------------------------------------------

_MOOD_MIN, _MOOD_MAX = -50, 50

# How fast mood decays back toward 0 — one unit per `_MOOD_DECAY_SECONDS`.
_MOOD_DECAY_SECONDS = 60.0

# Per-action bumps. Bigger numbers = bigger mood swing.
_BUMP = {
    "pet":  +6,
    "feed": +12,
    "play": +18,
    "speak": +2,
    "ignore": -3,
}


def _label_for_mood(mood: int) -> str:
    if mood >= 25:  return "ecstatic"
    if mood >= 5:   return "happy"
    if mood >= -4:  return "neutral"
    if mood >= -24: return "needy"
    return "sad"


def _state_for_mood(mood: int) -> str:
    """Map mood → renderer pet state (idle / working / celebrate / sad)."""
    if mood >= 25:  return "celebrate"
    if mood >= -4:  return "idle"
    if mood >= -24: return "working"
    return "sad"


# Storage layer --------------------------------------------------------


def _read_mood(variable_store) -> tuple[int, float]:
    """Return (mood_after_decay, last_updated_ts)."""
    var = variable_store.get("pet_mood")
    if var is None or not isinstance(var.value, dict):
        return 0, time.time()
    raw = var.value
    last_ts = float(raw.get("updated_at", time.time()))
    raw_mood = int(raw.get("mood", 0))
    # Lazy decay — mood drifts toward 0 one unit per _MOOD_DECAY_SECONDS.
    elapsed = max(0.0, time.time() - last_ts)
    drift = int(elapsed // _MOOD_DECAY_SECONDS)
    if drift > 0 and raw_mood != 0:
        if raw_mood > 0:
            raw_mood = max(0, raw_mood - drift)
        else:
            raw_mood = min(0, raw_mood + drift)
    return _clamp(raw_mood), last_ts


def _write_mood(variable_store, mood: int, last_quote: str = "") -> dict:
    payload = {
        "mood":       _clamp(mood),
        "label":      _label_for_mood(mood),
        "state":      _state_for_mood(mood),
        "last_quote": last_quote,
        "updated_at": time.time(),
    }
    variable_store.set(
        "pet_mood", payload, VarType.JSON,
        description="Pet companion mood + last spoken line",
        source="pet_skill",
    )
    return payload


def _clamp(n: int) -> int:
    return max(_MOOD_MIN, min(_MOOD_MAX, int(n)))


# Tool implementations -------------------------------------------------


def _make_pet_tools(variable_store, profile_getter, workspace_getter):
    """Return the seven pet tools as a tuple, closing over the var store,
    a callable returning the active pet id, and a callable returning the
    active profile's workspace path (so per-pet memory lands inside the
    profile's directory).
    """
    from chika._cli import pets as _pets

    def _active_pet():
        try:
            pet_id = profile_getter() if callable(profile_getter) else profile_getter
        except Exception:
            pet_id = None
        return _pets.get(pet_id)

    def _active_workspace() -> str:
        try:
            ws = workspace_getter() if callable(workspace_getter) else workspace_getter
        except Exception:
            ws = ""
        return str(ws) if ws else ""

    def _react(action: str, custom_speech: str = "") -> dict:
        pet = _active_pet()
        prev_mood, _ = _read_mood(variable_store)
        new_mood = _clamp(prev_mood + _BUMP.get(action, 0))
        # Pick a quote in the matching mood bucket.
        if custom_speech:
            quote = custom_speech.strip()
        else:
            kind = "celebrate" if action in ("pet", "feed", "play") else "idle"
            try:
                pool = pet.quotes.get(kind) or pet.quotes.get("idle") or []
            except Exception:
                pool = []
            quote = random.choice(pool) if pool else ""
        payload = _write_mood(variable_store, new_mood, last_quote=quote)
        return {
            "_source":   f"pet_{action}",
            "pet_id":    pet.id,
            "pet_name":  pet.name,
            "action":    action,
            "mood":      payload["mood"],
            "label":     payload["label"],
            "state":     payload["state"],
            "speech":    quote,
            "delta":     new_mood - prev_mood,
        }

    async def pet_pet(**_extra) -> dict:
        """Briefly pet the companion. Small mood bump + short celebrate."""
        return _react("pet")

    async def pet_feed(food: str | None = None, **_extra) -> dict:
        """Feed the companion. ``food`` is purely cosmetic narrative."""
        result = _react("feed")
        if food:
            result["food"] = str(food)[:60]
        return result

    async def pet_play(**_extra) -> dict:
        """A longer play session. Biggest mood bump."""
        return _react("play")

    async def pet_speak(line: str = "", **_extra) -> dict:
        """Give the pet a custom one-line speech bubble.

        Use this when the user asks you to make the pet say something
        specific ("tell my cat to wish me good morning"). The bubble
        rendering is governed by the renderer; this tool just records
        the line so every surface picks it up.
        """
        if not line or not line.strip():
            return {"error": "pet_speak requires a non-empty 'line'."}
        return _react("speak", custom_speech=line[:160])

    async def pet_status(**_extra) -> dict:
        """Return everything we know about the pet right now."""
        pet = _active_pet()
        mood, last_ts = _read_mood(variable_store)
        ws = _active_workspace()
        memory = _read_pet_memory(ws, pet.id) if ws else ""
        return {
            "_source":     "pet_status",
            "pet_id":      pet.id,
            "pet_name":    pet.name,
            "personality": pet.personality,
            "description": pet.description,
            "mood":        mood,
            "label":       _label_for_mood(mood),
            "state":       _state_for_mood(mood),
            "last_seen":   last_ts,
            "memory":      memory or "(empty — nothing remembered yet)",
            "memory_lines": memory.count("\n") if memory else 0,
        }

    async def pet_remember(fact: str = "", **_extra) -> dict:
        """Persist a fact about the pet to its per-profile memory file.

        Use when the user shares something the pet should remember
        across sessions: nicknames, dietary preferences, personality
        notes, last week's adventures. Each fact is timestamped and
        appended to ``data/profiles/<profile>/pets/<pet_id>/memory.md``.
        """
        if not fact or not fact.strip():
            return {"error": "pet_remember requires a non-empty 'fact'."}
        pet = _active_pet()
        ws = _active_workspace()
        if not ws:
            return {
                "error": "no_workspace",
                "hint":  "pet_remember needs an active profile workspace.",
            }
        path = _append_pet_memory(ws, pet.id, fact[:500])
        return {
            "_source":   "pet_remember",
            "pet_id":    pet.id,
            "pet_name":  pet.name,
            "stored":    fact[:500],
            "path":      str(path),
        }

    async def pet_recall(query: str | None = None, max_lines: int = 12,
                         **_extra) -> dict:
        """Read the pet's memory file. ``query`` filters lines by
        case-insensitive substring; without it the most recent
        ``max_lines`` are returned."""
        pet = _active_pet()
        ws = _active_workspace()
        if not ws:
            return {
                "error": "no_workspace",
                "hint":  "pet_recall needs an active profile workspace.",
            }
        memory = _read_pet_memory(ws, pet.id)
        if not memory:
            return {
                "_source":  "pet_recall",
                "pet_id":   pet.id,
                "pet_name": pet.name,
                "memory":   "",
                "lines":    [],
                "note":     "No memory yet — call pet_remember to save facts.",
            }
        lines = [ln for ln in memory.splitlines() if ln.strip()]
        if query:
            q = query.lower()
            lines = [ln for ln in lines if q in ln.lower()]
        # Last N matching lines so the agent gets the most recent context.
        if max_lines and len(lines) > max_lines:
            lines = lines[-max_lines:]
        return {
            "_source":  "pet_recall",
            "pet_id":   pet.id,
            "pet_name": pet.name,
            "lines":    lines,
            "memory":   "\n".join(lines),
            "filtered": bool(query),
        }

    return (pet_pet, pet_feed, pet_play, pet_speak, pet_status,
            pet_remember, pet_recall)


# Prompt-section contributor ------------------------------------------


def _make_prompt_section(variable_store, profile_getter, workspace_getter):
    """Build the per-turn prompt block describing the pet.

    Kept tight — about 8 lines of markdown — so we don't spend much of
    the turn budget on cosmetic context. Includes the live frame and a
    short memory tail (last 3 remembered facts) so the agent can react
    to "look at my pretty cat!" with conviction and reference things
    the user has explicitly asked it to remember.
    """
    from chika._cli import pets as _pets

    def render() -> str:
        try:
            pet_id = profile_getter() if callable(profile_getter) else profile_getter
        except Exception:
            pet_id = None
        pet = _pets.get(pet_id)
        mood, _ = _read_mood(variable_store)
        label = _label_for_mood(mood)
        state = _state_for_mood(mood)
        try:
            frame = pet.frame_for(state, 0)
        except Exception:
            frame = ""

        # Pull the last 3 memory lines (compact tail so we don't bloat
        # the prompt). Full memory is available via pet_recall.
        try:
            ws = workspace_getter() if callable(workspace_getter) else workspace_getter
        except Exception:
            ws = ""
        recent_facts: list[str] = []
        if ws:
            memory = _read_pet_memory(str(ws), pet.id)
            if memory:
                non_empty = [ln for ln in memory.splitlines() if ln.strip()]
                recent_facts = non_empty[-3:]

        lines = [
            "## Your pet companion",
            "",
            f"You have a pet named **{pet.name}** ({pet.id}). It lives "
            "next to you in the CLI panel + frontend overlay + extension "
            f"popup — the user sees it the same way you do. Personality: "
            f"_{pet.personality or 'cheerful'}_. Current mood: "
            f"**{label}** ({mood:+d}/50). State: `{state}`.",
            "",
            "When the user mentions or compliments the pet, acknowledge "
            "it warmly — call it by name. Use `pet_pet` / `pet_feed` / "
            "`pet_play` to react; `pet_speak` for a custom line; "
            "`pet_remember` / `pet_recall` for persistent facts about "
            "the pet (the user can ask you to remember nicknames, "
            "favourites, anything across sessions).",
        ]
        if recent_facts:
            lines.append("")
            lines.append("Recently remembered about this pet:")
            for fact in recent_facts:
                lines.append(fact)
        if frame:
            lines += ["", "Current frame (idle):", "```", frame, "```"]
        return "\n".join(lines)

    return render


# Public builder -------------------------------------------------------


def build_pet_skill(variable_store, profile_getter,
                    workspace_getter=None) -> Skill:
    """Build the pet skill.

    ``profile_getter`` is a no-arg callable returning the active pet id
    ('cat', 'dog', ...). ``workspace_getter`` (optional) returns the
    active profile's workspace path so per-pet memory files land
    inside the profile directory. Both are late-bound so the skill can
    be registered before the engine is constructed; the session
    manager wires them to live profile state.
    """
    (pet_pet, pet_feed, pet_play, pet_speak, pet_status,
     pet_remember, pet_recall) = _make_pet_tools(
        variable_store, profile_getter, workspace_getter,
    )
    section = _make_prompt_section(
        variable_store, profile_getter, workspace_getter,
    )
    return Skill(
        name="pet",
        description=(
            "Interact with the user's animated pet companion. Use the "
            "pet tools to react in-character when the user comments on "
            "the pet, asks how it's doing, or wants it to do something."
        ),
        tools=[
            ToolDefinition(
                name="pet_pet",
                description=(
                    "Pet the companion briefly. Small mood bump + short "
                    "celebrate animation. Call this when the user says "
                    "things like 'aww', 'good kitty', 'hi pet', etc."
                ),
                parameters={"type": "object", "properties": {}},
                handler=pet_pet,
            ),
            ToolDefinition(
                name="pet_feed",
                description=(
                    "Feed the companion. Bigger mood bump than pet_pet. "
                    "Optional ``food`` argument is purely cosmetic — "
                    "doesn't affect the mood maths."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "food": {
                            "type": "string",
                            "description": (
                                "What you're feeding it (optional, "
                                "narrative only)."
                            ),
                        },
                    },
                },
                handler=pet_feed,
            ),
            ToolDefinition(
                name="pet_play",
                description=(
                    "A play session. Biggest mood bump of the three. "
                    "Use when the user wants the pet to do something "
                    "active: 'play with my dog', 'fetch', 'zoomies'."
                ),
                parameters={"type": "object", "properties": {}},
                handler=pet_play,
            ),
            ToolDefinition(
                name="pet_speak",
                description=(
                    "Give the pet a custom one-line speech bubble. Use "
                    "when the user asks the pet to say a specific thing "
                    "('tell my cat to wish me good morning'). The bubble "
                    "shows in every surface; line is capped at 160 chars."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "line": {
                            "type": "string",
                            "description": "What the pet should say.",
                        },
                    },
                    "required": ["line"],
                },
                handler=pet_speak,
            ),
            ToolDefinition(
                name="pet_status",
                description=(
                    "Return the pet's current name, mood, label, and state. "
                    "Use when the user asks how the pet is feeling."
                ),
                parameters={"type": "object", "properties": {}},
                handler=pet_status,
            ),
            ToolDefinition(
                name="pet_remember",
                description=(
                    "Persist a fact about the pet to its per-profile / "
                    "per-pet memory file. Survives across sessions. Use "
                    "when the user shares something the pet should "
                    "remember next time: nicknames, favourite food, "
                    "personality quirks, last week's adventures."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "fact": {
                            "type": "string",
                            "description": (
                                "The fact to remember (≤500 chars). "
                                "Plain prose; will be timestamped + "
                                "appended to the pet's memory file."
                            ),
                        },
                    },
                    "required": ["fact"],
                },
                handler=pet_remember,
            ),
            ToolDefinition(
                name="pet_recall",
                description=(
                    "Read the pet's persistent memory. Optional ``query`` "
                    "filters lines by case-insensitive substring; "
                    "without it returns the most recent ``max_lines`` "
                    "(default 12). Use before answering questions about "
                    "what the user has previously told you about the pet."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Optional substring filter.",
                        },
                        "max_lines": {
                            "type": "integer",
                            "description": "Cap on returned lines (default 12).",
                        },
                    },
                },
                handler=pet_recall,
            ),
        ],
        prompt_section=section,
        workflow_examples="",
    )
