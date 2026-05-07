"""Tests for the skill auto-discovery contract.

The session manager walks ``chika/skills/*_skill/`` at build time
instead of importing each skill by name. These tests pin the
contract so a contributor can't accidentally break it:

  - Every shipped skill subpackage exports ``SKILL_NAME`` + ``build_skill``.
  - Discovery surfaces all of them.
  - ``build_skill`` accepts a SkillBuildContext and returns a Skill
    whose ``.name`` matches ``SKILL_NAME`` (no rename drift).
  - Settings validation is sourced from the same discovery walk —
    so the allow-list can never lag behind the filesystem.
"""
from __future__ import annotations

import pytest

from chika.core.skill_registry import Skill
from chika.core.variable_store import VariableStore
from chika.skills import (
    SkillBuildContext,
    iter_skill_modules,
    known_skill_names_set,
    list_known_skill_names,
)


def _bare_context() -> SkillBuildContext:
    """Build a SkillBuildContext where every getter returns ``None``.

    Skills must work in this state — the engine + workflow engine +
    profile don't exist yet at first-pass registration time.
    """
    return SkillBuildContext(
        variable_store=VariableStore(),
        engine_getter=lambda: None,
        memory_getter=lambda: None,
        workflow_engine_getter=lambda: None,
        profile_getter=lambda: None,
        workspace_getter=lambda: "",
    )


def test_all_shipped_skills_are_discovered() -> None:
    """The ten shipped skills should appear in the discovery walk."""
    expected = {
        "git", "web", "web_app", "spotify", "browser",
        "verify", "plan", "pet", "shell", "question",
    }
    discovered = known_skill_names_set()
    missing = expected - discovered
    assert not missing, f"discovery missed shipped skills: {missing}"


def test_known_skill_names_is_sorted_tuple() -> None:
    names = list_known_skill_names()
    assert isinstance(names, tuple)
    assert list(names) == sorted(names)


def test_every_module_exports_skill_name_and_build_skill() -> None:
    """The discovery walk should never yield a module missing the contract."""
    for mod in iter_skill_modules():
        assert isinstance(getattr(mod, "SKILL_NAME", None), str), \
            f"{mod.__name__} missing SKILL_NAME"
        assert callable(getattr(mod, "build_skill", None)), \
            f"{mod.__name__} missing build_skill"


def test_build_skill_returns_skill_with_matching_name() -> None:
    """For every shipped skill, ``build_skill(ctx).name == SKILL_NAME``."""
    ctx = _bare_context()
    for mod in iter_skill_modules():
        skill = mod.build_skill(ctx)
        assert isinstance(skill, Skill), f"{mod.__name__}.build_skill did not return Skill"
        assert skill.name == mod.SKILL_NAME, (
            f"{mod.__name__}.build_skill returned skill named "
            f"{skill.name!r}; expected {mod.SKILL_NAME!r} (SKILL_NAME drift)"
        )


def test_build_skill_works_with_all_none_getters() -> None:
    """Pre-engine registration MUST not crash even though all getters
    return None. Skills should defer engine access to call time."""
    ctx = _bare_context()
    for mod in iter_skill_modules():
        # Should not raise; if a skill captures live state at build
        # time it will explode here.
        mod.build_skill(ctx)


def test_settings_store_uses_discovered_names(monkeypatch, tmp_path) -> None:
    """``skills_disabled`` validation must accept every discovered name
    and only those — sourced from the same discovery walk."""
    from api import settings_store
    monkeypatch.setattr(settings_store, "_SETTINGS_PATH", tmp_path / "s.json")
    settings_store._settings = {}
    settings_store.init({})

    # Every discovered name validates clean.
    for name in list_known_skill_names():
        settings_store.update({"skills_disabled": [name]})
        assert settings_store.get("skills_disabled") == [name]

    # An unknown name raises with a helpful list.
    with pytest.raises(ValueError, match="Unknown skill"):
        settings_store.update({"skills_disabled": ["definitely_not_a_skill"]})
