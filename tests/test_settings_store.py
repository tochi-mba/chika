"""Tests for api/settings_store."""
from __future__ import annotations

import json
import pytest


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Give each test its own settings file and a clean _settings dict."""
    import api.settings_store as ss
    monkeypatch.setattr(ss, "_SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(ss, "_settings", {})
    yield
    monkeypatch.setattr(ss, "_settings", {})


def test_init_writes_defaults(tmp_path):
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    assert ss.get("autonomy") == "supervised"
    assert (tmp_path / "settings.json").exists()


def test_init_is_idempotent(tmp_path):
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    ss.init({"autonomy": "autonomous"})  # already set — should not overwrite
    assert ss.get("autonomy") == "supervised"


def test_update_autonomy(tmp_path):
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    result = ss.update({"autonomy": "autonomous"})
    assert result["autonomy"] == "autonomous"
    assert ss.get("autonomy") == "autonomous"


def test_update_autonomy_invalid():
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    with pytest.raises(ValueError, match="Invalid autonomy"):
        ss.update({"autonomy": "turbo"})


def test_update_autonomy_resets_tool_permissions():
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    ss.update({"tool_permissions": {"shell": "skip"}})
    assert ss.get("tool_permissions") == {"shell": "skip"}
    ss.update({"autonomy": "autonomous"})  # should clear overrides
    assert ss.get("tool_permissions") == {}


def test_update_tool_permissions_valid():
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    ss.update({"tool_permissions": {"shell": "skip", "file_write": "ask"}})
    tp = ss.get("tool_permissions")
    assert tp["shell"] == "skip"
    assert tp["file_write"] == "ask"


def test_update_tool_permissions_invalid_category():
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    with pytest.raises(ValueError, match="Unknown category"):
        ss.update({"tool_permissions": {"not_a_real_cat": "skip"}})


def test_update_tool_permissions_invalid_value():
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    with pytest.raises(ValueError, match="Invalid permission"):
        ss.update({"tool_permissions": {"shell": "maybe"}})


def test_get_tool_permission_supervised_default():
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    # shell_exec maps to "shell" category; no override → ask (supervised default)
    assert ss.get_tool_permission("shell_exec") == "ask"


def test_get_tool_permission_autonomous_default():
    import api.settings_store as ss
    ss.init({"autonomy": "autonomous"})
    assert ss.get_tool_permission("shell_exec") == "skip"


def test_get_tool_permission_explicit_override():
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    ss.update({"tool_permissions": {"shell": "skip"}})
    assert ss.get_tool_permission("shell_exec") == "skip"


def test_get_tool_permission_unknown_tool_uses_global():
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    # tool not in category map → falls back to global default
    assert ss.get_tool_permission("some_unknown_tool") == "ask"


def test_all_settings_returns_copy():
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    s1 = ss.all_settings()
    s1["autonomy"] = "hacked"
    assert ss.get("autonomy") == "supervised"  # original unchanged


def test_persisted_to_disk(tmp_path):
    import api.settings_store as ss
    ss.init({"autonomy": "supervised"})
    ss.update({"autonomy": "autonomous"})
    # Reload from disk
    raw = json.loads((tmp_path / "settings.json").read_text())
    assert raw["autonomy"] == "autonomous"
