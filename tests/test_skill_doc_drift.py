"""Doc-drift guard: every registered tool name must appear in its skill's
SKILL.md, AND the auto-generated tool-reference appendix must be in sync
with the live registry.

A SKILL.md that lies about its tool surface is exactly the bug we
shipped against — agent reads the doc, calls a kwarg the doc shows but
the tool doesn't accept, crash. These two tests fail loudly when that
state is regressed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from api.session_manager import session_manager


_REPO = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO / "chika" / "skills"

# Build the registry once. ``__skill_doc_drift__`` is a throwaway session id.
_eng = session_manager.get_or_create("__skill_doc_drift__")


def _skill_md_path(skill_name: str) -> Path:
    """Resolve ``<skill>_skill/SKILL.md`` (or ``<skill>/SKILL.md``)."""
    for cand in (f"{skill_name}_skill", skill_name):
        path = _SKILLS_DIR / cand / "SKILL.md"
        if path.is_file():
            return path
    raise AssertionError(f"no SKILL.md found for skill {skill_name!r}")


@pytest.mark.parametrize(
    "skill_name,tool_name",
    [
        (skill_name, tool.name)
        for skill_name, skill in _eng._skills._skills.items()
        for tool in skill.tools
    ],
    ids=lambda val: str(val),
)
def test_every_registered_tool_appears_in_its_skill_md(skill_name, tool_name):
    """Each tool must be NAMED in its SKILL.md (any prose mention counts).
    Catches the case where a tool is added to the registry but the doc is
    forgotten — the agent then has to guess the tool surface."""
    md = _skill_md_path(skill_name).read_text(encoding="utf-8")
    assert f"`{tool_name}`" in md, (
        f"skill {skill_name!r}: tool `{tool_name}` is registered but does "
        f"not appear in its SKILL.md. Run "
        f"`python scripts/sync_skill_docs.py` to regenerate the auto "
        f"appendix, OR add prose mentioning {tool_name!r}."
    )


def test_skill_doc_appendix_is_in_sync_with_registry():
    """Run the sync script in --check mode — fails if any SKILL.md's
    auto-generated tool reference is stale."""
    result = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "sync_skill_docs.py"), "--check"],
        capture_output=True, text=True,
        cwd=str(_REPO),
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        "SKILL.md auto-reference is out of date. Run "
        "`python scripts/sync_skill_docs.py` to regenerate.\n\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
