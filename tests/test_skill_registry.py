"""Tests for SkillRegistry — register, unregister, tool propagation, workflow examples."""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


import pytest

from chika.core.memory_manager import MemoryManager
from chika.core.prompt_builder import PromptBuilder
from chika.core.skill_registry import Skill, SkillRegistry
from chika.core.tool_registry import ToolDefinition, ToolRegistry
from chika.core.variable_store import VariableStore


def make_tool(name):
    async def handler(**kwargs): return {}
    return ToolDefinition(name, f"Tool {name}", {"type": "object", "properties": {}}, handler)


@pytest.fixture
def registry(tmp_path):
    tool_reg = ToolRegistry()
    VariableStore()
    mem = MemoryManager(path=str(tmp_path / "memory.md"))
    prompt = PromptBuilder()
    return SkillRegistry(tool_reg, mem, prompt), tool_reg, mem, prompt


# ── Registration ──────────────────────────────────────────────────────────────

def test_register_skill_adds_tools(registry):
    sr, tool_reg, _, _ = registry
    skill = Skill(
        name="test_skill",
        description="A test skill",
        tools=[make_tool("skill_tool_a"), make_tool("skill_tool_b")],
    )
    sr.register(skill)
    assert tool_reg.get("skill_tool_a") is not None
    assert tool_reg.get("skill_tool_b") is not None


def test_register_skill_is_retrievable(registry):
    sr, _, _, _ = registry
    skill = Skill(name="my_skill", description="desc", tools=[])
    sr.register(skill)
    assert sr.get("my_skill") is not None
    assert sr.get("my_skill").name == "my_skill"


def test_register_skill_missing_returns_none(registry):
    sr, _, _, _ = registry
    assert sr.get("nonexistent") is None


def test_register_multiple_skills(registry):
    sr, tool_reg, _, _ = registry
    sr.register(Skill("skill_a", "a", [make_tool("tool_a1")]))
    sr.register(Skill("skill_b", "b", [make_tool("tool_b1")]))
    assert tool_reg.get("tool_a1") is not None
    assert tool_reg.get("tool_b1") is not None


# ── Unregister ────────────────────────────────────────────────────────────────

def test_unregister_removes_skill(registry):
    sr, _, _, _ = registry
    sr.register(Skill("removable", "r", []))
    sr.unregister("removable")
    assert sr.get("removable") is None


def test_unregister_removes_tools(registry):
    sr, tool_reg, _, _ = registry
    sr.register(Skill("s", "s", [make_tool("removable_tool")]))
    assert tool_reg.get("removable_tool") is not None
    sr.unregister("s")
    assert tool_reg.get("removable_tool") is None


def test_unregister_missing_skill_is_safe(registry):
    sr, _, _, _ = registry
    sr.unregister("does_not_exist")  # Should not raise


def test_unregister_does_not_affect_other_skills(registry):
    sr, tool_reg, _, _ = registry
    sr.register(Skill("s1", "s1", [make_tool("t1")]))
    sr.register(Skill("s2", "s2", [make_tool("t2")]))
    sr.unregister("s1")
    assert tool_reg.get("t1") is None
    assert tool_reg.get("t2") is not None


# ── Workflow examples ─────────────────────────────────────────────────────────

def test_register_adds_workflow_examples_to_prompt(registry):
    sr, _, _, prompt = registry
    skill = Skill(
        name="ws",
        description="with examples",
        tools=[],
        workflow_examples="### Git Workflow\nExample here",
    )
    sr.register(skill)
    built = prompt.build([], [], "")
    assert "Git Workflow" in built


def test_unregister_removes_workflow_examples(registry):
    sr, _, _, prompt = registry
    skill = Skill(
        name="ws",
        description="with examples",
        tools=[],
        workflow_examples="### Unique Section XYZ123",
    )
    sr.register(skill)
    assert "Unique Section XYZ123" in prompt.build([], [], "")
    sr.unregister("ws")
    assert "Unique Section XYZ123" not in prompt.build([], [], "")


def test_skill_without_workflow_examples_is_fine(registry):
    sr, _, _, prompt = registry
    sr.register(Skill("s", "s", [], workflow_examples=""))
    built = prompt.build([], [], "")
    assert built  # prompt still builds without error


# ── Memory seeds ──────────────────────────────────────────────────────────────

def test_register_seeds_memory(registry):
    sr, _, mem, _ = registry
    skill = Skill(
        name="sk",
        description="sk",
        tools=[],
        memory_seeds={"git_conventions": "Use conventional commits"},
    )
    sr.register(skill)
    assert mem.read("git_conventions") == "Use conventional commits"


def test_seed_does_not_overwrite_existing(registry):
    sr, _, mem, _ = registry
    mem.persist("existing_key", "original_value")
    skill = Skill(
        name="sk",
        description="sk",
        tools=[],
        memory_seeds={"existing_key": "new_value"},
    )
    sr.register(skill)
    assert mem.read("existing_key") == "original_value"


def test_multiple_seeds(registry):
    sr, _, mem, _ = registry
    skill = Skill(
        name="sk",
        description="sk",
        tools=[],
        memory_seeds={
            "key_alpha": "alpha",
            "key_beta": "beta",
            "key_gamma": "gamma",
        },
    )
    sr.register(skill)
    assert mem.read("key_alpha") == "alpha"
    assert mem.read("key_beta") == "beta"
    assert mem.read("key_gamma") == "gamma"


# ── list_skills ───────────────────────────────────────────────────────────────

def test_list_skills_empty(registry):
    sr, _, _, _ = registry
    assert sr.list_skills() == []


def test_list_skills_returns_registered(registry):
    sr, _, _, _ = registry
    sr.register(Skill("s1", "first skill", [make_tool("st1")]))
    sr.register(Skill("s2", "second skill", [make_tool("st2")]))
    listing = sr.list_skills()
    names = [s["name"] for s in listing]
    assert "s1" in names
    assert "s2" in names


def test_list_skills_includes_tool_names(registry):
    sr, _, _, _ = registry
    sr.register(Skill("sk", "sk", [make_tool("listed_tool")]))
    listing = sr.list_skills()
    sk = next(s for s in listing if s["name"] == "sk")
    assert "listed_tool" in sk["tools"]


def test_list_skills_includes_description(registry):
    sr, _, _, _ = registry
    sr.register(Skill("sk", "My skill description", []))
    listing = sr.list_skills()
    sk = listing[0]
    assert sk["description"] == "My skill description"
