"""
SessionManager — creates and maintains one ChikaEngine per session_id.
Each session gets its own history, variable store, and memory file.
"""
from __future__ import annotations

import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import secrets as _secrets
from pathlib import Path
from typing import Any
from collections.abc import Callable

from chika.core.chat_store import ChatStore
from chika.core.device_store import DeviceStore
from chika.core.engine import ChikaEngine
from chika.core.memory_manager import MemoryManager
from chika.core.prompt_builder import PromptBuilder
from chika.core.skill_registry import SkillRegistry
from chika.core.tool_registry import ToolRegistry
from chika.core.variable_store import VariableStore

# Sessions directory — lives outside source tree so uvicorn --reload ignores it
_SESSIONS_DIR = Path(__file__).parent.parent / "data" / "sessions"
_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# Profiles directory — lives under data/ alongside sessions/ and devices/ so
# all persistent state is under one folder (easier to gitignore, back up, etc.)
_PROFILES_DIR = Path(__file__).parent.parent / "data" / "profiles"
_PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def _get_disabled_skills() -> list[str]:
    """Read the current ``skills_disabled`` list from settings, fail-soft.

    Wrapped so a missing/corrupt settings file doesn't crash engine
    construction — we just register every skill (the safe default).
    """
    try:
        from api import settings_store
        return list(settings_store.get("skills_disabled", []) or [])
    except Exception:
        return []
