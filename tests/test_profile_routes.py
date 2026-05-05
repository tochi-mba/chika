"""Tests for the profile-selection API used by the frontend + extension gates."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config as cfg

cfg.MAX_MEMORY_TOKENS = 1000
cfg.MAX_HISTORY_TOKENS = 10000
cfg.CHIKA_API_KEY = ""
cfg.GROUNDING_VALIDATE_RESPONSE = False

import pytest
from fastapi.testclient import TestClient

from api.server import app
from api.session_manager import session_manager


client = TestClient(app)


_TEST_PROFILE_PREFIXES = ("pick_", "pw_", "clear_", "locked_",
                          "rotate_", "test_profile_")


def _new_name(prefix: str = "test_profile") -> str:
    """Generate a profile name unique across this session.

    Names use one of the ``_TEST_PROFILE_PREFIXES`` so the
    session-scoped cleanup fixture below knows which folders are test
    artifacts. We DO NOT wipe per-test — artifacts stay on disk so a
    failing run can be inspected. The next run wipes them at startup.
    """
    import secrets
    return f"{prefix}_{secrets.token_hex(4)}"


@pytest.fixture(scope="module", autouse=True)
def _wipe_stale_test_profiles_before_run():
    """Wipe leftover test profiles from a previous run BEFORE this
    module's tests begin. Artifacts created during the new run are
    LEFT IN PLACE so the user can inspect them in ``data/profiles/``.

    Triggers off the known prefixes only — never deletes a real
    user-named profile (alex / tochi / default / etc.).
    """
    import shutil
    from api.session_manager import _PROFILES_DIR  # type: ignore
    if _PROFILES_DIR.exists():
        for entry in _PROFILES_DIR.iterdir():
            if not entry.is_dir():
                continue
            if any(entry.name.startswith(p) for p in _TEST_PROFILE_PREFIXES):
                shutil.rmtree(entry, ignore_errors=True)
    yield


def test_list_profiles_returns_default_with_has_password_flag():
    res = client.get("/api/profiles")
    assert res.status_code == 200
    data = res.json()
    assert "profiles" in data
    assert isinstance(data["profiles"], list)
    for p in data["profiles"]:
        assert "name" in p and "has_password" in p


def test_create_profile_no_password():
    name = _new_name()
    res = client.post("/api/profiles/create", json={"name": name})
    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True, "name": name, "has_password": False}


def test_create_profile_with_password_then_authenticate():
    name = _new_name("pw")
    create = client.post(
        "/api/profiles/create", json={"name": name, "password": "hunter2"},
    )
    assert create.json()["has_password"] is True

    # Wrong password rejected.
    bad = client.post(
        "/api/profiles/authenticate",
        json={"name": name, "password": "wrong"},
    )
    assert bad.status_code == 401

    # Correct password accepted.
    ok = client.post(
        "/api/profiles/authenticate",
        json={"name": name, "password": "hunter2"},
    )
    assert ok.status_code == 200
    assert ok.json()["ok"] is True


def test_authenticate_unknown_profile_returns_404():
    res = client.post(
        "/api/profiles/authenticate",
        json={"name": "definitely_does_not_exist", "password": ""},
    )
    assert res.status_code == 404


def test_select_profile_switches_active_engine_profile():
    name = _new_name("pick")
    client.post("/api/profiles/create", json={"name": name})
    res = client.post(
        "/api/profiles/select",
        json={"session_id": "test_select", "name": name, "password": ""},
    )
    assert res.status_code == 200
    engine = session_manager.get_or_create("test_select")
    assert engine._active_profile is not None
    assert engine._active_profile.name == name


def test_select_profile_with_wrong_password_is_401():
    name = _new_name("locked")
    client.post(
        "/api/profiles/create", json={"name": name, "password": "secret"},
    )
    res = client.post(
        "/api/profiles/select",
        json={"session_id": "test_locked", "name": name, "password": "nope"},
    )
    assert res.status_code == 401


def test_change_password_requires_old_password():
    name = _new_name("rotate")
    client.post(
        "/api/profiles/create", json={"name": name, "password": "old"},
    )

    # Wrong old password → rejected.
    bad = client.post(
        f"/api/profiles/{name}/password",
        json={"old_password": "wrong", "new_password": "new"},
    )
    assert bad.status_code == 401

    # Correct → accepted.
    ok = client.post(
        f"/api/profiles/{name}/password",
        json={"old_password": "old", "new_password": "new"},
    )
    assert ok.status_code == 200

    # New password works for auth now.
    auth = client.post(
        "/api/profiles/authenticate",
        json={"name": name, "password": "new"},
    )
    assert auth.status_code == 200


def test_clearing_password_makes_profile_open():
    name = _new_name("clear")
    client.post(
        "/api/profiles/create", json={"name": name, "password": "p"},
    )
    res = client.post(
        f"/api/profiles/{name}/password",
        json={"old_password": "p", "new_password": ""},
    )
    assert res.status_code == 200
    assert res.json()["has_password"] is False
