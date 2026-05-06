"""Tests for the web_app skill — built-in templates + tool registration.

Network-backed scaffolders (Vite, Next, etc.) are NOT exercised here — they
require npm and would slow CI. The dispatch logic is tested via stack
catalogue inspection + the no-network ``vanilla`` / ``static-site`` paths.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chika.skills.web_app_skill import WEB_APP_SKILL, list_stacks
from chika.skills.web_app_skill.scaffold_tool import (
    _STACKS,
    _scaffold_web_app,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else \
        asyncio.run(coro)


# ── Skill registration ────────────────────────────────────────────────────

def test_skill_exposes_scaffold_tool():
    names = {t.name for t in WEB_APP_SKILL.tools}
    assert "scaffold_web_app" in names


def test_stack_catalogue_has_known_families():
    stacks = set(list_stacks())
    # Built-ins
    assert "vanilla" in stacks
    assert "static-site" in stacks
    # Vite family
    for v in ("vite-vue", "vite-react", "vite-svelte", "vite-solid",
              "vite-vanilla-ts", "vue", "react", "svelte"):
        assert v in stacks, f"missing stack: {v}"
    # Full-stack
    for fs in ("next", "nuxt", "astro", "sveltekit", "remix"):
        assert fs in stacks, f"missing stack: {fs}"
    # Game / canvas
    for g in ("three", "p5", "phaser"):
        assert g in stacks, f"missing stack: {g}"


def test_each_stack_entry_is_dispatchable():
    """Every stack entry must declare a kind and the matching keys."""
    for sid, spec in _STACKS.items():
        kind = spec.get("kind")
        assert kind in ("builtin", "vite", "cmd"), f"bad kind for {sid}: {kind!r}"
        if kind == "builtin":
            assert "template" in spec, f"{sid}: builtin needs 'template'"
        elif kind == "vite":
            assert "vite_template" in spec, f"{sid}: vite needs 'vite_template'"
        elif kind == "cmd":
            assert "cmd_template" in spec, f"{sid}: cmd needs 'cmd_template'"
            assert "{name}" in spec["cmd_template"], (
                f"{sid}: cmd_template must use {{name}} placeholder"
            )


# ── Built-in template scaffolding ─────────────────────────────────────────

def test_vanilla_scaffold_writes_runnable_files(tmp_path: Path):
    out = _run(_scaffold_web_app(
        stack="vanilla", name="demo", target_dir=str(tmp_path),
    ))
    assert out.get("ok") is True, out
    project = Path(out["project"])
    assert project.is_dir()
    # Required files
    for fname in ("index.html", "styles.css", "main.js", "README.md", ".gitignore"):
        assert (project / fname).exists(), f"missing {fname}"
    # HTML references the CSS + JS
    html = (project / "index.html").read_text(encoding="utf-8")
    assert 'href="styles.css"' in html
    assert 'src="main.js"' in html
    # Project name was substituted
    assert "demo" in html


def test_static_site_scaffold_has_three_pages(tmp_path: Path):
    out = _run(_scaffold_web_app(
        stack="static-site", name="my-site", target_dir=str(tmp_path),
    ))
    assert out.get("ok") is True, out
    project = Path(out["project"])
    for fname in ("index.html", "about.html", "contact.html",
                  "styles.css", "main.js", "README.md"):
        assert (project / fname).exists(), f"missing {fname}"
    # Cross-page nav present
    for page in ("index.html", "about.html", "contact.html"):
        body = (project / page).read_text(encoding="utf-8")
        assert "about.html" in body and "contact.html" in body, (
            f"{page} missing nav links"
        )


def test_target_exists_returns_clean_error(tmp_path: Path):
    # Pre-create the project directory so the tool refuses.
    (tmp_path / "demo").mkdir()
    out = _run(_scaffold_web_app(
        stack="vanilla", name="demo", target_dir=str(tmp_path),
    ))
    assert out.get("error") == "target_exists"
    assert "hint" in out


def test_name_sanitisation_strips_unsafe_chars(tmp_path: Path):
    # Name with spaces/punctuation should produce a safe folder name.
    out = _run(_scaffold_web_app(
        stack="vanilla", name="My Cool App!", target_dir=str(tmp_path),
    ))
    assert out.get("ok") is True, out
    project = Path(out["project"])
    # Each unsafe char was replaced with '-' — exactly the chars present in
    # the input were either kept (alnum) or replaced. We only assert the
    # folder exists and contains no unsafe chars.
    assert project.is_dir()
    assert all(c.isalnum() or c in "-_" for c in project.name)


def test_empty_name_errors_cleanly(tmp_path: Path):
    out = _run(_scaffold_web_app(
        stack="vanilla", name="!!!", target_dir=str(tmp_path),
    ))
    assert "error" in out
    assert "alphanumerics" in out["error"]


def test_empty_stack_errors_cleanly(tmp_path: Path):
    out = _run(_scaffold_web_app(
        stack="", name="x", target_dir=str(tmp_path),
    ))
    assert "error" in out


def test_returned_next_step_mentions_live_server_for_vanilla(tmp_path: Path):
    """The vanilla scaffold should hand the agent the live_server next step."""
    out = _run(_scaffold_web_app(
        stack="vanilla", name="demo", target_dir=str(tmp_path),
    ))
    assert "live_server" in (out.get("next_step") or ""), (
        f"expected live_server in next_step, got {out.get('next_step')!r}"
    )


# ── Network paths — dispatch only, mocked subprocess ──────────────────────

@pytest.mark.parametrize("stack,expected_template", [
    ("vite-vue",    "vue"),
    ("vite-react",  "react"),
    ("vue",         "vue-ts"),     # alias
    ("react",       "react-ts"),   # alias
    ("svelte",      "svelte-ts"),  # alias
    ("vite-svelte-ts", "svelte-ts"),
])
def test_vite_stack_resolves_correct_template(stack, expected_template):
    spec = _STACKS[stack]
    assert spec["kind"] == "vite"
    assert spec["vite_template"] == expected_template


def test_unknown_stack_falls_through_to_npm_create(monkeypatch, tmp_path: Path):
    """An unrecognised stack id should attempt `npm create <stack>@latest`."""
    seen = {}

    async def _fake_run(cmd, cwd):
        seen["cmd"] = cmd
        # Pretend the scaffolder ran successfully and created the dir.
        (cwd / "totally-fake-stack-app").mkdir()
        return 0, "ok"

    monkeypatch.setattr(
        "chika.skills.web_app_skill.scaffold_tool._run", _fake_run,
    )
    monkeypatch.setattr(
        "chika.skills.web_app_skill.scaffold_tool._which",
        lambda _t: "/usr/bin/npm",
    )

    out = _run(_scaffold_web_app(
        stack="totally-fake-stack",
        name="totally-fake-stack-app",
        target_dir=str(tmp_path),
    ))
    assert out.get("ok") is True, out
    assert "totally-fake-stack" in seen["cmd"]
    assert "@latest" in seen["cmd"]
