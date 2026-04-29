"""Tests for PromptBuilder — build(), workflow examples, tool/variable/memory injection."""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from chika.core.prompt_builder import PromptBuilder


@pytest.fixture
def builder():
    return PromptBuilder()


# ── build() basics ────────────────────────────────────────────────────────────

def test_build_returns_string(builder):
    result = builder.build([], [], "")
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_contains_workflow_section(builder):
    result = builder.build([], [], "")
    assert "workflow_orchestrator" in result


def test_build_contains_variable_syntax(builder):
    result = builder.build([], [], "")
    assert "store_result_as" in result


def test_build_with_no_tools_shows_none(builder):
    result = builder.build([], [], "")
    assert "None registered" in result


def test_build_with_tool_list(builder):
    tools = [
        {"name": "shell_exec", "description": "Run a shell command"},
        {"name": "file_read",  "description": "Read a file"},
    ]
    result = builder.build(tools, [], "")
    assert "`shell_exec`" in result
    assert "Run a shell command" in result
    assert "`file_read`" in result
    assert "Read a file" in result


def test_build_tool_list_formatted_as_bullet_list(builder):
    tools = [{"name": "my_tool", "description": "does things"}]
    result = builder.build(tools, [], "")
    assert "- `my_tool`:" in result


def test_build_with_no_variables_shows_none(builder):
    result = builder.build([], [], "")
    assert "None" in result


def test_build_with_variables(builder):
    variables = [
        {"name": "result", "type": "json", "size_bytes": 42, "description": "command output"},
    ]
    result = builder.build([], variables, "")
    assert "$result" in result
    assert "command output" in result
    assert "json" in result


def test_build_with_memory(builder):
    memory = "## Memory\n**tip**: Use conventional commits"
    result = builder.build([], [], memory)
    assert "conventional commits" in result


def test_build_with_empty_memory(builder):
    result = builder.build([], [], "")
    assert isinstance(result, str)  # no crash


# ── Workflow examples ─────────────────────────────────────────────────────────

def test_add_workflow_examples_appears_in_build(builder):
    builder.add_workflow_examples("git", "### Git Examples\nExample workflow here")
    result = builder.build([], [], "")
    assert "Git Examples" in result
    assert "Example workflow here" in result


def test_multiple_workflow_examples_all_appear(builder):
    builder.add_workflow_examples("git", "### Git: push commit")
    builder.add_workflow_examples("web", "### Web: fetch page")
    result = builder.build([], [], "")
    assert "Git: push commit" in result
    assert "Web: fetch page" in result


def test_remove_workflow_examples_removes_from_build(builder):
    builder.add_workflow_examples("git", "### Removable Git Section")
    builder.remove_workflow_examples("git")
    result = builder.build([], [], "")
    assert "Removable Git Section" not in result


def test_remove_missing_workflow_examples_is_safe(builder):
    builder.remove_workflow_examples("nonexistent")  # should not raise


def test_workflow_examples_section_heading(builder):
    builder.add_workflow_examples("myskill", "some content")
    result = builder.build([], [], "")
    assert "Skill Workflow Examples" in result


def test_no_workflow_examples_no_skill_section(builder):
    result = builder.build([], [], "")
    assert "Skill Workflow Examples" not in result


def test_add_overrides_existing_skill_section(builder):
    builder.add_workflow_examples("s", "### Version 1")
    builder.add_workflow_examples("s", "### Version 2")
    result = builder.build([], [], "")
    assert "Version 2" in result
    assert "Version 1" not in result


# ── Step types coverage ───────────────────────────────────────────────────────

def test_build_mentions_all_step_types(builder):
    result = builder.build([], [], "")
    for step_type in ["sequential", "parallel", "conditional", "loop", "map", "fan_out", "retry", "pipeline", "sub_workflow"]:
        assert step_type in result, f"Missing step type: {step_type}"


# ── Meta-tools ────────────────────────────────────────────────────────────────

def test_build_mentions_meta_tools(builder):
    result = builder.build([], [], "")
    assert "llm_summarise" in result
    assert "llm_transform" in result


# ── Rules ────────────────────────────────────────────────────────────────────

def test_build_contains_rules_section(builder):
    result = builder.build([], [], "")
    assert "Rules" in result or "rules" in result.lower()


def test_build_multiple_tools(builder):
    tools = [{"name": f"tool_{i}", "description": f"Tool {i}"} for i in range(10)]
    result = builder.build(tools, [], "")
    for i in range(10):
        assert f"tool_{i}" in result


def test_build_multiple_variables(builder):
    variables = [
        {"name": f"var_{i}", "type": "text", "size_bytes": 10, "description": f"Var {i}"}
        for i in range(5)
    ]
    result = builder.build([], variables, "")
    for i in range(5):
        assert f"$var_{i}" in result
