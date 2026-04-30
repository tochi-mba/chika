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
from pathlib import Path

from chika.core._io import atomic_write

_SETTINGS_PATH = Path("data/settings.json")

_VALID_AUTONOMY = {"supervised", "autonomous"}
_VALID_PERMISSION = {"ask", "skip"}

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

    _save()
    return dict(_settings)


def _save() -> None:
    atomic_write(_SETTINGS_PATH, json.dumps(_settings, indent=2))
