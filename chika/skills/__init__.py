"""Skills package — drop-in auto-discovery.

A skill is a folder under ``chika/skills/<name>_skill/`` whose
``__init__.py`` exports:

* ``SKILL_NAME``   — string. Canonical name (e.g. ``"git"``,
                     ``"plan"``). Must match the ``Skill(name=...)``
                     value the skill returns.
* ``build_skill(context)`` — entry point. Receives a
                     :class:`SkillBuildContext`; returns a
                     :class:`Skill`. See ``_context.py`` docstring
                     for the contract.
* ``SKILL_PHASE``  — *optional*. ``"pre_engine"`` (default) or
                     ``"post_engine"``. Use ``"post_engine"`` only
                     when the skill's tool needs to reach into the
                     ``ChikaEngine`` itself before any agent turn
                     runs (the question skill is the only example
                     today, and it uses lazy getters instead — so
                     in practice nobody needs this).

Adding a new skill = drop the folder. The session manager picks it
up, the settings UI picks it up, the skill summary pipeline picks it
up. No imports to maintain elsewhere.

Why this is here, not duck-typed
--------------------------------

Auto-discovery means the session manager doesn't know which skills
exist until it walks the package — but tests, settings validation,
and the API still need a way to *enumerate* skills. This module owns
that enumeration so every other surface uses the same source of
truth.

Functions
---------
``iter_skill_modules() -> Iterator[ModuleType]``
    Yield every imported skill subpackage that exports both
    ``SKILL_NAME`` and ``build_skill``.

``list_known_skill_names() -> tuple[str, ...]``
    Sorted tuple of every skill name. Cached after first call.

``known_skill_names_set() -> frozenset[str]``
    Frozenset shape for membership tests.

``get_skill_module(name)``
    Look up a skill module by its ``SKILL_NAME``. Returns ``None``
    if no such skill is shipped.
"""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from chika.skills._context import (
    PHASE_POST_ENGINE,
    PHASE_PRE_ENGINE,
    SkillBuildContext,
)

__all__ = [
    "SkillBuildContext",
    "PHASE_PRE_ENGINE",
    "PHASE_POST_ENGINE",
    "iter_skill_modules",
    "list_known_skill_names",
    "known_skill_names_set",
    "get_skill_module",
    "iter_skill_routers",
    "iter_skill_cli",
    "iter_skill_settings",
    "iter_skill_websocket_registrars",
    "iter_skill_ui_manifests",
    "skill_folder",
    "fire_setting_changed",
    "fire_env_changed",
    "fire_session_linked",
    "iter_skill_intent_cases",
    "render_intent_examples_block",
    "iter_skill_events",
    "iter_skill_routed_events",
]


def _is_valid_skill_module(mod: ModuleType) -> bool:
    """Return True iff ``mod`` exports the discovery contract."""
    name = getattr(mod, "SKILL_NAME", None)
    builder = getattr(mod, "build_skill", None)
    return (
        isinstance(name, str)
        and name.strip() != ""
        and callable(builder)
    )


@lru_cache(maxsize=1)
def _discover() -> tuple[ModuleType, ...]:
    """Walk ``chika/skills/*`` and import every subpackage that
    declares ``SKILL_NAME`` + ``build_skill``. Failures are silently
    skipped so a missing optional dependency doesn't tank the whole
    session boot — affected skills just don't appear in the registry.
    Cached for the process lifetime."""
    found: list[ModuleType] = []
    pkg_path = Path(__file__).parent
    for module_info in pkgutil.iter_modules([str(pkg_path)]):
        if not module_info.ispkg:
            # Top-level helper modules (``summarizer.py``, ``_context.py``)
            # never declare the contract — skip without importing them
            # in the discovery walk.
            continue
        if module_info.name.startswith("_"):
            # Private subpackages (none today, but reserved).
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{module_info.name}")
        except Exception:
            continue
        if _is_valid_skill_module(mod):
            found.append(mod)
    return tuple(found)


def iter_skill_modules() -> Iterator[ModuleType]:
    """Yield every shipped skill module in discovery order. Order is
    the alphabetical filesystem order of the subpackages — stable
    enough that tests can assert on it without flaking."""
    yield from _discover()


@lru_cache(maxsize=1)
def list_known_skill_names() -> tuple[str, ...]:
    """Return every shipped skill's canonical name, sorted."""
    return tuple(sorted({mod.SKILL_NAME for mod in _discover()}))


