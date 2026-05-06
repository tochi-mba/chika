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
ALLOWED_CROSS_IMPORTS: set[tuple[str, str]] = {
    # ── Spotify ────────────────────────────────────────────────────
    # The OAuth callback endpoint is an HTTP-server-level route — has
    # to live in api/routes/ to be mounted on the FastAPI app. It pulls
    # the skill's connection + oauth helpers to drive the flow. Moving
    # this into the skill folder would require the skill to register
    # its own routes (a bigger architectural change).
    ("api/routes/spotify.py",      "chika.skills.spotify_skill.connection"),
    ("api/routes/spotify.py",      "chika.skills.spotify_skill.oauth"),

    # The settings-store invalidates the in-memory token cache when
    # the share-across-profiles flag flips, so the next read picks up
    # the right bucket without a process restart. Importing the
    # cache directly is the simplest path; alternatives (event
    # subscriptions, signals) would be heavier for one cache clear.
    ("api/settings_store.py",      "chika.skills.spotify_skill.oauth"),

    # ── Browser ────────────────────────────────────────────────────
    # The extension's session manager is per-tab + cross-cut state —
    # the API extension router calls into it to reflect tab state and
    # forward heartbeats. Moving the singleton into api/ would split
    # the browser skill's runtime; leaving it in the skill keeps that
    # module's contract intact.
    ("api/routes/extension.py",    "chika.skills.browser_skill.extension_manager"),
    ("api/routes/extension.py",    "chika.skills.browser_skill.extension_manager.extension_manager"),

    # ── Pet ────────────────────────────────────────────────────────
    # The /api/profile/<name>/pet endpoints reset / copy per-profile
    # pet memory when the user switches pets. The two helpers live
    # next to the rest of the pet-state logic in the skill; the
    # alternative (event-driven invalidation) would require a heavier
    # bus subscription for two one-shot ops.
    ("api/routes/pets.py",         "chika.skills.pet_skill.clear_pet_memory"),
    ("api/routes/pets.py",         "chika.skills.pet_skill.copy_pet_memory"),

    # ── CLI subcommands ────────────────────────────────────────────
    # ``chika spotify connect|status|disconnect|share`` and
    # ``/spotify`` slash command live in chika/_cli/ because they're
    # part of the global CLI dispatch table. They drive the same
    # connection.py the Vue / extension UIs do; importing it directly
    # is the only way to share that logic.
    ("chika/_cli/spotify.py",      "chika.skills.spotify_skill.connection"),

    # ── Engine wiring ──────────────────────────────────────────────
    # The session manager + server know about every skill because
    # they HOST the skill registry — this is the canonical
    # registration site. A registry-pattern refactor (skills
    # auto-register via entry points) would remove these, but until
    # then the engine wiring has to import each skill builder
    # explicitly.
    ("api/server.py",              "chika.skills.browser_skill.extension_manager"),
    ("api/server.py",              "chika.skills.browser_skill.extension_manager.extension_manager"),
    ("api/server.py",              "chika.skills.browser_skill.set_frontend_push"),
    ("api/session_manager.py",     "chika.skills.browser_skill.BROWSER_SKILL"),
    ("api/session_manager.py",     "chika.skills.git_skill.GIT_SKILL"),
    ("api/session_manager.py",     "chika.skills.pet_skill.build_pet_skill"),
    ("api/session_manager.py",     "chika.skills.plan_skill.build_plan_skill"),
    ("api/session_manager.py",     "chika.skills.question_skill.build_question_skill"),
    ("api/session_manager.py",     "chika.skills.shell_skill.build_shell_skill"),
    ("api/session_manager.py",     "chika.skills.spotify_skill.SPOTIFY_SKILL"),
    ("api/session_manager.py",     "chika.skills.verify_skill.build_verify_skill"),
    ("api/session_manager.py",     "chika.skills.web_app_skill.WEB_APP_SKILL"),
    ("api/session_manager.py",     "chika.skills.web_skill.WEB_SKILL"),

    # ── Cross-skill integration tests ──────────────────────────────
    # These tests genuinely exercise multiple skills together (the
    # skill-gate enforces a contract across every skill, the e2e
    # engine stub drives the plan + browser + shell skills as one).
    # Both stay at the top level by design.
    ("tests/test_skill_gate.py",      "chika.skills.plan_skill._make_plan_tools"),
    ("tests/test_skill_gate.py",      "chika.skills.web_app_skill.scaffold_tool"),
    ("tests/test_skill_gate.py",      "chika.skills.web_app_skill.scaffold_tool._scaffold_web_app"),
    ("tests/test_e2e_engine_stub.py", "chika.skills.plan_skill.build_plan_skill"),
}


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