import config
from chika.core.profile_manager import ProfileManager
# Skills are NOT imported individually here. The session manager walks
# ``chika/skills/*_skill/`` at build time via
# :func:`chika.skills.iter_skill_modules` and calls each module's
# ``build_skill(context)`` entry point. Adding a new skill is a
# drop-in: create the folder, declare ``SKILL_NAME`` + ``build_skill``,
# and the engine picks it up automatically. See
# ``chika/skills/_context.py`` for the contract.
from chika.skills import (
    PHASE_POST_ENGINE,
    SkillBuildContext,
    iter_skill_modules,
)
from chika.tools.apps_tool import APP_OPEN_TOOL
from chika.tools.file_tools import FILE_TOOLS
from chika.tools.live_server_tool import LIVE_SERVER_TOOL
from chika.tools.memory_tool import make_memory_tools
from chika.tools.profile_tools import make_profile_tools, make_set_password_tool
from chika.tools.python_run_tool import PYTHON_RUN_TOOL
from chika.tools.skill_doc_tool import SKILL_QUERY_TOOL, make_skill_doc_tool
from chika.tools.variable_tools import make_variable_tools
from chika.tools.wait_tool import WAIT_TOOL
from chika.tools.web_fetch_tool import WEB_FETCH_TOOLS


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, ChikaEngine] = {}
        self._profile_manager = ProfileManager(_PROFILES_DIR)
        self._chat_store = ChatStore(_PROFILES_DIR)
        _DATA_DIR = Path(__file__).parent.parent / "data"
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._device_store = DeviceStore(_DATA_DIR)

    def get_or_create(self, session_id: str) -> ChikaEngine:
        if session_id not in self._sessions:
            engine = self._build_engine(session_id)
            # Try to restore from persistent storage (e.g. after server reload)
            profile_name = self._chat_store.find_session_profile(session_id)
            if profile_name:
                chat_data = self._chat_store.load(profile_name, session_id)
                if chat_data and chat_data.get("messages"):
                    engine._history = chat_data["messages"]
                    engine._title = chat_data.get("title", "")
                    engine._needs_restore_event = True
                    # Restore the profile context
                    profile = self._profile_manager.get(profile_name)
                    if profile:
                        engine.switch_profile(profile)
            self._sessions[session_id] = engine
        return self._sessions[session_id]

    def get(self, session_id: str) -> ChikaEngine | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[dict]:
        result = []
        for sid, engine in self._sessions.items():
            result.append({
                "session_id": sid,
                "message_count": len(engine._history),
                "variable_count": len(engine._vars.all()),
            })
        return result

    def reload_skills(self) -> dict[str, object]:
        """Apply the current ``skills_disabled`` setting to every active engine.

        For each engine, compares the registered skill set against the
        target (``builders.keys() - disabled``) and:

          - **Unregisters** any skill that's now disabled (its tools
            disappear from the next turn's tool list).
          - **Re-registers** any skill that's now enabled (rebuilds via
            the cached builder thunk).

        No-op for skills that haven't changed state. Soft-fails per
        engine — a single broken builder doesn't stop the rest.

        Returns ``{disabled, enabled, sessions, errors}``.
        """
        target_disabled = set(_get_disabled_skills())
        errors: list[str] = []
        affected_sessions = 0

        for sid, engine in self._sessions.items():
            builders = getattr(engine, "_skill_builders", None)
            if not builders:
                continue
            registry = engine._skills  # SkillRegistry instance
            currently_registered = set(registry._skills.keys())
            target_registered = set(builders.keys()) - target_disabled

            to_remove = currently_registered & target_disabled
            to_add    = target_registered - currently_registered

            if not to_remove and not to_add:
                continue
            affected_sessions += 1

            for name in to_remove:
                try:
                    registry.unregister(name)
                except Exception as exc:
                    errors.append(f"{sid}.unregister({name}): {exc}")
            for name in to_add:
                try:
                    registry.register(builders[name]())
                except Exception as exc:
                    errors.append(f"{sid}.register({name}): {exc}")

        return {
            "disabled":          sorted(target_disabled),
            "sessions_affected": affected_sessions,
            "sessions_total":    len(self._sessions),
            "errors":            errors,
        }

    def reload_clients(self) -> dict[str, object]:
        """Fan reload_client out to every active engine.

        Returns a summary the caller can surface to the user:

            {
              "provider": "openai",
              "model":    "gpt-4o",
              "sessions": 3,
              "changed":  true,
              "errors":   [],
            }

        If any individual engine fails to rebuild (e.g. missing API
        key), it's caught and reported in ``errors`` — other engines
        still get the new client.
        """
        # Always refresh the global config first — even if no engines
        # are active, future engines built lazily by get_or_create
        # need to see the fresh values.
        import config as _config  # type: ignore[import-not-found]
        _config.reload_from_env()

        if not self._sessions:
            cfg = _config.get_provider_config()
            return {
                "provider": cfg.provider, "model": cfg.model,
                "sessions": 0, "changed": True, "errors": [],
            }

        provider = ""
        model = ""
        any_changed = False
        errors: list[str] = []
        for sid, engine in self._sessions.items():
            try:
                result = engine.reload_client()
                provider = result["provider"]
                model    = result["model"]
                if result["changed"] == "true":
                    any_changed = True
            except Exception as exc:
                errors.append(f"{sid}: {exc}")
        return {
            "provider": provider, "model": model,
            "sessions": len(self._sessions),
            "changed":  any_changed, "errors": errors,
        }

    def get_device_session(self, device_id: str) -> tuple[ChikaEngine, str]:
        """Get the current session for a device, creating one if it doesn't exist."""
        session_id = self._device_store.get_session(device_id)
        if not session_id:
            session_id = "sess_" + _secrets.token_hex(8)
            self._device_store.set_session(device_id, session_id)
        engine = self.get_or_create(session_id)
        return engine, session_id

    def new_chat_for_device(self, device_id: str) -> tuple[ChikaEngine, str]:
        """Create a fresh chat session for a device and set it as current."""
        session_id = "sess_" + _secrets.token_hex(8)
        self._device_store.set_session(device_id, session_id)
        engine = self.get_or_create(session_id)
        return engine, session_id

    def switch_device_chat(self, device_id: str, chat_id: str) -> tuple[ChikaEngine, str]:
        """Switch a device to an existing chat session."""
        self._device_store.set_session(device_id, chat_id)
        engine = self.get_or_create(chat_id)
        return engine, chat_id

    def _build_engine(self, session_id: str) -> ChikaEngine:
        tool_registry = ToolRegistry()
        variable_store = VariableStore()

        # Start on the default profile
        default_profile = self._profile_manager.get_or_create("default")
        memory_manager = MemoryManager(
            path=default_profile.memory_path,
            max_tokens=config.MAX_MEMORY_TOKENS,
        )

        prompt_builder = PromptBuilder()
        skill_registry = SkillRegistry(tool_registry, memory_manager, prompt_builder)

        # Resolve the disabled set once up front so every skill registration
        # below honours it.
        disabled = set(_get_disabled_skills())

        # Register built-in tools (NOT skills — these live in
        # chika/tools/ rather than chika/skills/).
        tool_registry.register(APP_OPEN_TOOL)
        tool_registry.register(LIVE_SERVER_TOOL)
        tool_registry.register(WAIT_TOOL)
        tool_registry.register(PYTHON_RUN_TOOL)
        for t in FILE_TOOLS:
            tool_registry.register(t)
        for t in WEB_FETCH_TOOLS:
            tool_registry.register(t)
        # Memory tools get registered AFTER the engine is built — they need
        # to look up engine._memory dynamically so profile switches take
        # effect. (Closure-bound memory managers were being written to the
        # wrong profile after switch_profile swapped _memory.)
        for t in make_variable_tools(variable_store):
            tool_registry.register(t)

        # ── Auto-discovery skill registration ─────────────────────────
        #
        # The session manager doesn't know which skills exist until it
        # walks ``chika/skills/*_skill/`` via :func:`iter_skill_modules`.
        # Each module exports a ``build_skill(context)`` entry point —
        # the loop below calls it with a SkillBuildContext whose
        # getters resolve to the engine's live state once it exists.
        #
        # Every skill is wrapped in a "builder" thunk on
        # ``engine._skill_builders`` so :meth:`reload_skills` can rebuild
        # any one of them later without re-running the whole engine
        # construction path — that's how the Settings UI hot-reloads
        # toggles without a restart.
        _engine_holder: dict[str, ChikaEngine | None] = {"engine": None}

        ctx = SkillBuildContext(
            variable_store=variable_store,
            engine_getter=lambda: _engine_holder["engine"],
            memory_getter=lambda: (
                _engine_holder["engine"]._memory
                if _engine_holder["engine"] else None
            ),
            workflow_engine_getter=lambda: (
                _engine_holder["engine"]._workflow_engine
                if _engine_holder["engine"] else None
            ),
            profile_getter=lambda: (
                _engine_holder["engine"]._active_profile.pet_id
                if _engine_holder["engine"] and _engine_holder["engine"]._active_profile
                else None
            ),
            workspace_getter=lambda: (
                _engine_holder["engine"]._active_profile.workspace
                if _engine_holder["engine"] and _engine_holder["engine"]._active_profile
                else ""
            ),
        )

        # Build the per-skill builder thunks. Each thunk closes over
        # the SAME ctx + module so reload_skills() can rebuild any one
        # in isolation. The phases dict captures pre/post engine
        # ordering — most skills are pre_engine; any skill declaring
        # ``SKILL_PHASE = "post_engine"`` registers after the engine
        # constructor runs (rare; the lazy context getters handle
        # most needs without forcing post-engine).
        skill_builders: dict[str, Callable[[], Any]] = {}
        skill_phases: dict[str, str] = {}

        def _make_builder(mod: Any, c: SkillBuildContext) -> Callable[[], Any]:
            # Wrapped in a helper so each closure captures its OWN module
            # binding — using a bare lambda inside the loop would have all
            # closures share the loop variable.
            return lambda: mod.build_skill(c)

        for mod in iter_skill_modules():
            name = mod.SKILL_NAME
            phase = getattr(mod, "SKILL_PHASE", None) or "pre_engine"
            skill_builders[name] = _make_builder(mod, ctx)
            skill_phases[name] = phase

        # First pass: register every pre-engine skill that isn't in the
        # disabled list. Post-engine skills wait until after the engine
        # constructor runs.
        for name, build in skill_builders.items():
            if name in disabled:
                continue
            if skill_phases.get(name) == PHASE_POST_ENGINE:
                continue
            skill_registry.register(build())

        engine = ChikaEngine(
            tool_registry=tool_registry,
            variable_store=variable_store,
            memory_manager=memory_manager,
            prompt_builder=prompt_builder,
            skill_registry=skill_registry,
        )
        engine.session_id = session_id
        engine._chat_store = self._chat_store
        # Stash the builder thunks on the engine so reload_skills() can
        # rebuild a previously-disabled skill without re-running the
        # whole engine construction path.
        engine._skill_builders = skill_builders  # type: ignore[attr-defined]
        # Patch the late-bound engine reference into the shared
        # ``SkillBuildContext`` getters. Skills that captured the
        # context now resolve their engine_getter / memory_getter /
        # workflow_engine_getter / profile_getter to the live engine —
        # which is how plan_reconcile reaches the LLM client and how
        # the pet skill's prompt section reads profile state.
        _engine_holder["engine"] = engine

        # Register memory tools now — they look up engine._memory dynamically
        # so a profile switch correctly redirects writes to the new profile's
        # memory file.
        for t in make_memory_tools(engine):
            tool_registry.register(t)
        # skill_load — pulls a skill's SKILL.md into context, optionally
        # condensing via a second LLM call when the doc is too long.
        tool_registry.register(make_skill_doc_tool(engine))
        # skill_query — focused BM25 retrieval over chunked SKILL.md so
        # the agent can ask targeted questions without paying for the
        # full doc each time.
        tool_registry.register(SKILL_QUERY_TOOL)
        # Second-pass registration: any skill whose SKILL_PHASE is
        # ``"post_engine"`` registers now that the engine + workflow
        # engine exist. ``ask_user`` reads
        # ``engine._workflow_engine.question_handler`` at call time.
        for name, build in skill_builders.items():
            if name in disabled:
                continue
            if skill_phases.get(name) != PHASE_POST_ENGINE:
                continue
            skill_registry.register(build())

        # All skills are registered now. Refresh the workflow engine's
        # skill-gate index so it can map every skill tool back to its skill
        # for the auto-load gate. (The engine's own constructor wired this
        # earlier but only knew about the skills registered before the
        # engine was built.)
        engine._workflow_engine.set_skill_registry(skill_registry)

        # Wire up active profile (profile tools need engine reference, so registered after)
        engine._active_profile = default_profile
        variable_store.set("profile.name", default_profile.name, description="Active profile name")
        variable_store.set("profile.workspace", default_profile.workspace, description="Profile workspace directory")

        # Chika's own repo root — used for self-modification workflows
        repo_root = str(Path(__file__).parent.parent.resolve())
        variable_store.set("chika.repo", repo_root, description="Chika's source repo root directory")

        # Platform + shell hints so the agent picks the right commands.
        # On Windows: prefer `dir /s /b`, `type`, PowerShell; avoid `ls`, `find`,
        # `grep` (not available in plain cmd.exe). On POSIX: prefer ls/find/grep.
        import platform as _platform
        import tempfile as _tempfile
        os_name = "windows" if _platform.system().lower().startswith("win") else _platform.system().lower()
        variable_store.set(
            "os",
            os_name,
            description=(
                "Host operating system. On 'windows' DO NOT use `/tmp/` — it is "
                "a file literal, not a directory. Use $tmp for temp files. "
                "git-bash is usually available so ls/find/grep/curl work, but "
                "cmd.exe-only commands (dir /s /b, type, findstr) are fine too. "
                "On 'linux'/'darwin' prefer ls/find/grep/cat, use $tmp for temp files."
            ),
        )
        # Platform-appropriate temp dir. On Windows this is something like
        # C:\Users\<user>\AppData\Local\Temp — not /tmp/.
        variable_store.set(
            "tmp",
            str(_tempfile.gettempdir()).replace("\\", "/"),
            description="Platform-appropriate temp directory for scratch files. Always use this instead of hardcoding /tmp/.",
        )

        for t in make_profile_tools(engine, self._profile_manager):
            tool_registry.register(t)

        # set_profile_password is only available when NOT on the default profile.
        # A profile-switch hook handles register/unregister on every switch.
        _pm = self._profile_manager

        def _update_password_tool(profile) -> None:
            if profile.name == "default":
                tool_registry.unregister("set_profile_password")
            elif not tool_registry.get("set_profile_password"):
                tool_registry.register(make_set_password_tool(_pm))

        engine._profile_switch_hooks.append(_update_password_tool)

        # Default profile → tool NOT registered initially (by design).
        # If a session is restored to a non-default profile the hook fires
        # via switch_profile(), so no extra registration needed here.

        return engine


# Global singleton
session_manager = SessionManager()
