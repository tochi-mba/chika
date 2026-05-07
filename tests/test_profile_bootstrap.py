"""ProfileManager bootstrap — no more hardcoded "default" profile.

The system used to auto-create a profile literally named ``"default"``.
That label conveys no identity — it appears next to the user's chats,
in their workspace path, and in the agent's prompt context. Now the
first profile is bootstrapped from real identity sources:

  1. ``CHIKA_PROFILE`` env var (explicit override)
  2. OS username (``os.getlogin`` → ``getpass.getuser`` → ``USER``/``USERNAME``)
  3. ``"user"`` only as a final sandbox-fallback (CI with no user)

These tests pin the resolution order + the idempotent
``bootstrap_initial`` flow.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from chika.core.profile_manager import ProfileManager


@pytest.fixture
def empty_profiles_dir(tmp_path: Path) -> Path:
    return tmp_path / "profiles"


# ── bootstrap_name resolution ─────────────────────────────────────────


def test_bootstrap_name_uses_env_var_first(monkeypatch):
    """``CHIKA_PROFILE`` is the explicit override — wins over OS info."""
    monkeypatch.setenv("CHIKA_PROFILE", "kachi")
    assert ProfileManager.bootstrap_name() == "kachi"


def test_bootstrap_name_falls_back_to_os_username(monkeypatch):
    """When no env override, use the OS username."""
    monkeypatch.delenv("CHIKA_PROFILE", raising=False)
    monkeypatch.setattr("getpass.getuser", lambda: "tochi")
    monkeypatch.setattr("chika.core.profile_manager._safe_getlogin", lambda: "")
    assert ProfileManager.bootstrap_name() == "tochi"


def test_bootstrap_name_sanitises_username(monkeypatch):
    """Usernames with spaces / mixed case → sanitised."""
    monkeypatch.delenv("CHIKA_PROFILE", raising=False)
    monkeypatch.setattr("chika.core.profile_manager._safe_getlogin", lambda: "Tochukwu Mba")
    monkeypatch.setattr("getpass.getuser", lambda: "Tochukwu Mba")
    assert ProfileManager.bootstrap_name() == "tochukwu_mba"


def test_bootstrap_name_strips_unsafe_chars(monkeypatch):
    """Path-traversal chars in a username get stripped before the
    sanitiser sees them — the resolver must never accept ``..`` in
    the profile name."""
    monkeypatch.delenv("CHIKA_PROFILE", raising=False)
    monkeypatch.setattr("chika.core.profile_manager._safe_getlogin", lambda: "../etc/passwd")
    monkeypatch.setattr("getpass.getuser", lambda: "../etc/passwd")
    out = ProfileManager.bootstrap_name()
    # Sanitisation kicks in — fallback to "user" since the cleaned
    # candidate is empty / disallowed.
    assert ".." not in out
    assert "/" not in out


def test_bootstrap_name_final_fallback(monkeypatch):
    """Sandbox / CI: no env, no usable username → ``"user"`` (NOT
    ``"default"``)."""
    monkeypatch.delenv("CHIKA_PROFILE", raising=False)
    monkeypatch.setattr("chika.core.profile_manager._safe_getlogin", lambda: "")
    monkeypatch.setattr("getpass.getuser", lambda: "")
    assert ProfileManager.bootstrap_name() == "user"


def test_bootstrap_name_never_returns_default_literal(monkeypatch):
    """Hard guarantee — even when env / OS produce ``"default"``,
    that's not special. Just a real profile name."""
    monkeypatch.setenv("CHIKA_PROFILE", "default")
    # If the user explicitly says CHIKA_PROFILE=default, we honour it
    # (their choice). But the system never INVENTS that name.
    assert ProfileManager.bootstrap_name() == "default"


# ── bootstrap_initial flow ────────────────────────────────────────────


def test_bootstrap_initial_creates_first_profile_from_env(empty_profiles_dir, monkeypatch):
    """Fresh install: no profiles on disk + ``CHIKA_PROFILE`` set →
    that's the initial profile name."""
    monkeypatch.setenv("CHIKA_PROFILE", "tochi")
    pm = ProfileManager(empty_profiles_dir)
    profile = pm.bootstrap_initial()
    assert profile.name == "tochi"
    assert pm.exists("tochi")
    assert not pm.exists("default")


def test_bootstrap_initial_returns_existing_profile(empty_profiles_dir, monkeypatch):
    """Subsequent boots: an existing profile on disk wins over
    bootstrap_name. Picks the most-recently-modified."""
    monkeypatch.setenv("CHIKA_PROFILE", "would-be-new")
    pm = ProfileManager(empty_profiles_dir)
    pm.get_or_create("alice")
    profile = pm.bootstrap_initial()
    assert profile.name == "alice"
    assert not pm.exists("would-be-new"), (
        "bootstrap_initial must NOT create a fresh profile when one "
        "already exists — that would multiply profiles every boot"
    )


def test_bootstrap_initial_picks_most_recent_when_multiple_exist(
    empty_profiles_dir, monkeypatch,
):
    """Multiple profiles on disk → pick the most-recently-modified
    so the user lands back where they were."""
    import os
    import time
    monkeypatch.setenv("CHIKA_PROFILE", "would-be-new")
    pm = ProfileManager(empty_profiles_dir)
    pm.get_or_create("alice")
    time.sleep(0.05)
    pm.get_or_create("bob")
    # Touch alice last so it's most-recently-modified.
    time.sleep(0.05)
    os.utime(empty_profiles_dir / "alice", None)
    profile = pm.bootstrap_initial()
    assert profile.name == "alice"


def test_bootstrap_initial_no_default_profile_on_fresh_install(
    empty_profiles_dir, monkeypatch,
):
    """Critical contract: a fresh install must NEVER produce a
    profile literally named ``"default"`` from the bootstrap path."""
    monkeypatch.delenv("CHIKA_PROFILE", raising=False)
    monkeypatch.setattr("chika.core.profile_manager._safe_getlogin", lambda: "tochi")
    monkeypatch.setattr("getpass.getuser", lambda: "tochi")
    pm = ProfileManager(empty_profiles_dir)
    pm.bootstrap_initial()
    assert not pm.exists("default"), (
        "fresh install bootstrapped a 'default' profile — that label "
        "conveys no identity; bootstrap_name resolver should have "
        "picked the OS username instead"
    )
    assert pm.exists("tochi")
