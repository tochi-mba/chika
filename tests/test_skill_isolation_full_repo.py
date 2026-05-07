"""Strict full-repo skill isolation — no skill names outside the skill folder.

Stronger than ``test_skill_isolation.py`` (which only checks Python
imports). This test scans **every** text file in the repo — Vue, JS,
TS, HTML, CSS, Python, Markdown — and fails if a skill's name appears
outside that skill's own folder in any of the patterns below.

What counts as a violation
--------------------------

We flag, for each shipped skill name (e.g. ``spotify``):

  1. ``chika.skills.spotify_skill`` — Python module path
  2. ``chika/skills/spotify_skill`` — filesystem path
  3. ``spotify_skill`` as a bare token
  4. ``SPOTIFY_<X>`` — UPPERCASE constants (event types, env vars)
  5. ``Spotify<X>`` — PascalCase identifiers (Pydantic models, Vue components)
  6. ``"spotify_<x>"`` / ``"spotify"`` — string literals in dispatch tables
  7. ``/api/spotify/`` / ``/auth/spotify`` — URL path components

Each occurrence is checked: if the file lives outside the corresponding
skill folder AND outside the documented exceptions list, the test
fails with a precise pointer.

Why this exists
---------------

The drop-in skill contract is only as strong as its enforcement. The
Python-imports test catches ~80% of drift; this catches the other
20% — Vue components hardcoding ``chika/skills/spotify_skill/ui/``,
docs referencing ``pet_skill.clear_pet_memory``, hardcoded URLs in
the extension popup, frontend tab labels that name a skill, etc.

Exceptions
----------

The exception list is intentionally narrow. New entries require a
clear "this can't be moved into the skill" justification — most of
the time the right answer is to push the reference INSIDE the skill,
not to grow the list.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "chika" / "skills"

# Directories we never scan (vendored, generated, build outputs, VCS,
# and the runtime ``data/`` tree which is gitignored everywhere
# except ``data/settings.json`` — user-specific state, not source).
SKIP_DIRS = {
    "node_modules", "dist", "build", ".venv", "venv",
    "__pycache__", ".git", "playwright-report", "test-results",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage",
    ".claude",  # Claude Code worktrees — different snapshot of the repo
    "egg-info", ".eggs",
    "release",  # PyInstaller / installer build artefacts
    "data",     # Runtime state (skill summaries, session logs, profiles,
                # BM25 index). Gitignored except settings.json which is
                # exempted explicitly below.
}

# File extensions we DO scan. Markdown is included so doc drift is
# caught — but see ``DOC_EXEMPT_PATHS`` for legit doc cases.
SCAN_EXTENSIONS = {
    ".py", ".vue", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".html", ".css", ".scss", ".sh", ".ps1",
    ".json", ".md", ".yml", ".yaml", ".toml", ".ini",
}

# Files that LEGITIMATELY mention every skill name by design — they
# document or enumerate the skills as a registry. Allowlisted with
# justification. Paths are POSIX-style relative to the repo root.
EXEMPT_PATHS: set[str] = {
    # Documentation — by design enumerates the architecture, including
    # which skills ship out of the box. These are READ by humans, not
    # imported by code.
    "README.md",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "DECISIONS.md",

    # Tests that ENFORCE the skill-isolation contract
    "tests/test_skill_isolation.py",
    "tests/test_skill_isolation_full_repo.py",
    "tests/test_skill_discovery.py",
    "tests/test_dynamic_skills.py",

    # Auto-generated files. Each derives its content from the skill
    # registry via a generator script — the generator script itself
    # is a per-skill walker (already exempt via EXEMPT_DIR_PREFIXES).
    # The generated output is a checked-in artefact, not source.
    "frontend/src/lib/api-client.js",       # gen_api_client.py walks routes
    "frontend/src/lib/toolSummaries.js",    # gen_tool_summaries.py walks tools
    "frontend/src/types/api.d.ts",          # gen_api_types.py walks Pydantic
    "frontend/src/types/events.d.ts",       # gen_event_types.py walks events
    "extension/lib/event-types.js",         # ditto for the extension
    "api/readme_html.py",                   # auto-rendered REST docs page

}

# Whole-directory exemptions — for files that legitimately walk EVERY
# shipped skill as part of their purpose. Cross-skill infrastructure
# scripts that *are* the registry walker are the only entries here;
# everything else has to migrate into a skill folder.
EXEMPT_DIR_PREFIXES: tuple[str, ...] = (
    # Generator scripts — these tools regenerate per-skill artefacts
    # (SKILL.md tool-reference appendix, TS event-type catalogue,
    # skill-summary JSON cache). They're allowed to enumerate skills
    # because that's what they're FOR.
    "scripts/sync_skill_docs.py",
    "scripts/gen_event_types.py",
    "scripts/regenerate_skill_summaries.py",
)


def _shipped_skill_names() -> list[str]:
    """Discover skill names by walking the skills directory.

    Mirrors ``chika.skills.list_known_skill_names`` but is purely
    filesystem-based so this test doesn't depend on the module import
    succeeding (catches very early bootstrap failures too)."""
    out: list[str] = []
    for d in SKILLS_DIR.iterdir():
        if not d.is_dir() or not d.name.endswith("_skill"):
            continue
        out.append(d.name[:-len("_skill")])
    return sorted(out)


def _is_inside(path: Path, root: Path) -> bool:
    rp = path.resolve()
    return root.resolve() in rp.parents or rp == root.resolve()


def _file_exempt(rel: str) -> bool:
    if rel in EXEMPT_PATHS:
        return True
    for prefix in EXEMPT_DIR_PREFIXES:
        if rel == prefix or rel.startswith(prefix):
            return True
    return False


def _candidate_files() -> list[Path]:
    """Every file we should scan — filtered by extension + skip dirs."""
    out: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SCAN_EXTENSIONS:
            continue
        out.append(path)
    return out


@pytest.fixture(scope="module")
def skill_names() -> list[str]:
    return _shipped_skill_names()


@pytest.fixture(scope="module")
def violations(skill_names: list[str]) -> list[tuple[str, str, int, str]]:
    """``[(file, skill, line_no, line_excerpt), ...]`` for every
    occurrence of a skill's package path outside that skill's folder."""
    found: list[tuple[str, str, int, str]] = []
    skill_folders = {n: SKILLS_DIR / f"{n}_skill" for n in skill_names}

    # Patterns per skill. Multiple alternations cover every PRECISE
    # shape a skill name leaks into source/text files. We deliberately
    # do NOT match the bare lowercase token (``git``, ``web``) or
    # generic PascalCase — both create massive false positives on
    # common English words (Git/GitHub/GitRunner, WebSocket, PlanType,
    # PetCompanion). The patterns below are all distinctive enough to
    # be unambiguous signals of skill drift.
    patterns: dict[str, re.Pattern] = {}
    # Skills with names that overlap common English words. We can't
    # use the UPPERCASE pattern for them either — ``GIT_RUNNER``,
    # ``WEB_FETCH``, ``PLAN_TYPE``, ``PET_BUBBLES`` all appear in
    # legitimate non-skill code (env vars, top-level constants). For
    # these skills we only flag the precise module-path pattern.
    AMBIGUOUS = {"git", "web", "plan", "pet", "shell"}
    for name in skill_names:
        # Skill names with non-alphanum chars (``web_app`` has an
        # underscore) need careful escaping.
        n = re.escape(name)
        nu = re.escape(name.upper())
        alts: list[str] = [
            # Python module + filesystem paths — always precise.
            r"chika\.skills\." + n + r"_skill",
            r"chika/skills/" + n + r"_skill",
            n + r"_skill",
        ]
        # UPPERCASE constants and URL paths only for skills whose
        # name doesn't collide with common English words.
        if name not in AMBIGUOUS:
            alts.extend([
                # ``SPOTIFY_AUTH_CHANGED`` / ``CHIKA_SPOTIFY_CLIENT_ID``.
                nu + r"_[A-Z][A-Z0-9_]*",
                # ``/api/spotify/``, ``/auth/spotify``.
                r"/(?:api|auth|ws|skill)/" + n,
            ])
        patterns[name] = re.compile(
            r"(?<![A-Za-z0-9_])(?:" + r"|".join(alts) + r")(?![A-Za-z0-9_])"
        )

    for path in _candidate_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if _file_exempt(rel):
            continue

        # Files inside a skill folder are exempt — they may freely
        # reference their own skill (and rarely a sibling skill, which
        # the cross-skill rule below catches).
        for name, folder in skill_folders.items():
            if _is_inside(path, folder):
                # Inside *some* skill folder — don't flag references
                # to its own name. We still want to catch sibling
                # cross-references, but that's the same isolation
                # signal as the test_skill_isolation.py Python test
                # already enforces.
                break
        else:
            # Outside every skill folder — full scan.
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                for skill_name, pattern in patterns.items():
                    if pattern.search(line):
                        found.append((rel, skill_name, line_no, line.strip()[:160]))
    return found


def test_no_skill_package_paths_outside_skill_folders(violations):
    """Drop-in skill contract — no file outside a skill's own folder
    may reference the skill by its package path. If a reference is
    needed, push the consumer INTO the skill (route, UI, CLI handler),
    or use the public discovery API in chika.skills."""
    if not violations:
        return
    msg_lines = [
        "Skill-isolation drift — these references reach into a skill",
        "by its package/folder name from outside the skill's folder.",
        "Fix: push the consumer into the skill folder, OR use the",
        "discovery API in chika/skills/__init__.py:",
        "",
    ]
    for rel, skill, line_no, excerpt in violations:
        msg_lines.append(f"  {rel}:{line_no}  ({skill}_skill)")
        msg_lines.append(f"    {excerpt}")
    pytest.fail("\n".join(msg_lines))


def test_every_shipped_skill_has_an_init_with_required_exports(skill_names):
    """Sanity check: every shipped skill folder declares the
    discovery contract. Catches a folder rename / deletion before
    it cascades into other failures."""
    for name in skill_names:
        init_py = SKILLS_DIR / f"{name}_skill" / "__init__.py"
        assert init_py.exists(), f"{name}_skill missing __init__.py"
        text = init_py.read_text(encoding="utf-8")
        assert "SKILL_NAME" in text, f"{name}_skill missing SKILL_NAME"
        assert "build_skill" in text, f"{name}_skill missing build_skill"
