"""Tests for chika/core/device_store.py."""
from __future__ import annotations

import json
import time

import pytest

from chika.core.device_store import DeviceStore


@pytest.fixture
def store(tmp_path):
    return DeviceStore(tmp_path)


class TestNewDeviceId:
    def test_format(self):
        dev_id = DeviceStore.new_device_id()
        assert dev_id.startswith("dev_")
        assert len(dev_id) == 4 + 16  # "dev_" + 16 hex chars

    def test_unique(self):
        ids = {DeviceStore.new_device_id() for _ in range(10)}
        assert len(ids) == 10


class TestGetSession:
    def test_returns_none_for_unknown_device(self, store):
        assert store.get_session("dev_unknown") is None

    def test_returns_session_after_set(self, store):
        store.set_session("dev_abc", "sess_123")
        assert store.get_session("dev_abc") == "sess_123"

    def test_corrupt_file_returns_none(self, store, tmp_path):
        dev_dir = tmp_path / "devices"
        dev_dir.mkdir(exist_ok=True)
        (dev_dir / "dev_bad.json").write_text("not json", encoding="utf-8")
        assert store.get_session("dev_bad") is None


class TestSetSession:
    def test_creates_file(self, store, tmp_path):
        store.set_session("dev_x", "sess_y")
        path = tmp_path / "devices" / "dev_x.json"
        assert path.exists()

    def test_persists_correct_data(self, store, tmp_path):
        store.set_session("dev_x", "sess_y")
        data = json.loads((tmp_path / "devices" / "dev_x.json").read_text(encoding="utf-8"))
        assert data["device_id"] == "dev_x"
        assert data["current_session_id"] == "sess_y"
        assert "created_at" in data
        assert "last_seen" in data

    def test_updates_session_preserves_created_at(self, store, tmp_path):
        store.set_session("dev_x", "sess_1")
        data1 = json.loads((tmp_path / "devices" / "dev_x.json").read_text(encoding="utf-8"))
        time.sleep(0.01)
        store.set_session("dev_x", "sess_2")
        data2 = json.loads((tmp_path / "devices" / "dev_x.json").read_text(encoding="utf-8"))
        assert data2["created_at"] == pytest.approx(data1["created_at"], abs=0.01)
        assert data2["current_session_id"] == "sess_2"

    def test_overwrites_existing_session(self, store):
        store.set_session("dev_x", "sess_old")
        store.set_session("dev_x", "sess_new")
        assert store.get_session("dev_x") == "sess_new"


class TestExists:
    def test_nonexistent_returns_false(self, store):
        assert store.exists("dev_ghost") is False

    def test_existing_returns_true(self, store):
        store.set_session("dev_real", "sess_1")
        assert store.exists("dev_real") is True
