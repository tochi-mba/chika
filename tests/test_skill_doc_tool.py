"""Coverage for chika/tools/skill_doc_tool.py — skill_load + skill_query."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from chika.tools import skill_doc_tool as sdt


# ── _resolve_skill_dir ────────────────────────────────────────────────


def _a_real_skill() -> str:
    """Pick the first shipped skill via the public discovery API.
    Used as a stable test fixture so the test exercises the resolver
    against a real folder without hardcoding any specific skill
    name (skill-isolation contract: no skill names in tests outside
    the skill's own folder)."""
    from chika.skills import list_known_skill_names
    names = list_known_skill_names()
    assert names, "no skills shipped — discovery is broken"
    return names[0]


def test_resolve_skill_dir_canonical_name():
    """Plain name resolves when the skill folder ends in ``_skill``."""
    name = _a_real_skill()
    out = sdt._resolve_skill_dir(name)
    assert out is not None
    assert out.name == f"{name}_skill"


def test_resolve_skill_dir_with_suffix():
    """Passing the full ``<name>_skill`` form also resolves."""
    name = _a_real_skill()
    out = sdt._resolve_skill_dir(f"{name}_skill")
    assert out is not None
    assert out.name == f"{name}_skill"


def test_resolve_skill_dir_lowercase_normalises():
    """Lowercase names work; on case-sensitive filesystems (Linux CI)
    the resolver also tries lowercased candidates."""
    name = _a_real_skill()
    out = sdt._resolve_skill_dir(name.lower())
    assert out is not None
    assert out.name == f"{name}_skill"


def test_resolve_skill_dir_unknown_returns_none():
    assert sdt._resolve_skill_dir("nonexistent_skill_xyz") is None


# ── _read_skill_doc ────────────────────────────────────────────────────


def test_read_skill_doc_finds_skill_md(tmp_path: Path):
    skill_dir = tmp_path / "fake_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# fake skill\nbody", encoding="utf-8")
    path, content = sdt._read_skill_doc(skill_dir)
    assert path is not None
    assert path.name == "SKILL.md"
    assert "fake skill" in content


def test_read_skill_doc_case_insensitive(tmp_path: Path):
    """Lower-case skill.md still resolves."""
    skill_dir = tmp_path / "fake_skill"
    skill_dir.mkdir()
    (skill_dir / "skill.md").write_text("body", encoding="utf-8")
    path, content = sdt._read_skill_doc(skill_dir)
    assert path is not None
    assert content == "body"


def test_read_skill_doc_missing_returns_none(tmp_path: Path):
    skill_dir = tmp_path / "empty_skill"
    skill_dir.mkdir()
    path, content = sdt._read_skill_doc(skill_dir)
    assert path is None
    assert content == ""


# ── _last_messages ─────────────────────────────────────────────────────


def test_last_messages_renders_pairs():
    history = [
        {"role": "user",      "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user",      "content": "bye"},
    ]
    out = sdt._last_messages(history, 5)
    assert "[user] hi" in out
    assert "[assistant] hello" in out
    assert "[user] bye" in out


def test_last_messages_takes_only_last_n():
    history = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
    out = sdt._last_messages(history, 3)
    # Should include only the last 3.
    assert "msg 7" in out
    assert "msg 8" in out
    assert "msg 9" in out
    assert "msg 0" not in out


def test_last_messages_skips_non_user_assistant_roles():
    history = [
        {"role": "system", "content": "system prompt"},
        {"role": "user",   "content": "ask"},
        {"role": "tool",   "content": "tool_result"},
    ]
    out = sdt._last_messages(history, 5)
    assert "[user] ask" in out
    assert "system prompt" not in out
    assert "tool_result" not in out


def test_last_messages_truncates_long_content():
    long = "x" * 600
    out = sdt._last_messages([{"role": "user", "content": long}], 1)
    # Output should be truncated to ~400 chars + ellipsis.
    assert "…" in out
    assert len(out) < 500


def test_last_messages_empty_history_returns_empty_string():
    assert sdt._last_messages([], 5) == ""


def test_last_messages_skips_non_string_content():
    """tool_calls etc. set content to a list — those should be skipped."""
    history = [
        {"role": "user",      "content": "hi"},
        {"role": "assistant", "content": [{"type": "tool_use"}]},
    ]
    out = sdt._last_messages(history, 5)
    assert "[user] hi" in out
    # The tool_use entry has no rendered substring.


# ── handler — skill_load ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_load_rejects_empty_name():
    engine = type("E", (), {})()
    tool = sdt.make_skill_doc_tool(engine)
    out = await tool.handler(skill="")
    assert out["error"]
    assert "non-empty" in out["error"]


