from __future__ import annotations

from typing import TYPE_CHECKING

from chika.core.profile_manager import ProfileManager
from chika.core.tool_registry import ToolDefinition

if TYPE_CHECKING:
    from chika.core.engine import ChikaEngine


def make_profile_tools(engine: ChikaEngine, profile_manager: ProfileManager) -> list[ToolDefinition]:
    """Return profile tools with a closure over the engine and profile manager."""

    async def profile_list() -> dict:
        current = engine._active_profile.name if engine._active_profile else "default"
        return {
            "profiles": profile_manager.list_profiles(),
            "current": current,
        }

    async def profile_get() -> dict:
        p = engine._active_profile
        if p is None:
            return {"name": "default", "workspace": None}
        return {
            "name": p.name,
            "workspace": p.workspace,
            "memory_path": p.memory_path,
        }

    async def profile_switch(name: str) -> dict:
        """Switch to an existing profile."""
        if not profile_manager.exists(name):
            return {
                "error": (
                    f"Profile '{name}' does not exist. "
                    "Call profile_create to create it (requires approval)."
                )
            }
        profile = profile_manager.get(name)
        if profile is None:
            return {"error": f"Profile '{name}' could not be loaded."}
        engine.switch_profile(profile)
        return {
            "switched_to": name,
            "workspace": profile.workspace,
            "memory_loaded": True,
        }

    async def profile_create(name: str, _password: str = "") -> dict:
        """Create a new profile and switch to it. Requires approval.

        _password is injected by the approval handler when the user sets a
        password in the approval dialog — the AI never provides this value.
        """
        safe_name = name.strip().lower().replace(" ", "_")
        if profile_manager.exists(safe_name):
            # Already exists — just switch (password was verified in approval flow)
            profile = profile_manager.get(safe_name)
            if profile is None:
                return {"error": f"Profile '{safe_name}' could not be loaded."}
            engine.switch_profile(profile)
            return {
                "note": f"Profile '{safe_name}' already existed",
                "switched_to": safe_name,
                "workspace": profile.workspace,
            }
        profile = profile_manager.get_or_create(safe_name)
        if _password:
            profile_manager.set_password(safe_name, _password)
        engine.switch_profile(profile)
        return {
            "created": safe_name,
            "workspace": profile.workspace,
            "switched_to": safe_name,
        }

    return [
        ToolDefinition(
            name="profile_list",
            description="List all profiles and which one is currently active.",
            parameters={"type": "object", "properties": {}},
            handler=profile_list,
        ),
        ToolDefinition(
            name="profile_get",
            description="Get the currently active profile name and workspace directory.",
            parameters={"type": "object", "properties": {}},
            handler=profile_get,
        ),
        ToolDefinition(
            name="profile_switch",
            description=(
                "Switch to an existing profile by name. "
                "First call profile_list to confirm the profile exists. "
                "Returns an error if the profile does not exist — use profile_create instead."
            ),
            requires_approval=True,
            approval_message="Chika wants to switch the active user profile.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Profile name to switch to"},
                },
                "required": ["name"],
            },
            handler=profile_switch,
        ),
        ToolDefinition(
            name="profile_create",
            description=(
                "Create a brand-new profile and switch to it. "
                "Only call this after profile_list confirms the profile does NOT exist. "
                "Requires user approval — a confirmation dialog will appear where the user "
                "can optionally set a password for the new profile."
            ),
            requires_approval=True,
            approval_message="Chika wants to create a new user profile.",
            approval_type="set_password",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "New profile name (e.g. 'tochi'). Will be lowercased.",
                    },
                },
                "required": ["name"],
            },
            handler=profile_create,
        ),
    ]


def make_set_password_tool(profile_manager: ProfileManager) -> ToolDefinition:
    """
    Returns the set_profile_password tool.

    This tool is ONLY registered when the active profile is not 'default'.
    The actual password is collected from the user via the approval dialog
    (approval_type='set_password') — the AI never provides it.
    The approval handler injects the new password before running this no-op.
    """

    async def set_profile_password() -> dict:
        # Password setting is handled entirely by the approval flow in server.py.
        # By the time this runs, the password is already persisted.
        return {"success": True, "message": "Password has been updated successfully."}

    return ToolDefinition(
        name="set_profile_password",
        description=(
            "Set, change, or remove the password for the current profile. "
            "The user will be prompted to enter the new password in a secure dialog. "
            "Leave the password blank to remove it."
        ),
        parameters={"type": "object", "properties": {}},
        handler=set_profile_password,
        requires_approval=True,
        approval_message="Set password for current profile",
        approval_type="set_password",
    )