def known_skill_names_set() -> frozenset[str]:
    """Frozenset shape of :func:`list_known_skill_names`."""
    return frozenset(list_known_skill_names())


def get_skill_module(name: str) -> ModuleType | None:
    """Look up a skill module by ``SKILL_NAME``. Useful when a caller
    knows the name (e.g. from a settings list) and wants the module's
    other exports (constants, helper functions). Returns ``None`` if
    no shipped skill matches."""
    for mod in _discover():
        if getattr(mod, "SKILL_NAME", None) == name:
            return mod
    return None


def skill_folder(name: str) -> Path | None:
    """Return the absolute folder path for a skill, or ``None`` if
    that skill isn't shipped. Used by the asset endpoint to safely
    resolve ``ui/<file>`` references inside a skill folder."""
    mod = get_skill_module(name)
    if not mod:
        return None
    spec = getattr(mod, "__file__", None)
    if not spec:
        return None
    return Path(spec).parent


# ── Iterators that pick up the optional contract pieces ───────────────


def iter_skill_routers() -> Iterator[tuple[str, object]]:
    """Yield ``(skill_name, router)`` for every skill that exports
    ``register_routes()`` and returns a non-None value. The server
    walks this at boot to mount per-skill REST routes without
    importing each skill by name."""
    for mod in _discover():
        register = getattr(mod, "register_routes", None)
        if not callable(register):
            continue
        try:
            router = register()
        except Exception:
            continue
        if router is not None:
            yield mod.SKILL_NAME, router


def iter_skill_websocket_registrars() -> Iterator[tuple[str, object]]:
    """Yield ``(skill_name, register_callable)`` for every skill that
    exports ``register_websocket(app)``. Server calls each one with
    its FastAPI app so the skill can attach its own
    ``@app.websocket(...)`` endpoints."""
    for mod in _discover():
        register = getattr(mod, "register_websocket", None)
        if callable(register):
            yield mod.SKILL_NAME, register


def iter_skill_cli() -> Iterator[tuple[str, dict]]:
    """Yield ``(skill_name, dispatch_table)`` for every skill that
    exports ``register_cli()``. Dispatch table shape::

        {"slash": {<name>: handler}, "argv": {<name>: subparser_factory}}
    """
    for mod in _discover():
        register = getattr(mod, "register_cli", None)
        if not callable(register):
            continue
        try:
            table = register()
        except Exception:
            continue
        if isinstance(table, dict) and table:
            yield mod.SKILL_NAME, table


def iter_skill_settings() -> Iterator[tuple[str, dict]]:
    """Yield ``(skill_name, settings_dict)`` for every skill that
    exports ``SKILL_SETTINGS``. Settings_store walks this at init to
    seed defaults + register validators without naming each skill."""
    for mod in _discover():
        spec = getattr(mod, "SKILL_SETTINGS", None)
        if isinstance(spec, dict) and spec:
            yield mod.SKILL_NAME, spec


def iter_skill_ui_manifests() -> Iterator[tuple[str, dict]]:
    """Yield ``(skill_name, manifest)`` for every skill that exports
    ``SKILL_UI``. The frontend ``/api/skills/ui`` endpoint enumerates
    these so SettingsModal + extension popup can render dynamic tabs
    without hardcoding skill names."""
    for mod in _discover():
        manifest = getattr(mod, "SKILL_UI", None)
        if isinstance(manifest, dict) and manifest:
            yield mod.SKILL_NAME, manifest


# ── Subscriber bus — settings + env hot-reload events ─────────────────
#
# Skills used to be coupled to settings_store + the env router via
# direct imports (settings_store called oauth.reload_from_env on a
# share-flag flip; env router did the same on env-var change). Both
# now go through these fan-out helpers — settings_store and env
# router fire the events; skills' optional ``on_setting_changed`` /
# ``on_env_changed`` callbacks receive them. Failures in one skill
# don't block the others (best-effort).


def fire_setting_changed(key: str, new_value, old_value) -> None:
    """Notify every skill that a setting changed. Each skill's
    ``on_setting_changed(key, new_value, old_value)`` callback runs;
    exceptions are caught and ignored to keep settings updates
    atomic."""
    for mod in _discover():
        cb = getattr(mod, "on_setting_changed", None)
        if not callable(cb):
            continue
        try:
            cb(key, new_value, old_value)
        except Exception:
            continue


