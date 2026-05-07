"""Invariants for the system-prompt ↔ SKILL.md split.

The system prompt and each skill's SKILL.md must NOT duplicate content.
Skills with a SKILL.md own the canonical reference; the agent loads it
on demand via ``skill_load``. The system prompt only contains
cross-cutting rules that don't belong to any single skill.

These tests lock that contract in so a future PR can't sneak skill
content back into the prompt.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from chika.core.memory_manager import MemoryManager
from chika.core.prompt_builder import _CORE, _REFERENCE_SECTIONS, PromptBuilder
from chika.core.skill_registry import SkillRegistry, _has_skill_doc
from chika.core.tool_registry import ToolRegistry


_REPO = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO / "chika" / "skills"


# ── 1. Every shipped skill has a SKILL.md ─────────────────────────────────

@pytest.mark.parametrize("skill_dir", [
    p for p in _SKILLS_DIR.iterdir()
    if p.is_dir() and not p.name.startswith("_")
])
def test_every_skill_folder_has_a_skill_md(skill_dir):
    assert (skill_dir / "SKILL.md").is_file(), (
        f"{skill_dir.name} is missing SKILL.md — without it the canonical "
        "skill reference falls back to prompt injection."
    )


# ── 2. _has_skill_doc resolves both naming conventions ────────────────────

def test_has_skill_doc_resolves_name_with_or_without_suffix():
    """The resolver accepts either the canonical skill name (e.g.
    ``"foo"``) or the folder name (``"foo_skill"``). We discover real
    skill names via the public discovery API rather than hardcoding,
    so this test stays valid as the universe of skills evolves."""
    from chika.skills import list_known_skill_names
    names = list_known_skill_names()
    assert names, "no skills shipped — discovery is broken"
    for name in names:
        assert _has_skill_doc(name) is True, f"missing SKILL.md for {name!r}"
    # An unknown skill returns False, not a crash.
    assert _has_skill_doc("definitely-not-real") is False


# ── 3. Registering a skill with SKILL.md does NOT inject its examples ────

def test_skill_with_doc_does_not_inject_workflow_examples(tmp_path):
    """A skill that has a SKILL.md must not push workflow_examples into
    the prompt builder — that would duplicate context every turn."""
    from chika.core.skill_registry import Skill

    # Prepare a fake "git" skill but with workflow_examples that we'd
    # notice if it leaked into the prompt.
    sentinel = "SENTINEL_workflow_text_should_not_appear"

    # We can't easily mock _has_skill_doc per-call, so build directly.
    pb = PromptBuilder()
    sr = SkillRegistry(
        ToolRegistry(),
        MemoryManager(path=str(tmp_path / "mem.md"), max_tokens=2000),
        pb,
    )
    sr.register(Skill(
        name="git",   # has SKILL.md
        description="git ops",
        tools=[],
        workflow_examples=sentinel,
    ))
    rendered = pb.build(tool_list=[], variables=[], memory="",
                       skill_index=sr.skill_index())
    assert sentinel not in rendered, (
        "skills with SKILL.md must not inject workflow_examples — that's "
        "duplicate context every turn"
    )
    # And the skill index DOES report the doc as available.
    idx = sr.skill_index()
    assert any(s["name"] == "git" and s["has_doc"] for s in idx)


def test_skill_without_doc_still_injects_workflow_examples(tmp_path):
    """Defensive fallback: a skill without SKILL.md keeps the old
    behaviour — its workflow_examples land in the prompt."""
    from chika.core.skill_registry import Skill

    pb = PromptBuilder()
    sr = SkillRegistry(
        ToolRegistry(),
        MemoryManager(path=str(tmp_path / "mem.md"), max_tokens=2000),
        pb,
    )
    sentinel = "SENTINEL_for_skill_without_doc"
    sr.register(Skill(
        name="this-skill-has-no-md-on-disk",
        description="defensive case",
        tools=[],
        workflow_examples=sentinel,
    ))
    rendered = pb.build(tool_list=[], variables=[], memory="",
                       skill_index=sr.skill_index())
    assert sentinel in rendered, (
        "skill without a SKILL.md must still inject its workflow_examples "
        "as a fallback so the agent isn't flying blind"
    )


# ── 4. The prompt no longer contains skill-specific big blocks ───────────

@pytest.mark.parametrize("phrase", [
    # These phrases were duplicated between ``_REFERENCE_SECTIONS`` and
    # the shipped SKILL.md docs. If they reappear in ``_CORE``, the
    # dedup invariant is broken.
    "MANDATORY after any HTML/JS build",
    "Build the real thing, not sketches",
])
def test_core_prompt_does_not_duplicate_skill_content(phrase):
    assert phrase not in _CORE, (
        f"system prompt contains {phrase!r} which now lives in a "
        "skill's SKILL.md. Don't duplicate context."
    )


def test_web_reference_section_removed():
    """The dedicated 'web' reference section was migrated to a
    skill's SKILL.md and dropped from _REFERENCE_SECTIONS."""
    assert "web" not in _REFERENCE_SECTIONS, (
        "_REFERENCE_SECTIONS['web'] was removed because the web skill's "
        "SKILL.md is now the canonical reference. Don't add it back."
    )


# ── 5. Skill index is rendered into the prompt ────────────────────────────

def test_skill_index_renders_in_prompt(tmp_path):
    from chika.core.skill_registry import Skill

    pb = PromptBuilder()
    sr = SkillRegistry(
        ToolRegistry(),
        MemoryManager(path=str(tmp_path / "mem.md"), max_tokens=2000),
        pb,
    )
    sr.register(Skill(
        name="git",
        description="Git operations — status, diff, log, etc.",
        tools=[],
    ))
    rendered = pb.build(
        tool_list=[], variables=[], memory="",
        skill_index=sr.skill_index(),
    )
    assert "## Available skills" in rendered or "Available skills" in rendered
    assert "`git`" in rendered, "skill index should mention each registered skill"
    # SKILL.md is present so the doc marker should appear.
    assert "📚" in rendered or "no SKILL.md yet" in rendered


# ── 6. SKILL.md migration sanity — content survives ───────────────────────

@pytest.mark.parametrize("skill,phrase", [
    # Content moved out of the prompt should be findable in the SKILL.md.
    ("web_app", "MANDATORY: serve every HTML/JS build with `live_server`"),
    ("web_app", "Build the real thing, not sketches"),
    ("web",     "Never construct URLs from memory"),
    ("git",     "Diff and summarise"),
    ("git",     "Full feature flow"),
])
def test_migrated_content_survives_in_skill_md(skill, phrase):
    md = _SKILLS_DIR / f"{skill}_skill" / "SKILL.md"
    assert md.is_file()
    body = md.read_text(encoding="utf-8")
    assert phrase in body, (
        f"phrase {phrase!r} should now live in {md} (migrated from the "
        "system prompt). If you removed it on purpose, update this test."
    )