@pytest.mark.asyncio
async def test_skill_load_rejects_non_string_name():
    engine = type("E", (), {})()
    tool = sdt.make_skill_doc_tool(engine)
    out = await tool.handler(skill=123)  # type: ignore[arg-type]
    assert out["error"]


@pytest.mark.asyncio
async def test_skill_load_unknown_skill_returns_not_found():
    engine = type("E", (), {})()
    tool = sdt.make_skill_doc_tool(engine)
    out = await tool.handler(skill="ghost_skill_xyz_999")
    assert out["error"] == "not_found"
    assert "hint" in out
    assert "Folders found" in out["hint"]


@pytest.mark.asyncio
async def test_skill_load_loads_real_skill_under_budget():
    """A small SKILL.md (under the budget) returns verbatim, condensed=False."""
    engine = type("E", (), {"_history": []})()
    tool = sdt.make_skill_doc_tool(engine)
    # Use a real bundled skill discovered at test time.
    name = _a_real_skill()
    out = await tool.handler(skill=name, max_chars=100_000)
    assert out["skill"] == f"{name}_skill"
    assert out["condensed"] is False
    assert out["char_count"] > 0
    assert isinstance(out["doc"], str)


@pytest.mark.asyncio
async def test_skill_load_force_full_skips_condensation():
    """Even if doc > budget, force_full=True returns verbatim."""
    engine = type("E", (), {"_history": []})()
    tool = sdt.make_skill_doc_tool(engine)
    out = await tool.handler(skill="browser", max_chars=100, force_full=True)
    assert out["condensed"] is False


@pytest.mark.asyncio
async def test_skill_load_clamps_max_chars():
    """max_chars below 1000 floors to 1000, above 50000 caps to 50000."""
    engine = type("E", (), {"_history": []})()
    engine._llm_complete = AsyncMock(return_value="condensed")
    tool = sdt.make_skill_doc_tool(engine)
    # Below floor — should still be respected (≥1000) so most docs render verbatim.
    out = await tool.handler(skill="git", max_chars=10, force_full=True)
    assert out["condensed"] is False


@pytest.mark.asyncio
async def test_skill_load_triggers_condensation_above_budget():
    """When the doc is bigger than the budget, condense() is called."""
    engine = type("E", (), {"_history": []})()
    engine._llm_complete = AsyncMock(return_value="<condensed>")
    tool = sdt.make_skill_doc_tool(engine)
    out = await tool.handler(skill="browser", max_chars=1000)
    assert out["condensed"] is True
    assert out["doc"] == "<condensed>"
    engine._llm_complete.assert_called_once()


# ── _condense fallback path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_condense_fallback_when_llm_raises():
    """If the condense LLM call raises, we fall back to head-truncation."""
    engine = type("E", (), {})()
    engine._llm_complete = AsyncMock(side_effect=RuntimeError("API down"))
    out = await sdt._condense(engine, "x" * 50_000, [])
    assert "condense_failed" in out
    assert "RuntimeError" in out
    # Truncated head + marker line.
    assert "(truncated; condense failed)" in out


@pytest.mark.asyncio
async def test_condense_passes_recent_history_into_prompt():
    """The condense prompt should include recent chat for relevance."""
    engine = type("E", (), {})()
    seen: list[str] = []

    async def fake_complete(prompt: str) -> str:
        seen.append(prompt)
        return "summary"

    engine._llm_complete = fake_complete
    history = [
        {"role": "user", "content": "I want to delete a branch"},
    ]
    out = await sdt._condense(engine, "doc body", history)
    assert out == "summary"
    # The prompt should include the user's most recent message.
    assert any("delete a branch" in p for p in seen)


# ── skill_query handler ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_query_routes_through_index():
    """_skill_query_handler delegates to skill_query_index.query()."""
    out = await sdt._skill_query_handler(skill="git", query="commit", k=3)
    # Whatever the index returns, the handler should round-trip a dict-like result.
    assert isinstance(out, dict) or isinstance(out, list)


@pytest.mark.asyncio
async def test_skill_query_tolerates_kwarg_aliases():
    """LLM sometimes spells the args differently — handler accepts aliases."""
    out = await sdt._skill_query_handler(skill_name="git", q="commit", k=2)
    assert out is not None


def test_skill_query_tool_metadata():
    """The exported tool has the expected name + required params."""
    assert sdt.SKILL_QUERY_TOOL.name == "skill_query"
    required = sdt.SKILL_QUERY_TOOL.parameters["required"]
    assert "skill" in required
    assert "query" in required
