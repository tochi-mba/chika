"""SkillBuildContext + the full skill drop-in contract.

Why this exists
---------------

Skills used to be wired in piecemeal: one import in
``api/session_manager.py``, another in ``api/server.py``, a routes
file under ``api/routes/``, a CLI subcommand under ``chika/_cli/``,
hardcoded settings keys in ``api/settings_store.py``, hardcoded UI
panels in ``frontend/src/components/SettingsModal.vue``. Adding a
skill required touching every layer.

The drop-in goal: **a skill is exactly one folder.** Drop
``chika/skills/myskill_skill/`` and everything plugs in
automatically — engine tools, REST routes, WebSocket endpoints, CLI
subcommands, settings keys, settings-tab UI, extension UI section.
Remove the folder and every surface above disappears with it.

The contract
------------

Every skill's ``__init__.py`` MAY export the following names.
``SKILL_NAME`` and ``build_skill`` are required; the rest are
optional, picked up if present.

REQUIRED
~~~~~~~~

``SKILL_NAME``
    String. Canonical name (e.g. ``"git"``). Must match the
    ``Skill(name=...)`` value the skill returns.

``build_skill(context: SkillBuildContext) -> Skill``
    Entry point. Returns the engine-side ``Skill`` (tools +
    prompt section + memory seeds).

OPTIONAL
~~~~~~~~

``SKILL_PHASE``
    ``"pre_engine"`` (default) or ``"post_engine"``. Use
    ``"post_engine"`` only for skills whose tool must access the
    constructed ``ChikaEngine`` immediately at registration time
    — most skills should use the lazy getters in
    :class:`SkillBuildContext` instead.

``register_routes() -> APIRouter | None``
    Return a FastAPI ``APIRouter`` to mount on the app. The
    server walks every skill at boot and calls this. Routes are
    fully owned by the skill — drop the skill, drop its routes.

``register_websocket(app: FastAPI) -> None``
    Called once at server boot. The skill registers its own
    WebSocket endpoints via ``@app.websocket(...)``. Used for
    skills with a non-trivial WS protocol (e.g. a chrome
    extension command/control channel).

``register_cli() -> dict | None``
    Return a dispatch table for slash commands and argv
    subcommands. Shape::

        {
          "slash": {
            "<name>": <handler>,            # /<name> ...
          },
          "argv": {
            "spotify": <argparse_subparser_factory>,  # chika spotify ...
          },
        }

    Either key is optional.

``SKILL_SETTINGS``
    Dict of settings keys this skill owns + their default value
    + (optional) validator callable. Mounted onto the
    settings_store so a skill toggle / config field flows through
    the same patch path as core settings::

        SKILL_SETTINGS = {
            "spotify_share_across_profiles": {
                "default": "off",
                "validate": lambda v: v in ("on", "off"),
            },
        }

``on_setting_changed(key, new_value, old_value) -> None``
    Settings-change subscriber. Settings_store fires this for
    every change so skills can invalidate caches / push events
    without the store knowing about them.

``on_env_changed(name, new_value, old_value) -> None``
    Env-var change subscriber. The env router fires this when
    ``/api/env`` patches a variable so skills can hot-reload
    credentials without restarting the server.

``SKILL_UI``
    UI manifest. Tells the frontend SettingsModal + extension
    popup how to render this skill's tab/section. Shape::

        SKILL_UI = {
            "settings_tab": {
                "label": "Spotify",
                "order": 50,                # tab sort order
                "frontend": {
                    "component": "ui/SettingsCard.vue",
                },
                "extension": {
                    "html":     "ui/section.html",
                    "js":       "ui/section.js",
                },
            },
        }

    Paths are relative to the skill folder and served via
    ``GET /api/skills/<name>/asset/<path>``. The SettingsModal
    fetches ``/api/skills/ui`` and renders the dynamic tabs.

Adding a new skill — the full procedure
---------------------------------------

1. ``mkdir chika/skills/myskill_skill/``.
2. Drop ``__init__.py`` exposing ``SKILL_NAME`` + ``build_skill``.
3. (Optional) Add ``SKILL.md`` for agent context.
4. (Optional) Add ``register_routes`` returning your
   ``APIRouter``. They mount under whatever paths your router
   declares.
5. (Optional) Add ``register_cli`` returning slash + argv handlers.
6. (Optional) Add ``SKILL_SETTINGS`` to declare your settings keys.
7. (Optional) Add ``SKILL_UI`` and drop a Vue component +
   extension HTML/JS in ``ui/`` for a settings tab.
8. Done. Reboot the server. The session manager, the API, the
   CLI dispatcher, the Settings UI, and the extension popup all
   pick it up automatically.

No edits to ``api/server.py``, ``api/session_manager.py``,
``api/settings_store.py``, or ``frontend/SettingsModal.vue``
required. Drop the folder, the system finds it.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chika.core.engine import ChikaEngine
    from chika.core.memory_manager import MemoryManager
    from chika.core.variable_store import VariableStore
    from chika.core.workflow_engine import WorkflowEngine


# Lazy getters: at the moment session_manager builds the
# context, the engine doesn't exist yet — the getters return
# ``None`` until it does, and resolve correctly afterwards. Skills
# that need engine state should ALWAYS go through the getter rather
# than capturing a value at build time.
@dataclass
class SkillBuildContext:
    """Build-time dependency bag passed to every skill's ``build_skill``.

    Skills only need the fields they actually use. The getters are
    callables (not values) so the context can be assembled before the
    engine exists — once it does, every getter resolves correctly.

    Attributes
    ----------
    variable_store
        Session-scoped variable store. Plan skill, verify skill, etc.
        write to this directly.
    engine_getter
        Returns the live ``ChikaEngine`` once it's constructed.
        ``None`` during the brief pre-construction window. Plan skill
        uses this for plan_reconcile's LLM call.
    memory_getter
        Returns the active ``MemoryManager`` (i.e. profile-aware —
        the manager swaps when the user changes profile, so callers
        must go through the getter rather than caching the reference).
    workflow_engine_getter
        Returns the engine's ``WorkflowEngine``. The question skill's
        ``ask_user`` tool reads ``question_handler`` off it at call time.
    profile_getter
        Returns the active profile's ``pet_id`` (used by skills that
        contribute a profile-aware prompt section).
    workspace_getter
        Returns the active profile's ``workspace`` directory string.
        Empty string if no profile is bound.
    """
    variable_store: VariableStore
    engine_getter: Callable[[], ChikaEngine | None]
    memory_getter: Callable[[], MemoryManager | None]
    workflow_engine_getter: Callable[[], WorkflowEngine | None]
    profile_getter: Callable[[], str | None]
    workspace_getter: Callable[[], str]

    # Free-form bag for forward compat — if a future skill needs a
    # context field that doesn't exist yet, the discoverer can stash
    # it here without breaking every existing skill's signature.
    extras: dict[str, Any] | None = None


# Phase constants — re-exported for skills that want to be explicit.
PHASE_PRE_ENGINE = "pre_engine"
PHASE_POST_ENGINE = "post_engine"
