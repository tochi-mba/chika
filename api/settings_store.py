"""
Runtime settings store — persisted to data/settings.json.

Settings survive server restarts. The env var (CHIKA_AUTONOMY) sets the
default only; once the user changes it via the API the disk value wins.

Autonomy model
--------------
``autonomy`` is a global preset: "supervised" (default = ask each tool)
or "autonomous" (default = skip all approvals).

``tool_permissions`` is a per-category override map:
  category_id → "ask" | "skip"

Effective permission for a tool:
  1. Look up the tool's category in TOOL_CATEGORY_MAP
  2. Check tool_permissions[category] if present
  3. Fall back to the autonomy-derived global default ("ask" or "skip")

Setting autonomy="autonomous" resets tool_permissions to all "skip".
Setting autonomy="supervised" resets tool_permissions to all "ask".
Patching individual tool_permissions preserves autonomy but customises
individual categories — the lock icon shows the mixed/custom state.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from chika.core._io import atomic_write

# ``CHIKA_SETTINGS_PATH`` lets a parent process redirect the persisted
# settings file:
#
#   - Tests that spawn ``python chika.py`` as a subprocess use this
#     because the in-process monkeypatch in conftest can't reach a
#     child Python interpreter (without it, subprocess slash commands
#     like ``/auto-continue off`` would write to the real committed
#     ``data/settings.json``).
#   - The Windows installer's ``chika.cmd`` shim sets it to
#     ``%USERPROFILE%\.chika\data\settings.json`` so user settings
#     survive an Add/Remove Programs uninstall — the install dir gets
#     wiped on uninstall but ``~/.chika/`` is left alone.
#
# ``CHIKA_DATA_DIR`` is the broader equivalent for *any* future state
# file we add. If set, files default to ``$CHIKA_DATA_DIR/<name>``;
# ``CHIKA_SETTINGS_PATH`` (when also set) wins over it for settings
# specifically. We don't currently consume CHIKA_DATA_DIR for settings
# because the installer's chika.cmd already sets the more specific
# CHIKA_SETTINGS_PATH — but exposing it as a published env var means
# future state stores can opt into the same uninstall-survives pattern
# without each one inventing its own env var.
_SETTINGS_PATH = Path(
    os.environ.get("CHIKA_SETTINGS_PATH")
    or (
        f"{os.environ['CHIKA_DATA_DIR']}/settings.json"
        if os.environ.get("CHIKA_DATA_DIR")
        else "data/settings.json"
    )
)

_VALID_AUTONOMY = {"supervised", "autonomous"}
_VALID_PERMISSION = {"ask", "skip"}
_VALID_PET_SPEECH = {"on", "off"}
_VALID_AUTO_CONTINUE = {"on", "off"}
_VALID_STATE_VERBS = {"on", "off"}
_VALID_AUTO_UPDATE = {"on", "off"}

# Defaults for the pet companion. Each profile picks its own pet (handled by
# ProfileManager); these settings control whether the pet says LLM-generated
# quips and how many tokens each quip is allowed.
_PET_DEFAULTS = {
    "pet_speech":        "off",
    "pet_speech_tokens": 40,
}

# Auto-continuation: when the assistant's reply ends with a "next I'll …"
# style promise (and isn't asking a question), the engine fires another
# turn with the synthetic prompt "continue" so the agent actually does the
# next thing instead of stopping mid-thought. Hard-capped to prevent
# runaway loops.
_AUTO_CONTINUE_DEFAULTS = {
    "auto_continue":     "on",
    "auto_continue_max": 10,   # bumped from 5 — most multi-step plans need ≥7
}

# State indicator: the inline ``◣ ▲ ◢   Thinking… 2.3s`` activity row
# shown while the agent is between user input and first signal of life.
# When ``state_verbs == "on"`` the engine fires a fire-and-forget LLM
# call per turn asking for context-aware verbs ("Investigating",
# "Sketching", etc.); when "off" the indicator cycles a static set.
_STATE_DEFAULTS = {
    "state_verbs":        "on",
    "state_verbs_tokens": 80,
}

# Auto-update: on startup, the CLI does a fire-and-forget check
# against the upstream remote (GitHub for git clones, PyPI for pip
# installs). When ``auto_update == "on"`` AND the new commit's CI is
# green, we silently apply the update (``git pull`` + editable
# refresh) and surface a one-line "restart to apply" notice. We never
# auto-roll the user onto a red commit, and the network check is
# throttled to once an hour to respect GitHub's unauthed rate limit.
_AUTO_UPDATE_DEFAULTS = {
    "auto_update": "on",
}

# Spotify integration: three modes, in resolution order.
#
#   1. Per-profile override (highest precedence)
#      ``spotify_profile_overrides[<profile>] = true`` → that profile
#      uses its own bucket, even when global sharing is on. Useful for
#      "everyone on this machine shares my Spotify, but my work
#      profile uses the team account."
#
#   2. Global share
#      ``spotify_share_across_profiles = "on"`` → every profile reads
#      the special ``_shared`` bucket. One connection, every profile.
#
#   3. Per-profile (default)
#      Each profile gets its own bucket. Switching profiles switches
#      which Spotify account is active.
#
# Switching modes never migrates tokens — each bucket retains whatever
# was last connected to it, so toggling preserves prior connections.
_SPOTIFY_DEFAULTS = {
    "spotify_share_across_profiles": "off",
    "spotify_profile_overrides": {},
}
_VALID_SPOTIFY_SHARING = {"on", "off"}

# ── Category definitions ──────────────────────────────────────────────────────

CATEGORIES: dict[str, str] = {
    "shell":         "Shell commands (exec, background)",
    "file_write":    "File writes & deletes",
    "browser_write": "Browser actions (navigate, click, fill, scroll)",
    "browser_read":  "Browser reads (screenshot, DOM, tab info)",
    "memory":        "Memory updates (persist, forget)",
    "profile":       "Profile management (switch, create, password)",
    "git":           "Git operations (commit, push, PR)",
    "network":       "Network requests (web fetch, search)",
}

# Maps tool name → category id.  Tools not listed fall back to global default.
TOOL_CATEGORY_MAP: dict[str, str] = {
    # Shell
    "shell_exec":           "shell",
    "bg_shell_exec":        "shell",
    "shell_kill":           "shell",
    "python_run":           "shell",
    # File writes
    "file_write":           "file_write",
    "file_append":          "file_write",
    "file_edit_lines":      "file_write",
    "file_replace":         "file_write",
    # Browser writes
    "browser_navigate":     "browser_write",
    "browser_click":        "browser_write",
    "browser_fill_input":   "browser_write",
    "browser_open_tab":     "browser_write",
    "browser_close_tab":    "browser_write",
    "browser_scroll":       "browser_write",
    "browser_run_research": "browser_write",
    "browser_watch_element":"browser_write",
    # Browser reads
    "browser_screenshot":   "browser_read",
    "browser_get_active_tab": "browser_read",
    "browser_get_dom":      "browser_read",
    "browser_get_element":  "browser_read",
    "browser_get_page_var": "browser_read",
    "browser_get_tabs":     "browser_read",
    "browser_get_text":     "browser_read",
    "browser_list_watches": "browser_read",
    "browser_switch_tab":   "browser_read",
    "browser_unwatch":      "browser_read",
    # Memory
    "memory_persist":       "memory",
    "memory_forget":        "memory",
    "memory_append":        "memory",
    # Profile
    "profile_create":       "profile",
    "profile_switch":       "profile",
    "set_profile_password": "profile",
    # Git
    "git_commit":           "git",
    "git_push":             "git",
    "git_pull":             "git",
    "git_pr_create":        "git",
    "git_pr_merge":         "git",
    "git_checkout":         "git",
    "git_branch":           "git",
    # Network
    "web_fetch":            "network",
    "web_search":           "network",
    "verify_url":           "network",
    "verify":               "network",
    "web_head":             "network",
}

_settings: dict = {}


# ── Init ──────────────────────────────────────────────────────────────────────

def init(defaults: dict) -> None:
    """Load from disk, then fill in missing keys from defaults."""
    global _settings
    if _SETTINGS_PATH.exists():
        try:
            _settings = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            _settings = {}
    changed = False
    for k, v in defaults.items():
        if k not in _settings:
            _settings[k] = v
            changed = True
    if "tool_permissions" not in _settings:
        _settings["tool_permissions"] = {}
        changed = True
    for k, v in _PET_DEFAULTS.items():
        if k not in _settings:
            _settings[k] = v
            changed = True
    for k, v in _AUTO_CONTINUE_DEFAULTS.items():
        if k not in _settings:
            _settings[k] = v
            changed = True
    for k, v in _STATE_DEFAULTS.items():
        if k not in _settings:
            _settings[k] = v
            changed = True
    for k, v in _AUTO_UPDATE_DEFAULTS.items():
        if k not in _settings:
            _settings[k] = v
            changed = True
    for k, v in _SPOTIFY_DEFAULTS.items():
        if k not in _settings:
            _settings[k] = v
            changed = True
    if changed:
        _save()


# ── Read ──────────────────────────────────────────────────────────────────────

def get(key: str, default=None):
    return _settings.get(key, default)


def get_tool_permission(tool: str) -> str:
    """Return "ask" or "skip" for a given tool name.

    Checks the explicit tool_permissions override first, then falls back
    to the autonomy-derived global default.
    """
    category = TOOL_CATEGORY_MAP.get(tool)
    explicit = _settings.get("tool_permissions", {})
    if category and category in explicit:
        return explicit[category]
    # Global default: autonomous → skip, supervised → ask
    autonomy = _settings.get("autonomy", "supervised")
    return "skip" if autonomy == "autonomous" else "ask"


def all_settings() -> dict:
    return dict(_settings)


# ── Write ─────────────────────────────────────────────────────────────────────

def update(patch: dict) -> dict:
    """Validate and apply a partial settings update. Returns full settings."""
    if "autonomy" in patch:
        val = patch["autonomy"]
        if val not in _VALID_AUTONOMY:
            raise ValueError(
                f"Invalid autonomy value: {val!r}. Must be one of {sorted(_VALID_AUTONOMY)}"
            )
        _settings["autonomy"] = val
        # Reset per-category overrides so the new preset takes full effect.
        _settings["tool_permissions"] = {}

    if "tool_permissions" in patch:
        perms = patch["tool_permissions"]
        if not isinstance(perms, dict):
            raise ValueError("tool_permissions must be a dict")
        for cat, perm in perms.items():
            if cat not in CATEGORIES:
                raise ValueError(f"Unknown category: {cat!r}. Valid: {sorted(CATEGORIES)}")
            if perm not in _VALID_PERMISSION:
                raise ValueError(f"Invalid permission {perm!r} for {cat!r}. Use 'ask' or 'skip'.")
        _settings.setdefault("tool_permissions", {}).update(perms)

    if "pet_speech" in patch:
        val = patch["pet_speech"]
        if val not in _VALID_PET_SPEECH:
            raise ValueError(
                f"Invalid pet_speech value: {val!r}. Use 'on' or 'off'."
            )
        _settings["pet_speech"] = val

    if "pet_speech_tokens" in patch:
        val = patch["pet_speech_tokens"]
        if not isinstance(val, int) or val < 8 or val > 200:
            raise ValueError("pet_speech_tokens must be an int in [8, 200]")
        _settings["pet_speech_tokens"] = val

    if "auto_continue" in patch:
        val = patch["auto_continue"]
        if val not in _VALID_AUTO_CONTINUE:
            raise ValueError(
                f"Invalid auto_continue: {val!r}. Use 'on' or 'off'."
            )
        _settings["auto_continue"] = val

    if "auto_continue_max" in patch:
        val = patch["auto_continue_max"]
        if not isinstance(val, int) or val < 1 or val > 50:
            raise ValueError("auto_continue_max must be an int in [1, 50]")
        _settings["auto_continue_max"] = val

    if "state_verbs" in patch:
        val = patch["state_verbs"]
        if val not in _VALID_STATE_VERBS:
            raise ValueError(
                f"Invalid state_verbs: {val!r}. Use 'on' or 'off'."
            )
        _settings["state_verbs"] = val

    if "state_verbs_tokens" in patch:
        val = patch["state_verbs_tokens"]
        if not isinstance(val, int) or val < 16 or val > 200:
            raise ValueError("state_verbs_tokens must be an int in [16, 200]")
        _settings["state_verbs_tokens"] = val

    if "auto_update" in patch:
        val = patch["auto_update"]
        if val not in _VALID_AUTO_UPDATE:
            raise ValueError(
                f"Invalid auto_update: {val!r}. Use 'on' or 'off'."
            )
        _settings["auto_update"] = val

    if "spotify_share_across_profiles" in patch:
        val = patch["spotify_share_across_profiles"]
        if val not in _VALID_SPOTIFY_SHARING:
            raise ValueError(
                f"Invalid spotify_share_across_profiles: {val!r}. Use 'on' or 'off'."
            )
        _settings["spotify_share_across_profiles"] = val
        _invalidate_spotify_cache()

    if "spotify_profile_overrides" in patch:
        # Three accepted shapes:
        #   - {} or None → clear every override
        #   - {"alice": True, "bob": False} → set explicitly
        #   - any other type → reject
        val = patch["spotify_profile_overrides"]
        if val is None:
            val = {}
        if not isinstance(val, dict):
            raise ValueError(
                "spotify_profile_overrides must be a dict of "
                "{profile_name: bool}"
            )
        for k, v in val.items():
            if not isinstance(k, str) or not isinstance(v, bool):
                raise ValueError(
                    "spotify_profile_overrides keys must be str, "
                    "values must be bool"
                )
        # False entries are equivalent to "no override" — drop them so
        # the dict stays small and reads cleanly.
        _settings["spotify_profile_overrides"] = {
            k: True for k, v in val.items() if v
        }
        _invalidate_spotify_cache()

    _save()
    return dict(_settings)


def _invalidate_spotify_cache() -> None:
    """Drop the in-memory Spotify token cache so the next read picks
    up the right bucket (per-profile / shared / override) without a
    process restart. The on-disk tokens in any bucket are untouched."""
    try:
        from chika.skills.spotify_skill import oauth as _spotify_oauth
        _spotify_oauth._cache.clear()
    except Exception:
        pass


def _save() -> None:
    atomic_write(_SETTINGS_PATH, json.dumps(_settings, indent=2))
