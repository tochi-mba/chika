"""Skill-isolation contract test.

Each skill under ``chika/skills/<skill>/`` must be self-contained: the
code that *implements* the skill (handlers, OAuth flows, helpers,
private modules) lives inside that folder, and the rest of the
codebase only depends on either:

  1. **Public tool names** — string references like ``"spotify_play"``
     in tool dispatch tables. Unavoidable; expected.
  2. **The skill's top-level package** — e.g.,
     ``import chika.skills.spotify_skill`` to discover the registered
     tools. Done by the skill registry; expected.
  3. **A small allowlist** of cross-module imports that genuinely
     belong at the system boundary (HTTP routes that need access to
     skill internals, settings-store cache invalidation, etc.).

Anything else — a random module reaching INTO a skill's submodules
— signals architectural drift. The test enumerates every Python file
that imports skill internals and fails if a new one shows up that
isn't in :data:`ALLOWED_CROSS_IMPORTS`.

Why bother:

  - Keeps PRs reviewable: the skill diff stays inside one folder.
  - Makes "disable a skill" trivially safe: nothing outside that
    folder will silently break.
  - Future-proofs the per-skill test pattern (tests live next to the
    skill they test).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "chika" / "skills"

# ── Allowlist ───────────────────────────────────────────────────────────
#
# Each entry is ``(importing_file_relative_to_repo, skill_module_imported,
# justification)``. New entries require sign-off — the rule of thumb is
# "could this code live INSIDE the skill folder instead?" If yes, move
# it; only if no, allowlist it.
ALLOWED_CROSS_IMPORTS: set[tuple[str, str]] = set()
# Intentionally empty. The drop-in skill contract (see
# ``chika/skills/_context.py``) means every per-skill surface — routes,
# websockets, CLI, settings keys, UI components, hot-reload hooks —
# lives inside the skill folder and plugs in via discovery. If you
# find yourself wanting to add an entry here, that's a signal to
# refactor the consumer to use one of the discovery APIs in
# ``chika/skills/__init__.py`` instead:
#
#   - ``register_routes()``       ← server walks for HTTP routes
#   - ``register_websocket(app)`` ← server walks for WS endpoints
#   - ``register_cli()``          ← CLI dispatch walks
#   - ``SKILL_SETTINGS``          ← settings_store walks
#   - ``on_setting_changed`` / ``on_env_changed`` ← subscription bus
#   - ``SKILL_UI``                ← frontend / extension walk for tabs
#   - ``get_skill_module(name)``  ← test-side public lookup helper
#
# Skill-specific tests (kwarg aliases, scaffold dispatch, etc.) live
# INSIDE the skill folder so they're naturally exempt — the test
# walker only flags imports from OUTSIDE the skill folder.


def _all_skill_dirs() -> list[Path]:
    """Every skill folder — defined as a subdir of chika/skills/ that
    contains a ``SKILL.md``. Avoids picking up ``__pycache__``,
    ``__init__.py`` siblings, etc."""
    return [
        d for d in SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    ]


def _module_name(skill_dir: Path) -> str:
    """``chika/skills/spotify_skill/`` → ``chika.skills.spotify_skill``."""
    return f"chika.skills.{skill_dir.name}"


def _imports_from_file(path: Path) -> list[str]:
    """Every fully-qualified import target in a Python file.

    Returns module strings: ``import a.b.c`` → ``["a.b.c"]``;
    ``from a.b import c`` → ``["a.b.c"]``. ``from . import x`` and
    relative imports return their resolved name as best we can.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    except SyntaxError:
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            # ``from chika.skills.spotify_skill import oauth``
            # → tracked as ``chika.skills.spotify_skill.oauth`` (the
            # specific submodule), since that's the targeted depth.
            base = node.module
            for alias in node.names:
                # ``from chika.skills.x import y`` — we record both
                # the parent (``chika.skills.x``) and the targeted
                # module (``chika.skills.x.y``) so test reports point
                # to the deepest violation.
                out.append(base)
                out.append(f"{base}.{alias.name}")
    return out


def _file_is_inside(path: Path, *parents: Path) -> bool:
    """``path`` lives under any of ``parents``."""
    rp = path.resolve()
    return any(p.resolve() in rp.parents for p in parents)


