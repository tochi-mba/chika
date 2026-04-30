"""Tests for chika/core/chat_store.py."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from chika.core.chat_store import ChatStore


@pytest.fixture
def store(tmp_path):
    return ChatStore(tmp_path / "profiles")


class TestSave:
    def test_save_creates_file(self, store, tmp_path):
        store.save("default", "sess1", [{"role": "user", "content": "hello"}], title="My Chat")
        path = tmp_path / "profiles" / "default" / "chats" / "sess1.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["id"] == "sess1"
        assert data["title"] == "My Chat"
        assert data["profile"] == "default"
        assert len(data["messages"]) == 1

    def test_save_preserves_created_at_on_update(self, store):
        store.save("default", "sess1", [], title="First")
        data1 = store.load("default", "sess1")
        assert data1 is not None
        time.sleep(0.01)
        store.save("default", "sess1", [{"role": "user", "content": "hi"}], title="Updated")
        data2 = store.load("default", "sess1")
        assert data2 is not None
        assert data2["created_at"] == pytest.approx(data1["created_at"], abs=0.01)
        assert data2["updated_at"] >= data1["updated_at"]

    def test_save_inherits_title_when_empty(self, store):
        store.save("default", "sess1", [], title="Original")
        store.save("default", "sess1", [], title="")
        data = store.load("default", "sess1")
        assert data is not None
        assert data["title"] == "Original"


class TestLoad:
    def test_load_nonexistent_returns_none(self, store):
        assert store.load("default", "missing") is None

    def test_load_returns_dict(self, store):
        store.save("default", "s1", [{"role": "user", "content": "hi"}])
        data = store.load("default", "s1")
        assert isinstance(data, dict)
        assert data["id"] == "s1"

    def test_load_corrupt_file_returns_none(self, store, tmp_path):
        chat_dir = tmp_path / "profiles" / "default" / "chats"
        chat_dir.mkdir(parents=True)
        (chat_dir / "bad.json").write_text("not json", encoding="utf-8")
        assert store.load("default", "bad") is None


class TestUpdateTitle:
    def test_update_existing(self, store):
        store.save("default", "s1", [], title="Old")
        store.update_title("default", "s1", "New Title")
        data = store.load("default", "s1")
        assert data is not None
        assert data["title"] == "New Title"

    def test_update_nonexistent_is_noop(self, store):
        store.update_title("default", "ghost", "Title")  # should not raise


class TestListChats:
    def test_empty_profile_returns_empty(self, store):
        assert store.list_chats("nobody") == []

    def test_lists_saved_chats(self, store):
        store.save("alice", "s1", [{"role": "user", "content": "hello"}], title="Chat 1")
        store.save("alice", "s2", [{"role": "assistant", "content": "hi"}], title="Chat 2")
        chats = store.list_chats("alice")
        assert len(chats) == 2
        ids = {c["id"] for c in chats}
        assert ids == {"s1", "s2"}

    def test_preview_extracted_from_messages(self, store):
        msgs = [
            {"role": "user", "content": "what is the capital of France?"},
            {"role": "assistant", "content": "Paris"},
        ]
        store.save("alice", "s1", msgs)
        chats = store.list_chats("alice")
        assert chats[0]["preview"] != ""

    def test_message_count_only_counts_user_and_assistant(self, store):
        msgs = [
            {"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        store.save("alice", "s1", msgs)
        chats = store.list_chats("alice")
        assert chats[0]["message_count"] == 2

    def test_sorted_by_updated_at_descending(self, store):
        store.save("alice", "s1", [], title="Older")
        time.sleep(0.02)
        store.save("alice", "s2", [], title="Newer")
        chats = store.list_chats("alice")
        assert chats[0]["id"] == "s2"

    def test_corrupted_file_skipped(self, store, tmp_path):
        chat_dir = tmp_path / "profiles" / "alice" / "chats"
        chat_dir.mkdir(parents=True)
        (chat_dir / "broken.json").write_text("{bad json", encoding="utf-8")
        store.save("alice", "good", [], title="Good")
        chats = store.list_chats("alice")
        assert len(chats) == 1
        assert chats[0]["id"] == "good"


class TestDelete:
    def test_delete_existing_returns_true(self, store):
        store.save("default", "s1", [])
        assert store.delete("default", "s1") is True

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete("default", "ghost") is False

    def test_deleted_file_gone(self, store, tmp_path):
        store.save("default", "s1", [])
        store.delete("default", "s1")
        assert store.load("default", "s1") is None


class TestFindSessionProfile:
    def test_finds_correct_profile(self, store):
        store.save("alice", "sess-alice", [])
        store.save("bob", "sess-bob", [])
        assert store.find_session_profile("sess-alice") == "alice"
        assert store.find_session_profile("sess-bob") == "bob"

    def test_returns_none_when_not_found(self, store):
        assert store.find_session_profile("nonexistent") is None

    def test_returns_none_when_profiles_dir_missing(self, tmp_path):
        store = ChatStore(tmp_path / "does_not_exist" / "profiles")
        assert store.find_session_profile("any") is None
