"""Tests for the planning-intent heuristic.

The heuristic is the kind of thing that's easy to over-fit to a
small set of phrasings, so the test suite is exhaustive and grouped
by category. Each category has both POSITIVE cases (should trigger)
and NEGATIVE cases (should NOT trigger), so adding a new pattern
that breaks an old assumption gets caught immediately.
"""
from __future__ import annotations

import pytest

from chika.core.intent import detect_planning_intent


# ── Positive: build / create / scaffold ─────────────────────────────────


@pytest.mark.parametrize("text", [
    "make me a vue dashboard with three charts",
    "build me a CLI tool that monitors a folder",
    "create me an API for managing inventory",
    "generate a TypeScript SDK for our REST API",
    "scaffold a new Next.js project with auth",
    "spin up a FastAPI server with two endpoints",
    "set up a CI pipeline for this repo",
])
def test_make_me_pattern(text):
    assert detect_planning_intent(text) is not None


@pytest.mark.parametrize("text", [
    "I want to build a workflow tool that fans out tasks",
    "I need to make a settings UI for my admin panel",
    "I'd like to create a chat interface using websockets",
    "i want a dashboard that shows usage over time",
    "I want to scaffold something quick to test the UX",
    "i need a chrome extension for tracking time",
])
def test_i_want_pattern(text):
    assert detect_planning_intent(text) is not None


@pytest.mark.parametrize("text", [
    "help me build a Vue 3 dashboard with charts",
    "can you help me design a clean settings flow",
    "help me scaffold a NestJS backend",
    "help me refactor the auth module to use JWT instead of sessions",
    "help me implement a rate limiter",
])
def test_help_me_pattern(text):
    assert detect_planning_intent(text) is not None


@pytest.mark.parametrize("text", [
    "refactor the auth module to use JWT",
    "rewrite this test to use pytest fixtures",
    "migrate the codebase from Vue 2 to Vue 3",
    "port this Flask app to FastAPI",
    "convert this monolith into modules",
])
def test_refactor_pattern(text):
    assert detect_planning_intent(text) is not None


@pytest.mark.parametrize("text", [
    "add a settings tab for keyboard shortcuts",
    "add a feature for exporting plans as JSON",
    "add an endpoint that returns the user's profile",
    "add a test for the new oauth flow",
    "add a component for the audit log viewer",
])
def test_add_feature_pattern(text):
    assert detect_planning_intent(text) is not None


@pytest.mark.parametrize("text", [
    "let's build a small caching layer",
    "lets create a markdown editor",
    "let's design the new permissions UX",
    "let's set up a staging environment",
    "I'm trying to build a recommendation engine",
    "i'm trying to create an offline-first PWA",
])
def test_lets_build_pattern(text):
    assert detect_planning_intent(text) is not None


@pytest.mark.parametrize("text", [
    "build a Vue dashboard for our metrics",
    "create an API client for Spotify",
    "make a CLI for monitoring our nodes",
    "scaffold a small TypeScript library",
    "implement a JSON schema validator",
    "design a clean settings flow for the extension",
])
def test_imperative_pattern(text):
    assert detect_planning_intent(text) is not None


# ── Negative: questions, lookups, fixes ─────────────────────────────────


@pytest.mark.parametrize("text", [
    "what does git rebase do?",
    "what is the difference between a generator and an iterator",
    "what's the maximum context length for opus 4.7",
    "why does pytest emit those warnings",
    "how do I install Playwright on Windows",
    "how does our auth flow work",
    "is there a way to disable the pet quips",
    # Skill-named test cases ("are there any tests for the X_skill")
    # are contributed back here from each skill's own INTENT_CASES so
    # the skill name string stays inside the skill folder. See
    # ``test_skill_contributed_negative_cases`` below.
    "can the agent see my chat history",
    "explain the role of the workflow engine",
    "show me the current settings",
    "tell me which provider is active",
    "describe how the skill summary cache works",
    "list every tool the agent has",
    "find the function that handles auth",
    "search for files that mention 'compaction'",
    "look up the GitHub API rate limit",
    "where is the .env file",
    "when was this branch last merged",
    "who pushed the last commit on main",
    "which version of Vue is bundled",
])
def test_questions_skip_planning(text):
    assert detect_planning_intent(text) is None


@pytest.mark.parametrize("text", [
    "fix the bug in oauth.py where state is dropped",
    "fix this regex it's not matching apostrophes",
    "repair the broken import in engine.py",
    "patch the failing tests in test_codegen_scripts",
    "debug why the WebSocket disconnects after 30s",
])
def test_fix_overrides_build(text):
    assert detect_planning_intent(text) is None


@pytest.mark.parametrize("text", [
    "run the tests",
    "run the playwright suite once",
    "execute the migration script",
    "invoke the spotify_search tool with 'SZA'",
])
def test_run_overrides_build(text):
    assert detect_planning_intent(text) is None