@pytest.fixture(scope="module")
def violations() -> list[tuple[str, str]]:
    """Walk every .py under repo, flag (file, skill_module) pairs that
    import a skill from outside its folder."""
    skill_dirs = _all_skill_dirs()
    skill_modules = {_module_name(d): d for d in skill_dirs}

    found: list[tuple[str, str]] = []

    excluded_top_level = {
        "node_modules", "dist", "build", ".venv", "venv",
        "__pycache__", ".git", "frontend", "extension", "docs",
        "playwright-report", "test-results",
        # ``.claude`` holds Claude Code worktrees — copies of the repo
        # at different points in time. Their imports aren't part of
        # this checkout's contract.
        ".claude",
    }

    for py in REPO_ROOT.rglob("*.py"):
        # Skip vendored / generated / non-Python directories.
        if any(part in excluded_top_level for part in py.parts):
            continue

        # Files INSIDE any skill folder may freely import their own
        # skill's internals (and other skills, occasionally — the
        # browser skill calls into shell, etc.). Tests living next to
        # a skill are also exempt.
        if any(_file_is_inside(py, d) for d in skill_modules.values()):
            continue

        imports = _imports_from_file(py)
        for imp in imports:
            for mod_name in skill_modules:
                if imp == mod_name:
                    # Importing the top-level package is allowed
                    # (skill registry / discovery).
                    continue
                if imp.startswith(mod_name + "."):
                    rel = py.relative_to(REPO_ROOT).as_posix()
                    found.append((rel, imp))
    return found


def test_no_undocumented_skill_internals_imports(violations):
    """Every cross-skill import must either be inside the skill or in
    the documented allowlist. New violations fail CI with a clear
    suggestion."""
    undocumented = [
        (file, mod)
        for (file, mod) in violations
        if (file, mod) not in ALLOWED_CROSS_IMPORTS
    ]
    if undocumented:
        msg_lines = [
            "Skill-isolation drift — these imports reach INTO a skill",
            "from outside its folder without an allowlist entry:",
            "",
        ]
        for file, mod in undocumented:
            msg_lines.append(f"  {file}  →  {mod}")
        msg_lines.extend([
            "",
            "Pick one:",
            "  1. Move the importing code INSIDE the skill folder.",
            "     (Preferred — keeps the skill self-contained.)",
            "  2. Add to ALLOWED_CROSS_IMPORTS in this file with a",
            "     comment explaining why it can't live in the skill.",
        ])
        pytest.fail("\n".join(msg_lines))


def test_allowlist_entries_are_actually_used(violations):
    """Stale allowlist entries are bugs in the other direction —
    they document a constraint that no longer exists. Drop them so
    future readers don't think the constraint is still load-bearing."""
    actual = set(violations)
    stale = ALLOWED_CROSS_IMPORTS - actual
    if stale:
        pytest.fail(
            "ALLOWED_CROSS_IMPORTS has stale entries (these imports "
            "no longer exist; remove the entry):\n  "
            + "\n  ".join(f"{f}  →  {m}" for f, m in sorted(stale))
        )


def test_every_skill_has_a_skill_md():
    """Sanity: a folder under chika/skills/ either contains a
    SKILL.md (it's a real skill) or is excluded from this test's
    enumeration. No half-skills."""
    for d in SKILLS_DIR.iterdir():
        if d.name in {"__pycache__", "__init__.py"}:
            continue
        if d.is_file():
            continue
        assert (d / "SKILL.md").exists(), (
            f"{d.name} looks like a skill folder but has no SKILL.md. "
            "Add one or move the dir out of chika/skills/."
        )


def test_skill_local_tests_live_inside_skill_folders():
    """Per the convention: skill-specific tests live next to the
    skill they test (chika/skills/<skill>/tests/), not in the
    top-level tests/ tree. We don't ENFORCE this strictly — some
    integration tests at the top level legitimately exercise multiple
    skills — but we DO require that any folder named ``tests/`` under
    a skill exists in at least one skill (proves the convention is
    in use)."""
    has_local_tests = any(
        (d / "tests").is_dir()
        for d in _all_skill_dirs()
    )
    assert has_local_tests, (
        "No skill has a chika/skills/<skill>/tests/ folder. "
        "Skill-local tests are the project convention — see "
        "chika/skills/spotify_skill/tests/ for the canonical shape."
    )
