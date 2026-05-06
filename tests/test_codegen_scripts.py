"""Tests for the auto-gen / drift-check scripts under ``scripts/``.

Each generator:
  - produces deterministic output (same inputs → same bytes mod date stamp)
  - has a working ``--check`` mode
  - covers its expected file targets

Plus the asset-name SOT, the brand parity checker, the skill→tool
drift checker, and the scaffolders.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── gen_event_types.py ───────────────────────────────────────────────


def test_gen_event_types_check_passes_on_committed_files():
    """The committed ``frontend/.../events.d.ts`` and
    ``extension/lib/event-types.js`` must be up-to-date with
    api/models.py. CI gate."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gen_event_types.py"), "--check"],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"event types stale. Run: python scripts/gen_event_types.py\n"
        f"stderr: {proc.stderr}"
    )


def test_gen_event_types_emits_typescript_and_jsdoc(tmp_path, monkeypatch):
    """Smoke: re-run the generator into actual files and verify the
    expected types appear."""
    from scripts import gen_event_types as gen
    ts = gen.generate_ts()
    js = gen.generate_jsdoc()

    # TS contract
    assert "export type EventTypeName" in ts
    assert "export interface TokenEvent" in ts
    assert "export interface ToolCallEvent" in ts
    assert "export type EngineEvent" in ts

    # JSDoc contract
    assert "@typedef {Object} TokenEvent" in js
    assert "@property {string} text" in js or "@property {string} step_id" in js
    assert "@typedef" in js


def test_gen_event_types_normalize_strips_date():
    """``--check`` ignores the date line so re-running on a different
    day doesn't fail."""
    from scripts import gen_event_types as gen
    a = "// Generated:  2026-01-01\nrest"
    b = "// Generated:  2026-12-31\nrest"
    assert gen._normalize(a) == gen._normalize(b)


# ── check_brand_parity.py ────────────────────────────────────────────


def test_brand_parity_passes_on_repo():
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_brand_parity.py")],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )
    assert proc.returncode == 0, f"brand parity drift: {proc.stderr}"


def test_brand_parity_extracts_signature(tmp_path):
    from scripts.check_brand_parity import extract_petal_signature
    text = '<path d="M 0,-58 C 13,-44 19,-22 0,-6 C -19,-22 -13,-44 0,-58 Z"/>'
    sig = extract_petal_signature(text)
    assert sig is not None
    nums = sig.split(",")
    # Should include the canonical numerics
    assert "0" in nums
    assert "-58" in nums
    assert "13" in nums
    assert "-44" in nums


def test_brand_parity_returns_none_for_unrelated_text():
    from scripts.check_brand_parity import extract_petal_signature
    assert extract_petal_signature("hello world") is None


def test_brand_parity_picks_up_python_constants():
    """The CLI rasteriser stores the path as Python constants — the
    extractor must reconstruct the SVG numeric sequence from them."""
    text = """
        _TIP_Y     = -58.0
        _INNER_Y   = -6.0
        _CP1       = (13.0, -44.0)
        _CP2       = (19.0, -22.0)
    """
    from scripts.check_brand_parity import extract_petal_signature
    sig = extract_petal_signature(text)
    assert sig is not None
    nums = sig.split(",")
    assert "-58" in nums
    assert "-44" in nums
    # Mirror values for the second cubic
    assert "-19" in nums or "-13" in nums


# ── regenerate_skill_summaries.py ────────────────────────────────────


def test_regenerate_skill_summaries_check_mode_runs():
    """``--check`` should exit cleanly (0 or 1) without crashing."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "regenerate_skill_summaries.py"),
         "--check"],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    # 0 = clean, 1 = drift detected. Both are "ran successfully".
    # Anything else is a crash.
    assert proc.returncode in (0, 1), (
        f"regenerator crashed: {proc.returncode}\n{proc.stderr}"
    )


def test_regenerate_skill_summaries_dry_run_no_provider_needed():
    """Dry-run must not require an API key."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "regenerate_skill_summaries.py"),
         "--dry-run"],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
        env={**__import__("os").environ, "ANTHROPIC_API_KEY": "",
             "OPENAI_API_KEY": ""},
    )
    # Either "all fresh" (0) or "would regen N" (also 0)
    assert proc.returncode == 0


def test_regenerate_skill_summaries_unknown_skill_errors():
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "regenerate_skill_summaries.py"),
         "--skill", "nonexistent_skill", "--dry-run"],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=15,
    )
    assert proc.returncode == 2


# ── installers/asset_names.py ────────────────────────────────────────


def test_asset_names_returns_correct_filenames():
    from installers.asset_names import expected_asset_name
    assert expected_asset_name("windows_installer", "2.0.5") == "chika-setup-2.0.5.exe"
    assert expected_asset_name("macos_installer", "2.0.5")   == "Chika-2.0.5.pkg"
    assert expected_asset_name("linux_deb", "2.0.5")         == "chika_2.0.5_all.deb"
    assert expected_asset_name("linux_universal", "2.0.5")   is None
    assert expected_asset_name("not_a_real_kind", "1.0.0")    is None