@pytest.mark.parametrize("text", [
    "fix the typo in README.md",
    "create a PR with this typo fix",      # build pattern but typo override
    "add a fix for the comma in line 42",  # add pattern but cosmetic override
    "build me a regex that catches typos", # contains 'typo' → skip
])
def test_cosmetic_overrides(text):
    assert detect_planning_intent(text) is None


@pytest.mark.parametrize("text", [
    "revert the last commit",
    "undo my changes to engine.py",
    "rollback the migration",
    "restore the old version of config.py",
])
def test_revert_overrides_build(text):
    assert detect_planning_intent(text) is None


# ── Edge cases ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "",                # empty
    "   \n  \t   ",    # whitespace
    "ty",              # one word
    "thanks!",         # one word + punct
    "ok do it",        # 3 words but no build pattern
    "yes",
    "no",
    "continue",
])
def test_short_or_empty_skips(text):
    assert detect_planning_intent(text) is None


def test_none_input_returns_none():
    """``detect_planning_intent(None)`` shouldn't crash — returns None."""
    assert detect_planning_intent(None) is None  # type: ignore[arg-type]


def test_hint_is_a_non_empty_string():
    """Sanity: when it fires, the hint is a real string (not '' or True)."""
    hint = detect_planning_intent("build me a small dashboard")
    assert isinstance(hint, str)
    assert len(hint) > 50
    assert "plan" in hint.lower()


def test_hint_is_deterministic():
    """Same input → same output. (Important for the 'no LLM call'
    promise — the heuristic must be repeatable.)"""
    text = "build me a small dashboard with three charts"
    h1 = detect_planning_intent(text)
    h2 = detect_planning_intent(text)
    assert h1 == h2


def test_case_insensitivity():
    """A user shouting 'BUILD ME A DASHBOARD' still gets the hint."""
    assert detect_planning_intent("BUILD ME A DASHBOARD WITH AUTH") is not None
    assert detect_planning_intent("Build Me A Dashboard With Auth") is not None


# ── Skill-contributed test cases ──────────────────────────────────────────
#
# Skills contribute their own positive/negative cases via
# ``INTENT_CASES`` in their ``__init__.py``. The central test walks
# them via ``iter_skill_intent_cases`` so any skill-name strings
# (e.g. "are there any tests for the foo_skill") stay INSIDE the
# skill folder — preserves the strict skill-isolation contract while
# keeping coverage complete.


def _skill_intent_cases(kind: str) -> list[str]:
    """Aggregate a flat list of every shipped skill's contributed
    cases for the given kind ("positive" or "negative")."""
    from chika.skills import iter_skill_intent_cases
    out: list[str] = []
    for _name, cases in iter_skill_intent_cases():
        for text in cases.get(kind, []):
            if isinstance(text, str) and text.strip():
                out.append(text)
    return out


@pytest.mark.parametrize("text", _skill_intent_cases("negative"))
def test_skill_contributed_negative_cases(text):
    """Every skill-contributed negative case must NOT trigger the
    heuristic. Drop a string into a skill's ``INTENT_CASES["negative"]``
    and it joins this suite automatically."""
    assert detect_planning_intent(text) is None, (
        f"Skill-contributed negative case unexpectedly triggered: {text!r}"
    )


@pytest.mark.parametrize("text", _skill_intent_cases("positive"))
def test_skill_contributed_positive_cases(text):
    """Every skill-contributed positive case must trigger the
    heuristic. Skills add domain-specific build phrasings here."""
    assert detect_planning_intent(text) is not None, (
        f"Skill-contributed positive case did NOT trigger: {text!r}"
    )


# ── Engine-side wiring ───────────────────────────────────────────────────


def test_engine_latest_user_text_returns_empty_for_empty_history():
    """``_latest_user_text`` returns '' when there's no user message
    yet — the per-turn prompt builder uses this on the first turn."""
    from unittest.mock import MagicMock

    from chika.core.engine import ChikaEngine
    fake = MagicMock(spec=ChikaEngine)
    fake._history = []
    assert ChikaEngine._latest_user_text(fake) == ""


def test_engine_latest_user_text_finds_most_recent_user_msg():
    """When history has both user + assistant messages, the helper
    skips assistants and returns the LATEST user content."""
    from unittest.mock import MagicMock

    from chika.core.engine import ChikaEngine
    fake = MagicMock(spec=ChikaEngine)
    fake._history = [
        {"role": "user", "content": "first thing"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "build me a dashboard"},
        {"role": "assistant", "content": "got it"},
    ]
    assert ChikaEngine._latest_user_text(fake) == "build me a dashboard"


def test_engine_latest_user_text_handles_multipart_content():
    """When the user message is image+text (multipart), the helper
    flattens the text parts so the heuristic can still inspect it."""
    from unittest.mock import MagicMock

    from chika.core.engine import ChikaEngine
    fake = MagicMock(spec=ChikaEngine)
    fake._history = [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"data": "..."}},
            {"type": "text",  "text": "build me a UI for this"},
        ],
    }]
    assert "build me a UI" in ChikaEngine._latest_user_text(fake)
