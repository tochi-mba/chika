"""Coverage for chika/tools/profile_tools.py."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from chika.tools import profile_tools as pt


def _engine_with_profile(name="alice", workspace="/ws"):
    engine = MagicMock()
    profile = MagicMock()
    profile.name = name
    profile.workspace = workspace
    profile.memory_path = f"/memory/{name}.md"
    engine._active_profile = profile
    return engine


def _pm(profiles=None, passwords=None):
    profiles = list(profiles or [])
    passwords = dict(passwords or {})
    pm = MagicMock()
    pm.list_profiles.return_value = profiles
    pm.exists.side_effect = lambda n: n in profiles
    def get(n):
        if n not in profiles:
            return None
        prof = MagicMock()
        prof.name = n
        prof.workspace = f"/ws/{n}"
        prof.memory_path = f"/memory/{n}.md"
        return prof
    pm.get.side_effect = get
    pm.get_or_create.side_effect = lambda n: (profiles.append(n), get(n))[1]
    pm.set_password.side_effect = lambda n, pw: passwords.setdefault(n, pw)
    return pm


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


@pytest.mark.asyncio
async def test_profile_list_returns_current_and_list():
    engine = _engine_with_profile("alice")
    pm = _pm(["alice", "bob"])
    tools = pt.make_profile_tools(engine, pm)
    out = await _tool(tools, "profile_list").handler()
    assert out["current"] == "alice"
    assert "alice" in out["profiles"]
    assert "bob" in out["profiles"]


@pytest.mark.asyncio
async def test_profile_list_uses_default_when_no_active():
    engine = MagicMock()
    engine._active_profile = None
    pm = _pm([])
    tools = pt.make_profile_tools(engine, pm)
    out = await _tool(tools, "profile_list").handler()
    assert out["current"] == "default"


@pytest.mark.asyncio
async def test_profile_get_returns_active_profile_details():
    engine = _engine_with_profile("alice", workspace="/x")
    pm = _pm(["alice"])
    tools = pt.make_profile_tools(engine, pm)
    out = await _tool(tools, "profile_get").handler()
    assert out["name"] == "alice"
    assert out["workspace"] == "/x"
    assert out["memory_path"]


@pytest.mark.asyncio
async def test_profile_get_returns_default_when_no_active():
    engine = MagicMock()
    engine._active_profile = None
    pm = _pm([])
    tools = pt.make_profile_tools(engine, pm)
    out = await _tool(tools, "profile_get").handler()
    assert out["name"] == "default"
    assert out["workspace"] is None


@pytest.mark.asyncio
async def test_profile_switch_to_existing_profile():
    engine = _engine_with_profile("alice")
    pm = _pm(["alice", "bob"])
    tools = pt.make_profile_tools(engine, pm)
    out = await _tool(tools, "profile_switch").handler(name="bob")
    assert out["switched_to"] == "bob"
    assert engine.switch_profile.called


@pytest.mark.asyncio
async def test_profile_switch_unknown_returns_error():
    engine = _engine_with_profile("alice")
    pm = _pm(["alice"])
    tools = pt.make_profile_tools(engine, pm)
    out = await _tool(tools, "profile_switch").handler(name="ghost")
    assert "error" in out
    assert "does not exist" in out["error"]


@pytest.mark.asyncio
async def test_profile_switch_load_failure_returns_error():
    """When pm.get returns None for a profile that exists, surface an error."""
    engine = _engine_with_profile("alice")
    pm = MagicMock()
    pm.exists.return_value = True
    pm.get.return_value = None
    tools = pt.make_profile_tools(engine, pm)
    out = await _tool(tools, "profile_switch").handler(name="bob")
    assert "error" in out


@pytest.mark.asyncio
async def test_profile_create_new_profile_lowercases_and_underscores():
    engine = _engine_with_profile("alice")
    pm = _pm(["alice"])
    tools = pt.make_profile_tools(engine, pm)
    out = await _tool(tools, "profile_create").handler(name="New Person")
    assert out["created"] == "new_person"
    assert out["switched_to"] == "new_person"


@pytest.mark.asyncio
async def test_profile_create_with_password_calls_set_password():
    engine = _engine_with_profile("alice")
    pm = _pm(["alice"])
    tools = pt.make_profile_tools(engine, pm)
    await _tool(tools, "profile_create").handler(
        name="bob", _password="hunter2",
    )
    pm.set_password.assert_called_once_with("bob", "hunter2")


@pytest.mark.asyncio
async def test_profile_create_existing_just_switches():
    engine = _engine_with_profile("alice")
    pm = _pm(["alice", "bob"])
    tools = pt.make_profile_tools(engine, pm)
    out = await _tool(tools, "profile_create").handler(name="bob")
    assert "note" in out
    assert "already existed" in out["note"]
    assert out["switched_to"] == "bob"


@pytest.mark.asyncio
async def test_profile_create_existing_load_failure_returns_error():
    """Existing profile that fails to load returns an error rather than crashing."""
    engine = _engine_with_profile("alice")
    pm = MagicMock()
    pm.exists.return_value = True
    pm.get.return_value = None
    tools = pt.make_profile_tools(engine, pm)
    out = await _tool(tools, "profile_create").handler(name="bob")
    assert "error" in out


@pytest.mark.asyncio
async def test_set_password_tool_returns_success_no_op():
    """The set_password tool is purely a no-op acknowledgement — the
    real password write happens in the approval handler."""
    pm = _pm([])
    tool = pt.make_set_password_tool(pm)
    out = await tool.handler()
    assert out["success"] is True
    assert "updated" in out["message"]


def test_set_password_tool_metadata():
    tool = pt.make_set_password_tool(_pm([]))
    assert tool.name == "set_profile_password"
    assert tool.requires_approval is True
    assert tool.approval_type == "set_password"


def test_make_profile_tools_returns_four_tools():
    engine = _engine_with_profile("alice")
    pm = _pm(["alice"])
    tools = pt.make_profile_tools(engine, pm)
    names = {t.name for t in tools}
    assert names == {"profile_list", "profile_get", "profile_switch", "profile_create"}


def test_profile_switch_requires_approval():
    engine = _engine_with_profile("alice")
    pm = _pm(["alice"])
    tools = pt.make_profile_tools(engine, pm)
    switch = _tool(tools, "profile_switch")
    assert switch.requires_approval is True


def test_profile_create_uses_set_password_approval_type():
    engine = _engine_with_profile("alice")
    pm = _pm(["alice"])
    tools = pt.make_profile_tools(engine, pm)
    create = _tool(tools, "profile_create")
    assert create.requires_approval is True
    assert create.approval_type == "set_password"
