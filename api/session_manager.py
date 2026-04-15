"""
SessionManager — creates and maintains one ChikaEngine per session_id.
Each session gets its own history, variable store, and memory file.
"""
from __future__ import annotations
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathlib import Path

from chika.core.chat_store import ChatStore
from chika.core.device_store import DeviceStore
import secrets as _secrets
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
from chika.tools.apps_tool import APP_OPEN_TOOL
from chika.tools.shell_tool import ALL_SHELL_TOOLS
from chika.tools.file_tools import FILE_TOOLS
from chika.tools.web_fetch_tool import WEB_FETCH_TOOLS
from chika.tools.memory_tool import make_memory_tools
from chika.tools.profile_tools import make_profile_tools, make_set_password_tool
from chika.tools.wait_tool import WAIT_TOOL
from chika.tools.variable_tools import make_variable_tools
from chika.core.profile_manager import ProfileManager
from chika.skills.git_skill import GIT_SKILL
from chika.skills.web_skill import WEB_SKILL
from chika.skills.spotify_skill import SPOTIFY_SKILL
from chika.skills.verify_skill import build_verify_skill
from chika.skills.plan_skill import build_plan_skill
from chika.skills.question_skill import build_question_skill
import config


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

    def get_device_session(self, device_id: str) -> tuple["ChikaEngine", str]:
        """Get the current session for a device, creating one if it doesn't exist."""
        session_id = self._device_store.get_session(device_id)
        if not session_id:
            session_id = "sess_" + _secrets.token_hex(8)
            self._device_store.set_session(device_id, session_id)
        engine = self.get_or_create(session_id)
        return engine, session_id

    def new_chat_for_device(self, device_id: str) -> tuple["ChikaEngine", str]:
        """Create a fresh chat session for a device and set it as current."""
        session_id = "sess_" + _secrets.token_hex(8)
        self._device_store.set_session(device_id, session_id)
        engine = self.get_or_create(session_id)
        return engine, session_id

    def switch_device_chat(self, device_id: str, chat_id: str) -> tuple["ChikaEngine", str]:
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

        # Register built-in tools
        for t in ALL_SHELL_TOOLS:
            tool_registry.register(t)
        tool_registry.register(APP_OPEN_TOOL)
        tool_registry.register(WAIT_TOOL)
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

        # Register skills
        skill_registry.register(GIT_SKILL)
        skill_registry.register(WEB_SKILL)
        skill_registry.register(SPOTIFY_SKILL)
        # verify_skill is session-scoped because fact_check needs a live reference
        # to this session's variable store (the $facts ledger lives there)
        skill_registry.register(build_verify_skill(variable_store))
        # plan_skill is session-scoped too — stores the live plan in $plan
        skill_registry.register(build_plan_skill(variable_store))
        # question_skill's ask_user tool looks up engine.question_handler at
        # call time — server.py sets that per-WebSocket. In CLI/test mode it
        # stays None and the tool returns a structured error instead of hanging.
        # Register after engine is built so we can pass the workflow_engine.

        engine = ChikaEngine(
            tool_registry=tool_registry,
            variable_store=variable_store,
            memory_manager=memory_manager,
            prompt_builder=prompt_builder,
            skill_registry=skill_registry,
        )
        engine.session_id = session_id
        engine._chat_store = self._chat_store

        # Register memory tools now — they look up engine._memory dynamically
        # so a profile switch correctly redirects writes to the new profile's
        # memory file.
        for t in make_memory_tools(engine):
            tool_registry.register(t)
        # Register question_skill now that the engine exists — ask_user reads
        # engine._workflow_engine.question_handler at call time.
        skill_registry.register(build_question_skill(engine._workflow_engine))

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
        import platform as _platform, tempfile as _tempfile
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