def fire_env_changed(name: str, new_value, old_value) -> None:
    """Notify every skill that an env var changed via /api/env. Each
    skill's ``on_env_changed(name, new_value, old_value)`` runs."""
    for mod in _discover():
        cb = getattr(mod, "on_env_changed", None)
        if not callable(cb):
            continue
        try:
            cb(name, new_value, old_value)
        except Exception:
            continue


# Default text shown for each intent dimension's positive/negative
# section header in the rendered system-prompt block. New dimensions
# add an entry here; missing dimensions render with a generic header.
_INTENT_HEADERS: dict[str, tuple[str, str, str]] = {
    # dimension → (block_title, positive_header, negative_header)
    "plan": (
        "Planning calibration (from shipped skills)",
        "**Make a plan first** for prompts like these:",
        "**Skip planning** for prompts like these:",
    ),
    "ask": (
        "Ask-user calibration (from shipped skills)",
        "**Ask the user a multiple-choice question** when the prompt is vague, like:",
        "**Don't ask — just proceed** when the prompt is specific enough, like:",
    ),
    "skill_load": (
        "Skill-load calibration (when to read the full SKILL.md)",
        "**Load the full SKILL.md** for non-trivial work, like:",
        "**Skip the full doc** — the summary in this prompt covers it:",
    ),
    "memory": (
        "Memory-persist calibration",
        "**Write to memory** when the user states a durable preference:",
        "**Don't pollute memory** — these are conversational:",
    ),
    "approval": (
        "Approval calibration (require user confirmation?)",
        "**Require approval** before running these:",
        "**Auto-approve** these read-only / no-side-effect calls:",
    ),
    "research": (
        "Research calibration (ground in a real fetch first?)",
        "**Run web_fetch / verify_url first** for these claim-shaped prompts:",
        "**Answer from training-data knowledge** for these:",
    ),
    "refuse": (
        "Refusal calibration (decline when out-of-scope/unsafe)",
        "**Decline** these requests:",
        "**Proceed** with these:",
    ),
}


def render_intent_examples_block(
    dimension: str = "plan",
    *,
    per_skill_positive: int = 1,
    per_skill_negative: int = 1,
    max_total: int = 24,
) -> str:
    """Render a markdown block of "do X vs don't" examples sourced
    from every skill's ``INTENT_CASES`` for the given dimension.
    Goes into the system prompt so the agent has concrete,
    domain-specific calibration.

    Default dimension is ``"plan"`` (when to call ``plan_set``).
    Pass ``"ask"`` for ``ask_user`` calibration (vague vs specific).
    New dimensions are accepted; their header text falls back to a
    generic "POSITIVE / NEGATIVE" if not registered in
    ``_INTENT_HEADERS``.

    Threshold knobs:

    * ``per_skill_positive`` — how many positive cases to take per
      skill (default 1).
    * ``per_skill_negative`` — same for negatives.
    * ``max_total`` — hard cap on the SUM across all skills. Once we
      hit this, additional skills' cases drop. Default 24, sized so
      a 12-skill install at 1 positive + 1 negative each fits.

    Empty string when no skill contributes for this dimension —
    prompt builder skips empty contributions, so the agent never
    sees a "no examples" header.
    """
    positive_lines: list[str] = []
    negative_lines: list[str] = []
    total = 0
    for _name, cases in iter_skill_intent_cases(dimension):
        pos = list(cases.get("positive") or [])
        neg = list(cases.get("negative") or [])
        for ex in pos[:per_skill_positive]:
            if total >= max_total:
                break
            positive_lines.append(f"- {ex}")
            total += 1
        for ex in neg[:per_skill_negative]:
            if total >= max_total:
                break
            negative_lines.append(f"- {ex}")
            total += 1
        if total >= max_total:
            break
    if not positive_lines and not negative_lines:
        return ""
    title, pos_header, neg_header = _INTENT_HEADERS.get(
        dimension,
        (f"{dimension.title()} calibration (from shipped skills)",
         f"**{dimension.title()} positive** examples:",
         f"**{dimension.title()} negative** examples:"),
    )
    out: list[str] = [f"## {title}", ""]
    if positive_lines:
        out.append(pos_header)
        out.extend(positive_lines)
        out.append("")
    if negative_lines:
        out.append(neg_header)
        out.extend(negative_lines)
    return "\n".join(out).rstrip()


