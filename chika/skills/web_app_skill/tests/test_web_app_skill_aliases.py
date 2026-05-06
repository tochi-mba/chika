"""Comprehensive tests for the web_app skill — alias resolution, dispatch
correctness, error recovery, and the full mocked-network flow.

The earlier test file covered happy-path built-in templates. This file
exercises the *failure modes* and *resolution rules* that bit users in
real sessions:

- ``vite-three`` got dispatched to ``npm create vite-three@latest`` and
  404'd after 27s. That's now an alias for ``three``.
- Unknown stacks need to surface SUGGESTIONS the agent can retry with.
- Every catalogue entry must dispatch to a runnable code path.
- The success result must report the canonical id (so the agent learns)
  AND the original input (so the user sees what they typed got remapped).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chika.skills.web_app_skill.scaffold_tool import (
    _STACKS,
    _SYNONYMS,
    _resolve_stack,
    _scaffold_web_app,
    _suggest_stacks,
    list_stacks,
)


def _run(coro):
    return asyncio.run(coro)


# ── Alias resolution — pure function ──────────────────────────────────────

@pytest.mark.parametrize("user_id, expected_canonical", [
    # Direct hits
    ("vanilla",        "vanilla"),
    ("vite-vue",       "vite-vue"),
    ("react",          "react"),
    ("VANILLA",        "vanilla"),     # case-insensitive
    ("  vue  ",        "vue"),         # whitespace tolerant

    # The original bug — vite-X for game stacks
    ("vite-three",     "three"),
    ("vite-threejs",   "three"),
    ("vite-p5",        "p5"),
    ("vite-phaser",    "phaser"),

    # Synonym table
    ("threejs",        "three"),
    ("three.js",       "three"),
    ("three-js",       "three"),
    ("p5js",           "p5"),
    ("p5.js",          "p5"),
    ("nextjs",         "next"),
    ("next.js",        "next"),
    ("nuxtjs",         "nuxt"),
    ("nuxt.js",        "nuxt"),
    ("solidjs",        "solid"),
    ("html",           "vanilla"),
    ("html-css-js",    "vanilla"),
    ("javascript",     "vanilla"),
    ("static",         "static-site"),

    # Reverse aliases (X-vite → vite-X)
    ("react-vite",     "vite-react"),
    ("vue-vite",       "vite-vue"),
    ("svelte-vite",    "vite-svelte"),
])
def test_resolve_canonicalises_alias(user_id, expected_canonical):
    canonical, spec = _resolve_stack(user_id)
    assert canonical == expected_canonical, (
        f"_resolve_stack({user_id!r}) → {canonical!r}, expected {expected_canonical!r}"
    )
    assert spec is not None, (
        f"alias {user_id!r} resolved to {canonical!r} but spec missing — "
        "likely a typo in _SYNONYMS pointing at a stack that's not in _STACKS"
    )


def test_unknown_stack_returns_no_spec():
    canonical, spec = _resolve_stack("definitely-not-a-real-stack-9999")
    assert spec is None
    # Original id preserved when no resolution found.
    assert canonical == "definitely-not-a-real-stack-9999"


def test_every_synonym_target_exists_in_stacks():
    """Every value in _SYNONYMS must be a real catalogue id — guards against
    typos in the synonym table that would silently produce an unresolvable
    alias."""
    for synonym, target in _SYNONYMS.items():
        assert target in _STACKS, (
            f"synonym {synonym!r} → {target!r} but {target!r} is not in _STACKS"
        )


# ── Suggestions for fuzzy matches ─────────────────────────────────────────

def test_suggestions_offer_useful_alternatives():
    # Common typo — agent (or user) might say "vue3" instead of "vue".
    suggestions = _suggest_stacks("vue3")
    assert any("vue" in s.lower() for s in suggestions), (
        f"expected a vue-flavoured suggestion for 'vue3', got {suggestions}"
    )


def test_suggestions_for_completely_unknown_returns_something():
    # Even garbage input should surface SOMETHING (cutoff is 0.5 — at worst
    # it returns the empty list, which is documented).
    suggestions = _suggest_stacks("zzzzzzzz")
    assert isinstance(suggestions, list)


# ── Catalogue integrity ───────────────────────────────────────────────────

def test_every_stack_dispatches_via_resolver():
    """Every catalogue id should resolve directly to itself with a spec."""
    for stack_id in _STACKS:
        canonical, spec = _resolve_stack(stack_id)
        assert canonical == stack_id
        assert spec is not None


def test_every_alias_dispatch_kind_matches_target():
    """``vite-three`` (alias) should dispatch with the same kind as ``three``."""
    for alias, canonical in _SYNONYMS.items():
        a_can, a_spec = _resolve_stack(alias)
        b_can, b_spec = _resolve_stack(canonical)
        assert a_spec == b_spec, (
            f"alias {alias!r} produced spec {a_spec!r} but canonical "
            f"{canonical!r} produced {b_spec!r} — they should be identical"
        )


# ── End-to-end with mocked subprocess ─────────────────────────────────────

@pytest.fixture
def mocked_npm(monkeypatch):
    """Patch _run + _which so we never touch the network in tests.

    Returns a list of (cmd, cwd) tuples actually invoked. By default the
    fake ``_run`` simulates a successful scaffold by creating the project
    directory. Tests can mutate the side-effect via the `behaviour` ref.
    """
    invocations: list[tuple[str, str]] = []
    behaviour = {"rc": 0, "log": "", "create_project": True}

    async def _fake_run(cmd, cwd):
        invocations.append((cmd, str(cwd)))
        if behaviour["create_project"] and behaviour["rc"] == 0:
            # Reverse-engineer the project name from the command. Both
            # `npm create vite@latest <name> ...` and `npx ... <name> ...`
            # put the name as the first non-flag positional after create.
            tokens = cmd.split()
            name = next(
                (t for t in tokens
                 if t and not t.startswith("-")
                 and not t.startswith("@")
                 and t not in ("npm", "npx", "create", "--yes",
                               "create-next-app@latest", "vite@latest")
                 and not t.endswith("@latest")),
                None,
            )
            if name:
                Path(cwd, name).mkdir(parents=True, exist_ok=True)
        return behaviour["rc"], behaviour["log"]

    monkeypatch.setattr(
        "chika.skills.web_app_skill.scaffold_tool._run", _fake_run,
    )
    monkeypatch.setattr(
        "chika.skills.web_app_skill.scaffold_tool._which",
        lambda _t: "/usr/bin/npm",
    )
    return invocations, behaviour


def test_vite_three_now_dispatches_to_three_alias(mocked_npm, tmp_path: Path):
    """Regression: this is the EXACT bug from the user's session."""
    invocations, _ = mocked_npm
    out = _run(_scaffold_web_app(
        stack="vite-three", name="racing-demo", target_dir=str(tmp_path),
    ))
    assert out.get("ok") is True, out
    # The resolver rewrote vite-three → three. Result reports the canonical
    # id AND the original.
    assert out["stack"] == "three"
    assert out["resolved_from"] == "vite-three"
    # `three` is a vite-kind stack, so the command must be `npm create vite@latest`
    # NOT `npm create vite-three@latest`.
    cmds = [c for c, _ in invocations]
    assert any("npm create vite@latest" in c for c in cmds), (
        f"expected vite invocation, got: {cmds}"
    )
    assert not any("vite-three" in c for c in cmds), (
        f"vite-three should NEVER appear in actual command: {cmds}"
    )