def test_asset_names_cli_smoke():
    proc = subprocess.run(
        [sys.executable, "-m", "installers.asset_names",
         "windows_installer", "2.0.5"],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "chika-setup-2.0.5.exe"


def test_asset_names_consistent_with_update_module():
    """The update module's _expected_asset_name MUST agree with the SOT."""
    from chika._cli.update import _expected_asset_name
    from installers.asset_names import expected_asset_name
    for kind in ("windows_installer", "macos_installer", "linux_deb", "linux_universal"):
        assert _expected_asset_name(kind, "1.2.3") == expected_asset_name(kind, "1.2.3")


# ── check_skill_tool_drift.py ────────────────────────────────────────


def test_skill_tool_drift_check_runs_clean_or_reports():
    """Smoke: drift check exits 0 (clean) or 1 (drift) without crashing."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_skill_tool_drift.py")],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )
    assert proc.returncode in (0, 1)


def test_skill_tool_drift_extracts_only_underscored_tokens():
    from scripts.check_skill_tool_drift import _claimed_tools_from_skill_md
    text = "use the `shell_exec` tool for `git_commit`. The agent reads things."
    out = _claimed_tools_from_skill_md(text)
    assert "shell_exec" in out
    assert "git_commit" in out
    # Single-word tokens are excluded (too many false positives in prose)
    assert "agent" not in out


# ── scaffold.py ──────────────────────────────────────────────────────


def test_scaffold_skill_creates_package(tmp_path, monkeypatch):
    """End-to-end: scaffold a skill into a tmp repo + verify files."""
    monkeypatch.setattr(
        "scripts.scaffold.REPO_ROOT", tmp_path,
    )
    (tmp_path / "chika" / "skills").mkdir(parents=True)
    (tmp_path / "tests").mkdir()

    from scripts.scaffold import scaffold_skill
    rc = scaffold_skill("MyTest")
    assert rc == 0
    pkg = tmp_path / "chika" / "skills" / "mytest_skill"
    assert (pkg / "__init__.py").is_file()
    assert (pkg / "SKILL.md").is_file()
    assert (tmp_path / "tests" / "test_mytest_skill.py").is_file()
    # Re-running must abort
    rc2 = scaffold_skill("MyTest")
    assert rc2 == 1


def test_scaffold_tool_creates_module(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.scaffold.REPO_ROOT", tmp_path,
    )
    (tmp_path / "chika" / "tools").mkdir(parents=True)
    (tmp_path / "tests").mkdir()

    from scripts.scaffold import scaffold_tool
    rc = scaffold_tool("foo_bar")
    assert rc == 0
    assert (tmp_path / "chika" / "tools" / "foo_bar_tool.py").is_file()
    assert (tmp_path / "tests" / "test_foo_bar_tool.py").is_file()


def test_scaffold_event_modifies_models_and_routing(tmp_path, monkeypatch):
    """scaffold event reads + appends to api/models.py and event_routing.py."""
    monkeypatch.setattr(
        "scripts.scaffold.REPO_ROOT", tmp_path,
    )
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "models.py").write_text(
        "from enum import Enum\n"
        "class EventType(str, Enum):\n"
        "    EXISTING = \"existing\"\n"
        "\n# Map from EventType value → strict Pydantic model.\n"
        "_TYPED_MODELS = {}\n",
        encoding="utf-8",
    )
    (tmp_path / "api" / "event_routing.py").write_text(
        "from api.models import EventType\n\n"
        "CLI_EVENTS: frozenset[str] = frozenset({\n"
        "    EventType.EXISTING.value,\n"
        "})\n",
        encoding="utf-8",
    )

    from scripts.scaffold import scaffold_event
    rc = scaffold_event("my_new_event")
    assert rc == 0

    models_text = (tmp_path / "api" / "models.py").read_text(encoding="utf-8")
    assert 'MY_NEW_EVENT = "my_new_event"' in models_text
    assert "class MyNewEventEvent" in models_text

    routing_text = (tmp_path / "api" / "event_routing.py").read_text(encoding="utf-8")
    assert "EventType.MY_NEW_EVENT.value" in routing_text


def test_scaffold_adr_appends_template(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.scaffold.REPO_ROOT", tmp_path)
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(
        "# Existing\n\n"
        "## ADR-1: Some prior decision\n\n"
        "Body\n",
        encoding="utf-8",
    )
    from scripts.scaffold import scaffold_adr
    rc = scaffold_adr("Test ADR")
    assert rc == 0
    text = decisions.read_text(encoding="utf-8")
    assert "## ADR-2: Test ADR" in text
    assert "**Status:**" in text


def test_scaffold_slug_normalises_input():
    from scripts.scaffold import _slug
    assert _slug("My Cool Skill") == "my_cool_skill"
    assert _slug("foo-bar") == "foo_bar"
    assert _slug("123abc") == "_123abc"  # leading digit guarded
    assert _slug("...") == ""


def test_scaffold_invalid_name_returns_error_code(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.scaffold.REPO_ROOT", tmp_path)
    from scripts.scaffold import scaffold_skill
    rc = scaffold_skill("...")
    assert rc == 2


# ── gen_openapi_client.py ────────────────────────────────────────────


def test_gen_openapi_client_runs_clean():
    """Smoke: the generator runs without crashing (uses fallback if
    api.server import fails)."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gen_openapi_client.py")],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    assert proc.returncode == 0, f"openapi-codegen crashed:\n{proc.stderr}"


def test_gen_openapi_client_emits_files():
    """After running, the expected output files exist."""
    types_path = REPO_ROOT / "frontend" / "src" / "types" / "api.d.ts"
    client_path = REPO_ROOT / "frontend" / "src" / "lib" / "api-client.js"
    assert types_path.is_file()
    assert client_path.is_file()
    # Header banner
    assert "AUTO-GENERATED" in types_path.read_text(encoding="utf-8")
    assert "AUTO-GENERATED" in client_path.read_text(encoding="utf-8")


def test_gen_openapi_client_check_mode_after_regen():
    """Just-regenerated files must pass --check."""
    # Run regen first
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gen_openapi_client.py")],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=60,
    )
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gen_openapi_client.py"),
         "--check"],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    assert proc.returncode == 0, f"check failed after regen:\n{proc.stderr}"