def iter_skill_intent_cases(dimension: str = "plan") -> Iterator[tuple[str, dict]]:
    """Yield ``(skill_name, cases)`` for every skill that exports
    ``INTENT_CASES`` for the given dimension.

    ``INTENT_CASES`` shape (every dimension lives under its own key)::

        INTENT_CASES = {
            "plan": {
                "positive": [...],   # should fire ``plan_set``
                "negative": [...],   # should NOT fire
            },
            "ask": {
                "positive": [...],   # vague — should ``ask_user``
                "negative": [...],   # specific enough — proceed
            },
            # Other dimensions: "memory", "approval", "research",
            # "skill_load", "refuse", "clarify". Skills opt in to
            # whichever dimensions are relevant — pet might supply
            # ``memory`` only, shell might supply ``approval`` only.
        }

    Skills contribute their own cases for two purposes:
      1. The central tests parametrise over the union, so coverage
         grows automatically with every new skill.
      2. ``render_intent_examples_block`` samples a few into the
         system prompt for runtime calibration.

    All strings stay INSIDE the skill folder — preserves the strict
    skill-isolation contract."""
    for mod in _discover():
        cases = getattr(mod, "INTENT_CASES", None)
        if not isinstance(cases, dict) or not cases:
            continue
        # ``cases[dimension]`` must be a ``{"positive": [...], "negative": [...]}``
        # dict. Skills that don't supply this dimension simply don't
        # contribute. Flat top-level positive/negative shapes are NOT
        # honoured — every dimension lives under its own key for
        # consistency and forward extensibility.
        block = cases.get(dimension)
        if isinstance(block, dict) and block:
            yield mod.SKILL_NAME, block


def iter_skill_events() -> Iterator[tuple[str, object]]:
    """Yield ``(event_name, pydantic_model)`` for every event a skill
    contributes via its ``SKILL_EVENTS`` dict.

    Shape::

        # chika/skills/<name>_skill/__init__.py
        SKILL_EVENTS = {
            "spotify_auth_changed": SpotifyAuthChangedEvent,
        }

    ``api/models.py`` walks this at module import time to populate
    ``_TYPED_MODELS`` so ``validate_event`` accepts skill events
    without naming them in core. ``api/event_routing.py`` walks it
    via :func:`iter_skill_routed_events` to extend the FRONTEND /
    EXTENSION sets.
    """
    for mod in _discover():
        events = getattr(mod, "SKILL_EVENTS", None)
        if not isinstance(events, dict):
            continue
        for name, model in events.items():
            if isinstance(name, str) and name.strip():
                yield name, model


def iter_skill_routed_events() -> Iterator[tuple[str, str, frozenset[str]]]:
    """Yield ``(skill_name, event_name, surfaces)`` for every event
    a skill contributes via ``SKILL_EVENT_ROUTING``. ``surfaces`` is a
    frozenset of strings drawn from {"cli", "frontend", "extension"}.

    Shape::

        SKILL_EVENT_ROUTING = {
            "spotify_auth_changed": {"cli", "frontend", "extension"},
        }

    ``api/event_routing.py`` walks this at import time to extend its
    static sets so ``EXTENSION_EVENTS`` no longer hardcodes a
    spotify-specific entry.
    """
    for mod in _discover():
        routing = getattr(mod, "SKILL_EVENT_ROUTING", None)
        if not isinstance(routing, dict):
            continue
        for event_name, surfaces in routing.items():
            if isinstance(event_name, str) and event_name.strip():
                if isinstance(surfaces, (set, frozenset, list, tuple)):
                    yield mod.SKILL_NAME, event_name, frozenset(surfaces)


async def fire_session_linked(engine, session_id: str) -> None:
    """Notify every skill that a frontend session has been linked to a
    chat / engine. Async because handlers may push WebSocket events.
    Each skill's optional ``on_session_linked(engine, session_id)``
    coroutine runs; exceptions are swallowed so a single broken skill
    doesn't kill the WS connect."""
    for mod in _discover():
        cb = getattr(mod, "on_session_linked", None)
        if not callable(cb):
            continue
        try:
            result = cb(engine, session_id)
            if hasattr(result, "__await__"):
                await result
        except Exception:
            continue