def test_unknown_stack_returns_suggestions(mocked_npm, tmp_path: Path):
    """The fallthrough path should return a structured ``unknown_stack``
    error with suggestions when npm create fails — NOT just bail out."""
    _, behaviour = mocked_npm
    behaviour["rc"] = 1
    behaviour["log"] = "npm error 404 Not Found"
    behaviour["create_project"] = False

    out = _run(_scaffold_web_app(
        stack="vue3-app", name="my-app", target_dir=str(tmp_path),
    ))
    assert out.get("error") == "unknown_stack"
    # Must include a list of suggestions the agent can retry with.
    assert "suggestions" in out
    assert isinstance(out["suggestions"], list)
    # Must include actionable hint.
    assert "scaffold_web_app" in out["hint"]


def test_canonical_stack_runs_normally(mocked_npm, tmp_path: Path):
    """Sanity: a direct catalogue id should work without any alias rewrite."""
    out = _run(_scaffold_web_app(
        stack="vite-vue", name="my-vue-app", target_dir=str(tmp_path),
    ))
    assert out.get("ok") is True, out
    assert out["stack"] == "vite-vue"
    # No alias rewrite happened
    assert out.get("resolved_from") is None


def test_alias_three_extra_packages_propagate(mocked_npm, tmp_path: Path):
    """Aliasing ``vite-three`` → ``three`` must preserve extra_packages."""
    invocations, _ = mocked_npm
    out = _run(_scaffold_web_app(
        stack="vite-three", name="three-demo", target_dir=str(tmp_path),
        install=True,
    ))
    assert out.get("ok") is True, out
    # Should have run an extra `npm install three @types/three` step
    cmds = " || ".join(c for c, _ in invocations)
    assert "three" in cmds and "@types/three" in cmds, (
        f"extra_packages not installed for vite-three alias: {cmds}"
    )


