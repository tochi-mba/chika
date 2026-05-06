"""Tests for pet_skill — mood model, prompt section, persistent memory,
and the carry/clear flow on pet swaps."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chika.core.variable_store import VariableStore
from chika.skills.pet_skill import (
    _pet_memory_path,
    _read_pet_memory,
    build_pet_skill,
    clear_pet_memory,
    copy_pet_memory,
)


@pytest.fixture
def fake_profile(tmp_path: Path):
    """A minimal profile-shaped dict: ``workspace`` lives under a profile
    root so the per-pet memory dir lands at ``profile/pets/<pet>/``.
    """
    profile_root = tmp_path / "profile"
    workspace = profile_root / "workspace"
    workspace.mkdir(parents=True)
    return {
        "root":      profile_root,
        "workspace": str(workspace),
        "pet_id":    "cat",
    }


def _make_skill(fake_profile):
    vs = VariableStore()
    return vs, build_pet_skill(
        vs,
        profile_getter=lambda: fake_profile["pet_id"],
        workspace_getter=lambda: fake_profile["workspace"],
    )


def _tool(skill, name):
    return next(t.handler for t in skill.tools if t.name == name)


# ── Mood model ─────────────────────────────────────────────────────────


def test_pet_pet_bumps_mood():
    fp = {"workspace": "", "pet_id": "cat"}
    vs, skill = _make_skill(fp)
    pet_pet = _tool(skill, "pet_pet")
    res = asyncio.run(pet_pet())
    assert res["delta"] > 0
    assert res["mood"] > 0
    assert res["pet_name"]
    assert res["state"] in ("idle", "celebrate")


def test_pet_play_bigger_than_pet_pet():
    fp = {"workspace": "", "pet_id": "cat"}
    vs, skill = _make_skill(fp)
    pet_pet = _tool(skill, "pet_pet")
    a = asyncio.run(pet_pet())
    fp_b_vs = VariableStore()
    skill_b = build_pet_skill(
        fp_b_vs,
        profile_getter=lambda: "cat",
        workspace_getter=lambda: "",
    )
    pet_play_b = _tool(skill_b, "pet_play")
    b = asyncio.run(pet_play_b())
    assert b["delta"] > a["delta"]


def test_pet_speak_with_custom_line(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    pet_speak = _tool(skill, "pet_speak")
    res = asyncio.run(pet_speak(line="hello human"))
    assert res["speech"] == "hello human"
    assert res["delta"] > 0  # speak still bumps a tiny bit


def test_pet_speak_rejects_empty_line(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    pet_speak = _tool(skill, "pet_speak")
    res = asyncio.run(pet_speak(line=""))
    assert "error" in res


# ── Persistent memory ──────────────────────────────────────────────────


def test_pet_remember_creates_memory_file(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    pet_remember = _tool(skill, "pet_remember")
    res = asyncio.run(pet_remember(fact="favourite food is salmon"))
    assert "error" not in res
    path = _pet_memory_path(fake_profile["workspace"], "cat")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "favourite food is salmon" in content


def test_pet_remember_appends_multiple_facts(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    pet_remember = _tool(skill, "pet_remember")
    asyncio.run(pet_remember(fact="hates baths"))
    asyncio.run(pet_remember(fact="loves the red ball"))
    memory = _read_pet_memory(fake_profile["workspace"], "cat")
    assert "hates baths" in memory
    assert "loves the red ball" in memory


def test_pet_recall_reads_back_facts(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    pet_remember = _tool(skill, "pet_remember")
    pet_recall = _tool(skill, "pet_recall")
    asyncio.run(pet_remember(fact="favourite food is salmon"))
    res = asyncio.run(pet_recall())
    assert "salmon" in res["memory"]
    assert len(res["lines"]) == 1


def test_pet_recall_filters_by_query(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    pet_remember = _tool(skill, "pet_remember")
    pet_recall = _tool(skill, "pet_recall")
    for fact in ("loves squeaky toys", "hates baths", "favourite food: tuna"):
        asyncio.run(pet_remember(fact=fact))
    filtered = asyncio.run(pet_recall(query="bath"))
    assert filtered["filtered"] is True
    assert all("bath" in ln.lower() for ln in filtered["lines"])
    assert any("hates baths" in ln for ln in filtered["lines"])


def test_pet_recall_empty_when_no_memory(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    pet_recall = _tool(skill, "pet_recall")
    res = asyncio.run(pet_recall())
    assert res["memory"] == ""
    assert "No memory yet" in res["note"]


def test_pet_remember_no_workspace_returns_error():
    fp = {"workspace": "", "pet_id": "cat"}
    _vs, skill = _make_skill(fp)
    pet_remember = _tool(skill, "pet_remember")
    res = asyncio.run(pet_remember(fact="anything"))
    assert res["error"] == "no_workspace"


# ── Carry / clear on pet swap ──────────────────────────────────────────


def test_copy_pet_memory_carries_facts_to_new_pet(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    pet_remember = _tool(skill, "pet_remember")
    asyncio.run(pet_remember(fact="loves catnip"))

    copied = copy_pet_memory(fake_profile["workspace"], "cat", "owl")
    assert copied is True
    new_memory = _read_pet_memory(fake_profile["workspace"], "owl")
    assert "loves catnip" in new_memory


def test_copy_pet_memory_returns_false_when_source_missing(fake_profile):
    copied = copy_pet_memory(fake_profile["workspace"], "no_such_pet", "cat")
    assert copied is False


def test_clear_pet_memory_deletes_file(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    pet_remember = _tool(skill, "pet_remember")
    asyncio.run(pet_remember(fact="forget me"))

    cleared = clear_pet_memory(fake_profile["workspace"], "cat")
    assert cleared is True
    assert _read_pet_memory(fake_profile["workspace"], "cat") == ""


def test_clear_pet_memory_idempotent_on_missing(fake_profile):
    cleared = clear_pet_memory(fake_profile["workspace"], "ghost")
    assert cleared is True


def test_pet_memory_per_pet_is_independent(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    pet_remember = _tool(skill, "pet_remember")
    asyncio.run(pet_remember(fact="cat fact"))
    fake_profile["pet_id"] = "dog"
    asyncio.run(pet_remember(fact="dog fact"))

    assert "cat fact" in _read_pet_memory(fake_profile["workspace"], "cat")
    assert "cat fact" not in _read_pet_memory(fake_profile["workspace"], "dog")
    assert "dog fact" in _read_pet_memory(fake_profile["workspace"], "dog")


# ── Prompt section ─────────────────────────────────────────────────────


def test_prompt_section_includes_pet_name_and_mood(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    text = skill.prompt_section()
    assert "Mochi the Cat" in text
    assert "neutral" in text or "happy" in text  # default mood label


def test_prompt_section_surfaces_recent_memory(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    pet_remember = _tool(skill, "pet_remember")
    asyncio.run(pet_remember(fact="purrs at sunrise"))
    text = skill.prompt_section()
    assert "purrs at sunrise" in text
    assert "Recently remembered" in text


def test_prompt_section_omits_memory_block_when_empty(fake_profile):
    _vs, skill = _make_skill(fake_profile)
    text = skill.prompt_section()
    assert "Recently remembered" not in text
