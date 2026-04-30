"""Tests for chika/core/profile_manager.py."""
from __future__ import annotations

import pytest

from chika.core.profile_manager import Profile, ProfileManager


@pytest.fixture
def pm(tmp_path):
    return ProfileManager(tmp_path / "profiles")


class TestGetOrCreate:
    def test_creates_profile_directories(self, pm, tmp_path):
        pm.get_or_create("tochi")
        assert (tmp_path / "profiles" / "tochi").is_dir()
        assert (tmp_path / "profiles" / "tochi" / "workspace").is_dir()

    def test_returns_profile_with_correct_name(self, pm):
        profile = pm.get_or_create("alice")
        assert profile.name == "alice"

    def test_workspace_path_is_absolute(self, pm):
        profile = pm.get_or_create("alice")
        import os
        assert os.path.isabs(profile.workspace)

    def test_idempotent(self, pm):
        p1 = pm.get_or_create("alice")
        p2 = pm.get_or_create("alice")
        assert p1.name == p2.name
        assert p1.workspace == p2.workspace

    def test_no_password_by_default(self, pm):
        profile = pm.get_or_create("alice")
        assert profile.password_hash is None


class TestExists:
    def test_nonexistent_returns_false(self, pm):
        assert pm.exists("nobody") is False

    def test_existing_returns_true(self, pm):
        pm.get_or_create("alice")
        assert pm.exists("alice") is True


class TestGet:
    def test_get_nonexistent_returns_none(self, pm):
        assert pm.get("nobody") is None

    def test_get_existing_returns_profile(self, pm):
        pm.get_or_create("alice")
        profile = pm.get("alice")
        assert profile is not None
        assert profile.name == "alice"


class TestListProfiles:
    def test_empty_returns_empty(self, pm):
        assert pm.list_profiles() == []

    def test_lists_created_profiles(self, pm):
        pm.get_or_create("bob")
        pm.get_or_create("alice")
        profiles = pm.list_profiles()
        assert sorted(profiles) == ["alice", "bob"]

    def test_sorted_alphabetically(self, pm):
        pm.get_or_create("zebra")
        pm.get_or_create("ant")
        assert pm.list_profiles() == ["ant", "zebra"]


class TestPasswordHashing:
    def test_hash_password_returns_salt_colon_hash(self, pm):
        hashed = ProfileManager._hash_password("secret")
        assert ":" in hashed
        parts = hashed.split(":")
        assert len(parts) == 2

    def test_check_password_correct(self, pm):
        hashed = ProfileManager._hash_password("secret")
        assert ProfileManager._check_password("secret", hashed) is True

    def test_check_password_wrong(self, pm):
        hashed = ProfileManager._hash_password("secret")
        assert ProfileManager._check_password("wrong", hashed) is False

    def test_check_password_empty_stored_returns_false(self, pm):
        assert ProfileManager._check_password("anything", "") is False

    def test_check_password_no_colon_returns_false(self, pm):
        assert ProfileManager._check_password("anything", "nocolon") is False

    def test_different_hashes_for_same_password(self, pm):
        h1 = ProfileManager._hash_password("same")
        h2 = ProfileManager._hash_password("same")
        assert h1 != h2  # different salts


class TestSetPassword:
    def test_set_password_persists(self, pm):
        pm.get_or_create("alice")
        pm.set_password("alice", "mypassword")
        assert pm.has_password("alice") is True

    def test_verify_correct_password(self, pm):
        pm.get_or_create("alice")
        pm.set_password("alice", "mypassword")
        assert pm.verify_password("alice", "mypassword") is True

    def test_verify_wrong_password(self, pm):
        pm.get_or_create("alice")
        pm.set_password("alice", "mypassword")
        assert pm.verify_password("alice", "wrong") is False

    def test_clear_password_with_empty_string(self, pm):
        pm.get_or_create("alice")
        pm.set_password("alice", "mypassword")
        pm.set_password("alice", "")
        assert pm.has_password("alice") is False

    def test_verify_no_password_returns_true(self, pm):
        pm.get_or_create("alice")
        assert pm.verify_password("alice", "anything") is True

    def test_password_hash_loaded_from_disk(self, pm, tmp_path):
        pm.get_or_create("alice")
        pm.set_password("alice", "diskpass")
        # Create a new ProfileManager pointing at same dir (simulates restart)
        pm2 = ProfileManager(tmp_path / "profiles")
        assert pm2.verify_password("alice", "diskpass") is True
        assert pm2.verify_password("alice", "wrongpass") is False


class TestHasPassword:
    def test_no_password_returns_false(self, pm):
        pm.get_or_create("alice")
        assert pm.has_password("alice") is False

    def test_with_password_returns_true(self, pm):
        pm.get_or_create("alice")
        pm.set_password("alice", "secret")
        assert pm.has_password("alice") is True