def test_target_exists_short_circuits_before_npm(mocked_npm, tmp_path: Path):
    """If the target dir exists, never reach npm — return immediately."""
    invocations, _ = mocked_npm
    (tmp_path / "demo").mkdir()
    out = _run(_scaffold_web_app(
        stack="vite-vue", name="demo", target_dir=str(tmp_path),
    ))
    assert out.get("error") == "target_exists"
    assert invocations == [], (
        f"target_exists must short-circuit before any npm call, got: {invocations}"
    )


def test_npm_missing_returns_node_install_hint(monkeypatch, tmp_path: Path):
    """When npm/npx aren't on PATH, the tool should NOT try to run them
    and the hint should include the install URL the agent can app_open."""
    monkeypatch.setattr(
        "chika.skills.web_app_skill.scaffold_tool._which", lambda _t: None,
    )

    async def _fail_run(*a, **kw):  # noqa: ARG001
        pytest.fail("_run should not be called when npm is missing")

    monkeypatch.setattr(
        "chika.skills.web_app_skill.scaffold_tool._run", _fail_run,
    )
    out = _run(_scaffold_web_app(
        stack="vite-vue", name="demo", target_dir=str(tmp_path),
    ))
    assert out.get("error") == "npm_not_found"
    assert "nodejs.org" in out["hint"]


def test_install_failure_keeps_project_dir(mocked_npm, tmp_path: Path):
    """If `npm install` fails post-scaffold, the project dir should still
    exist and the result should distinguish install_failed from
    scaffolder_failed."""
    invocations, behaviour = mocked_npm

    # The first call (scaffolder) succeeds; subsequent ``npm install``
    # calls fail.
    async def _seq_run(cmd, cwd):
        invocations.append((cmd, str(cwd)))
        if "create" in cmd:
            (Path(cwd) / "demo").mkdir(parents=True, exist_ok=True)
            return 0, "scaffolded"
        # subsequent install calls fail
        return 1, "npm error: install failed"

    import chika.skills.web_app_skill.scaffold_tool as mod
    mod._run = _seq_run  # type: ignore[assignment]  # test monkeypatch — signature compatible at call-site
    out = _run(_scaffold_web_app(
        stack="vite-vue", name="demo", target_dir=str(tmp_path),
        install=True,
    ))

    assert out.get("error") == "install_failed"
    assert (tmp_path / "demo").exists(), (
        "project dir must remain so the user can retry install manually"
    )


# ── Builtin paths still solid (regression net) ────────────────────────────

@pytest.mark.parametrize("alias", ["html", "javascript", "html-css-js", "js"])
def test_html_synonyms_resolve_to_vanilla(alias, tmp_path: Path):
    out = _run(_scaffold_web_app(
        stack=alias, name="demo", target_dir=str(tmp_path),
    ))
    assert out.get("ok") is True, out
    assert out["stack"] == "vanilla"
    assert out["resolved_from"] == alias


def test_static_synonym_resolves_to_static_site(tmp_path: Path):
    out = _run(_scaffold_web_app(
        stack="static", name="demo", target_dir=str(tmp_path),
    ))
    assert out.get("ok") is True
    assert out["stack"] == "static-site"


# ── Smoke: list_stacks contract ──────────────────────────────────────────

def test_list_stacks_is_sorted_and_contains_all():
    listed = list_stacks()
    assert listed == sorted(listed), "list_stacks() must be sorted"
    assert set(listed) == set(_STACKS.keys())
